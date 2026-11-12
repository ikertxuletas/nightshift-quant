from quant.investigacion import fuentes

ARXIV = """<feed><entry><id>http://arxiv.org/abs/2609.00001v1</id>
<title>Momentum en divisas</title><published>2026-09-01T00:00:00Z</published>
<summary>Compramos el par con mas momentum a 12 meses.</summary></entry></feed>"""

LISTADO_QP = '<a href="/strategies/asset-class-trend-following">x</a> <a href="/strategies/corta">y</a>'
PAGINA_QP = "<html><style>a{}</style><body><h1>Trend following</h1><p>" + "regla de entrada. " * 200 + "</p></body></html>"

RSS = """<feed><entry><title>Mi sistema de rupturas</title><link href="https://reddit.com/x"/>
<updated>2026-09-10T10:00:00Z</updated><content type="html">&lt;p&gt;compro maximos de 20 dias&lt;/p&gt;</content></entry></feed>"""

LISTADO_MQL5 = '<a href="/en/code/77386">EA</a><a href="/en/code/77386">repe</a>'
PAGINA_MQL5 = ("<html><head><title>Cruce de medias - MQL5 Code Base</title></head>"
               "<body><h2>Cruce de medias</h2><pre>int OnInit()</pre></body></html>")


def test_texto_plano():
    limpio = fuentes.texto_plano("<script>malo()</script><p>Hola &amp; adios</p>   <b>ya</b>")
    assert limpio == "Hola & adios ya"


def test_arxiv_sin_pdf(sesion_falsa):
    s = sesion_falsa({fuentes.URL_ARXIV.format(n=5): ARXIV.encode()})
    docs = fuentes.arxiv(s, 5, dormir=lambda x: None)
    assert len(docs) == 1
    d = docs[0]
    assert d["fuente"] == "arxiv" and d["url"] == "http://arxiv.org/abs/2609.00001v1"
    assert d["titulo"] == "Momentum en divisas" and d["fecha"].startswith("2026-09-01")
    assert "momentum a 12 meses" in d["texto"]


def test_quantpedia_descarta_paginas_cortas(sesion_falsa):
    s = sesion_falsa({fuentes.URL_QUANTPEDIA: LISTADO_QP.encode(),
                      "https://quantpedia.com/strategies/asset-class-trend-following": PAGINA_QP.encode(),
                      "https://quantpedia.com/strategies/corta": b"<html><body>poco texto</body></html>"})
    docs = fuentes.quantpedia(s, 10, dormir=lambda x: None)
    assert [d["titulo"] for d in docs] == ["asset-class-trend-following"]
    assert "a{}" not in docs[0]["texto"]


def test_reddit(sesion_falsa):
    s = sesion_falsa({fuentes.URL_REDDIT.format(sub="algotrading"): RSS.encode()})
    docs = fuentes.reddit(s, subs=("algotrading",), max_n=5, dormir=lambda x: None)
    assert docs[0]["url"] == "https://reddit.com/x" and "maximos de 20 dias" in docs[0]["texto"]


def test_reddit_usa_su_propia_cabecera(sesion_falsa):
    s = sesion_falsa({fuentes.URL_REDDIT.format(sub="algotrading"): RSS.encode()})
    fuentes.reddit(s, subs=("algotrading",), max_n=5, dormir=lambda x: None)
    assert s.cabeceras_enviadas == [fuentes.CABECERAS_REDDIT]


def test_reddit_duerme_10s_entre_subreddits(sesion_falsa):
    s = sesion_falsa({fuentes.URL_REDDIT.format(sub="algotrading"): RSS.encode(),
                      fuentes.URL_REDDIT.format(sub="quant"): RSS.encode()})
    esperas = []
    fuentes.reddit(s, subs=("algotrading", "quant"), max_n=5, dormir=esperas.append)
    assert esperas == [10.0, 10.0]


def test_mql5_sin_repetir(sesion_falsa):
    s = sesion_falsa({fuentes.URL_MQL5: LISTADO_MQL5.encode(),
                      "https://www.mql5.com/en/code/77386": PAGINA_MQL5.encode()})
    docs = fuentes.mql5(s, 5, dormir=lambda x: None)
    assert len(docs) == 1 and "OnInit" in docs[0]["texto"]
    assert docs[0]["titulo"] == "Cruce de medias - MQL5 Code Base"


def test_materiales(tmp_path):
    (tmp_path / "apuntes.md").write_text("compro si rsi < 10", encoding="utf-8")
    (tmp_path / "otro.docx").write_text("ignorado", encoding="utf-8")
    docs = fuentes.materiales(tmp_path)
    assert len(docs) == 1 and docs[0]["url"] == "materiales://apuntes.md"
