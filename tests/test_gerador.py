import pandas as pd
import pytest

from dados.gerar_operacao import CANAIS, FASES, gerar


@pytest.fixture(scope="module")
def t(pasta_pequena):
    return {n: pd.read_csv(pasta_pequena / f"{n}.csv", parse_dates=["dia"])
            for n in ["producao", "cpc_eventos", "estoque"]}


def test_periodo_e_grade(t):
    p = t["producao"]
    assert (p["dia"].dt.dayofweek < 5).all()
    assert sorted(p["hora"].unique()) == list(range(8, 21))
    assert set(p["fase"]) == set(FASES) and set(p["canal"]) == set(CANAIS)
    assert p["dia"].max() == pd.Timestamp("2026-11-19")
    assert not p.duplicated(["dia", "hora", "fase", "canal"]).any()


def test_cpc_unico_menor_que_cpc(t):
    p, e = t["producao"], t["cpc_eventos"]
    assert len(e) == p["cpc"].sum()
    por_dia = e.groupby(["dia", "fase"])["id_contrato"].nunique()
    soma = p.groupby(["dia", "fase"])["cpc"].sum()
    assert (por_dia <= soma.loc[por_dia.index]).all()
    assert (por_dia < soma.loc[por_dia.index]).mean() > 0.5


def test_episodio_de_estoque(t):
    est = t["estoque"]
    f = est[est["fase"] == "31-90"].set_index("dia")["contratos"]
    assert f["2026-11"].mean() <= 0.8 * f["2026-08"].mean()
