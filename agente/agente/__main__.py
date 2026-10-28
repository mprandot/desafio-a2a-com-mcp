"""Sobe o agente: host MCP por dentro, servidor A2A por fora."""

from __future__ import annotations

import asyncio
import os

import uvicorn

from agente.host_mcp import HostMCP
from agente.http_a2a import criar_app
from agente.tarefas import Agenda


async def _servir() -> None:
    url_mcp = os.environ.get("MCP_URL", "http://127.0.0.1:7301/mcp")
    host = os.environ.get("AGENTE_HOST", "127.0.0.1")
    porta = int(os.environ.get("AGENTE_PORT", "7300"))
    url_publica = os.environ.get("AGENTE_PUBLIC_URL", f"http://127.0.0.1:{porta}")
    mcp = HostMCP(url_mcp)
    await mcp.conectar()
    app = criar_app(Agenda(mcp), url_publica)
    config = uvicorn.Config(app, host=host, port=porta, access_log=False)
    servidor = uvicorn.Server(config)
    try:
        await servidor.serve()
    finally:
        await mcp.fechar()


def main() -> None:
    asyncio.run(_servir())


if __name__ == "__main__":
    main()
