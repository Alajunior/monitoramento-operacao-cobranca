import pytest

from dados.gerar_operacao import gerar


@pytest.fixture(scope="session")
def pasta_pequena(tmp_path_factory):
    """Operação reduzida: 8 meses, escala 0,2 (inclui o episódio de estoque de out/2026)."""
    pasta = tmp_path_factory.mktemp("operacao")
    gerar(pasta, inicio="2026-03-02", escala=0.2, carteira="veiculos")
    return pasta
