import numpy as np
import pandas as pd

from src.previsao_mes import prever_mes


def _diaria(valor_fn, inicio="2025-05-19", fim="2026-11-30"):
    dias = pd.bdate_range(inicio, fim)
    return pd.DataFrame({"dia": dias, "fase": "A", "cpc": [valor_fn(d) for d in dias]})


def test_mes_constante_preve_exato():
    d = _diaria(lambda _: 100)
    r = prever_mes(d, "2026-11-12", "cpc")
    n = len(pd.bdate_range("2026-11-01", "2026-11-30"))
    assert abs(r["prev"] - 100 * n) / (100 * n) < 0.01
    assert r["realizado_ate"] == 100 * len(pd.bdate_range("2026-11-01", "2026-11-12"))


def test_faixa_contem_prev():
    rng = np.random.default_rng(0)
    d = _diaria(lambda _: 100 * rng.lognormal(0, 0.1))
    r = prever_mes(d, "2026-11-12", "cpc")
    assert r["lo"] <= r["prev"] <= r["hi"]
    assert len(r["curva"]) == len(pd.bdate_range("2026-11-01", "2026-11-30"))
    assert len(r["mes_anterior"]) > 15 and len(r["mes_retrasado"]) > 15


def test_ultimo_dia_do_mes():
    rng = np.random.default_rng(1)
    d = _diaria(lambda _: 100 * rng.lognormal(0, 0.1))
    r = prever_mes(d, "2026-10-30", "cpc")
    assert abs(r["prev"] - r["realizado_ate"]) < 1e-6


def test_story_fecha_as_contas():
    rng = np.random.default_rng(3)
    d = _diaria(lambda _: 100 * rng.lognormal(0, 0.1))
    r = prever_mes(d, "2026-11-12", "cpc")
    falta = sum(g["n"] * g["media"] for g in r["falta_dow"])
    assert abs(r["realizado_ate"] + falta - r["por_dow"]) < 1.0       # realizado + o que falta = ritmo por dia da semana
    assert abs((r["linear"] + r["por_dow"]) / 2 - r["blend"]) < 0.2    # previsão = média dos dois ritmos
    assert r["du_passados"] + sum(g["n"] for g in r["falta_dow"]) == r["du_total"]


def test_previsto_na_vespera_so_nos_dias_passados():
    d = _diaria(lambda _: 100)
    r = prever_mes(d, "2026-11-12", "cpc")
    for p in r["por_dia"]:
        if p["dia"] <= "2026-11-12":
            assert p["realizado"] is not None and p["previsto"] is None and abs(p["vespera"] - 100) < 1e-6
        else:
            assert p["realizado"] is None and p["vespera"] is None and p["previsto"] is not None
    assert abs(sum(p["previsto"] for p in r["por_dia"] if p["previsto"]) - (r["prev"] - r["realizado_ate"])) < 1
