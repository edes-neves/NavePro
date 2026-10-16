"""Testes headless da responsividade das janelas (1024x768 -> resoluções altas).

O NavePro precisa funcionar de 1024x768 até as resoluções mais altas. Este
teste cobre:

- o helper ``_limitar_ao_monitor`` (limita o tamanho pedido à tela);
- a janela principal (``minsize`` que caiba em 768 e máximo responsivo);
- os diálogos que pediam tamanho maior que 1024x768 (relógio, banco de mídia,
  editor de anúncio, ordem de serviço);
- a janela embutida do Sorteio (1200x880).
"""

import ast
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

from navepro.core.util_tk import _limitar_ao_monitor  # noqa: E402

_SRC = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
_SRC_INTEG = open(
    os.path.join(RAIZ, "navepro", "sorteio", "integracao.py"), encoding="utf-8"
).read()
_SRC_APP = open(
    os.path.join(RAIZ, "navepro", "sorteio", "app.py"), encoding="utf-8"
).read()
_NOS = {
    n.name: n for n in ast.walk(ast.parse(_SRC)) if isinstance(n, ast.FunctionDef)
}


def _corpo_sem_docstring(no):
    """Código do nó sem a docstring.

    A docstring não é código: ela pode citar valores antigos ("em vez de um
    900x800 fixo") para documentar a correção e, se for incluída na checagem,
    faz o teste acusar falha por causa da própria explicação.
    """
    corpo = no.body
    primeiro = corpo[0] if corpo else None
    if (isinstance(primeiro, ast.Expr)
            and isinstance(primeiro.value, ast.Constant)
            and isinstance(primeiro.value.value, str)):
        corpo = corpo[1:]
    return "\n".join(
        ast.get_source_segment(_SRC, st) or "" for st in corpo
    )


_SEG_ALTERNAR = ast.get_source_segment(_SRC, _NOS["_alternar_maximizar"])
_CORPO_ALTERNAR = _corpo_sem_docstring(_NOS["_alternar_maximizar"])

falhas = []


def check(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


# ── 1) Helper _limitar_ao_monitor ──
class _FakeJanela:
    def __init__(self, sw, sh):
        self._sw, self._sh = sw, sh
        self.geo = None

    def winfo_screenwidth(self):
        return self._sw

    def winfo_screenheight(self):
        return self._sh

    def geometry(self, g):
        self.geo = g


def limitar(sw, sh, w, h):
    f = _FakeJanela(sw, sh)
    aplicado = _limitar_ao_monitor(f, w, h)
    return f, aplicado


# Em 1024x768 nada pode passar da margem da tela.
f, (w, h) = limitar(1024, 768, 1100, 750)
check("1024x768: largura > tela é limitada", w <= 1024 and h <= 768, f.geo)
check("1024x768: geometria com coordenadas", "+" in f.geo, f.geo)

f, (w, h) = limitar(1024, 768, 680, 980)
check("1024x768: altura > tela é limitada", w == 680 and h <= 768, f.geo)

f, (w, h) = limitar(1024, 768, 800, 900)
check("1024x768: 800x900 cabe ajustado", w == 800 and h <= 768, f.geo)

# Em telas maiores o tamanho pedido é preservado.
f, (w, h) = limitar(1920, 1080, 1100, 750)
check("1920x1080: tamanho pedido preservado", (w, h) == (1100, 750), f.geo)

f, (w, h) = limitar(1920, 1080, 680, 980)
check("1920x1080: 680x980 preservado", (w, h) == (680, 980), f.geo)

# Tela menor que o mínimo suportado: continua cabendo.
f, (w, h) = limitar(800, 600, 1100, 750)
check("tela 800x600: não estoura a tela", w <= 800 and h <= 600, f.geo)

# Nunca aumenta o tamanho pedido.
f, (w, h) = limitar(4000, 3000, 500, 400)
check("nunca aumenta além do pedido", (w, h) == (500, 400), f.geo)


# ── 2) Janela principal ──
check(
    "minsize da janela principal cabe em 768",
    "minsize(900, 620)" in _SRC,
)
check(
    "fachada tk não usa minsize 800 de altura (900x800 antigo)",
    "minsize(900, 800)" not in _SRC,
)
check(
    "_alternar_maximizar não fixa 900x800",
    "900x800" not in _CORPO_ALTERNAR and "900, 800" not in _CORPO_ALTERNAR,
)
check(
    "_alternar_maximizar calcula o tamanho a partir do monitor",
    "_monitor_geo" in _SEG_ALTERNAR and "0.78" in _SEG_ALTERNAR,
)


# ── 3) Diálogos maiores que 1024x768 usam o helper ──
check(
    "diálogos grandes usam _limitar_ao_monitor",
    _SRC.count("_limitar_ao_monitor(") >= 4,
    str(_SRC.count("_limitar_ao_monitor(")),
)
for _tamanho in ("680, 980", "800, 900", "680, 860", "1100, 750"):
    check(
        f"diálogo {_tamanho} limitado ao monitor",
        "_limitar_ao_monitor(" in _SRC and _tamanho in _SRC,
    )
check(
    "nenhum geometry fixo antigo restou para os diálogos grandes",
    '"680x980"' not in _SRC
    and '"800x900"' not in _SRC
    and '"680x860"' not in _SRC
    and '"1100x750"' not in _SRC,
)


# ── 4) Sorteio embutido ──
check(
    "sorteio: usa _limitar_ao_monitor no place()",
    "_limitar_ao_monitor(janela, width, height)" in _SRC_INTEG,
)
check(
    "sorteio: não força minsize 1200x880",
    "minsize(width, height)" not in _SRC_INTEG,
)
check(
    "sorteio: minsize cabe em 768",
    "minsize(880, 620)" in _SRC_INTEG,
)
check(
    "sorteio app: run() limita o tamanho ao monitor primário",
    "primary.width - 48" in _SRC_APP and "primary.height - 48" in _SRC_APP,
)
check(
    "sorteio app: minsize cabe em 768",
    "minsize(880, 620)" in _SRC_APP,
)

print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas else f"FALHAS: {falhas}"))
sys.exit(1 if falhas else 0)
