"""Servidor MCP stateless. O MRTR termina a resposta; não há canal de volta."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Context, MCPServer, RequestStateSecurity
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from mcp_types import (
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    ClientCapabilities,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitationCapability,
    FormElicitationCapability,
    InputRequiredResult,
    MissingRequiredClientCapabilityErrorData,
)
from pydantic import BaseModel

from servidor_mcp.dominio import MSG_ELICITACAO, MSG_SEM_ALTERNATIVA, Catalogo

RAIZ = Path(__file__).resolve().parents[2]
CATALOGO = Catalogo(RAIZ / "dados")
CHAVE_ESCOLHA = "escolha_de_sala"


class SalaOut(BaseModel):
    id: str
    nome: str
    capacidade: int
    recursos: list[str]


class ListaDeSalas(BaseModel):
    salas: list[SalaOut]


class ConflitoOut(BaseModel):
    id: str
    inicio: str
    fim: str
    responsavel: str


class Disponibilidade(BaseModel):
    sala: str
    livre: bool
    conflitos: list[ConflitoOut]


class ReservaOut(BaseModel):
    reserva: str | None = None
    reservado: bool = True
    sala: str | None = None
    inicio: str | None = None
    fim: str | None = None
    responsavel: str | None = None
    politica: str | None = None
    motivo: str | None = None


def carregar_chave() -> bytes:
    bruto = os.environ.get("REQUEST_STATE_SECRET", "").strip()
    if not bruto:
        raise SystemExit("REQUEST_STATE_SECRET ausente. Gere com python -c \"import secrets; print(secrets.token_hex(32))\"")
    try:
        chave = bytes.fromhex(bruto)
    except ValueError:
        chave = bruto.encode("utf-8")
    if len(chave) < 32:
        raise SystemExit("REQUEST_STATE_SECRET precisa de pelo menos 32 bytes")
    return chave


def criar_servidor() -> MCPServer:
    return MCPServer(
        "central-de-salas",
        version="1.0.0",
        request_state_security=RequestStateSecurity(keys=[carregar_chave()], ttl=600),
    )


mcp = criar_servidor()


def _exigir(sala: str, inicio: str, fim: str) -> None:
    erro = CATALOGO.validar(sala, inicio, fim)
    if erro:
        raise ToolError(erro)


def _reserva_out(reserva_id: str, sala: str, inicio: str, fim: str, responsavel: str) -> ReservaOut:
    return ReservaOut(
        reserva=reserva_id,
        reservado=True,
        sala=sala,
        inicio=inicio,
        fim=fim,
        responsavel=responsavel,
        politica=CATALOGO.politica_versao,
        motivo=None,
    )


def _recusa() -> ReservaOut:
    return ReservaOut(reservado=False, motivo="recusado")


def _declara_form(ctx: Context) -> bool:
    capacidades = ctx.client_capabilities
    if capacidades is None or capacidades.elicitation is None:
        return False
    elicitation = capacidades.elicitation
    return elicitation.form is not None or elicitation.url is None


def _erro_sem_form() -> MCPError:
    dados = MissingRequiredClientCapabilityErrorData(
        required_capabilities=ClientCapabilities(
            elicitation=ElicitationCapability(form=FormElicitationCapability())
        )
    )
    return MCPError(
        code=MISSING_REQUIRED_CLIENT_CAPABILITY,
        message="Client did not declare the form elicitation capability required by reservar_sala",
        data=dados.model_dump(by_alias=True, mode="json", exclude_none=True),
    )


def _schema_alternativas(alternativas: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "sala": {
                "type": "string",
                "enum": alternativas,
                "title": "Sala",
                "description": "Sala alternativa escolhida",
            }
        },
        "required": ["sala"],
    }


def _selar_pedido(sala: str, inicio: str, fim: str, responsavel: str, alternativas: list[str]) -> str:
    return json.dumps(
        {
            "sala": sala,
            "inicio": inicio,
            "fim": fim,
            "responsavel": responsavel,
            "alternativas": alternativas,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _ler_acao(resposta: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(resposta, dict):
        acao = str(resposta.get("action") or "")
        conteudo = resposta.get("content") or {}
    else:
        acao = str(getattr(resposta, "action", "") or "")
        conteudo = getattr(resposta, "content", None) or {}
    if hasattr(conteudo, "model_dump"):
        conteudo = conteudo.model_dump()
    if not isinstance(conteudo, dict):
        conteudo = {}
    return acao, conteudo


def _concluir_retry(ctx: Context) -> ReservaOut:
    bruto = ctx.request_state
    if not bruto:
        raise ToolError("requestState ausente")
    try:
        selado = json.loads(bruto)
    except json.JSONDecodeError as exc:
        raise ToolError("requestState ilegivel") from exc
    respostas = ctx.input_responses or {}
    if CHAVE_ESCOLHA in respostas:
        resposta = respostas[CHAVE_ESCOLHA]
    elif len(respostas) == 1:
        resposta = next(iter(respostas.values()))
    else:
        raise ToolError("inputResponses sem a escolha")
    acao, conteudo = _ler_acao(resposta)
    if acao in {"decline", "cancel"}:
        return _recusa()
    if acao != "accept":
        raise ToolError("acao de elicitation desconhecida")
    escolhida = str(conteudo.get("sala") or "")
    alternativas = list(selado["alternativas"])
    if escolhida not in alternativas:
        raise ToolError("sala fora das alternativas oferecidas")
    sala = str(selado["sala"])
    inicio = str(selado["inicio"])
    fim = str(selado["fim"])
    responsavel = str(selado["responsavel"])
    _exigir(escolhida, inicio, fim)
    if CATALOGO.conflitos(escolhida, inicio, fim):
        raise ToolError(MSG_SEM_ALTERNATIVA)
    criada = CATALOGO.reservar(escolhida, inicio, fim, responsavel)
    return _reserva_out(criada.id, escolhida, inicio, fim, responsavel)


@mcp.tool(description="Lista todas as salas com capacidade e recursos.")
def listar_salas() -> ListaDeSalas:
    return ListaDeSalas(salas=[SalaOut.model_validate(item) for item in CATALOGO.listar()])


@mcp.tool(description="Diz se uma sala esta livre no intervalo, e quais reservas conflitam.")
def consultar_disponibilidade(sala: str, inicio: str, fim: str) -> Disponibilidade:
    _exigir(sala, inicio, fim)
    conflitos = CATALOGO.conflitos(sala, inicio, fim)
    return Disponibilidade(
        sala=sala,
        livre=not conflitos,
        conflitos=[ConflitoOut.model_validate(item.como_conflito()) for item in conflitos],
    )


@mcp.tool(description="Reserva uma sala. Se o intervalo estiver ocupado, pergunta qual alternativa usar.")
def reservar_sala(
    sala: str, inicio: str, fim: str, responsavel: str, ctx: Context
) -> ReservaOut | InputRequiredResult:
    if ctx.input_responses:
        return _concluir_retry(ctx)
    _exigir(sala, inicio, fim)
    if CATALOGO.conflitos(sala, inicio, fim):
        alternativas = CATALOGO.alternativas(sala, inicio, fim)
        if not alternativas:
            raise ToolError(MSG_SEM_ALTERNATIVA)
        if not _declara_form(ctx):
            raise _erro_sem_form()
        return InputRequiredResult(
            input_requests={
                CHAVE_ESCOLHA: ElicitRequest(
                    params=ElicitRequestFormParams(
                        message=MSG_ELICITACAO,
                        mode="form",
                        requested_schema=_schema_alternativas(alternativas),
                    )
                )
            },
            request_state=_selar_pedido(sala, inicio, fim, responsavel, alternativas),
        )
    criada = CATALOGO.reservar(sala, inicio, fim, responsavel)
    return _reserva_out(criada.id, sala, inicio, fim, responsavel)


@mcp.resource(
    "politica://uso",
    mime_type="text/markdown",
    name="politica-de-uso",
    description="Politica de uso das salas de reuniao.",
)
def politica_de_uso() -> str:
    return CATALOGO.politica_texto


class LogRequests:
    """Registra no stderr cada POST, inclusive os que o SDK rejeita na borda."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        corpo = b""
        while True:
            mensagem = await receive()
            if mensagem["type"] != "http.request":
                break
            corpo += mensagem.get("body", b"")
            if not mensagem.get("more_body", False):
                break
        _registrar(corpo)
        enviado = False

        async def replay() -> dict[str, Any]:
            nonlocal enviado
            if not enviado:
                enviado = True
                return {"type": "http.request", "body": corpo, "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay, send)


def _registrar(corpo: bytes) -> None:
    metodo = "-"
    identificador: object = "-"
    traceparent = ""
    try:
        pedido = json.loads(corpo)
    except json.JSONDecodeError:
        pedido = None
    if isinstance(pedido, dict):
        metodo = str(pedido.get("method") or "-")
        identificador = pedido.get("id", "-")
        params = pedido.get("params")
        meta = params.get("_meta") if isinstance(params, dict) else None
        if isinstance(meta, dict) and meta.get("traceparent"):
            traceparent = str(meta["traceparent"])
    print(
        f"mcp method={metodo} id={identificador} traceparent={traceparent}",
        file=sys.stderr,
        flush=True,
    )


def aplicacao():
    return LogRequests(
        mcp.streamable_http_app(
            streamable_http_path="/mcp",
            json_response=True,
            stateless_http=True,
        )
    )

