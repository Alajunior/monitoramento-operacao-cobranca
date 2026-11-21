import pandas as pd
import pytest

from src.indicadores import carregar, cpc_unico_acumulado, derivados, serie_diaria


@pytest.fixture(scope="module")
def t(pasta_pequena):
    return carregar(pasta_pequena)


def test_cpc_unico_acumulado_monotono(t):
    a = cpc_unico_acumulado(t["cpc_eventos"])
    assert set(a.columns) == {"dia", "fase", "hora", "cpc_unico_acum"}
    assert (a.groupby(["dia", "fase"])["cpc_unico_acum"].diff().dropna() >= 0).all()
    dia = a["dia"].max()
    as20 = a[(a.dia == dia) & (a.hora == 20)].set_index("fase")["cpc_unico_acum"]
    e = t["cpc_eventos"]
    distintos = e[e.dia == dia].groupby("fase")["id_contrato"].nunique()
    assert (as20.loc[distintos.index] == distintos).all()
    assert len(a[(a.dia == dia)]) == 4 * 13   # todas as fases × horas, mesmo sem CPC


def test_derivados_divisao_por_zero():
    d = derivados({"fups": 0, "cpc": 0, "cpca": 0, "boleto": 0, "cpc_unico": 0, "estoque": 0, "operadores": 0})
    assert d["pct_cpc"] is None and d["conversao"] is None and d["cpc_por_oper"] is None
    d = derivados({"fups": 200, "cpc": 20, "cpca": 5, "boleto": 4, "cpc_unico": 18, "estoque": 1000, "operadores": 10})
    assert d["pct_cpc"] == 0.1 and d["conversao"] == 0.8 and d["cpcu_estoque"] == 0.018


def test_serie_diaria_totais(t):
    s = serie_diaria(t)
    p = t["producao"]
    assert s["fups"].sum() == p["fups"].sum()
    assert {"dia", "fase", "fups", "cpc", "cpca", "boleto", "cpc_unico", "estoque"} <= set(s.columns)
    assert not s.duplicated(["dia", "fase"]).any()
