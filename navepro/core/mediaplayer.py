"""MediaPlayer - reprodução de mídia no telão.

Extraído de NavePro.py sem alterar o comportamento (ver AGENTS.md).
"""
from __future__ import annotations

import datetime
import os
import re
import signal
import subprocess
import threading
import time
import tkinter as tk
from collections.abc import Callable

from navepro.config import EXTENSOES_VIDEO, PLAYER_PADRAO
from navepro.core import telao as telao_mod
from navepro.core.ambiente import (
    _ambiente_sem_appimage,
    _eh_flatpak,
    _eh_linux,
    _eh_wayland,
    _eh_windows,
)
from navepro.core.log import get_logger
from navepro.core.monitores import MonitorInfo, get_monitors_config
from navepro.core.player import (
    MPRIS_DESTS,
    ClienteMpvIpc,
    destino_mpris,
    encerrar_arvore,
    esconder_janelas_auxiliares,
    localizar_executavel,
    mpris_ativo,
    mpris_status,
    nome_pipe_mpv,
    posicionar_janela_player,
)

log = get_logger("mediaplayer")


def _eh_url(arquivo: str) -> bool:
    """True se `arquivo` for uma URL http(s) em vez de um caminho em disco.

    Usado pelo item "YouTube" da Ordem de Serviço: a URL é entregue ao mpv,
    que transmite pelo yt-dlp em vez de abrir um arquivo local.
    """
    return (arquivo or "").strip().lower().startswith(("http://", "https://"))


# Opções que o mpv repassa ao yt-dlp para URLs do YouTube.
#
# Medido aqui (yt-dlp 2025.09.26): o cliente padrão ("web") devolve
# "The page needs to be reloaded" e o mpv encerra na hora — sem janela, sem
# aviso (o `--really-quiet` engole o erro). Forçando o cliente "android" o
# yt-dlp resolve e o vídeo toca. Sem isto, o item YouTube fica mudo no telão.
_MPV_YTDL_OPCOES = [
    "--ytdl-raw-options=extractor-args=youtube:player_client=android",
]

# Idade (em dias) a partir da qual o yt-dlp instalado é considerado velho. O
# yt-dlp acompanha as mudanças do YouTube e costuma ser atualizado com
# frequência; passando disso, é bem provável que a URL pare de resolver. O
# app NÃO atualiza o yt-dlp sozinho (é pacote do sistema: apt/pipx/binário) —
# só avisa o operador (ver _aviso_ytdlp_desatualizado).
_YTDLP_IDADE_MAX_DIAS = 120

# Versão do mpv instalado, cacheada (None = não descobriu). Usada para saber
# se o mpv conhece o `--screen-name` (Wayland) sem um subprocess por vídeo.
_MPV_VERSAO_CACHE: tuple[int, int] | None = None


def _versao_mpv_cacheada() -> tuple[int, int] | None:
    """Versão (maior, menor) do mpv instalado, ou None se não der para saber."""
    global _MPV_VERSAO_CACHE
    if _MPV_VERSAO_CACHE is not None:
        return _MPV_VERSAO_CACHE
    try:
        exe = localizar_executavel("mpv") or "mpv"
        resp = subprocess.run(
            [exe, '--version'], timeout=5, capture_output=True, text=True,
            env=_ambiente_sem_appimage())
        m = re.search(r'mpv\s+v?(\d+)\.(\d+)', resp.stdout or '')
        if m:
            _MPV_VERSAO_CACHE = (int(m.group(1)), int(m.group(2)))
    except Exception:
        _MPV_VERSAO_CACHE = None
    return _MPV_VERSAO_CACHE


def _opcoes_telao_wayland(nome_monitor: str) -> list[str]:
    """Opções do mpv para o telão quando a sessão é Wayland nativa.

    Numa sessão Wayland o mpv IGNORA o `--screen` (índice X11) e abre em
    tela cheia na saída do foco — o que mandava vídeo/YouTube para o monitor
    do operador. O que escolhe a saída lá é o `--screen-name=<nome>` (mpv >=
    0.34). Devolve [] quando não dá para usar: sessão X11, sem nome de saída,
    ou mpv antigo demais (que morreria com "option not found").
    """
    if not _eh_wayland():
        return []
    nome = (nome_monitor or "").strip()
    if not nome:
        return []
    versao = _versao_mpv_cacheada()
    if versao is None or versao < (0, 34):
        return []
    return [f"--screen-name={nome}"]


class MediaPlayer:
    """Gerencia a reprodução de mídia no telão.

    Otimizações:
    - Cache de duração de arquivos (evita ffprobe repetido)
    - Sem sleep() no _tocar_arquivo (usa wait pid + timeout)
    - Sem pkill() (mata apenas o processo conhecido, sem força bruta)
    - Sincronização via D-Bus unificada
    - Monitoramento via after() sem polling agressivo
    - Transições mais rápidas entre faixas
    """

    # Cache global de duração para evitar ffprobe repetido (LRU limitado)
    _duracao_cache: dict[str, float] = {}
    _duracao_cache_lock = threading.Lock()
    _DURACAO_CACHE_MAX: int = 256
    # Mapeamento player -> D-Bus (fonte única em navepro/core/player.py)
    _MPRIS_DESTS: dict[str, str] = dict(MPRIS_DESTS)

    def __init__(self, monitor_index: int = 1, player_cmd: str = PLAYER_PADRAO,
                 telao: TelaoWindow | None = None) -> None:  # noqa: F821
        self.playlist: list[str] = []
        self.index: int = 0
        self.is_playing: bool = False
        self.is_paused: bool = False
        self._process: subprocess.Popen | None = None
        self._process_lock: threading.Lock = threading.Lock()
        self.monitor_index: int = monitor_index
        self.player_cmd: str = player_cmd
        self.tempo_inicio: float | None = None
        self.tempo_acumulado: float = 0.0
        self.duracao_total: float | None = None
        self._player_pid: int | None = None
        # Player realmente usado na última reprodução. Pode diferir de
        # player_cmd quando o configurado não existe e caiu no fallback.
        self._player_em_uso: str = player_cmd
        # Flag para evitar que _monitorar dispare "ended" quando matamos
        # o processo intencionalmente (via stop, próximo, anterior, tocar_indice)
        self._killed_intentionally: bool = False
        # ── Controle remoto do player (só Windows) ───────────────────
        # No Linux o controle vem por D-Bus/MPRIS (ver _pausar_player). No
        # Windows o mpv expõe o IPC JSON dele, que é o equivalente. Guardamos
        # o pipe/ipc por reprodução: o nome muda a cada faixa para não
        # reaproveitar a conversa de um mpv anterior.
        self._ipc: ClienteMpvIpc | None = None
        self._pipe_mpv: str = ""
        self._contador_pipe: int = 0
        # True quando o lançamento foi via "aplicativo padrão" (cmd /c start):
        # nesse caso o cmd.exe morre na hora e não sobra handle para o player,
        # então o fim não pode ser detectado pelo poll() do processo.
        self._lancamento_desanexado: bool = False

        # Dependency Injection: 'TelaoWindow'  # noqa: F821
        # para testes ou uso compartilhado. Fallback: cria internamente.
        self.telao = telao if telao is not None else None  # noqa: F821
        self.on_state_change: Callable[[str], None] | None = None
        self.on_track_change: Callable[[int, str], None] | None = None
        # Aviso não-bloqueante para o painel (AppInterface escreve no
        # status_label). O NavePro.exe é gerado sem console, então um `print`
        # de aviso não chegaria a quem opera o NavePro — precisa ser visual.
        self.on_aviso: Callable[[str], None] | None = None
        # Só avisa uma vez por sessão sobre falta de controle remoto, para
        # não repetir o mesmo aviso a cada clique em pausar.
        self._ja_avisou_sem_controle: bool = False
        # Versão do yt-dlp (cacheada) e trava para avisar só uma vez por
        # sessão que ela está velha. None = ainda não checada.
        self._ytdlp_versao: str | None = None
        self._ja_avisou_ytdlp: bool = False
        # Referência para o root da janela principal (setado externamente)
        self._root_after: tk.Misc | None = None
        # Garante existência do telão antes de monitorar
        self._garantir_telao()
        # Inicia monitoramento assíncrono
        self._monitorar()
        # Garante que o telão fique com alpha e lower desde o início
        t = self._garantir_telao()
        try:
            t.root.lower()
        except Exception:
            pass

    @property
    def process(self) -> subprocess.Popen | None:
        """Retorna o processo do player (somente leitura)."""
        return self._process

    def _garantir_telao(self):  # noqa: F821
        """Garante que o telão existe; recria se tiver sido fechado.

        O telão é um tk.Tk() separado e pode ser destruído em execução
        normal (Esc fora de projeção, Ctrl+Q ou X na janela TELÃO). Sem
        recuperação, a próxima reprodução estourava com "can't invoke wm
        command: application has been destroyed".
        """
        telao = getattr(self, "telao", None)
        if telao is not None and getattr(telao, "_raiz_viva", lambda: False)():
            return telao
        log.info("🖥️ Telão fechado — recriando automaticamente...")
        try:
            novo = telao_mod.TelaoWindow()
        except Exception as e:
            log.warning(f"⚠️ Falha ao recriar telão: {e}")
            return telao if telao is not None else None
        try:
            novo.root.lower()
        except Exception:
            pass
        self.telao = novo
        cb = getattr(self, "on_telao_recriado", None)
        if cb:
            try:
                cb(novo)
            except Exception as e:
                log.warning(f"⚠️ Falha ao reaplicar config no telão recriado: {e}")
        return novo

    def _monitorar(self) -> None:
        """Verifica se o player terminou (sem polling, via after)."""
        processo_terminou = False
        # Um lançamento "desanexado" (cmd /c start) morre na hora que sai,
        # mas o player que ele abriu continua tocando. Nesse caso o fim não
        # pode ser deduzido do poll() — senão o NavePro pulava de faixa
        # sozinho logo depois de começar a tocar.
        ignora_processo = self._lancamento_desanexado
        with self._process_lock:
            if self._process is not None and not ignora_processo:
                rc = self._process.poll()
                if rc is not None:
                    # rc não-None significa que o processo morreu (qualquer código)
                    # SMPlayer pode retornar 0, 1, -15, etc. Todos indicam fim.
                    self.is_playing = False
                    self.is_paused = False
                    processo_terminou = True
                    self._process = None
                    self._player_pid = None

        if processo_terminou:
            self.telao = self._garantir_telao()
            t2 = self.telao
            if t2 is not None:
                try:
                    t2.restaurar_tela()
                except Exception:
                    pass
            # Só dispara "ended" se o processo NÃO foi morto intencionalmente
            # (stop, próximo, anterior, tocar_indice já tratam a transição)
            if self.on_state_change and not self._killed_intentionally:
                self.on_state_change("ended")
            self._killed_intentionally = False  # Reset para próxima execução

        t = self._garantir_telao()
        if t is not None and t.rodando:
            # Aguarda 500ms entre verificações (usa try para ser seguro)
            # Usa o after da janela principal (AppInterface.root) se disponível,
            # senão usa o do telão
            try:
                if hasattr(self, '_root_after') and self._root_after:
                    self._root_after.after(500, self._monitorar)
                else:
                    t.root.after(500, self._monitorar)
            except tk.TclError:
                pass

    def carregar_playlist(self, arquivos: list[str]) -> None:
        """Define a playlist de arquivos."""
        self.playlist = list(arquivos) if arquivos else []
        self.index = 0

    def _monitor_alvo(self):
        """Devolve o MonitorInfo do telão (com fallback se a lista falhar)."""
        try:
            monitors = get_monitors_config()
            if len(monitors) >= self.monitor_index:
                return monitors[self.monitor_index - 1]
            if len(monitors) > 1:
                return monitors[1]
            return monitors[0]
        except Exception:
            return MonitorInfo(1920, 0, 1920, 1080, "Telão")

    def _get_monitor_geometry(self) -> tuple[int, int, int, int]:
        """Retorna (x, y, width, height) do monitor alvo."""
        try:
            m = self._monitor_alvo()
            return m.x, m.y, m.width, m.height
        except Exception:
            return 1920, 0, 1920, 1080

    def _indice_screennumber(self) -> int:
        """Índice 0-based do telão para o `--qt-fullscreen-screennumber` do VLC.

        O VLC numera os monitores na ordem em que o Windows os enumera
        (primário primeiro), e é a mesma ordem de `get_monitors_config()`.
        Confere pela geometria: se dois monitores tivessem a mesma origem,
        o índice da lista ainda seria o certo.
        """
        try:
            m = self._monitor_alvo()
            for indice, outro in enumerate(get_monitors_config()):
                if (outro.x, outro.y, outro.width, outro.height) == (
                        m.x, m.y, m.width, m.height):
                    return indice
        except Exception:
            pass
        return 0

    def _matar_processo(self) -> None:
        """Mata o processo atual e TODOS os seus filhos (grupo de processos).
        
        Como usamos start_new_session=True ao criar o processo, o SMPlayer
        e o mplayer filho pertencem ao mesmo grupo (PGID = PID do pai).
        Matar o grupo inteiro garante que o áudio pare.
        """
        self._fechar_ipc()

        with self._process_lock:
            proc = self._process
            self._process = None
            self._player_pid = None

        if proc is None:
            return

        self._killed_intentionally = True
        pid = proc.pid
        log.info(f"🛑 Encerrando processo {pid} (grupo)...")

        if _eh_windows():
            # Windows: não existem grupos de processo nem os sinais POSIX.
            # `taskkill /T` é o equivalente: sem o /T, um player que abre
            # processo auxiliar sobrevive ao terminate() e continua tocando.
            encerrar_arvore(pid)
            try:
                proc.wait(timeout=2.0)
                return
            except subprocess.TimeoutExpired:
                pass
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
            return

        try:
            pgid = os.getpgid(pid)
            # Wake-up se o pause congelou o grupo (SIGSTOP): processo parado
            # ignora SIGTERM (fica pendurado); CONT acorda e o TERM mata.
            try:
                os.killpg(pgid, signal.SIGCONT)
            except OSError:
                pass
            # SIGTERM no grupo inteiro (mata smplayer + mplayer filho)
            os.killpg(pgid, signal.SIGTERM)
            
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                # Se timeout, SIGKILL no grupo
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=1.0)
        except ProcessLookupError:
            pass  # Já morreu naturalmente
        except Exception as e:
            log.exception(f"Erro ao encerrar processo {pid}: {e}")
            try:
                os.kill(pid, signal.SIGKILL)
            except (OSError, PermissionError):
                pass

    def _obter_duracao_arquivo(self, arquivo: str) -> float | None:
        """Obtém duração do arquivo via ffprobe com cache (evita chamadas repetidas)."""
        if not arquivo or not os.path.exists(arquivo):
            return None

        # Verifica cache primeiro
        with self._duracao_cache_lock:
            if arquivo in self._duracao_cache:
                return self._duracao_cache[arquivo]

        try:
            resultado = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries',
                 'format=duration', '-of',
                 'default=noprint_wrappers=1:nokey=1', arquivo],
                capture_output=True, text=True, timeout=5,
                env=_ambiente_sem_appimage()
            )
            if resultado.returncode == 0 and resultado.stdout.strip():
                duracao = float(resultado.stdout.strip())
                with self._duracao_cache_lock:
                    # LRU: remove mais antigo se exceder limite
                    if len(self._duracao_cache) >= self._DURACAO_CACHE_MAX:
                        self._duracao_cache.pop(next(iter(self._duracao_cache)))
                    self._duracao_cache[arquivo] = duracao
                return duracao
        except (subprocess.TimeoutExpired, ValueError, OSError):
            pass
        return None

    def _tocar_arquivo(self, arquivo: str) -> bool:
        """Inicia a reprodução de um arquivo no player externo (sem sleep).

        Aceita também uma URL (http/https, ex.: YouTube): nesse caso a
        transmissão vai pelo mpv + yt-dlp, então os requisitos são checados
        antes de encerrar a reprodução atual.
        """
        _url = _eh_url(arquivo)
        if _url:
            _falta = self._checar_requisitos_url()
            if _falta:
                self._avisar(_falta)
                return False
            # yt-dlp velho não impede a tentativa, mas costuma ser a causa
            # do vídeo não abrir: avisa (uma vez por sessão) e segue.
            if not self._ja_avisou_ytdlp:
                self._ja_avisou_ytdlp = True
                _aviso_ytdlp = self._aviso_ytdlp_desatualizado()
                if _aviso_ytdlp:
                    self._avisar(_aviso_ytdlp)
        # Mata processo anterior
        self._matar_processo()

        if not _url and not os.path.exists(arquivo):
            log.error(f"❌ Arquivo não encontrado: {arquivo}")
            return False

        log.info(f"🎵 Tocando: {os.path.basename(arquivo)}")
        self.telao = self._garantir_telao()
        self.telao.preparar_video()
        self.tempo_acumulado = 0.0
        self.tempo_inicio = time.time()
        self.duracao_total = self._obter_duracao_arquivo(arquivo)

        mx, my, mw, mh = self._get_monitor_geometry()

        # Cada reprodução começa sem controle remoto e sem sendo "desanexada";
        # _montar_comando_player reaciona se for o caso do app padrão.
        self._fechar_ipc()
        self._pipe_mpv = ""
        self._lancamento_desanexado = False

        try:
            cmd = self._montar_comando_player(arquivo, mx, my, mw, mh)

            log.info(f"🎬 Executando: {' '.join(cmd)}")
            creationflags = 0
            if _eh_windows():
                # Não deixa a janela de console "piscar" ao lançar o player.
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(
                cmd, start_new_session=True, env=_ambiente_sem_appimage(),
                creationflags=creationflags
            )

            with self._process_lock:
                self._process = proc
                self._player_pid = proc.pid

            self.is_playing = True
            self.is_paused = False
            if _eh_windows():
                self._preparar_controle_windows(proc.pid, arquivo, mx, my, mw, mh)
            return True
        except Exception as e:
            log.exception(f"❌ Erro ao iniciar player: {e}")
            return False

    def _fechar_ipc(self) -> None:
        """Fecha o cliente IPC da reprodução anterior, se houver."""
        if self._ipc is not None:
            try:
                self._ipc.fechar()
            except Exception:
                pass
            self._ipc = None

    def _player_se_posiciona_sozinho(self) -> bool:
        """True se o player em uso já entra no telão sem ajuda do Win32.

        Só o VLC: ele aceita `--fullscreen` com `--qt-fullscreen-screennumber`
        e cumpre o monitor pedido (medido aqui no VLC 3.0.24, estável por
        46 s de reprodução). O mpv ignora `--screen`/`--geometry` em tela
        cheia, então para ele o NavePro continua movendo a janela.

        O VLC não pode ser reposicionado por `posicionar_janela_player`: o
        redimensionamento quebra o vout `direct3d11` e a janela cresce sem
        parar. Por isso ele entra EXCLUSIVAMENTE por este caminho.
        """
        return self._player_em_uso == "vlc"

    def _preparar_controle_windows(
        self, pid: int, arquivo: str, mx: int, my: int, mw: int, mh: int
    ) -> None:
        """Liga o canal de comando e joga a janela do player no telão.

        Duas coisas separadas, porque uma depende da outra:

        1. **Janela no telão** — reposiciona em uma thread de fundo, para não
           travar a interface enquanto espera a janela do player aparecer. Só
           para vídeo: arquivo de áudio não tem janela para cobrir.

        2. **Comando remoto** — se o player for o mpv, conecta no IPC dele. É
           o que dá pausa/continuar/parar e o tempo exato, e só precisa do
           pipe: não bloqueia.
        """
        if self._eh_arquivo_de_video(arquivo):
            # O VLC já entra em tela cheia no monitor certo por conta própria
            # (--fullscreen + --qt-fullscreen-screennumber), e redimensionar a
            # janela de vídeo dele quebra o vout (ver _montar_comando_player).
            # Então só escondemos o painel de controle que ele abre na tela
            # primária; nenhum SetWindowPos é feito.
            if self._player_se_posiciona_sozinho():
                def _limpar() -> None:
                    n = esconder_janelas_auxiliares(pid)
                    log.info(f"   🖥️ Vídeo no telão (player se posicionou)"
                          f"{f', {n} painel(is) escondido(s)' if n else ''}")

                threading.Thread(target=_limpar, daemon=True,
                                 name="navepro-limpa-vlc").start()
            else:
                def _posicionar() -> None:
                    ok = posicionar_janela_player(pid, mx, my, mw, mh)
                    if ok:
                        log.info("   🖥️ Player posicionado no telão")
                    else:
                        log.warning("   ⚠️ Não consegui posicionar o player no telão")

                threading.Thread(target=_posicionar, daemon=True,
                                 name="navepro-pos-player").start()

        if self._pipe_mpv:
            cliente = ClienteMpvIpc(self._pipe_mpv)
            if cliente.conectar():
                self._ipc = cliente
                log.info("🎛️ Controle remoto do mpv ligado (IPC)")

    def _checar_requisitos_url(self) -> str:
        """Mensagem de aviso se faltar mpv/yt-dlp para tocar uma URL.

        Devolve "" quando dá para transmitir. O mpv é quem toca e o yt-dlp
        é quem resolve a URL do YouTube; sem um dos dois o operador recebe
        uma instrução de instalação em vez de uma falha silenciosa.
        """
        if localizar_executavel("mpv") is None:
            if _eh_windows():
                return ("⚠️ Para reproduzir YouTube é preciso o mpv. "
                        "Instale com: winget install mpv-player.mpv-CI.MSVC")
            return ("⚠️ Para reproduzir YouTube é preciso o mpv. "
                    "Instale com: sudo apt install mpv (ou equivalente).")
        if (localizar_executavel("yt-dlp") is None
                and localizar_executavel("youtube-dl") is None):
            if _eh_windows():
                return ("⚠️ Para reproduzir YouTube é preciso o yt-dlp. "
                        "Instale com: winget install yt-dlp.yt-dlp")
            return ("⚠️ Para reproduzir YouTube é preciso o yt-dlp. "
                    "Instale com: sudo apt install yt-dlp (ou pipx install yt-dlp).")
        return ""

    def _versao_ytdlp(self) -> str:
        """Versão do yt-dlp instalado ("" se não houver/der para descobrir).

        Fica em cache por instância: é um processo a menos a cada item. Aceita
        o yt-dlp ou o antigo youtube-dl como nome do executável.
        """
        if self._ytdlp_versao is not None:
            return self._ytdlp_versao
        exe = localizar_executavel("yt-dlp") or localizar_executavel("youtube-dl")
        if not exe:
            self._ytdlp_versao = ""
            return ""
        try:
            r = subprocess.run(
                [exe, "--version"], capture_output=True, text=True,
                timeout=5, env=_ambiente_sem_appimage())
            saida = (r.stdout or "").strip().splitlines()
            self._ytdlp_versao = saida[0].strip() if saida else ""
        except (subprocess.SubprocessError, OSError):
            self._ytdlp_versao = ""
        return self._ytdlp_versao

    def _aviso_ytdlp_desatualizado(self) -> str:
        """Aviso se o yt-dlp estiver velho demais para o YouTube (senão "").

        NÃO bloqueia a reprodução: só alerta que o pacote do sistema está
        desatualizado. O app não atualiza o yt-dlp por conta própria — quem
        instala é o sistema (apt/pipx/binário), então a mensagem diz como.
        """
        versao = self._versao_ytdlp()
        if not versao:
            return ""
        # yt-dlp é versionado por data (ex.: 2025.09.26). Nightly/fora do
        # padrão não dá para medir: não avisa para não gerar falso positivo.
        m = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", versao)
        if not m:
            return ""
        try:
            lancamento = datetime.date(
                int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return ""
        idade = (datetime.date.today() - lancamento).days
        if idade <= _YTDLP_IDADE_MAX_DIAS:
            return ""
        return (f"⚠️ yt-dlp desatualizado ({versao}, há {idade} dias). "
                "Atualize com 'pipx upgrade yt-dlp' ou pelo gerenciador de "
                "pacotes para o YouTube voltar a funcionar.")

    def _montar_comando_player(
        self, arquivo: str, mx: int, my: int, mw: int, mh: int
    ) -> list[str]:
        """Monta o comando do player conforme o tipo configurado.

        ANTES de montar, verifica se o player existe no sistema (PATH +
        diretórios de instalação padrão). Se o configurado não existir, tenta
        alternativas — no Windows o mpv vem primeiro por ser o único com canal
        de comando; no Linux a ordem é a de sempre (smplayer, que expõe MPRIS).

        No Windows, como o monitor é escolhido:

        - **VLC** — aberto em `--fullscreen` + `--qt-fullscreen-screennumber`,
          então ele mesmo entra no monitor pedido. Não usamos
          `posicionar_janela_player` nele: redimensionar a janela de vídeo do
          VLC quebra o vout (medido aqui nos comentários do comando).
        - **mpv / SMPlayer** — abertos SEM `--fullscreen`, porque nenhum dos
          dois respeita o monitor pedido nesse modo (medido aqui: o mpv 0.41
          ignora `--screen` e `--geometry` e vai sempre para o primário). A
          janela é aberta normal e reposicionada sobre o telão por
          `posicionar_janela_player`.
        """
        player = self.player_cmd

        # URL (ex.: item YouTube da Ordem de Serviço): caminho dedicado.
        # Os requisitos (mpv/yt-dlp) já foram checados em _tocar_arquivo.
        if _eh_url(arquivo):
            return self._montar_comando_url(arquivo, mx, my, mw, mh)

        # Verifica se o player configurado existe no sistema
        if not self._player_existe(player):
            log.warning(f"\u26a0\ufe0f Player '{player}' n\u00e3o encontrado no sistema!")
            # Tenta alternativas em ordem de prefer\u00eancia
            alternativas = (["mpv", "vlc", "smplayer"] if _eh_windows()
                            else ["smplayer", "mpv", "vlc"])
            for alt in alternativas:
                if self._player_existe(alt):
                    log.info(f"   \u27a1\ufe0f Usando '{alt}' como alternativa")
                    player = alt
                    break
            else:
                log.error("   ❌ Nenhum player encontrado! "
                      "Usando o aplicativo padrão")
                self._lancamento_desanexado = True
                if _eh_windows():
                    return ['cmd', '/c', 'start', '', arquivo]
                return ['xdg-open', arquivo]

        # Player realmente usado (pode ter mudado pelo fallback acima). É
        # daqui que _preparar_controle_windows descobre se precisa posicionar
        # a janela ou se o player já se posicionou sozinho.
        self._player_em_uso = player

        if player == "smplayer":
            if _eh_windows():
                exe = localizar_executavel("smplayer") or "smplayer"
                return [exe, '-close-at-end', '--no-embedded-video', arquivo]
            return [
                'smplayer', '-close-at-end', '-fullscreen',
                arquivo,
            ]
        elif player == "vlc":
            if _eh_windows():
                exe = localizar_executavel("vlc") or "vlc"
                # Fullscreen pedido AO VLC, e não via SetWindowPos.
                # Medido aqui: redimensionar a janela de vídeo do VLC 3.0.24
                # (vout direct3d11) faz o vout renegociar o tamanho a cada
                # chamada — a janela cresce sem parar (1920x1080 → 5328x9368
                # → 10240x21341 → 12864x27737), o monitor do telão fica com
                # uma cor só (sem imagem) e a máquina trava. Deixando o VLC
                # se posicionar sozinho, o vídeo entra certo e fica estável.
                # `--qt-fullscreen-screennumber` é o que escolhe o monitor
                # (é 0-based, na ordem do Windows: primário primeiro).
                return [
                    exe, '--quiet', '--no-osd', '--no-video-title-show',
                    '--play-and-exit', '--fullscreen',
                    f'--qt-fullscreen-screennumber={self._indice_screennumber()}',
                    arquivo,
                ]
            return [
                'vlc', '--quiet', '--no-osd', '--no-video-title-show',
                '--play-and-exit', '--fullscreen',
                '--no-embedded-video',
                f'--video-x={mx}', f'--video-y={my}',
                f'--width={mw}', f'--height={mh}',
                arquivo,
            ]
        elif player == "mpv":
            if _eh_windows():
                exe = localizar_executavel("mpv") or "mpv"
                self._contador_pipe += 1
                self._pipe_mpv = nome_pipe_mpv(self._contador_pipe)
                return [
                    exe, '--no-border',
                    '--really-quiet', '--no-terminal',
                    f'--input-ipc-server={self._pipe_mpv}',
                    '--keep-open=no',
                    f'--geometry={mw}x{mh}+{mx}+{my}',
                    arquivo,
                ]
            return [
                'mpv', '--fullscreen',
                f'--screen={self._indice_screennumber()}',
                '--really-quiet', '--no-terminal',
                f'--geometry={mw}x{mh}+{mx}+{my}',
                *_opcoes_telao_wayland(self._monitor_alvo().name),
                arquivo,
            ]
        else:
            self._lancamento_desanexado = True
            if _eh_windows():
                # Abre com o aplicativo padrão do Windows (sem console).
                return ['cmd', '/c', 'start', '', arquivo]
            return ['xdg-open', arquivo]

    def _montar_comando_url(self, url: str, mx: int, my: int,
                            mw: int, mh: int) -> list[str]:
        """Comando do mpv para uma URL de vídeo (ex.: YouTube).

        O mpv resolve a URL pelo yt-dlp (já verificado por _tocar_arquivo),
        então este caminho força o mpv em vez de usar o player configurado.
        No Windows liga o IPC (dá pausa/continuar/parar, como um vídeo local);
        no Linux abre em tela cheia no telão — o `--screen` segue o monitor
        configurado (`_indice_screennumber`), não o índice 1 fixo: com o
        `--screen=1` empedrado o vídeo abria no monitor do operador quando o
        telão configurado não era o segundo da lista.
        """
        self._player_em_uso = "mpv"
        if _eh_windows():
            exe = localizar_executavel("mpv") or "mpv"
            self._contador_pipe += 1
            self._pipe_mpv = nome_pipe_mpv(self._contador_pipe)
            return [
                exe, '--no-border',
                '--really-quiet', '--no-terminal',
                f'--input-ipc-server={self._pipe_mpv}',
                '--keep-open=no',
                f'--geometry={mw}x{mh}+{mx}+{my}',
                *_MPV_YTDL_OPCOES,
                url,
            ]
        return [
            'mpv', '--fullscreen',
            f'--screen={self._indice_screennumber()}',
            '--really-quiet', '--no-terminal',
            f'--geometry={mw}x{mh}+{mx}+{my}',
            *_opcoes_telao_wayland(self._monitor_alvo().name),
            *_MPV_YTDL_OPCOES,
            url,
        ]

    def _eh_arquivo_de_video(self, arquivo: str) -> bool:
        """True para extensão de vídeo — só vídeo tem janela para posicionar."""
        return os.path.splitext(arquivo or "")[1].lower() in EXTENSOES_VIDEO, PLAYER_PADRAO

    @staticmethod
    def _player_existe(player: str) -> bool:
        """Verifica se um player está disponível no sistema.

        No Linux é o que sempre foi: PATH + /usr/bin, /usr/local/bin e
        /run/host/usr/bin (sandbox do AppImage).

        No Windows passou a olhar também os diretórios de instalação padrão
        (Program Files, WinGet, scoop, Chocolatey). Sem isso, o VLC instalado
        em "C:\\Program Files\\VideoLAN\\VLC" — que normalmente não está no
        PATH do processo — era dado como inexistente, o NavePro caía no
        "aplicativo padrão do sistema" e perdia o controle do player.
        """
        return localizar_executavel(player) is not None

    def _ipc_mpv_disponivel(self) -> bool:
        """True se há um mpv conectado e respondendo ao IPC.

        Exige as duas coisas: o pipe aberto E o processo vivo. O handle do
        pipe continua "válido" para o Windows mesmo depois de o mpv sair, então
        sozinho ele não serve de resposta — sem o poll(), o NavePro ficaria
        perguntando o tempo para um player que já terminou.
        """
        if self._ipc is None or not self._ipc.vivo():
            return False
        with self._process_lock:
            proc = self._process
        return proc is not None and proc.poll() is None

    def _avisar(self, mensagem: str) -> None:
        """Manda um aviso para o painel (sem travar a interface)."""
        log.warning(f"⚠️ {mensagem}")
        if self.on_aviso:
            try:
                self.on_aviso(mensagem)
            except Exception:
                pass  # Nunca deixar o aviso derrubar o playback

    def _sem_controle_remoto(self) -> bool:
        """True se o player em uso não aceita comando de pause/continuar.

        Só o mpv expõe um canal de comando no Windows (IPC JSON). VLC e
        SMPlayer abrem o vídeo, são posicionados no telão e param pelo
        `taskkill`, mas ignoram pausa — medido aqui: o VLC 3.0.24 não responde
        nem pela interface HTTP dele nem por `WM_APPCOMMAND`. No Linux quem
        atende é o D-Bus/MPRIS, presente no smplayer.
        """
        if _eh_windows():
            return self._ipc is None
        if _eh_linux():
            return False  # D-Bus/MPRIS: o painel assume que dá
        return True

    def _explicar_sem_controle(self) -> str:
        """Mensagem actionable sobre a falta de controle remoto."""
        if _eh_windows():
            if self.player_cmd and self.player_cmd != "mpv":
                return (f"⚠️ Pausar/continuar não funciona com "
                        f"'{self.player_cmd}' — ele não aceita comando remoto. "
                        f"Em Configurações, troque o player para 'mpv'.")
            return ("⚠️ Pausar/continuar precisa do mpv, que não está instalado. "
                    "Instale com: winget install mpv-player.mpv-CI.MSVC "
                    "(vídeo e parar funcionam mesmo sem ele)")
        return ("⚠️ Este player não aceita comando remoto; "
                "use um player com D-Bus/MPRIS (smplayer) no Linux.")

    def _avisar_sem_controle_se_precisar(self) -> None:
        """Chamado quando um pause/continuar não surtiu efeito."""
        if not self._sem_controle_remoto() or self._ja_avisou_sem_controle:
            return
        self._ja_avisou_sem_controle = True
        self._avisar(self._explicar_sem_controle())

    def _pausar_player(self) -> bool:
        """Pausa/continua o player externo.

        No Linux usa D-Bus (MPRIS) ou SIGSTOP/SIGCONT (fallback). No Windows
        usa o IPC JSON do mpv — o equivalente ao MPRIS. Sem nenhum dos dois
        (macOS, ou player que não expõe canal) devolve False e o chamador
        mantém o estado interno como estava.

        No Flatpak o SIGSTOP direto não serve: o player roda no HOST
        (flatpak-spawn) e o processo na mão é só o proxy do smplayer-host —
        ali o sinal vai pelo pidfile do shim, no grupo do player real.
        Além disso, dentro do sandbox os MÉTODOS MPRIS (PlayPause/Pause/
        Play) não pausam o smplayer de forma consistente — só a leitura de
        propriedade funciona — por isso o caminho Flatpak tenta o pidfile
        PRIMEIRO e só cai no MPRIS se o sinal falhar, e o MPRIS só afirma
        sucesso se o PlaybackStatus realmente mudar.
        """
        if _eh_windows():
            if not self._ipc_mpv_disponivel():
                return False
            try:
                # These runs on the Tk main thread (tecla de pause/continuar),
                # so the timeout is tight: the named pipe is local and answers
                # in milliseconds. If mpv is hung, we don't want to freeze the
                # interface waiting for it.
                return self._ipc.definir_pausa(not self.is_paused, timeout=1.0)
            except Exception:
                return False
        if not _eh_linux():
            return False

        candidatos: list[str] = []
        for nome in (self._player_em_uso, self.player_cmd):
            dest = destino_mpris(nome or "")
            if dest and dest not in candidatos:
                candidatos.append(dest)
        for dest in MPRIS_DESTS.values():
            if dest not in candidatos:
                candidatos.append(dest)

        # Flatpak: sinal no player do HOST pelo pidfile do shim — caminho
        # confiável (mpv congela junto com o smplayer, mesmo grupo).
        if _eh_flatpak():
            if self._pausar_player_flatpak():
                return True
            # Se o pidfile falhou, tenta MPRIS com verificação de status.
            dest = mpris_ativo(candidatos)
            if dest and self._mpris_alternar(dest):
                return True
            return False

        # AppImage/código-fonte: MPRIS com verificação — o nome no
        # barramento não basta; o PlaybackStatus precisa ter mudado.
        dest = mpris_ativo(candidatos)
        if dest and self._mpris_alternar(dest):
            return True

        # Fallback direto: o player é filho nosso.
        with self._process_lock:
            proc = self._process
        if proc is None:
            return False
        try:
            sig = signal.SIGCONT if self.is_paused else signal.SIGSTOP
            os.kill(proc.pid, sig)
            return True
        except (OSError, PermissionError):
            return False

    def _mpris_alternar(self, dest: str) -> bool:
        """PlayPause via MPRIS; True só se o PlaybackStatus mudou.

        O dbus-send devolve exit 0 mesmo quando o nome não existe, e dentro
        do Flatpak o método chega ao barramento mas não pausa o smplayer.
        Ler o status antes e depois é o que garante que o painel não mostre
        'pausado' com o vídeo tocando.
        """
        antes = mpris_status(dest)
        try:
            subprocess.run(
                ['dbus-send', '--type=method_call',
                 f'--dest={dest}',
                 '/org/mpris/MediaPlayer2',
                 'org.mpris.MediaPlayer2.Player.PlayPause'],
                timeout=1, capture_output=True, env=_ambiente_sem_appimage()
            )
        except Exception:
            return False
        depois = mpris_status(dest)
        return bool(antes and depois and depois != antes)

    def _pausar_player_flatpak(self) -> bool:
        """Pausa/continua o player do HOST (Flatpak) pelo pidfile do shim.

        Os shims `smplayer-host`/`mpv-host` gravam o PID real do player em
        ~/.navepro/<player>-host.pid — mesmo caminho dentro e fora do sandbox.
        O sinal vai por `flatpak-spawn --host` no GRUPO de processos, o mesmo
        mecanismo que o shim usa para repassar o TERM: smplayer e mpv param
        juntos. SIGSTOP no proxy (o processo que o NavePro tem na mão) não
        pausava nada — é por isso que o pause não funcionava no Flatpak.

        O mpv tem shim próprio (mpv-host) porque o sandbox não traz mpv: sem
        ele o item YouTube e o vídeo local com o player mpv nem abriam. Só o
        pidfile do player em uso é consultado — um `mpv-host.pid` velho (de
        outra sessão) nunca deve receber sinal de pause do smplayer, nem
        vice-versa. VLC não tem shim no Flatpak: sem pidfile, cai no MPRIS.
        """
        if self._player_em_uso == "mpv":
            nome = "mpv-host.pid"
        elif self._player_em_uso == "smplayer":
            nome = "smplayer-host.pid"
        else:
            return False  # sem shim (ex.: vlc) → pause fica com o MPRIS
        pidfile = os.path.join(os.path.expanduser("~"), ".navepro", nome)
        sig = "CONT" if self.is_paused else "STOP"
        try:
            with open(pidfile, encoding="utf-8") as arq:
                pid = int(arq.read().strip())
        except (OSError, ValueError):
            return False
        if pid <= 0:
            return False
        # kill direto (util-linux), sem wrapper de sh: o /bin/sh do host é o
        # dash, cujo builtin kill rejeita pid negativo ("Illegal number: -")
        # e aí o mpv do grupo seguia tocando. Grupo primeiro (smplayer + mpv);
        # PID sozinho se o grupo não existir mais.
        for alvo in (f"-{pid}", str(pid)):
            try:
                resp = subprocess.run(
                    ['flatpak-spawn', '--host', 'kill', f'-{sig}', '--', alvo],
                    timeout=2, capture_output=True,
                    env=_ambiente_sem_appimage())
                if resp.returncode == 0:
                    return True
            except Exception:
                continue
        return False

    def obter_tempo_decorrido(self) -> float:
        """Retorna o tempo decorrido em segundos."""
        if self.tempo_inicio is not None:
            return self.tempo_acumulado + (time.time() - self.tempo_inicio)
        return self.tempo_acumulado

    def sincronizar_tempo_dbus(self, player: str = "") -> None:
        """Sincroniza tempo/estado com o player externo.

        O nome é herança do Linux, onde isso é D-Bus/MPRIS. No Windows a mesma
        função pergunta o IPC JSON do mpv (mesma ideia: o player é a fonte da
        verdade do que está tocando). Em qualquer outro SO fica só com o
        relógio local do NavePro.
        """
        if not self.is_playing:
            return

        # No Linux o pause congela o player (SIGSTOP no grupo): o servidor
        # MPRIS dele para de responder e cada sync de D-Bus seguraria a
        # interface ~2 s no timeout. Com pausa, o estado interno já é a
        # fonte da verdade — não há o que sincronizar.
        if self.is_paused and _eh_linux():
            return

        if _eh_windows():
            self._sincronizar_ipc_mpv()
            return

        if not _eh_linux():
            return

        dest = player or self._player_em_uso or self.player_cmd
        mpris_dest = destino_mpris(dest)

        if mpris_dest is None:
            return

        try:
            # Obtém status e posição em uma única chamada D-Bus
            result = subprocess.run(
                ['dbus-send', '--print-reply',
                 f'--dest={mpris_dest}',
                 '/org/mpris/MediaPlayer2',
                 'org.freedesktop.DBus.Properties.GetAll',
                 'string:org.mpris.MediaPlayer2.Player'],
                capture_output=True, text=True, timeout=2,
                env=_ambiente_sem_appimage()
            )

            stdout = result.stdout
            status = None
            position_us: int | None = None

            for line in stdout.split('\n'):
                stripped = line.strip()
                if 'string "Playing"' in stripped:
                    status = 'Playing'
                elif 'string "Paused"' in stripped:
                    status = 'Paused'
                elif 'int64' in stripped:
                    try:
                        position_us = int(stripped.split()[-1])
                    except (ValueError, IndexError):
                        pass

            if position_us is not None:
                position_sec = position_us / 1_000_000
                if status == 'Playing':
                    self.is_paused = False
                    self.tempo_acumulado = position_sec
                    self.tempo_inicio = time.time()
                elif status == 'Paused':
                    self.is_paused = True
                    self.tempo_acumulado = position_sec
                    self.tempo_inicio = None
        except Exception:
            pass  # Mantém valores internos

    def _sincronizar_ipc_mpv(self) -> None:
        """Pergunta ao mpv (via IPC) o estado real da reprodução.

        Três propriedades por sincronização. O `duration` também substitui o
        ffprobe no Windows: ele quase nunca está instalado lá, e sem ele a
        barra de progresso ficava sem tempo total.

        O tratamento é idêntico ao do caminho D-Bus do Linux — `tempo_acumulado`
        vira a última posição conhecida e `tempo_inicio` reanima a contagem até
        a próxima sincronização, de modo que o tempo exibido não "pula".
        """
        if not self._ipc_mpv_disponivel():
            return
        ipc = self._ipc
        # Isso roda no `after` do Tk, na thread da interface: as três
        # propriedades compartilham UM prazo, para que um mpv travado não
        # trave a interface por 3x o timeout.
        limite = time.monotonic() + 1.2
        try:
            pausado = ipc.propriedade("pause", timeout=1.2)
            posicao = ipc.propriedade("time-pos",
                                      timeout=max(0.05, limite - time.monotonic()))
            duracao = ipc.propriedade("duration",
                                      timeout=max(0.05, limite - time.monotonic()))
        except Exception:
            return  # Mantém valores internos

        if isinstance(duracao, (int, float)) and duracao > 0:
            self.duracao_total = float(duracao)
        if isinstance(posicao, (int, float)) and posicao >= 0:
            self.is_paused = bool(pausado)
            self.tempo_acumulado = float(posicao)
            self.tempo_inicio = None if self.is_paused else time.time()

    # ── Controles principais ──────────────────────────────────────

    def play_pause(self) -> None:
        """Alterna entre play e pause (sem busy waiting)."""
        if self.is_playing and not self.is_paused:
            if self._pausar_player():
                self.is_paused = True
                if self.tempo_inicio is not None:
                    self.tempo_acumulado += time.time() - self.tempo_inicio
                    self.tempo_inicio = None
            else:
                # O player não aceitou o comando: o estado interno não muda
                # (senão o painel mentiria), e o operador é avisado de por quê.
                self._avisar_sem_controle_se_precisar()
        elif self.is_paused:
            if self._pausar_player():
                self.is_paused = False
                self.is_playing = True
                self.tempo_inicio = time.time()
            else:
                self._avisar_sem_controle_se_precisar()
        else:
            if self.playlist and self.index < len(self.playlist):
                arquivo = self.playlist[self.index]
                if self._tocar_arquivo(arquivo):
                    if self.on_track_change:
                        self.on_track_change(self.index, arquivo)

    def stop(self) -> None:
        """Para o player completamente."""
        # Pedir educadamente primeiro: o mpv sai pelo IPC, fechando o vídeo e
        # o áudio sem o piscar do /F. Se o IPC não responder, _matar_processo
        # cai no taskkill /T.
        if self._ipc_mpv_disponivel():
            try:
                if self._ipc.encerrar():
                    log.info("🛑 Player encerrado pelo IPC")
                    self._fechar_ipc()
                    with self._process_lock:
                        proc = self._process
                        self._process = None
                        self._player_pid = None
                    if proc is not None:
                        try:
                            proc.wait(timeout=2.0)
                        except subprocess.TimeoutExpired:
                            pass
                    self.is_playing = False
                    self.is_paused = False
                    self.tempo_inicio = None
                    self.tempo_acumulado = 0.0
                    self.duracao_total = None
                    self.telao = self._garantir_telao()
                    self.telao.restaurar_tela()
                    log.info("✅ Player parado")
                    return
            except Exception:
                pass  # Cai para o encerramento forçado
        self._matar_processo()
        self.is_playing = False
        self.is_paused = False
        self.tempo_inicio = None
        self.tempo_acumulado = 0.0
        self.duracao_total = None
        self.telao = self._garantir_telao()
        self.telao.restaurar_tela()
        log.info("✅ Player parado")

    def proximo(self) -> bool:
        """Avança para o próximo item da playlist (sem sleep)."""
        if not self.playlist or self.index >= len(self.playlist) - 1:
            return False
        log.info("⏭ Indo para próximo...")
        self.index += 1
        arquivo = self.playlist[self.index]
        if self._tocar_arquivo(arquivo):
            if self.on_track_change:
                self.on_track_change(self.index, arquivo)
            return True
        return False

    def anterior(self) -> bool:
        """Volta para o item anterior da playlist (sem sleep)."""
        if not self.playlist or self.index <= 0:
            log.warning("⚠️ Não há item anterior")
            return False
        log.info("⏮ Voltando para anterior...")
        self.index -= 1
        arquivo = self.playlist[self.index]
        if self._tocar_arquivo(arquivo):
            if self.on_track_change:
                self.on_track_change(self.index, arquivo)
            return True
        return False

    def tocar_indice(self, indice: int) -> bool:
        """Toca um índice específico da playlist (sem sleep)."""
        if not self.playlist or indice < 0 or indice >= len(self.playlist):
            return False
        log.info(f"🎯 Tocando índice {indice}...")
        self.index = indice
        arquivo = self.playlist[self.index]
        if self._tocar_arquivo(arquivo):
            if self.on_track_change:
                self.on_track_change(self.index, arquivo)
            return True
        return False

    def mostrar_relogio(self, texto: str, temperatura: str = "") -> None:
        """Atualiza o relógio no telão (se estiver no modo relógio)."""
        if self.telao.mostrando_relogio and not self.is_playing:
            self.telao.mostrar_relogio(texto, temperatura)
