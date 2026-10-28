"""Cliente MCP. Enxerga o input_required cru e não responde a elicitation sozinho."""

from __future__ import annotations

import secrets
from typing import Any

from mcp import Client
from mcp.types import ElicitResult
from mcp_types import Implementation

PROTOCOLO = "2026-07-28"


def propagar_traceparent(traceparent: str | None) -> str | None:
    if not traceparent:
        return None
    partes = traceparent.strip().split("-")
    if len(partes) != 4 or len(partes[1]) != 32:
        return traceparent
    return f"00-{partes[1]}-{secrets.token_hex(8)}-{partes[3]}"


async def _recusar_callback(*_args: Any, **_kwargs: Any) -> ElicitResult:
    raise RuntimeError("o agente nao responde elicitation por conta propria")


class HostMCP:
    def __init__(self, url: str) -> None:
        self.url = url
        self.politica = ""
        self.nome_reserva = ""
        self._client: Client | None = None

    async def conectar(self) -> None:
        self._client = Client(
            self.url,
            mode=PROTOCOLO,
            cache=None,
            client_info=Implementation(name="agente-central-de-salas", version="1.0.0"),
            elicitation_callback=_recusar_callback,
        )
        await self._client.__aenter__()
        descobertas = await self._client.session.list_tools()
        nomes = [ferramenta.name for ferramenta in descobertas.tools]
        if "reservar_sala" not in nomes:
            raise RuntimeError(f"tools/list nao trouxe reservar_sala: {nomes}")
        self.nome_reserva = nomes[nomes.index("reservar_sala")]
        leitura = await self._client.session.read_resource("politica://uso")
        texto = leitura.contents[0].text or ""
        primeira = texto.splitlines()[0] if texto else ""
        if ":" not in primeira:
            raise RuntimeError("resource politica://uso sem versao na primeira linha")
        self.politica = primeira.split(":", 1)[1].strip()

    async def fechar(self) -> None:
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None

    async def chamar(
        self,
        argumentos: dict[str, Any],
        *,
        traceparent: str | None = None,
        input_responses: dict[str, ElicitResult] | None = None,
        request_state: str | None = None,
    ) -> Any:
        if self._client is None or not self.nome_reserva:
            raise RuntimeError("host MCP ainda nao descobriu as tools")
        meta = None
        propagado = propagar_traceparent(traceparent)
        if propagado:
            meta = {"traceparent": propagado}
        return await self._client.session.call_tool(
            self.nome_reserva,
            argumentos,
            input_responses=input_responses,
            request_state=request_state,
            meta=meta,
            allow_input_required=True,
        )
