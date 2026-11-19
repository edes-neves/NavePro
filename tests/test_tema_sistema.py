#!/usr/bin/env python3
"""Tema automático: detecção do SO e modo salvo no config.

Cobre a leitura das preferências do sistema (GNOME, portal, KDE, Windows e
macOS) sem executar nada de verdade e o comportamento dos três modos do
painel: ``auto`` (padrão), ``claro`` e ``escuro``.
"""

import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

import navepro.core.tema_sistema as ts  # noqa: E402
import navepro.ui.tema_painel as tp  # noqa: E402

falhas = []


def check(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


# ── 1. Interpretação das saídas dos sistemas ────────────────────────
check("color-scheme prefer-dark vira escuro",
      ts._tema_por_esquema("'prefer-dark'") == "escuro")
check("color-scheme prefer-light vira claro",
      ts._tema_por_esquema("'prefer-light'") == "claro")
check("color-scheme default (sem preferência) fica indefinido",
      ts._tema_por_esquema("'default'") is None)
check("nome de tema com dark vira escuro",
      ts._tema_por_nome_tema("Yaru-dark") == "escuro")
check("nome de tema com light vira claro",
      ts._tema_por_nome_tema("BreezeLight") == "claro")
check("nome de tema neutro fica indefinido",
      ts._tema_por_nome_tema("Adwaita") is None)

check("portal uint32 1 vira escuro",
      ts._tema_por_saida_portal("(<<uint32 1>>,)") == "escuro")
check("portal uint32 2 vira claro",
      ts._tema_por_saida_portal("(<<uint32 2>>,)") == "claro")
check("portal uint32 0 (sem preferência) fica indefinido",
      ts._tema_por_saida_portal("(<<uint32 0>>,)") is None)

_kde_escuro = "[General]\nColorScheme=BreezeDark\n"
_kde_claro = "[General]\nColorScheme=BreezeLight\n"
_kde_rgb_escuro = "[Colors:Window]\nBackgroundNormal=27,30,32\n"
_kde_rgb_claro = "[Colors:Window]\nBackgroundNormal=239,240,241\n"
check("KDE ColorScheme escuro",
      ts._tema_por_kdeglobals(_kde_escuro) == "escuro")
check("KDE ColorScheme claro",
      ts._tema_por_kdeglobals(_kde_claro) == "claro")
check("KDE sem nome cai na luminosidade do fundo (escuro)",
      ts._tema_por_kdeglobals(_kde_rgb_escuro) == "escuro")
check("KDE sem nome cai na luminosidade do fundo (claro)",
      ts._tema_por_kdeglobals(_kde_rgb_claro) == "claro")
check("KDE sem informação fica indefinido",
      ts._tema_por_kdeglobals("[General]\n") is None)

_gtk_escuro = ("[Settings]\ngtk-theme-name=Adwaita\n"
               "gtk-application-prefer-dark-theme=true\n")
_gtk_claro = "[Settings]\ngtk-theme-name=Adwaita\n"
_gtk_nome_escuro = "[Settings]\ngtk-theme-name=Adwaita-dark\n"
check("GTK settings com prefer-dark vira escuro",
      ts._tema_por_gtk_settings(_gtk_escuro) == "escuro")
check("GTK settings sem preferência é claro",
      ts._tema_por_gtk_settings(_gtk_claro) == "claro")
check("GTK settings com tema -dark vira escuro",
      ts._tema_por_gtk_settings(_gtk_nome_escuro) == "escuro")
check("GTK settings vazio fica indefinido",
      ts._tema_por_gtk_settings("") is None)

# ── 2. Resolução do valor salvo ─────────────────────────────────────
check("modo claro é escolha manual (não detecta)",
      ts.resolver_tema("claro", lambda: "escuro") == "claro")
check("modo escuro é escolha manual (não detecta)",
      ts.resolver_tema("escuro", lambda: "claro") == "escuro")
check("auto consulta a detecção",
      ts.resolver_tema("auto", lambda: "claro") == "claro")
check("config antigo sem a chave tema usa auto",
      ts.resolver_tema(None, lambda: "claro") == "claro")
check("valor inválido usa auto",
      ts.resolver_tema("roxo", lambda: "claro") == "claro")
check("falha na detecção mantém o escuro",
      ts.resolver_tema("auto", lambda: (_ for _ in ()).throw(RuntimeError()))
      == "escuro")
check("detecção devolvendo lixo mantém o escuro",
      ts.resolver_tema("auto", lambda: "neon") == "escuro")

# ── 3. detectar_tema_sistema nunca levanta e cai no escuro ──────────
_orig_windows = ts._eh_windows
_orig_platform = ts.sys.platform
_orig_linux = ts._detectar_linux
try:
    ts._eh_windows = lambda: False
    ts.sys.platform = "linux"
    ts._detectar_linux = lambda: "claro"
    check("detecção Linux devolve claro", ts.detectar_tema_sistema() == "claro")
    ts._detectar_linux = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    check("exceção na detecção não derruba o app",
          ts.detectar_tema_sistema() == "escuro")
finally:
    ts._eh_windows = _orig_windows
    ts.sys.platform = _orig_platform
    ts._detectar_linux = _orig_linux

# ── 4. Modos do painel (alternar manual x automático) ───────────────
class _Var:
    def __init__(self, valor):
        self.valor = valor

    def set(self, valor):
        self.valor = valor


class _MenuFalso:
    def __init__(self):
        self.estados = {}

    def entryconfigure(self, indice, **kwargs):
        self.estados[indice] = kwargs.get("state")


class _Host(tp.TemaPainelMixin):
    def __init__(self, tema, modo):
        self.tema = tema
        self.tema_modo = modo
        self.config_data = {}
        self.aplicados = []
        self.salvo = None
        self._var_tema_auto = _Var(modo == "auto")
        self._var_tema_claro = _Var(tema == "claro")

    def _salvar_tema(self):
        self.salvo = self.tema_modo
        self.config_data["tema"] = self.tema_modo

    def _aplicar_tema(self):
        self.aplicados.append(self.tema)


_orig_resolver = tp.resolver_tema
_detectado = ["claro"]
try:
    tp.resolver_tema = lambda modo: (
        _detectado[0] if modo == "auto" else modo)

    # Manual: claro -> escuro e o automático é desligado.
    _h = _Host("claro", "claro")
    _h._alternar_tema()
    check("alternar manual claro->escuro",
          (_h.tema, _h.tema_modo) == ("escuro", "escuro"),
          f"{_h.tema}/{_h.tema_modo}")
    check("alternar manual persiste o modo escuro", _h.salvo == "escuro")
    check("alternar manual repinta uma vez", _h.aplicados == ["escuro"],
          str(_h.aplicados))
    check("alternar manual desmarca o automático",
          _h._var_tema_auto.valor is False)

    # Manual: escuro -> claro.
    _h = _Host("escuro", "escuro")
    _h._alternar_tema()
    check("alternar manual escuro->claro",
          (_h.tema, _h.tema_modo) == ("claro", "claro"),
          f"{_h.tema}/{_h.tema_modo}")
    check("alternar manual marca o Tema Claro",
          _h._var_tema_claro.valor is True)

    # Ligar o automático segue o SO (claro) e persiste "auto".
    _h = _Host("escuro", "escuro")
    _h._alternar_tema_automatico()
    check("ligar automático aplica o tema do SO",
          (_h.tema, _h.tema_modo) == ("claro", "auto"),
          f"{_h.tema}/{_h.tema_modo}")
    check("ligar automático persiste auto", _h.salvo == "auto")
    check("ligar automático repinta uma vez", _h.aplicados == ["claro"],
          str(_h.aplicados))
    check("ligar automático marca as duas opções",
          _h._var_tema_auto.valor is True
          and _h._var_tema_claro.valor is True)

    # Desligar o automático mantém o tema efetivo como escolha manual.
    _h = _Host("claro", "auto")
    _h._alternar_tema_automatico()
    check("desligar automático vira escolha manual",
          (_h.tema, _h.tema_modo) == ("claro", "claro"),
          f"{_h.tema}/{_h.tema_modo}")
    check("desligar automático não repinta sem troca",
          _h.aplicados == [], str(_h.aplicados))
    check("desligar automático desmarca a opção",
          _h._var_tema_auto.valor is False)

    # Ctrl+T com o automático ligado vira escolha manual.
    _h = _Host("claro", "auto")
    _h._alternar_tema()
    check("Ctrl+T sai do automático",
          (_h.tema, _h.tema_modo) == ("escuro", "escuro"),
          f"{_h.tema}/{_h.tema_modo}")

    # Modo inválido no config é tratado como automático.
    _h = _Host("escuro", "auto")
    _h._definir_tema("roxo")
    check("modo inválido vira automático",
          (_h.tema, _h.tema_modo) == ("claro", "auto"),
          f"{_h.tema}/{_h.tema_modo}")

    # Mudança do sistema com o app aberto: aplica e atualiza o menu.
    _h = _Host("escuro", "auto")
    _h._aplicar_tema_detectado("claro")
    check("sistema mudou para claro com o app aberto",
          _h.tema == "claro" and _h.aplicados == ["claro"],
          f"{_h.tema}/{_h.aplicados}")
    check("mudança em tempo real marca o Tema Claro",
          _h._var_tema_claro.valor is True)
    _h = _Host("escuro", "escuro")
    _h._aplicar_tema_detectado("claro")
    check("checagem é ignorada no modo manual",
          _h.tema == "escuro" and _h.aplicados == [])
    _h = _Host("escuro", "auto")
    _h._aplicar_tema_detectado("neon")
    check("detecção inválida não altera o tema",
          _h.tema == "escuro" and _h.aplicados == [])

    # No automático, "Tema Claro" fica desabilitado (quem decide é o SO).
    _h = _Host("claro", "auto")
    _h._menu_visualizar = _MenuFalso()
    _h._indice_tema_claro = 3
    _h._sincronizar_vars_tema()
    check("automático desabilita Tema Claro",
          _h._menu_visualizar.estados.get(3) == "disabled",
          str(_h._menu_visualizar.estados))
    _h._definir_tema("claro")
    check("desligar o automático reabilita Tema Claro",
          _h._menu_visualizar.estados.get(3) == "normal",
          str(_h._menu_visualizar.estados))
finally:
    tp.resolver_tema = _orig_resolver

# ── 4b. GNOME claro sem preferência explícita (caso Ubuntu/Yaru) ────
_orig_gsettings = ts._gsettings
_orig_rodar = ts._rodar
_orig_kde = ts._ler_kdeglobals
_orig_gtk = ts._ler_gtk_settings
_orig_env_gtk = os.environ.get("GTK_THEME")
_orig_env_qt = os.environ.get("QT_STYLE_OVERRIDE")
try:
    os.environ.pop("GTK_THEME", None)
    os.environ.pop("QT_STYLE_OVERRIDE", None)
    ts._rodar = lambda *a, **k: None
    ts._ler_kdeglobals = lambda: None
    ts._ler_gtk_settings = lambda: None

    def _gsettings_gnome(esquema, chave):
        if esquema != "org.gnome.desktop.interface":
            return None
        if chave == "color-scheme":
            return "'default'"
        if chave == "gtk-theme":
            return "'Yaru'"
        return None

    ts._gsettings = _gsettings_gnome
    check("GNOME claro sem preferência (Yaru) detecta claro",
          ts._detectar_linux() == "claro")

    def _gsettings_kde(esquema, chave):
        if esquema == "org.gnome.desktop.interface":
            if chave == "color-scheme":
                return "'default'"
            if chave == "gtk-theme":
                return "'Adwaita'"
        return None

    ts._gsettings = _gsettings_kde
    ts._ler_kdeglobals = lambda: "[General]\nColorScheme=BreezeDark\n"
    check("KDE escuro vence um tema GTK neutro",
          ts._detectar_linux() == "escuro")

    def _gsettings_dark(esquema, chave):
        if esquema == "org.gnome.desktop.interface":
            if chave == "color-scheme":
                return "'default'"
            if chave == "gtk-theme":
                return "'Yaru-dark'"
        return None

    ts._gsettings = _gsettings_dark
    ts._ler_kdeglobals = lambda: None
    check("tema GTK com dark continua escuro",
          ts._detectar_linux() == "escuro")

    ts._gsettings = lambda esquema, chave: None
    check("Linux sem informação nenhuma fica indefinido",
          ts._detectar_linux() is None)
finally:
    ts._gsettings = _orig_gsettings
    ts._rodar = _orig_rodar
    ts._ler_kdeglobals = _orig_kde
    ts._ler_gtk_settings = _orig_gtk
    for nome, valor in (("GTK_THEME", _orig_env_gtk),
                        ("QT_STYLE_OVERRIDE", _orig_env_qt)):
        if valor is None:
            os.environ.pop(nome, None)
        else:
            os.environ[nome] = valor

# ── 5. Integração: padrão auto e menu têm as duas opções ────────────
_src_navepro = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
_src_painel = open(os.path.join(RAIZ, "navepro", "ui", "painel.py"),
                   encoding="utf-8").read()
check("config sem tema abre no modo automático",
      'self.config_data.get("tema", "auto")' in _src_navepro)
check("menu Visualizar mostra Tema Automático",
      'label="Tema Automático"' in _src_painel)
check("menu mantém a opção Tema Claro",
      'label="Tema Claro"' in _src_painel)

print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas else f"FALHAS: {falhas}"))
sys.exit(1 if falhas else 0)
