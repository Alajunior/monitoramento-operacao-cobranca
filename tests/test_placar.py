import pandas as pd
import pytest

from src.indicadores import carregar, cpc_unico_acumulado, serie_diaria
from src.placar import placar, placar_mes, reconstruir_registro_dia, ultimos_dias
from src.previsao_dia import prever


def test_placar_valores_conhecidos():
    reg = pd.DataFrame({"dia": pd.to_datetime(["2026-11-17", "2026-11-18"]), "hora": 12, "escopo": "__TOTAL__",
                        "prev": [110.0, 90.0], "lo": [95.0, 80.0], "hi": [120.0, 99.0], "real": [100.0, 100.0]})
    p = placar(reg).set_index("hora")
    assert p.loc[12, "wmape"] == pytest.approx(0.10)
    assert p.loc[12, "vies"] == pytest.approx(0.0)
    assert p.loc[12, "cobertura"] == pytest.approx(0.5)   # 100 em [95,120] sim; 100 em [80,99] não


def test_placar_mes_por_trecho():
    reg = pd.DataFrame({"dia": pd.to_datetime(["2026-10-02", "2026-10-28"]), "indicador": "cpc_unico",
                        "prev": [100.0, 100.0], "lo": [90.0, 99.0], "hi": [110.0, 101.0], "real": [100.0, 100.0]})
    p = placar_mes(reg).set_index("trecho")
    assert list(p.index) == ["inicio", "final"]
    assert p.loc["final", "wmape"] == 0.0


def test_registro_nao_usa_o_dia(pasta_pequena):
    t = carregar(pasta_pequena)
    acum, diaria = cpc_unico_acumulado(t["cpc_eventos"]), serie_diaria(t)
    dias = sorted(diaria["dia"].unique())[-3:]
    reg = reconstruir_registro_dia(acum, diaria, dias, horas=(12,))
    d = dias[0]
    linha = reg[(reg.dia == d) & (reg.escopo == "__TOTAL__")].iloc[0]
    assert linha["prev"] == prever(acum, diaria, d, 12)["total"]["prev"]
    assert linha["real"] == diaria[diaria.dia == d]["cpc_unico"].sum()
    assert len(ultimos_dias(reg, n=2)) == 2
