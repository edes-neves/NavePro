"""Testes headless da integração do Sorteio Profissional com o NavePro.

Não abre janelas: valida o shim ``customtkinter``→``tkinter``, a
vendorização (sem resquícios de ``customtkinter``/``from src``), os caminhos
de dados e a lógica pura do sorteio.
"""

import ast
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

_DIR_SORTEIO = os.path.join(RAIZ, "navepro", "sorteio")

# --- O shim deve expor toda a API usada pelos módulos do sorteio ---
from navepro.sorteio import ctk  # noqa: E402

_API_ESPERADA = [
    "CTk", "CTkToplevel", "CTkFrame", "CTkLabel", "CTkButton", "CTkEntry",
    "CTkTextbox", "CTkScrollableFrame", "CTkCheckBox", "CTkSegmentedButton",
    "CTkProgressBar", "CTkBaseClass", "ThemeManager",
    "set_appearance_mode", "set_default_color_theme",
    "set_widget_scaling", "set_window_scaling",
]
for _nome in _API_ESPERADA:
    assert hasattr(ctk, _nome), f"shim ctk sem {_nome}"


# --- Vendorização: nenhum módulo pode importar customtkinter/from src ---
def _modulos_importados(caminho):
    with open(caminho, encoding="utf-8") as f:
        arvore = ast.parse(f.read())
    modulos = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            modulos.extend(alias.name for alias in no.names)
        elif isinstance(no, ast.ImportFrom):
            modulos.append(no.module or "")
    return modulos


for _arq in sorted(os.listdir(_DIR_SORTEIO)):
    if not _arq.endswith(".py"):
        continue
    for _mod in _modulos_importados(os.path.join(_DIR_SORTEIO, _arq)):
        assert _mod.split(".")[0] != "customtkinter", f"{_arq} importa customtkinter"
        assert _mod != "src" and not _mod.startswith("src."), (
            f"{_arq} importa de src ({_mod})"
        )


# --- Todos os módulos importam sem display ---
import navepro.sorteio.app  # noqa: E402,F401
import navepro.sorteio.integracao  # noqa: E402,F401
import navepro.sorteio.main_window  # noqa: E402,F401
import navepro.sorteio.public_window  # noqa: E402,F401

# --- Caminhos de dados sob ~/.navepro/sorteio ---
from navepro.sorteio import history_manager, settings_manager  # noqa: E402

assert settings_manager.CONFIG_FILE.endswith(
    os.path.join("sorteio", "config", "settings.json")
), settings_manager.CONFIG_FILE
assert os.sep + ".navepro" in settings_manager.CONFIG_FILE
assert history_manager.BASE_DIR.endswith(os.path.join(".navepro", "sorteio")), (
    history_manager.BASE_DIR
)
assert history_manager.BASE_DIR == settings_manager.DATA_DIR

# --- Assets de som dentro do pacote ---
from navepro.sorteio import sound_manager  # noqa: E402

assert sound_manager.SOUNDS_DIR.endswith(
    os.path.join("sorteio", "assets", "sounds")
), sound_manager.SOUNDS_DIR

# --- Reprodução sem pygame: players nativos (Windows/winsound; Linux/players) ---
assert not hasattr(sound_manager, "HAS_PYGAME"), "pygame não deve ser dependência"

_cmd_paplay = sound_manager._montar_comando(
    "paplay", "/usr/bin/paplay", "/tmp/x.wav", 0.5
)
assert _cmd_paplay[0] == "/usr/bin/paplay", _cmd_paplay
assert _cmd_paplay[-1] == "/tmp/x.wav", _cmd_paplay
assert "--volume=" in " ".join(_cmd_paplay), _cmd_paplay

_cmd_mpv = sound_manager._montar_comando("mpv", "/usr/bin/mpv", "/tmp/x.wav", 0.5)
assert _cmd_mpv[0] == "/usr/bin/mpv", _cmd_mpv
assert "--no-video" in _cmd_mpv, _cmd_mpv
assert "--volume=50" in _cmd_mpv, _cmd_mpv

_cmd_aplay = sound_manager._montar_comando("aplay", "/usr/bin/aplay", "/tmp/x.wav", 0.5)
assert _cmd_aplay == ["/usr/bin/aplay", "-q", "/tmp/x.wav"], _cmd_aplay

assert sound_manager.SoundManager().volume == 0.5

# --- Lógica pura do motor de sorteio ---
from navepro.sorteio.lottery_engine import LotteryEngine  # noqa: E402

_engine = LotteryEngine()
_engine.configure(1, 3)
assert _engine.total_numbers == 3
assert _engine.is_ready()
_sorteados = _engine.draw_many(3)
assert sorted(_sorteados) == [1, 2, 3]
assert _engine.drawn_count == 3
assert _engine.is_completed()
assert _engine.draw_many(1) == []

_engine.configure_names(["ana", "josé"])
assert _engine.mode == "names"
assert sorted(_engine.all_items) == ["ANA", "JOSÉ"]

# --- Validator: faixa válida e inválida ---
from navepro.sorteio.validator import Validator  # noqa: E402

_inicio, _fim = Validator.validate_range("2", "10")
assert (_inicio, _fim) == (2, 10)

# --- CTkEntry com cantos arredondados (Frame + Canvas, não tk.Entry) ---
import tkinter as tk  # noqa: E402

assert issubclass(ctk.CTkEntry, tk.Frame), "CTkEntry deve ser um Frame"
assert not issubclass(ctk.CTkEntry, tk.Entry), "CTkEntry não deve ser tk.Entry"
assert hasattr(ctk.CTkEntry, "_redraw"), "CTkEntry sem desenho arredondado"
assert hasattr(ctk, "_round_rect"), "shim sem helper de canto arredondado"

# --- CTkButton arredondado (herda do BotaoArredondado do NavePro) ---
from navepro.core.widgets_arredondados import (  # noqa: E402
    BotaoArredondado,
    CampoArredondado,
    TkArredondado,
)

assert issubclass(ctk.CTkButton, BotaoArredondado), "CTkButton sem cantos arredondados"
assert issubclass(ctk.CTkButton, tk.Frame), "CTkButton deve ser um Frame"
assert not issubclass(ctk.CTkButton, tk.Button), "CTkButton não deve ser tk.Button"
for _cls in (BotaoArredondado, CampoArredondado):
    assert issubclass(_cls, tk.Frame), f"{_cls.__name__} deve ser um Frame"
    assert hasattr(_cls, "_redraw"), f"{_cls.__name__} sem _redraw"
assert CampoArredondado.get and CampoArredondado.insert and CampoArredondado.bind, (
    "CampoArredondado sem repasse ao Entry interno"
)

# --- Alinhamento do texto: "center" não pode virar alinhamento à direita ---
# O teste antigo por substring ("e" in "center") alinhava todo botão
# centralizado à direita (bug reportado no nome do hino na lista).
class _FakeBotao:
    _padx = 8

    def __init__(self, anchor):
        self._anchor = anchor


for _anc, _esperado in (("center", "center"), ("n", "center"), ("s", "center"),
                        ("w", "w"), ("nw", "w"), ("sw", "w"),
                        ("e", "e"), ("ne", "e"), ("se", "e")):
    _x, _saida = BotaoArredondado._posicao_texto(_FakeBotao(_anc), 200)
    assert _saida == _esperado, f"anchor {_anc!r} -> {_saida!r}"
assert BotaoArredondado._posicao_texto(_FakeBotao("center"), 200)[0] == 100, (
    "texto centralizado não ficou no meio"
)

# --- NavePro usa a fachada tk: Button/Entry arredondados no app inteiro ---
with open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8") as _f_np:
    _fonte_np = _f_np.read()
assert "tk = TkArredondado(tk)" in _fonte_np, "NavePro.py não usa a fachada tk"
assert TkArredondado(tk).Button is BotaoArredondado, "fachada não troca Button"
assert TkArredondado(tk).Entry is CampoArredondado, "fachada não troca Entry"
assert TkArredondado(tk).Label is tk.Label, "fachada deve repassar o resto ao tkinter"


# --- Largura da janela do operador (1200px) ---
from navepro.sorteio import integracao  # noqa: E402

assert integracao._TAMANHO_JANELA == (1200, 880), integracao._TAMANHO_JANELA

# --- Atalho de aparência do telão no painel do operador ---
import inspect  # noqa: E402

from navepro.sorteio.app import App  # noqa: E402
from navepro.sorteio.main_window import MainWindow  # noqa: E402

assert hasattr(App, "_show_telao_dialog"), "App sem diálogo do telão"
assert hasattr(App, "_telao_aplicar"), "App sem aplicação da aparência do telão"
assert len(App._TELAO_CORES_FUNDO) >= 1, "sem opções de cor de fundo"
_assinatura = inspect.signature(MainWindow.__init__).parameters
assert "on_telao" in _assinatura, "MainWindow sem callback on_telao"
assert hasattr(MainWindow, "_on_telao_click"), "MainWindow sem handler do telão"

# --- Nomes: seletor "Nomes por vez" espelhando os números ---
assert hasattr(MainWindow, "_names_per_draw"), "MainWindow sem _names_per_draw"
assert hasattr(MainWindow, "_on_names_count_toggle"), "MainWindow sem toggle de nomes"

with open(
    os.path.join(_DIR_SORTEIO, "main_window.py"), encoding="utf-8"
) as _f:
    _fonte_mw = _f.read()
assert "self._names_per_draw()" in _fonte_mw, "sorteio de nomes não usa o seletor"

# --- Layout: caixas de texto não devem inflar a largura pedida ---
assert _fonte_mw.count("width=40") >= 2, (
    "CTkTextbox sem largura contida (quebra o layout da janela)"
)
assert "target_w" in _fonte_mw, "_fit_window_to_content não ajusta a largura"
assert "height=72" in _fonte_mw, "faixa de status baixa demais (corta os números)"

# --- Sem menu superior (Arquivos/Editar/Exibir/Sobre) e sem a tira clara ---
assert "_build_menu" not in _fonte_mw, "janela com menu superior"
assert "configure(menu=" not in _fonte_mw, "menubar ainda configurado"

# --- Fonte dos nomes: não usa a "Digital-7" dos números ---
from navepro.sorteio.animation_engine import AnimationEngine  # noqa: E402

assert hasattr(AnimationEngine, "_resolve_name_font"), "sem fonte para nomes"
assert hasattr(AnimationEngine, "_get_name_measure_font"), "sem medição de nomes"

with open(
    os.path.join(_DIR_SORTEIO, "animation_engine.py"), encoding="utf-8"
) as _f:
    _fonte_an = _f.read()

for _no in ast.walk(ast.parse(_fonte_an)):
    if isinstance(_no, ast.FunctionDef) and _no.name == "_draw_gold_text":
        _corpo = ast.get_source_segment(_fonte_an, _no)
        assert "_name_font" in _corpo, "_draw_gold_text não usa a fonte de nomes"
        assert "_number_font" not in _corpo, "_draw_gold_text usa Digital-7"
        break
else:
    raise AssertionError("animation_engine sem _draw_gold_text")

# --- Paletas do sorteio alinhadas ao NavePro ---
from navepro.sorteio.theme_manager import ThemeManager  # noqa: E402

# Escuro = cores do NavePro (dourado/roxo/superfícies escuras).
assert ThemeManager.NEON_DARK["bg"] == "#0d1117"
assert ThemeManager.NEON_DARK["bg_card"] == "#21262d"
assert ThemeManager.NEON_DARK["primary"] == "#f0c040"
assert ThemeManager.NEON_DARK["btn_primary"] == "#6e40c9"
assert ThemeManager.NEON_DARK["btn_text"] == "#ffffff"
# Claro = hierarquia de claros (janela cinza-clara, cartões brancos).
assert ThemeManager.NEON_LIGHT["bg"] == "#eaeef2"
assert ThemeManager.NEON_LIGHT["bg_card"] == "#ffffff"
assert ThemeManager.NEON_LIGHT["primary"] == "#8250df"
assert ThemeManager.NEON_LIGHT["btn_neutral"] == "#6e7681"
# A janela e os cartões NÃO podem ser a mesma cor (hierarquia, como no escuro).
assert ThemeManager.NEON_LIGHT["bg"] != ThemeManager.NEON_LIGHT["bg_card"]
assert ThemeManager.NEON_DARK["bg"] != ThemeManager.NEON_DARK["bg_card"]
# Mesmos tokens nos dois temas (widgets não podem quebrar na troca).
assert set(ThemeManager.NEON_DARK) == set(ThemeManager.NEON_LIGHT)
# O telão continua sempre na paleta escura.
assert "return self.NEON_DARK[name]" in open(
    os.path.join(_DIR_SORTEIO, "theme_manager.py"), encoding="utf-8"
).read()
assert hasattr(ThemeManager, "definir_tema"), "ThemeManager sem definir_tema"

# --- Sincronização do tema com o NavePro ---
assert hasattr(integracao, "sincronizar_tema"), "integracao sem sincronizar_tema"
assert hasattr(integracao, "_tema_navepro"), "integracao sem _tema_navepro"


class _FakeNavePro:
    def __init__(self, tema):
        self.tema = tema


assert integracao._tema_navepro(_FakeNavePro("claro")) == "light"
assert integracao._tema_navepro(_FakeNavePro("escuro")) == "dark"
assert integracao._tema_navepro(_FakeNavePro(None)) == "dark"

# --- App sabe trocar/reconstruir a interface por tema ---
assert hasattr(App, "definir_tema"), "App sem definir_tema"
assert hasattr(App, "_criar_main_window"), "App sem _criar_main_window"
assert hasattr(App, "_reconstruir_janela"), "App sem _reconstruir_janela"

# --- A janela do sorteio é marcada com tema próprio (fora do passe genérico) ---
with open(
    os.path.join(_DIR_SORTEIO, "integracao.py"), encoding="utf-8"
) as _f_integ:
    _fonte_integ = _f_integ.read()
assert "_navepro_tema_proprio = True" in _fonte_integ, "janela sem marca de tema"

# --- O NavePro sincroniza o tema e respeita a marca de tema próprio ---
_fonte_navepro = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
assert "_sorteio_sync_tema" in _fonte_navepro, (
    "NavePro não sincroniza o tema do sorteio"
)
assert "_navepro_tema_proprio" in _fonte_navepro, (
    "NavePro ignora a marca de tema próprio"
)

# --- Controle remoto do sorteio (abrir/sortear/reiniciar pelo celular) ---
assert hasattr(integracao, "estado_sorteio"), "integracao sem estado_sorteio"
assert hasattr(integracao, "sortear"), "integracao sem sortear"
assert hasattr(integracao, "reiniciar"), "integracao sem reiniciar"


class _LabelFalso:
    def __init__(self, texto=""):
        self._texto = texto

    def configure(self, **kw):
        self._texto = kw.get("text", "")

    def cget(self, chave):
        return self._texto


class _JanelaFalsa:
    def __init__(self, engine, erro=""):
        self._engine = engine
        self._error_label = _LabelFalso(erro)
        self.sorteou = 0
        self.limpou = 0

    def _on_draw_toggle(self):
        self.sorteou += 1
        if self._error_label._texto:
            return  # simula validação que barra o clique
        self._engine.configure(1, 5)
        self._engine.draw_many(1)

    def _on_clear_toggle(self):
        self.limpou += 1
        self._engine.reset()


class _AppSorteioFalso:
    def __init__(self, engine, janela):
        self._engine = engine
        self._main_window = janela


class _RaizFalsa:
    pass


class _NaveProFalso:
    def __init__(self):
        self.root = _RaizFalsa()


def _registrar(np_falso, app):
    integracao._aberto[id(np_falso.root)] = {"janela": None, "app": app}


_np = _NaveProFalso()

# Fechado: estado {aberto: False} e ações recusadas com mensagem clara.
assert integracao.estado_sorteio(_np) == {"aberto": False}
assert integracao.sortear(_np)["ok"] is False
assert integracao.reiniciar(_np)["ok"] is False
assert "Abra o Sorteio" in integracao.sortear(_np)["erro"]

# Aberto e configurado: "sortear" incrementa e o estado reflete o sorteio.
_eng = LotteryEngine()
_jan = _JanelaFalsa(_eng)
_registrar(_np, _AppSorteioFalso(_eng, _jan))
_est = integracao.estado_sorteio(_np)
assert _est["aberto"] is True and _est["sorteados"] == [], _est
_res = integracao.sortear(_np)
assert _res["ok"] is True and _res["desenhou"] == 1, _res
assert len(integracao.estado_sorteio(_np)["sorteados"]) == 1
assert _jan.sorteou == 1

# Reiniciar zera os sorteados.
_res = integracao.reiniciar(_np)
assert _res["ok"] is True and _res["sorteados"] == [], _res
assert integracao.estado_sorteio(_np)["sorteados"] == []
assert _jan.limpou == 1

# Janela barrando o clique (intervalo/nomes não configurados): o aviso dela
# chega ao celular em vez de um "ok" silencioso.
_eng2 = LotteryEngine()
_jan2 = _JanelaFalsa(_eng2, erro="Configure o intervalo e clique em Iniciar.")
_registrar(_np, _AppSorteioFalso(_eng2, _jan2))
_res = integracao.sortear(_np)
assert _res["ok"] is False and "Configure o intervalo" in _res["erro"], _res

integracao._aberto.pop(id(_np.root), None)

# --- Configuração remota (faixa de números / lista de nomes) ---
assert hasattr(integracao, "configurar_sorteio"), "integracao sem configurar_sorteio"
assert hasattr(integracao, "_lista_de_nomes"), "integracao sem _lista_de_nomes"

# Parsing de nomes: uma por linha ou separadas por vírgula, sem repetir.
assert integracao._lista_de_nomes("Ana\nJoão, Ana\nMaria") == [
    "Ana", "João", "Maria"
], integracao._lista_de_nomes("Ana\nJoão, Ana\nMaria")
assert integracao._lista_de_nomes(["a", "b"]) == ["a", "b"]
assert integracao._lista_de_nomes("  \n ,  ") == []


class _JanelaConfigFalsa:
    def __init__(self):
        self._mode = "numbers"
        self._stored_names = []
        self.chamadas = []

    def configurar_numeros(self, inicio, fim, por_vez):
        self.chamadas.append(("numeros", inicio, fim, por_vez))

    def configurar_nomes(self, nomes, por_vez):
        self.chamadas.append(("nomes", list(nomes), por_vez))

    def _numbers_per_draw(self):
        return 1

    def _names_per_draw(self):
        return 1

    def _names_from_input(self):
        return []


class _AppConfigFalso:
    def __init__(self, engine, mw):
        self._engine = engine
        self._main_window = mw


_np2 = _NaveProFalso()

# Fechado: recusa configurar.
assert integracao.configurar_sorteio(
    _np2, {"modo": "numeros", "inicio": "1", "fim": "10"}
)["ok"] is False

_eng3 = LotteryEngine()
_jan3 = _JanelaConfigFalsa()
_registrar(_np2, _AppConfigFalso(_eng3, _jan3))

# Números válidos: repassa (inicio, fim, por_vez).
_res = integracao.configurar_sorteio(
    _np2, {"modo": "numeros", "inicio": "1", "fim": "50", "por_vez": "3"})
assert _res["ok"] is True and _jan3.chamadas[-1] == ("numeros", 1, 50, 3), _res

# "por vez" fora da faixa é limitado a 1..5.
integracao.configurar_sorteio(
    _np2, {"modo": "numeros", "inicio": "1", "fim": "10", "por_vez": "99"})
assert _jan3.chamadas[-1] == ("numeros", 1, 10, 5), _jan3.chamadas
integracao.configurar_sorteio(
    _np2, {"modo": "numeros", "inicio": "1", "fim": "10", "por_vez": "0"})
assert _jan3.chamadas[-1] == ("numeros", 1, 10, 1), _jan3.chamadas

# Faixa inválida: usa a validação do sorteio (mensagem em português).
_res = integracao.configurar_sorteio(
    _np2, {"modo": "numeros", "inicio": "10", "fim": "1"})
assert _res["ok"] is False and "inicial" in _res["erro"].lower(), _res

# Nomes: normaliza e repassa a lista.
_res = integracao.configurar_sorteio(
    _np2, {"modo": "nomes", "nomes": "Ana\nJoão, Ana\nMaria", "por_vez": "2"})
assert _res["ok"] is True and _jan3.chamadas[-1] == (
    "nomes", ["Ana", "João", "Maria"], 2), _res

# Nomes vazio: recusa.
_res = integracao.configurar_sorteio(_np2, {"modo": "nomes", "nomes": " \n , "})
assert _res["ok"] is False and "nome" in _res["erro"].lower(), _res

integracao._aberto.pop(id(_np2.root), None)

# Os métodos de configuração vivem na janela do sorteio e mexem no motor.
assert hasattr(MainWindow, "configurar_numeros"), "MainWindow sem configurar_numeros"
assert hasattr(MainWindow, "configurar_nomes"), "MainWindow sem configurar_nomes"
with open(os.path.join(_DIR_SORTEIO, "main_window.py"), encoding="utf-8") as _f_mwc:
    _fonte_mwc = _f_mwc.read()
assert "self._engine.configure(int(inicio), int(fim))" in _fonte_mwc, (
    "configurar_numeros não deixa o motor pronto para o celular"
)
assert "self._engine.configure_names(nomes)" in _fonte_mwc, (
    "configurar_nomes não deixa o motor pronto para o celular"
)

print("OK test_sorteio")
