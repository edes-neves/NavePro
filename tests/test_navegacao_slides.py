#!/usr/bin/env python3
"""Testes das fábricas compartilhadas de navegação/busca (navepro/ui/navegacao.py).

As janelas de Hinos/Anúncios/Bíblia/Ordem de Serviço repetiam as mesmas
closures; agora elas vêm do `NavegacaoSlidesMixin` (e dos helpers do módulo).
Estes testes travam o comportamento comum: retorno "break" das teclas,
callbacks só em navegação bem-sucedida, parada com callback, indicador e
debounce da busca.
"""

import os
import sys
import types

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

from navepro.ui.navegacao import (  # noqa: E402
    NavegacaoSlidesMixin,
    _ligar_busca_com_debounce,
    _termo_da_busca,
)

falhas = 0


def checar(desc, cond):
    global falhas
    print(f"{'OK ' if cond else 'X  '} {desc}")
    if not cond:
        falhas += 1


class TelaoFake:
    def __init__(self, em_slides=True, navega=True):
        self._em_slides = em_slides
        self._slides = ["a", "b"] if em_slides else []
        self._slide_index = 0
        self.mostrando_letra = em_slides
        self.navega = navega
        self.chamadas = []

    def slide_anterior(self):
        self.chamadas.append("anterior")
        if not self.navega:
            return False
        self._slide_index = max(0, self._slide_index - 1)
        return True

    def slide_proximo(self):
        self.chamadas.append("proximo")
        if not self.navega:
            return False
        self._slide_index = min(len(self._slides) - 1, self._slide_index + 1)
        return True

    def parar_projecao(self):
        self.chamadas.append("parar")


class LabelFake:
    def __init__(self):
        self.texto = None

    def winfo_exists(self):
        return True

    def config(self, **k):
        if "text" in k:
            self.texto = k["text"]


def _app(telao):
    """AppInterface falsa: só o que as fábricas tocam."""
    return types.SimpleNamespace(player=types.SimpleNamespace(telao=telao))


# ── 1. Navegação por setas (retorno e callback) ──────────────────────
telao = TelaoFake(em_slides=True)
app = _app(telao)
ant, prox, parar = NavegacaoSlidesMixin._criar_navegacao_slides.__get__(
    app)()
checar("seta esquerda navega e devolve 'break'",
       ant(None) == "break" and telao.chamadas[-1] == "anterior")
checar("seta direita navega e devolve 'break'",
       prox(None) == "break" and telao.chamadas[-1] == "proximo")
checar("Esc para a projeção e devolve 'break'",
       parar(None) == "break" and telao.chamadas[-1] == "parar")

app_off = _app(TelaoFake(em_slides=False))
ant_off, _, parar_off = NavegacaoSlidesMixin._criar_navegacao_slides.__get__(
    app_off)()
checar("sem projeção, setas devolvem None e não navegam",
       ant_off(None) is None and app_off.player.telao.chamadas == [])
checar("sem projeção, Esc devolve None e não para",
       parar_off(None) is None and app_off.player.telao.chamadas == [])

avisos = []
telao2 = TelaoFake(em_slides=True)
app2 = _app(telao2)
ant2, _, parar2 = NavegacaoSlidesMixin._criar_navegacao_slides.__get__(app2)(
    ao_navegar=lambda: avisos.append("navegou"),
    ao_parar=lambda: avisos.append("parou"))
ant2(None)
checar("callback ao_navegar roda após navegar", avisos == ["navegou"])
telao2.navega = False
ant2(None)
checar("slide que falha não dispara o callback", avisos == ["navegou"])
parar2(None)
checar("Esc para e dispara ao_parar",
       telao2.chamadas[-1] == "parar" and avisos == ["navegou", "parou"])

# ── 2. Indicador padrão (Slide x de y / imagem / sem projeção) ───────
label = LabelFake()
telao_i = TelaoFake(em_slides=True)
telao_i._slides = ["a", "b", "c"]
telao_i._slide_index = 1
ind = NavegacaoSlidesMixin._criar_atualizador_indicador_slide.__get__(
    _app(telao_i))(label)
ind()
checar("indicador mostra 'Slide 2 de 3'", label.texto == "Slide 2 de 3")
telao_i._slides = []
telao_i.mostrando_letra = False
ind()
checar("sem projeção mostra 'Sem projeção'", label.texto == "Sem projeção")
telao_i.mostrando_letra = True
ind()
checar("letra ativa mostra 'Projeção ativa'", label.texto == "Projeção ativa")
telao_i.mostrando_letra = False
telao_i._mostrando_imagem = True
ind()
checar("imagem ativa mostra 'Imagem ativa'", label.texto == "🖼️ Imagem ativa")

# ── 3. Debounce/placeholder da busca ─────────────────────────────────
class EntryFake:
    def __init__(self, texto):
        self.texto = texto
        self.fg = None
        self.binds = {}

    def get(self):
        return self.texto

    def delete(self, a, b):
        self.texto = ""

    def insert(self, pos, texto):
        self.texto = self.texto + texto

    def config(self, **k):
        if "fg" in k:
            self.fg = k["fg"]

    def bind(self, seq, fn):
        self.binds[seq] = fn


class JanelaFake:
    def __init__(self):
        self.timers = {}
        self.cancelados = []
        self._id = 0

    def after(self, ms, fn):
        self._id += 1
        self.timers[str(self._id)] = (ms, fn)
        return str(self._id)

    def after_cancel(self, tid):
        self.cancelados.append(tid)
        self.timers.pop(str(tid), None)


placeholder = "Buscar algo..."
entry = EntryFake(placeholder)
janela = JanelaFake()
chamadas_busca = []
_ligar_busca_com_debounce(janela, entry, placeholder,
                          lambda: chamadas_busca.append("buscar"))
entry.binds["<FocusIn>"](None)
checar("FocusIn limpa o placeholder", entry.texto == "" and entry.fg == "#f0c040")
entry.binds["<FocusOut>"](None)
checar("FocusOut devolve o placeholder",
       entry.texto == placeholder and entry.fg == "#8b949e")
entry.texto = "aleluia"
entry.binds["<KeyRelease>"](None)
checar("digitar agenda a busca (debounce 400 ms)",
       len(janela.timers) == 1 and next(iter(janela.timers.values()))[0] == 400)
entry.binds["<KeyRelease>"](None)
checar("nova tecla cancela o timer anterior",
       len(janela.cancelados) == 1 and len(janela.timers) == 1)
checar("_termo_da_busca limpa o placeholder do texto",
       _termo_da_busca(EntryFake(placeholder), placeholder) == ""
       and _termo_da_busca(EntryFake("  aleluia"), placeholder) == "aleluia")

print()
if falhas:
    print(f"X {falhas} teste(s) falharam.")
    sys.exit(1)
print("OK todos os testes de navegação passaram.")
