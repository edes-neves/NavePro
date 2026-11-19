"""Detecção do tema claro/escuro do sistema operacional.

O modo automático do painel usa este módulo para abrir o NavePro já com o
tema do sistema. A detecção é conservadora: qualquer falha (comando ausente,
saída inesperada ou sistema sem preferência) cai no tema ESCURO, que é o
padrão histórico do app. Nada aqui toca nas cores do telão.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

from navepro.core.ambiente import _ambiente_sem_appimage, _eh_windows

ESCURO = "escuro"
CLARO = "claro"


def _tema_por_esquema(valor: str | None) -> str | None:
    """Interpreta ``color-scheme`` (GNOME/portal): prefer-dark/prefer-light."""
    if not valor:
        return None
    texto = str(valor).strip().lower()
    if "prefer-dark" in texto:
        return ESCURO
    if "prefer-light" in texto:
        return CLARO
    return None


def _tema_por_nome_tema(nome: str | None) -> str | None:
    """Interpreta nomes de tema/estilo que carregam "dark" ou "light"."""
    if not nome:
        return None
    texto = str(nome).strip().lower()
    if "dark" in texto:
        return ESCURO
    if "light" in texto:
        return CLARO
    return None


def _tema_por_saida_portal(saida: str | None) -> str | None:
    """Interpreta a resposta do xdg-desktop-portal (1=escuro, 2=claro)."""
    if not saida:
        return None
    match = re.search(r"uint32\s+([012])", str(saida))
    if not match:
        return None
    return {1: ESCURO, 2: CLARO}.get(int(match.group(1)))


def _tema_por_kdeglobals(texto: str | None) -> str | None:
    """Interpreta ``~/.config/kdeglobals`` (KDE Plasma).

    Usa o nome do esquema de cores quando ele diz dark/light e, se preciso,
    a luminosidade de ``[Colors:Window] BackgroundNormal``.
    """
    if not texto:
        return None
    secao = ""
    esquema = None
    fundo = None
    for linha in str(texto).splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        if linha.startswith("[") and linha.endswith("]"):
            secao = linha[1:-1].strip().lower()
            continue
        if "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        chave = chave.strip().lower()
        valor = valor.strip()
        if secao == "general" and chave == "colorscheme":
            esquema = valor
        elif secao == "colors:window" and chave == "backgroundnormal":
            fundo = valor
    tema = _tema_por_nome_tema(esquema)
    if tema:
        return tema
    try:
        r, g, b = (int(parte) for parte in fundo.split(",")[:3])
    except (AttributeError, TypeError, ValueError):
        return None
    return ESCURO if (r + g + b) / 3 < 128 else CLARO


def _tema_por_gtk_settings(texto: str | None) -> str | None:
    """Interpreta ``settings.ini`` do GTK (gtk-3.0/gtk-4.0).

    É o último recurso no Linux: serve para desktops que não expõem a
    preferência por gsettings nem pelo portal (Xfce, LXDE, etc.).
    """
    if not texto:
        return None
    nome = None
    prefere_escuro = False
    for linha in str(texto).splitlines():
        linha = linha.strip()
        if not linha or linha.startswith(("#", ";")) or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        chave = chave.strip().lower()
        valor = valor.strip()
        if chave == "gtk-theme-name":
            nome = valor
        elif chave == "gtk-application-prefer-dark-theme":
            prefere_escuro = valor.lower() in ("1", "true", "yes", "on")
    if prefere_escuro:
        return ESCURO
    tema = _tema_por_nome_tema(nome)
    if tema:
        return tema
    # Um tema nomeado sem "dark" e sem preferência explícita é claro.
    return CLARO if nome else None


def _rodar(comando: list[str], timeout: float = 2.0):
    """Executa um comando curto de detecção; devolve None em qualquer falha."""
    try:
        return subprocess.run(
            comando, capture_output=True, text=True, errors="replace",
            timeout=timeout, env=_ambiente_sem_appimage(),
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _saida(proc) -> str | None:
    if proc is None or proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


def _gsettings(esquema: str, chave: str) -> str | None:
    return _saida(_rodar([
        "gsettings", "get", esquema, chave,
    ]))


# Desktops que guardam a preferência clara/escura em esquemas gsettings.
# Cinnamon e MATE mantêm esquemas próprios; consultar os três é barato e
# cobre a maioria das distros (GNOME, Ubuntu, Mint, Debian/MATE...).
_ESQUEMAS_INTERFACE = (
    "org.gnome.desktop.interface",
    "org.cinnamon.desktop.interface",
    "org.mate.interface",
)


def _ler_arquivo_texto(caminho: str) -> str | None:
    try:
        with open(caminho, encoding="utf-8", errors="replace") as arquivo:
            return arquivo.read()
    except OSError:
        return None


def _ler_kdeglobals() -> str | None:
    return _ler_arquivo_texto(os.path.join(
        os.path.expanduser("~"), ".config", "kdeglobals"))


def _ler_gtk_settings() -> str | None:
    """Lê o settings.ini do GTK 4 (preferido) ou do GTK 3."""
    base = os.path.join(os.path.expanduser("~"), ".config")
    for pasta in ("gtk-4.0", "gtk-3.0"):
        texto = _ler_arquivo_texto(
            os.path.join(base, pasta, "settings.ini"))
        if texto:
            return texto
    return None


def _detectar_linux() -> str | None:
    # 1) Preferência explícita clara/escura (GNOME 42+, Cinnamon, MATE).
    for esquema in _ESQUEMAS_INTERFACE:
        tema = _tema_por_esquema(_gsettings(esquema, "color-scheme"))
        if tema:
            return tema
    # 2) Portal do desktop: funciona também dentro do Flatpak e no KDE.
    tema = _tema_por_saida_portal(_saida(_rodar([
        "gdbus", "call", "--session",
        "--dest", "org.freedesktop.portal.Desktop",
        "--object-path", "/org/freedesktop/portal/desktop",
        "--method", "org.freedesktop.portal.Settings.Read",
        "org.freedesktop.appearance", "color-scheme",
    ])))
    if tema:
        return tema

    # Nome de tema GTK NEUTRO (Yaru, Adwaita, Breeze...) indica CLARO: só o
    # tema escuro leva "dark" no nome. É o caso do Ubuntu/GNOME em modo
    # claro, que devolve color-scheme "default" e portal 0 (sem preferência)
    # — antes essa ausência de preferência caía no escuro e o modo
    # automático nunca acompanhava o sistema claro. O nome neutro fica
    # guardado para o FIM, para não atropelar o KDE nem o settings.ini de um
    # desktop onde o esquema GNOME exista apenas como padrão do dconf.
    tema_neutro = None

    def _classificar_nome_tema(valor: str | None) -> str | None:
        nonlocal tema_neutro
        tema = _tema_por_nome_tema(valor)
        if tema:
            return tema
        if valor and tema_neutro is None:
            tema_neutro = valor
        return None

    # 3) Nome do tema GTK (versões antigas do GNOME usam "* -dark").
    for esquema in _ESQUEMAS_INTERFACE:
        tema = _classificar_nome_tema(_gsettings(esquema, "gtk-theme"))
        if tema:
            return tema
    # 4) KDE Plasma.
    tema = _tema_por_kdeglobals(_ler_kdeglobals())
    if tema:
        return tema
    # 5) Xfce (xfconf) e desktops que só escrevem o settings.ini do GTK.
    tema = _classificar_nome_tema(_saida(_rodar([
        "xfconf-query", "-c", "xsettings", "-p", "/Net/ThemeName",
    ])))
    if tema:
        return tema
    tema = _tema_por_gtk_settings(_ler_gtk_settings())
    if tema:
        return tema
    # 6) Variáveis de ambiente definidas pelo desktop/Flatpak.
    for variavel in ("GTK_THEME", "QT_STYLE_OVERRIDE"):
        tema = _classificar_nome_tema(os.environ.get(variavel))
        if tema:
            return tema
    # Desktop reconhecido por um tema claro, mas sem preferência explícita.
    if tema_neutro:
        return CLARO
    return None


def _detectar_macos() -> str | None:
    proc = _rodar(["defaults", "read", "-g", "AppleInterfaceStyle"])
    if proc is None:
        return None
    if proc.returncode == 0:
        return ESCURO if "dark" in (proc.stdout or "").lower() else None
    # A chave só existe quando o modo escuro está ativo; sem ela, é claro.
    return CLARO


def _detectar_windows() -> str | None:
    try:
        import winreg
    except ImportError:
        return None
    caminho = (
        r"Software\Microsoft\Windows\CurrentVersion"
        r"\Themes\Personalize")

    def _ler(nome: str) -> int | None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, caminho) as chave:
                valor, _tipo = winreg.QueryValueEx(chave, nome)
            return int(valor)
        except (OSError, TypeError, ValueError):
            return None

    # "AppsUseLightTheme" é o modo dos aplicativos (o que o NavePro segue).
    # Em Windows antigos ele pode faltar; nesse caso usa o modo do sistema.
    valor = _ler("AppsUseLightTheme")
    if valor is None:
        valor = _ler("SystemUsesLightTheme")
    if valor is None:
        return None
    return CLARO if valor else ESCURO


def detectar_tema_sistema() -> str:
    """Detecta o tema do SO e devolve ``escuro`` ou ``claro``.

    Nunca levanta exceção: sem informação confiável, mantém o tema escuro.
    """
    try:
        if _eh_windows():
            tema = _detectar_windows()
        elif sys.platform == "darwin":
            tema = _detectar_macos()
        else:
            tema = _detectar_linux()
    except Exception:
        tema = None
    return tema if tema in (CLARO, ESCURO) else ESCURO


def resolver_tema(valor: str | None, detectar=None) -> str:
    """Resolve o valor salvo no config para o tema efetivo.

    ``claro``/``escuro`` são escolhas manuais; ``auto``, valor ausente ou
    inválido consulta o sistema operacional.
    """
    if valor == CLARO:
        return CLARO
    if valor == ESCURO:
        return ESCURO
    funcao = detectar or detectar_tema_sistema
    try:
        tema = funcao()
    except Exception:
        tema = None
    return tema if tema in (CLARO, ESCURO) else ESCURO
