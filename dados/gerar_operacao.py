"""Gera uma operação FICTÍCIA de cobrança, hora a hora, para alimentar o painel.

Uso:
    python dados/gerar_operacao.py                    # 18 meses, escala 1
    python dados/gerar_operacao.py --escala 0.2       # base menor (testes/CI)

Saída (padrão em dados/operacao/):
    producao.csv     dia, hora, fase, canal, fups, cpc, cpca, boleto, risco, propostas, operadores
    cpc_eventos.csv  dia, hora, fase, canal, id_contrato   (1 linha por CPC: permite contar CPC ÚNICO)
    estoque.csv      dia, fase, contratos

Como a operação funciona:
    - operadores trabalham em turno (pico de manhã e à tarde); cada um faz ~22 acionamentos (FUPS) por hora;
    - os acionamentos se dividem entre as fases pelo tamanho do estoque; cada fase tem sua taxa de CPC;
    - o mesmo contrato pode ser alcançado mais de uma vez no dia, por isso CPC único < CPC;
    - segunda rende mais, sexta menos; o começo do mês rende mais que o fim;
    - cada dia tem um "humor" próprio e a tarde pode render diferente da manhã: prever o fechamento é difícil
      de verdade.
Episódio de mudança: a partir de 01/10/2026 o estoque da fase 31-90 cai 25% em 3 semanas.

Tudo é sintético: nenhum dado real de cliente ou de empresa.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

FASES = ["Até 30", "31-90", "91-360", "360+"]
CANAIS = ["Discador", "Digital"]
HORAS = list(range(8, 21))
SAIDA_PADRAO = Path(__file__).parent / "operacao"

ESTOQUE_BASE = {"Até 30": 6000, "31-90": 8000, "91-360": 9000, "360+": 7000}
PESO_ESFORCO = {"Até 30": 1.4, "31-90": 1.2, "91-360": 0.9, "360+": 0.6}   # onde a operação concentra esforço
TAXA_CPC = {"Até 30": 0.14, "31-90": 0.10, "91-360": 0.07, "360+": 0.04}
TAXA_CPCA = {"Até 30": 0.30, "31-90": 0.25, "91-360": 0.20, "360+": 0.15}
TICKET = {"Até 30": 3500, "31-90": 6000, "91-360": 9000, "360+": 12000}
CURVA_OPER = np.array([.45, .80, 1.0, 1.0, .70, .55, .85, 1.0, 1.0, .90, .70, .45, .25])   # 8h..20h
BONUS_HORA = np.array([0, .10, .15, .10, 0, -.05, 0, .05, 0, .05, .15, .15, .05])          # taxa de CPC
FATOR_DIA_SEMANA = np.array([1.08, 1.03, 1.00, 0.98, 0.92])
EPISODIO = pd.Timestamp("2026-10-01")


def gerar(saida: Path = SAIDA_PADRAO, inicio="2025-05-19", fim="2026-11-19", escala=1.0, seed=42):
    rng = np.random.default_rng(seed)
    dias = pd.bdate_range(inicio, fim)
    nd = len(dias)

    # ---------- estoque por fase: passeio aleatório lento + episódio ----------
    estoque = {}
    for f in FASES:
        passeio = np.exp(np.cumsum(rng.normal(0, 0.003, nd)))
        queda = np.clip((dias - EPISODIO).days / 21, 0, 1) if f == "31-90" else np.zeros(nd)
        estoque[f] = np.round(ESTOQUE_BASE[f] * escala * passeio * (1 - 0.25 * queda)).astype(int)
    est = pd.DataFrame([(d, f, estoque[f][i]) for i, d in enumerate(dias) for f in FASES],
                       columns=["dia", "fase", "contratos"])

    # ---------- fatores de dia: dia da semana, posição no mês, humor do dia, tarde ----------
    pos_mes = dias.to_series().groupby(dias.to_period("M")).cumcount().to_numpy()
    resto_mes = dias.to_series().groupby(dias.to_period("M")).cumcount(ascending=False).to_numpy()
    fator_mes = np.where(pos_mes < 5, 1.06, np.where(resto_mes < 3, 0.95, 1.0))
    humor = rng.lognormal(0, 0.07, nd)
    tarde = rng.lognormal(0, 0.08, nd)                   # a tarde rende diferente da manhã
    fator_dia = FATOR_DIA_SEMANA[dias.dayofweek] * fator_mes * humor
    oper_base = 60 * escala

    linhas = []
    for i, d in enumerate(dias):
        operadores = np.maximum(1, np.round(oper_base * CURVA_OPER * rng.lognormal(0, 0.05, 13))).astype(int)
        fator_h = np.where(np.array(HORAS) >= 13, tarde[i], 1.0)
        fups_hora = operadores * 22 * fator_dia[i] * fator_h
        peso = np.array([estoque[f][i] * PESO_ESFORCO[f] for f in FASES])
        peso = peso / peso.sum()
        for j, f in enumerate(FASES):
            for canal, share, mult in [("Discador", 0.75, 1.0), ("Digital", 0.25, 0.6)]:
                fups = rng.poisson(fups_hora * peso[j] * share)
                taxa = np.clip(TAXA_CPC[f] * mult * (1 + BONUS_HORA), 0, 1)
                cpc = rng.binomial(fups, taxa)
                cpca = rng.binomial(cpc, TAXA_CPCA[f])
                boleto = rng.binomial(cpca, 0.7)
                propostas = rng.binomial(cpc, 0.05)
                risco = np.round(boleto * TICKET[f] * rng.lognormal(0, 0.3, 13), 2)
                linhas.append(pd.DataFrame({
                    "dia": d, "hora": HORAS, "fase": f, "canal": canal, "fups": fups, "cpc": cpc,
                    "cpca": cpca, "boleto": boleto, "risco": risco, "propostas": propostas,
                    "operadores": operadores}))   # operadores ativos na hora (mesmo valor em todo dia × hora)
    prod = pd.concat(linhas, ignore_index=True)

    # ---------- eventos de CPC: contratos sorteados entre os alcançáveis (30% do estoque) ----------
    idx = np.repeat(np.arange(len(prod)), prod["cpc"].to_numpy())
    ev = prod.loc[idx, ["dia", "hora", "fase", "canal"]].reset_index(drop=True)
    est_map = est.set_index(["dia", "fase"])["contratos"]
    alcancaveis = np.maximum(1, (est_map.loc[list(zip(ev["dia"], ev["fase"]))].to_numpy() * 0.3).astype(int))
    base_id = ev["fase"].map({f: (k + 1) * 1_000_000 for k, f in enumerate(FASES)}).to_numpy()
    ev["id_contrato"] = base_id + (rng.random(len(ev)) * alcancaveis).astype(int)

    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    tabelas = {"producao": prod, "cpc_eventos": ev, "estoque": est}
    for nome, df in tabelas.items():
        df.to_csv(saida / f"{nome}.csv", index=False, date_format="%Y-%m-%d")
    print(f"OK - {nd} dias úteis | " + " | ".join(f"{k} {len(v):,}" for k, v in tabelas.items()))
    return tabelas


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--escala", type=float, default=1.0)
    ap.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    a = ap.parse_args()
    gerar(a.saida, escala=a.escala)
