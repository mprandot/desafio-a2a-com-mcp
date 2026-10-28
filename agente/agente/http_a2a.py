"""Servidor A2A v1.0. Card público e JSON-RPC em /a2a."""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agente.tarefas import Agenda, TaskErro


def card(url_publica: str) -> dict[str, Any]:
    base = url_publica.rstrip("/")
    return {
        "name": "Central de Salas",
        "description": "Reserva salas de reuniao da Hill Valley Tech.",
        "provider": {
            "organization": "Hill Valley Tech",
            "url": "https://hillvalley.example",
        },
        "version": "1.0.0",
        "supportedInterfaces": [
            {
                "url": f"{base}/a2a",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "extendedAgentCard": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "reservar-sala",
                "name": "Reservar sala",
                "description": "Reserva uma sala em um intervalo. Se houver conflito, pergunta qual alternativa usar.",
                "tags": ["salas", "agenda"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
                "examples": [
                    "reservar sala=sala-garagem inicio=2026-11-03T14:00:00-03:00 fim=2026-11-03T15:00:00-03:00 responsavel=Marty"
                ],
            }
        ],
    }


def criar_app(agenda: Agenda, url_publica: str) -> Starlette:
    async def agent_card(_request: Request) -> JSONResponse:
        return JSONResponse(card(url_publica))

    async def a2a(request: Request) -> JSONResponse:
        try:
            corpo = await request.json()
        except Exception:
            return JSONResponse(_erro(None, -32700, "JSON invalido"))
        if not isinstance(corpo, dict):
            return JSONResponse(_erro(None, -32600, "pedido invalido"))
        identificador = corpo.get("id")
        metodo = corpo.get("method")
        params = corpo.get("params") if isinstance(corpo.get("params"), dict) else {}
        traceparent = request.headers.get("traceparent")
        try:
            if metodo == "SendMessage":
                mensagem = params.get("message")
                if not isinstance(mensagem, dict):
                    raise TaskErro("SendMessage sem message")
                resultado = await agenda.enviar(mensagem, traceparent)
            elif metodo == "GetTask":
                task_id = params.get("id")
                if not isinstance(task_id, str) or not task_id:
                    raise TaskErro("GetTask sem id")
                resultado = agenda.obter(task_id)
            else:
                return JSONResponse(_erro(identificador, -32601, "metodo nao encontrado"))
        except TaskErro as exc:
            return JSONResponse(_erro(identificador, -32602, str(exc)))
        return JSONResponse({"jsonrpc": "2.0", "id": identificador, "result": resultado})

    return Starlette(
        routes=[
            Route("/.well-known/agent-card.json", agent_card, methods=["GET"]),
            Route("/a2a", a2a, methods=["POST"]),
        ]
    )


def _erro(identificador: Any, codigo: int, mensagem: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": identificador, "error": {"code": codigo, "message": mensagem}}
