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