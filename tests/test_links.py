#!/usr/bin/env python3
"""Testes da abertura externa de URLs (e-mail/WhatsApp da licença)."""

import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import navepro.core.links as links  # noqa: E402

falhas = 0


def checar(desc, cond, extra=""):
    global falhas
    print(f"{'OK ' if cond else 'X  '} {desc}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas += 1


class PopenFake:
    chamadas = []

    def __init__(self, *args, **kwargs):
        self.chamadas.append((args, kwargs))


def _rodar() -> int:
    originais = {
        "_eh_windows": links._eh_windows,
        "_eh_flatpak": links._eh_flatpak,
        "which": links.shutil.which,
        "Popen": links.subprocess.Popen,
    }
    env_original = os.environ.copy()
    try:
        links.shutil.which = lambda nome: (
            "/usr/bin/xdg-open" if nome == "xdg-open" else None)
        links._eh_windows = lambda: False
        links._eh_flatpak = lambda: False
        links.subprocess.Popen = PopenFake

        PopenFake.chamadas.clear()
        checar("URL vazia não abre nada",
               links.abrir_url_externa("") is False
               and not PopenFake.chamadas)

        os.environ["GDK_BACKEND"] = "x11"
        os.environ["LD_LIBRARY_PATH"] = "/tmp/libs"
        os.environ["APPDIR"] = "/tmp/appdir"
        PopenFake.chamadas.clear()
        ok = links.abrir_url_externa("https://wa.me/554431700809")
        args, kwargs = PopenFake.chamadas[0]
        env = kwargs.get("env")
        checar("Linux usa xdg-open", ok and args[0] == [
            "xdg-open", "https://wa.me/554431700809"])
        checar("remove GDK_BACKEND do processo externo",
               "GDK_BACKEND" not in env)
        checar("remove LD_LIBRARY_PATH do AppImage/PyInstaller",
               "LD_LIBRARY_PATH" not in env and "APPDIR" not in env)
        checar("processo externo é independente e silencioso",
               kwargs.get("start_new_session") is True
               and kwargs.get("cwd") == "/"
               and kwargs.get("stdout") == links.subprocess.DEVNULL
               and kwargs.get("stderr") == links.subprocess.DEVNULL)

        links._eh_flatpak = lambda: True
        PopenFake.chamadas.clear()
        ok = links.abrir_url_externa("mailto:x@y.com")
        args, _ = PopenFake.chamadas[0]
        checar("Flatpak entrega a URL ao xdg-open do host",
               ok and args[0] == [
                   "flatpak-spawn", "--host", "xdg-open", "mailto:x@y.com"])

        links._eh_flatpak = lambda: False
        links.shutil.which = lambda nome: (
            "/usr/bin/gio" if nome == "gio" else None)
        PopenFake.chamadas.clear()
        ok = links.abrir_url_externa("mailto:x@y.com")
        args, _ = PopenFake.chamadas[0]
        checar("sem xdg-open usa gio open",
               ok and args[0] == [
                   "gio", "open", "--", "mailto:x@y.com"])

        links.shutil.which = lambda nome: None
        PopenFake.chamadas.clear()
        checar("sem abridor disponível retorna False",
               links.abrir_url_externa("https://exemplo.com") is False)

        links.shutil.which = lambda nome: (
            "/usr/bin/xdg-open" if nome == "xdg-open" else None)

        def _falha(*_a, **_k):
            raise OSError("sem display")

        links.subprocess.Popen = _falha
        checar("falha ao executar o abridor não derruba o app",
               links.abrir_url_externa("https://exemplo.com") is False)
    finally:
        links._eh_windows = originais["_eh_windows"]
        links._eh_flatpak = originais["_eh_flatpak"]
        links.shutil.which = originais["which"]
        links.subprocess.Popen = originais["Popen"]
        os.environ.clear()
        os.environ.update(env_original)

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
