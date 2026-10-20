#!/usr/bin/env python3
"""Testes do item "YouTube" da Ordem de Serviço.

Trava o que sustenta o recurso em navepro/core/mediaplayer.py:

1. `_eh_url` distingue uma URL (http/https) de um caminho em disco.
2. `_montar_comando_url` entrega a URL ao **mpv** (que transmite pelo
   yt-dlp), não ao player configurado, e liga o IPC no Windows.
3. `_montar_comando_player` roteia qualquer URL para esse caminho dedicado.
"""

import ast
import datetime
import os
import re
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

from fixture_log import log  # noqa: E402

import navepro.core.mediaplayer as mediaplayer_mod  # noqa: E402
from navepro.core import player as player_mod  # noqa: E402
from navepro.core.ambiente import _eh_wayland, _eh_windows  # noqa: E402
from navepro.core.mediaplayer import (  # noqa: E402
    _MPV_YTDL_OPCOES,
    _YTDLP_IDADE_MAX_DIAS,
    _eh_url,
    _opcoes_telao_mpv,
)
from navepro.core.player import localizar_executavel, nome_pipe_mpv  # noqa: E402

_FONTE = open(os.path.join(RAIZ, "navepro/core/mediaplayer.py"),
              encoding="utf-8").read()


def _extrair_metodo(classe: str, metodo: str):
    """Extrai um método do mediaplayer.py via AST, sem importar o app."""
    no = ast.parse(_FONTE)
    for node in ast.walk(no):
        if isinstance(node, ast.ClassDef) and node.name == classe:
            for sub in node.body:
                if (isinstance(sub, ast.FunctionDef) and sub.name == metodo):
                    mod = ast.Module(body=[sub], type_ignores=[])
                    ast.fix_missing_locations(mod)
                    ns: dict = {"_eh_windows": _eh_windows,
                                "_eh_url": _eh_url,
                                "_opcoes_telao_mpv": _opcoes_telao_mpv,
                                "_MPV_YTDL_OPCOES": _MPV_YTDL_OPCOES,
                                "_YTDLP_IDADE_MAX_DIAS": _YTDLP_IDADE_MAX_DIAS,
                                "localizar_executavel": localizar_executavel,
                                "nome_pipe_mpv": nome_pipe_mpv,
                                "datetime": datetime, "re": re,
                                "os": os, "log": log}
                    exec(compile(mod, f"<{classe}.{metodo}>", "exec"), ns)
                    return ns[metodo]
    raise AssertionError(f"{classe}.{metodo} não encontrada")


falhas = 0


def checar(desc, cond):
    global falhas
    print(f"{'?' if cond else 'X'} {desc}")
    if not cond:
        falhas += 1


# ── 1. Detecção de URL ────────────────────────────────────────────────
checar("URL do youtu.be é reconhecida", _eh_url("https://youtu.be/abc123"))
checar("URL www.youtube.com é reconhecida",
       _eh_url("https://www.youtube.com/watch?v=abc123"))
checar("http:// também vale", _eh_url("http://exemplo.com/v.mp4"))
checar("caminho local não é URL", not _eh_url("/home/user/video.mp4"))
checar("string vazia não é URL", not _eh_url(""))
checar("espaços em volta não atrapalham", _eh_url("  https://youtu.be/x  "))

# ── 2. Comando do mpv para a URL ──────────────────────────────────────
_montar_url = _extrair_metodo("MediaPlayer", "_montar_comando_url")


class _FakeUrl:
    _player_em_uso = ""
    _contador_pipe = 0
    _pipe_mpv = ""

    @staticmethod
    def _indice_screennumber():
        # Índice do MONITOR CONFIGURADO do telão — 3 de propósito para
        # provar que o mpv recebe esse índice e não o "1" fixo.
        return 3

    @staticmethod
    def _monitor_alvo():
        # Monitor do telão configurado (nome da saída, usado no Wayland).
        return type("_M", (), {"name": "HDMI-2"})()


url = "https://youtu.be/abc123"
self_fake = _FakeUrl()
cmd = _montar_url(self_fake, url, 1920, 0, 1920, 1080)
checar("a URL é o último argumento do comando", cmd[-1] == url)
checar("o player usado passa a ser o mpv", self_fake._player_em_uso == "mpv")
checar("o comando usa o mpv", os.path.basename(cmd[0]).startswith("mpv"))
checar("força um cliente do youtube que o yt-dlp resolve",
       any(c.startswith("--ytdl-raw-options=extractor-args=youtube:")
           for c in cmd))
if _eh_windows():
    checar("no Windows liga o IPC (pausa/continuar/parar)",
           any(c.startswith("--input-ipc-server=") for c in cmd))
    checar("no Windows o pipe do mpv é criado", bool(self_fake._pipe_mpv))
else:
    checar("no Linux abre em tela cheia", "--fullscreen" in cmd)
    if _eh_wayland():
        checar("no Wayland a saída do telão vai por NOME (estável)",
               "--screen-name=HDMI-2" in cmd
               and "--fs-screen-name=HDMI-2" in cmd)
        checar("no Wayland não manda índice (ele anularia o nome no mpv)",
               not any(c.startswith(("--screen=", "--fs-screen="))
                       for c in cmd))
    else:
        checar("no X11 o mpv segue o monitor configurado (não o 1 fixo)",
               "--screen=3" in cmd and "--screen=1" not in cmd)
        checar("no X11 o FULLSCREEN explícito vai para o telão (--fs-screen)",
               "--fs-screen=3" in cmd)

# ── 3. _montar_comando_player roteia URL para o mpv ───────────────────
_montar_player = _extrair_metodo("MediaPlayer", "_montar_comando_player")
chamadas = {}


def _montar_url_espiao(self, u, mx, my, mw, mh):
    chamadas["url"] = u
    return ["mpv", u]


fake_player = type("F", (), {
    "player_cmd": "vlc",  # configurado como VLC: a URL NÃO pode ir pro VLC
    "_montar_comando_url": _montar_url_espiao,
})()
cmd = _montar_player(fake_player, url, 1920, 0, 1920, 1080)
checar("_montar_comando_player roteia a URL para o caminho do mpv",
       chamadas.get("url") == url and cmd[-1] == url)

# ── 4. Aviso de yt-dlp desatualizado ──────────────────────────────────
# Extrai o método e liga num "self" falso que devolve a versão desejada,
# para testar a regra de idade sem depender do yt-dlp instalado.
_aviso_ytdlp = _extrair_metodo("MediaPlayer", "_aviso_ytdlp_desatualizado")


def _fake_versao(versao):
    return type("F", (), {"_versao_ytdlp": lambda self: versao})()


_hoje = datetime.date.today()
_velho = (_hoje - datetime.timedelta(days=_YTDLP_IDADE_MAX_DIAS + 60))
_recente = (_hoje - datetime.timedelta(days=5)).strftime("%Y.%m.%d")

aviso = _aviso_ytdlp(_fake_versao(_velho.strftime("%Y.%m.%d")))
checar("yt-dlp velho gera aviso de atualização", bool(aviso))
checar("o aviso mostra a versão instalada",
       _velho.strftime("%Y.%m.%d") in aviso)
checar("o aviso ensina como atualizar (sem o app atualizar sozinho)",
       "pipx upgrade yt-dlp" in aviso)
checar("yt-dlp recente não gera aviso",
       _aviso_ytdlp(_fake_versao(_recente)) == "")
checar("sem yt-dlp não gera aviso (quem trata é _checar_requisitos_url)",
       _aviso_ytdlp(_fake_versao("")) == "")
checar("versão fora do padrão de data não gera aviso",
       _aviso_ytdlp(_fake_versao("nightly")) == "")

# ── 5. Monitor do telão (janela E tela cheia) ────────────────────────
# Bug relatado: ao executar o 2º vídeo do YouTube com o 1º ainda tocando,
# o novo mpv abria no monitor do operador. Causa: o telão só recebia
# `--screen` (posição inicial da janela); a TELA CHEIA usa `--fs-screen`,
# cujo padrão é `current` — o monitor do foco. Agora o fullscreen é
# explícito: índice no X11 e nome da saída no Wayland (onde o índice muda
# de ordem). No Wayland os nomes só valem sozinhos: o mpv ignora
# `--screen-name`/`--fs-screen-name` se o índice correspondente existir.
_orig_wayland = mediaplayer_mod._eh_wayland
_orig_versao = mediaplayer_mod._versao_mpv_cacheada
try:
    mediaplayer_mod._eh_wayland = lambda: True
    mediaplayer_mod._versao_mpv_cacheada = lambda: (0, 37)
    _dec = _opcoes_telao_mpv("HDMI-2", 3)
    checar("Wayland: mpv vira X11 e escolhe janela + tela cheia pelo nome",
           _dec == ["--vo=x11", "--screen-name=HDMI-2",
                    "--fs-screen-name=HDMI-2"])
    checar("Wayland: manda só nomes (índice anularia o nome no mpv)",
           not any(o.startswith(("--screen=", "--fs-screen="))
                   for o in _dec))
    mediaplayer_mod._versao_mpv_cacheada = lambda: (0, 32)
    checar("mpv anterior ao 0.34: cai no índice (não usa opção inexistente)",
           _opcoes_telao_mpv("HDMI-2", 3) == [
               "--vo=x11", "--screen=3", "--fs-screen=3"])
    mediaplayer_mod._versao_mpv_cacheada = lambda: (0, 37)
    checar("Wayland sem nome de saída: cai no índice",
           _opcoes_telao_mpv("", 3) == [
               "--vo=x11", "--screen=3", "--fs-screen=3"])
    mediaplayer_mod._eh_wayland = lambda: False
    checar("X11: janela e tela cheia pelo índice do telão (sem VO x11)",
           _opcoes_telao_mpv("HDMI-2", 3) == ["--screen=3", "--fs-screen=3"])
finally:
    mediaplayer_mod._eh_wayland = _orig_wayland
    mediaplayer_mod._versao_mpv_cacheada = _orig_versao

# ── 6. yt-dlp do host acessível no Flatpak ────────────────────────────
# O Flatpak não herda o PATH do host nem o /usr/local/bin dele (o sandbox
# mostra o /usr/local da runtime). O yt-dlp instalado pelo binário oficial
# (ex.: wget -O /usr/local/bin/yt-dlp) só é visto via /run/host/usr/local/bin.
checar("Flatpak enxerga o /usr/local/bin do host (yt-dlp oficial)",
       "/run/host/usr/local/bin" in player_mod._CAMINHOS_LINUX)
checar("sandbox também cobre /run/host/usr/bin (mpv do apt)",
       "/run/host/usr/bin" in player_mod._CAMINHOS_LINUX)

# ── 7. Título do item YouTube não é trocado pela URL ──────────────────
# No editor "Ad. Item", o título de cada tipo é resolvido a partir de uma
# busca. Para o YouTube não há busca (a caixa "Buscar" fica vazia), então o
# título digitado pelo operador precisa ser preservado — a URL é só a mídia,
# quem executa o vídeo. Antes, com a busca vazia, `_usou_titulo_como_busca`
# virava True e o título era sobreescrito pela URL.
_fonte_app = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
_bloco_youtube = _fonte_app.split('elif tipo == "youtube":', 1)[1]
_bloco_youtube = _bloco_youtube.split("elif ", 1)[0]
checar("título do YouTube só cai para a URL quando está vazio",
       "if not titulo:" in _bloco_youtube)
checar("título do YouTube não usa mais a regra de busca (_usou_titulo_como_busca)",
       "_usou_titulo_como_busca" not in _bloco_youtube)
checar("a URL continua sendo a mídia do item (youtube_url lido na execução)",
       "item.get('youtube_url')" in _fonte_app)

# ── 8. Item YouTube no controle remoto (_remoto_resolver_item) ────────
# O editor do celular marca a caixinha "Vídeo do YouTube" sob o tipo Vídeo e
# envia tipo='youtube' + youtube_url. A resolução sem Tk precisa aceitar esse
# tipo, validar a URL e não guardar caminho em disco — espelhando o desktop.


def _extrair_metodo_app(classe, metodo, ns):
    _no = ast.parse(_fonte_app)
    for _n in ast.walk(_no):
        if isinstance(_n, ast.ClassDef) and _n.name == classe:
            for _sub in _n.body:
                if isinstance(_sub, ast.FunctionDef) and _sub.name == metodo:
                    _mod = ast.Module(body=[_sub], type_ignores=[])
                    ast.fix_missing_locations(_mod)
                    exec(compile(_mod, f"<{classe}.{metodo}>", "exec"), ns)
                    return ns[metodo]
    raise AssertionError(f"{classe}.{metodo} não encontrada")


_resolver = _extrair_metodo_app("AppInterface", "_remoto_resolver_item",
                                {"os": os, "_eh_url": _eh_url})

_ok, _err, _campos = _resolver(None, {
    "tipo": "youtube", "youtube_url": "https://youtu.be/abc123"})
checar("remoto: item YouTube é aceito", _ok and not _err)
checar("remoto: tipo do item vira 'youtube'", _campos.get("tipo") == "youtube")
checar("remoto: a URL é guardada em youtube_url",
       _campos.get("youtube_url") == "https://youtu.be/abc123")
checar("remoto: item YouTube não guarda caminho de arquivo",
       _campos.get("caminho_arquivo") == "")
checar("remoto: sem título, a URL vira o rótulo",
       _campos.get("titulo_custom") == "https://youtu.be/abc123")

_ok, _err, _campos = _resolver(None, {
    "tipo": "youtube", "youtube_url": "https://youtu.be/abc123",
    "titulo": "Culto ao vivo"})
checar("remoto: título digitado é preservado no YouTube",
       _campos.get("titulo_custom") == "Culto ao vivo")

_ok, _err, _campos = _resolver(None, {"tipo": "youtube", "youtube_url": ""})
checar("remoto: YouTube sem URL é recusado", not _ok and "URL" in _err)

_ok, _err, _campos = _resolver(None, {"tipo": "slide"})
checar("remoto: item comum também ganha a chave youtube_url (vazia)",
       _ok and _campos.get("youtube_url") == "")

print("OK" if not falhas else f"\n{falhas} falha(s)")
sys.exit(1 if falhas else 0)
