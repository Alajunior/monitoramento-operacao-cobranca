"""Quem puxou o CPC único para baixo? Decomposição LMDI em estoque × esforço × taxa.

    CPC único = Estoque × (FUPS / Estoque) × (CPC único / FUPS)
                 carteira    esforço por contrato   taxa de sucesso
LMDI aditivo: a variação total se divide exatamente entre os três fatores (a soma fecha).
"""
import math

NOMES = {"estoque": "pela queda de estoque", "esforco": "pelo menor esforço (acionamentos por contrato)",
         "taxa": "pela taxa de contato menor"}


def _media_log(a: float, b: float) -> float:
    return a if a == b else (a - b) / math.log(a / b)


def decompor(atual: dict, base: dict) -> dict:
    v1, v0 = atual["cpc_unico"], base["cpc_unico"]
    if min(v1, v0, atual["estoque"], base["estoque"], atual["fups"], base["fups"]) <= 0:
        return {"estoque": 0.0, "esforco": 0.0, "taxa": 0.0, "delta": float(v1 - v0)}
    fatores = {"estoque": (atual["estoque"], base["estoque"]),
               "esforco": (atual["fups"] / atual["estoque"], base["fups"] / base["estoque"]),
               "taxa": (v1 / atual["fups"], v0 / base["fups"])}
    L = _media_log(v1, v0)
    out = {k: L * math.log(x1 / x0) for k, (x1, x0) in fatores.items()}
    out["delta"] = float(v1 - v0)
    return out


def frase_ofensor(por_fase: dict[str, dict]) -> str:
    """por_fase = {fase: {"atual": {...}, "base": {...}}} → frase com a fase e o fator que mais puxaram para baixo."""
    atual = sum(f["atual"]["cpc_unico"] for f in por_fase.values())
    base = sum(f["base"]["cpc_unico"] for f in por_fase.values())
    var = atual / base - 1 if base else 0.0
    sentido = "abaixo" if var < 0 else "acima"
    pior = min(((fase, fator, valor) for fase, f in por_fase.items()
                for fator, valor in decompor(f["atual"], f["base"]).items() if fator != "delta"),
               key=lambda x: x[2])
    if abs(var) < 0.03:
        return f"CPC único em linha com o esperado ({var:+.0%})."
    if var < 0 and pior[2] < 0:
        return f"CPC único {abs(var):.0%} {sentido} do esperado, puxado {NOMES[pior[1]]} na fase {pior[0]}."
    return f"CPC único {abs(var):.0%} {sentido} do esperado."
