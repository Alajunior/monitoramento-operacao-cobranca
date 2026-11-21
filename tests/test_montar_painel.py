import json
import re

import pandas as pd
import pytest

from src.indicadores import carregar
from src.montar_painel import CHARTJS, FONTES, atalho, montar_carteira, montar_html

CHAVES_MES = {"previsao_hoje", "ofensor", "decomp", "fechamento_real_hoje", "alerta", "placar_dia", "placar_fases",
              "confiab", "placar_mes", "placar_mes_serie", "meses_fechados", "ultimos_dias", "mes", "mes_sem_prev",
              "boletos_canal", "funil_mes", "relogio"}


@pytest.fixture(scope="module")
def principal(pasta_pequena):
    return montar_carteira(carregar(pasta_pequena), "veiculos", "Carteira Veículos", "2026-11-19", True,
                           dias_registro=15, dias_registro_mes=5)


@pytest.fixture(scope="module")
def secundaria(pasta_pequena):
    return montar_carteira(carregar(pasta_pequena), "cartoes", "Carteira Cartões", "2026-11-19", False)


def test_atalhos_de_comparacao():
    dias = list(pd.bdate_range("2026-01-02", "2026-11-19"))
    assert atalho(dias, pd.Timestamp("2026-11-16"), "D-1") == pd.Timestamp("2026-11-13")
    assert atalho(dias, pd.Timestamp("2026-11-19"), "D-7") == pd.Timestamp("2026-11-12")
    assert atalho(dias, pd.Timestamp("2026-03-31"), "mes_anterior") == pd.Timestamp("2026-02-27")
    assert atalho(dias, pd.Timestamp("2026-11-19"), "sexta") == pd.Timestamp("2026-11-13")
    assert atalho(dias, pd.Timestamp("2026-11-19"), "mes_passado") == pd.Timestamp("2026-10-20")   # 14º dia útil


def test_presets_pre_calculados(principal):
    pr, dias = principal["presets"], principal["dias"]
    assert dias[pr[-1]["D-7"]] == "2026-11-12" and dias[pr[-1]["D-1"]] == "2026-11-18"
    assert dias[pr[-1]["mes_passado"]] == "2026-10-20"
    assert pr[0]["D-1"] is None and pr[0]["mes_passado"] is None   # fora da janela de 70 dias: sem atalho


def test_carteira_principal_tem_o_mes(principal):
    assert CHAVES_MES <= set(principal) and principal["com_mes"]
    assert len(principal["dias"]) == 70 and principal["dias"][-1] == "2026-11-19"
    assert set(principal["previsao_hoje"]) == {str(h) for h in range(9, 21)}
    assert set(principal["mes"]) == {"cpc_unico", "fups", "cpc", "cpca", "boleto", "propostas", "risco"}
    assert len(principal["faixa_share"]) == 70
    json.dumps(principal)


def test_carteira_secundaria_so_hora_a_hora(secundaria):
    assert not secundaria["com_mes"] and "mes" not in secundaria and "previsao_hoje" not in secundaria


def test_html_autocontido(principal, secundaria):
    html = montar_html({"hoje": "2026-11-19", "carteiras": [principal, secundaria]})
    assert "const DADOS = {" in html
    assert "fetch(" not in html and 'type="module"' not in html and not re.search(r"^\s*import ", html, re.M)
    assert set(re.findall(r"https://[^\s\"'<>)]+", html)) <= {CHARTJS, FONTES}
    assert len(html.encode("utf-8")) < 5 * 1024 * 1024
