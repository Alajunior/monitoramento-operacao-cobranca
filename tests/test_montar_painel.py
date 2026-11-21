import json
import re

import pandas as pd
import pytest

from src.indicadores import carregar
from src.montar_painel import CHARTJS, atalho, montar_dados, montar_html

CHAVES = {"hoje", "fases", "canais", "horas", "dias", "producao", "operadores", "cpcu_acum", "fups_acum", "estoque",
          "previsao_hoje", "fechamento_real_hoje", "ofensor", "alerta", "mes", "placar_dia", "placar_fases",
          "placar_mes", "ultimos_dias"}


@pytest.fixture(scope="module")
def dados(pasta_pequena):
    return montar_dados(carregar(pasta_pequena), hoje="2026-11-19", dias_registro=15, dias_registro_mes=5)


def test_atalhos_de_comparacao():
    dias = list(pd.bdate_range("2026-01-02", "2026-11-19"))
    assert atalho(dias, pd.Timestamp("2026-11-16"), "D-1") == pd.Timestamp("2026-11-13")
    assert atalho(dias, pd.Timestamp("2026-11-19"), "D-7") == pd.Timestamp("2026-11-12")
    assert atalho(dias, pd.Timestamp("2026-03-31"), "mes_anterior") == pd.Timestamp("2026-02-27")


def test_dados_tem_todas_as_chaves(dados):
    assert CHAVES <= set(dados)
    assert dados["hoje"] == "2026-11-19" and dados["dias"][-1] == "2026-11-19"
    assert len(dados["dias"]) == 70
    assert set(dados["previsao_hoje"]) == {str(h) for h in range(9, 21)}
    json.dumps(dados)   # serializável


def test_html_autocontido(dados):
    html = montar_html(dados)
    assert "const DADOS = {" in html
    assert "fetch(" not in html and 'type="module"' not in html and not re.search(r"^\s*import ", html, re.M)
    assert set(re.findall(r"https://[^\s\"'<>)]+", html)) == {CHARTJS}
    assert len(html.encode("utf-8")) < 5 * 1024 * 1024


def test_atalhos_pre_calculados(dados):
    at, dias = dados["atalhos"], dados["dias"]
    hoje = len(dias) - 1
    assert dias[at[hoje]["D-7"]] == "2026-11-12"
    assert dias[at[hoje]["D-1"]] == "2026-11-18"
    assert at[0]["D-1"] is None and at[0]["mes_anterior"] is None   # fora da janela de 70 dias: sem atalho
