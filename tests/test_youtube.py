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
from navepro.core.ambiente import _eh_windows  # noqa: E402
from navepro.core.mediaplayer import (  # noqa: E402
    _MPV_YTDL_OPCOES,
    _YTDLP_IDADE_MAX_DIAS,
    _eh_url,
    _opcoes_telao_wayland,
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
                                "_opcoes_telao_wayland": _opcoes_telao_wayland,
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
    checar("no Linux o mpv segue o monitor configurado do telão (não o 1 fixo)",
           any(c.startswith("--screen=") and c != "--screen=1" for c in cmd)
           and "--screen=3" in cmd)

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

# ── 5. Monitor do telão no Wayland (mpv ignora --screen) ──────────────
# Sessão Wayland: o mpv nativo não respeita o `--screen` (índice X11) e
# abre em tela cheia na saída do foco — o vídeo ia para o monitor do
# operador. O `--screen-name` é quem escolhe a saída lá (mpv >= 0.34).
_orig_wayland = mediaplayer_mod._eh_wayland
_orig_versao = mediaplayer_mod._versao_mpv_cacheada
try:
    mediaplayer_mod._eh_wayland = lambda: True
    mediaplayer_mod._versao_mpv_cacheada = lambda: (0, 37)
    _dec = _opcoes_telao_wayland("HDMI-2")
    checar("Wayland nativo: mpv recebe --screen-name do telão",
           _dec == ["--screen-name=HDMI-2"])
    checar("Wayland sem nome de saída: nenhuma opção extra",
           _opcoes_telao_wayland("") == [])
    mediaplayer_mod._versao_mpv_cacheada = lambda: (0, 32)
    checar("mpv anterior ao 0.34 não ganha opção desconhecida (não quebra)",
           _opcoes_telao_wayland("HDMI-2") == [])
    mediaplayer_mod._eh_wayland = lambda: False
    mediaplayer_mod._versao_mpv_cacheada = lambda: (0, 37)
    checar("sessão X11: sem --screen-name (o --screen do índice resolve)",
           _opcoes_telao_wayland("HDMI-2") == [])
finally:
    mediaplayer_mod._eh_wayland = _orig_wayland
    mediaplayer_mod._versao_mpv_cacheada = _orig_versao

print("OK" if not falhas else f"\n{falhas} falha(s)")
sys.exit(1 if falhas else 0)
