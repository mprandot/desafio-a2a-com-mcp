"""Ciclo MCP sem A2A. Descobre as tools, lê a política e mostra o input_required cru.

    python -m agente.ciclo --sala sala-garagem --inicio 2026-11-03T14:00:00-03:00 --fim 2026-11-03T15:00:00-03:00 --escolha sala-fusca
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from mcp.types import ElicitResult, InputRequiredResult

from agente.host_mcp import HostMCP
from agente.tarefas import _pausa_de


async def _rodar(args: argparse.Namespace) -> None:
    host = HostMCP(os.environ.get("MCP_URL", "http://127.0.0.1:7301/mcp"))
    await host.conectar()
    try:
        print(f"politica {host.politica}")
        print(f"tool {host.nome_reserva}")
        argumentos = {
            "sala": args.sala,
            "inicio": args.inicio,
            "fim": args.fim,
            "responsavel": args.responsavel,
        }
        resultado = await host.chamar(argumentos)
        if not isinstance(resultado, InputRequiredResult):
            print(json.dumps(getattr(resultado, "structured_content", None), ensure_ascii=False, default=str))
            return
        pausa = _pausa_de(resultado, argumentos)
        print(pausa.linha)
        print(f"chave {pausa.chave}")
        if not args.escolha:
            return
        acao = "decline" if args.escolha == "recusar" else "accept"
        conteudo = None if acao == "decline" else {"sala": args.escolha}
        retry = await host.chamar(
            argumentos,
            input_responses={pausa.chave: ElicitResult(action=acao, content=conteudo)},
            request_state=pausa.request_state,
        )
        print(json.dumps(getattr(retry, "structured_content", None), ensure_ascii=False, default=str))
    finally:
        await host.fechar()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ciclo MCP cru, sem A2A")
    parser.add_argument("--sala", default="sala-garagem")
    parser.add_argument("--inicio", default="2026-11-03T14:00:00-03:00")
    parser.add_argument("--fim", default="2026-11-03T15:00:00-03:00")
    parser.add_argument("--responsavel", default="Marty")
    parser.add_argument("--escolha", default="")
    asyncio.run(_rodar(parser.parse_args()))


if __name__ == "__main__":
    main()
