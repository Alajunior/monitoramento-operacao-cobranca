import math

import numpy as np
import pandas as pd

from src.previsao_dia import erro_12h_recente, prever

FASES = ["A", "B"]


def _historico(n_dias, fator=2.0, acum_12=50, seed=0):
    """Dias úteis em que o total do dia = fator × acumulado às 12h (curva linear nas horas)."""
    rng = np.random.default_rng(seed)
    dias = pd.bdate_range(end="2026-11-19", periods=n_dias)
    acum, diaria = [], []
    for d in dias:
        for f in FASES:
            a12 = acum_12 + int(rng.integers(-5, 6))
            total = int(round(fator * a12))
            for h in range(8, 21):
                v = round(a12 * (h - 7) / 5) if h <= 12 else round(a12 + (total - a12) * (h - 12) / 8)
                acum.append((d, f, h, v))
            diaria.append((d, f, total))
    return (pd.DataFrame(acum, columns=["dia", "fase", "hora", "cpc_unico_acum"]),
            pd.DataFrame(diaria, columns=["dia", "fase", "cpc_unico"]))


def test_razao_constante_preve_exato():
    acum, diaria = _historico(150)
    hoje = diaria["dia"].max()
    r = prever(acum, diaria, hoje, 12)
    real12 = acum[(acum.dia == hoje) & (acum.hora == 12)]["cpc_unico_acum"].sum()
    assert abs(r["total"]["prev"] - 2 * real12) / (2 * real12) < 0.01
    assert r["total"]["lo"] <= r["total"]["prev"] <= r["total"]["hi"]
    assert set(r["fases"]) == set(FASES)


def test_previsao_acumulado_zero():
    acum, diaria = _historico(150)
    hoje = diaria["dia"].max()
    acum.loc[(acum.dia == hoje) & (acum.fase == "A"), "cpc_unico_acum"] = 0
    r = prever(acum, diaria, hoje, 9)
    v = r["fases"]["A"]["prev"]
    assert math.isfinite(v) and v >= 0


def test_previsao_historico_curto():
    acum, diaria = _historico(10)
    assert prever(acum, diaria, diaria["dia"].max(), 12) is None


def test_sem_olhar_o_futuro():
    acum, diaria = _historico(150)
    dia = diaria["dia"].unique()[-10]
    antes = prever(acum, diaria, dia, 12)
    diaria2 = diaria.copy()
    diaria2.loc[diaria2.dia > dia, "cpc_unico"] *= 3
    assert prever(acum, diaria2, dia, 12) == antes


def test_erro_12h_recente():
    reg = pd.DataFrame({"dia": pd.bdate_range(end="2026-11-19", periods=6), "hora": 12,
                        "escopo": "__TOTAL__", "prev": [100, 110, 110, 90, 90, 100],
                        "real": [100, 100, 100, 100, 100, 100]})
    assert abs(erro_12h_recente(reg, n=5) - 0.08) < 1e-9


def test_faixa_nunca_abaixo_do_realizado():
    acum, diaria = _historico(150)
    hoje = diaria["dia"].max()
    acum.loc[(acum.dia == hoje) & (acum.hora >= 19), "cpc_unico_acum"] += 400   # dia muito acima do normal no fim
    r = prever(acum, diaria, hoje, 20)
    for v in [r["total"], *r["fases"].values()]:
        assert v["lo"] >= v["realizado"] and v["prev"] >= v["realizado"] and v["hi"] >= v["prev"]


def test_sem_olhar_o_proprio_dia():
    acum, diaria = _historico(150)
    dia = diaria["dia"].unique()[-10]
    antes = prever(acum, diaria, dia, 12)
    diaria2 = diaria.copy()
    diaria2.loc[diaria2.dia == dia, "cpc_unico"] *= 3   # o total do próprio dia não pode influenciar
    assert prever(acum, diaria2, dia, 12) == antes


def test_faixa_nunca_abaixo_do_realizado_nos_dados(pasta_pequena):
    from src.indicadores import carregar, cpc_unico_acumulado, serie_diaria
    t = carregar(pasta_pequena)
    acum, diaria = cpc_unico_acumulado(t["cpc_eventos"]), serie_diaria(t)
    for dia in sorted(diaria["dia"].unique())[-15:]:
        for h in (18, 19, 20):
            r = prever(acum, diaria, dia, h)
            for v in [r["total"], *r["fases"].values()]:
                assert v["lo"] >= v["realizado"] and v["prev"] >= v["realizado"], (dia, h, v)
