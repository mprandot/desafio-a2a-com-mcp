"""Salas, reservas em memória e as três regras da política.

Nada aqui sobrevive a um restart. O pedido interrompido viaja no requestState.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

FUSO = timezone(timedelta(hours=-3))
ABERTURA = time(8, 0)
FECHAMENTO = time(20, 0)
DURACAO_MAXIMA = timedelta(hours=2)

MSG_JANELA = "Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00"
MSG_DURACAO = "Duracao acima do limite: a politica permite no maximo 2 horas"
MSG_INTERVALO = "Intervalo invalido: fim deve ser posterior a inicio"
MSG_SEM_ALTERNATIVA = "Sem alternativas disponiveis no intervalo"
MSG_ELICITACAO = "A sala pedida esta ocupada nesse intervalo. Escolha uma alternativa."


def msg_sala(sala: str) -> str:
    return f"Sala inexistente: {sala}"


@dataclass(frozen=True)
class Sala:
    id: str
    nome: str
    capacidade: int
    recursos: list[str]


@dataclass
class Reserva:
    id: str
    sala: str
    inicio: datetime
    fim: datetime
    responsavel: str

    def como_conflito(self) -> dict[str, str]:
        return {
            "id": self.id,
            "inicio": _iso(self.inicio),
            "fim": _iso(self.fim),
            "responsavel": self.responsavel,
        }


def _iso(valor: datetime) -> str:
    return valor.isoformat()


def _parse(valor: str) -> datetime:
    texto = valor.strip()
    if texto.endswith("Z"):
        texto = texto[:-1] + "+00:00"
    instante = datetime.fromisoformat(texto)
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=FUSO)
    return instante.astimezone(FUSO)


def _na_janela(instante: datetime) -> bool:
    relogio = instante.astimezone(FUSO).time()
    return ABERTURA <= relogio <= FECHAMENTO


def _sobrepoe(a_inicio: datetime, a_fim: datetime, b_inicio: datetime, b_fim: datetime) -> bool:
    return a_inicio < b_fim and b_inicio < a_fim


class Catalogo:
    def __init__(self, raiz_dados: Path) -> None:
        salas = json.loads((raiz_dados / "salas.json").read_text(encoding="utf-8"))
        reservas = json.loads((raiz_dados / "reservas.json").read_text(encoding="utf-8"))
        self.politica_texto = (raiz_dados / "politica-de-uso.md").read_text(encoding="utf-8")
        self.politica_versao = self.politica_texto.splitlines()[0].split(":", 1)[1].strip()
        self.salas = {
            item["id"]: Sala(
                id=item["id"],
                nome=item["nome"],
                capacidade=item["capacidade"],
                recursos=list(item["recursos"]),
            )
            for item in salas
        }
        self.reservas = [
            Reserva(
                id=item["id"],
                sala=item["sala"],
                inicio=_parse(item["inicio"]),
                fim=_parse(item["fim"]),
                responsavel=item["responsavel"],
            )
            for item in reservas
        ]

    def listar(self) -> list[dict[str, object]]:
        return [
            {
                "id": sala.id,
                "nome": sala.nome,
                "capacidade": sala.capacidade,
                "recursos": list(sala.recursos),
            }
            for sala in self.salas.values()
        ]

    def validar(self, sala: str, inicio: str, fim: str) -> str | None:
        if sala not in self.salas:
            return msg_sala(sala)
        try:
            começo = _parse(inicio)
            término = _parse(fim)
        except ValueError:
            return MSG_INTERVALO
        if término <= começo:
            return MSG_INTERVALO
        if término - começo > DURACAO_MAXIMA:
            return MSG_DURACAO
        if not _na_janela(começo) or not _na_janela(término):
            return MSG_JANELA
        return None

    def conflitos(self, sala: str, inicio: str, fim: str) -> list[Reserva]:
        começo = _parse(inicio)
        término = _parse(fim)
        return [
            reserva
            for reserva in self.reservas
            if reserva.sala == sala and _sobrepoe(começo, término, reserva.inicio, reserva.fim)
        ]

    def alternativas(self, sala: str, inicio: str, fim: str) -> list[str]:
        pedida = self.salas[sala]
        candidatas = [
            outra
            for outra in self.salas.values()
            if outra.id != sala
            and outra.capacidade >= pedida.capacidade
            and not self.conflitos(outra.id, inicio, fim)
        ]
        candidatas.sort(key=lambda item: (item.capacidade, item.id))
        return [item.id for item in candidatas[:3]]

    def reservar(self, sala: str, inicio: str, fim: str, responsavel: str) -> Reserva:
        numero = 0
        for reserva in self.reservas:
            sufixo = reserva.id.removeprefix("res-")
            if sufixo.isdigit():
                numero = max(numero, int(sufixo))
        criada = Reserva(
            id=f"res-{numero + 1:04d}",
            sala=sala,
            inicio=_parse(inicio),
            fim=_parse(fim),
            responsavel=responsavel,
        )
        self.reservas.append(criada)
        return criada
