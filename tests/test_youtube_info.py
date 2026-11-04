#!/usr/bin/env python3
"""Testes da validação de URL e dos metadados do YouTube."""

import os
import sys
from types import SimpleNamespace

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

import navepro.core.youtube as yt  # noqa: E402
from navepro.core.youtube import _eh_url_youtube, _obter_info_youtube  # noqa: E402


def _rodar() -> int:
    falhas = 0

    def checar(desc, cond, extra=""):
        nonlocal falhas
        print(f"{'OK ' if cond else 'X  '} {desc}{cinza(extra)}")
        if not cond:
            falhas += 1

    def cinza(txt):
        return f" ({txt})" if txt else ""

    # ── Validação de domínio ──────────────────────────────────────
    for url in (
        "https://youtu.be/abc123",
        "http://youtu.be/abc123",
        "https://www.youtube.com/watch?v=abc123",
        "https://m.youtube.com/watch?v=abc123",
        "https://music.youtube.com/watch?v=abc123",
        "https://youtube-nocookie.com/embed/abc123",
    ):
        checar(f"aceita {url}", _eh_url_youtube(url))
    for url in (
        "",
        "youtu.be/abc123",
        "ftp://youtu.be/abc123",
        "https://exemplo.com/watch?v=abc123",
        "https://youtube.com.evil.com/watch?v=abc123",
        "https://notyoutube.com/watch?v=abc123",
    ):
        checar(f"recusa {url!r}", not _eh_url_youtube(url))

    # ── Metadados via yt-dlp (subprocess simulado) ────────────────
    original_localizar = yt.localizar_executavel
    original_run = yt.subprocess.run

    def _run_ok(*_args, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout='{"title": "Culto ao vivo", "duration": 123.4}',
            stderr="")

    yt.localizar_executavel = lambda _nome: "/fake/yt-dlp"
    yt.subprocess.run = _run_ok
    info = _obter_info_youtube("https://youtu.be/abc123")
    checar("título capturado do yt-dlp",
           info and info["titulo"] == "Culto ao vivo")
    checar("duração capturada do yt-dlp",
           info and info["duracao"] == 123.4)

    chamou = {"n": 0}

    def _run_nao_deveria(*_args, **_kwargs):
        chamou["n"] += 1
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    yt.subprocess.run = _run_nao_deveria
    checar("URL fora do YouTube nem chama o yt-dlp",
           _obter_info_youtube("https://exemplo.com/v") is None
           and chamou["n"] == 0)

    yt.subprocess.run = lambda *a, **k: SimpleNamespace(
        returncode=0, stdout='{"duration": 10}', stderr="")
    checar("vídeo sem título é recusado", _obter_info_youtube(
        "https://youtu.be/abc123") is None)

    yt.subprocess.run = lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="", stderr="erro")
    checar("falha do yt-dlp vira None", _obter_info_youtube(
        "https://youtu.be/abc123") is None)

    yt.localizar_executavel = lambda _nome: None
    checar("yt-dlp ausente vira None", _obter_info_youtube(
        "https://youtu.be/abc123") is None)

    yt.localizar_executavel = original_localizar
    yt.subprocess.run = original_run

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
