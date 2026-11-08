#!/usr/bin/env python3
"""Testes da validação de URL e dos metadados do YouTube."""

import os
import sys
from types import SimpleNamespace

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

import navepro.core.youtube as yt  # noqa: E402
from navepro.core.youtube import (  # noqa: E402
    _eh_url_youtube,
    _normalizar_url_youtube,
    _obter_info_youtube,
    _obter_info_youtube_oembed,
)


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
    checar("normaliza link colado sem https",
           _normalizar_url_youtube("youtu.be/abc123")
           == "https://youtu.be/abc123")
    checar("normaliza link protocol-relative",
           _normalizar_url_youtube("//youtu.be/abc123")
           == "https://youtu.be/abc123")
    checar("mantém URL que já tem esquema",
           _normalizar_url_youtube("http://youtu.be/abc123")
           == "http://youtu.be/abc123")

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
    original_flatpak = yt._eh_flatpak

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

    # ── Reserva sem yt-dlp: oEmbed público ────────────────────────
    original_baixar = yt._baixar

    class _Resposta:
        def __init__(self, corpo):
            self.corpo = corpo

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.corpo

    chamadas = {"n": 0}

    def _baixar_ok(*_args, **_kwargs):
        chamadas["n"] += 1
        return _Resposta(b'{"title": "Culto ao vivo"}')

    yt._baixar = _baixar_ok
    info = _obter_info_youtube_oembed("https://youtu.be/abc123")
    checar("oEmbed devolve o título quando o yt-dlp falha",
           info and info["titulo"] == "Culto ao vivo")
    checar("oEmbed não inventa duração", info and info["duracao"] == 0.0)

    chamadas["n"] = 0
    checar("oEmbed recusa URL que não é do YouTube",
           _obter_info_youtube_oembed("https://exemplo.com/v") is None
           and chamadas["n"] == 0)
    checar("oEmbed aceita link colado sem https",
           _obter_info_youtube_oembed("youtu.be/abc123") is not None)

    yt._baixar = original_baixar

    # ── Flatpak: o yt-dlp do host roda via flatpak-spawn ──────────
    # Dentro do sandbox o Python do runtime não enxerga o yt_dlp instalado
    # no host (apt ou pipx de outra versão). Rodar no host resolve.
    capturado = {}

    def _run_host(*args, **kwargs):
        capturado["cmd"] = args[0]
        capturado["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0, stdout='{"title": "Culto", "duration": 10}',
            stderr="")

    yt._eh_flatpak = lambda: True
    yt.localizar_executavel = lambda _nome: "/run/host/usr/bin/yt-dlp"
    yt.subprocess.run = _run_host
    info = _obter_info_youtube("https://youtu.be/abc123")
    checar("no Flatpak o yt-dlp roda no host via flatpak-spawn",
           capturado["cmd"][:3] == [
               "flatpak-spawn", "--host", "/usr/bin/yt-dlp"])
    checar("no Flatpak o /run/host é traduzido para o caminho do host",
           info and info["titulo"] == "Culto")
    checar("consulta ao yt-dlp usa CREATE_NO_WINDOW (sem console no Windows)",
           "creationflags" in capturado["kwargs"])

    yt.localizar_executavel = lambda _nome: os.path.expanduser(
        "~/.local/bin/yt-dlp")
    _obter_info_youtube("https://youtu.be/abc123")
    checar("no Flatpak o caminho do pipx é mantido (mesmo no host)",
           capturado["cmd"][2] == os.path.expanduser("~/.local/bin/yt-dlp"))

    yt._eh_flatpak = original_flatpak
    yt.localizar_executavel = original_localizar
    yt.subprocess.run = original_run

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
