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
        "subprocess_popen": yt.subprocess.Popen,
        "pasta": yt._pasta_videos_youtube,
        "eh_flatpak": yt._eh_flatpak,
        "baixar": yt.baixar_video_youtube,
        "baixar_deno": yt._baixar_deno,
    }
    pasta = tempfile.mkdtemp(prefix="navepro-yt-teste-")
    try:
        def _sem_rede(*_args, **_kwargs):
            raise RuntimeError("sem rede (teste)")

        # Nunca baixa o Deno de verdade durante a suíte.
        yt._baixar_deno = _sem_rede
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

        def baixar_espiao(url, ao_progresso=None):
            chamadas.append(url)
            return caminho

        yt.baixar_video_youtube = baixar_espiao
        checar("primeira chamada baixa o vídeo",
               yt.obter_video_youtube(URL) == caminho and len(chamadas) == 1)
        checar("segunda chamada reaproveita o arquivo local",
               yt.obter_video_youtube(URL) == caminho and len(chamadas) == 1)
        checar("vídeo da sessão é reconhecido sem baixar",
               yt.video_youtube_baixado(URL) == caminho)
        checar("vídeo desconhecido não é considerado baixado",
               yt.video_youtube_baixado("https://youtu.be/outro") is None)

        yt.baixar_video_youtube = original["baixar"]

        # ── yt-dlp novo: runtime JS + yt-dlp-ejs ─────────────────────        # Ubuntu 26.04 traz yt-dlp 2026.03.17, que exige runtime JS externo
        # para o YouTube; o do 24.04 (2024.04.09) não conhece essas opções.
        def _localizar_js(nome):
            return {"yt-dlp": "/fake/yt-dlp",
                    "deno": "/usr/bin/deno"}.get(nome)

        yt.localizar_executavel = _localizar_js
        yt._AJUDA_YTDLP.clear()
        yt._CACHE_OPCOES_JS.clear()
        yt.subprocess.run = lambda comando, **kw: types.SimpleNamespace(
            returncode=0,
            stdout="--js-runtimes RUNTIME --remote-components COMPONENT",
            stderr="")
        opcoes = yt._opcoes_js_youtube("/fake/yt-dlp")
        checar("yt-dlp novo recebe o runtime JS e os scripts do yt-dlp-ejs",
               opcoes == ["--js-runtimes", "deno:/usr/bin/deno",
                          "--remote-components", "ejs:github"], str(opcoes))
        cmd_js = yt._comando_baixar_youtube("/fake/yt-dlp", URL, pasta, "v")
        checar("o download leva as opções de JS/EJS",
               "--js-runtimes" in cmd_js and "ejs:github" in cmd_js)

        yt.localizar_executavel = _fake_localizar
        yt._AJUDA_YTDLP.clear()
        yt._CACHE_OPCOES_JS.clear()
        yt.subprocess.run = lambda comando, **kw: types.SimpleNamespace(
            returncode=0, stdout="uso: yt-dlp [OPÇÕES] URL", stderr="")
        checar("yt-dlp antigo não recebe opções que não conhece",
               yt._opcoes_js_youtube("/fake/yt-dlp") == []
               and "--js-runtimes" not in yt._comando_baixar_youtube(
                   "/fake/yt-dlp", URL, pasta, "v"))

        # ── 403: tenta clientes alternativos antes de desistir ───────
        yt._AJUDA_YTDLP.clear()
        yt._CACHE_OPCOES_JS.clear()
        tentativas = []

        def run_403_depois_ok(comando, **kwargs):
            if "--help" in comando:
                return types.SimpleNamespace(
                    returncode=0, stdout="", stderr="")
            tentativas.append(comando)
            if len(tentativas) == 1:
                return types.SimpleNamespace(
                    returncode=1, stdout="",
                    stderr="ERROR: unable to download video data: "
                           "HTTP Error 403: Forbidden")
            template = comando[comando.index("-o") + 1]
            caminho_ok = template.replace("%(ext)s", "mp4")
            with open(caminho_ok, "wb") as fh:
                fh.write(b"video")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        yt.subprocess.run = run_403_depois_ok
        caminho_retry = yt.baixar_video_youtube(URL)
        checar("403 no cliente padrão é repetido com outro cliente",
               len(tentativas) == 2 and os.path.isfile(caminho_retry),
               str(len(tentativas)))
        checar("a nova tentativa escolhe outro cliente do YouTube",
               any("--extractor-args" in c and
                   any(a.startswith("youtube:player_client=") for a in c)
                   for c in tentativas[1:]))

        # ── 403 sem runtime JS: mensagem ensina a instalar ───────────
        yt._AJUDA_YTDLP.clear()
        yt._CACHE_OPCOES_JS.clear()
        yt.subprocess.run = lambda comando, **kw: (
            types.SimpleNamespace(
                returncode=0, stdout="--js-runtimes RUNTIME", stderr="")
            if "--help" in comando else
            types.SimpleNamespace(
                returncode=1, stdout="",
                stderr="ERROR: HTTP Error 403: Forbidden"))
        try:
            yt.baixar_video_youtube(URL)
        except RuntimeError as exc:
            checar("403 sem runtime JS ensina a instalar Node/Deno",
                   "runtime JavaScript" in str(exc) and "nodejs" in str(exc))
        else:
            checar("403 sem runtime JS ensina a instalar Node/Deno", False)

        # ── Deno: asset por plataforma ───────────────────────────────
        checar("Deno: asset Linux x86_64",
               yt._asset_deno("linux", "x86_64")
               == "deno-x86_64-unknown-linux-gnu.zip")
        checar("Deno: asset Linux arm64",
               yt._asset_deno("linux", "aarch64")
               == "deno-aarch64-unknown-linux-gnu.zip")
        checar("Deno: asset Windows x64",
               yt._asset_deno("win32", "AMD64")
               == "deno-x86_64-pc-windows-msvc.zip")
        checar("Deno: plataforma desconhecida não inventa asset",
               yt._asset_deno("freebsd", "x86_64") is None)

        # ── Comando de download: velocidade + progresso ─────────────
        yt._AJUDA_YTDLP.clear()
        yt._CACHE_OPCOES_JS.clear()
        yt.localizar_executavel = _localizar_js
        yt.subprocess.run = lambda comando, **kw: types.SimpleNamespace(
            returncode=0,
            stdout=("--js-runtimes RUNTIME --remote-components COMP "
                    "--concurrent-fragments N"),
            stderr="")
        cmd_prog = yt._comando_baixar_youtube(
            "/fake/yt-dlp", URL, pasta, "v", com_progresso=True)
        checar("download usa fragmentos em paralelo",
               "--concurrent-fragments" in cmd_prog)
        checar("download emite progresso (sem --no-progress)",
               "--progress-template" in cmd_prog
               and "--no-quiet" in cmd_prog
               and "--no-progress" not in cmd_prog)
        checar("download limita a 1080p (mais rápido que 4K)",
               any("height<=1080" in arg for arg in cmd_prog))
        checar("sem progresso mantém o --no-progress antigo",
               "--no-progress" in yt._comando_baixar_youtube(
                   "/fake/yt-dlp", URL, pasta, "v"))

        # ── Leitura do progresso: vídeo + áudio somam 100% ──────────
        class _SaidaFalsa:
            def __init__(self, linhas):
                self._iter = iter(linhas)

            def __iter__(self):
                return self._iter

            def close(self):
                pass

        class _ProcessoFalso:
            def __init__(self, linhas):
                self.stdout = _SaidaFalsa(linhas)

            def wait(self, timeout=None):
                return 0

            def kill(self):
                pass

        linhas = [
            "NPINFO 300\n",
            "NAVEPRO NA|100|200|10|1000\n",
            "NAVEPRO NA|200|200|0|1000\n",
            "[download] Destination: /tmp/video.mp4\n",
            "NAVEPRO NA|50|100|5|1000\n",
            "NAVEPRO NA|100|100|0|1000\n",
            '[Merger] Merging formats into "/tmp/video.mp4"\n',
        ]
        vistos = []
        yt.subprocess.Popen = lambda *a, **k: _ProcessoFalso(linhas)
        saida_prog = yt._executar_ytdlp_stream(
            ["yt-dlp"], 10, lambda pct, txt: vistos.append((pct, txt)))
        percentuais = [pct for pct, _ in vistos]
        checar("progresso considera vídeo+áudio (termina em 100%)",
               percentuais and percentuais[-1] == 100.0,
               str(percentuais))
        checar("progresso nunca anda para trás",
               all(b >= a for a, b in zip(percentuais, percentuais[1:],
                                          strict=False)))
        checar("ao juntar os formatos avisa que está finalizando",
               any("Finalizando" in txt for _, txt in vistos))
        checar("o log do processo não guarda as linhas de progresso",
               "NAVEPRO" not in saida_prog.stdout
               and "Destination" not in saida_prog.stdout)
        yt.subprocess.Popen = original["subprocess_popen"]

        yt.subprocess.run = original["subprocess_run"]

        # ── Falha do yt-dlp ──────────────────────────────────────────
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
        yt.subprocess.Popen = original["subprocess_popen"]
        yt._pasta_videos_youtube = original["pasta"]
        yt._eh_flatpak = original["eh_flatpak"]
        yt.baixar_video_youtube = original["baixar"]
        yt._baixar_deno = original["baixar_deno"]
        yt._VIDEOS_BAIXADOS.clear()
        yt._AJUDA_YTDLP.clear()
        yt._CACHE_OPCOES_JS.clear()
        shutil.rmtree(pasta, ignore_errors=True)

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
