"""NavePro - Devolver o foco à apresentação em curso.

Durante um PowerPoint/Impress em modo de apresentação, o operador pode
projetar versículos bíblicos pelo NavePro. Ao clicar no painel, o foco do
Windows/X11 sai da apresentação; quando a projeção termina, a apresentação
continua aberta, porém sem receber as teclas do controle/passador.

Este módulo resolve isso sem depender de clique do operador:

1. Ao abrir a apresentação, o processo é registrado e uma thread captura a
   janela do modo apresentação assim que ela aparece (o PowerPoint pode
   reutilizar uma instância já aberta, então o PID do lançamento nem sempre
   é o dono da janela).
2. Ao fim de uma projeção (Esc, último versículo ou retorno automático), o
   telão chama `_focar_apresentacao`, que traz essa janela de volta ao
   primeiro plano.

No Windows usa a API Win32 (`screenClass` identifica o slide show do
PowerPoint). No Linux usa Xlib/X11 e o título/arquivo da apresentação, com
suporte ao mesmo caminho dentro do Flatpak (a janela pertence ao processo do
host, mas continua visível no XWayland).
"""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import os
import sys
import time
import unicodedata

# Executáveis que hospedam o modo apresentação. O PowerPoint continua sendo
# `POWERPNT.EXE` mesmo quando a janela do slide show é criada pela instância
# já aberta; o LibreOffice pode aparecer como soffice.bin/soffice.
_PROCESSOS_APRESENTACAO = frozenset({
    "powerpnt", "powerpnt.exe", "wpp", "wpp.exe",
    "soffice", "soffice.exe", "soffice.bin",
    "libreoffice", "libreoffice.exe", "simpress", "simpress.exe",
})

# Marcas no título usadas quando o nome do arquivo não aparece (títulos de
# janela variam com a versão/idioma do Office e do LibreOffice).
_MARCAS_TITULO = (
    "slide show", "slideshow", "apresentação de slides",
    "apresentacao de slides", "presenting:", "apresentando:",
)

# Janelas de controle do LibreOffice (Presenter Console / console do
# apresentador). Nunca são a apresentação em si; a pontuação é reduzida
# para que a captura não confunda as duas quando ambas ficam em tela cheia.
_MARCAS_CONTROLE = (
    "presenter console", "console do apresentador",
    "console de apresentador", "apresentador (console)",
)

_TITULOS_NAVEPRO = ("nave pro - pro", "telão", "telao")

# Pontuação mínima para aceitar uma janela como slide show. Um editor do
# Office aberto com o mesmo arquivo chega a 100 (nome no título); só a
# janela em tela cheia/`screenClass` alcança 120+. Evita capturar o editor
# antes de o modo de apresentação aparecer.
_PONTUACAO_MINIMA_CAPTURA = 120


def _normalizar(texto: str | None) -> str:
    """Minúsculas e sem acentos, para comparar títulos das janelas."""
    decomposto = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return sem_acento.casefold().strip()


def _nome_arquivo(caminho: str | None) -> str:
    """Nome do arquivo sem extensão, normalizado (ex.: 'Culto Domingo')."""
    nome = (caminho or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = os.path.splitext(nome)[0]
    return _normalizar(base)


def _pontuar_janela(janela: dict, alvo: dict) -> int:
    """Pontua uma janela candidata a ser a apresentação em curso.

    Devolve -1 quando não há indício nenhum de que a janela seja a
    apresentação. Títulos do próprio NavePro são descartados para nunca
    devolver o foco ao painel/telão.
    """
    titulo = _normalizar(janela.get("titulo"))
    processo = _normalizar(os.path.basename(janela.get("processo") or ""))
    classe = _normalizar(janela.get("classe"))
    nome = _nome_arquivo(alvo.get("caminho"))

    if titulo in _TITULOS_NAVEPRO or processo.startswith("navepro"):
        return -1

    pontos = -1
    # `screenClass` é a janela do slide show do PowerPoint no Windows —
    # o indício mais forte e imune a título localizado.
    if classe == "screenclass":
        pontos = max(pontos, 120)
    if nome and len(nome) >= 3 and nome in titulo:
        pontos = max(pontos, 100)
    if any(marca in titulo for marca in _MARCAS_TITULO):
        pontos = max(pontos, 60)
    if processo in _PROCESSOS_APRESENTACAO:
        pontos = max(pontos, 50)
    if pontos < 0:
        return -1
    # O console do apresentador também fica em tela cheia sobre o telão e
    # pode exibir o nome do arquivo; nunca deve ser escolhido como slide show.
    if any(marca in titulo for marca in _MARCAS_CONTROLE):
        pontos -= 80

    # Janela em tela cheia sobre o monitor do telão é quase certamente o
    # slide show (e não o editor do Office, que fica no monitor do operador).
    monitor = alvo.get("monitor")
    largura = int(janela.get("largura") or 0)
    altura = int(janela.get("altura") or 0)
    if monitor and largura > 0 and altura > 0:
        _mx, _my, mw, mh = monitor
        tolerancia_w = max(8, int(mw * 0.02))
        tolerancia_h = max(8, int(mh * 0.02))
        if abs(largura - mw) <= tolerancia_w and abs(altura - mh) <= tolerancia_h:
            pontos += 20
            x = int(janela.get("x") or 0)
            y = int(janela.get("y") or 0)
            if abs(x - _mx) <= tolerancia_w and abs(y - _my) <= tolerancia_h:
                pontos += 10

    if alvo.get("pid") and janela.get("pid") == alvo.get("pid"):
        pontos += 5
    return pontos


def _escolher_janela(candidatas: list[dict], alvo: dict) -> dict | None:
    """Escolhe a melhor candidata (maior pontuação; área como desempate)."""
    melhor: dict | None = None
    melhor_chave = (-1, -1)
    for janela in candidatas:
        largura = int(janela.get("largura") or 0)
        altura = int(janela.get("altura") or 0)
        if largura <= 0 or altura <= 0:
            continue
        pontos = _pontuar_janela(janela, alvo)
        chave = (pontos, largura * altura)
        if pontos >= 0 and chave > melhor_chave:
            melhor, melhor_chave = janela, chave
    return melhor


def _parece_apresentacao(janela: dict | None, alvo: dict) -> bool:
    """True se a janela tem indícios suficientes de ser o slide show."""
    return bool(janela) and (
        _pontuar_janela(janela, alvo) >= _PONTUACAO_MINIMA_CAPTURA)


def _criar_alvo_apresentacao(
    caminho: str, pid: int | None = None, monitor: tuple | None = None,
    monitor_painel: tuple | None = None,
) -> dict:
    """Estado do foco de uma apresentação recém-aberta.

    `monitor` é a geometria (x, y, largura, altura) do telão e
    `monitor_painel` a do monitor do operador. O segundo é usado para
    reposicionar a janela de controle do Impress quando o aplicativo abre
    as duas janelas no telão.
    """
    return {
        "caminho": caminho or "",
        "pid": pid,
        "monitor": monitor,
        "monitor_painel": monitor_painel,
        "janela": None,
        "capturado": False,
        "cancelado": False,
    }


# ── Windows ──────────────────────────────────────────────────────────
def _localizar_windows(alvo: dict) -> dict | None:
    """Procura a janela do slide show entre as janelas visíveis do Windows."""
    import ctypes.wintypes as wt

    try:
        u = ctypes.WinDLL("user32", use_last_error=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError:
        return None

    u.GetWindowTextLengthW.argtypes = [wt.HWND]
    u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    u.IsWindowVisible.argtypes = [wt.HWND]
    u.GetWindowThreadProcessId.argtypes = [wt.HWND,
                                           ctypes.POINTER(wt.DWORD)]
    k.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k.OpenProcess.restype = wt.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [
        wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    k.CloseHandle.argtypes = [wt.HANDLE]

    cache: dict[int, str] = {}

    def _processo(pid: int) -> str:
        if pid in cache:
            return cache[pid]
        nome = ""
        handle = k.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if handle:
            try:
                buffer = ctypes.create_unicode_buffer(1024)
                tamanho = wt.DWORD(len(buffer))
                if k.QueryFullProcessImageNameW(
                        handle, 0, buffer, ctypes.byref(tamanho)):
                    nome = os.path.basename(buffer.value)
            finally:
                k.CloseHandle(handle)
        cache[pid] = nome
        return nome

    candidatas: list[dict] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def _cb(hwnd, _lparam):
        if not u.IsWindowVisible(hwnd):
            return True
        pid = wt.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        tamanho = u.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(tamanho + 1)
        u.GetWindowTextW(hwnd, buffer, tamanho + 1)
        classe = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, classe, 256)
        rect = wt.RECT()
        if not u.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        candidatas.append({
            "id": int(hwnd),
            "pid": int(pid.value),
            "titulo": buffer.value,
            "classe": classe.value,
            "processo": _processo(int(pid.value)),
            "x": int(rect.left),
            "y": int(rect.top),
            "largura": int(rect.right - rect.left),
            "altura": int(rect.bottom - rect.top),
        })
        return True

    u.EnumWindows(_cb, 0)
    return _escolher_janela(candidatas, alvo)


def _janela_viva_windows(janela_id: int) -> bool:
    try:
        import ctypes.wintypes as wt
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.IsWindow.argtypes = [wt.HWND]
        return bool(u.IsWindow(janela_id))
    except Exception:
        return False


def _trazer_foco_windows(janela_id: int) -> bool:
    """Coloca a janela em primeiro plano (com o contorno de foreground)."""
    try:
        import ctypes.wintypes as wt
        u = ctypes.WinDLL("user32", use_last_error=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError:
        return False

    u.SetForegroundWindow.argtypes = [wt.HWND]
    u.SetForegroundWindow.restype = wt.BOOL
    u.BringWindowToTop.argtypes = [wt.HWND]
    u.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    u.IsIconic.argtypes = [wt.HWND]
    u.GetForegroundWindow.restype = wt.HWND
    u.GetWindowThreadProcessId.argtypes = [wt.HWND,
                                           ctypes.POINTER(wt.DWORD)]
    u.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
    k.GetCurrentThreadId.restype = wt.DWORD

    if u.IsIconic(janela_id):
        u.ShowWindow(janela_id, 9)  # SW_RESTORE
    u.ShowWindow(janela_id, 5)      # SW_SHOW
    u.BringWindowToTop(janela_id)
    if u.SetForegroundWindow(janela_id):
        return True

    # O Windows limita SetForegroundWindow para o processo em primeiro
    # plano. Anexar a entrada do processo atual à do foreground remove essa
    # restrição enquanto a chamada é feita.
    try:
        atual = k.GetCurrentThreadId()
        frente = u.GetForegroundWindow()
        thread_frente = u.GetWindowThreadProcessId(frente, None) if frente else 0
        if thread_frente and thread_frente != atual:
            if u.AttachThreadInput(atual, thread_frente, True):
                ok = bool(u.SetForegroundWindow(janela_id))
                u.AttachThreadInput(atual, thread_frente, False)
                if ok:
                    return True
    except Exception:
        pass
    return bool(u.SetForegroundWindow(janela_id))


# ── Linux/X11 ────────────────────────────────────────────────────────
class _XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int), ("y", ctypes.c_int),
        ("width", ctypes.c_int), ("height", ctypes.c_int),
        ("border_width", ctypes.c_int), ("depth", ctypes.c_int),
        ("visual", ctypes.c_void_p), ("root", ctypes.c_ulong),
        ("classe", ctypes.c_int), ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong),
        ("backing_pixel", ctypes.c_ulong), ("save_under", ctypes.c_int),
        ("colormap", ctypes.c_ulong), ("map_installed", ctypes.c_int),
        ("map_state", ctypes.c_int), ("all_event_masks", ctypes.c_long),
        ("your_event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p),
    ]


class _XClassHint(ctypes.Structure):
    _fields_ = [("res_name", ctypes.c_void_p),
                ("res_class", ctypes.c_void_p)]


class _XClientMessageData(ctypes.Union):
    _fields_ = [("b", ctypes.c_char * 20), ("s", ctypes.c_short * 10),
                ("l", ctypes.c_long * 5)]


class _XClientMessageEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int), ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int), ("data", _XClientMessageData),
    ]


class _XEvent(ctypes.Union):
    _fields_ = [("type", ctypes.c_int),
                ("xclient", _XClientMessageEvent),
                ("pad", ctypes.c_long * 24)]


class _XErrorEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int), ("display", ctypes.c_void_p),
        ("resourceid", ctypes.c_ulong), ("serial", ctypes.c_ulong),
        ("error_code", ctypes.c_ubyte), ("request_code", ctypes.c_ubyte),
        ("minor_code", ctypes.c_ubyte),
    ]


_XErrorHandler = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(_XErrorEvent))


@_XErrorHandler
def _ignorar_erro_x11(_display, _evento):
    """Ignora erros X11 previsíveis (janela destruída durante a varredura).

    O handler padrão do Xlib encerra o processo em qualquer erro não tratado.
    Durante a enumeração de janelas, o LibreOffice pode destruir/recriar a
    janela entre `XQueryTree` e `XGetWindowAttributes` — o que derrubava o
    NavePro inteiro com `BadWindow`.
    """
    return 0


@contextlib.contextmanager
def _silenciar_erros_x11(lib, display):
    """Troca temporariamente o handler de erros X11 e restaura ao final."""
    anterior = lib.XSetErrorHandler(
        ctypes.cast(_ignorar_erro_x11, ctypes.c_void_p))
    try:
        yield
    finally:
        # Drena os erros pendentes ainda com o handler tolerante ativo;
        # senão um BadWindow pode chegar depois e derrubar o processo.
        try:
            lib.XSync(display, False)
        finally:
            lib.XSetErrorHandler(anterior)


_XLIB = None
_XLIB_TENTOU = False


def _xlib():
    """Carrega a libX11 uma única vez (None se não houver X11)."""
    global _XLIB, _XLIB_TENTOU
    if _XLIB_TENTOU:
        return _XLIB
    _XLIB_TENTOU = True
    try:
        lib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
    except OSError:
        return None

    lib.XOpenDisplay.restype = ctypes.c_void_p
    lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    lib.XDefaultRootWindow.restype = ctypes.c_ulong
    lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    lib.XInternAtom.restype = ctypes.c_ulong
    lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                ctypes.c_int]
    lib.XGetWindowProperty.restype = ctypes.c_int
    lib.XGetWindowProperty.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long,
        ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    lib.XQueryTree.restype = ctypes.c_int
    lib.XQueryTree.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
        ctypes.POINTER(ctypes.c_uint),
    ]
    lib.XGetWindowAttributes.restype = ctypes.c_int
    lib.XGetWindowAttributes.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(_XWindowAttributes)]
    lib.XFetchName.restype = ctypes.c_int
    lib.XFetchName.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_char_p)]
    lib.XGetClassHint.restype = ctypes.c_int
    lib.XGetClassHint.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_XClassHint)]
    lib.XFree.argtypes = [ctypes.c_void_p]
    lib.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    lib.XSetInputFocus.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    lib.XSendEvent.restype = ctypes.c_int
    lib.XSendEvent.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long,
        ctypes.POINTER(_XEvent)]
    lib.XMoveResizeWindow.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
        ctypes.c_uint, ctypes.c_uint]
    lib.XFlush.argtypes = [ctypes.c_void_p]
    lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.XSetErrorHandler.restype = ctypes.c_void_p
    lib.XSetErrorHandler.argtypes = [ctypes.c_void_p]
    _XLIB = lib
    return _XLIB


def _x11_prop(display, janela: int, atom: int, tipo: int,
              limite: int = 1024) -> tuple[bytes, list[int]]:
    """Lê uma propriedade X11 e devolve (bytes, valores de formato 32)."""
    lib = _XLIB
    tipo_real = ctypes.c_ulong()
    formato = ctypes.c_int()
    itens = ctypes.c_ulong()
    restantes = ctypes.c_ulong()
    dados = ctypes.c_void_p()
    status = lib.XGetWindowProperty(
        display, janela, atom, 0, limite, False, tipo,
        ctypes.byref(tipo_real), ctypes.byref(formato),
        ctypes.byref(itens), ctypes.byref(restantes), ctypes.byref(dados))
    if status != 0 or not dados.value:
        return b"", []
    try:
        if formato.value == 8:
            return ctypes.string_at(dados, itens.value), []
        if formato.value == 32:
            valores = ctypes.cast(dados, ctypes.POINTER(ctypes.c_long))
            return b"", [int(valores[i]) for i in range(itens.value)]
    finally:
        lib.XFree(dados)
    return b"", []


def _x11_texto(display, janela: int) -> str:
    atom_nome = _XLIB.XInternAtom(display, b"_NET_WM_NAME", False)
    atom_utf8 = _XLIB.XInternAtom(display, b"UTF8_STRING", False)
    dados, _ = _x11_prop(display, janela, atom_nome, atom_utf8, 1024)
    if dados:
        return dados.decode("utf-8", "replace")
    nome = ctypes.c_char_p()
    if _XLIB.XFetchName(display, janela, ctypes.byref(nome)) and nome.value:
        texto = nome.value.decode("utf-8", "replace")
        _XLIB.XFree(nome)
        return texto
    return ""


def _x11_pid(display, janela: int) -> int:
    atom_pid = _XLIB.XInternAtom(display, b"_NET_WM_PID", False)
    atom_cardinal = _XLIB.XInternAtom(display, b"CARDINAL", False)
    _, valores = _x11_prop(display, janela, atom_pid, atom_cardinal, 1)
    return valores[0] if valores else 0


def _x11_classe(display, janela: int) -> str:
    hint = _XClassHint()
    if not _XLIB.XGetClassHint(display, janela, ctypes.byref(hint)):
        return ""
    partes = []
    for ponteiro in (hint.res_class, hint.res_name):
        if ponteiro:
            partes.append(ctypes.string_at(ponteiro).decode("utf-8", "replace"))
            _XLIB.XFree(ponteiro)
    return " ".join(partes)


def _x11_processo(pid: int) -> str:
    """Nome do processo via /proc (vazio no sandbox do Flatpak/host)."""
    if not pid:
        return ""
    try:
        with open(f"/proc/{pid}/comm", encoding="utf-8") as arquivo:
            return arquivo.read().strip()
    except OSError:
        return ""


def _varrer_janelas_x11() -> list[dict]:
    """Percorre a árvore X11 e devolve as janelas visíveis com metadados."""
    lib = _xlib()
    if lib is None:
        return []
    display = lib.XOpenDisplay(None)
    if not display:
        return []
    try:
        with _silenciar_erros_x11(lib, display):
            raiz = lib.XDefaultRootWindow(display)
            candidatas: list[dict] = []
            pilha = [(raiz, 0)]
            vistos: set[int] = set()
            while pilha and len(vistos) < 2000:
                janela, nivel = pilha.pop()
                if janela in vistos or nivel > 6:
                    continue
                vistos.add(janela)
                attrs = _XWindowAttributes()
                if lib.XGetWindowAttributes(
                        display, janela, ctypes.byref(attrs)):
                    if attrs.map_state == 2:  # IsViewable
                        titulo = _x11_texto(display, janela)
                        pid = _x11_pid(display, janela)
                        processo = _x11_processo(pid)
                        classe = _x11_classe(display, janela)
                        if titulo or processo:
                            candidatas.append({
                                "id": int(janela),
                                "pid": pid,
                                "titulo": titulo,
                                "classe": classe,
                                "processo": processo,
                                "x": int(attrs.x),
                                "y": int(attrs.y),
                                "largura": int(attrs.width),
                                "altura": int(attrs.height),
                            })
                raiz_ret = ctypes.c_ulong()
                pai = ctypes.c_ulong()
                filhos = ctypes.POINTER(ctypes.c_ulong)()
                total = ctypes.c_uint()
                if lib.XQueryTree(display, janela, ctypes.byref(raiz_ret),
                                  ctypes.byref(pai), ctypes.byref(filhos),
                                  ctypes.byref(total)):
                    for indice in range(total.value):
                        pilha.append((filhos[indice], nivel + 1))
                    if filhos:
                        lib.XFree(filhos)
            return candidatas
    finally:
        lib.XCloseDisplay(display)


def _localizar_x11(alvo: dict) -> dict | None:
    """Escolhe a janela do slide show entre as janelas visíveis do X11."""
    return _escolher_janela(_varrer_janelas_x11(), alvo)


def _janela_viva_x11(janela_id: int) -> bool:
    lib = _xlib()
    if lib is None:
        return False
    display = lib.XOpenDisplay(None)
    if not display:
        return False
    try:
        with _silenciar_erros_x11(lib, display):
            attrs = _XWindowAttributes()
            if not lib.XGetWindowAttributes(
                    display, janela_id, ctypes.byref(attrs)):
                return False
            return attrs.map_state == 2
    finally:
        lib.XCloseDisplay(display)


def _trazer_foco_x11(janela_id: int) -> bool:
    """Ativa a janela via EWMH e reforça com foco/raise direto no X11."""
    lib = _xlib()
    if lib is None:
        return False
    display = lib.XOpenDisplay(None)
    if not display:
        return False
    try:
        with _silenciar_erros_x11(lib, display):
            raiz = lib.XDefaultRootWindow(display)
            atom_ativo = lib.XInternAtom(
                display, b"_NET_ACTIVE_WINDOW", False)
            evento = _XEvent()
            evento.xclient.type = 33  # ClientMessage
            evento.xclient.send_event = 1
            evento.xclient.display = display
            evento.xclient.window = janela_id
            evento.xclient.message_type = atom_ativo
            evento.xclient.format = 32
            evento.xclient.data.l[0] = 2  # veio de um pager/taskbar
            evento.xclient.data.l[1] = 0  # timestamp (CurrentTime)
            evento.xclient.data.l[2] = 0
            mascara = 0x00100000 | 0x00080000  # Redirect | Notify (substr.)
            lib.XSendEvent(
                display, raiz, False, mascara, ctypes.byref(evento))
            lib.XRaiseWindow(display, janela_id)
            lib.XSetInputFocus(display, janela_id, 2, 0)  # RevertToParent
            lib.XFlush(display)
            return True
    finally:
        lib.XCloseDisplay(display)


# ── Posicionamento da janela de controle do Impress ──────────────────
def _janela_dentro_do_monitor(janela: dict, monitor: tuple | None) -> bool:
    """True se o centro da janela cai no monitor informado."""
    if not monitor:
        return False
    mx, my, mw, mh = monitor
    x = int(janela.get("x") or 0) + int(janela.get("largura") or 0) // 2
    y = int(janela.get("y") or 0) + int(janela.get("altura") or 0) // 2
    return mx <= x < mx + mw and my <= y < my + mh


def _janela_ocupa_monitor(janela: dict, monitor: tuple | None) -> bool:
    """True se a janela está em tela cheia sobre o monitor informado."""
    if not monitor:
        return False
    _mx, _my, mw, mh = monitor
    largura = int(janela.get("largura") or 0)
    altura = int(janela.get("altura") or 0)
    tol_w = max(8, int(mw * 0.02))
    tol_h = max(8, int(mh * 0.02))
    return (abs(largura - mw) <= tol_w and abs(altura - mh) <= tol_h)


def _eh_janela_libreoffice(janela: dict) -> bool:
    """True se a janela pertence ao LibreOffice/Impress."""
    processo = _normalizar(os.path.basename(janela.get("processo") or ""))
    classe = _normalizar(janela.get("classe"))
    return any(
        marca in processo or marca in classe
        for marca in ("soffice", "libreoffice", "simpress"))


def _eh_controle_libreoffice(janela: dict, alvo: dict) -> bool:
    """True se a janela é o editor/console de controle, não o slide show."""
    if janela.get("id") == alvo.get("janela"):
        return False
    if not _eh_janela_libreoffice(janela):
        return False
    titulo = _normalizar(janela.get("titulo"))
    nome = _nome_arquivo(alvo.get("caminho"))
    if nome and len(nome) >= 3 and nome in titulo:
        return True
    return any(marca in titulo for marca in _MARCAS_CONTROLE)


def _remover_tela_cheia_x11(lib, display, raiz, janela_id: int) -> None:
    """Pede ao WM para tirar a janela de tela cheia/maximizada antes de mover."""
    atom_state = lib.XInternAtom(display, b"_NET_WM_STATE", False)
    estados = (
        b"_NET_WM_STATE_FULLSCREEN",
        b"_NET_WM_STATE_MAXIMIZED_VERT",
        b"_NET_WM_STATE_MAXIMIZED_HORZ",
    )
    for nome in estados:
        evento = _XEvent()
        evento.xclient.type = 33  # ClientMessage
        evento.xclient.send_event = 1
        evento.xclient.display = display
        evento.xclient.window = janela_id
        evento.xclient.message_type = atom_state
        evento.xclient.format = 32
        evento.xclient.data.l[0] = 0  # _NET_WM_STATE_REMOVE
        evento.xclient.data.l[1] = lib.XInternAtom(display, nome, False)
        evento.xclient.data.l[2] = 0
        evento.xclient.data.l[3] = 2  # pager/taskbar
        mascara = 0x00100000 | 0x00080000  # SubstructureRedirect|Notify
        lib.XSendEvent(
            display, raiz, False, mascara, ctypes.byref(evento))
    lib.XSync(display, False)


def _mover_janela_para_monitor(janela: dict, destino: tuple) -> bool:
    """Move (e redimensiona, se preciso) uma janela para o monitor destino."""
    lib = _xlib()
    if lib is None:
        return False
    display = lib.XOpenDisplay(None)
    if not display:
        return False
    try:
        with _silenciar_erros_x11(lib, display):
            raiz = lib.XDefaultRootWindow(display)
            _remover_tela_cheia_x11(
                lib, display, raiz, int(janela["id"]))
            dx, dy, dw, dh = destino
            largura = int(janela.get("largura") or 0)
            altura = int(janela.get("altura") or 0)
            if largura >= dw * 0.8 and altura >= dh * 0.8:
                # Era tela cheia: ocupa o monitor do operador inteiro.
                x, y, largura, altura = dx, dy, dw, dh
            else:
                largura = min(largura or dw, dw)
                altura = min(altura or dh, dh)
                x = dx + max(0, (dw - largura) // 2)
                y = dy + max(0, (dh - altura) // 2)
            lib.XMoveResizeWindow(
                display, int(janela["id"]), x, y, largura, altura)
            lib.XRaiseWindow(display, int(janela["id"]))
            lib.XFlush(display)
        return True
    except Exception:
        return False
    finally:
        lib.XCloseDisplay(display)


def _reposicionar_janelas_controle(alvo: dict | None) -> int:
    """Versão portátil: no Linux delega para a implementação X11."""
    if not alvo or not sys.platform.startswith("linux"):
        return 0
    return _reposicionar_janelas_controle_linux(alvo)


def _reposicionar_janelas_controle_linux(alvo: dict | None) -> int:
    """Traz a janela de controle do Impress do telão para o monitor do operador.

    O LibreOffice às vezes abre o editor e o console do apresentador no
    mesmo monitor do slide show (principalmente quando o lançamento acontece
    com o telão em primeiro plano). Move só as janelas do LibreOffice que
    estão no telão e não são a apresentação capturada; nunca mexe no slide
    show nem em janelas de outros aplicativos.
    """
    if not alvo:
        return 0
    painel = alvo.get("monitor_painel")
    telao = alvo.get("monitor")
    if not painel or not telao or tuple(painel) == tuple(telao):
        return 0
    extensao = os.path.splitext(alvo.get("caminho") or "")[1].lower()
    if extensao not in {".ppt", ".pptx", ".pps", ".ppsx", ".odp"}:
        return 0
    movidas = 0
    for janela in _varrer_janelas_x11():
        if not _eh_controle_libreoffice(janela, alvo):
            continue
        if not _janela_dentro_do_monitor(janela, telao):
            continue
        if _mover_janela_para_monitor(janela, painel):
            movidas += 1
    if movidas and alvo.get("janela"):
        # Mover/levantar o controle não deve tirar as teclas da
        # apresentação: devolve o foco ao slide show que já estava ativo.
        _trazer_foco(int(alvo["janela"]))
    return movidas


# ── API usada pelo NavePro.py ────────────────────────────────────────
def _localizar_janela_apresentacao(alvo: dict) -> dict | None:
    """Procura a janela da apresentação no sistema operacional atual."""
    if sys.platform.startswith("win"):
        return _localizar_windows(alvo)
    if sys.platform.startswith("linux"):
        return _localizar_x11(alvo)
    return None


def _janela_viva(janela_id: int) -> bool:
    if sys.platform.startswith("win"):
        return _janela_viva_windows(janela_id)
    if sys.platform.startswith("linux"):
        return _janela_viva_x11(janela_id)
    return False


def _trazer_foco(janela_id: int) -> bool:
    if sys.platform.startswith("win"):
        return _trazer_foco_windows(janela_id)
    if sys.platform.startswith("linux"):
        return _trazer_foco_x11(janela_id)
    return False


def _tentar_capturar_janela_apresentacao(alvo: dict) -> bool:
    """Faz uma tentativa de localizar/guardar a janela do slide show."""
    if not alvo or alvo.get("cancelado"):
        return False
    janela = _localizar_janela_apresentacao(alvo)
    if not _parece_apresentacao(janela, alvo):
        return False
    alvo["janela"] = janela["id"]
    alvo["capturado"] = True
    return True


def _agendar_captura_janela_apresentacao(
    root, alvo: dict | None, timeout: float = 25.0,
) -> None:
    """Agenda no Tk a captura da janela, sem usar Xlib em outra thread.

    A captura precisa rodar na thread principal: o Tk e o Xlib do processo
    não são usados de forma concorrente (chamadas simultâneas ao X11 podem
    corromper a conexão). Usa `after` para não travar a interface enquanto
    o PowerPoint/Impress abre.
    """
    if not alvo or not (sys.platform.startswith(("win", "linux"))):
        return
    limite = time.monotonic() + max(0.5, timeout)

    def _tentar():
        if alvo.get("cancelado") or alvo.get("capturado"):
            return
        if _tentar_capturar_janela_apresentacao(alvo):
            _agendar_reposicionamento_controle(root, alvo)
            return
        if time.monotonic() >= limite:
            return
        try:
            root.after(250, _tentar)
        except Exception:
            pass

    try:
        root.after(250, _tentar)
    except Exception:
        pass


def _agendar_reposicionamento_controle(root, alvo: dict) -> None:
    """Tenta mover o controle do Impress para o monitor do operador.

    São feitas algumas tentativas porque o LibreOffice pode criar o slide
    show primeiro e a janela de controle/console alguns instantes depois.
    """
    for atraso in (0, 500, 1500):
        def _mover():
            _reposicionar_janelas_controle(alvo)

        try:
            root.after(atraso, _mover)
        except Exception:
            pass


def _registrar_janela_apresentacao(alvo: dict, timeout: float = 25.0) -> None:
    """Espera a janela do slide show aparecer (uso síncrono/testes).

    O NavePro usa `_agendar_captura_janela_apresentacao` para não chamar
    Xlib fora da thread principal.
    """
    if not alvo or not (sys.platform.startswith(("win", "linux"))):
        return
    limite = time.monotonic() + max(0.5, timeout)
    while time.monotonic() < limite:
        if _tentar_capturar_janela_apresentacao(alvo):
            return
        time.sleep(0.25)


def _focar_apresentacao(alvo: dict | None) -> bool:
    """Devolve o foco à janela capturada da apresentação.

    Se a janela capturada não existe mais (a apresentação terminou), não
    tenta adivinhar outra janela do Office: devolve False para não trazer o
    editor de slides para a frente.
    """
    if not alvo:
        return False
    janela_id = alvo.get("janela")
    if janela_id:
        if not _janela_viva(janela_id):
            return False
        # A janela do Impress pode ser a MESMA janela do editor: ao sair do
        # modo apresentação ela continua viva, só perde tela cheia/título de
        # slide show. Confere de novo antes de ativar.
        atual = _localizar_janela_apresentacao(alvo)
        if (not _parece_apresentacao(atual, alvo)
                or atual.get("id") != janela_id):
            return False
        return _trazer_foco(janela_id)

    # A captura assíncrona pode não ter terminado (projeção encerrada logo
    # após abrir a apresentação): tenta localizar agora.
    janela = _localizar_janela_apresentacao(alvo)
    if not _parece_apresentacao(janela, alvo):
        return False
    alvo["janela"] = janela["id"]
    alvo["capturado"] = True
    return _trazer_foco(janela["id"])
