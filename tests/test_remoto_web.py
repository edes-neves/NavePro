#!/usr/bin/env python3
"""Testes da página do controle remoto (navepro/remoto_web.py).

A página é uma STRING (constante do módulo) para sobreviver ao PyInstaller,
AppImage e Flatpak — não existe arquivo estático no bundle. Como não há HTML
de verdade para o linter enxergar, estes testes travam os invariantes que, se
quebrados, deixam o controle remoto mudo sem aviso:

1. A PAGINA é montada como CSS + HTML + JS e continua um documento único.
2. Nenhum ``</style>``/``</script>`` embutido no CSS/JS (fecharia a tag cedo e
   destruiria o resto da página).
3. Todo id usado por ``getElementById`` existe no HTML (um id renomeado de um
   lado só quebra o JS silenciosamente no celular).
4. Toda rota ``/api/remoto/*`` usada pela página existe no servidor — evita o
   "drift" em que a página chama um endpoint que o servidor não serve.
"""

import os
import re
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

# remoto_web.py é só constantes de string (sem imports): dá para executar o
# fonte direto num namespace, sem tocar no pacote navepro nem em tkinter.
_SRC = open(os.path.join(RAIZ, "navepro", "remoto_web.py"),
            encoding="utf-8").read()
_NS: dict = {}
exec(compile(_SRC, "<remoto_web>", "exec"), _NS)

PAGINA = _NS["PAGINA"]
CSS = _NS["_REMOTO_CSS"]
JS = _NS["_REMOTO_JS"]

_SRV_SRC = open(os.path.join(RAIZ, "navepro", "core", "servidor_http.py"),
                encoding="utf-8").read()

falhas = []


def check(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


# ── 1. Documento único, montado a partir das partes ──────────────────
check("PAGINA embute o CSS", CSS in PAGINA)
check("PAGINA embute o JS", JS in PAGINA)
check("PAGINA começa com <!DOCTYPE html>", PAGINA.lstrip().startswith("<!DOCTYPE html>"))
check("PAGINA termina com </html>", PAGINA.rstrip().endswith("</html>"))
check("uma única tag <style>", PAGINA.count("<style>") == 1)
check("uma única tag </style>", PAGINA.count("</style>") == 1)
check("uma única tag <script>", PAGINA.count("<script>") == 1)
check("uma única tag </script>", PAGINA.count("</script>") == 1)

# ── 2. Nada que feche a tag por dentro ───────────────────────────────
check("CSS não contém '</style>'", "</style>" not in CSS)
check("JS não contém '</script>'", "</script>" not in JS)

# ── 3. ids do getElementById existem no HTML ─────────────────────────
ids_usados = set(re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", JS))
ids_definidos = set(re.findall(r"id=['\"]([^'\"]+)['\"]", PAGINA))
faltando = sorted(ids_usados - ids_definidos)
check(f"todo getElementById tem id no HTML ({len(ids_usados)} ids)",
      not faltando, ", ".join(faltando))
check("há ids (o regex não passou em branco)", bool(ids_usados))

# ── 4. Rotas da página existem no servidor ───────────────────────────
rotas_pagina = set(re.findall(r"/api/remoto/[a-z_/]+", PAGINA))
rotas_servidor = set(re.findall(r"/api/remoto/[a-z_/]+", _SRV_SRC))
orfa = sorted(rotas_pagina - rotas_servidor)
check(f"toda rota da página existe no servidor ({len(rotas_pagina)} rotas)",
      not orfa, ", ".join(orfa))
check("há rotas (o regex não passou em branco)", bool(rotas_pagina))

print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas else f"FALHAS: {falhas}"))
sys.exit(1 if falhas else 0)
