"""Indicadores da operação, do jeito que o painel mostra.

FUPS = acionamentos · CPC = contato com a pessoa certa · CPC único = contratos DISTINTOS com CPC
CPCA = acordos · Boleto = boletos gerados · Risco = valor dos contratos com boleto · Estoque = carteira na fase
"""
from pathlib import Path

import pandas as pd

PASTA = Path(__file__).resolve().parent.parent / "dados" / "operacao" / "veiculos"   # carteira principal
HORAS = list(range(8, 21))


def carregar(pasta: Path = PASTA) -> dict[str, pd.DataFrame]:
    pasta = Path(pasta)
    nomes = ["producao", "cpc_eventos", "estoque"] + (["faixas"] if (pasta / "faixas.csv").exists() else [])
    return {n: pd.read_csv(pasta / f"{n}.csv", parse_dates=["dia"]) for n in nomes}


def cpc_unico_acumulado(eventos: pd.DataFrame, dia=None) -> pd.DataFrame:
    """Contratos distintos com CPC das 8h até o fim de cada hora, por dia e fase (todas as horas presentes)."""
    e = eventos if dia is None else eventos[eventos["dia"] == pd.Timestamp(dia)]
    primeira = e.groupby(["dia", "fase", "id_contrato"])["hora"].min().reset_index()   # 1º CPC do contrato no dia
    novos = primeira.groupby(["dia", "fase", "hora"]).size()
    grade = pd.MultiIndex.from_product([e["dia"].unique(), e["fase"].unique(), HORAS], names=["dia", "fase", "hora"])
    acum = novos.reindex(grade, fill_value=0).groupby(level=["dia", "fase"]).cumsum()
    return acum.rename("cpc_unico_acum").reset_index()


def serie_diaria(t: dict) -> pd.DataFrame:
    """Uma linha por dia × fase: totais de produção, CPC único do dia e estoque."""
    p = t["producao"]
    soma = p.groupby(["dia", "fase"])[["fups", "cpc", "cpca", "boleto", "risco", "propostas"]].sum()
    unico = t["cpc_eventos"].groupby(["dia", "fase"])["id_contrato"].nunique().rename("cpc_unico")
    est = t["estoque"].set_index(["dia", "fase"])["contratos"].rename("estoque")
    s = soma.join(unico).join(est).fillna({"cpc_unico": 0}).reset_index()
    s["cpc_unico"] = s["cpc_unico"].astype(int)
    return s


def _div(a, b):
    return None if not b else a / b


def derivados(d: dict) -> dict:
    return {"pct_cpc": _div(d["cpc"], d["fups"]), "pct_cpca": _div(d["cpca"], d["fups"]),
            "conversao": _div(d["boleto"], d["cpca"]), "cpcu_estoque": _div(d["cpc_unico"], d["estoque"]),
            "atend_base": _div(d["fups"], d["estoque"]), "cpc_por_oper": _div(d["cpc"], d["operadores"]),
            "boleto_por_oper": _div(d["boleto"], d["operadores"])}
