"""Monta o painel: calcula tudo em Python e grava UM arquivo HTML com os dados embutidos.

    python -m src.montar_painel        # lê dados/operacao/ e grava docs/index.html

Nada de modelo roda no navegador: as previsões de cada hora do "hoje" simulado já vão prontas no JSON.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.indicadores import PASTA, carregar, cpc_unico_acumulado, serie_diaria
from src.ofensor import frase_ofensor
from src.placar import (placar, placar_mes, reconstruir_registro_dia, reconstruir_registro_mes,
                        ultimos_dias)
from src.previsao_dia import ALERTA_DERIVA, erro_12h_recente, prever
from src.previsao_mes import INDICADORES, prever_mes

RAIZ = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).resolve().parent / "painel.html"
CHARTJS = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"
HORAS = list(range(8, 21))
METRICAS = ["fups", "cpc", "cpca", "boleto", "risco", "propostas"]
DIAS_PAINEL = 70


def atalho(dias, hoje: pd.Timestamp, tipo: str) -> pd.Timestamp:
    """Dia de comparação. Se o dia exato não existir (fim de semana, mês curto), usa o dia útil anterior."""
    alvo = {"D-1": hoje - pd.Timedelta(days=1), "D-7": hoje - pd.Timedelta(days=7),
            "mes_anterior": hoje - pd.DateOffset(months=1)}[tipo]
    anteriores = [d for d in dias if d <= alvo]
    return max(anteriores)


def _r(x, n=1):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)


def montar_dados(t: dict, hoje="2026-11-19", dias_registro=250, dias_registro_mes=130) -> dict:
    hoje = pd.Timestamp(hoje)
    p = t["producao"][t["producao"]["dia"] <= hoje]
    t = {**t, "producao": p, "cpc_eventos": t["cpc_eventos"][t["cpc_eventos"]["dia"] <= hoje],
         "estoque": t["estoque"][t["estoque"]["dia"] <= hoje]}
    fases, canais = list(dict.fromkeys(p["fase"])), list(dict.fromkeys(p["canal"]))
    todos = sorted(p["dia"].unique())
    dias = todos[-DIAS_PAINEL:]
    acum = cpc_unico_acumulado(t["cpc_eventos"])
    diaria = serie_diaria(t)

    # ---------- operação dos últimos 70 dias: arrays [dia][hora][fase][canal] ----------
    pj = p[p["dia"].isin(dias)].set_index(["dia", "hora", "fase", "canal"]).sort_index()
    grade = pd.MultiIndex.from_product([dias, HORAS, fases, canais])
    cubo = pj[METRICAS].reindex(grade, fill_value=0).to_numpy().reshape(len(dias), len(HORAS), len(fases),
                                                                        len(canais), len(METRICAS))
    producao = {m: np.round(cubo[..., k], 2).tolist() for k, m in enumerate(METRICAS)}
    oper = p[p["dia"].isin(dias)].groupby(["dia", "hora"])["operadores"].first() \
        .reindex(pd.MultiIndex.from_product([dias, HORAS]), fill_value=0).to_numpy().reshape(len(dias), -1)
    ac = acum[acum["dia"].isin(dias)].set_index(["dia", "fase", "hora"])["cpc_unico_acum"] \
        .reindex(pd.MultiIndex.from_product([dias, fases, HORAS]), fill_value=0)
    cpcu = ac.to_numpy().reshape(len(dias), len(fases), len(HORAS))
    fups_h = p.groupby(["dia", "fase", "hora"])["fups"].sum().groupby(level=["dia", "fase"]).cumsum()
    fups_acum = fups_h.reindex(pd.MultiIndex.from_product([dias, fases, HORAS]), fill_value=0) \
        .to_numpy().reshape(len(dias), len(fases), len(HORAS))
    est = t["estoque"].set_index(["dia", "fase"])["contratos"]
    estoque = est.reindex(pd.MultiIndex.from_product([dias, fases]), fill_value=0).to_numpy().reshape(len(dias), -1)

    # ---------- previsão do "hoje" em cada hora + ofensor (vs. média dos 20 dias anteriores na mesma hora) ----------
    previsao, ofensor = {}, {}
    for h in range(9, 21):
        previsao[str(h)] = prever(acum, diaria, hoje, h)
        por_fase = {}
        for k, f in enumerate(fases):
            hj = {"estoque": float(estoque[-1, k]), "fups": float(fups_acum[-1, k, h - 8]),
                  "cpc_unico": float(cpcu[-1, k, h - 8])}
            base = {"estoque": float(estoque[-21:-1, k].mean()), "fups": float(fups_acum[-21:-1, k, h - 8].mean()),
                    "cpc_unico": float(cpcu[-21:-1, k, h - 8].mean())}
            por_fase[f] = {"atual": hj, "base": base}
        ofensor[str(h)] = frase_ofensor(por_fase)
    real_hoje = diaria[diaria["dia"] == hoje].set_index("fase")["cpc_unico"]

    # ---------- registro reconstruído e placar ----------
    passados = [d for d in todos if d < hoje]
    reg = reconstruir_registro_dia(acum, diaria, passados[-dias_registro:])
    reg_mes = reconstruir_registro_mes(diaria, passados[-dias_registro_mes:])
    ult = ultimos_dias(reg, n=10)
    ult = ult.assign(erro_5d=[erro_12h_recente(reg[reg["dia"] <= d]) for d in ult["dia"]])
    erro_hoje = erro_12h_recente(reg) if len(reg) else float("nan")
    pf = reg[reg["hora"] == 12]
    placar_fases = {f: _r((g["real"] - g["prev"]).abs().sum() / g["real"].sum(), 4)
                    for f, g in pf[pf["escopo"] != "__TOTAL__"].groupby("escopo")}

    # atalhos de comparação de cada dia da janela (índice na janela, ou None se o alvo cair fora dela)
    pos = {d: k for k, d in enumerate(dias)}
    atalhos = [{tipo: pos.get(atalho(todos, d, tipo)) for tipo in ("D-1", "D-7", "mes_anterior")} for d in dias]

    def registros(df):
        return json.loads(df.to_json(orient="records", date_format="iso", double_precision=4))

    return {
        "hoje": f"{hoje:%Y-%m-%d}", "fases": fases, "canais": canais, "horas": HORAS,
        "dias": [f"{d:%Y-%m-%d}" for d in dias], "metricas": METRICAS, "atalhos": atalhos,
        "producao": producao, "operadores": oper.tolist(), "cpcu_acum": cpcu.tolist(),
        "fups_acum": fups_acum.tolist(), "estoque": estoque.tolist(),
        "previsao_hoje": previsao, "ofensor": ofensor,
        "fechamento_real_hoje": {"total": int(real_hoje.sum()), "fases": {f: int(real_hoje.get(f, 0)) for f in fases}},
        "alerta": {"erro_12h_5d": _r(erro_hoje, 4), "limite": ALERTA_DERIVA,
                   "ativo": bool(np.isfinite(erro_hoje) and erro_hoje > ALERTA_DERIVA)},
        "mes": {ind: prever_mes(diaria, hoje, ind) for ind in INDICADORES},
        "placar_dia": registros(placar(reg)) if len(reg) else [],
        "placar_fases": placar_fases,
        "placar_mes": registros(placar_mes(reg_mes)) if len(reg_mes) else [],
        "ultimos_dias": registros(ult[["dia", "prev", "lo", "hi", "real", "erro", "dentro", "erro_5d"]]),
    }


def montar_html(dados: dict) -> str:
    js = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    return TEMPLATE.read_text(encoding="utf-8").replace("/*__DADOS__*/", js).replace("__CHARTJS__", CHARTJS)


def main(pasta=PASTA, saida=RAIZ / "docs" / "index.html"):
    html = montar_html(montar_dados(carregar(pasta)))
    Path(saida).parent.mkdir(parents=True, exist_ok=True)
    Path(saida).write_text(html, encoding="utf-8")
    print(f"painel gravado em {saida} ({len(html.encode('utf-8')) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
