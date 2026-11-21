"""Previsão do fechamento do dia de CPC único, feita a cada hora, por RAZÃO DE FUNIL.

Ideia: num dia normal, "quanto o dia fecha" é um múltiplo estável de "quanto já foi feito até a hora h".
    razão[fase][h] = Σ w·total_do_dia / Σ w·acumulado_até_h      (w cai pela metade a cada 30 dias)
    previsão      = acumulado_de_hoje_até_h × razão              (se o acumulado for < 3, usa o esperado)
Depois:
    ajuste de viés = mediana de real/previsto (total) nos 20 dias anteriores
    faixa de 80%   = quantis 10–90% de real/previsto nos 60 dias anteriores, FORA da amostra
Cada previsão usa só os dias anteriores ao dia previsto.
"""
import numpy as np
import pandas as pd

HORAS = list(range(8, 21))
MAX_DIAS, MIN_DIAS, MEIA_VIDA = 120, 25, 30
JANELA_VIES, JANELA_FAIXA, JANELA_ESPERADO = 20, 60, 20
ALERTA_DERIVA = 0.08


def _matrizes(acum: pd.DataFrame, diaria: pd.DataFrame):
    dias = np.array(sorted(diaria["dia"].unique()), dtype="datetime64[ns]")
    fases = sorted(diaria["fase"].unique())
    T = diaria.pivot_table(index="dia", columns="fase", values="cpc_unico", aggfunc="sum") \
        .reindex(index=dias, columns=fases).fillna(0).to_numpy(float)
    A = acum.pivot_table(index=["hora", "dia"], columns="fase", values="cpc_unico_acum", aggfunc="sum")
    A = np.stack([A.loc[h].reindex(index=dias, columns=fases).fillna(0).to_numpy(float) for h in HORAS])
    return dias, fases, A, T


def _bruta(dias, A, T, i: int, h: int):
    """Previsão sem ajuste para o dia de índice i, na hora h (vetor por fase), ou None se faltar histórico."""
    ini = max(0, i - MAX_DIAS)
    if i - ini < MIN_DIAS:
        return None
    idade = (dias[i] - dias[ini:i]) / np.timedelta64(1, "D")
    w = 0.5 ** (idade / MEIA_VIDA)[:, None]
    ah = A[h - 8]
    num, den = (w * T[ini:i]).sum(0), (w * ah[ini:i]).sum(0)
    razao = np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)
    esperado = T[max(0, i - JANELA_ESPERADO):i].mean(0)
    real_h = ah[i]
    baixo = real_h + esperado * (1 - 1 / np.where(np.isfinite(razao) & (razao > 0), razao, np.inf))
    prev = np.where((real_h >= 3) & np.isfinite(razao), real_h * np.nan_to_num(razao), baixo)
    return np.maximum(prev, real_h), esperado


def _previsoes(dias, A, T, i: int, h: int):
    """Para o dia i: previsão ajustada e faixa, por fase e total (colunas: fases..., total)."""
    brutas = {}
    for j in range(max(0, i - JANELA_FAIXA - JANELA_VIES), i + 1):
        r = _bruta(dias, A, T, j, h)
        if r is not None:
            brutas[j] = np.append(r[0], r[0].sum())
    if i not in brutas:
        return None
    real = np.column_stack([T, T.sum(1)])

    def vies(j):   # mediana real/previsto do total nos 20 dias anteriores a j
        rs = [real[k, -1] / brutas[k][-1] for k in range(j - JANELA_VIES, j) if k in brutas and brutas[k][-1] > 0]
        return float(np.median(rs)) if rs else 1.0

    ajustadas = {j: brutas[j] * vies(j) for j in brutas}
    razoes = np.array([real[k] / np.where(ajustadas[k] > 0, ajustadas[k], np.nan)
                       for k in range(i - JANELA_FAIXA, i) if k in ajustadas])
    prev = ajustadas[i]
    if len(razoes) >= 10:
        q10, q90 = np.nanquantile(razoes, 0.10, axis=0), np.nanquantile(razoes, 0.90, axis=0)
    else:
        q10 = q90 = np.ones_like(prev)
    esperado = _bruta(dias, A, T, i, h)[1]
    return prev, prev * np.minimum(q10, 1), prev * np.maximum(q90, 1), np.append(esperado, esperado.sum())


def prever(acum: pd.DataFrame, diaria: pd.DataFrame, dia, hora: int) -> dict | None:
    """Previsão do fechamento de `dia` feita às `hora` h, usando só os dias anteriores. None sem histórico."""
    dias, fases, A, T = _matrizes(acum[acum["dia"] <= pd.Timestamp(dia)], diaria[diaria["dia"] <= pd.Timestamp(dia)])
    i = int(np.searchsorted(dias, np.datetime64(pd.Timestamp(dia))))
    if i >= len(dias) or dias[i] != np.datetime64(pd.Timestamp(dia)):   # dia sem total (hoje): cria a linha
        dias = np.append(dias, np.datetime64(pd.Timestamp(dia), "ns"))
        T = np.vstack([T, np.zeros(len(fases))])
        hoje = acum[acum["dia"] == pd.Timestamp(dia)].pivot_table(index="hora", columns="fase",
                                                                  values="cpc_unico_acum", aggfunc="sum")
        A = np.concatenate([A, np.stack([hoje.reindex(columns=fases).loc[h].fillna(0).to_numpy(float)
                                         if h in hoje.index else np.zeros(len(fases)) for h in HORAS])[:, None, :]], 1)
        i = len(dias) - 1
    r = _previsoes(dias, A, T, i, hora)
    if r is None:
        return None
    prev, lo, hi, esp = r
    real_h = np.append(A[hora - 8][i], A[hora - 8][i].sum())
    nomes = list(fases) + ["__TOTAL__"]
    saida = {n: {"prev": round(float(prev[k]), 1), "lo": round(float(lo[k]), 1), "hi": round(float(hi[k]), 1),
                 "esperado": round(float(esp[k]), 1), "realizado": int(real_h[k])} for k, n in enumerate(nomes)}
    return {"total": saida.pop("__TOTAL__"), "fases": saida}


def erro_12h_recente(registro: pd.DataFrame, n: int = 5) -> float:
    """WMAPE da previsão das 12h (total, já ajustada) nos últimos n dias fechados."""
    r = registro[(registro["hora"] == 12) & (registro["escopo"] == "__TOTAL__")].sort_values("dia").tail(n)
    return float((r["real"] - r["prev"]).abs().sum() / r["real"].sum())
