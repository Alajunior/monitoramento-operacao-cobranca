import numpy as np
import pandas as pd
import pytest

from dados.gerar_operacao import CARTEIRAS, gerar


@pytest.fixture(scope="module")
def cartoes(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("cartoes")
    gerar(pasta, inicio="2026-09-01", escala=0.2, carteira="cartoes")
    return {n: pd.read_csv(pasta / f"{n}.csv", parse_dates=["dia"]) for n in ["producao", "estoque", "faixas"]}


def test_tres_carteiras_com_fases_proprias():
    assert list(CARTEIRAS) == ["veiculos", "cartoes", "varejo"]
    assert all(c["nome"].startswith("Carteira ") for c in CARTEIRAS.values())
    assert len({tuple(c["fases"]) for c in CARTEIRAS.values()}) == 3


def test_fases_da_carteira(cartoes):
    assert set(cartoes["producao"]["fase"]) == set(CARTEIRAS["cartoes"]["fases"])


def test_pagos_nunca_maior_que_boletos(cartoes):
    p = cartoes["producao"]
    assert (p["pagos"] <= p["boleto"]).all() and (p["valor_pago"] >= 0).all()
    assert p["pagos"].sum() > 0


def test_shares_das_faixas_somam_um(cartoes):
    f = cartoes["faixas"]
    cols = [c for c in f.columns if c.startswith("share_")]
    soma = f.groupby(["dia", "fase"])[cols].sum()
    assert np.allclose(soma.to_numpy(), 1.0)
    assert f.groupby("fase")["faixa"].nunique().between(2, 3).all()


def test_carteira_principal_nao_mudou(pasta_pequena):
    # a principal precisa continuar igual à v1 (README e placar): o gerador novo usa outro gerador aleatório
    p = pd.read_csv(pasta_pequena / "producao.csv")
    assert {"pagos", "valor_pago", "risco_cpc"} <= set(p.columns)
    assert (int(p["fups"].sum()), int(p["cpc"].sum())) == (485910, 44303)   # totais da v1 nesta base: não mudam
