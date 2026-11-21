"""Previsão do fechamento do mês ("blend" de dois ritmos) com faixa histórica.

    ritmo linear        = realizado / dias úteis passados × dias úteis do mês
    ritmo dia da semana = realizado + Σ (média recente daquele dia da semana) nos dias que faltam
    previsão            = média dos dois
    faixa 5–95%         = erro relativo do mesmo método nos 12 meses anteriores, no mesmo ponto do mês (±7 dias)
"""
import numpy as np
import pandas as pd

MEIA_VIDA = 14
INDICADORES = ["fups", "cpc", "cpc_unico", "cpca", "boleto"]


def _dias_uteis(mes: pd.Period) -> pd.DatetimeIndex:
    return pd.bdate_range(mes.start_time, mes.end_time.normalize())


def _blend(serie: pd.Series, dia: pd.Timestamp) -> tuple[float, float, np.ndarray, pd.DatetimeIndex]:
    """(previsão, realizado até o dia, esperado de cada dia que falta, dias que faltam)."""
    uteis = _dias_uteis(dia.to_period("M"))
    passados, faltam = uteis[uteis <= dia], uteis[uteis > dia]
    realizado = float(serie.reindex(passados).fillna(0).sum())
    if len(faltam) == 0:
        return realizado, realizado, np.array([]), faltam
    linear = realizado / max(len(passados), 1) * len(uteis)
    esperado = esperado_por_dia(serie, dia, faltam)
    por_dow = realizado + esperado.sum()
    return (linear + por_dow) / 2, realizado, esperado, faltam


def esperado_por_dia(serie: pd.Series, ref: pd.Timestamp, alvos) -> np.ndarray:
    """Quanto se espera em cada dia de `alvos`, sabendo só até `ref`: média recente daquele dia da semana."""
    hist = serie[(serie.index <= ref) & (serie.index > ref - pd.Timedelta(days=120))]
    w = 0.5 ** ((ref - hist.index).days / MEIA_VIDA)
    media_dow = pd.Series(hist.to_numpy() * w, index=hist.index).groupby(hist.index.dayofweek).sum() \
        / pd.Series(w, index=hist.index).groupby(hist.index.dayofweek).sum()
    return media_dow.reindex(pd.DatetimeIndex(alvos).dayofweek).fillna(hist.mean()).to_numpy()


def _acumulado_por_posicao(serie: pd.Series, mes: pd.Period) -> list[float]:
    return serie.reindex(_dias_uteis(mes)).fillna(0).cumsum().round(1).tolist()


def prever_mes(diaria: pd.DataFrame, dia, indicador: str) -> dict:
    dia = pd.Timestamp(dia)
    serie = diaria.groupby("dia")[indicador].sum().sort_index()
    prev, realizado, esperado, faltam = _blend(serie, dia)

    # faixa: erro relativo (real/prev) do mesmo método nos 12 meses anteriores, perto do mesmo dia do mês
    razoes = []
    for k in range(1, 13):
        mes = (dia.to_period("M") - k)
        uteis = _dias_uteis(mes)
        if uteis[0] < serie.index.min() + pd.Timedelta(days=30):
            continue
        real_mes = serie.reindex(uteis).fillna(0).sum()
        for d in uteis[abs(uteis.day - dia.day) <= 7]:
            p = _blend(serie, d)[0]
            if p > 0:
                razoes.append(real_mes / p)
    q05, med, q95 = np.quantile(razoes, [0.05, 0.5, 0.95]) if len(razoes) >= 10 else (1.0, 1.0, 1.0)
    erro_tipico = float(np.median(np.abs(np.array(razoes) - 1))) if razoes else None
    base = prev
    prev = max(realizado, base * med)                        # corrige o viés histórico do método nesse ponto do mês
    lo, hi = max(realizado, base * q05), max(realizado, base * q95)   # nunca abaixo do que já foi feito

    uteis = _dias_uteis(dia.to_period("M"))
    curva, acum = [], 0.0
    peso = np.cumsum(esperado) / esperado.sum() if len(esperado) and esperado.sum() > 0 else np.array([])
    for d in uteis:
        if d <= dia:
            acum += float(serie.get(d, 0))
            curva.append({"dia": f"{d:%Y-%m-%d}", "realizado_acum": round(acum, 1), "prev_acum": None,
                          "lo": None, "hi": None})
        else:
            f = float(peso[list(faltam).index(d)])
            curva.append({"dia": f"{d:%Y-%m-%d}", "realizado_acum": None,
                          "prev_acum": round(realizado + f * (prev - realizado), 1),
                          "lo": round(realizado + f * (lo - realizado), 1),
                          "hi": round(realizado + f * (hi - realizado), 1)})
    mes = dia.to_period("M")
    passados = uteis[uteis <= dia]
    linear = realizado / max(len(passados), 1) * len(uteis)
    falta_dow = [{"dow": int(k), "n": int((faltam.dayofweek == k).sum()),
                  "media": round(float(esperado[faltam.dayofweek == k].mean()), 1)}
                 for k in sorted(set(faltam.dayofweek))]
    # por dia: realizado nos dias passados; previsto (escala da previsão final) nos que faltam;
    # "previsto na véspera" = o que se esperava para cada dia passado, com os dados até o dia útil anterior
    escala = (prev - realizado) / esperado.sum() if len(esperado) and esperado.sum() > 0 else 1.0
    por_dia = []
    for d in uteis:
        if d <= dia:
            vespera = serie.index[serie.index < d]
            v = float(esperado_por_dia(serie, vespera[-1], [d])[0]) if len(vespera) else None
            por_dia.append({"dia": f"{d:%Y-%m-%d}", "realizado": round(float(serie.get(d, 0)), 1),
                            "previsto": None, "vespera": None if v is None else round(v, 1)})
        else:
            por_dia.append({"dia": f"{d:%Y-%m-%d}", "realizado": None, "vespera": None,
                            "previsto": round(float(esperado[list(faltam).index(d)] * escala), 1)})
    ant = serie.reindex(_dias_uteis(mes - 1)).fillna(0)
    return {"indicador": indicador, "realizado_ate": round(realizado, 1), "prev": round(prev, 1),
            "lo": round(lo, 1), "hi": round(hi, 1), "curva": curva,
            "mes_anterior": _acumulado_por_posicao(serie, mes - 1),
            "mes_retrasado": _acumulado_por_posicao(serie, mes - 2),
            "linear": round(linear, 1), "por_dow": round(realizado + float(esperado.sum()), 1),
            "blend": round(base, 1), "ajuste": round(float(med), 4), "falta_dow": falta_dow,
            "erro_tipico": None if erro_tipico is None else round(erro_tipico, 4),
            "du_passados": int(len(passados)), "du_total": int(len(uteis)), "por_dia": por_dia,
            "mes_anterior_dia": ant.round(1).tolist(), "total_mes_anterior": round(float(ant.sum()), 1),
            "total_mes_retrasado": round(float(serie.reindex(_dias_uteis(mes - 2)).fillna(0).sum()), 1)}
