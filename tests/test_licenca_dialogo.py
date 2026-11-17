#!/usr/bin/env python3
"""Testes headless do seletor de licença (pastas ocultas escondidas)."""

import os
import sys
import tkinter as tk

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from navepro.ui import licenca  # noqa: E402

falhas = 0


def checar(desc, cond, extra=""):
    global falhas
    print(f"{'OK ' if cond else 'X  '} {desc}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas += 1


class TkFalso:
    def __init__(self):
        self.tk = self
        self.valores = {
            "::tk::dialog::file::showHiddenBtn": 0,
            "::tk::dialog::file::showHiddenVar": 1,
        }
        self.auto_loads = []
        self.chamadas = []

    def call(self, *args):
        self.chamadas.append(args)
        if args[0] == "auto_load":
            self.auto_loads.append(args[1])
            return 1
        if args[0] == "set":
            nome = args[1]
            if nome not in self.valores:
                raise tk.TclError(f"can't read {nome}")
            if len(args) == 2:
                return self.valores[nome]
            self.valores[nome] = args[2]
            return ""
        raise tk.TclError(f"comando inesperado: {args[0]}")


def _rodar() -> int:
    root = TkFalso()
    falso_self = type("Falso", (), {"root": root})()
    janela = object()
    vistos = {}
    original = licenca.tkinter.filedialog.askopenfilename

    def ask_falso(**kwargs):
        vistos.update(kwargs)
        vistos["btn_durante"] = root.valores[
            "::tk::dialog::file::showHiddenBtn"]
        vistos["var_durante"] = root.valores[
            "::tk::dialog::file::showHiddenVar"]
        return "/tmp/licenca.key"

    licenca.tkinter.filedialog.askopenfilename = ask_falso
    try:
        caminho = licenca.LicencaMixin._selecionar_arquivo_licenca(
            falso_self, janela)
    finally:
        licenca.tkinter.filedialog.askopenfilename = original

    checar("retorna o caminho escolhido", caminho == "/tmp/licenca.key", caminho)
    checar("abre na pasta do usuário",
           vistos.get("initialdir") == os.path.expanduser("~"),
           str(vistos.get("initialdir")))
    checar("usa a janela de licença como pai", vistos.get("parent") is janela)
    checar("carrega o diálogo de arquivos do Tk",
           root.auto_loads == ["::tk::dialog::file::"],
           str(root.auto_loads))
    checar("esconde pastas ocultas por padrão",
           vistos.get("var_durante") == 0, str(vistos.get("var_durante")))
    checar("mostra o botão de arquivos ocultos",
           vistos.get("btn_durante") == 1, str(vistos.get("btn_durante")))
    checar("restaura a configuração anterior do diálogo",
           root.valores["::tk::dialog::file::showHiddenBtn"] == 0
           and root.valores["::tk::dialog::file::showHiddenVar"] == 1,
           str(root.valores))

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
