#!/usr/bin/env python3
"""Testes de segurança da importação .navepro (navepro/core/transferencia.py).

Trava o zip-slip: um pacote malicioso não pode escrever FORA da pasta
temporária de extração. No Windows "\" também é separador de caminho, então
"midia/..\\..\\evil.txt" escaparia — o `_abrir_pacote` precisa normalizar a
barra invertida antes do filtro de ".."/absoluto.
"""

import ast
import json
import os
import shutil
import sys
import tempfile
import zipfile

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
if _AQUI not in sys.path:
    sys.path.insert(0, _AQUI)

from fixture_log import log  # noqa: E402

_MOD = os.path.join(RAIZ, "navepro", "core", "transferencia.py")
_SRC = open(_MOD, encoding="utf-8").read()
_TREE = ast.parse(_SRC)

_NOMES_CONST = ("PASTA_MIDIA", "ARQ_MANIFESTO", "ARQ_ANUNCIOS",
                "ARQ_SERVICOS", "FORMATO_TRANSFERENCIA",
                "EXTENSAO_TRANSFERENCIA")


def _constantes() -> dict:
    ns: dict = {}
    for no in _TREE.body:
        if (isinstance(no, ast.Assign)
                and isinstance(no.targets[0], ast.Name)
                and no.targets[0].id in _NOMES_CONST):
            ns[no.targets[0].id] = ast.literal_eval(no.value)
    return ns


def _montar_abrir(windows: bool):
    """Extrai _abrir_pacote via AST com _eh_windows fixo (injetável)."""
    ns: dict = {
        "os": os, "shutil": shutil, "tempfile": tempfile,
        "zipfile": zipfile, "json": json, "log": log,
        "_eh_windows": lambda: windows,
    }
    ns.update(_constantes())
    for no in ast.walk(_TREE):
        if isinstance(no, ast.FunctionDef) and no.name == "_abrir_pacote":
            exec(compile(ast.get_source_segment(_SRC, no), "<_abrir_pacote>",
                         "exec"), ns)  # noqa: S102
            return ns["_abrir_pacote"]
    raise AssertionError("_abrir_pacote não encontrada em transferencia.py")


def _extraidos(temp_dir: str) -> set[str]:
    """Nomes de arquivos extraídos dentro do temp_dir (sempre com "/").

    No Windows o `os.path.relpath` devolve "\\"; normalizamos para comparar
    com os nomes do ZIP, que usam "/".
    """
    nomes = set()
    for raiz, _, arquivos in os.walk(temp_dir):
        for nome in arquivos:
            rel = os.path.relpath(os.path.join(raiz, nome), temp_dir)
            nomes.add(rel.replace(os.sep, "/"))
    return nomes


def _rodar() -> int:
    falhas = 0

    def checar(desc, cond):
        nonlocal falhas
        print(f"{'OK ' if cond else 'X  '} {desc}")
        if not cond:
            falhas += 1

    const = _constantes()

    with tempfile.TemporaryDirectory() as raiz:
        pacote = os.path.join(raiz, "malicioso.navepro")
        escape_abs = f"escape-{os.getpid()}-abs.txt"
        escape_win = f"escape-{os.getpid()}-win.txt"
        with zipfile.ZipFile(pacote, "w") as zf:
            zf.writestr(const["ARQ_ANUNCIOS"], json.dumps([]))
            zf.writestr("midia/ok.mp4", b"ok")
            zf.writestr(f"midia/../../{escape_abs}", b"fora")
            zf.writestr(f"midia/..\\..\\{escape_win}", b"fora2")

        # ── 1. Windows: "\" é separador — o membro tem de ser DESCARTADO ─
        abrir_win = _montar_abrir(windows=True)
        resultado = abrir_win(pacote)
        checar("Windows: abre o pacote normalmente",
               isinstance(resultado, dict) and "temp_dir" in resultado)
        checar("Windows: só o arquivo legítimo é extraído",
               _extraidos(resultado["temp_dir"]) == {"midia/ok.mp4"})
        # O alvo do zip-slip fica 2 níveis acima do temp_dir (ex.: /tmp).
        fora = os.path.dirname(resultado["temp_dir"])
        vazou_win = (os.path.exists(os.path.join(fora, escape_win))
                     or os.path.exists(os.path.join(fora, escape_abs)))
        checar("Windows: nada é escrito fora do temp_dir (zip-slip)",
               not vazou_win)
        shutil.rmtree(resultado["temp_dir"], ignore_errors=True)

        # ── 2. Linux: "\" é caractere literal — comportamento de sempre ─
        # No Windows o host trata "\" como separador, então esta simulação
        # não representa o Linux de verdade: pulamos para não dar falso
        # negativo. O caso crítico (Windows) já foi coberto acima.
        if os.name == "nt":
            print("--  Linux: simulação de separador pulada no Windows")
        else:
            abrir_linux = _montar_abrir(windows=False)
            resultado = abrir_linux(pacote)
            extraidos = _extraidos(resultado["temp_dir"])
            checar("Linux: membro com barra invertida continua contido",
                   "midia/..\\..\\" + escape_win in extraidos
                   and "midia/ok.mp4" in extraidos)
            checar("Linux: o ../ de barra normal continua filtrado",
                   escape_abs not in extraidos)
            fora = os.path.dirname(resultado["temp_dir"])
            vazou_linux = (os.path.exists(os.path.join(fora, escape_win))
                           or os.path.exists(os.path.join(fora, escape_abs)))
            checar("Linux: nada escapa do temp_dir",
                   not vazou_linux)
            shutil.rmtree(resultado["temp_dir"], ignore_errors=True)

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
