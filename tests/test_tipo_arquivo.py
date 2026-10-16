"""Testa ``MediaPlayer._eh_arquivo_de_video``.

Bug coberto: a função retornava ``(bool, PLAYER_PADRAO)`` por causa de uma
vírgula sobrando (``... in EXTENSOES_VIDEO, PLAYER_PADRAO``). Como toda tupla
não-vazia é truthy, arquivos de áudio passavam a ser tratados como vídeo —
disparando a thread ``navepro-pos-player`` no Windows para áudio.
"""

import ast
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

from navepro.config import EXTENSOES_VIDEO  # noqa: E402

_SRC = open(
    os.path.join(RAIZ, "navepro", "core", "mediaplayer.py"), encoding="utf-8"
).read()
_ARVORE = ast.parse(_SRC)

_no_metodo = None
for _node in ast.walk(_ARVORE):
    if isinstance(_node, ast.ClassDef) and _node.name == "MediaPlayer":
        for _sub in _node.body:
            if isinstance(_sub, ast.FunctionDef) and _sub.name == "_eh_arquivo_de_video":
                _no_metodo = _sub
assert _no_metodo is not None, "MediaPlayer._eh_arquivo_de_video não encontrado"

_mod = ast.Module(body=[_no_metodo], type_ignores=[])
ast.fix_missing_locations(_mod)
_ns = {"os": os, "EXTENSOES_VIDEO": EXTENSOES_VIDEO}
exec(compile(_mod, "<MediaPlayer._eh_arquivo_de_video>", "exec"), _ns)
eh_video = _ns["_eh_arquivo_de_video"]

falhas = []


def check(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


# O retorno PRECISA ser bool — não uma tupla.
for _caso, _esperado in (
    ("filme.mp4", True),
    ("FOTO.MKV", True),
    ("musica.mp3", False),
    ("podcast.mp3", False),
    ("sermao.wav", False),
    ("", False),
    ("sem_extensao", False),
    (None, False),
):
    _r = eh_video(None, _caso)
    check(f"{_caso!r} -> {_esperado}", _r is _esperado, f"retornou {_r!r}")

check(
    "retorno é bool (não tupla truthy)",
    isinstance(eh_video(None, "musica.mp3"), bool),
    type(eh_video(None, "musica.mp3")).__name__,
)

print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas else f"FALHAS: {falhas}"))
sys.exit(1 if falhas else 0)
