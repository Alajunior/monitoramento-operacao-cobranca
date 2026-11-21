import pytest

from src.ofensor import decompor, frase_ofensor


def test_lmdi_soma_fecha():
    d = decompor({"estoque": 900, "fups": 2000, "cpc_unico": 180}, {"estoque": 1000, "fups": 2100, "cpc_unico": 210})
    assert d["estoque"] + d["esforco"] + d["taxa"] == pytest.approx(d["delta"], abs=1e-9)
    assert d["delta"] == pytest.approx(-30)


def test_so_estoque_muda():
    # estoque cai 10%, FUPS cai 10% (esforço por contrato igual) e a taxa CPCu/FUPS fica igual
    d = decompor({"estoque": 900, "fups": 1800, "cpc_unico": 180}, {"estoque": 1000, "fups": 2000, "cpc_unico": 200})
    assert d["esforco"] == pytest.approx(0, abs=1e-9) and d["taxa"] == pytest.approx(0, abs=1e-9)
    assert d["estoque"] == pytest.approx(-20)


def test_frase_aponta_maior_ofensor():
    por_fase = {
        "Até 30": {"atual": {"estoque": 1000, "fups": 2000, "cpc_unico": 200},
                   "base": {"estoque": 1000, "fups": 2000, "cpc_unico": 205}},
        "31-90": {"atual": {"estoque": 750, "fups": 1500, "cpc_unico": 150},
                  "base": {"estoque": 1000, "fups": 2000, "cpc_unico": 200}},
    }
    f = frase_ofensor(por_fase)
    assert "estoque" in f and "31-90" in f and "abaixo" in f
