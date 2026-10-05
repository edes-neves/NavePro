#!/usr/bin/env python3
"""Testes do controle do player no Windows (navepro/core/player.py).

Regressões travadas aqui:

1. **Descoberta de executável** — o Windows não tem smplayer/vlc/mpv no PATH,
   e antes disso o NavePro caía em "app default", que solta o player e perde
   o controle. `localizar_executavel` precisa achar os três em disco.

2. **Pipe do mpv único por reprodução** — se o nome se repetisse, o mpv novo
   reconectaria no servidor do mpv velho e o NavePro controlaria o player errado.

3. **Flags do comando** — no Windows o player NÃO pode levar `--fullscreen`:
   medido aqui, o mpv ignora `--screen`/`--geometry` em tela cheia e sempre abre
   no monitor primário. A posição vem do Win32 depois.

4. **Fim de faixa** — lançamento desanexado (`cmd /c start`) não pode gerar
   "ended" falso logo depois de começar a tocar.

5. **Integridade** — `_pausar_player` precisa existir em todos os caminhos e o
   caminho Linux não pode ter sido comido.
"""

import ast
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

from navepro.core.player import (  # noqa: E402
    ClienteMpvIpc,
    encerrar_arvore,
    localizar_executavel,
    limpar_cache_executaveis,
    nome_pipe_mpv,
    posicionar_janela_player,
)
from navepro.core.ambiente import _eh_windows  # noqa: E402


def _extrair_metodo(classe: str, metodo: str) -> callable:
    """Pega um método do NavePro.py via AST, sem importar o app inteiro."""
    src = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
    no = ast.parse(src)
    for node in ast.walk(no):
        if isinstance(node, ast.ClassDef) and node.name == classe:
            for sub in node.body:
                if (isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and sub.name == metodo):
                    mod = ast.Module(body=[sub], type_ignores=[])
                    ast.fix_missing_locations(mod)
                    ns: dict = {"_eh_windows": _eh_windows,
                                "localizar_executavel": localizar_executavel,
                                "nome_pipe_mpv": nome_pipe_mpv}
                    exec(compile(mod, f"<{classe}.{metodo}>", "exec"), ns)
                    return ns[metodo]
    raise AssertionError(f"{classe}.{metodo} não encontrada em NavePro.py")


def _fontes_da_classe(classe: str) -> str:
    src = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
    no = ast.parse(src)
    for node in ast.walk(no):
        if isinstance(node, ast.ClassDef) and node.name == classe:
            return ast.unparse(node)
    raise AssertionError(f"classe {classe} não encontrada em NavePro.py")


def _rodar() -> int:
    falhas = 0

    def checar(desc, cond):
        nonlocal falhas
        print(f"{'?' if cond else 'X'} {desc}")
        if not cond:
            falhas += 1

    # ── 1. Descoberta de executável ──────────────────────────────────
    limpar_cache_executaveis()
    achados = {nome: localizar_executavel(nome)
               for nome in ("mpv", "vlc", "smplayer")}
    for nome, caminho in achados.items():
        if caminho:
            print(f"   {nome}: {caminho}")
            checar(f"{nome} encontrado é um arquivo existente",
                   os.path.isfile(caminho))
        else:
            print(f"   {nome}: não instalado (teste pula a checagem)")

    checar("localizar_executavel ignora nomes absurdos",
           localizar_executavel("player_que_nao_existe_xyz") is None)
    checar("localizar_executavel trata entrada vazia",
           localizar_executavel("") is None)

    # ── 2. Pipe do mpv único por reprodução ──────────────────────────
    p1 = nome_pipe_mpv(1)
    p2 = nome_pipe_mpv(2)
    checar("pipes de faixas diferentes são diferentes", p1 != p2)
    checar("pipe começa com o prefixo de named pipe do Windows",
           p1.startswith("\\\\.\\pipe\\"))
    checar("pipe tem o PID do NavePro (evita colisão entre cópias)",
           str(os.getpid()) in p1)
    checar("nome_pipe_mpv é repetível (mesmo índice, mesmo nome)",
           nome_pipe_mpv(1) == p1)

    # ── 3. Comando do player no Windows ───────────────────────────────
    montar = _extrair_metodo("MediaPlayer", "_montar_comando_player")
    if _eh_windows():
        mpv = localizar_executavel("mpv")
        if mpv:
            # self mínimo: só o que _montar_comando_player usa.
            fake = type("F", (), {
                "player_cmd": "mpv", "_lancamento_desanexado": False,
                "_pipe_mpv": "", "_contador_pipe": 0,
                "_player_existe": staticmethod(
                    lambda n: localizar_executavel(n) is not None),
                "_print": staticmethod(lambda *a: None),
            })()
            cmd = montar(fake, "musica.mp3", 1920, 0, 1920, 1080)
            checar("mpv é chamado pelo caminho completo (não depende do PATH)",
                   cmd[0] == mpv)
            checar("mpv NÃO recebe --fullscreen no Windows",
                   "--fullscreen" not in cmd)
            checar("mpv recebe --screen=1 também não (quebra o telão)",
                   not any(c.startswith("--screen") for c in cmd))
            checar("mpv recebe o pipe de IPC",
                   any(c.startswith("--input-ipc-server=") for c in cmd))
            checar("mpv fica sem moldura (--no-border)",
                   "--no-border" in cmd)
            checar("--autofit=no não é usado (faz o mpv sair com erro 1)",
                   not any(c.startswith("--autofit") for c in cmd))
            checar("o nome do arquivo é o último argumento",
                   cmd[-1] == "musica.mp3")
            checar("o pipe foi guardado para conectar depois",
                   fake._pipe_mpv.startswith("\\\\.\\pipe\\navepro-mpv-"))
            checar("lançamento NÃO é desanexado (mpv é chamado direto)",
                   fake._lancamento_desanexado is False)

            vlc = localizar_executavel("vlc")
            if vlc:
                fake2 = type("F", (), {
                    "player_cmd": "vlc", "_lancamento_desanexado": False,
                    "_pipe_mpv": "", "_contador_pipe": 0,
                    "_player_existe": staticmethod(
                        lambda n: localizar_executavel(n) is not None),
                })()
                cmd2 = montar(fake2, "video.mp4", 1920, 0, 1920, 1080)
                checar("vlc é chamado pelo caminho completo",
                       cmd2[0] == vlc)
                checar("vlc NÃO recebe --fullscreen no Windows",
                       "--fullscreen" not in cmd2)
                checar("vlc não é lançado desanexado (senão perde o handle)",
                       fake2._lancamento_desanexado is False)

            # Player configurado que não existe: tem de cair no mpv (que tem
            # canal de comando), não no SMPlayer (não tem).
            smplayer = localizar_executavel("smplayer")
            fake3 = type("F", (), {
                "player_cmd": "player-inexistente", "_lancamento_desanexado": False,
                "_pipe_mpv": "", "_contador_pipe": 0,
                "_player_existe": staticmethod(
                    lambda n: localizar_executavel(n) is not None),
            })()
            cmd3 = montar(fake3, "video.mp4", 1920, 0, 1920, 1080)
            if mpv and smplayer:
                checar("player inexistente cai no mpv, não no smplayer",
                       cmd3[0] == mpv)
                checar("comando de fallback continua sendo um player direto",
                       cmd3[0] != "cmd")
        else:
            print("   (mpv ausente: pulando os testes de comando)")
    else:
        # No Linux nada muda: player direto, sem IPC, sem pipe.
        fake = type("F", (), {
            "player_cmd": "smplayer", "_lancamento_desanexado": False,
            "_pipe_mpv": "", "_contador_pipe": 0,
            "_player_existe": staticmethod(lambda n: True),
        })()
        cmd = montar(fake, "video.mp4", 0, 0, 1920, 1080)
        checar("Linux: smplayer direto", cmd[0] == "smplayer")
        checar("Linux: sem pipe de IPC", not fake._pipe_mpv)
        checar("Linux: sem --no-border do Windows", "--no-border" not in cmd)

    # ── 4. Fim de faixa com lançamento desanexado ──────────────────────
    monitorar = _extrair_metodo("MediaPlayer", "_monitorar")
    if _eh_windows():
        import subprocess
        import sys as _sys
        import threading

        class _TelaoFalsa:
            rodando = False

            def restaurar_tela(self):
                pass

        def _cenario(desanexado):
            """Objeto com o mínimo que _monitorar toca, sobre um processo morto."""
            proc = subprocess.Popen([_sys.executable, "-c", "pass"])
            proc.wait()
            obj = type("F", (), {})()
            obj._process_lock = threading.Lock()
            obj._process = proc
            obj._player_pid = proc.pid
            obj._lancamento_desanexado = desanexado
            obj._killed_intentionally = False
            obj.is_playing = True
            obj.is_paused = False
            obj.telao = _TelaoFalsa()
            obj._root_after = None
            obj._garantir_telao = lambda: _TelaoFalsa()
            eventos = []
            obj.on_state_change = lambda e: eventos.append(e)
            return obj, eventos

        # Processo morto e lançado direto: o fim é real e precisa ser avisado,
        # senão a playlist trava na faixa que acabou.
        obj, eventos = _cenario(False)
        monitorar(obj)
        checar("processo morto com handle próprio → ended (comportamento antigo)",
               eventos == ["ended"])
        checar("ended limpa o handle do processo",
               obj._process is None and obj._player_pid is None)
        checar("ended marca que não está tocando",
               obj.is_playing is False and obj.is_paused is False)

        # Mesmo processo morto, mas lançado desanexado: NÃO pode dar ended,
        # senão o NavePro pula de faixa assim que começa a tocar.
        obj2, eventos2 = _cenario(True)
        monitorar(obj2)
        checar("lançamento desanexado não dispara ended falso",
               eventos2 == [])
        checar("lançamento desanexado continua marcado como tocando",
               obj2.is_playing is True)

        # Morte intencional (parar/avançar) também não deve virar ended.
        obj3, eventos3 = _cenario(False)
        obj3._killed_intentionally = True
        monitorar(obj3)
        checar("morte intencional não dispara ended", eventos3 == [])

    # ── 5. Pausa: existe em todos os caminhos, sem encolher o Linux ────
    fonte = _fontes_da_classe("MediaPlayer")
    checar("MediaPlayer tem _pausar_player", "def _pausar_player" in fonte)
    checar("MediaPlayer tem _ipc_mpv_disponivel",
           "def _ipc_mpv_disponivel" in fonte)
    checar("MediaPlayer tem _sincronizar_ipc_mpv",
           "def _sincronizar_ipc_mpv" in fonte)
    checar("o caminho Linux da pausa foi preservado (D-Bus)",
           "dbus" in fonte.lower() and "org.mpris" in fonte)
    checar("_pausar_player usa o IPC no Windows",
           "_eh_windows()" in fonte.split("def _pausar_player")[1][:2000])

    # ── 5b. Aviso quando o player não aceita comando remoto ──────────
    # O NavePro.exe é gerado sem console: um `print` de aviso não chegaria
    # a quem opera. Precisa existir o caminho on_aviso -> status_label.
    sem_ctrl = _extrair_metodo("MediaPlayer", "_sem_controle_remoto")
    explicar = _extrair_metodo("MediaPlayer", "_explicar_sem_controle")
    play_pause = _extrair_metodo("MediaPlayer", "play_pause")

    if _eh_windows():
        obj = type("F", (), {})()
        obj.player_cmd = "mpv"
        obj._ipc = None
        checar("sem mpv conectado → sem controle remoto",
               sem_ctrl(obj) is True)

        obj2 = type("F", (), {})()
        obj2.player_cmd = "vlc"
        obj2._ipc = None
        msg = explicar(obj2)
        checar("com VLC, o aviso diz para trocar o player para mpv",
               "mpv" in msg and "vlc" in msg.lower())
        obj3 = type("F", (), {})()
        obj3.player_cmd = "mpv"
        obj3._ipc = object()  # IPC "conectado"
        checar("com IPC conectado → há controle remoto",
               sem_ctrl(obj3) is False)

    checar("play_pause avisa quando o pause não surte efeito",
           "_avisar_sem_controle_se_precisar()" in
           fonte.split("def play_pause")[1][:1200])

    # O aviso precisa ser visível: _avisar chama on_aviso, e a AppInterface
    # escreve no status_label. Confere que o encadeamento existe.
    fonte_app = _fontes_da_classe("AppInterface")
    checar("AppInterface tem mostrar_aviso", "def mostrar_aviso" in fonte_app)
    checar("AppInterface mostra o aviso no status_label",
           "status_label.config" in
           fonte_app.split("def mostrar_aviso")[1][:1500])
    checar("mostrar_aviso segura o texto contra o atualizar_status",
           "after(" in fonte_app.split("def mostrar_aviso")[1][:1500])
    checar("MediaPlayer avisa via on_aviso (sem console no .exe)",
           "on_aviso" in fonte)

    # ── 6. Posicionamento: coordenadas exatas, sem sair do SO ─────────
    if _eh_windows():
        checar("posicionar_janela_player ignora PID inexistente",
               posicionar_janela_player(0, 1920, 0, 1920, 1080,
                                       tentativas=1) is False)
        # PID vivo sem janela (o proprio python): nao deve levantar, nem travar.
        checar("posicionar_janela_player tolera processo sem janela",
               posicionar_janela_player(os.getpid(), 0, 0, 10, 10,
                                       tentativas=2, intervalo=0.01) is False)
        checar("encerrar_arvore tolera PID inexistente",
               encerrar_arvore(0) is False)
    else:
        checar("fora do Windows, posicionar_janela_player é no-op",
               posicionar_janela_player(1234, 0, 0, 10, 10,
                                       tentativas=1) is False)

    # ── 7. Cliente IPC: não conecta em pipe que não existe ────────────
    cliente = ClienteMpvIpc("\\\\.\\pipe\\navepro-mpv-pipe-inexistente-xyz",
                            timeout_conexao=0.3)
    checar("conectar() em pipe inexistente devolve False",
           cliente.conectar() is False)
    checar("vivo() é False sem conexão", cliente.vivo() is False)
    cliente.fechar()
    cliente.fechar()  # idempotente
    checar("fechar() duas vezes não levanta", cliente.vivo() is False)
    # Sem pipe, comandar() precisa devolver (False, None) em vez de estourar:
    # é o caminho que _sincronizar_ipc_mpv usa quando o mpv já saiu.
    resposta = cliente.comandar(["get_property", "pause"], timeout=0.2)
    checar("comandar() sem pipe devolve (False, None) em vez de estourar",
           resposta == (False, None))
    checar("propriedade() sem pipe devolve None",
           cliente.propriedade("pause", timeout=0.2) is None)
    checar("definir_pausa() sem pipe devolve False",
           cliente.definir_pausa(True, timeout=0.2) is False)
    checar("encerrar() sem pipe devolve False",
           cliente.encerrar(timeout=0.2) is False)

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print()
    if f:
        print(f"X {f} teste(s) falharam.")
        sys.exit(1)
    print("OK todos os testes de player (Windows) passaram.")
