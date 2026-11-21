"""Registro das previsões e placar: a previsão "de fato" acerta?

O registro é RECONSTRUÍDO: cada dia passado é previsto só com os dias anteriores a ele, nas horas de corte.
    erro (WMAPE)  = Σ|real − previsto| / Σ real     (erro em % do volume, sem explodir em dia pequeno)
    viés          = Σ previsto / Σ real − 1         (positivo = otimista)
    cobertura     = % de dias em que o real caiu dentro da faixa (alvo: 80%)
"""
import pandas as pd

from src.previsao_dia import prever
from src.previsao_mes import prever_mes

TRECHOS = [("inicio", 1, 7), ("meio", 8, 15), ("3/4", 16, 22), ("final", 23, 31)]


def reconstruir_registro_dia(acum, diaria, dias, horas=(10, 12, 14)) -> pd.DataFrame:
    real = diaria.groupby(["dia", "fase"])["cpc_unico"].sum()
    linhas = []
    for d in dias:
        d = pd.Timestamp(d)
        for h in horas:
            r = prever(acum, diaria, d, h)
            if r is None:
                continue
            for escopo, v in [("__TOTAL__", r["total"]), *r["fases"].items()]:
                rv = real.loc[d].sum() if escopo == "__TOTAL__" else real.get((d, escopo), 0)
                linhas.append({"dia": d, "hora": h, "escopo": escopo, "prev": v["prev"], "lo": v["lo"], "esperado": v["esperado"],
                               "hi": v["hi"], "real": float(rv)})
    return pd.DataFrame(linhas, columns=["dia", "hora", "escopo", "prev", "lo", "hi", "esperado", "real"])


def _medidas(g: pd.DataFrame) -> pd.Series:
    return pd.Series({"wmape": (g["real"] - g["prev"]).abs().sum() / g["real"].sum(),
                      "vies": g["prev"].sum() / g["real"].sum() - 1,
                      "cobertura": ((g["real"] >= g["lo"]) & (g["real"] <= g["hi"])).mean(),
                      "dias": len(g)})


def placar(registro: pd.DataFrame, escopo: str = "__TOTAL__") -> pd.DataFrame:
    r = registro[registro["escopo"] == escopo]
    return r.groupby("hora")[["prev", "lo", "hi", "real"]].apply(_medidas).reset_index()


def reconstruir_registro_mes(diaria, dias, indicador="cpc_unico") -> pd.DataFrame:
    total = diaria.groupby("dia")[indicador].sum()
    ultimo = total.index.max()
    linhas = []
    for d in dias:
        d = pd.Timestamp(d)
        fim_mes = pd.bdate_range(d.to_period("M").start_time, d.to_period("M").end_time.normalize())[-1]
        if fim_mes > ultimo:   # mês ainda aberto: não há "real" para comparar
            continue
        r = prever_mes(diaria, d, indicador)
        mes = d.to_period("M")
        real = total[(total.index >= mes.start_time) & (total.index <= mes.end_time)].sum()
        linhas.append({"dia": d, "indicador": indicador, "prev": r["prev"], "lo": r["lo"], "hi": r["hi"],
                       "real": float(real)})
    return pd.DataFrame(linhas, columns=["dia", "indicador", "prev", "lo", "hi", "real"]).astype({"dia": "datetime64[ns]"})


def placar_mes(registro_mes: pd.DataFrame) -> pd.DataFrame:
    dia = registro_mes["dia"].dt.day
    trecho = pd.Series(pd.NA, index=registro_mes.index, dtype="object")
    for nome, a, b in TRECHOS:
        trecho[(dia >= a) & (dia <= b)] = nome
    r = registro_mes.assign(trecho=pd.Categorical(trecho, [t[0] for t in TRECHOS], ordered=True))
    return r.groupby("trecho", observed=True)[["prev", "lo", "hi", "real"]].apply(_medidas).reset_index() \
        .astype({"trecho": str})


def ultimos_dias(registro: pd.DataFrame, n: int = 10, hora: int = 12) -> pd.DataFrame:
    r = registro[(registro["escopo"] == "__TOTAL__") & (registro["hora"] == hora)].sort_values("dia").tail(n)
    return r.assign(erro=(r["prev"] / r["real"] - 1), dentro=(r["real"] >= r["lo"]) & (r["real"] <= r["hi"]))
