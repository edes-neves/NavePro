"""Detecção de monitores (screeninfo > xrandr > tkinter).

Extraído de NavePro.py sem alterar o comportamento (ver AGENTS.md).
"""

import subprocess
import time
import tkinter as tk

try:
    from screeninfo import get_monitors as _get_monitors
    _HAS_SCREENINFO = True
except ImportError:
    _HAS_SCREENINFO = False

from navepro.config import CACHE_TTL_SEGUNDOS
from navepro.core.ambiente import _ambiente_sem_appimage, _eh_linux
from navepro.core.log import get_logger

log = get_logger("monitores")


# ────────────────────────────────────────────────────────────────────
# MONITORES - DETECÇÃO (mantido)
# ────────────────────────────────────────────────────────────────────


class MonitorInfo:
    """Informações de um monitor detectado."""
    def __init__(self, x: int, y: int, w: int, h: int, name: str = "Monitor",
                 primary: bool = False) -> None:
        self.x = x
        self.y = y
        self.width = w
        self.height = h
        self.name = name
        self.primary = primary

    def __repr__(self) -> str:
        return (f"Monitor({self.name}: {self.width}x{self.height} em ({self.x},{self.y})"
                f"{' [primário]' if self.primary else ''})")


# Cache global de monitores com TTL
_MONITORS_CACHE: tuple[float, list[MonitorInfo]] | None = None

def get_monitors_config() -> list[MonitorInfo]:
    """
    Detecta monitores com cache TTL (60s).
    Prioriza screeninfo > xrandr (geometria real) > heurística tkinter.
    """
    global _MONITORS_CACHE
    # Verifica cache
    if _MONITORS_CACHE is not None:
        timestamp, cached = _MONITORS_CACHE
        if time.time() - timestamp < CACHE_TTL_SEGUNDOS:
            return cached
        _MONITORS_CACHE = None

    # Método 1: screeninfo (biblioteca Python, multiplataforma)
    if _HAS_SCREENINFO:
        try:
            monitors = _get_monitors()
            if monitors:
                result = [
                    MonitorInfo(m.x, m.y, m.width, m.height,
                                m.name or f"Monitor {i+1}",
                                primary=getattr(m, 'is_primary', False))
                    for i, m in enumerate(monitors)
                ]
                _MONITORS_CACHE = (time.time(), result)
                log.info(f"✅ screeninfo: {len(monitors)} monitor(es) detectado(s)")
                return result
        except ImportError:
            pass
        except Exception as e:
            log.warning(f"⚠️ screeninfo: {e}")

    # Método 2: xrandr (Linux X11) - geometria REAL dos monitores,
    # evita o palpite de metades iguais quando há telões com resoluções
    # diferentes (ex.: 1920x1080 + 1280x720).
    # No Windows nenhuma dessas ferramentas existe — o screeninfo/cTk dão conta.
    if _eh_linux():
        try:
            result = subprocess.run(
                ['xrandr'], capture_output=True, text=True, timeout=5,
                env=_ambiente_sem_appimage()
            )
            connected: list[MonitorInfo] = []
            for line in result.stdout.split('\n'):
                if ' connected' in line and '+' in line:
                    parts = line.split()
                    primary = ' primary' in line
                    for p in parts:
                        if 'x' in p and '+' in p:
                            size_pos = p.split('+')
                            if len(size_pos) >= 3:
                                size = size_pos[0].split('x')
                                x, y = int(size_pos[1]), int(size_pos[2])
                                w, h = int(size[0]), int(size[1])
                                connected.append(
                                    MonitorInfo(x, y, w, h, parts[0], primary=primary)
                                )
                            break
            if connected:
                connected.sort(key=lambda m: (m.x, m.y))
                _MONITORS_CACHE = (time.time(), connected)
                log.info(f"✅ xrandr: {len(connected)} monitor(es) detectado(s)")
                return connected
        except Exception as e:
            log.warning(f"⚠️ xrandr: {e}")

    # Método 3: tkinter + heurística de largura (apenas último recurso)
    try:
        root = tk.Tk(className="NavePro_monitor")
        root.withdraw()
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        root.destroy()

        if screen_width > 2500:
            half = screen_width // 2
            result = [
                MonitorInfo(0, 0, half, screen_height, "Monitor 1"),
                MonitorInfo(half, 0, screen_width - half, screen_height, "Monitor 2"),
            ]
            result.sort(key=lambda m: (m.x, m.y))
        else:
            result = [MonitorInfo(0, 0, screen_width, screen_height, "Monitor 1")]
        _MONITORS_CACHE = (time.time(), result)
        return result
    except Exception as e:
        log.warning(f"⚠️ tkinter fallback: {e}")

    # Fallback
    log.warning("⚠️ Usando fallback: dual-monitor 1920x1080")
    result = [
        MonitorInfo(0, 0, 1920, 1080, "Monitor 1"),
        MonitorInfo(1920, 0, 1920, 1080, "Monitor 2"),
    ]
    result.sort(key=lambda m: (m.x, m.y))
    _MONITORS_CACHE = (time.time(), result)
    return result
