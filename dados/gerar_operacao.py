"""Gera uma operação FICTÍCIA de cobrança, hora a hora, para alimentar o painel.

Uso:
    python dados/gerar_operacao.py                    # 3 carteiras, 18 meses, em dados/operacao/<carteira>/
    python dados/gerar_operacao.py --escala 0.2       # bases menores

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
Episódios de mudança:
    - a partir de 01/10/2026 o estoque da fase 31-90 cai 25% em 3 semanas (o volume cai, o ritmo do dia não);
    - a partir de 05/11/2026 a tarde passa a render 15% menos (o ritmo muda: a previsão das 12h erra para cima).

Tudo é sintético: nenhum dado real de cliente ou de empresa.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

CANAIS = ["Discador", "Digital"]
HORAS = list(range(8, 21))
SAIDA_PADRAO = Path(__file__).parent / "operacao"

# Cada carteira: fases (faixa de atraso), faixas dentro da fase, estoque, onde se concentra o esforço, taxas e ticket.
CARTEIRAS = {
    "veiculos": {
        "nome": "Carteira Veículos", "escala": 1.0, "seed": 42, "oper": 60, "episodios": True,
        "fases": ["Até 30", "31-90", "91-360", "360+"],
        "faixas": {"Até 30": ["01-15", "16-30"], "31-90": ["31-60", "61-90"], "91-360": ["91-180", "181-360"],
                   "360+": ["361-720", "720+"]},
        "estoque": {"Até 30": 6000, "31-90": 8000, "91-360": 9000, "360+": 7000},
        "esforco": {"Até 30": 1.4, "31-90": 1.2, "91-360": 0.9, "360+": 0.6},
        "taxa_cpc": {"Até 30": 0.14, "31-90": 0.10, "91-360": 0.07, "360+": 0.04},
        "taxa_cpca": {"Até 30": 0.30, "31-90": 0.25, "91-360": 0.20, "360+": 0.15},
        "ticket": {"Até 30": 3500, "31-90": 6000, "91-360": 9000, "360+": 12000},
    },
    "cartoes": {
        "nome": "Carteira Cartões", "escala": 0.7, "seed": 7, "oper": 45, "episodios": False,
        "fases": ["Até 60", "61-180", "180+"],
        "faixas": {"Até 60": ["01-30", "31-60"], "61-180": ["61-90", "91-180"], "180+": ["181-360", "360+"]},
        "estoque": {"Até 60": 9000, "61-180": 11000, "180+": 14000},
        "esforco": {"Até 60": 1.5, "61-180": 1.0, "180+": 0.5},
        "taxa_cpc": {"Até 60": 0.11, "61-180": 0.07, "180+": 0.03},
        "taxa_cpca": {"Até 60": 0.22, "61-180": 0.17, "180+": 0.12},
        "ticket": {"Até 60": 1800, "61-180": 2600, "180+": 3400},
    },
    "varejo": {
        "nome": "Carteira Varejo", "escala": 0.5, "seed": 11, "oper": 35, "episodios": False,
        "fases": ["Até 90", "91-360", "360+"],
        "faixas": {"Até 90": ["01-30", "31-90"], "91-360": ["91-180", "181-270", "271-360"], "360+": ["361-720", "720+"]},
        "estoque": {"Até 90": 7000, "91-360": 8000, "360+": 9000},
        "esforco": {"Até 90": 1.4, "91-360": 1.0, "360+": 0.6},
        "taxa_cpc": {"Até 90": 0.12, "91-360": 0.08, "360+": 0.04},
        "taxa_cpca": {"Até 90": 0.26, "91-360": 0.19, "360+": 0.13},
        "ticket": {"Até 90": 1200, "91-360": 1700, "360+": 2300},
    },
}
FASES = CARTEIRAS["veiculos"]["fases"]   # compatibilidade com a v1
PAGA = {"Discador": 0.55, "Digital": 0.70}   # boletos que viram pagamento no mês
METRICAS_FAIXA = ["fups", "cpc", "cpca", "boleto", "risco", "estoque"]
CURVA_OPER = np.array([.45, .80, 1.0, 1.0, .70, .55, .85, 1.0, 1.0, .90, .70, .45, .25])   # 8h..20h
BONUS_HORA = np.array([0, .10, .15, .10, 0, -.05, 0, .05, 0, .05, .15, .15, .05])          # taxa de CPC
FATOR_DIA_SEMANA = np.array([1.08, 1.03, 1.00, 0.98, 0.92])
EPISODIO = pd.Timestamp("2026-10-01")
EPISODIO_TARDE = pd.Timestamp("2026-11-05")   # nova escala de turno: a tarde passa a render 15% menos


def gerar(saida: Path = SAIDA_PADRAO, inicio="2025-05-19", fim="2026-11-19", escala=None, seed=None,
          carteira="veiculos"):
    cfg = CARTEIRAS[carteira]
    escala = cfg["escala"] if escala is None else escala
    seed = cfg["seed"] if seed is None else seed
    FASES, ESTOQUE_BASE, PESO_ESFORCO = cfg["fases"], cfg["estoque"], cfg["esforco"]
    TAXA_CPC, TAXA_CPCA, TICKET = cfg["taxa_cpc"], cfg["taxa_cpca"], cfg["ticket"]
    rng = np.random.default_rng(seed)
    rng2 = np.random.default_rng(seed + 1000)   # dados novos (v2) num gerador à parte: a v1 continua idêntica
    dias = pd.bdate_range(inicio, fim)
    nd = len(dias)

    # ---------- estoque por fase: passeio aleatório lento + episódio ----------
    estoque = {}
    for f in FASES:
        passeio = np.exp(np.cumsum(rng.normal(0, 0.003, nd)))
        queda = np.clip((dias - EPISODIO).days / 21, 0, 1) if (cfg["episodios"] and f == "31-90") else np.zeros(nd)
        estoque[f] = np.round(ESTOQUE_BASE[f] * escala * passeio * (1 - 0.25 * queda)).astype(int)
    est = pd.DataFrame([(d, f, estoque[f][i]) for i, d in enumerate(dias) for f in FASES],
                       columns=["dia", "fase", "contratos"])

    # ---------- fatores de dia: dia da semana, posição no mês, humor do dia, tarde ----------
    pos_mes = dias.to_series().groupby(dias.to_period("M")).cumcount().to_numpy()
    resto_mes = dias.to_series().groupby(dias.to_period("M")).cumcount(ascending=False).to_numpy()
    fator_mes = np.where(pos_mes < 5, 1.06, np.where(resto_mes < 3, 0.95, 1.0))
    humor = rng.lognormal(0, 0.07, nd)
    tarde = rng.lognormal(0, 0.08, nd) * np.where(cfg["episodios"] & (dias >= EPISODIO_TARDE), 0.85, 1.0)
    fator_dia = FATOR_DIA_SEMANA[dias.dayofweek] * fator_mes * humor
    oper_base = cfg["oper"] * escala

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
    prod["pagos"] = rng2.binomial(prod["boleto"].to_numpy(), prod["canal"].map(PAGA).to_numpy())
    ticket = prod["fase"].map(TICKET).to_numpy()
    prod["valor_pago"] = np.round(prod["pagos"] * ticket * 0.45 * rng2.lognormal(0, 0.25, len(prod)), 2)

    # ---------- faixas dentro de cada fase: participação de cada faixa em cada métrica, mudando devagar ----------
    faixas = []
    for f in FASES:
        nomes = cfg["faixas"][f]
        k = len(nomes)
        base = rng2.dirichlet(np.full(k, 6.0))
        deriva = np.exp(np.cumsum(rng2.normal(0, 0.01, (nd, k)), axis=0))
        inclina = {m: np.linspace(1.18, 0.82, k) if m in ("cpc", "cpca", "boleto") else
                   (np.linspace(0.9, 1.1, k) if m == "estoque" else np.ones(k)) for m in METRICAS_FAIXA}
        for i, d in enumerate(dias):
            partes = {}
            for m in METRICAS_FAIXA:
                w = base * deriva[i] * inclina[m]
                partes[m] = w / w.sum()
            for j, nome in enumerate(nomes):
                faixas.append({"dia": d, "fase": f, "faixa": nome,
                               **{f"share_{m}": round(float(partes[m][j]), 6) for m in METRICAS_FAIXA}})
    fx = pd.DataFrame(faixas)
    cols = [f"share_{m}" for m in METRICAS_FAIXA]
    fx[cols] = fx[cols] / fx.groupby(["dia", "fase"])[cols].transform("sum")   # soma exata 1 após arredondar
    # valor em risco dos contratos alcançados (CPC): o que estava em jogo nas conversas certas
    prod["risco_cpc"] = np.round(prod["cpc"] * ticket * rng2.lognormal(0, 0.3, len(prod)), 2)

    # ---------- eventos de CPC: contratos sorteados entre os alcançáveis (30% do estoque) ----------
    idx = np.repeat(np.arange(len(prod)), prod["cpc"].to_numpy())
    ev = prod.loc[idx, ["dia", "hora", "fase", "canal"]].reset_index(drop=True)
    est_map = est.set_index(["dia", "fase"])["contratos"]
    alcancaveis = np.maximum(1, (est_map.loc[list(zip(ev["dia"], ev["fase"]))].to_numpy() * 0.3).astype(int))
    base_id = ev["fase"].map({f: (k + 1) * 1_000_000 for k, f in enumerate(FASES)}).to_numpy()
    ev["id_contrato"] = base_id + (rng.random(len(ev)) * alcancaveis).astype(int)

    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    tabelas = {"producao": prod, "cpc_eventos": ev, "estoque": est, "faixas": fx}
    for nome, df in tabelas.items():
        df.to_csv(saida / f"{nome}.csv", index=False, date_format="%Y-%m-%d")
    print(f"OK - {nd} dias úteis | " + " | ".join(f"{k} {len(v):,}" for k, v in tabelas.items()))
    return tabelas


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--escala", type=float, default=None, help="multiplica o tamanho de cada carteira")
    ap.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    a = ap.parse_args()
    for slug, cfg in CARTEIRAS.items():   # uma pasta por carteira
        print(cfg["nome"], end=": ")
        gerar(a.saida / slug, escala=None if a.escala is None else cfg["escala"] * a.escala, carteira=slug)
