"""NavePro - Sistema de Projeção para Igrejas.

Camada de infraestrutura pura (Python + stdlib/tkinter), sem dependência
da interface (AppInterface), do player ou do servidor HTTP.
"""

import os
import sys


def _ambiente_sem_appimage() -> dict[str, str]:
    """Retorna um ambiente SEM as bibliotecas embutidas do AppImage.

    Quando o NavePro roda dentro de um AppImage, o runtime injeta
    LD_LIBRARY_PATH (e ARGV0/APPDIR/OWD) apontando para as libs embutidas
    (fontconfig, pango, glib...). Ao lançar programas do sistema
    (smplayer -> mpv, ffprobe, dbus-send, vlc, xrandr...), essa variável
    faz com que eles carreguem versões ERRADAS das bibliotecas e quebrem
    com "symbol lookup error" (ex.: libpangoft2 vs fontconfig).

    Aqui removemos QUALQUER LDLIBRARY_PATH herdado do AppImage antes de
    executar programas externos. O processo NavePro já carregou todas as
    libs que precisa em memória no arranque, então é seguro repassar
    um ambiente sem essa variável aos filhos do sistema.
    """
    env = os.environ.copy()
    for var in ('LD_LIBRARY_PATH', 'APPDIR', 'APPIMAGE', 'OWD', 'ARGV0'):
        env.pop(var, None)
    return env


def _eh_windows() -> bool:
    """True se estivermos rodando no Windows."""
    return sys.platform.startswith('win')


def _eh_linux() -> bool:
    """True se estivermos rodando no Linux."""
    return sys.platform.startswith('linux')


def _tornar_dpi_aware() -> bool:
    """Torna o processo DPI-aware no Windows. Deve ser chamado ANTES de
    qualquer tk.Tk(), porque o Tk 8.6 não é DPI-aware e não se auto-corrige.

    Sem isto, o Tk reporta a tela em pixels LÓGICOS (a resolução virtualizada
    pelo Windows quando há escala de 125%/150%), enquanto o screeninfo — que
    chama SetProcessDpiAwareness(2) na primeira enumeração — passa a reportar
    pixels FÍSICOS. Os dois passam a falar unidades diferentes e o
    geometry("WxH+X+Y") do telão aponta para fora da tela; o Windows então
    puxa a janela de volta para o monitor primário. Sintoma: painel e telão
    abertos no mesmo monitor, e o telão não cobre a segunda tela.

    Em Linux e macOS é no-op: ambos já entregam coordenadas físicas ao Tk.
    """
    if not _eh_windows():
        return False
    try:
        import ctypes
    except ImportError:
        return False

    # Windows 10 1703+: "per monitor v2", o melhor comportamento para
    # telas com escalas diferentes. Precisa vir antes dos demais porque,
    # depois de definido, o contexto não pode ser rebaixado.
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
        return True
    except (AttributeError, OSError):
        pass
    # Windows 8.1+.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return True
    except (AttributeError, OSError):
        pass
    # Vista+ (DPI awareness "system-wide", sem suporte a DPI por monitor).
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return True
    except (AttributeError, OSError):
        pass
    return False


def _eh_flatpak() -> bool:
    """True se o NavePro estiver rodando DENTRO de um Flatpak.

    Detecta pelos dois sinais que o runtime do Flatpak define: a variável
    FLATPAK_ID e o /.flatpak-info na raiz. Importante para a atualização
    automática: quem está instalado como Flatpak se atualiza com
    `flatpak update`, e não substituindo um AppImage baixado.
    """
    if os.environ.get('FLATPAK_ID'):
        return True
    try:
        return os.path.exists('/.flatpak-info')
    except OSError:
        return False


def _eh_appimage() -> bool:
    """True se o NavePro estiver rodando a partir de um AppImage.

    O AppImage define APPIMAGE com o caminho do próprio arquivo, além de
    APPDIR/OWD (removidos em _ambiente_sem_appimage ao lançar filhos).
    """
    return bool(os.environ.get('APPIMAGE'))