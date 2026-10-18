#!/usr/bin/env python3
"""Testes da projeção automática da aba Bíblia do controle remoto.

Comportamento travado (pedido do usuário):
  * escolher livro/capítulo e preencher o versículo (V:) projeta sozinho,
    sem tocar em botão;
  - os botões da aba viram ◀ Anterior / ▶ Próximo, ligados à MESMA rota da
    aba Slides (POST /api/remoto/slide) — então ▶ Próximo encerra e volta ao
    relógio ao passar do último versículo, como o "Próximo" dos Slides.

A página é uma string (navepro/remoto_web.py), então os invariantes são
verificados no próprio texto (mesma abordagem do test_remoto_web.py).
"""

import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)

_SRC = open(os.path.join(RAIZ, "navepro", "remoto_web.py"),
            encoding="utf-8").read()
_NS: dict = {}
exec(compile(_SRC, "<remoto_web>", "exec"), _NS)  # noqa: S102

PAGINA = _NS["PAGINA"]
JS = _NS["_REMOTO_JS"]

# Bloco da aba Bíblia (referência) — isolado para não confundir com a aba
# Slides, que tem os mesmos rótulos Anterior/Próximo.
_inicio = PAGINA.index('<section id="aba-biblia">')
_fim = PAGINA.index("</section>", _inicio)
aba = PAGINA[_inicio:_fim]

falhas = []


def check(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


# ── 1. Botões da referência viram Anterior/Próximo (rota dos Slides) ──
check("aba Bíblia tem o botão Anterior ligado a slide('ant')",
      "onclick=\"slide('ant')\"" in aba and "Anterior" in aba)
check("aba Bíblia tem o botão Próximo ligado a slide('prox')",
      "onclick=\"slide('prox')\"" in aba and "Pr&oacute;ximo" in aba)
check("botões antigos (Buscar/Projetar) saíram da referência",
      "buscarBibliaRef()" not in aba and "projetarBibliaRef()" not in aba)
check("Anterior/Próximo usam a mesma rota da aba Slides",
      "/api/remoto/slide" in JS and "function slide(acao)" in JS)

# ── 2. Escolher a referência projeta sozinho (com debounce) ──
check("existe a carga automática da referência", "function autoBiblia()" in JS)
check("carga automática é agendada com atraso (debounce)",
      "clearTimeout(_bibTimer)" in JS and "}, 600);" in JS)
check("os 4 campos da referência disparam a carga automática",
      "['bib_versao', 'bib_livro', 'bib_cap', 'bib_vers']" in JS
      and "el.addEventListener('input', autoBiblia)" in JS
      and "el.addEventListener('change', autoBiblia)" in JS)
check("carga automática projeta E atualiza a lista",
      "projetarBibliaRef(null, true);" in JS and "buscarBibliaRef();" in JS)

# ── 3. Guarda de entrada: não projeta refeição incompleta ("1-") ──
check("carga automática exige capítulo numérico",
      "/^[0-9]+$/.test(cap)" in JS)
check("carga automática exige 'V:' preenchido", "if (!vers ||" in JS)
check("carga automática aceita número ou faixa em 'V:'",
      "/^[0-9]+$/.test(vers)" in JS and "/^[0-9]+ *- *[0-9]+$/.test(vers)" in JS)

# ── 3b. A projeção automática é silenciosa (sem aviso na tela) ──
check("apiPost aceita o modo silencioso",
      "function apiPost(path, dados, silencioso)" in JS
      and "j.erro && !silencioso" in JS)
check("projetarBibliaRef usa o modo silencioso na projeção automática",
      "function projetarBibliaRef(vers, silencioso)" in JS
      and "projetarBibliaRef(null, true)" in JS)

# ── 3. Campos/datalists continuam existindo (não quebrou o que havia) ──
for _id in ("bib_versao", "bib_livro", "bib_cap", "bib_vers"):
    check(f"campo {_id} continua na página", f'id="{_id}"' in PAGINA)

print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas else f"FALHAS: {falhas}"))
sys.exit(1 if falhas else 0)
