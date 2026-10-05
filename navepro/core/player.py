"""NavePro - Localização e controle de players externos.

Este módulo concentra o que é específico do Windows para tocar mídia no
telão. No Linux nada aqui altera o comportamento: os caminhos Linux e o
controle por D-Bus/MPRIS continuam como estavam em NavePro.py.

1. `localizar_executavel` - além do PATH, procura o programa nos diretórios
   padrão de instalação do Windows. Sem isso, um VLC instalado em
   "C:\\Program Files\\VideoLAN\\VLC\\vlc.exe" (que normalmente NÃO está no
   PATH) é julgado inexistente, e o NavePro cai no "aplicativo padrão do
   sistema" - que é justamente o player que não aceita comandos.

2. `ClienteMpvIpc` - canal de controle do mpv. No Linux o NavePro controla o
   player por D-Bus/MPRIS; no Windows o equivalente é o `--input-ipc-server`
   do mpv, que em Windows é um *named pipe* (`\\\\.\\pipe\\nome`). Protocolo
   JSON linha a linha, igual ao unix socket. Usa só stdlib + ctypes, sem
   nenhuma dependência nova.

3. `encerrar_arvore` - no Windows não existe grupo de processos (o
   `os.killpg` do Linux), então `taskkill /T /F` é o equivalente: mata o
   player e todos os filhos dele.

Tudo é importável em qualquer sistema operacional: as partes de Windows só
rodam dentro de funções protegidas por `_eh_windows()`.
"""

import ctypes
import ctypes.wintypes as wt
import glob
import json
import os
import shutil
import time
from typing import Optional

from navepro.core.ambiente import _eh_windows

# Nomes de programa que o NavePro pode precisar localizar no Windows, com os
# caminhos relativos de instalação padrão de cada um. A sintaxe é a do
# Windows (%VAR%), que é a que o os.path.expandvars entende nesta plataforma.
_CANDIDATOS_WINDOWS: dict[str, tuple[str, ...]] = {
    "mpv": (
        r"%WinGet%\Packages\*\mpv.exe",
        r"%WinGet%\Links\mpv.exe",
        r"%LocalAppData%\Programs\mpv\mpv.exe",
        r"%ProgramFiles%\mpv\mpv.exe",
    ),
    "vlc": (
        r"%ProgramFiles%\VideoLAN\VLC\vlc.exe",
        r"%ProgramFilesX86%\VideoLAN\VLC\vlc.exe",
        r"%LocalAppData%\Programs\VideoLAN\VLC\vlc.exe",
    ),
    "smplayer": (
        r"%ProgramFiles%\SMPlayer\SMPlayer.exe",
        r"%ProgramFilesX86%\SMPlayer\SMPlayer.exe",
    ),
    "mpc-hc": (
        r"%ProgramFiles%\MPC-HC\mpc-hc.exe",
        r"%ProgramFilesX86%\MPC-HC\mpc-hc.exe",
        r"%ProgramFiles%\ClassiC Lite\mpc-hc.exe",
    ),
    "mpc": (
        r"%ProgramFiles%\MPC-HC\mpc.exe",
        r"%ProgramFilesX86%\MPC-HC\mpc.exe",
    ),
}

# Caminhos absolutos do Linux, mantidos exatamente como o NavePro já usava.
_CAMINHOS_LINUX: tuple[str, ...] = ("/usr/bin", "/usr/local/bin",
                                    "/run/host/usr/bin")

# Cache de resoluções: localizar executável custa alguns stat() no disco e o
# NavePro pergunta várias vezes por faixa. Valores: nome -> caminho ou None.
_CACHE_EXECUTAVEIS: dict[str, Optional[str]] = {}


def _variaveis_windows() -> dict[str, str]:
    """Expande as variáveis de ambiente usadas nos caminhos de instalação."""
    env = os.environ.copy()
    env.setdefault("WinGet",
                   os.path.join(env.get("LOCALAPPDATA", ""),
                                "Microsoft", "WinGet"))
    env.setdefault("ProgramFilesX86",
                   env.get("ProgramFiles", "C:\\Program Files (x86)"))
    return env


def _trocar_wrapper_console(caminho: str) -> str:
    """Se o PATH devolveu o wrapper `.com`, prefere o `.exe` de verdade.

    Instaladores Windows costumam expor um `programa.com` (versão console) ao
    lado do `programa.exe` (versão janela). Quando o NavePro roda a partir de
    um .exe sem console, o wrapper não é necessário - e o .exe evita a
    janela preta piscando. Só Windows; no Linux não há extensão.
    """
    if not _eh_windows() or not caminho.lower().endswith(".com"):
        return caminho
    irmao = caminho[:-4] + ".exe"
    if os.path.isfile(irmao):
        return irmao
    return caminho


def _expandir_padrao(relativo: str, env: dict[str, str]) -> str:
    """Substitui %VAR% usando o dicionário `env`.

    Não dá para usar o os.path.expandvars aqui: ele lê o os.environ do
    processo, e o WinGet/LOCALAPPDATA podem ter sido resolvidos por nós (o
    instalador mudou o PATH depois que o NavePro subiu).
    """
    resultado = relativo
    while True:
        inicio = resultado.find("%")
        if inicio < 0:
            return resultado
        fim = resultado.find("%", inicio + 1)
        if fim < 0:
            return resultado
        nome = resultado[inicio + 1:fim]
        if not nome:
            return resultado
        valor = None
        for chave, conteudo in env.items():
            if chave.upper() == nome.upper():
                valor = conteudo
                break
        if valor is None:
            return resultado
        resultado = resultado[:inicio] + valor + resultado[fim + 1:]


def _candidatos_windows(nome: str) -> list[str]:
    """Lista os caminhos absolutos onde `nome` costuma estar no Windows."""
    env = _variaveis_windows()
    exe = nome if nome.lower().endswith(".exe") else nome + ".exe"
    base = exe[:-4] if exe.lower().endswith(".exe") else exe
    chave = nome.lower()
    if chave not in _CANDIDATOS_WINDOWS:
        chave = base.lower()
    relatorios = _CANDIDATOS_WINDOWS.get(chave, ())
    achados: list[str] = []
    for relativo in relatorios:
        expandido = _expandir_padrao(relativo, env)
        if any(ch in expandido for ch in "*?"):
            for item in sorted(glob.glob(expandido)):
                if os.path.isfile(item):
                    achados.append(_trocar_wrapper_console(item))
        elif os.path.isfile(expandido):
            achados.append(_trocar_wrapper_console(expandido))
    return achados


def localizar_executavel(nome: str) -> Optional[str]:
    """Devolve o caminho completo de um programa, ou None se não achar.

    Ordem: cache, PATH, caminhos de instalação padrão do SO. No Windows isso
    inclui o WinGet, o scoop e o Chocolatey, porque é comum o programa
    funcionar e ainda assim não estar no PATH do processo.
    """
    if not nome:
        return None
    if nome in _CACHE_EXECUTAVEIS:
        return _CACHE_EXECUTAVEIS[nome]

    achado: Optional[str] = None

    # 1. PATH do processo (inclui o .exe implícito do Windows).
    via_path = shutil.which(nome)
    if via_path:
        achado = _trocar_wrapper_console(via_path)

    # 2. Caminhos absolutos de instalação.
    if achado is None and _eh_windows():
        for candidato in _candidatos_windows(nome):
            achado = candidato
            break

    # 3. Caminhos absolutos do Linux (AppImage/sandbox usem /run/host/usr/bin).
    if achado is None:
        for pasta in _CAMINHOS_LINUX:
            completo = os.path.join(pasta, nome)
            if os.path.exists(completo) and os.access(completo, os.X_OK):
                achado = completo
                break

    _CACHE_EXECUTAVEIS[nome] = achado
    return achado


def limpar_cache_executaveis() -> None:
    """Esquece os caminhos já localizados (usado se o PATH mudar em runtime)."""
    _CACHE_EXECUTAVEIS.clear()


def encerrar_arvore(pid: int, timeout: float = 3.0) -> bool:
    """Encerra o processo `pid` e todos os filhos dele.

    Equivalente Windows do `os.killpg` que o Linux usa. Sem o `/T`, um player
    que lance um processo auxiliar sobrevive ao `terminate()` e continua
    tocando no telão.
    """
    if not _eh_windows() or not pid:
        return False
    import subprocess
    try:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True, timeout=timeout,
        )
        return True
    except Exception:
        return False


class ClienteMpvIpc:
    """Cliente do IPC JSON do mpv, via named pipe do Windows.

    espelha o que o Linux faz com D-Bus/MPRIS: `definir_pausa` responde ao
    botão ⏯ / tecla espaço, `propriedade('time-pos')` alimenta o tempo
    decorrido e `propriedade('duration')` a barra de progresso.

    Uma instância por reprodução. Se o mpv não estiver com
    `--input-ipc-server`, `conectar()` devolve False e o NavePro segue
    funcionando só com o estado interno.
    """

    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _OPEN_EXISTING = 3
    _INVALID_HANDLE = ctypes.c_void_p(-1).value

    def __init__(self, caminho_pipe: str, timeout_conexao: float = 6.0) -> None:
        self.caminho_pipe = caminho_pipe
        self.timeout_conexao = timeout_conexao
        self._handle = None
        self._req_id = 0
        self._k32 = None

    # ── infra ctypes ──────────────────────────────────────────────
    def _kernel32(self):
        """Carrega o kernel32 já com os protótipos certainados.

        Sem os argtypes o ctypes converte o HANDLE para int e estoura
        OverflowError em 64 bits - foi o que quebrou o primeiro teste.
        """
        if self._k32 is None:
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD,
                                      wt.LPVOID, wt.DWORD, wt.DWORD,
                                      wt.HANDLE]
            k.CreateFileW.restype = wt.HANDLE
            k.ReadFile.argtypes = [wt.HANDLE, wt.LPVOID, wt.DWORD,
                                   ctypes.POINTER(wt.DWORD), wt.LPVOID]
            k.WriteFile.argtypes = [wt.HANDLE, wt.LPCVOID, wt.DWORD,
                                    ctypes.POINTER(wt.DWORD), wt.LPVOID]
            k.PeekNamedPipe.argtypes = [wt.HANDLE, wt.LPVOID, wt.DWORD,
                                        wt.LPVOID, ctypes.POINTER(wt.DWORD),
                                        wt.LPVOID]
            k.CloseHandle.argtypes = [wt.HANDLE]
            k.FlushFileBuffers.argtypes = [wt.HANDLE]
            k.WaitNamedPipeW.argtypes = [wt.LPCWSTR, wt.DWORD]
            self._k32 = k
        return self._k32

    # ── ciclo de vida ─────────────────────────────────────────────
    def conectar(self) -> bool:
        """Abre o pipe, aguardando o mpv criar o servidor.

        O mpv cria o named pipe pouco depois de subir; por isso há espera com
        `WaitNamedPipeW` em vez de uma conexão seca.
        """
        k = self._kernel32()
        limite = time.monotonic() + self.timeout_conexao
        while time.monotonic() < limite:
            try:
                k.WaitNamedPipeW(self.caminho_pipe, 250)
            except OSError:
                pass
            handle = k.CreateFileW(
                self.caminho_pipe,
                self._GENERIC_READ | self._GENERIC_WRITE,
                0, None, self._OPEN_EXISTING, 0, None,
            )
            if handle and handle != self._INVALID_HANDLE:
                self._handle = handle
                return True
            time.sleep(0.1)
        return False

    def vivo(self) -> bool:
        """True se há um pipe conectado (o cliente está utilizável).

        Não confirma se o mpv continua tocando - para isso use a propriedade
        'pause' ou o poll() do processo, que é a fonte de verdade do fim de
        faixa.
        """
        return self._handle is not None

    def fechar(self) -> None:
        """Fecha o handle do pipe. Seguro chamar várias vezes."""
        if self._handle is not None:
            try:
                self._kernel32().CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None

    # ── leitura/escrita ───────────────────────────────────────────
    def _ler_linha(self, limite: float) -> Optional[str]:
        """Lê UMA linha JSON, ou None se o pipe fechou / estourou o prazo.

        Usa PeekNamedPipe em vez de ReadFile direto: ReadFile num named pipe
        síncrono bloqueia para sempre se o mpv não responder, e isto roda na
        thread do Tk — travar aqui trava a interface inteira.
        """
        k = self._kernel32()
        while time.monotonic() < limite:
            disponivel = wt.DWORD(0)
            ok = k.PeekNamedPipe(self._handle, None, 0, None,
                                 ctypes.byref(disponivel), None)
            if not ok or disponivel.value == 0:
                # 0 bytes com pipe vivo = nada aind; pipe morto = erro.
                if not ok:
                    return None
                time.sleep(0.005)
                continue
            buffer = ctypes.create_string_buffer(disponivel.value)
            lidos = wt.DWORD(0)
            if not k.ReadFile(self._handle, buffer, disponivel.value,
                              ctypes.byref(lidos), None) or not lidos.value:
                return None
            return buffer.raw[:lidos.value].decode("utf-8", "replace")
        return None

    def _escrever(self, texto: str) -> bool:
        k = self._kernel32()
        dados = texto.encode("utf-8")
        escritos = wt.DWORD(0)
        if not k.WriteFile(self._handle, dados, len(dados),
                           ctypes.byref(escritos), None):
            return False
        k.FlushFileBuffers(self._handle)
        return True

    def comandar(self, comando: list, timeout: float = 3.0):
        """Envia um comando JSON ao mpv e devolve (ok, dados).

        O mpv entrelaça eventos (`{"event": ...}`) entre as respostas, então
        as linhas são filtradas pelo `request_id` até achar a resposta certa.
        """
        if self._handle is None:
            return False, None
        self._req_id += 1
        meu_id = self._req_id
        carga = json.dumps({"command": list(comando),
                            "request_id": meu_id}) + "\n"
        try:
            if not self._escrever(carga):
                return False, None
        except Exception:
            return False, None

        limite = time.monotonic() + timeout
        while True:
            linha = self._ler_linha(limite)
            if linha is None:
                return False, None
            for pedaco in linha.splitlines():
                pedaco = pedaco.strip()
                if not pedaco:
                    continue
                try:
                    mensagem = json.loads(pedaco)
                except (ValueError, TypeError):
                    continue
                if mensagem.get("request_id") != meu_id:
                    continue  # evento do mpv, ignora
                if mensagem.get("error") == "success":
                    return True, mensagem.get("data")
                return False, mensagem.get("error")

    # ── atalhos de uso ────────────────────────────────────────────
    def propriedade(self, nome: str, timeout: float = 2.0):
        """Lê uma propriedade do mpv (ex.: 'time-pos', 'duration', 'pause')."""
        ok, dados = self.comandar(["get_property", nome], timeout=timeout)
        return dados if ok else None

    def definir_pausa(self, pausado: bool, timeout: float = 3.0) -> bool:
        """Pausa (True) ou continua (False). É o equivalente ao PlayPause."""
        ok, _ = self.comandar(["set_property", "pause", bool(pausado)],
                              timeout=timeout)
        return ok

    def encerrar(self, timeout: float = 3.0) -> bool:
        """Pede o fim da reprodução (`quit`). O mpv sai e o pipe fecha."""
        ok, _ = self.comandar(["quit"], timeout=timeout)
        return ok


def nome_pipe_mpv(indice: int) -> str:
    """Gera um nome de named pipe único por reprodução.

    Inclui o PID do NavePro e um contador: se o pipe anterior ainda existir
    (mpv demorando a morrer), o novo mpv não herda a conversa velha.
    """
    return f"\\\\.\\pipe\\navepro-mpv-{os.getpid()}-{indice}"


# ── Posicionamento da janela do player ─────────────────────────────
# Constantes Win32 usadas por posicionar_janela_player.
_GWL_STYLE = -16
_GWL_EXSTYLE = -20
_WS_POPUP = 0x80000000
_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_WS_DLGFRAME = 0x00080000
_WS_EX_APPWINDOW = 0x00040000
_SWP_FRAMECHANGED = 0x0020
_SWP_SHOWWINDOW = 0x0040
_HWND_TOPMOST = -1


def _user32():
    """Carrega o user32 com os protótipos certainados (HANDLE em 64 bits)."""
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.SetWindowLongW.restype = ctypes.c_long
    u.GetWindowLongW.restype = ctypes.c_long
    u.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_long]
    u.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
    u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, wt.UINT]
    u.SetWindowPos.restype = wt.BOOL
    u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    u.IsWindowVisible.argtypes = [wt.HWND]
    u.IsIconic.argtypes = [wt.HWND]
    u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    return u


def _janela_do_processo(u, pid: int) -> Optional[int]:
    """HWND da janela visível principal do processo `pid`, se houver.

    O EnumWindows passa por janelas auxiliares do próprio processo (IME,
    SMTC, ícones invisíveis), então filtra por visível + título com "mpv"
    ou o nome do arquivo - o que sobra é a janela de vídeo.
    """
    candidatas: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def _cb(hwnd, _lparam):
        dono = wt.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(dono))
        if dono.value == pid and u.IsWindowVisible(hwnd):
            tamanho = u.GetWindowTextLengthW(hwnd)
            if tamanho:
                buffer = ctypes.create_unicode_buffer(tamanho + 1)
                u.GetWindowTextW(hwnd, buffer, tamanho + 1)
                titulo = buffer.value
                if "IME" not in titulo:
                    candidatas.append((hwnd, titulo))
        return True

    u.EnumWindows(_cb, 0)
    if not candidatas:
        return None
    # A janela de vídeo é a de maior área — as auxiliares são 0x0 ou minúsculas.
    melhor = None
    melhor_area = -1
    for hwnd, _titulo in candidatas:
        r = wt.RECT()
        if not u.GetWindowRect(hwnd, ctypes.byref(r)):
            continue
        area = (r.right - r.left) * (r.bottom - r.top)
        if area > melhor_area:
            melhor_area, melhor = area, hwnd
    return melhor


def posicionar_janela_player(
    pid: int, x: int, y: int, largura: int, altura: int,
    tentativas: int = 40, intervalo: float = 0.1, topo: bool = True,
) -> bool:
    """Coloca a janela do player cobrindo exatamente o monitor do telão.

    POR QUE NÃO USAR O `--fullscreen` DO PLAYER
    Medido neste Windows: mpv 0.41 ignora `--screen` (0, 1 e 2 dão sempre o
    monitor primário) e ignora `--geometry` quando está em tela cheia — vai
    para (0,0) do jeito que for. O Tk do telão tem o mesmo defeito. Então o
    player é aberto NORMAL e a janela é colocada por aqui.

    Janela sem moldura (`WS_POPUP` + `WS_EX_APPWINDOW`) e em cima das outras,
    para o telão ficar limpo e o vídeo não ser interrompido por clique.

    Repete algumas vezes porque o player se reposiciona quando carrega o
    arquivo, logo depois de aparecer a janela. Se nãoouver janela visível
    (arquivo só de áudio, ou player que não abre janela), devolve False e o
    NavePro segue normalmente.
    """
    if not _eh_windows() or not pid:
        return False
    try:
        u = _user32()
    except Exception:
        return False

    alvo = (int(x), int(y), int(largura), int(altura))
    for _ in range(max(1, tentativas)):
        hwnd = _janela_do_processo(u, pid)
        if hwnd:
            try:
                estilo = u.GetWindowLongW(hwnd, _GWL_STYLE)
                novo = ((estilo & ~(_WS_CAPTION | _WS_THICKFRAME | _WS_DLGFRAME))
                        | _WS_POPUP)
                u.SetWindowLongW(hwnd, _GWL_STYLE, novo)
                ex = u.GetWindowLongW(hwnd, _GWL_EXSTYLE)
                u.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex | _WS_EX_APPWINDOW)
                u.SetWindowPos(hwnd, _HWND_TOPMOST if topo else -2,
                               alvo[0], alvo[1], alvo[2], alvo[3],
                               _SWP_FRAMECHANGED | _SWP_SHOWWINDOW)
                if u.IsIconic(hwnd):
                    u.ShowWindow(hwnd, 5)  # SW_SHOW
                r = wt.RECT()
                if u.GetWindowRect(hwnd, ctypes.byref(r)):
                    if (r.left, r.top, r.right - r.left, r.bottom - r.top) == alvo:
                        return True
            except Exception:
                return False
        time.sleep(intervalo)
    return False

