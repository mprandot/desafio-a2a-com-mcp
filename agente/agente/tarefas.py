"""Máquina da Task. A ponte mora em pausar e retomar."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from typing import Any

from mcp.types import ElicitResult, InputRequiredResult

from agente.host_mcp import HostMCP

TERMINAIS = {"TASK_STATE_COMPLETED", "TASK_STATE_CANCELED", "TASK_STATE_FAILED"}


@dataclass
class Pausa:
    request_state: str
    chave: str
    argumentos: dict[str, str]
    alternativas: list[str]
    linha: str


@dataclass
class Task:
    id: str
    context_id: str
    state: str
    history: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    status_message: dict[str, Any] | None = None
    pausa: Pausa | None = None
    traceparent: str | None = None

    def publico(self) -> dict[str, Any]:
        status: dict[str, Any] = {"state": self.state}
        if self.status_message is not None:
            status["message"] = self.status_message
        return {
            "id": self.id,
            "contextId": self.context_id,
            "status": status,
            "history": self.history,
            "artifacts": self.artifacts,
        }


class Agenda:
    def __init__(self, host: HostMCP) -> None:
        self.host = host
        self.tasks: dict[str, Task] = {}

    async def enviar(self, mensagem: dict[str, Any], traceparent: str | None) -> dict[str, Any]:
        texto = _texto(mensagem)
        task_id = mensagem.get("taskId")
        if task_id:
            tarefa = self.tasks.get(str(task_id))
            if tarefa is None:
                raise TaskErro("Task inexistente")
            if tarefa.state in TERMINAIS:
                raise TaskErro("Task em estado terminal")
            if traceparent:
                tarefa.traceparent = traceparent
            _anexar(tarefa, mensagem)
            if tarefa.state != "TASK_STATE_INPUT_REQUIRED":
                raise TaskErro("Task nao esta aguardando escolha")
            return await self.retomar(tarefa, texto)
        tarefa = Task(
            id=f"task-{secrets.token_hex(6)}",
            context_id=f"ctx-{secrets.token_hex(6)}",
            state="TASK_STATE_SUBMITTED",
            traceparent=traceparent,
        )
        self.tasks[tarefa.id] = tarefa
        _anexar(tarefa, mensagem)
        tarefa.state = "TASK_STATE_WORKING"
        argumentos = _parse_reserva(texto)
        if argumentos is None:
            return self._falhar(tarefa, "pedido fora do formato reservar sala=<id> inicio=<iso8601> fim=<iso8601> responsavel=<nome>")
        resultado = await self.host.chamar(argumentos, traceparent=tarefa.traceparent)
        return self._aplicar(tarefa, resultado, argumentos)

    async def retomar(self, tarefa: Task, texto: str) -> dict[str, Any]:
        """Devolve o requestState ao servidor MCP, num tools/call com id novo."""
        pausa = tarefa.pausa
        if pausa is None:
            raise TaskErro("Task sem requestState")
        escolha = _parse_escolha(texto)
        if escolha is None or (escolha != "recusar" and escolha not in pausa.alternativas):
            return self.pausar(tarefa, pausa)
        tarefa.state = "TASK_STATE_WORKING"
        acao = "decline" if escolha == "recusar" else "accept"
        conteudo = None if acao == "decline" else {"sala": escolha}
        resultado = await self.host.chamar(
            dict(pausa.argumentos),
            traceparent=tarefa.traceparent,
            input_responses={pausa.chave: ElicitResult(action=acao, content=conteudo)},
            request_state=pausa.request_state,
        )
        if acao == "decline" and not _erro(resultado):
            tarefa.state = "TASK_STATE_CANCELED"
            tarefa.pausa = None
            tarefa.status_message = _mensagem(tarefa, "ROLE_AGENT", "escolha recusada")
            return {"task": tarefa.publico()}
        return self._aplicar(tarefa, resultado, pausa.argumentos)

    def pausar(self, tarefa: Task, pausa: Pausa) -> dict[str, Any]:
        """O input_required do MCP vira TASK_STATE_INPUT_REQUIRED."""
        tarefa.state = "TASK_STATE_INPUT_REQUIRED"
        tarefa.pausa = pausa
        tarefa.status_message = _mensagem(tarefa, "ROLE_AGENT", pausa.linha)
        return {"task": tarefa.publico()}

    def obter(self, task_id: str) -> dict[str, Any]:
        tarefa = self.tasks.get(task_id)
        if tarefa is None:
            raise TaskErro("Task inexistente")
        return {"task": tarefa.publico()}

    def _aplicar(self, tarefa: Task, resultado: Any, argumentos: dict[str, str]) -> dict[str, Any]:
        if isinstance(resultado, InputRequiredResult):
            return self.pausar(tarefa, _pausa_de(resultado, argumentos))
        if _erro(resultado):
            return self._falhar(tarefa, _texto_tool(resultado))
        dados = dict(getattr(resultado, "structured_content", None) or {})
        dados["politica"] = self.host.politica
        tarefa.state = "TASK_STATE_COMPLETED"
        tarefa.pausa = None
        tarefa.artifacts = [
            {
                "name": "reserva",
                "parts": [{"text": json.dumps(dados, ensure_ascii=False)}],
            }
        ]
        reserva = dados.get("reserva") or ""
        sala = dados.get("sala") or ""
        tarefa.status_message = _mensagem(tarefa, "ROLE_AGENT", f"Reserva {reserva} confirmada na {sala}.")
        return {"task": tarefa.publico()}

    def _falhar(self, tarefa: Task, texto: str) -> dict[str, Any]:
        tarefa.state = "TASK_STATE_FAILED"
        tarefa.pausa = None
        tarefa.status_message = _mensagem(tarefa, "ROLE_AGENT", texto)
        return {"task": tarefa.publico()}


class TaskErro(Exception):
    pass


def _pausa_de(resultado: InputRequiredResult, argumentos: dict[str, str]) -> Pausa:
    pedidos = resultado.input_requests or {}
    if len(pedidos) != 1:
        raise TaskErro("input_required sem uma unica escolha")
    chave = next(iter(pedidos))
    pedido = pedidos[chave]
    params = pedido.params
    schema = params.requested_schema
    if hasattr(schema, "model_dump"):
        schema = schema.model_dump()
    campo = (schema or {}).get("properties", {}).get("sala", {})
    if campo.get("enum"):
        alternativas = [str(item) for item in campo["enum"]]
    elif "const" in campo:
        alternativas = [str(campo["const"])]
    else:
        alternativas = []
    linha = "alternativas: " + ", ".join(alternativas)
    if not resultado.request_state:
        raise TaskErro("input_required sem requestState")
    return Pausa(
        request_state=resultado.request_state,
        chave=chave,
        argumentos=dict(argumentos),
        alternativas=alternativas,
        linha=linha,
    )


def _anexar(tarefa: Task, mensagem: dict[str, Any]) -> None:
    partes = mensagem.get("parts") or [{"text": _texto(mensagem)}]
    registro = {
        "messageId": mensagem.get("messageId") or f"msg-{secrets.token_hex(6)}",
        "role": mensagem.get("role") or "ROLE_USER",
        "parts": partes,
    }
    if mensagem.get("taskId"):
        registro["taskId"] = mensagem["taskId"]
    tarefa.history.append(registro)


def _mensagem(tarefa: Task, papel: str, texto: str) -> dict[str, Any]:
    registro = {
        "messageId": f"msg-{secrets.token_hex(6)}",
        "role": papel,
        "parts": [{"text": texto}],
        "taskId": tarefa.id,
        "contextId": tarefa.context_id,
    }
    tarefa.history.append(
        {
            "messageId": registro["messageId"],
            "role": papel,
            "parts": [{"text": texto}],
            "taskId": tarefa.id,
            "contextId": tarefa.context_id,
        }
    )
    return registro


def _texto(mensagem: dict[str, Any]) -> str:
    return " ".join(parte.get("text", "") for parte in mensagem.get("parts") or [] if isinstance(parte, dict))


def _parse_reserva(texto: str) -> dict[str, str] | None:
    partes = texto.strip().split()
    if len(partes) != 5 or partes[0] != "reservar":
        return None
    campos: dict[str, str] = {}
    for parte in partes[1:]:
        if "=" not in parte:
            return None
        chave, valor = parte.split("=", 1)
        campos[chave] = valor
    if set(campos) != {"sala", "inicio", "fim", "responsavel"}:
        return None
    return campos


def _parse_escolha(texto: str) -> str | None:
    bruto = texto.strip()
    if not bruto.startswith("escolha=") or " " in bruto:
        return None
    return bruto.split("=", 1)[1]


def _erro(resultado: Any) -> bool:
    return bool(getattr(resultado, "is_error", False))


def _texto_tool(resultado: Any) -> str:
    blocos = getattr(resultado, "content", None) or []
    return " ".join(getattr(bloco, "text", "") for bloco in blocos)
