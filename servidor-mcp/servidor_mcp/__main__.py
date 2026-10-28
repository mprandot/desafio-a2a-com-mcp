"""Sobe o servidor MCP em Streamable HTTP."""

from __future__ import annotations

import os

import uvicorn

from servidor_mcp.app import aplicacao


def main() -> None:
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    porta = int(os.environ.get("MCP_PORT", "7301"))
    uvicorn.run(aplicacao(), host=host, port=porta, access_log=False)


if __name__ == "__main__":
    main()
