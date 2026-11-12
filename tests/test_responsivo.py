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
import re
import sys
import tkinter as tk

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

from navepro.core.util_tk import (  # noqa: E402
    _centralizar_sobre,
    _habilitar_maximizar_janela,
    _janela_maximizada,
    _limitar_ao_monitor,
)

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
check("1024x768: geometria só com o tamanho", "+" not in f.geo, f.geo)

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

# Com a área do monitor do operador (não a tela virtual inteira), a janela
# é limitada pela altura do monitor primário — não pela soma dos monitores.
f = _FakeJanela(3840, 1080)
aplicado = _limitar_ao_monitor(
    f, 680, 980, area=(1920, 0, 1366, 768))
check("área do operador limita a altura do diálogo",
      aplicado == (680, 720), str(aplicado))
check("área do operador gera geometria só com tamanho",
      f.geo == "680x720", f.geo)

f = _FakeJanela(3840, 1080)
aplicado = _limitar_ao_monitor(
    f, 1100, 750, area=(1920, 0, 1366, 768))
check("1100x750 cabe ajustado no monitor do operador",
      aplicado == (1100, 720), str(aplicado))


class _FakeDialogo:
    def __init__(self, w, h):
        self._w, self._h = w, h
        self.geo = None

    def update_idletasks(self):
        pass

    def winfo_width(self):
        return self._w

    def winfo_height(self):
        return self._h

    def winfo_reqwidth(self):
        return self._w

    def winfo_reqheight(self):
        return self._h

    def geometry(self, g):
        self.geo = g


d = _FakeDialogo(680, 600)
_centralizar_sobre(d, area=(1920, 50, 1366, 768))
check("centraliza na área do monitor do operador (x/y respeitados)",
      d.geo == "+2263+134", d.geo)

# Sem a área, o comportamento antigo (centralizar sobre o pai) é mantido.
class _FakePai:
    def winfo_exists(self):
        return True

    def winfo_x(self):
        return 10

    def winfo_y(self):
        return 20

    def winfo_width(self):
        return 900

    def winfo_height(self):
        return 700


d = _FakeDialogo(400, 300)
_centralizar_sobre(d, _FakePai())
check("sem área continua centralizando sobre o pai",
      d.geo == "+260+220", d.geo)


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
_SRC_OS = open(os.path.join(RAIZ, "navepro", "ui", "janela_ordem_servico.py"),
               encoding="utf-8").read()
_SRC_UI = (_SRC
           + open(os.path.join(RAIZ, "navepro", "ui", "janela_anuncios.py"),
                  encoding="utf-8").read()
           + _SRC_OS
           + open(os.path.join(RAIZ, "navepro", "ui", "gerenciador_midias.py"),
                  encoding="utf-8").read()
           + open(os.path.join(RAIZ, "navepro", "ui", "config_relogio.py"),
                  encoding="utf-8").read())
check(
    "diálogos grandes usam _limitar_ao_monitor",
    _SRC_UI.count("_limitar_ao_monitor(") >= 4,
    str(_SRC_UI.count("_limitar_ao_monitor(")),
)
for _tamanho in ("680, 980", "800, 900", "680, 860", "1100, 750"):
    check(
        f"diálogo {_tamanho} limitado ao monitor",
        "_limitar_ao_monitor(" in _SRC_UI and _tamanho in _SRC_UI,
    )
check(
    "nenhum geometry fixo antigo restou para os diálogos grandes",
    '"680x980"' not in _SRC
    and '"800x900"' not in _SRC
    and '"680x860"' not in _SRC
    and '"1100x750"' not in _SRC,
)
check(
    "diálogos usam a área do monitor do operador",
    "_SRC_UI.count('_area_monitor_operador') >= 7"
    and _SRC_UI.count("area=self._area_monitor_operador()") >= 6,
    str(_SRC_UI.count("area=self._area_monitor_operador()")),
)
check(
    "árvore tem o helper da área do monitor do operador",
    "_area_monitor_operador" in _NOS,
)

# ── 3b) Ordem de Serviço responsiva e maximizável ──
check(
    "OS: lista fica com o espaço extra do grid",
    "main.rowconfigure(2, weight=1)" in _SRC_OS,
)
check(
    "OS: barra de botões fixa embaixo (grid row 3)",
    "btn_frame.grid(row=3, column=0, sticky='ew'" in _SRC_OS,
)
check(
    "OS: barra de botões se reorganiza quando a janela estreita",
    "def _reorganizar_botoes" in _SRC_OS
    and 'btn_frame.bind("<Configure>", _reorganizar_botoes)' in _SRC_OS,
)
check(
    "OS: janela pode ser maximizada/restaurada",
    "_habilitar_maximizar_janela(" in _SRC_OS
    and "ao_mudar_estado=_atualizar_botao_max" in _SRC_OS,
)
check(
    "OS: mínimo cabe em telas 800x600",
    "minsize(800, 540)" in _SRC_OS,
)
check(
    "OS: cartões acompanham a largura da janela",
    "lista_canvas.itemconfigure(_canvas_window, width=largura)" in _SRC_OS
    and 'dados["titulo"].configure(wraplength=wrap)' in _SRC_OS,
)
check(
    "OS: mantém viva a StringVar do seletor de serviço",
    "combo_servico._navepro_servico_var = servico_var" in _SRC_OS,
)


def _carregar_area_monitor_operador():
    no = _NOS["_area_monitor_operador"]
    mod = ast.Module(body=[no], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns = {}
    exec(compile(mod, "<area_monitor_operador>", "exec"), ns)
    return ns["_area_monitor_operador"]


_area_operador = _carregar_area_monitor_operador()


class _AppComMonitor:
    _monitor_geo = (1366, 768, 1920, 50)


class _AppSemMonitor:
    _monitor_geo = None


check(
    "helper devolve (x, y, largura, altura) do monitor primário",
    _area_operador(_AppComMonitor()) == (1920, 50, 1366, 768),
    str(_area_operador(_AppComMonitor())),
)
check(
    "helper sem geometria devolve None (fallback antigo)",
    _area_operador(_AppSemMonitor()) is None,
)


# ── 3c) Maximizar/restaurar janelas secundárias ──
class _FakeJanelaMax:
    """Toplevel mínimo para exercitar o helper sem display."""

    def __init__(self, geo="640x620+100+100", suporta_zoomed=True):
        self._geo = geo
        self.zoomed = False
        self.suporta_zoomed = suporta_zoomed
        self.tipo = None
        self.resizable_cfg = None
        self.binds = {}
        self.w, self.h, self.x, self.y = 640, 620, 100, 100
        self.geometry(geo)

    def resizable(self, w, h):
        self.resizable_cfg = (w, h)

    def attributes(self, nome, valor=None):
        if nome == "-type":
            if valor is None:
                return self.tipo
            self.tipo = valor
            return None
        if nome != "-zoomed":
            raise tk.TclError("atributo não suportado")
        if not self.suporta_zoomed:
            raise tk.TclError("atributo não suportado")
        if valor is None:
            return self.zoomed
        self.zoomed = bool(valor)
        return None

    def state(self, novo=None):
        if novo is None:
            return "zoomed" if self.zoomed else "normal"
        if novo == "zoomed" and not self.suporta_zoomed:
            raise tk.TclError('bad argument "zoomed"')
        self.zoomed = novo == "zoomed"

    def geometry(self, g=None):
        if g is not None:
            self._geo = str(g)
            m = re.match(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", self._geo)
            if m:
                self.w, self.h, self.x, self.y = (int(v) for v in m.groups())
        return self._geo

    def update_idletasks(self):
        pass

    def winfo_width(self):
        return self.w

    def winfo_height(self):
        return self.h

    def winfo_reqwidth(self):
        return self.w

    def winfo_reqheight(self):
        return self.h

    def winfo_x(self):
        return self.x

    def winfo_y(self):
        return self.y

    def bind(self, seq, func, add=None):
        self.binds[seq] = func

    def after_idle(self, func):
        func()

    def after(self, ms, func=None):
        if func is not None:
            func()
        return "after"

    def disparar_configure(self):
        self.binds["<Configure>"]()


f = _FakeJanelaMax()
alternar = _habilitar_maximizar_janela(f)
check("helper torna a janela redimensionável", f.resizable_cfg == (True, True),
      str(f.resizable_cfg))
check("helper troca o tipo diálogo por normal (habilita o botão nativo)",
      f.tipo == "normal", str(f.tipo))
check("helper registra F11 e <Configure>",
      "<F11>" in f.binds and "<Configure>" in f.binds)
f.disparar_configure()
alternar()
check("F11 maximiza a janela", f.zoomed is True)
f._geo = "1366x768+0+0"
f.disparar_configure()
alternar()
check("F11 restaura exatamente a geometria anterior",
      f.zoomed is False and f._geo == "640x620+100+100", f._geo)

estados = []
f = _FakeJanelaMax()
alternar = _habilitar_maximizar_janela(f, ao_mudar_estado=estados.append)
f.disparar_configure()
f.zoomed = True
f.geometry("1366x768+0+0")
f.disparar_configure()
check("detecta a maximização feita pelo botão do meio",
      estados and estados[-1] is True, str(estados))
alternar()
check("maximizar pelo botão do meio também restaura o tamanho",
      f.zoomed is False and f._geo == "640x620+100+100", f._geo)
check("helper identifica o estado maximizado", _janela_maximizada(f) is False)

# Linux/X11: o Tk 8.6 ignora -zoomed e recusa state("zoomed"); o helper
# precisa cair na geometria da área do monitor.
estados = []
f = _FakeJanelaMax(geo="640x620+100+100", suporta_zoomed=False)
alternar = _habilitar_maximizar_janela(
    f, area=(0, 0, 1366, 768), ao_mudar_estado=estados.append)
alternar()
check("X11: maximiza pela área do monitor",
      f._geo == "1366x768+0+0" and estados[-1] is True, f._geo)
alternar()
check("X11: restaura a geometria original",
      f._geo == "640x620+100+100" and estados[-1] is False, f._geo)

estados.clear()
f = _FakeJanelaMax(geo="640x620+100+100", suporta_zoomed=False)
alternar = _habilitar_maximizar_janela(
    f, area=(0, 0, 1366, 768), ao_mudar_estado=estados.append)
f.geometry("1366x768+0+0")
f.disparar_configure()
check("X11: reconhece a maximização feita pelo gerenciador",
      estados and estados[-1] is True, str(estados))
alternar()
check("X11: botão restaura depois da maximização nativa",
      f._geo == "640x620+100+100" and estados[-1] is False, f._geo)

# Todas as janelas secundárias que abrem em tamanho normal usam o helper.
for _arquivo, _rotulo in (
    ("navepro/ui/janela_anuncios.py", "Anúncios"),
    ("navepro/ui/janela_hinos.py", "Hinos"),
    ("navepro/ui/janela_biblia.py", "Bíblia (busca)"),
    ("navepro/ui/gerenciador_midias.py", "Gerenciar mídias"),
    ("navepro/ui/janela_transferencia.py", "Transferência"),
    ("navepro/ui/config_relogio.py", "Configura Relógio"),
    ("navepro/ui/janela_ordem_servico.py", "Ordem de Serviço (item)"),
    ("navepro/ui/apoio.py", "Seletor de arquivos"),
    ("navepro/ui/atualizacao.py", "Atualização via Flatpak"),
):
    _src = open(os.path.join(RAIZ, _arquivo), encoding="utf-8").read()
    check(f"{_rotulo}: janela pode ser maximizada/restaurada",
          "_habilitar_maximizar_janela(" in _src)

check("Aparência da Projeção também pode ser maximizada/restaurada",
      "_habilitar_maximizar_janela(cfg_win" in _SRC)
check("Configura Relógio não bloqueia as outras janelas",
      ".grab_set(" not in open(
          os.path.join(RAIZ, "navepro", "ui", "config_relogio.py"),
          encoding="utf-8").read())

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
