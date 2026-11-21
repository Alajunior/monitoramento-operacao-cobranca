"""Monta o painel: calcula tudo em Python e grava UM arquivo HTML com os dados embutidos.

    python -m src.montar_painel        # lê dados/operacao/<carteira>/ e grava docs/index.html

Nada de modelo roda no navegador: as previsões de cada hora do "hoje" simulado já vão prontas no JSON.
A carteira principal traz também a aba "Previsões & Mês"; as outras só a visão hora a hora (como no painel real).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.indicadores import carregar, cpc_unico_acumulado, serie_diaria
from src.ofensor import decompor, frase_ofensor
from src.placar import (placar, placar_mes, reconstruir_registro_dia, reconstruir_registro_mes,
                        ultimos_dias)
from src.previsao_dia import ALERTA_DERIVA, erro_12h_recente, prever
from src.previsao_mes import prever_mes

RAIZ = Path(__file__).resolve().parent.parent
PASTA_RAIZ = RAIZ / "dados" / "operacao"
TEMPLATE = Path(__file__).resolve().parent / "painel.html"
CHARTJS = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"
FONTES = "https://fonts.googleapis.com/css2?family=Sora:wght@700;800&family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@600&display=swap"
HORAS = list(range(8, 21))
METRICAS = ["fups", "cpc", "cpca", "boleto", "risco", "risco_cpc", "propostas", "pagos", "valor_pago"]
METRICAS_FAIXA = ["fups", "cpc", "cpca", "boleto", "risco", "estoque"]
MES_PREV = ["cpc_unico", "fups", "cpc", "cpca", "boleto", "propostas", "risco"]
MES_SEM_PREV = ["pagos", "valor_pago"]
DIAS_PAINEL = 70
CARTEIRAS = [("veiculos", "Carteira Veículos", True), ("cartoes", "Carteira Cartões", False),
             ("varejo", "Carteira Varejo", False)]


def atalho(dias, hoje: pd.Timestamp, tipo: str):
    """Dia de comparação. Se o dia exato não existir (fim de semana, mês curto), usa o dia útil anterior."""
    hoje = pd.Timestamp(hoje)
    if tipo == "mes_passado":   # mesmo dia útil (n-ésimo) do mês anterior; se não houver, o último dele
        mes = hoje.to_period("M")
        n = sum(1 for d in dias if d.to_period("M") == mes and d <= hoje)
        ant = [d for d in dias if d.to_period("M") == mes - 1]
        return ant[min(n, len(ant)) - 1] if ant else None
    alvo = {"D-1": hoje - pd.Timedelta(days=1), "D-7": hoje - pd.Timedelta(days=7),
            "mes_anterior": hoje - pd.DateOffset(months=1),
            "sexta": hoje - pd.Timedelta(days=hoje.dayofweek + 3)}[tipo]   # a sexta da semana anterior
    anteriores = [d for d in dias if d <= alvo]
    return max(anteriores) if anteriores else None


def _r(x, n=1):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)


def _registros(df):
    return json.loads(df.to_json(orient="records", date_format="iso", double_precision=4))


def montar_carteira(t: dict, slug: str, nome: str, hoje, com_mes: bool,
                    dias_registro=250, dias_registro_mes=130) -> dict:
    hoje = pd.Timestamp(hoje)
    t = {k: v[v["dia"] <= hoje] for k, v in t.items()}
    p = t["producao"]
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
    producao = {m: np.round(cubo[..., k]).astype(int).tolist() for k, m in enumerate(METRICAS)}
    oper = p[p["dia"].isin(dias)].groupby(["dia", "hora"])["operadores"].first() \
        .reindex(pd.MultiIndex.from_product([dias, HORAS]), fill_value=0).to_numpy().reshape(len(dias), -1)
    cpcu = acum[acum["dia"].isin(dias)].set_index(["dia", "fase", "hora"])["cpc_unico_acum"] \
        .reindex(pd.MultiIndex.from_product([dias, fases, HORAS]), fill_value=0) \
        .to_numpy().reshape(len(dias), len(fases), len(HORAS))
    fups_acum = p.groupby(["dia", "fase", "hora"])["fups"].sum().groupby(level=["dia", "fase"]).cumsum() \
        .reindex(pd.MultiIndex.from_product([dias, fases, HORAS]), fill_value=0) \
        .to_numpy().reshape(len(dias), len(fases), len(HORAS))
    estoque = t["estoque"].set_index(["dia", "fase"])["contratos"] \
        .reindex(pd.MultiIndex.from_product([dias, fases]), fill_value=0).to_numpy().reshape(len(dias), -1)

    faixas_nomes, faixa_share = {}, []
    if "faixas" in t:
        fx = t["faixas"][t["faixas"]["dia"].isin(dias)]
        faixas_nomes = {f: list(dict.fromkeys(fx[fx["fase"] == f]["faixa"])) for f in fases}
        idx = fx.set_index(["dia", "fase", "faixa"])
        faixa_share = [[[[round(float(idx.loc[(d, f, k), f"share_{m}"]), 4) for m in METRICAS_FAIXA]
                         for k in faixas_nomes[f]] for f in fases] for d in dias]

    pos = {d: k for k, d in enumerate(dias)}
    presets = [{tipo: pos.get(atalho(todos, d, tipo)) for tipo in ("D-1", "sexta", "mes_passado", "D-7")}
               for d in dias]
    base = {"slug": slug, "nome": nome, "com_mes": com_mes, "fases": fases, "canais": canais, "horas": HORAS,
            "dias": [f"{d:%Y-%m-%d}" for d in dias], "metricas": METRICAS, "metricas_faixa": METRICAS_FAIXA,
            "producao": producao, "operadores": oper.tolist(), "cpcu_acum": cpcu.tolist(),
            "estoque": estoque.tolist(), "faixas": faixas_nomes, "faixa_share": faixa_share, "presets": presets}
    if not com_mes:
        return base

    # ---------- previsão do "hoje" em cada hora + ofensores ----------
    hoje_i, comp_i = len(dias) - 1, presets[-1]["D-7"]
    previsao, ofensor, decomp = {}, {}, {}
    for h in range(9, 21):
        previsao[str(h)] = prever(acum, diaria, hoje, h)
        por_fase, dec = {}, {}
        for k, f in enumerate(fases):
            def pt(i, fn=np.mean):
                return {"estoque": float(fn(estoque[i, k])), "fups": float(fn(fups_acum[i, k, h - 8])),
                        "cpc_unico": float(fn(cpcu[i, k, h - 8]))}
            hj = pt(hoje_i)
            por_fase[f] = {"atual": hj, "base": pt(slice(hoje_i - 20, hoje_i))}
            if comp_i is not None:
                dec[f] = {kk: _r(v, 1) for kk, v in decompor(hj, pt(comp_i)).items()}
        ofensor[str(h)] = frase_ofensor(por_fase)
        decomp[str(h)] = dec
    real_hoje = diaria[diaria["dia"] == hoje].set_index("fase")["cpc_unico"]

    # ---------- registro reconstruído, placar e confiabilidade ----------
    passados = [d for d in todos if d < hoje]
    reg = reconstruir_registro_dia(acum, diaria, passados[-dias_registro:], horas=tuple(range(9, 21)))
    reg_mes = reconstruir_registro_mes(diaria, passados[-dias_registro_mes:])
    ult = ultimos_dias(reg, n=10)
    ult = ult.assign(erro_5d=[erro_12h_recente(reg[reg["dia"] <= d]) for d in ult["dia"]])
    erro_hoje = erro_12h_recente(reg) if len(reg) else float("nan")
    pf = reg[reg["hora"] == 12]
    placar_fases = {f: _r((g["real"] - g["prev"]).abs().sum() / g["real"].sum(), 4)
                    for f, g in pf[pf["escopo"] != "__TOTAL__"].groupby("escopo")}
    pl = placar(reg)
    t12 = pf[pf["escopo"] == "__TOTAL__"]
    direcao = float((np.sign(t12["prev"] - t12["esperado"]) == np.sign(t12["real"] - t12["esperado"])).mean()) \
        if len(t12) else None
    linha12 = pl[pl["hora"] == 12]
    confiab = {"erro_12h": _r(linha12["wmape"].iloc[0], 4) if len(linha12) else None,
               "cobertura": _r(linha12["cobertura"].iloc[0], 4) if len(linha12) else None,
               "vies": _r(linha12["vies"].iloc[0], 4) if len(linha12) else None,
               "direcao": _r(direcao, 4), "dias": int(len(t12)),
               "erro_por_hora": [{"hora": int(r.hora), "wmape": _r(r.wmape, 4)} for r in pl.itertuples()]}

    # ---------- mês ----------
    mes = hoje.to_period("M")
    no_mes = diaria[diaria["dia"].dt.to_period("M") == mes]
    du = sorted(no_mes["dia"].unique())
    mes_ant = [d for d in todos if d.to_period("M") == mes - 1][:len(du)]   # mesmo número de dias úteis
    prev_mes = {}
    for ind in MES_PREV:
        r = prever_mes(diaria, hoje, ind)
        r["vs_ant"] = _r(r["prev"] / r["total_mes_anterior"] - 1, 4) if r["total_mes_anterior"] else None
        prev_mes[ind] = r
    pm = p[p["dia"].dt.to_period("M") == mes]
    pa = p[p["dia"].isin(mes_ant)]
    sem_prev = {m: {"realizado": _r(pm[m].sum(), 1), "mesmo_ponto_ant": _r(pa[m].sum(), 1)} for m in MES_SEM_PREV}
    canal = pm.groupby("canal")[["boleto", "pagos", "valor_pago"]].sum()
    boletos_canal = [{"canal": c, "emitidos": int(v.boleto), "pagos": int(v.pagos), "valor": _r(v.valor_pago, 0),
                      "conversao": _r(v.pagos / v.boleto, 4) if v.boleto else None} for c, v in canal.iterrows()]
    da, db = diaria[diaria["dia"].isin(du)], diaria[diaria["dia"].isin(mes_ant)]
    funil_mes = {"etapas": [{"m": m, "atual": _r(da[m].sum() / max(len(du), 1), 1),
                             "ant": _r(db[m].sum() / max(len(mes_ant), 1), 1)}
                            for m in ["fups", "cpc", "cpca", "boleto"]],
                 "estoque": _r(da.groupby("dia")["estoque"].sum().mean(), 0),
                 "estoque_ant": _r(db.groupby("dia")["estoque"].sum().mean(), 0),
                 "mes_ant": f"{(mes - 1).strftime('%m/%Y')}"}
    # previsão do mês ao longo do mês atual (o registro só guarda meses fechados, que têm "real")
    total = diaria.groupby("dia")["cpc_unico"].sum()
    serie_mes = pd.DataFrame([{"dia": d, **{k: r[k] for k in ("prev", "lo", "hi")},
                               "realizado_ate": float(total[(total.index.to_period("M") == mes) & (total.index <= d)].sum())}
                              for d in du for r in [prever_mes(diaria, d, "cpc_unico")]])
    fechados = []
    for m, g in reg_mes[reg_mes["dia"].dt.to_period("M") < mes].groupby(reg_mes["dia"].dt.to_period("M")):
        if g["dia"].dt.day.min() > 7:   # o registro começou no meio deste mês: placar incompleto, fica de fora
            continue
        tr = placar_mes(g).set_index("trecho")
        fechados.append({"mes": m.strftime("%m/%Y"), "real": _r(g["real"].iloc[0], 0),
                         **{k: _r(tr["wmape"].get(k), 4) for k in ["inicio", "meio", "3/4", "final"]},
                         "cobertura": _r(((g["real"] >= g["lo"]) & (g["real"] <= g["hi"])).mean(), 4)})

    return {**base, "previsao_hoje": previsao, "ofensor": ofensor, "decomp": decomp, "comp_dia": comp_i,
            "fechamento_real_hoje": {"total": int(real_hoje.sum()), "fases": {f: int(real_hoje.get(f, 0)) for f in fases}},
            "alerta": {"erro_12h_5d": _r(erro_hoje, 4), "limite": ALERTA_DERIVA,
                       "ativo": bool(np.isfinite(erro_hoje) and erro_hoje > ALERTA_DERIVA)},
            "placar_dia": _registros(pl[pl["hora"].isin([10, 12, 14])]), "placar_fases": placar_fases,
            "confiab": confiab, "placar_mes": _registros(placar_mes(reg_mes)) if len(reg_mes) else [],
            "placar_mes_serie": _registros(serie_mes[["dia", "prev", "lo", "hi", "realizado_ate"]]),
            "meses_fechados": fechados, "registro_desde": f"{passados[-dias_registro]:%Y-%m-%d}" if passados else None,
            "ultimos_dias": _registros(ult[["dia", "prev", "lo", "hi", "real", "erro", "dentro", "erro_5d"]]),
            "mes": prev_mes, "mes_sem_prev": sem_prev, "boletos_canal": boletos_canal, "funil_mes": funil_mes,
            "relogio": {"du_passados": len(du), "du_total": prev_mes["cpc_unico"]["du_total"],
                        "dia": int(hoje.day), "dias_mes": int(hoje.days_in_month), "mes": mes.strftime("%m/%Y")}}


def montar_dados(pasta_raiz=PASTA_RAIZ, hoje="2026-11-19", **kw) -> dict:
    carteiras = []
    for slug, nome, com_mes in CARTEIRAS:
        pasta = Path(pasta_raiz) / slug
        if pasta.exists():
            carteiras.append(montar_carteira(carregar(pasta), slug, nome, hoje, com_mes, **kw))
    return {"hoje": f"{pd.Timestamp(hoje):%Y-%m-%d}", "carteiras": carteiras}


def montar_html(dados: dict) -> str:
    js = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    return (TEMPLATE.read_text(encoding="utf-8").replace("/*__DADOS__*/", js)
            .replace("__CHARTJS__", CHARTJS).replace("__FONTES__", FONTES))


def main(pasta=PASTA_RAIZ, saida=RAIZ / "docs" / "index.html"):
    html = montar_html(montar_dados(pasta))
    Path(saida).parent.mkdir(parents=True, exist_ok=True)
    Path(saida).write_text(html, encoding="utf-8")
    print(f"painel gravado em {saida} ({len(html.encode('utf-8')) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
