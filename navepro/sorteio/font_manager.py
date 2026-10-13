"""Font family resolution for cross-platform rendering.

The bundled Tcl/Tk shipped with python-build-standalone is built without
Xft/fontconfig, so it can only use X core fonts.  On such builds the family
"Arial" is unknown and every widget falls back to the tiny bitmap "fixed"
font.  This module resolves the preferred family to the best one actually
available at runtime, keeping the same look on the development machine
(Arial via fontconfig) and readable fonts inside the AppImage.

The core-font X server path usually lacks the Liberation family, so Tk
would fall back to the wider DejaVu Sans and distort the layout.  To avoid
that, this module appends a directory with Liberation .ttf files (bundled
with the AppImage, or the system one) to the server's core-font path.
"""

import ctypes
import ctypes.util
import os
import sys
import tkinter as tk

_UI_FONT = "Arial"
_FAMILIES: set[str] = set()
_QUERIED = False
_FONT_PATH_SETUP_DONE = False

_FALLBACKS = [
    "Liberation Sans",
    "DejaVu Sans",
    "Noto Sans",
    "Helvetica",
    "Inconsolata",
    "TkDefaultFont",
]


def _bundled_font_dirs() -> list[str]:
    """Directories that contain Liberation core-font .ttf files, in order."""
    dirs: list[str] = []
    here = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
    )
    bundled = os.path.join(here, "usr", "share", "fonts", "liberation")
    if os.path.isfile(os.path.join(bundled, "fonts.dir")):
        dirs.append(bundled)
    system = os.path.join(os.path.sep, "usr", "share", "fonts", "liberation")
    if os.path.isfile(os.path.join(system, "fonts.dir")) and system not in dirs:
        dirs.append(system)
    return dirs


def _ensure_liberation_core_fonts() -> None:
    """Add Liberation to the X core-font path for no-xft Tk builds.

    The bundled Tcl/Tk resolves families against the X server's core fonts
    only, and Liberation Sans is normally absent from that path.  This
    appends a directory containing Liberation .ttf files (bundled or system)
    to the server's font path once, before any family list is queried.
    """
    global _FONT_PATH_SETUP_DONE
    if _FONT_PATH_SETUP_DONE:
        return
    dirs = _bundled_font_dirs()
    if not dirs:
        _FONT_PATH_SETUP_DONE = True
        return
    try:
        lib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        display = lib.XOpenDisplay(None)
        if not display:
            return
        lib.XGetFontPath.restype = ctypes.POINTER(ctypes.c_char_p)
        lib.XGetFontPath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        lib.XFreeFontPath.argtypes = [ctypes.c_void_p]
        lib.XSetFontPath.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.c_int,
        ]
        lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XCloseDisplay.restype = ctypes.c_int
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        count = ctypes.c_int(0)
        paths = lib.XGetFontPath(display, ctypes.byref(count))
        existing = [paths[i].decode(errors="replace") for i in range(count.value)]
        # The X server rejects the request if any entry does not exist on
        # disk.  Drop stale absolute dirs (e.g. a previous AppImage mount)
        # but keep pseudo-entries like "built-ins".
        existing = [
            p
            for p in existing
            if not p.startswith("/") or os.path.isdir(p)
        ]
        changed = False
        for d in dirs:
            if d not in existing:
                existing.append(d)
                changed = True
        if changed:
            array = (ctypes.c_char_p * len(existing))(*[p.encode() for p in existing])
            lib.XSetFontPath(display, array, len(existing))
            lib.XSync(display, 0)
        lib.XFreeFontPath(paths)
        lib.XCloseDisplay(display)
    except Exception:
        pass


_ensure_liberation_core_fonts()


def _available_families() -> set[str]:
    global _FAMILIES, _QUERIED
    if not _QUERIED:
        _ensure_liberation_core_fonts()
        try:
            import tkinter.font as tkfont
            root = tk._default_root
            if root is not None:
                _FAMILIES = {f.lower() for f in tkfont.families(root)}
                _QUERIED = True
        except Exception:
            _FAMILIES = set()
    return _FAMILIES


def ui_font(preferred: str = "Arial") -> str:
    """Returns the preferred family, or the best available substitute."""
    global _UI_FONT
    families = _available_families()
    if preferred.lower() in families:
        _UI_FONT = preferred
        return _UI_FONT
    for candidate in _FALLBACKS:
        if candidate.lower() in families:
            _UI_FONT = candidate
            return _UI_FONT
    _UI_FONT = "Fixed"
    return _UI_FONT


def is_using_fallback() -> bool:
    """True when no scalable family is available (tiny bitmap fonts)."""
    return ui_font().lower() == "fixed"
