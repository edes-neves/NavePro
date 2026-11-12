#!/usr/bin/env python3
"""Caixa (cartão) da projeção bíblica: contraste com o fundo e limpeza.

A caixa é desenhada pelo próprio Tk (sem display neste teste), então a
verificação cobre a lógica pura de contraste/cantos e, pela AST, garante que
o texto com referência bíblica continua desenhando a caixa e que o cartão é
removido ao voltar ao relógio.
"""

import ast
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

ARQ = os.path.join(RAIZ, "navepro", "core", "telao.py")
fonte = open(ARQ, encoding="utf-8").read()
modulo = ast.parse(fonte)
nos = {n.name: n for n in ast.walk(modulo) if isinstance(n, ast.FunctionDef)}

import navepro.core.telao as telao_mod  # noqa: E402
from navepro.core.telao import (  # noqa: E402
    TelaoWindow,
    _justify_biblia,
    _texto_biblia_com_caixa,
)

falhas = 0


def checar(desc, cond):
    global falhas
    print(f"{'?' if cond else 'X'} {desc}")
    if not cond:
        falhas += 1


class _RootFalso:
    def winfo_rgb(self, cor):
        hexa = cor.lstrip("#")
        r, g, b = (int(hexa[i:i + 2], 16) for i in (0, 2, 4))
        return (r * 257, g * 257, b * 257)


telao = object.__new__(TelaoWindow)
telao.root = _RootFalso()

# ── Opções do texto bíblico (maiúsculas/minúsculas e alinhamento) ──
checar("modo normal mantém o texto do versículo",
       _texto_biblia_com_caixa("João 3:16", "normal") == "João 3:16")
checar("modo maiúsculas converte o versículo",
       _texto_biblia_com_caixa("João 3:16", "maiusculas") == "JOÃO 3:16")
checar("modo minúsculas converte o versículo",
       _texto_biblia_com_caixa("João 3:16", "minusculas") == "joão 3:16")
checar("alinhamento à esquerda", _justify_biblia("esquerda") == "left")
checar("alinhamento centralizado", _justify_biblia("centro") == "center")
checar("alinhamento à direita", _justify_biblia("direita") == "right")

telao.configurar_projecao()
checar("padrão bíblico: texto normal e centralizado",
       telao._proj_cfg.get("biblia_caixa") == "normal"
       and telao._proj_cfg.get("biblia_alinhamento") == "centro")
checar("caixa do versículo começa ligada por padrão",
       telao._proj_cfg.get("biblia_mostrar_caixa") is True)
telao.configurar_projecao({
    "biblia_caixa": "maiusculas", "biblia_alinhamento": "direita"})
checar("configuração preserva as opções bíblicas",
       telao._proj_cfg.get("biblia_caixa") == "maiusculas"
       and telao._proj_cfg.get("biblia_alinhamento") == "direita")
telao.configurar_projecao({"biblia_mostrar_caixa": False})
checar("caixa do versículo pode ser desligada na configuração",
       telao._proj_cfg.get("biblia_mostrar_caixa") is False)


def _lum(cor):
    hexa = cor.lstrip("#")
    r, g, b = (int(hexa[i:i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


for fundo in ("#000000", "#1a1a2e", "#0d1b2a", "#0a1f0a", "#2d0a0a"):
    fundo_caixa, borda, _sombra = telao._cores_da_caixa_texto(fundo)
    checar(f"fundo escuro {fundo}: borda clara contrasta",
           _lum(borda) - _lum(fundo) > 0.45)
    checar(f"fundo escuro {fundo}: cartão diferente do fundo",
           abs(_lum(fundo_caixa) - _lum(fundo)) > 0.05)
    checar(f"fundo escuro {fundo}: borda mais clara que o cartão",
           _lum(borda) > _lum(fundo_caixa))

for fundo in ("#FFFFFF", "#F0F0F0", "#E6EDF3"):
    fundo_caixa, borda, _sombra = telao._cores_da_caixa_texto(fundo)
    checar(f"fundo claro {fundo}: borda escura contrasta",
           _lum(fundo) - _lum(borda) > 0.45)
    checar(f"fundo claro {fundo}: cartão escuro", _lum(fundo_caixa) < 0.5)
    checar(f"fundo claro {fundo}: borda mais escura que o cartão",
           _lum(borda) < _lum(fundo_caixa))

pontos = telao._pontos_caixa_arredondada(10, 20, 210, 120, 18)
checar("cantos arredondados têm 24 coordenadas", len(pontos) % 2 == 0)
checar("caixa não sai do retângulo informado",
       min(pontos[0::2]) >= 10 and max(pontos[0::2]) <= 210
       and min(pontos[1::2]) >= 20 and max(pontos[1::2]) <= 120)

# Invariantes no código real: a referência bíblica e a limpeza do cartão.
corpo_texto = ast.get_source_segment(fonte, nos["_desenhar_texto_no_canvas"])
checar("texto com referência bíblica ativa a caixa",
       "usar_caixa = bool(" in corpo_texto
       and "biblia_mostrar_caixa" in corpo_texto)
checar("texto com referência desenha o cartão",
       "_desenhar_caixa_texto(" in corpo_texto)
checar("cartão é limpo antes de redesenhar",
       "self._limpar_caixa_texto()" in corpo_texto)
corpo_relogio = ast.get_source_segment(fonte, nos["_retornar_ao_relogio"])
checar("voltar ao relógio remove o cartão",
       'getattr(self, "_limpar_caixa_texto", None)' in corpo_relogio)

# ── Referência dentro do cartão e opções de texto/alinhamento ──
corpo_caixa = ast.get_source_segment(fonte, nos["_desenhar_caixa_texto"])
checar("cartão reserva espaço para a referência dentro da caixa",
       "largura_referencia" in corpo_caixa
       and "altura_referencia" in corpo_caixa
       and "_caixa_texto_box" in corpo_caixa)
checar("referência é posicionada dentro do cartão",
       "_caixa_texto_ref_cabe" in corpo_texto
       and "x2 - margem" in corpo_texto
       and "y2 - margem" in corpo_texto)
checar("caixa do versículo respeita o alinhamento escolhido",
       "justify=justify" in corpo_texto
       and "_justify_biblia" in corpo_texto)
checar("caixa do versículo aplica maiúsculas/minúsculas",
       "_texto_biblia_com_caixa" in corpo_texto)

_NAVEPRO = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
checar("janela de Projeção oferece maiúsculas/minúsculas",
       '"biblia_caixa"' in _NAVEPRO
       and '"MAIÚSCULAS"' in _NAVEPRO and '"minúsculas"' in _NAVEPRO)
checar("janela de Projeção oferece alinhamento à esquerda/direita/centro",
       '"biblia_alinhamento"' in _NAVEPRO
       and '"Esquerda"' in _NAVEPRO and '"Direita"' in _NAVEPRO
       and '"Centralizado"' in _NAVEPRO)
checar("NavePro alterna a caixa e persiste a escolha",
       "def alternar_caixa_versiculo" in _NAVEPRO
       and 'cfg["biblia_mostrar_caixa"] = novo' in _NAVEPRO
       and "self.salvar_config_projecao(cfg)" in _NAVEPRO)
checar("telão sabe redesenhar a projeção após alternar a caixa",
       "def reaplicar_projecao_atual" in fonte)
checar("Aparência da Projeção preserva o estado da caixa ao salvar",
       'novo["biblia_mostrar_caixa"] = bool(' in _NAVEPRO)

_JANELA_BIBLIA = open(os.path.join(RAIZ, "navepro", "ui", "janela_biblia.py"),
                      encoding="utf-8").read()
_GRADE = open(os.path.join(RAIZ, "navepro", "ui", "biblia_grade.py"),
              encoding="utf-8").read()
_REMOTO = open(os.path.join(RAIZ, "navepro", "ui", "remoto.py"),
               encoding="utf-8").read()
_REMOTO_WEB = open(os.path.join(RAIZ, "navepro", "remoto_web.py"),
                   encoding="utf-8").read()
checar("janela Bíblia tem botão para ligar/desligar a caixa",
       "btn_caixa_versiculo" in _JANELA_BIBLIA
       and "self.alternar_caixa_versiculo()" in _JANELA_BIBLIA)
checar("Bíblia em grade também tem o botão da caixa",
       "btn_caixa_versiculo" in _GRADE
       and "self.alternar_caixa_versiculo()" in _GRADE)
checar("controle remoto expõe biblia_mostrar_caixa na API",
       '"biblia_mostrar_caixa"' in _REMOTO)
checar("página do controle remoto tem o botão da caixa",
       'id="btn_caixa_versiculo"' in _REMOTO_WEB
       and "alternarCaixaVersiculo" in _REMOTO_WEB)


# ── Posição real da referência: dentro do cartão, canto inferior direito ──
class _CanvasFalso:
    def __init__(self, largura, altura, altura_por_tamanho=None):
        self.largura = largura
        self.altura = altura
        self.altura_por_tamanho = altura_por_tamanho
        self.itens = {}
        self.fontes = {}
        self._prox = 1

    def winfo_width(self):
        return self.largura

    def winfo_height(self):
        return self.altura

    def itemconfig(self, item, **cfg):
        self.itens.setdefault(item, {}).update(cfg)
        if "font" in cfg:
            self.fontes[item] = cfg["font"]

    def coords(self, item, *xy):
        self.itens.setdefault(item, {})["coords"] = xy

    def bbox(self, item):
        if self.altura_por_tamanho:
            fonte = self.fontes.get(item) or (None, 54, None)
            altura = max(1, int(fonte[1]) * self.altura_por_tamanho)
            topo = self.altura // 2 - altura // 2
            return (100, topo, self.largura - 100, topo + altura)
        return (100, 380, 1820, 700)

    def create_polygon(self, *pontos, **cfg):
        item = f"poly{self._prox}"
        self._prox += 1
        self.itens[item] = {"pontos": pontos, **cfg}
        return item

    def tag_lower(self, item, abaixo):
        self.itens.setdefault(item, {})["abaixo"] = abaixo

    def tag_raise(self, item, acima=None):
        self.itens.setdefault(item, {})["acima"] = acima

    def delete(self, item):
        self.itens.pop(item, None)


class _RootJanelaFalsa(_RootFalso):
    def update_idletasks(self):
        pass


class _FonteFalsa:
    def __init__(self, family=None, size=0, weight="normal"):
        self.size = max(1, int(size or 0))

    def measure(self, texto):
        return len(str(texto)) * max(1, int(self.size * 0.6))

    def metrics(self, _chave):
        return max(1, int(self.size * 1.2))


class _MonitorFalso:
    width = 1920
    height = 1080


_fonte_real = telao_mod.tkfont.Font
_familias_real = telao_mod.tkfont.families
try:
    telao_mod.tkfont.Font = _FonteFalsa
    telao_mod.tkfont.families = lambda root: ["DejaVu Sans"]

    janela_teste = object.__new__(TelaoWindow)
    janela_teste.root = _RootJanelaFalsa()
    janela_teste.canvas = _CanvasFalso(1920, 1080)
    janela_teste._monitor = _MonitorFalso()
    janela_teste.overlay_text = "texto"
    janela_teste.ref_text = "ref"
    janela_teste.temp_text = "temp"
    janela_teste._raiz_viva = lambda: True
    janela_teste._proj_cfg = {
        "fonte": "DejaVu Sans", "tamanho_pct": 5.0, "cor": "#FFFFFF",
        "cor_ref": "#A0A0A0", "cor_fundo": "#000000",
        "biblia_caixa": "normal", "biblia_alinhamento": "centro",
    }
    janela_teste._caixa_texto_itens = []
    janela_teste._desenhar_texto_no_canvas(
        "No princípio era o Verbo, e o Verbo estava com Deus.",
        referencia="João 1:1")

    caixa = janela_teste._caixa_texto_box
    coords_ref = janela_teste.canvas.itens["ref"].get("coords")
    checar("referência cabe dentro do cartão (não cai no canto da tela)",
           bool(caixa) and bool(coords_ref)
           and coords_ref != (1920 - 30, 1080 - 30))
    checar("referência fica no canto inferior direito DENTRO do cartão",
           bool(caixa) and bool(coords_ref)
           and caixa[0] < coords_ref[0] < caixa[2]
           and caixa[1] < coords_ref[1] < caixa[3]
           and coords_ref[0] > (caixa[0] + caixa[2]) // 2
           and coords_ref[1] > (caixa[1] + caixa[3]) // 2)

    janela_sem_caixa = object.__new__(TelaoWindow)
    janela_sem_caixa.root = _RootJanelaFalsa()
    janela_sem_caixa.canvas = _CanvasFalso(1920, 1080)
    janela_sem_caixa._monitor = _MonitorFalso()
    janela_sem_caixa.overlay_text = "texto"
    janela_sem_caixa.ref_text = "ref"
    janela_sem_caixa.temp_text = "temp"
    janela_sem_caixa._raiz_viva = lambda: True
    janela_sem_caixa._proj_cfg = {
        "fonte": "DejaVu Sans", "tamanho_pct": 5.0, "cor": "#FFFFFF",
        "cor_ref": "#A0A0A0", "cor_fundo": "#000000",
        "biblia_caixa": "normal", "biblia_alinhamento": "centro",
        "biblia_mostrar_caixa": False,
    }
    janela_sem_caixa._caixa_texto_itens = []
    janela_sem_caixa._desenhar_texto_no_canvas(
        "No princípio era o Verbo, e o Verbo estava com Deus.",
        referencia="João 1:1")
    checar("com a caixa desligada o versículo continua sendo desenhado",
           janela_sem_caixa._current_text != ""
           and janela_sem_caixa._caixa_texto_box is None
           and not janela_sem_caixa._caixa_texto_itens)
finally:
    telao_mod.tkfont.Font = _fonte_real
    telao_mod.tkfont.families = _familias_real

# Versículo grande: a estimativa inicial de linhas pode passar, mas o bbox
# real é alto demais. A fonte deve encolher até o cartão (com a referência
# embaixo) caber no telão — nunca empurrar a referência para fora da caixa.
try:
    telao_mod.tkfont.Font = _FonteFalsa
    telao_mod.tkfont.families = lambda root: ["DejaVu Sans"]

    janela_grande = object.__new__(TelaoWindow)
    janela_grande.root = _RootJanelaFalsa()
    janela_grande.canvas = _CanvasFalso(1920, 1080, altura_por_tamanho=40)
    janela_grande._monitor = _MonitorFalso()
    janela_grande.overlay_text = "texto"
    janela_grande.ref_text = "ref"
    janela_grande.temp_text = "temp"
    janela_grande._raiz_viva = lambda: True
    janela_grande._proj_cfg = {
        "fonte": "DejaVu Sans", "tamanho_pct": 5.0, "cor": "#FFFFFF",
        "cor_ref": "#A0A0A0", "cor_fundo": "#000000",
        "biblia_caixa": "normal", "biblia_alinhamento": "centro",
    }
    janela_grande._caixa_texto_itens = []
    janela_grande._desenhar_texto_no_canvas(
        "No princípio era o Verbo, e o Verbo estava com Deus. " * 8,
        referencia="Salmos 119:105")

    caixa_grande = janela_grande._caixa_texto_box
    coords_ref_grande = janela_grande.canvas.itens["ref"].get("coords")
    checar("versículo grande reduz a fonte para caber com a referência",
           18 <= janela_grande._font_letra[1] < 54)
    checar("referência do versículo grande cabe DENTRO do cartão",
           janela_grande._caixa_texto_ref_cabe
           and bool(caixa_grande) and bool(coords_ref_grande)
           and caixa_grande[0] < coords_ref_grande[0] < caixa_grande[2]
           and caixa_grande[1] < coords_ref_grande[1] < caixa_grande[3])
finally:
    telao_mod.tkfont.Font = _fonte_real
    telao_mod.tkfont.families = _familias_real

print("OK" if not falhas else f"\n{falhas} falha(s)")
sys.exit(1 if falhas else 0)
