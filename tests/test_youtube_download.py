#!/usr/bin/env python3
"""Testes do download temporário de vídeos do YouTube."""

import os
import shutil
import sys
import tempfile
import types

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import navepro.core.youtube as yt  # noqa: E402

falhas = 0


def checar(desc, cond, extra=""):
    global falhas
    print(f"{'OK ' if cond else 'X  '} {desc}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas += 1


URL = "https://youtu.be/abc123"


def _fake_localizar(nome):
    return {"yt-dlp": "/fake/yt-dlp", "ffmpeg": "/fake/ffmpeg"}.get(nome)


def _rodar() -> int:
    original = {
        "localizar_executavel": yt.localizar_executavel,
        "subprocess_run": yt.subprocess.run,
        "pasta": yt._pasta_videos_youtube,
        "eh_flatpak": yt._eh_flatpak,
        "baixar": yt.baixar_video_youtube,
    }
    pasta = tempfile.mkdtemp(prefix="navepro-yt-teste-")
    try:
        yt.localizar_executavel = _fake_localizar
        yt._VIDEOS_BAIXADOS.clear()

        # ── Onde os vídeos ficam ─────────────────────────────────────
        yt._eh_flatpak = lambda: False
        checar("fora do Flatpak usa a pasta temporária do sistema",
               yt._pasta_videos_youtube() == os.path.join(
                   tempfile.gettempdir(), "navepro_youtube"))
        yt._eh_flatpak = lambda: True
        checar("no Flatpak usa uma pasta do home compartilhada com o host",
               yt._pasta_videos_youtube() == os.path.join(
                   yt.DATA_USER_DIR, "tmp_youtube"))
        yt._eh_flatpak = lambda: False
        yt._pasta_videos_youtube = lambda: pasta

        # ── Comando de download ──────────────────────────────────────
        cmd = yt._comando_baixar_youtube(
            "/fake/yt-dlp", URL,
            os.path.join(pasta, "sub"), "video_teste")
        checar("não usa playlist", "--no-playlist" in cmd)
        checar("baixa para o caminho temporário",
               os.path.join(pasta, "sub", "video_teste.%(ext)s") in cmd)
        checar("junta vídeo+áudio em mp4 quando há ffmpeg",
               "--merge-output-format" in cmd and "mp4" in cmd)
        checar("a URL é o último argumento", cmd[-1] == URL)

        yt._eh_flatpak = lambda: True
        cmd_flatpak = yt._comando_baixar_youtube(
            "/run/host/usr/local/bin/yt-dlp", URL, pasta, "video_teste")
        checar("no Flatpak executa o yt-dlp do host",
               cmd_flatpak[:3] == [
                   "flatpak-spawn", "--host", "/usr/local/bin/yt-dlp"],
               str(cmd_flatpak[:3]))
        yt._eh_flatpak = lambda: False

        # ── Download com sucesso ─────────────────────────────────────
        def run_ok(comando, **kwargs):
            template = comando[comando.index("-o") + 1]
            caminho = template.replace("%(ext)s", "mp4")
            with open(caminho, "wb") as fh:
                fh.write(b"video")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        yt.subprocess.run = run_ok
        caminho = yt.baixar_video_youtube(URL)
        checar("download devolve o arquivo criado",
               os.path.isfile(caminho) and caminho.endswith(".mp4"), caminho)
        checar("o arquivo fica dentro da pasta temporária",
               os.path.dirname(caminho) == pasta)

        # ── O mesmo vídeo é reaproveitado na sessão ──────────────────
        chamadas = []

        def baixar_espiao(url):
            chamadas.append(url)
            return caminho

        yt.baixar_video_youtube = baixar_espiao
        checar("primeira chamada baixa o vídeo",
               yt.obter_video_youtube(URL) == caminho and len(chamadas) == 1)
        checar("segunda chamada reaproveita o arquivo local",
               yt.obter_video_youtube(URL) == caminho and len(chamadas) == 1)

        # ── Falha do yt-dlp ──────────────────────────────────────────
        yt.baixar_video_youtube = original["baixar"]

        def run_falha(comando, **kwargs):
            return types.SimpleNamespace(
                returncode=1, stdout="",
                stderr="ERROR: Video unavailable")

        yt.subprocess.run = run_falha
        try:
            yt.baixar_video_youtube(URL)
        except RuntimeError as exc:
            checar("falha do yt-dlp vira RuntimeError com o motivo",
                   "Video unavailable" in str(exc), str(exc))
        else:
            checar("falha do yt-dlp vira RuntimeError com o motivo", False)

        # ── URL inválida ─────────────────────────────────────────────
        try:
            yt.baixar_video_youtube("https://exemplo.com/video")
        except ValueError:
            checar("URL fora do YouTube é recusada", True)
        else:
            checar("URL fora do YouTube é recusada", False)

        # ── Limpeza ao fechar o app ──────────────────────────────────
        yt.baixar_video_youtube = baixar_espiao
        yt.obter_video_youtube(URL)
        yt.limpar_videos_youtube()
        checar("limpar apaga a pasta e o cache da sessão",
               not os.path.exists(pasta) and not yt._VIDEOS_BAIXADOS)
    finally:
        yt.localizar_executavel = original["localizar_executavel"]
        yt.subprocess.run = original["subprocess_run"]
        yt._pasta_videos_youtube = original["pasta"]
        yt._eh_flatpak = original["eh_flatpak"]
        yt.baixar_video_youtube = original["baixar"]
        yt._VIDEOS_BAIXADOS.clear()
        shutil.rmtree(pasta, ignore_errors=True)

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
