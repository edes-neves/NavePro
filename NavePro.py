"""
NavePro - Sistema de Projeção para Igrejas
Versão: 1.9.3
Licença: GPLv3
Autor: José Edes Neves - Julho 2026 edes.neves7@gmail.com
Aplicação para reprodução de mídia com projeção em telão,
busca inteligente no banco de dados e informações climáticas.

"""
from __future__ import annotations
import unicodedata
import json
import mimetypes
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import ssl
import sys
import tempfile
import threading
import time
import tkinter as tk
import tkinter.filedialog
import tkinter.messagebox
import tkinter.simpledialog
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import datetime
import asyncio
from queue import Queue, Empty
from tkinter import ttk
from tkinter import font as tkfont
from typing import Any, Callable, Iterator, Optional, List, Dict, Tuple
import xml.etree.ElementTree as ET
try:
    from screeninfo import get_monitors as _get_monitors
    _HAS_SCREENINFO = True
except ImportError:
    _HAS_SCREENINFO = False

# ────────────────────────────────────────────────────────────────────
# AMBIENTE LIMPO PARA PROCESSOS EXTERNOS
# ────────────────────────────────────────────────────────────────────

def _ambiente_sem_appimage() -> dict[str, str]:
    """Retorna um ambiente SEM as bibliotecas embutidas do AppImage.

    Quando o NavePro roda dentro de um AppImage, o runtime injeta
    LD_LIBRARY_PATH (e ARGV0/APPDIR/OWD) apontando para as libs embutidas
    (fontconfig, pango, glib...). Ao lançar programas do sistema
    (smplayer -> mpv, ffprobe, dbus-send, vlc, xrandr...), essa variável
    faz com que eles carreguem versões ERRADAS das bibliotecas e quebrem
    com "symbol lookup error" (ex.: libpangoft2 vs fontconfig).

    Aqui removemos QUALQUER LDLIBRARY_PATH herdado do AppImage antes de
    executar programas externos. O processo NavePro já carregou todas as
    libs que precisa em memória no arranque, então é seguro repassar
    um ambiente sem essa variável aos filhos do sistema.
    """
    env = os.environ.copy()
    for var in ('LD_LIBRARY_PATH', 'APPDIR', 'APPIMAGE', 'OWD', 'ARGV0'):
        env.pop(var, None)
    return env


def _eh_windows() -> bool:
    """True se estivermos rodando no Windows."""
    return sys.platform.startswith('win')


def _eh_linux() -> bool:
    """True se estivermos rodando no Linux."""
    return sys.platform.startswith('linux')


# ────────────────────────────────────────────────────────────────────
# CONTEXTO SSL USANDO OS CERTIFICADOS DO SISTEMA
# ────────────────────────────────────────────────────────────────────

_SSL_CONTEXTO: Optional[ssl.SSLContext] = None
_SSL_CONTEXTO_LOCK: threading.Lock = threading.Lock()
# Locais comuns do bundle de CA do sistema
_CAMINHOS_CACERT: tuple[str, ...] = (
    "/etc/ssl/certs/ca-certificates.crt",   # Debian/Ubuntu/derivados (BigLinux)
    "/etc/ssl/cert.pem",                    # macOS/Fedora
    "/etc/pki/tls/certs/ca-bundle.crt",     # RHEL/Fedora
    "/etc/ssl/ca-bundle.pem",               # openSUSE
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
)
# Caminhos onde o host pode ter CAs corporativas (MITM/proxy) adicionais
_CAMINHOS_CLIENTE: tuple[str, ...] = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/cert.pem",
)


def _ssl_context() -> ssl.SSLContext:
    """Retorna um contexto SSL com as CAs do SISTEMA (não as embutidas).

    Dentro do AppImage, o Python embutido usa um bundle de CA próprio que
    nem sempre confia nas raízes (ex.: proxy corporativo, ou distribuições
    em que as CAs ficam em local específico — como no BigLinux). Isso
    causa "SSL: CERTIFICATE_VERIFY_FAILED". Aqui carregamos o bundle de CA
    do sistema do host de verdade.
    """
    global _SSL_CONTEXTO
    if _SSL_CONTEXTO is not None:
        return _SSL_CONTEXTO
    with _SSL_CONTEXTO_LOCK:
        if _SSL_CONTEXTO is not None:
            return _SSL_CONTEXTO

        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED

        # 1) Tenta carregar explicitamente o bundle de CA do sistema.
        for cafile in _CAMINHOS_CACERT:
            try:
                if os.path.isfile(cafile):
                    ctx.load_verify_locations(cafile=cafile)
                    break
            except (ssl.SSLError, OSError):
                continue

        # 2) Tenta um bundle de cliente/CA corporativa (evita MITM falso).
        for cafile in _CAMINHOS_CLIENTE:
            try:
                if os.path.isfile(cafile):
                    ctx.load_verify_locations(cafile=cafile)
                    break
            except (ssl.SSLError, OSError):
                continue

        _SSL_CONTEXTO = ctx
        return ctx


def _baixar(url, timeout: int = 8, **kwargs):
    """Faz uma requisição HTTPS usando o certificado do sistema.

    Aceita uma URL (str) ou um urllib.request.Request já montado
    (headers/User-Agent etc.). Encapsular um Request em outro Request
    quebra a URL e levanta 'ValueError: unknown url type'.
    """
    if not isinstance(url, urllib.request.Request):
        url = urllib.request.Request(url, **kwargs)
    return urllib.request.urlopen(url, timeout=timeout, context=_ssl_context())


# ────────────────────────────────────────────────────────────────────
# CONSTANTES
# ────────────────────────────────────────────────────────────────────

APP_VERSION: str = "1.9.4"
CONFIG_FILE: str = "config.json"  # Será redefinido abaixo em UTILITÁRIOS DE CAMINHO
PLAYER_PADRAO: str = "mpv" if _eh_windows() else "smplayer"
BACKEND_PORT: int = 5897
BACKEND_URL: str = f"http://127.0.0.1:{BACKEND_PORT}"

# ── Atualização automática (GitHub Releases) ──
# O NavePro consulta o release mais recente em
# https://github.com/{GITHUB_REPO}/releases/latest e, se houver versão
# nova, oferece baixar o AppImage para ~/Downloads com instruções de
# substituição do arquivo antigo.
GITHUB_USER: str = "edes-neves"
GITHUB_REPO: str = "NavePro"
RELEASES_API_URL: str = (
    f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/releases/latest"
)
SEGUNDOS_PARA_VERIFICAR_ATUALIZACAO: int = 20

EXTENSOES_VIDEO: frozenset = frozenset({'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.webm'})
EXTENSOES_AUDIO: frozenset = frozenset({'.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac'})
EXTENSOES_TEXTO: frozenset = frozenset({'.txt', '.pdf', '.doc', '.docx', '.md'})
EXTENSOES_TODAS: frozenset = EXTENSOES_VIDEO | EXTENSOES_AUDIO | EXTENSOES_TEXTO

SQLITE_TIMEOUT: int = 10
CACHE_TTL_SEGUNDOS: int = 60
CACHE_LRU_MAXSIZE: int = 256


# ────────────────────────────────────────────────────────────────────
# TEMAS DA INTERFACE (painel do administrador / monitor 1)
# ────────────────────────────────────────────────────────────────────
# O tema ESCURO atual permanece intacto e é o padrão. O tema CLARO é
# uma opção extra: as cores escuras hardcoded na interface são convertidas
# em tempo de execução pela tabela abaixo, sem alterar nenhuma cor do
# código existente. As cores de projeção/relógio do TELÃO NÃO são tocadas.
#
# Mapa: cor ESCURA atual -> cor equivalente no tema CLARO.
MAPA_COR_CLARA: dict[str, str] = {
    # Fundos
    '#0d1117': '#f6f8fa',   # fundo principal da janela
    '#161b22': '#ffffff',   # cards/containers
    '#21262d': '#ffffff',   # entradas/botões neutros/lista
    '#1c2128': '#f6f8fa',   # linha alternada (par) da lista
    '#30363d': '#d0d7de',   # bordas/separadores/hover neutro
    # Roxos (accent)
    '#6e40c9': '#8250df',
    '#8b5cf6': '#8250df',
    '#8957e5': '#8250df',
    '#a371f7': '#8250df',
    '#a78bfa': '#8250df',
    # Verdes (sucesso)
    '#238636': '#1a7f37',
    '#2ea043': '#2ea043',
    '#3fb950': '#2ea043',
    # Azuis (info)
    '#1f6feb': '#0969da',
    '#388bfd': '#388bfd',
    '#58a6ff': '#0969da',
    # Vermelhos (perigo)
    '#da3633': '#cf222e',
    '#f85149': '#f85149',
    # Textos fixos
    '#c9d1d9': '#1f2328',   # texto normal
    '#8b949e': '#656d76',   # texto secundário/muted
}

_MAPA_COR_CLARA_UP: dict[str, str] = {
    chave.upper(): valor for chave, valor in MAPA_COR_CLARA.items()
}

# Cores fortes do tema claro (mantêm texto branco por cima)
_CORES_FORTES_CLARO: frozenset = frozenset({
    '#8250df', '#6e40c9',                                              # roxos
    '#1a7f37', '#2ea043', '#238636', '#2ea043',                        # verdes
    '#0969da', '#388bfd', '#1f6feb', '#58a6ff',                        # azuis
    '#cf222e', '#da3633', '#f85149',                                   # vermelhos
})

# Fundos claros (texto branco fica ilegível em cima)
_FUNDOS_CLAROS: frozenset = frozenset({
    '#ffffff', '#f6f8fa', '#eaeef2',
})

# Opções de cor do Tk que o tema pode recolorir por widget
_OPCOES_COR_TK: tuple[str, ...] = (
    'background', 'foreground',
    'activebackground', 'activeforeground',
    'highlightbackground', 'highlightcolor',
    'selectcolor', 'insertbackground',
    'selectbackground', 'selectforeground',
    'troughcolor', 'arrowcolor',
)

# Opções que representam TEXTO (precisam decidir a cor com base no fundo)
_OPCOES_TEXTO: frozenset = frozenset({
    'foreground', 'activeforeground', 'arrowcolor',
    'insertbackground', 'selectforeground',
})


def _cor_clara(cor: Optional[str], bg_final: Optional[str] = None) -> str:
    """Devolve a equivalente CLARA da cor ESCURA `cor` (ou ela mesma).

    Amarelos e brancos dependem do contexto: sobre um fundo forte
    (roxo/verde/azul/vermelho) mantêm branco; sobre fundo claro viram
    um tom escuro legível.
    """
    if not cor:
        return '#000000'
    mapa = _MAPA_COR_CLARA_UP
    if cor.upper() in mapa:
        return mapa[cor.upper()]
    if cor in ('#f0c040', '#F5BE08'):
        if bg_final in _CORES_FORTES_CLARO:
            return '#ffffff'
        return '#24292f'
    if cor in ('#ffffff', '#FFFFFF'):
        if bg_final in _FUNDOS_CLAROS:
            return '#1f2328'
        return '#ffffff'
    return cor


# ────────────────────────────────────────────────────────────────────
# UTILITÁRIOS DE CAMINHO
# ────────────────────────────────────────────────────────────────────


def _caminho_base() -> str:
    """Diretório do executável/script (compatível PyInstaller)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _caminho_recurso(nome: str) -> str:
    """Caminho de recurso embutido (PyInstaller) ou local (dev)."""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, nome)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), nome)


def _aplicar_icone_janela(janela) -> None:
    """Define o ícone da janela: XBM no Linux, ICO no Windows."""
    try:
        if _eh_windows():
            ico = _caminho_recurso("Icon.ico")
            if os.path.exists(ico):
                janela.wm_iconbitmap(ico)
        else:
            xbm = _caminho_recurso("Icon.xbm")
            if os.path.exists(xbm):
                janela.wm_iconbitmap("@" + xbm)
    except Exception:
        pass


def _obter_dados_usuario() -> str:
    """Diretório persistente do usuário (~/.navepro)."""
    data_dir = os.path.join(os.path.expanduser("~"), ".navepro")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


DATA_USER_DIR: str = _obter_dados_usuario()
CONFIG_FILE: str = os.path.join(DATA_USER_DIR, "config.json")
DB_PATH: str = os.path.join(DATA_USER_DIR, "midia.db")
UPLOAD_FOLDER: str = os.path.join(DATA_USER_DIR, "uploads")
DIR_BASE: str = _caminho_base()
DB_EMBUTIDO: str = _caminho_recurso("midia.db")
UPLOADS_EMBUTIDO: str = _caminho_recurso("uploads")
ANUNCIOS_FILE: str = os.path.join(DATA_USER_DIR, "anuncios.json")
SERVICOS_FILE: str = os.path.join(DATA_USER_DIR, "servicos.json")

# Extensões de imagem aceitas como "slide" nos anúncios
SUFIXOS_IMAGEM: frozenset = frozenset({'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'})


# ────────────────────────────────────────────────────────────────────
# ATUALIZAÇÃO AUTOMÁTICA
# ────────────────────────────────────────────────────────────────────


def _versao_tuple(versao: str) -> tuple:
    """Converte '1.8.0'/'v1.9.1' em tupla numérica para comparação."""
    partes: list[int] = []
    for p in re.split(r'\D+', versao):
        if p:
            try:
                partes.append(int(p))
            except ValueError:
                partes.append(0)
    return tuple(partes) or (0,)


def _versao_nova(remota: str, local: str = APP_VERSION) -> bool:
    """True se a versão remota (GitHub) for maior que a instalada."""
    return _versao_tuple(remota) > _versao_tuple(local)


def _buscar_release_latest(timeout: int = 10) -> Optional[dict]:
    """Consulta o release mais recente na API do GitHub (thread-safe).

    Retorna dict com 'tag_name', 'name', 'body' e 'assets' (lista de
    assets do release, cada um com 'name' e 'browser_download_url').
    """
    try:
        req = urllib.request.Request(
            RELEASES_API_URL, headers={
                "User-Agent": f"NavePro/{APP_VERSION}",
                "Accept": "application/vnd.github+json",
            }
        )
        with _baixar(req, timeout=timeout) as resp:
            dados = json.loads(resp.read().decode('utf-8'))
        if not isinstance(dados, dict) or not dados.get('tag_name'):
            return None
        return dados
    except Exception as e:
        print(f"⚠️  Verificação de atualização falhou: {e}")
        return None


def _procurar_asset_instalador(release: dict) -> Optional[dict]:
    """Encontra o instalador da plataforma atual.

    Windows procura o primeiro asset '.exe'; Linux o primeiro '.AppImage'.
    """
    sufixo = ".exe" if _eh_windows() else ".appimage"
    for asset in release.get('assets', []) or []:
        nome = str(asset.get('name', '')).lower()
        if nome.endswith(sufixo):
            return asset
    return None


def _pasta_downloads() -> str:
    """Retorna ~/Downloads (ou ~ como fallback) para salvar o instalador."""
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    if not os.path.isdir(downloads):
        downloads = os.path.expanduser("~")
    return downloads


# ────────────────────────────────────────────────────────────────────
# UTILITÁRIOS DE TEXTO
# ────────────────────────────────────────────────────────────────────


def detectar_tipo_arquivo(caminho: str) -> Optional[str]:
    """Detecta o tipo de mídia pela extensão."""
    ext = os.path.splitext(caminho)[1].lower()
    if ext in EXTENSOES_VIDEO:
        return 'video'
    if ext in EXTENSOES_AUDIO:
        return 'audio'
    if ext in EXTENSOES_TEXTO:
        return 'texto'
    return None


# Regex compilada para remoção de acentos (O(n), sem laço Python)
_PATTERN_ACENTOS: re.Pattern = re.compile(
    '[áàãâäéèêëíìîïóòõôöúùûüçñÁÀÃÂÄÉÈÊËÍÌÎÏÓÒÕÔÖÚÙÛÜÇÑ]'
)
# Cache LRU para remover_acentos (evita normalizações repetidas)
_ACENTOS_CACHE: OrderedDict[str, str] = OrderedDict()
_ACENTOS_CACHE_LOCK = threading.Lock()
_ACENTOS_CACHE_MAX: int = 1024

_MAPA_ACENTOS: dict[str, str] = {
    'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'ä': 'a',
    'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
    'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
    'ó': 'o', 'ò': 'o', 'õ': 'o', 'ô': 'o', 'ö': 'o',
    'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
    'ç': 'c', 'ñ': 'n',
    'Á': 'A', 'À': 'A', 'Ã': 'A', 'Â': 'A', 'Ä': 'A',
    'É': 'E', 'È': 'E', 'Ê': 'E', 'Ë': 'E',
    'Í': 'I', 'Ì': 'I', 'Î': 'I', 'Ï': 'I',
    'Ó': 'O', 'Ò': 'O', 'Õ': 'O', 'Ô': 'O', 'Ö': 'O',
    'Ú': 'U', 'Ù': 'U', 'Û': 'U', 'Ü': 'U',
    'Ç': 'C', 'Ñ': 'N',
}

def _replace_acentos(match: re.Match) -> str:
    """Callback para substituir acento no regex."""
    char = match.group(0)
    return _MAPA_ACENTOS.get(char, char)


def remover_acentos(texto: str) -> str:
    """Remove acentos usando regex compilada com callback e cache LRU."""
    if not texto:
        return texto
    # Cache check (thread-safe via lock)
    with _ACENTOS_CACHE_LOCK:
        cached = _ACENTOS_CACHE.get(texto)
        if cached is not None:
            return cached
    texto = unicodedata.normalize('NFC', texto)
    resultado = _PATTERN_ACENTOS.sub(_replace_acentos, texto)
    # Cache write (LRU via OrderedDict.move_to_end)
    with _ACENTOS_CACHE_LOCK:
        if len(_ACENTOS_CACHE) >= _ACENTOS_CACHE_MAX:
            _ACENTOS_CACHE.popitem(last=False)
        _ACENTOS_CACHE[texto] = resultado
        _ACENTOS_CACHE.move_to_end(texto)
    return resultado


def normalizar_texto(texto: str) -> str:
    """Normaliza: minúsculas, sem acentos, sem espaços extras."""
    return re.sub(r'\s+', ' ', remover_acentos(str(texto or '').strip())).casefold()

# ────────────────────────────────────────────────────────────────────
# BANCO DE DADOS – GERENCIADOR COM CACHE E CONEXÃO PERSISTENTE
# ────────────────────────────────────────────────────────────────────

class DatabaseManager:
    """Singleton para gerenciar conexão SQLite e cache em memória."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._conn: Optional[sqlite3.Connection] = None
        self._cache: List[Dict[str, Any]] = []
        self._cache_loaded: bool = False
        self._reload_lock = threading.Lock()
        self._result_cache: OrderedDict[str, List[Dict[str, Any]]] = OrderedDict()
        self._load_cache()

    def _connect(self) -> sqlite3.Connection:
        """Retorna uma conexão persistente (cria se não existir)."""
        if self._conn is None:
            self._conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT,
                                         check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def _load_cache(self) -> None:
        """Carrega todos os registros ativos em memória com seus campos normalizados."""
        with self._reload_lock:
            try:
                conn = self._connect()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, nome_exibicao, nome_original, caminho_arquivo, tipo
                    FROM midia
                    WHERE ativo = 1
                """)
                rows = cursor.fetchall()
                self._cache = []
                # Verifica existência dos arquivos em lote (reduz chamadas stat)
                caminhos = tuple({row['caminho_arquivo'] for row in rows})
                caminhos_existem = {c: os.path.exists(c) for c in caminhos}
                for row in rows:
                    if not caminhos_existem.get(row['caminho_arquivo'], False):
                        continue
                    record = dict(row)
                    record['nome_exibicao_norm'] = normalizar_texto(record['nome_exibicao'])
                    record['nome_original_norm'] = normalizar_texto(record['nome_original'])
                    # Pré-calcular chave de ordenação
                    record['sort_key'] = self._compute_sort_key(record['nome_exibicao'])
                    self._cache.append(record)
                self._cache_loaded = True
            except Exception as e:
                print(f"Erro ao carregar cache: {e}")
                self._cache = []
                self._cache_loaded = False

    @staticmethod
    def _compute_sort_key(nome: str) -> Tuple[int, int, str]:
        """Gera chave de ordenação: (prioridade_numero, numero, resto)"""
        # Extrai número inicial e resto em uma única regex
        match = re.match(r"(\d+)[\s\-._]+(.+)", nome)
        if match:
            return (0, int(match.group(1)), match.group(2).casefold())
        # Tenta extrair só número sem separador
        match = re.match(r"(\d+)", nome)
        if match:
            num = int(match.group(1))
            # Resto é o nome sem o número (mais eficiente com slice)
            resto = nome[len(match.group(1)):].lstrip(' -._').casefold()
            return (0, num, resto)
        return (1, 0, nome.casefold())

    def reload_cache(self) -> None:
        """Recarrega o cache (após alterações no banco)."""
        self._load_cache()

    def search(self, term: str) -> List[Dict[str, Any]]:
        """Busca síncrona em memória usando normalização com cache LRU."""
        if not self._cache_loaded or not term:
            return []
        term_norm = normalizar_texto(term)
        if not term_norm:
            return []

        # Verifica cache LRU (usa term_norm como chave para consistência)
        if term_norm in self._result_cache:
            self._result_cache.move_to_end(term_norm)
            return self._result_cache[term_norm]

        results: List[Dict[str, Any]] = []

        # Se termo é número, busca exata e por prefixo
        if term.isdigit():
            num = term
            for rec in self._cache:
                if (rec['nome_exibicao'] == num or
                    rec['nome_exibicao'].startswith(num + ' -') or
                    rec['nome_exibicao'].startswith(num + '-') or
                    rec['nome_original'] == num or
                    rec['nome_original'].startswith(num + ' -') or
                    rec['nome_original'].startswith(num + '-')):
                    results.append(rec)
        else:
            # Busca textual
            for rec in self._cache:
                if (term_norm in rec['nome_exibicao_norm'] or
                    term_norm in rec['nome_original_norm']):
                    results.append(rec)

        # Ordenar por chave de ordenação
        results.sort(key=lambda x: x['sort_key'])

        # Atualiza cache LRU (armazena referência, não cópia)
        self._result_cache[term_norm] = results
        if len(self._result_cache) > CACHE_LRU_MAXSIZE:
            self._result_cache.popitem(last=False)

        return results

    def get_all_ids(self) -> List[int]:
        """Retorna todos os IDs em cache."""
        return [rec['id'] for rec in self._cache]

    def get_by_id(self, midia_id: int) -> Optional[Dict[str, Any]]:
        """Retorna um registro pelo ID."""
        for rec in self._cache:
            if rec['id'] == midia_id:
                return rec
        return None

    def get_path_by_id(self, midia_id: int) -> Optional[str]:
        """Retorna o caminho do arquivo pelo ID."""
        rec = self.get_by_id(midia_id)
        return rec['caminho_arquivo'] if rec else None

    # Métodos para operações de banco (INSERT/UPDATE/DELETE) – usam conexão persistente
    def execute(self, query: str, params: tuple = ()) -> Optional[int]:
        """Executa INSERT/UPDATE/DELETE e retorna lastrowid."""
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        return cursor.lastrowid

    def query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Executa SELECT e retorna lista de dicionários."""
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

# ────────────────────────────────────────────────────────────────────
# FUNÇÕES DE BANCO LEGADAS (PARA COMPATIBILIDADE COM API E GERENCIADOR)
# ────────────────────────────────────────────────────────────────────

# As funções db_query e db_execute são mantidas para uso em threads separadas
# (API REST e gerenciador) para evitar concorrência com a conexão persistente.

# Pool de conexões SQLite (thread-safe) para db_query/db_execute
# Reduz abertura/fechamento de conexões em requisições concorrentes


def db_query(query: str, params: tuple = ()) -> list[dict]:
    """Executa SELECT usando DatabaseManager (singleton)."""
    return DatabaseManager().query(query, params)

def db_execute(query: str, params: tuple = ()) -> Optional[int]:
    """Executa INSERT/UPDATE/DELETE usando DatabaseManager (singleton)."""
    return DatabaseManager().execute(query, params)

# ────────────────────────────────────────────────────────────────────
# REUSO DE IDs (ID INTEGER PRIMARY KEY AUTOINCREMENT)
# ────────────────────────────────────────────────────────────────────
#
# Ao excluir registros (ex.: hinos com DELETE real), o AUTOINCREMENT não
# reutiliza os IDs: os próximos inserts continuam do max+1, deixando
# "lacunas". Estas funções reutilizam o menor ID livre em novas importações.

# Só reutilizamos IDs de tabelas de conteúdo do usuário.
_TABELAS_REUSO_ID: frozenset = frozenset({"letras", "versiculos", "midia"})
# Colunas precisam ser seguras para montar o INSERT (nomes internos literais)
_PADRAO_COL_INSERCAO: re.Pattern = re.compile(r"^[a-z_][a-z0-9_]*$")


def _ids_referenciados_itens_servico() -> set:
    """IDs ainda apontados por itens_servico.referencia_id (Ordens de Serviço).

    Uma ordem de serviço pode referenciar letras.id, versiculos.id ou
    midia.id. Se reutilizarmos uma dessas IDs após exclusão, o item antigo
    da ordem passaria a apontar para o registro NOVO — por isso esses IDs
    são preservados (nunca reutilizados).
    """
    try:
        return {
            r["referencia_id"] for r in db_query(
                "SELECT DISTINCT referencia_id FROM itens_servico "
                "WHERE referencia_id IS NOT NULL")
        }
    except Exception:
        return set()


def _gerador_id_livre(tabela: str, limitar: int = 0) -> Iterator[int]:
    """Gera os menores IDs livres (lacunas) da tabela, em ordem crescente.

    Pula IDs ainda referenciados em itens_servico.referencia_id. Se não
    houver lacuna reutilizável, não gera nada (AUTOINCREMENT segue normal).
    """
    if tabela not in _TABELAS_REUSO_ID:
        return
    linhas = sorted(r["id"] for r in db_query(f"SELECT id FROM {tabela}"))
    referenciados = _ids_referenciados_itens_servico()
    esperado = 1
    gerados = 0
    for id_atual in linhas:
        while esperado < id_atual:
            if esperado not in referenciados:
                yield esperado
                gerados += 1
                if limitar and gerados >= limitar:
                    return
            esperado += 1
        esperado = max(esperado, id_atual) + 1


def _proximo_id_livre(tabela: str) -> Optional[int]:
    """Menor ID livre reutilizável da tabela (None se não houver)."""
    return next(_gerador_id_livre(tabela, 1), None)


def _inserir_com_id_reuso(tabela: str, colunas: tuple, valores: tuple) -> int:
    """Insere registro reutilizando o menor ID livre, quando houver.

    Sem lacuna disponível, o AUTOINCREMENT segue o comportamento padrão.
    Retorna o id do registro inserido.
    """
    assert tabela in _TABELAS_REUSO_ID, f"Tabela inválida: {tabela}"
    assert all(
        isinstance(c, str) and _PADRAO_COL_INSERCAO.match(c) for c in colunas
    ), "Colunas inválidas para INSERT"
    cols = ", ".join(colunas)
    marks = ", ".join(["?"] * len(colunas))
    valores = tuple(valores)
    id_livre = _proximo_id_livre(tabela)
    if id_livre is not None:
        db_execute(
            f"INSERT INTO {tabela} (id, {cols}) VALUES (?, {marks})",
            (id_livre,) + valores)
        return id_livre
    return db_execute(
        f"INSERT INTO {tabela} ({cols}) VALUES ({marks})", valores) or 0

# ────────────────────────────────────────────────────────────────────
# INICIALIZAÇÃO DO BANCO
# ────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Cria a estrutura do banco de dados se não existir."""
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS midia (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_original TEXT NOT NULL,
            nome_exibicao TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('video', 'audio', 'texto')),
            caminho_arquivo TEXT NOT NULL,
            tamanho_bytes INTEGER DEFAULT 0,
            mime_type TEXT DEFAULT '',
            duracao_segundos REAL DEFAULT NULL,
            data_upload TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            data_modificacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ativo INTEGER DEFAULT 1
        )
    """)
    for idx_col in ('tipo', 'nome_exibicao', 'ativo'):
        idx_name = f"idx_midia_{idx_col}"
        cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON midia({idx_col})")
    # Índice para busca textual (nome_exibicao, nome_original) – ajuda mas não substitui FTS
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_midia_nomes ON midia(nome_exibicao, nome_original)")

    # ── Tabela de Letras/Hinos ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS letras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            artista TEXT DEFAULT '',
            compositor TEXT DEFAULT '',
            ccli_numero TEXT DEFAULT '',
            categoria TEXT DEFAULT '',
            idioma TEXT DEFAULT 'pt-BR',
            letra_completa TEXT NOT NULL DEFAULT '',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ativo INTEGER DEFAULT 1
        )
    """)
    for idx_col in ('titulo', 'artista', 'ccli_numero', 'ativo'):
        idx_name = f"idx_letras_{idx_col}"
        cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON letras({idx_col})")

    # ── Tabela de Bíblia (versículos) ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS versiculos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            versao TEXT NOT NULL DEFAULT 'NVI',
            livro TEXT NOT NULL,
            capitulo INTEGER NOT NULL,
            versiculo INTEGER NOT NULL,
            texto TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_versiculos_ref ON versiculos(versao, livro, capitulo, versiculo)")

    # ── Tabela de Ordens de Serviço ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS servicos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            data_servico TEXT,
            template INTEGER DEFAULT 0,
            tempo_estimado_minutos INTEGER DEFAULT 0,
            observacoes TEXT DEFAULT '',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ativo INTEGER DEFAULT 1
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_servicos_ativo ON servicos(ativo)")

    # ── Tabela de Itens da Ordem de Serviço ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS itens_servico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            servico_id INTEGER NOT NULL,
            ordem INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            referencia_id INTEGER DEFAULT NULL,
            titulo_custom TEXT DEFAULT '',
            letra_snapshot TEXT DEFAULT '',
            duracao_estimada_segundos INTEGER DEFAULT 0,
            configuracoes TEXT DEFAULT '{}',
            FOREIGN KEY (servico_id) REFERENCES servicos(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_itens_servico_sid ON itens_servico(servico_id, ordem)")

    # ── Tabela de Anúncios (persistência no banco a partir desta versão) ──
    # tipo_midia: 'slide' (texto), 'video', 'audio', 'imagem' (slide de imagem).
    # Para vídeo/áudio/imagem, o arquivo é copiado para UPLOAD_FOLDER e o
    # caminho guardado em arquivo_midia.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS anuncios (
            id INTEGER PRIMARY KEY,
            titulo TEXT NOT NULL,
            categoria TEXT DEFAULT '',
            texto TEXT DEFAULT '',
            tipo_midia TEXT NOT NULL DEFAULT 'slide',
            arquivo_midia TEXT DEFAULT '',
            nome_arquivo_midia TEXT DEFAULT '',
            config_midia TEXT DEFAULT '',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ativo INTEGER DEFAULT 1
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_anuncios_titulo ON anuncios(titulo)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_anuncios_ativo ON anuncios(ativo)")

    # ── Migração: remover AUTOINCREMENT de bancos existentes ──
    # Sem AUTOINCREMENT, o SQLite reaproveita o menor ID livre ao inserir.
    try:
        info = cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='anuncios'"
        ).fetchone()
        if info and info[0] and "AUTOINCREMENT" in info[0]:
            dados_existentes = cursor.execute(
                "SELECT * FROM anuncios"
            ).fetchall()
            colunas = [desc[0] for desc in cursor.description]
            cursor.execute("DROP TABLE anuncios")
            cursor.execute("""
                CREATE TABLE anuncios (
                    id INTEGER PRIMARY KEY,
                    titulo TEXT NOT NULL,
                    categoria TEXT DEFAULT '',
                    texto TEXT DEFAULT '',
                    tipo_midia TEXT NOT NULL DEFAULT 'slide',
                    arquivo_midia TEXT DEFAULT '',
                    nome_arquivo_midia TEXT DEFAULT '',
                    config_midia TEXT DEFAULT '',
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ativo INTEGER DEFAULT 1
                )
            """)
            for row in dados_existentes:
                vals = dict(zip(colunas, row))
                placeholders = ", ".join("?" for _ in vals)
                cols = ", ".join(vals.keys())
                cursor.execute(
                    f"INSERT INTO anuncios ({cols}) VALUES ({placeholders})",
                    tuple(vals.values()),
                )
            cursor.execute("DROP TABLE IF EXISTS _anuncios_backup_old_ai")
            print("✅ Migração anuncios: AUTOINCREMENT removido (IDs passam a reaproveitar).")
    except Exception as e:
        print(f"⚠️ Migração AUTOINCREMENT ignorada (nova tabela ou já migrada): {e}")

    # ── Migração: garantir a coluna config_midia em bancos já existentes ──
    # Aditiva e idempotente: se a coluna já existe (banco novo ou já migrado),
    # não faz nada.
    try:
        colunas_existentes = {desc[1] for desc in cursor.execute(
            "PRAGMA table_info(anuncios)").fetchall()}
        if colunas_existentes and 'config_midia' not in colunas_existentes:
            cursor.execute("ALTER TABLE anuncios ADD COLUMN config_midia TEXT DEFAULT ''")
            print("✅ Migração anuncios: coluna 'config_midia' adicionada.")
    except Exception as e:
        print(f"⚠️ Migração config_midia ignorada: {e}")

    conn.commit()
    conn.close()


def inicializar_banco() -> None:
    """Copia banco embutido se necessário e inicializa."""
    if not os.path.exists(DB_PATH):
        if os.path.exists(DB_EMBUTIDO):
            print(f"📦 Copiando banco embutido para {DB_PATH}")
            shutil.copy2(DB_EMBUTIDO, DB_PATH)
        else:
            print(f"📦 Banco não encontrado, criando novo em {DB_PATH}")
    init_db()


def inicializar_config() -> None:
    """Copia config embutido para ~/.navepro/ se necessário."""
    config_embutido = _caminho_recurso("config.json")
    if not os.path.exists(CONFIG_FILE) and os.path.exists(config_embutido):
        print(f"📦 Copiando config embutido para {CONFIG_FILE}")
        shutil.copy2(config_embutido, CONFIG_FILE)


def garantir_pasta_uploads() -> bool:
    """Garante que a pasta uploads existe com conteúdo."""
    if os.path.isdir(UPLOAD_FOLDER):
        try:
            if any(True for _ in os.scandir(UPLOAD_FOLDER)):
                return True
        except (PermissionError, OSError):
            pass

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    for origem in [UPLOADS_EMBUTIDO, os.path.join(DIR_BASE, "originais")]:
        if os.path.isdir(origem):
            try:
                if any(True for _ in os.scandir(origem)):
                    print(f"📦 Copiando de '{origem}' para '{UPLOAD_FOLDER}'...")
                    shutil.copytree(origem, UPLOAD_FOLDER, dirs_exist_ok=True)
                    return True
            except (PermissionError, OSError):
                continue

    if getattr(sys, 'frozen', False):
        print("\n⚠️ Pasta de músicas não encontrada!")
        resposta = tkinter.messagebox.askyesno(
            "Pasta de mídias não encontrada",
            "A pasta 'uploads' não foi encontrada.\n\n"
            "Deseja selecionar a pasta com os arquivos de mídia?"
        )
        if resposta:
            root = tk.Tk(className="NavePro_selector")
            root.withdraw()
            pasta = tkinter.filedialog.askdirectory(
                title="Selecione a pasta com os arquivos de mídia"
            )
            root.destroy()
            if pasta:
                shutil.copytree(pasta, UPLOAD_FOLDER, dirs_exist_ok=True)
                try:
                    return any(True for _ in os.scandir(UPLOAD_FOLDER))
                except (PermissionError, OSError):
                    return False
    return False


def _sincronizar_uploads_midia() -> int:
    """Registra no banco os arquivos da pasta uploads ainda não cadastrados.

    Arquivos já cadastrados (mesmo caminho_arquivo) são ignorados, então a
    função pode ser chamada quantas vezes for preciso. Devolve a quantidade
    de mídias sincronizadas na última chamada.
    """
    if not os.path.isdir(UPLOAD_FOLDER):
        return 0
    try:
        registrados = {
            r["caminho_arquivo"]
            for r in db_query("SELECT caminho_arquivo FROM midia")
        }
    except Exception:
        return 0
    try:
        entradas = sorted(
            os.scandir(UPLOAD_FOLDER), key=lambda e: (e.name or "").casefold()
        )
    except (PermissionError, OSError):
        return 0
    novos = 0
    for ent in entradas:
        try:
            if not ent.is_file():
                continue
            caminho = ent.path
            if caminho in registrados:
                continue
            tipo = detectar_tipo_arquivo(caminho)
            if not tipo:
                continue
            mime, _ = mimetypes.guess_type(caminho)
            try:
                tamanho: int = ent.stat().st_size
            except OSError:
                tamanho = 0
            db_execute("""
                INSERT INTO midia
                    (nome_original, nome_exibicao, tipo, caminho_arquivo,
                     tamanho_bytes, mime_type, data_upload, data_modificacao)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """, (ent.name, os.path.splitext(ent.name)[0], tipo, caminho,
                  tamanho, mime or ''))
            novos += 1
        except Exception:
            continue
    if novos:
        DatabaseManager().reload_cache()
        print(f"📦 {novos} mídia(s) sincronizada(s) da pasta uploads.")
    return novos


# As funções inicializar_banco e garantir_pasta_uploads são
# chamadas dentro de AppInterface.__init__ para evitar efeitos
# colaterais na importação do módulo.

# ────────────────────────────────────────────────────────────────────
# WORKER DE BUSCA (ÚNICA THREAD COM FILA)
# ────────────────────────────────────────────────────────────────────

class SearchWorker:
    """Worker único com fila para processar buscas de forma assíncrona."""

    def __init__(self):
        self.queue: Queue = Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._db = DatabaseManager()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                task = self.queue.get(timeout=0.5)
                if task is None:
                    continue
                term, version, callback = task
                results = self._db.search(term)
                if callback:
                    try:
                        root = tk._default_root
                        if root is not None:
                            # Dispatch via after(0) na thread principal
                            root.after(0, self._dispatch_callback, results, version, callback)
                        elif callback:
                            callback(results, version)
                    except Exception as e:
                        print(f"Erro ao chamar callback: {e}")
                self.queue.task_done()
            except Empty:
                continue
            except Exception as e:
                print(f"Erro no SearchWorker: {e}")

    def _dispatch_callback(self, results: List[Dict[str, Any]], version: int, callback: Callable) -> None:
        """Dispatch seguro do callback na thread principal."""
        try:
            callback(list(results), version)
        except Exception as e:
            print(f"Erro no dispatch: {e}")

    def submit(self, term: str, version: int, callback: Callable) -> None:
        """Enfileira uma tarefa de busca."""
        self.queue.put((term, version, callback))

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

# ────────────────────────────────────────────────────────────────────
# SERVIDOR HTTP - API REST (mantido como antes)
# ────────────────────────────────────────────────────────────────────


class ServidorAsyncHTTP:
    """Servidor HTTP assíncrono usando asyncio.
    
    Substitui HTTPServer (bloqueante) por um servidor asyncio que não
    interfere com o event loop do Tk. Roda em uma thread separada
    com seu próprio event loop asyncio.
    """
    
    def __init__(self, port: int = BACKEND_PORT) -> None:
        self.port = port
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server: Optional[asyncio.AbstractServer] = None

    def iniciar(self) -> None:
        """Inicia o servidor em uma thread separada com event loop asyncio."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_async, daemon=True)
        self._thread.start()

    def _run_async(self) -> None:
        """Executa o event loop asyncio (chamado pela thread)."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._servir())
            self._loop.run_forever()
        except Exception as e:
            print(f"Erro no servidor async: {e}")
        finally:
            self._loop.close()

    async def _servir(self) -> None:
        """Configura e inicia o servidor HTTP assíncrono."""
        self._server = await asyncio.start_server(
            self._handle_connection,
            '127.0.0.1', self.port
        )
        print(f"✅ Servidor async rodando em 127.0.0.1:{self.port}")

    async def _handle_connection(self, reader: asyncio.StreamReader, 
                                  writer: asyncio.StreamWriter) -> None:
        """Handler de conexão HTTP assíncrono."""
        try:
            request_data = await reader.read(65536)
            if not request_data:
                writer.close()
                return
            
            request_text = request_data.decode('utf-8', errors='replace')
            
            # Parse da requisição HTTP
            lines_req = request_text.split('\r\n')
            if not lines_req:
                writer.close()
                return
            
            first_line = lines_req[0].split()
            if len(first_line) < 2:
                writer.close()
                return
            
            method = first_line[0]
            path_line = first_line[1]
            
            # Parse headers
            headers: dict[str, str] = {}
            body_start = request_text.find('\r\n\r\n')
            for line in lines_req[1:]:
                if ':' in line:
                    key, val = line.split(':', 1)
                    headers[key.strip().lower()] = val.strip()
                if line == '':
                    break
            
            # Extrair body
            body_bytes = b''
            if body_start != -1:
                body_bytes = request_data[body_start + 4:]
            
            # Processar requisição
            response = await self._process_request(method, path_line, headers, body_bytes)
            
            writer.write(response)
            await writer.drain()
        except Exception as e:
            print(f"Erro ao processar requisição: {e}")
            error_response = (
                "HTTP/1.1 500 Internal Server Error\r\n"
                "Content-Type: application/json; charset=utf-8\r\n"
                "Access-Control-Allow-Origin: *\r\n"
                "Connection: close\r\n"
                "\r\n"
                '{"erro": "Erro interno do servidor"}'
            ).encode()
            try:
                writer.write(error_response)
                await writer.drain()
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _process_request(self, method: str, path_full: str,
                                headers: dict, body: bytes) -> bytes:
        """Processa uma requisição HTTP e retorna a resposta."""
        parsed = urllib.parse.urlparse(path_full)
        path = parsed.path
        params = dict(urllib.parse.parse_qsl(parsed.query))
        
        # CORS preflight
        if method == 'OPTIONS':
            return (
                "HTTP/1.1 200 OK\r\n"
                "Access-Control-Allow-Origin: *\r\n"
                "Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS\r\n"
                "Access-Control-Allow-Headers: Content-Type\r\n"
                "Content-Length: 0\r\n"
                "\r\n"
            ).encode()
        
        # ROTEAMENTO
        if method == 'GET':
            return await self._handle_get(path, params)
        elif method == 'POST':
            return await self._handle_post(path, headers, body)
        elif method == 'DELETE':
            return await self._handle_delete(path)
        else:
            return self._responder_erro_bytes("Método não suportado", 405)

    async def _handle_get(self, path: str, params: dict) -> bytes:
        """Processa requisições GET."""
        if path == '/api/midia':
            return self._handle_get_midia_bytes(params)
        elif path == '/api/midia/contagem':
            resultados = db_query(
                "SELECT tipo, COUNT(*) as total FROM midia WHERE ativo = 1 GROUP BY tipo"
            )
            contagem: dict[str, int] = {r['tipo']: r['total'] for r in resultados}
            return self._responder_json_bytes(contagem)
        elif (match := re.match(r'^/api/midia/(\d+)$', path)):
            midia_id = int(match.group(1))
            row = db_query("SELECT * FROM midia WHERE id = ? AND ativo = 1", (midia_id,))
            if row:
                return self._responder_json_bytes(row[0])
            else:
                return self._responder_erro_bytes("Mídia não encontrada", 404)
        elif path.startswith('/api/midia/') and path.endswith('/download'):
            return await self._handle_download_bytes(path)
        elif path == '/':
            return (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                "Access-Control-Allow-Origin: *\r\n"
                "\r\n"
                "<h1>Servidor do Hinario</h1><p>API em /api/midia</p>"
            ).encode('utf-8')
        else:
            return self._responder_erro_bytes("Rota não encontrada", 404)

    def _handle_get_midia_bytes(self, params: dict) -> bytes:
        """Busca mídias (igual ao handler anterior, retorna bytes)."""
        tipo = params.get('tipo')
        busca = params.get('busca', '').strip()
        query = "SELECT * FROM midia WHERE ativo = 1"
        query_params: list[object] = []

        if busca:
            if busca.isdigit():
                num = busca
                query += (
                    " AND (\n"
                    "    nome_exibicao = ? OR\n"
                    "    nome_exibicao LIKE ? OR\n"
                    "    nome_exibicao LIKE ? OR\n"
                    "    nome_original = ? OR\n"
                    "    nome_original LIKE ? OR\n"
                    "    nome_original LIKE ? OR\n"
                    "    id = ?\n"
                    ")"
                )
                query_params.extend([
                    num, f"{num} -%", f"{num}-%",
                    num, f"{num} -%", f"{num}-%",
                ])
            else:
                busca_nfc = unicodedata.normalize('NFC', busca)
                busca_like = busca_nfc.casefold()
                query += (
                    " AND (\n"
                    "    LOWER(nome_exibicao) LIKE ? OR\n"
                    "    LOWER(nome_original) LIKE ?\n"
                    ")"
                )
                query_params.extend([f"%{busca_like}%", f"%{busca_like}%"])

        if tipo:
            query += " AND tipo = ?"
            query_params.append(tipo)

        query += (
            " ORDER BY\n"
            "    CASE WHEN nome_exibicao GLOB '[0-9]*' THEN 0 ELSE 1 END,\n"
            "    CAST(SUBSTR(nome_exibicao, 1, INSTR(nome_exibicao || ' ', ' ') - 1) AS INTEGER),\n"
            "    SUBSTR(nome_exibicao, INSTR(nome_exibicao || ' ', ' ') + 1) ASC"
        )

        resultados = db_query(query, query_params)

        # Pós-filtro fonético
        if busca and resultados and not busca.isdigit():
            busca_nfc = unicodedata.normalize('NFC', busca)
            busca_ascii = remover_acentos(busca_nfc).casefold()
            cache_norm = {
                r['id']: remover_acentos(
                    unicodedata.normalize('NFC',
                        r.get('nome_exibicao', '') + ' ' + r.get('nome_original', '')
                    )
                ).casefold()
                for r in resultados
            }
            resultados = [r for r in resultados if busca_ascii in cache_norm[r['id']]]

        return self._responder_json_bytes(resultados)

    async def _handle_download_bytes(self, path: str) -> bytes:
        """Processa download de arquivo."""
        try:
            midia_id = int(path.split('/')[3])
        except (IndexError, ValueError):
            return self._responder_erro_bytes("ID inválido", 400)

        row = db_query("SELECT * FROM midia WHERE id = ? AND ativo = 1", (midia_id,))
        if not row:
            return self._responder_erro_bytes("Mídia não encontrada", 404)

        midia = row[0]
        caminho = midia['caminho_arquivo']
        if not os.path.exists(caminho):
            return self._responder_erro_bytes("Arquivo não encontrado no disco", 404)

        mime, _ = mimetypes.guess_type(caminho)
        try:
            with open(caminho, 'rb') as f:
                conteudo = f.read()
        except Exception:
            return self._responder_erro_bytes("Erro ao ler arquivo", 500)

        header = (
            f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: {mime or 'application/octet-stream'}\r\n"
            f"Content-Disposition: attachment; filename=\"{os.path.basename(caminho)}\"\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"Content-Length: {len(conteudo)}\r\n"
            f"\r\n"
        ).encode()
        return header + conteudo

    async def _handle_post(self, path: str, headers: dict, body: bytes) -> bytes:
        """Processa requisições POST."""
        if path == '/api/midia/upload':
            return self._handle_upload_bytes(headers, body)
        else:
            return self._responder_erro_bytes("Rota não encontrada", 404)

    def _handle_upload_bytes(self, headers: dict, body: bytes) -> bytes:
        """Processa upload de arquivo."""
        content_type = headers.get('content-type', '')
        if 'multipart/form-data' not in content_type:
            return self._responder_erro_bytes("Content-Type deve ser multipart/form-data")

        try:
            boundary = content_type.split('boundary=')[1].encode()
        except (IndexError, ValueError):
            return self._responder_erro_bytes("Boundary não encontrado")

        parts = body.split(b'--' + boundary)
        arquivo_dados = None
        nome_arquivo = None
        nome_exibicao = None

        for part in parts:
            if b'Content-Disposition' not in part:
                continue
            if b'filename="' in part:
                match = re.search(rb'filename="([^"]*)"', part)
                if match:
                    nome_arquivo = match.group(1).decode('utf-8', errors='ignore')
                header_end = part.find(b'\r\n\r\n')
                if header_end != -1:
                    arquivo_dados = part[header_end + 4:-2]
            elif b'name="nome_exibicao"' in part:
                header_end = part.find(b'\r\n\r\n')
                if header_end != -1:
                    nome_exibicao = part[header_end + 4:-2].decode(
                        'utf-8', errors='ignore'
                    ).strip()

        if not arquivo_dados or not nome_arquivo:
            return self._responder_erro_bytes("Nenhum arquivo enviado")

        tipo = detectar_tipo_arquivo(nome_arquivo)
        if not tipo:
            return self._responder_erro_bytes(
                f"Tipo não suportado: {os.path.splitext(nome_arquivo)[1].lower()}"
            )

        caminho = os.path.join(UPLOAD_FOLDER, nome_arquivo)
        contador = 1
        while os.path.exists(caminho):
            nome_base, ext_arq = os.path.splitext(nome_arquivo)
            caminho = os.path.join(UPLOAD_FOLDER, f"{nome_base}_{contador}{ext_arq}")
            contador += 1

        with open(caminho, 'wb') as f:
            f.write(arquivo_dados)

        if not nome_exibicao:
            nome_exibicao = os.path.splitext(os.path.basename(caminho))[0]

        mime, _ = mimetypes.guess_type(caminho)
        tamanho = os.path.getsize(caminho)

        midia_id = db_execute("""
            INSERT INTO midia
                (nome_original, nome_exibicao, tipo, caminho_arquivo,
                 tamanho_bytes, mime_type, data_upload, data_modificacao)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """, (os.path.basename(caminho), nome_exibicao, tipo, caminho,
              tamanho, mime or ''))

        DatabaseManager().reload_cache()

        return self._responder_json_bytes({
            "mensagem": "✅ Upload realizado!",
            "id": midia_id,
            "nome": nome_exibicao,
            "tipo": tipo,
            "caminho": caminho
        }, 201)

    async def _handle_delete(self, path: str) -> bytes:
        """Processa requisições DELETE."""
        match = re.match(r'^/api/midia/(\d+)$', path)
        if match:
            midia_id = int(match.group(1))
            db_execute(
                "UPDATE midia SET ativo = 0, data_modificacao = datetime('now') WHERE id = ?",
                (midia_id,)
            )
            DatabaseManager().reload_cache()
            return self._responder_json_bytes({"mensagem": "✅ Mídia removida!"})
        else:
            return self._responder_erro_bytes("Rota não encontrada", 404)

    # ── Utilitários de resposta ───────────────────────────────────

    def _responder_json_bytes(self, dados: Any, status: int = 200) -> bytes:
        """Gera resposta HTTP JSON como bytes."""
        body = json.dumps(dados, ensure_ascii=False, default=str).encode('utf-8')
        status_text = {200: "OK", 201: "Created", 400: "Bad Request",
                       404: "Not Found", 405: "Method Not Allowed", 500: "Internal Server Error"}
        header = (
            f"HTTP/1.1 {status} {status_text.get(status, 'OK')}\r\n"
            f"Content-Type: application/json; charset=utf-8\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS\r\n"
            f"Access-Control-Allow-Headers: Content-Type\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode()
        return header + body

    def _responder_erro_bytes(self, msg: str, status: int = 400) -> bytes:
        """Gera resposta HTTP de erro como bytes."""
        return self._responder_json_bytes({"erro": msg}, status)

    # ── Compatibilidade ───────────────────────────────────────────
    def parar(self) -> None:
        """Para o servidor HTTP de forma segura."""
        if self._server:
            self._server.close()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        print("✅ Servidor async parado")

    def run(self) -> None:
        self._run_async()

    def start(self) -> None:
        self.iniciar()
MAPA_ESTADOS: dict[str, str] = {
    'AC': 'Acre', 'AL': 'Alagoas', 'AP': 'Amapá', 'AM': 'Amazonas',
    'BA': 'Bahia', 'CE': 'Ceará', 'DF': 'Distrito Federal',
    'ES': 'Espírito Santo', 'GO': 'Goiás', 'MA': 'Maranhão',
    'MT': 'Mato Grosso', 'MS': 'Mato Grosso do Sul', 'MG': 'Minas Gerais',
    'PA': 'Pará', 'PB': 'Paraíba', 'PR': 'Paraná', 'PE': 'Pernambuco',
    'PI': 'Piauí', 'RJ': 'Rio de Janeiro', 'RN': 'Rio Grande do Norte',
    'RS': 'Rio Grande do Sul', 'RO': 'Rondônia', 'RR': 'Roraima',
    'SC': 'Santa Catarina', 'SP': 'São Paulo', 'SE': 'Sergipe',
    'TO': 'Tocantins',
}


def _estado_para_nome(estado: str) -> str:
    """Converte sigla UF para nome completo."""
    return MAPA_ESTADOS.get(estado.upper(), estado)


def _estado_bate(texto: str, estado_sigla: str, estado_nome: str) -> bool:
    """Verifica se o texto menciona o estado."""
    if not estado_sigla:
        return True
    texto_norm = normalizar_texto(texto)
    if not texto_norm:
        return False
    valores = {
        normalizar_texto(estado_sigla),
        normalizar_texto(estado_nome),
    }
    return any(v and v in texto_norm for v in valores)


def _cidade_estado_especial(cidade: str, estado: str) -> bool:
    """Verifica se é 'Mundo Novo' que existe em múltiplos estados."""
    return (
        normalizar_texto(cidade) == 'mundo novo'
        and normalizar_texto(estado) in {'ms', 'ba', 'go'}
    )


def _resultado_aceitavel_nominatim(
    item: dict, cidade: str, estado: str, estado_nome: str
) -> bool:
    """Filtra resultados do Nominatim para evitar locais inadequados."""
    if not item:
        return False

    nome = normalizar_texto(item.get('name', ''))
    cidade_norm = normalizar_texto(cidade)
    display_name = normalizar_texto(item.get('display_name', ''))

    nome_bate = nome == cidade_norm
    tokens_cidade = set(cidade_norm.split())
    tokens_nome = set(nome.split())
    tokens_batem = bool(tokens_cidade and tokens_cidade.issubset(tokens_nome))

    if not (nome_bate or tokens_batem):
        return False

    if _cidade_estado_especial(cidade, estado):
        return bool(estado and _estado_bate(display_name, estado, estado_nome))

    classe = normalizar_texto(item.get('class', ''))
    tipo = normalizar_texto(item.get('type', ''))

    if classe in {'landuse', 'water', 'amenity', 'natural'}:
        return False
    if tipo in {'building', 'peak', 'river', 'city_district',
                 'hamlet', 'suburb', 'neighbourhood', 'isolated_dwelling',
                 'farm', 'residential', 'locality'}:
        return False

    if estado and not _estado_bate(display_name, estado, estado_nome):
        return False

    return True


def obter_temperatura(cidade: str, estado: str) -> str:
    """
    Obtém a temperatura atual usando Open-Meteo.
    Retorna string formatada como '25°C' ou mensagem de erro.
    """
    try:
        cidade = cidade.strip()
        estado = estado.strip().upper()
        estado_nome = _estado_para_nome(estado)

        # Tenta consultas com e sem estado
        consultas: list[str] = []
        if estado:
            consultas.append(f"{cidade}, {estado_nome}, Brasil")
            consultas.append(f"{cidade}, {estado}, Brasil")
            consultas.append(f"{cidade}, {estado_nome}")
        consultas.append(cidade)

        for consulta in consultas:
            geo_url = (
                f"https://geocoding-api.open-meteo.com/v1/search?"
                f"name={urllib.parse.quote(consulta)}&count=8&language=pt&format=json"
                f"&country=BR"
            )
            if estado:
                geo_url += f"&admin1={urllib.parse.quote(estado_nome)}"

            try:
                with _baixar(geo_url, timeout=8) as response:
                    geo_data = json.loads(response.read().decode())
            except Exception as e:
                print(f"⚠️ Geocoding falhou ({consulta!r}): {e}")
                continue

            if 'results' not in geo_data or not geo_data['results']:
                continue

            resultado = None
            for item in geo_data['results']:
                if normalizar_texto(item.get('name', '')) != normalizar_texto(cidade):
                    continue
                if not estado:
                    resultado = item
                    break
                if _estado_bate(item.get('admin1', ''), estado, estado_nome):
                    resultado = item
                    break

            if resultado is None:
                print(f"⚠️ Geocoding sem resultado válido para {consulta!r}")
                continue

            lat = resultado.get('latitude')
            lon = resultado.get('longitude')
            if lat is None or lon is None:
                continue

            weather_url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat}&longitude={lon}&current_weather=true"
            )
            try:
                with _baixar(weather_url, timeout=8) as response:
                    weather_data = json.loads(response.read().decode())
            except Exception as e:
                print(f"⚠️ Weather falhou ({cidade!r} {lat},{lon}): {e}")
                continue

            if 'current_weather' in weather_data:
                temp = weather_data['current_weather']['temperature']
                return f"{temp}°C"

            return "ERRO AO OBTER TEMPERATURA"

        # Fallback para Nominatim
        try:
            geo_url = (
                f"https://nominatim.openstreetmap.org/search?"
                f"q={urllib.parse.quote(f'{cidade}, {estado_nome}, Brasil')}"
                f"&format=json&limit=3"
            )
            req = urllib.request.Request(geo_url, headers={'User-Agent': 'HinarioApp/1.0'})
            with _baixar(req, timeout=8) as response:
                geo_data = json.loads(response.read().decode())

            for item in geo_data:
                if not _resultado_aceitavel_nominatim(item, cidade, estado, estado_nome):
                    continue
                lat = float(item['lat'])
                lon = float(item['lon'])
                weather_url = (
                    f"https://api.open-meteo.com/v1/forecast?"
                    f"latitude={lat}&longitude={lon}&current_weather=true"
                )
                with _baixar(weather_url, timeout=8) as response:
                    weather_data = json.loads(response.read().decode())
                if 'current_weather' in weather_data:
                    return f"{weather_data['current_weather']['temperature']}°C"
        except Exception as e:
            print(f"⚠️ Nominatim falhou ({cidade!r}): {e}")
            pass

        if estado:
            estado_upper = remover_acentos(estado_nome).upper()
            return f"NAO PERTENCE AO ESTADO DE: {estado_upper}."
        return "NAO ENCONTRADA"

    except Exception as e:
        print(f"Erro ao obter temperatura: {e}")
        return "ERRO"

# ────────────────────────────────────────────────────────────────────
# MONITORES - DETECÇÃO (mantido)
# ────────────────────────────────────────────────────────────────────


class MonitorInfo:
    """Informações de um monitor detectado."""
    def __init__(self, x: int, y: int, w: int, h: int, name: str = "Monitor") -> None:
        self.x = x
        self.y = y
        self.width = w
        self.height = h
        self.name = name

    def __repr__(self) -> str:
        return f"Monitor({self.name}: {self.width}x{self.height} em ({self.x},{self.y}))"


# Cache global de monitores com TTL
_MONITORS_CACHE: Optional[Tuple[float, List[MonitorInfo]]] = None

def get_monitors_config() -> List[MonitorInfo]:
    """
    Detecta monitores com cache TTL (60s).
    Prioriza screeninfo > xrandr (geometria real) > heurística tkinter.
    """
    global _MONITORS_CACHE
    # Verifica cache
    if _MONITORS_CACHE is not None:
        timestamp, cached = _MONITORS_CACHE
        if time.time() - timestamp < CACHE_TTL_SEGUNDOS:
            return cached
        _MONITORS_CACHE = None

    # Método 1: screeninfo (biblioteca Python, multiplataforma)
    if _HAS_SCREENINFO:
        try:
            monitors = _get_monitors()
            if monitors:
                result = [
                    MonitorInfo(m.x, m.y, m.width, m.height, m.name or f"Monitor {i+1}")
                    for i, m in enumerate(monitors)
                ]
                _MONITORS_CACHE = (time.time(), result)
                print(f"✅ screeninfo: {len(monitors)} monitor(es) detectado(s)")
                return result
        except ImportError:
            pass
        except Exception as e:
            print(f"⚠️ screeninfo: {e}")

    # Método 2: xrandr (Linux X11) - geometria REAL dos monitores,
    # evita o palpite de metades iguais quando há telões com resoluções
    # diferentes (ex.: 1920x1080 + 1280x720).
    # No Windows nenhuma dessas ferramentas existe — o screeninfo/cTk dão conta.
    if _eh_linux():
        try:
            result = subprocess.run(
                ['xrandr'], capture_output=True, text=True, timeout=5,
                env=_ambiente_sem_appimage()
            )
            connected: list[MonitorInfo] = []
            for line in result.stdout.split('\n'):
                if ' connected' in line and '+' in line:
                    parts = line.split()
                    for p in parts:
                        if 'x' in p and '+' in p:
                            size_pos = p.split('+')
                            if len(size_pos) >= 3:
                                size = size_pos[0].split('x')
                                x, y = int(size_pos[1]), int(size_pos[2])
                                w, h = int(size[0]), int(size[1])
                                connected.append(
                                    MonitorInfo(x, y, w, h, parts[0])
                                )
                            break
            if connected:
                _MONITORS_CACHE = (time.time(), connected)
                print(f"✅ xrandr: {len(connected)} monitor(es) detectado(s)")
                return connected
        except Exception as e:
            print(f"⚠️ xrandr: {e}")

    # Método 3: tkinter + heurística de largura (apenas último recurso)
    try:
        root = tk.Tk(className="NavePro_monitor")
        root.withdraw()
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        root.destroy()

        if screen_width > 2500:
            half = screen_width // 2
            result = [
                MonitorInfo(0, 0, half, screen_height, "Monitor 1"),
                MonitorInfo(half, 0, half, screen_height, "Monitor 2"),
            ]
        else:
            result = [MonitorInfo(0, 0, screen_width, screen_height, "Monitor 1")]
        _MONITORS_CACHE = (time.time(), result)
        return result
    except Exception as e:
        print(f"⚠️ tkinter fallback: {e}")

    # Fallback
    print("⚠️ Usando fallback: dual-monitor 1920x1080")
    result = [
        MonitorInfo(0, 0, 1920, 1080, "Monitor 1"),
        MonitorInfo(1920, 0, 1920, 1080, "Monitor 2"),
    ]
    _MONITORS_CACHE = (time.time(), result)
    return result

# ────────────────────────────────────────────────────────────────────
# TELÃO - JANELA DE PROJEÇÃO (mantido)
# ────────────────────────────────────────────────────────────────────


def _normalizar_escala_tk(root) -> float:
    """Garante texto legível e consistente entre Python/Tk diferentes.

    O AppImage usa o python do sistema (AppRun), que pode ter um Tk com
    'tk scaling' baixo (ex.: dpi desconhecido), deixando botões e fontes
    minúsculos no monitor 1 e as letras pequenas no telão. Este ajuste
    aplica um piso de zoom (1.3 px/ponto, ≈96dpi) em qualquer interpretador.
    """
    escala_min = 1.3
    try:
        pixels_por_pol = float(root.winfo_fpixels('1i'))
        escala = pixels_por_pol / 72.0
        if escala < escala_min:
            escala = escala_min
        root.tk.call('tk', 'scaling', escala)
        return escala
    except Exception:
        try:
            root.tk.call('tk', 'scaling', escala_min)
        except Exception:
            pass
        return escala_min


class TelaoWindow:
    """Janela de projeção exibida no telão (monitor secundário).

    Otimizações:
    - Centralização calculada no init (sem recálculo em cada redesenho)
    - itemconfig só quando o texto realmente muda (evita redraw do Canvas)
    - Atributos '-alpha' e visibilidade mantidos em cache para evitar chamadas Tk
    - root.lower() chamado uma única vez (não repetido via after)
    - update() substituído por update_idletasks() (mais leve) + update() apenas
      quando necessário
    - Fontes calculadas proporcionalmente à altura da tela (uma vez)
    """

    def __init__(self, monitor_index: int = 1) -> None:
        self.root = tk.Tk(className="NavePro")
        self.root.title("TELÃO")
        _normalizar_escala_tk(self.root)
        _aplicar_icone_janela(self.root)

        monitors = get_monitors_config()
        print(f"🖥️ Monitores detectados: {len(monitors)}")
        for i, m in enumerate(monitors):
            print(f"   Monitor {i+1}: {m.width}x{m.height} em ({m.x},{m.y})")

        if len(monitors) >= monitor_index:
            monitor = monitors[monitor_index - 1]
        elif len(monitors) > 1:
            monitor = monitors[1]
        else:
            monitor = monitors[0]

        # Cache de geometria privada (evita acessos repetidos)
        self._monitor = monitor
        geometry = f"{monitor.width}x{monitor.height}+{monitor.x}+{monitor.y}"
        print(f"✅ TELÃO: {geometry}")
        # Inicia em TELA CHEIA (sem bordas) cobrindo o monitor secundário.
        # A tecla F11 alterna para o modo janela (min/max/redimensionar) e
        # volta à tela cheia.
        # Config do relógio (cores, tamanhos, espaçamento, fundo opaco)
        self._relogio_cfg: dict = {
            "cor_hora": "#F5BE08",
            "cor_temp": "#F5BE08",
            "cor_fundo": "#000000",
            "fator_hora": 1.0,
            "fator_temp": 1.0,
            "espacamento": 1.0,
            "fundo_opaco": False,
            "fundo_imagem": "",
        }
        self._fundo_relogio_item = None
        self._fundo_relogio_to_tk = None
        self._fundo_relogio_caminho = ""

        self.root.geometry(geometry)
        self.root.configure(bg='black')
        self.root.attributes('-alpha', self._alpha_relogio())
        self.root.attributes('-topmost', False)
        self._fullscreen: bool = True
        self.root.attributes('-fullscreen', True)
        self.root.lift()
        # Só reafirma a geometria no modo tela cheia; no modo janela o
        # gerenciador de janelas controla livremente (min/max/redimensionar).
        self.root.bind("<Configure>", self._reafirmar_geometria)

        # Cache de estado: evita chamadas repetidas à Tk
        self._current_alpha: float = self._alpha_relogio()
        self._current_text: str = ""
        self._current_temp: str = ""
        self._is_visible: bool = True

        self.main_frame = tk.Frame(self.root, bg='black')
        self.main_frame.pack(fill='both', expand=True)

        self.canvas = tk.Canvas(self.main_frame, bg='black', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)

        # Calcula fontes e posições sem sobreposição (720p–1080p),
        # medindo a altura real (linha) das fontes na tela atual.
        self._font_hora: tuple | None = None
        self._font_temp: tuple | None = None
        self._tam_hora: int = 0
        self._tam_temp: int = 0
        self._cx = 0
        self._cy_hora = 0
        self._cy_temp = 0
        self._calcular_layout(monitor.width, monitor.height)

        # Texto da hora
        self.overlay_text = self.canvas.create_text(
            self._cx, self._cy_hora, text="",
            fill=self._relogio_cfg["cor_hora"], anchor="center",
            font=self._font_hora
        )
        # Texto da temperatura
        self.temp_text = self.canvas.create_text(
            self._cx, self._cy_temp, text="",
            fill=self._relogio_cfg["cor_temp"], anchor="center",
            font=self._font_temp
        )
        # Referência bíblica (livro cap:vers.) — canto inferior direito
        self.ref_text = self.canvas.create_text(
            0, 0, text="", fill="#A0A0A0", anchor="se", state="hidden",
            font=("DejaVu Sans", 16, "bold")
        )

        # Redimensionamento mantido (caso janela seja movida)
        self.canvas.bind("<Configure>", self._centralizar)
        self.root.bind("<Escape>", self._ao_pressionar_esc)
        self.root.bind("<Control-q>", self.fechar)
        self.root.bind("<F11>", self._alternar_fullscreen)

        self.rodando = True
        self.mostrando_relogio = True
        self.mostrando_letra = False
        self._em_slides = False
        self._mostrando_imagem = False
        self._mostrando_imagem_com_texto = False
        self._imagem_item = None
        self._imagem_rect_base = None
        self._imagem_pil = None
        self._imagem_orig_pil = None
        self._imagem_escala = 1.0
        self._texto_box = (0, 0, 100, 100)
        self._texto_escala = 1.0
        self._texto_largura_base = None
        self._slides: list = []
        self._slide_index = 0
        self._proj_cfg: dict = {
            "fonte": "Montserrat",
            "tamanho_pct": 5.0,
            "cor": "#FFFFFF",
            "duracao_seg": 30,
            "cor_ref": "#A0A0A0",
            "cor_fundo": "#000000",
            "fundo_opaco": True,
            "fundo_imagem": "",
        }
        self._fundo_imagem_item = None
        self._fundo_imagem_to_tk = None
        self._fundo_imagem_caminho = ""
        self._proj_timer = None
        self._temp_salvo = ""
        self.root.protocol("WM_DELETE_WINDOW", self.fechar)
        # Aplica alpha imediatamente
        self.root.attributes('-alpha', self._alpha_relogio())
        self._current_alpha = self._alpha_relogio()
        # Exibe hora inicial
        self._exibir_hora_inicial()

    def _alpha_relogio(self) -> float:
        """Retorna o alpha do telão no modo relógio (opaco se configurado)."""
        if getattr(self, "_relogio_cfg", {}).get("fundo_opaco"):
            return 1.0
        return 0.55

    def _calcular_layout(self, largura: int, altura: int) -> bool:
        """Calcula fontes e posições sem sobreposição (720p–1080p).

        Mede a altura real de linha das fontes na tela atual e empilha
        hora + temperatura com espaçamento pequeno, como um bloco único
        centralizado. Funciona de 720p a 1080p e com qualquer fonte
        (inclusive fallback quando 'Digital-7' não existe).
        Retorna True se o layout mudou.

        IMPORTANTE: as fontes são atribuídas ao canvas como TUPLA
        ("Digital-7", tamanho, "normal") e NÃO como tkfont.Font. No X11,
        quando o telão é o segundo Tk() do processo (janela principal
        criada antes), fontes nomeadas (tkfont.Font) são renderizadas
        minúsculas pelo Tk. A tupla renderiza corretamente.
        """
        r_cfg = self._relogio_cfg
        margem_lateral = max(16, int(largura * 0.05))
        espacamento = r_cfg.get("espacamento", 1.0)
        gap = max(0, int(altura * 0.015 * espacamento))
        fator_hora = r_cfg.get("fator_hora", 1.0)
        fator_temp = r_cfg.get("fator_temp", 1.0)
        hora_px = int(altura * 0.48 * fator_hora)
        temp_px = max(24, int(altura * 0.28 * fator_temp))
        self._largura_temp_max = max(200, largura - 2 * margem_lateral)

        def _tam_para_altura(altura_px: int) -> int:
            # Mede a proporção px/point na tela atual (independe de DPI)
            ref = tkfont.Font(family="Digital-7", size=100)
            px_por_pt = ref.metrics("linespace") / 100.0
            if px_por_pt <= 0:
                px_por_pt = 1.0
            size = max(40, min(620, int(altura_px / px_por_pt)))
            fonte = tkfont.Font(family="Digital-7", size=size)
            # Refina pela altura real
            real = fonte.metrics("linespace")
            if real > 0 and abs(real - altura_px) > 2:
                size = max(40, min(620, int(size * altura_px / real)))
            return size

        def _linespace(tam: int) -> int:
            return tkfont.Font(family="Digital-7", size=tam).metrics("linespace")

        tam_hora = _tam_para_altura(hora_px)
        tam_temp = _tam_para_altura(temp_px)
        font_hora = ("Digital-7", tam_hora, "normal")
        font_temp = ("Digital-7", tam_temp, "normal")

        cx = largura // 2
        h_hora = _linespace(tam_hora)
        h_temp = _linespace(tam_temp)
        # O meio do espaço entre a hora e a temperatura coincide com o
        # centro vertical da tela: a hora fica acima e a temperatura abaixo,
        # ambas com o mesmo afastamento do centro.
        meio_gap = altura // 2
        cy_hora = meio_gap - gap // 2 - h_hora // 2
        cy_temp = meio_gap + gap // 2 + h_temp // 2

        mudou = (
            cx != self._cx or cy_hora != self._cy_hora or
            cy_temp != self._cy_temp or
            tam_hora != self._tam_hora or tam_temp != self._tam_temp
        )
        if mudou:
            self._font_hora = font_hora
            self._font_temp = font_temp
            self._tam_hora = tam_hora
            self._tam_temp = tam_temp
            self._cx = cx
            self._cy_hora = cy_hora
            self._cy_temp = cy_temp
        return mudou

    def _centralizar(self, event: object = None) -> None:
        """Recalcula posições e fontes (só se realmente mudou)."""
        if getattr(self, 'mostrando_letra', False):
            return
        w = self.canvas.winfo_width() if not event else event.width
        h = self.canvas.winfo_height() if not event else event.height
        if w < 100 or h < 100:
            return
        if self._calcular_layout(w, h):
            self.canvas.coords(self.overlay_text, self._cx, self._cy_hora)
            self.canvas.coords(self.temp_text, self._cx, self._cy_temp)
            self.canvas.itemconfig(self.overlay_text, font=self._font_hora)
            self.canvas.itemconfig(self.temp_text, font=self._font_temp)
            self._font_temp_exib_texto = None

    def _reafirmar_geometria(self, event: object = None) -> None:
        """Mantém o telão cobrindo o monitor apenas no modo tela cheia.

        No modo janela não força nada: deixa o usuário minimizar, maximizar,
        redimensionar e mover a janela livremente.
        """
        if not getattr(self, '_fullscreen', False):
            return
        m = self._monitor
        try:
            if (abs(self.root.winfo_width() - m.width) > 4 or
                    abs(self.root.winfo_height() - m.height) > 4 or
                    abs(self.root.winfo_x() - m.x) > 4 or
                    abs(self.root.winfo_y() - m.y) > 4):
                self.root.geometry(f"{m.width}x{m.height}+{m.x}+{m.y}")
        except tk.TclError:
            pass

    def _alternar_fullscreen(self, event: object = None) -> str:
        """Alterna entre tela cheia (sem bordas) e janela redimensionável."""
        self._fullscreen = not getattr(self, '_fullscreen', False)
        self.root.attributes('-fullscreen', self._fullscreen)
        if self._fullscreen:
            self.root.lift()
        else:
            m = self._monitor
            self.root.geometry(f"{m.width}x{m.height}+{m.x}+{m.y}")
        return "break"

    def _fonte_temp_para_texto(self, temperatura: str) -> tuple:
        """Retorna a fonte da temperatura ajustada à largura da tela.

        Encolhe a fonte somente quando o texto real não couber na largura
        (ex.: mensagem de erro longa). O resultado é cacheado por texto.
        Retorna TUPLA ("Digital-7", tamanho, "normal") para o canvas
        (fontes nomeadas renderizam minúsculas no segundo Tk do processo).
        """
        if not temperatura:
            return self._font_temp
        if (getattr(self, '_font_temp_exib_texto', None) == temperatura and
                getattr(self, '_font_temp_exib', None) is not None):
            return self._font_temp_exib
        size = int(self._font_temp[1])
        largura_max = getattr(self, '_largura_temp_max', None)
        if largura_max:
            w = tkfont.Font(family="Digital-7", size=size).measure(temperatura)
            if w > largura_max and w > 0:
                size = max(40, int(size * largura_max / w))
        fonte = ("Digital-7", size, "normal")
        self._font_temp_exib = fonte
        self._font_temp_exib_texto = temperatura
        return fonte

    def mostrar_relogio(self, texto: str, temperatura: str = "") -> None:
        """Exibe relógio e temperatura no telão (só redesenha se mudou)."""
        if not self.rodando:
            return

        # Evita chamadas Tk desnecessárias se os valores não mudaram
        texto_mudou = texto != self._current_text
        temp_mudou = temperatura != self._current_temp

        if not texto_mudou and not temp_mudou and self.mostrando_relogio:
            return

        self.mostrando_relogio = True
        self._current_text = texto
        self._current_temp = temperatura

        # Só mexe na visibilidade se necessário
        if not self._is_visible:
            self.root.deiconify()
            self._is_visible = True

        # Só mexe no alpha se necessário
        alpha_base = self._alpha_relogio()
        if self._current_alpha != alpha_base:
            self.root.attributes('-alpha', alpha_base)
            self._current_alpha = alpha_base

        # Atualiza apenas o que mudou
        if texto_mudou:
            self.canvas.itemconfig(self.overlay_text, text=texto, state="normal")

        if temperatura:
            if temp_mudou:
                self.canvas.itemconfig(
                    self.temp_text,
                    text=temperatura,
                    font=self._fonte_temp_para_texto(temperatura),
                    state="normal",
                )
        elif self._current_temp:
            self.canvas.itemconfig(self.temp_text, text="", state="hidden")

        # lower() apenas quando necessário (janela pode ter subido)
        # Usamos lower() apenas na primeira vez ou após vídeo
        if not self._is_visible or not self.mostrando_relogio:
            self.root.lower()

    def preparar_video(self) -> None:
        """Prepara para exibição de vídeo (esconde o telão)."""
        self.mostrando_relogio = False
        if self._current_alpha != 0.0:
            self.root.attributes('-alpha', 0.0)
            self._current_alpha = 0.0
        if self._is_visible:
            self.root.withdraw()
            self._is_visible = False

    def restaurar_tela(self) -> None:
        """Restaura o telão após o término do vídeo (sem after repetido)."""
        if self._is_visible and self.mostrando_relogio:
            return  # Já está visível

        self._current_alpha = self._alpha_relogio()
        self._is_visible = True
        self.mostrando_relogio = True
        # Reseta cache de hora para forçar redesenho do relógio
        self._current_text = ""
        self._current_temp = ""

        self.root.deiconify()
        self.root.attributes('-alpha', self._alpha_relogio())
        self.root.lower()

    # ── Projeção de texto (letra / versículo) ─────────────────────

    def configurar_projecao(self, cfg: Optional[dict] = None) -> None:
        """Define as configurações de aparência da projeção de texto."""
        defaults = {
            "fonte": "Montserrat",
            "tamanho_pct": 5.0,
            "cor": "#FFFFFF",
            "duracao_seg": 30,
            "cor_ref": "#A0A0A0",
            "cor_fundo": "#000000",
            "fundo_opaco": True,
            "fundo_imagem": "",
        }
        merged = dict(defaults)
        if isinstance(cfg, dict):
            for k, v in cfg.items():
                if k in defaults and v not in (None, ""):
                    merged[k] = v
        self._proj_cfg = merged

    def _alpha_projecao(self) -> float:
        """Alpha do telão durante uma projeção (opaco por padrão).

        Padrão histórico do NavePro: projeções são opacas (alpha 1.0).
        Se o operador desmarcar "Fundo opaco" na Aparência da Projeção,
        aplica a mesma transparência do modo relógio (0.55).
        """
        if not getattr(self, "_proj_cfg", {}).get("fundo_opaco", True):
            return 0.55
        return 1.0

    def _aplicar_fundo_projecao(self) -> None:
        """Aplica a cor de fundo ou a imagem de fundo configurada no telão.

        A imagem de fundo (se definida) vira um item de canvas posicionado
        abaixo de TODO o conteúdo projetado (tag_lower); sem imagem, aplica
        apenas a cor de fundo. Não afeta o modo relógio: ao retornar para o
        relógio, _retornar_ao_relogio limpa o item de imagem de fundo.
        """
        # Durante a projeção, some com a imagem de fundo do relógio para ela
        # não aparecer por trás (cada modo gerencia seu próprio fundo).
        if getattr(self, "_fundo_relogio_item", None) is not None:
            try:
                self.canvas.delete(self._fundo_relogio_item)
            except tk.TclError:
                pass
            self._fundo_relogio_item = None
            self._fundo_relogio_to_tk = None
            self._fundo_relogio_caminho = ""
        cfg = getattr(self, "_proj_cfg", {})
        cor_fundo = cfg.get("cor_fundo", "#000000")
        caminho = (cfg.get("fundo_imagem") or "").strip()
        atual = getattr(self, "_fundo_imagem_caminho", "")
        if caminho == atual and getattr(self, "_fundo_imagem_item", None) is not None:
            return
        # Remove o item de fundo anterior (se houver)
        if getattr(self, "_fundo_imagem_item", None) is not None:
            try:
                self.canvas.delete(self._fundo_imagem_item)
            except tk.TclError:
                pass
            self._fundo_imagem_item = None
        self._fundo_imagem_to_tk = None
        self._fundo_imagem_caminho = caminho
        ext_ok = caminho.lower().endswith(
            (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"))
        if caminho and os.path.exists(caminho) and ext_ok:
            try:
                from PIL import Image, ImageTk
                with Image.open(caminho) as img:
                    img_fundo = img.convert("RGB")
                w = self.canvas.winfo_width() or self._monitor.width
                h = self.canvas.winfo_height() or self._monitor.height
                if w < 1 or h < 1:
                    w, h = self._monitor.width, self._monitor.height
                redimensao = getattr(Image, "LANCZOS", None) or getattr(Image, "BICUBIC", None)
                img_fundo = img_fundo.resize((w, h), redimensao)
                self._fundo_imagem_to_tk = ImageTk.PhotoImage(
                    img_fundo, master=self.root)
                self._fundo_imagem_item = self.canvas.create_image(
                    w // 2, h // 2, image=self._fundo_imagem_to_tk,
                    anchor="center", tags=("fundo_imagem",))
                try:
                    self.canvas.tag_lower(self._fundo_imagem_item)
                except tk.TclError:
                    pass
                self.canvas.configure(bg=cor_fundo)
            except Exception as e:
                print(f"⚠️ Não foi possível exibir a imagem de fundo: {e}")
                self._fundo_imagem_item = None
                self.canvas.configure(bg=cor_fundo)
        else:
            self.root.configure(bg=cor_fundo)
            self.main_frame.configure(bg=cor_fundo)
            self.canvas.configure(bg=cor_fundo)
        self.root.update_idletasks()

    def configurar_relogio(self, cfg: Optional[dict] = None) -> None:
        """Define a configuração de aparência do relógio/temperatura no telão."""
        defaults = {
            "cor_hora": "#F5BE08",
            "cor_temp": "#F5BE08",
            "cor_fundo": "#000000",
            "fator_hora": 1.0,
            "fator_temp": 1.0,
            "espacamento": 1.0,
            "fundo_opaco": False,
            "fundo_imagem": "",
        }
        merged = dict(defaults)
        if isinstance(cfg, dict):
            for k, v in cfg.items():
                if k in defaults and v not in (None, ""):
                    merged[k] = v
        self._relogio_cfg = merged
        # Aplica cores ao canvas
        self._aplicar_cores_relogio()
        # Recalcula layout com novos tamanhos/espacamento
        w = self.canvas.winfo_width() or self._monitor.width
        h = self.canvas.winfo_height() or self._monitor.height
        if w > 100 and h > 100:
            self._calcular_layout(w, h)
            if self.mostrando_relogio:
                self.canvas.coords(self.overlay_text, self._cx, self._cy_hora)
                self.canvas.coords(self.temp_text, self._cx, self._cy_temp)
                self.canvas.itemconfig(self.overlay_text, font=self._font_hora)
                self.canvas.itemconfig(self.temp_text, font=self._font_temp)
                self.root.update_idletasks()
        # Aplica a opacidade configurada ao telão (apenas no modo relógio)
        if self.mostrando_relogio:
            alpha_base = self._alpha_relogio()
            if self._current_alpha != alpha_base:
                self.root.attributes('-alpha', alpha_base)
                self._current_alpha = alpha_base

    def _aplicar_cores_relogio(self) -> None:
        """Aplica as cores configuradas do relógio e temperatura ao canvas."""
        cfg = self._relogio_cfg
        cor_hora = cfg.get("cor_hora", "#F5BE08")
        cor_temp = cfg.get("cor_temp", "#F5BE08")
        cor_fundo = cfg.get("cor_fundo", "#000000")
        self.canvas.itemconfig(self.overlay_text, fill=cor_hora)
        self.canvas.itemconfig(self.temp_text, fill=cor_temp)
        # Imagem de fundo do relógio (opcional): vira item de canvas abaixo
        # do texto. Sem imagem, aplica apenas a cor de fundo.
        caminho = (cfg.get("fundo_imagem") or "").strip()
        caminho_atual = getattr(self, "_fundo_relogio_caminho", "")
        item_atual = getattr(self, "_fundo_relogio_item", None)
        if caminho != caminho_atual or item_atual is None:
            if item_atual is not None:
                try:
                    self.canvas.delete(item_atual)
                except tk.TclError:
                    pass
                self._fundo_relogio_item = None
            self._fundo_relogio_to_tk = None
            self._fundo_relogio_caminho = caminho
            ext_ok = caminho.lower().endswith(
                (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"))
            if caminho and os.path.exists(caminho) and ext_ok:
                try:
                    from PIL import Image, ImageTk
                    with Image.open(caminho) as img:
                        img_fundo = img.convert("RGB")
                    w = self.canvas.winfo_width() or self._monitor.width
                    h = self.canvas.winfo_height() or self._monitor.height
                    if w < 1 or h < 1:
                        w, h = self._monitor.width, self._monitor.height
                    redimensao = getattr(Image, "LANCZOS", None) or getattr(Image, "BICUBIC", None)
                    img_fundo = img_fundo.resize((w, h), redimensao)
                    self._fundo_relogio_to_tk = ImageTk.PhotoImage(
                        img_fundo, master=self.root)
                    self._fundo_relogio_item = self.canvas.create_image(
                        w // 2, h // 2, image=self._fundo_relogio_to_tk,
                        anchor="center", tags=("fundo_relogio",))
                    try:
                        self.canvas.tag_lower(self._fundo_relogio_item)
                    except tk.TclError:
                        pass
                except Exception as e:
                    print(f"⚠️ Não foi possível exibir a imagem de fundo do relógio: {e}")
                    self._fundo_relogio_item = None
                    self._fundo_relogio_caminho = ""
        self.root.configure(bg=cor_fundo)
        self.main_frame.configure(bg=cor_fundo)
        self.canvas.configure(bg=cor_fundo)

    def projetar_texto(self, texto: str, titulo: str = "") -> None:
        """Projeta texto (letra/versículo) no telão com a fonte configurada.

        Esconde relógio e temperatura, exibe o texto formatado no centro e
        agenda o retorno automático do relógio + temperatura após o tempo
        configurado (duracao_seg).
        """
        if not self.rodando:
            return
        cfg = getattr(self, "_proj_cfg", None)
        if cfg is None:
            self.configurar_projecao()

        # Cancela retorno automático anterior (re-projeção)
        if getattr(self, "_proj_timer", None) is not None:
            try:
                self.root.after_cancel(self._proj_timer)
            except tk.TclError:
                pass
            self._proj_timer = None

        # Guarda a temperatura exibida para restaurar depois
        self._temp_salvo = self._current_temp

        # Remove qualquer imagem de uma projeção anterior
        self._limpar_camada_imagem()

        self.mostrando_letra = True
        self._em_slides = False
        self.mostrando_relogio = False

        # Exibe a janela e aplica o fundo/opacidade configurados
        if not self._is_visible:
            self.root.deiconify()
            self._is_visible = True
        alpha = self._alpha_projecao()
        if self._current_alpha != alpha:
            self.root.attributes('-alpha', alpha)
            self._current_alpha = alpha
        self._aplicar_fundo_projecao()
        self.root.lift()

        # Esconde temperatura
        self.canvas.itemconfig(self.temp_text, text="", state="hidden")

        # Monta o texto final (título em destaque + letra)
        texto_final = f"{titulo}\n\n{texto}" if titulo else texto
        self._desenhar_texto_no_canvas(texto_final)

        # Agenda retorno automático do relógio + temperatura
        seg = max(1, int(float(cfg.get("duracao_seg", 30))))
        self._proj_timer = self.root.after(seg * 1000, self._retornar_ao_relogio)

    def _desenhar_texto_no_canvas(self, texto: str, referencia: str = "",
                                  largura_max: Optional[int] = None) -> tuple:
        """Desenha texto centralizado no canvas com auto-ajuste de fonte.

        Usado tanto na projeção simples (projetar_texto) quanto nos slides.
        Retorna a tupla de fonte aplicada.
        Se referencia for fornecida (ex.: "João 3:16"), exibe no canto inferior direito.
        Se largura_max for fornecida, o texto é quebrado (e centralizado)
        dentro dessa largura máxima — usado pelo anúncio de imagem + texto,
        em que parte da tela é ocupada pela imagem.
        """
        cfg = getattr(self, "_proj_cfg", None)
        if cfg is None:
            self.configurar_projecao()

        # Calcula largura de quebra e fonte inicial
        w = self.canvas.winfo_width() or self._monitor.width
        h = self.canvas.winfo_height() or self._monitor.height
        wrap_width = max(200, int(w * 0.95))
        if largura_max:
            wrap_width = max(120, min(wrap_width, int(largura_max)))
        centro_x = w // 2
        if largura_max:
            centro_x = int(largura_max) // 2
        tamanho = max(18, int(h * (float(cfg.get("tamanho_pct", 5.0)) / 100.0)))
        familia = cfg.get("fonte", "Montserrat")
        cor = cfg.get("cor", "#FFFFFF")

        # Fallback de fonte: Montserrat/Arial podem não existir no python do
        # sistema usado pelo AppImage; cai para uma fonte sans confirmada.
        disp = set(tkfont.families(self.root))
        if disp and familia not in disp:
            familia = next(
                (f for f in ("DejaVu Sans", "Liberation Sans", "Helvetica",
                             "Noto Sans", "TkDefaultFont") if f in disp),
                "TkDefaultFont")
            cfg["fonte"] = familia

        # Ajusta tamanho para não transbordar verticalmente
        ref = tkfont.Font(family=familia, size=tamanho)
        linhas = 0
        for parte in texto.split("\n"):
            if not parte:
                linhas += 1
            else:
                comp = ref.measure(parte)
                linhas += max(1, int(comp / wrap_width)) if comp > wrap_width else 1
        altura_total = linhas * max(1, ref.metrics("linespace"))
        max_altura = int(h * 0.92)
        if altura_total > max_altura and altura_total > 0:
            fator = max_altura / altura_total
            tamanho = max(12, int(tamanho * fator))

        fonte = (familia, tamanho, "normal")
        self._font_letra = fonte
        self._current_text = texto
        self._current_temp = ""

        self.canvas.itemconfig(
            self.overlay_text,
            text=texto,
            font=fonte,
            fill=cor,
            width=wrap_width,
            justify="center",
            state="normal",
        )
        self.canvas.coords(self.overlay_text, centro_x, h // 2)

        # Referência bíblica (livro cap:vers.) — canto inferior direito
        if referencia:
            cor_ref = cfg.get("cor_ref", "#A0A0A0")
            tam_ref = max(12, int(tamanho * 0.45))
            fonte_ref = (familia, tam_ref, "bold")
            self.canvas.itemconfig(
                self.ref_text,
                text=referencia,
                fill=cor_ref,
                font=fonte_ref,
                state="normal",
            )
            self.canvas.coords(self.ref_text, w - 30, h - 30)
        else:
            self.canvas.itemconfig(self.ref_text, text="", state="hidden")

        self.root.update_idletasks()
        return fonte

    # ── Projeção em slides (título + versos, navegação do administrador) ──

    def _limpar_camada_imagem(self) -> None:
        """Remove a camada de imagem projetada (anúncio de imagem/composto).

        Chamado ao projetar um conteúdo só de texto POR CIMA de uma projeção
        anterior com imagem, para não deixar a imagem antiga "colada" no telão
        (o texto novo apareceria por trás da imagem velha).
        """
        if getattr(self, "_imagem_item", None) is not None:
            try:
                self.canvas.delete(self._imagem_item)
            except tk.TclError:
                pass
            self._imagem_item = None
        self._imagem_pil = None
        self._imagem_orig_pil = None
        self._imagem_escala = 1.0
        self._imagem_rect_base = None
        self._texto_largura_base = None
        self._texto_box = (0, 0, 100, 100)
        self._texto_escala = 1.0
        self._mostrando_imagem = False
        self._mostrando_imagem_com_texto = False

    def projetar_slides(self, slides: list, indice_inicial: int = 0) -> None:
        """Inicia projeção em slides (ex.: título do hino e versos).

        Slide 0 deve ser o número/título do hino; os demais, os versos
        (2 linhas por slide). indice_inicial define o primeiro slide
        exibido (usado para iniciar pelo versículo selecionado). Não há
        retorno automático: o administrador navega com as setas
        (slide_proximo/slide_anterior) e encerra com Esc ou
        parar_projecao(), voltando o relógio + temperatura ao telão.
        """
        if not self.rodando or not slides:
            return
        # Cancela retorno automático anterior (re-projeção)
        if getattr(self, "_proj_timer", None) is not None:
            try:
                self.root.after_cancel(self._proj_timer)
            except tk.TclError:
                pass
            self._proj_timer = None

        # Guarda a temperatura exibida para restaurar depois
        self._temp_salvo = self._current_temp

        # Remove qualquer imagem de uma projeção anterior (ex.: anúncio de
        # imagem + texto) para o novo texto aparecer limpo por cima.
        self._limpar_camada_imagem()

        self._slides = list(slides)
        self._slide_index = 0
        self._em_slides = True
        self.mostrando_letra = True
        self.mostrando_relogio = False

        # Exibe a janela e aplica o fundo/opacidade configurados
        if not self._is_visible:
            self.root.deiconify()
            self._is_visible = True
        alpha = self._alpha_projecao()
        if self._current_alpha != alpha:
            self.root.attributes('-alpha', alpha)
            self._current_alpha = alpha
        self._aplicar_fundo_projecao()
        self.root.lift()

        # Esconde temperatura
        self.canvas.itemconfig(self.temp_text, text="", state="hidden")

        self._mostrar_slide(max(0, min(indice_inicial, len(self._slides) - 1)))

    def projetar_imagem(self, caminho: str) -> bool:
        """Projeta uma imagem estática centralizada no telão (slide de imagem).

        A imagem é redimensionada para caber na tela preservando a proporção.
        A parada (Esc, parar_projecao, _retornar_ao_relogio) volta o relógio +
        temperatura. Retorna False se o arquivo for inválido/inexistente.
        """
        if not self.rodando or not caminho or not os.path.exists(caminho):
            return False
        try:
            from PIL import Image, ImageTk
        except Exception as e:
            print(f"⚠️ PIL indisponível para projetar imagem: {e}")
            return False

        # Cancela retorno automático anterior (re-projeção)
        if getattr(self, "_proj_timer", None) is not None:
            try:
                self.root.after_cancel(self._proj_timer)
            except tk.TclError:
                pass
            self._proj_timer = None

        # Remove qualquer composição anterior (anúncio imagem + texto): o
        # _imagem_rect_base velho redirecionaria a imagem pura para a posição
        # do editor em vez de centralizá-la.
        self._limpar_camada_imagem()

        # Guarda a temperatura exibida para restaurar depois
        self._temp_salvo = self._current_temp

        self.mostrando_letra = True
        self._em_slides = False
        self._mostrando_imagem = True
        self._mostrando_imagem_com_texto = False
        self.mostrando_relogio = False

        # Exibe a janela e aplica o fundo/opacidade configurados
        if not self._is_visible:
            self.root.deiconify()
            self._is_visible = True
        alpha = self._alpha_projecao()
        if self._current_alpha != alpha:
            self.root.attributes('-alpha', alpha)
            self._current_alpha = alpha
        self._aplicar_fundo_projecao()
        self.root.lift()

        # Esconde temperatura, referência e hora para exibir só a imagem
        self.canvas.itemconfig(self.temp_text, text="", state="hidden")
        self.canvas.itemconfig(self.ref_text, text="", state="hidden")
        self.canvas.itemconfig(self.overlay_text, text="", state="hidden")

        try:
            with Image.open(caminho) as img_src:
                img_orig = img_src.convert("RGBA")
        except Exception as e:
            print(f"⚠️ Não foi possível abrir a imagem {caminho}: {e}")
            self._retornar_ao_relogio()
            return False

        # Guarda o original para permitir ajustar o tamanho em tempo real
        # (botões "🖼️ −/+" na tela do operador) re-renderizando por cima.
        self._imagem_orig_pil = img_orig
        self._imagem_escala = 1.0
        try:
            ok = self._renderizar_imagem_projetada()
        except Exception as e:
            print(f"⚠️ Não foi possível exibir a imagem no telão: {e}")
            ok = False
        if not ok:
            self._retornar_ao_relogio()
            return False
        return True

    def _renderizar_imagem_projetada(self) -> bool:
        """Renderiza a imagem projetada com a escala atual.

        Quando o anúncio está em modo composição (imagem + texto em camadas
        vivas), renderiza SOMENTE a camada da imagem — o texto continua no
        canvas (overlay_text) intacto. Assim os botões "🖼️ −/+" do painel
        redimensionam apenas a imagem em tempo real.
        """
        orig = getattr(self, "_imagem_orig_pil", None)
        if orig is None or not getattr(self, "_mostrando_imagem", False):
            return False
        try:
            from PIL import Image, ImageTk
        except Exception:
            return False
        w = self.canvas.winfo_width() or self._monitor.width
        h = self.canvas.winfo_height() or self._monitor.height
        lar, alt = orig.size
        if lar <= 0 or alt <= 0:
            return False

        escala = float(getattr(self, "_imagem_escala", 1.0) or 1.0)
        rect = getattr(self, "_imagem_rect_base", None)
        if rect is not None:
            # Modo composição (imagem + texto): usa a posição/tamanho salvos
            # no editor (espaço virtual 1440x1080) e redimensiona ao redor
            # do ponto central — nunca escala o texto nem o fundo.
            base_x, base_y, base_w, base_h = rect
            novo_w = max(1, min(int(base_w * escala), w))
            novo_h = max(1, min(int(base_h * escala), h))
            cx = base_x + base_w // 2
            cy = base_y + base_h // 2
            pos_x = max(0, min(cx - novo_w // 2, max(0, w - novo_w)))
            pos_y = max(0, min(cy - novo_h // 2, max(0, h - novo_h)))
            tamanho = (max(1, novo_w), max(1, novo_h))
            pos = (pos_x, pos_y)
        else:
            # Imagem pura: redimensiona para caber na tela preservando a
            # proporção (comportamento original de projetar_imagem).
            fator = min(w / lar, h / alt) * escala
            tamanho = (max(1, int(lar * fator)), max(1, int(alt * fator)))
            pos = None

        redimensao = getattr(Image, "LANCZOS", None) or getattr(Image, "BICUBIC", None)
        img_final = orig.resize(tamanho, redimensao)
        try:
            # master=self.root: o telão tem um Tcl/Tk interpreter próprio; sem
            # isso a PhotoImage fica registrada no root da janela principal e
            # o canvas do telão não a enxerga (TclError "image doesn't exist").
            self._imagem_pil = ImageTk.PhotoImage(img_final, master=self.root)
            if getattr(self, "_imagem_item", None) is not None:
                try:
                    self.canvas.delete(self._imagem_item)
                except tk.TclError:
                    pass
                self._imagem_item = None
            if pos is None:
                pos = (w // 2, h // 2)
                self._imagem_item = self.canvas.create_image(
                    pos[0], pos[1], image=self._imagem_pil, anchor="center")
            else:
                self._imagem_item = self.canvas.create_image(
                    pos[0], pos[1], image=self._imagem_pil, anchor="nw")
        except Exception as e:
            print(f"⚠️ Não foi possível renderizar a imagem no telão: {e}")
            return False
        self.root.update_idletasks()
        return True

    def imagem_aumentar(self) -> bool:
        """Aumenta a imagem já projetada (redimensionamento ao vivo no telão)."""
        escala = float(getattr(self, "_imagem_escala", 1.0) or 1.0)
        self._imagem_escala = min(2.5, escala + 0.15)
        return self._renderizar_imagem_projetada()

    def imagem_diminuir(self) -> bool:
        """Diminui a imagem já projetada (redimensionamento ao vivo no telão)."""
        escala = float(getattr(self, "_imagem_escala", 1.0) or 1.0)
        self._imagem_escala = max(0.25, escala - 0.15)
        return self._renderizar_imagem_projetada()

    def projetar_imagem_com_texto(self, caminho: str, texto: str,
                                  config_midia: str = "") -> bool:
        """Projeta imagem + texto em CAMADAS separadas no telão.

        A imagem é posicionada/tamanhada conforme config_midia (espaço
        virtual 1440x1080 do editor) e o texto é desenhado por cima como
        camada de canvas (como nos hinos). Assim o operador pode:
          - "🖼️ −/+" redimensionar SÓ a imagem (escala ao vivo);
          - "A−/A+" redimensionar SÓ o texto (fonte ao vivo).
        Sem config_midia (legado), a imagem fica à direita ocupando 55% da
        área útil (mesmo layout lado a lado do compositor antigo).
        Retorna False se o arquivo for inválido/inexistente.
        """
        if not self.rodando or not caminho or not os.path.exists(caminho):
            return False
        try:
            from PIL import Image
        except Exception as e:
            print(f"⚠️ PIL indisponível para projetar imagem + texto: {e}")
            return False

        # Cancela retorno automático anterior (re-projeção)
        if getattr(self, "_proj_timer", None) is not None:
            try:
                self.root.after_cancel(self._proj_timer)
            except tk.TclError:
                pass
            self._proj_timer = None

        # Guarda a temperatura exibida para restaurar depois
        self._temp_salvo = self._current_temp

        self.mostrando_letra = True
        self._em_slides = False
        self._mostrando_imagem = True
        self._mostrando_imagem_com_texto = True
        self._imagem_escala = 1.0
        self.mostrando_relogio = False

        # Exibe a janela e aplica o fundo/opacidade configurados
        if not self._is_visible:
            self.root.deiconify()
            self._is_visible = True
        alpha = self._alpha_projecao()
        if self._current_alpha != alpha:
            self.root.attributes('-alpha', alpha)
            self._current_alpha = alpha
        self._aplicar_fundo_projecao()
        self.root.lift()

        # Esconde temperatura e referência (o texto do anúncio usa o overlay)
        self.canvas.itemconfig(self.temp_text, text="", state="hidden")
        self.canvas.itemconfig(self.ref_text, text="", state="hidden")
        self.canvas.itemconfig(self.overlay_text, text="", state="hidden")

        ok = self._composicao_anuncio(caminho, texto, config_midia)
        if not ok:
            self._retornar_ao_relogio()
            return False
        return True

    def _composicao_anuncio(self, caminho: str, texto: str,
                            config_midia: str = "") -> bool:
        """Composição imagem + texto em camadas (reutilizada pela projeção).

        Desenha a imagem (camada própria) e o texto (overlay na caixa
        ajustada) a partir de config_midia. Não altera os flags de estado
        (/em_slides, /mostrando_*); o chamador decide. Retorna False se o
        arquivo for inválido/inexistente (sem voltar ao relógio).
        """
        if not self.rodando or not caminho or not os.path.exists(caminho):
            return False
        try:
            from PIL import Image
        except Exception as e:
            print(f"⚠️ PIL indisponível para projetar imagem + texto: {e}")
            return False

        try:
            with Image.open(caminho) as img_src:
                img_orig = img_src.convert("RGBA")
        except Exception as e:
            print(f"⚠️ Não foi possível abrir a imagem {caminho}: {e}")
            return False

        w = self.canvas.winfo_width() or self._monitor.width
        h = self.canvas.winfo_height() or self._monitor.height

        # Área útil (margens do editor/compositor) para a imagem.
        margem_h = int(w * 0.04) or 40
        margem_v = int(h * 0.06) or 60
        area_w = max(100, w - margem_h * 2)
        area_h = max(100, h - margem_v * 2)

        cfg: dict = {}
        try:
            c = json.loads(config_midia or "{}")
            if isinstance(c, dict):
                cfg = c
        except (ValueError, TypeError, AttributeError):
            cfg = {}
        conf_w = int(cfg.get("w") or 0)
        conf_h = int(cfg.get("h") or 0)
        conf_x = int(cfg.get("x") or 0)
        conf_y = int(cfg.get("y") or 0)
        absoluto = conf_w > 0 and conf_h > 0 and conf_x > 0 and conf_y > 0

        ow, oh = img_orig.size
        if absoluto:
            # Formato novo: converte o espaço virtual 1440x1080 do editor.
            escala_x = w / 1440.0
            escala_y = h / 1080.0
            img_w = max(20, min(int(conf_w * escala_x), w))
            img_h = max(20, min(int(conf_h * escala_y), h))
            img_x = max(0, min(int(conf_x * escala_x), w - img_w))
            img_y = max(0, min(int(conf_y * escala_y), h - img_h))
        elif conf_w > 0 and conf_h > 0:
            # Config legada (320x250 sem posição): imagem à direita, 55%.
            frac = max(0.20, min(0.75, conf_w / (conf_w + 200)))
            asp = ow / max(1, oh)
            iw = max(120, int(area_w * frac))
            ih = int(iw / asp)
            if ih > area_h:
                ih = int(area_h)
                iw = max(120, int(ih * asp))
            img_w = max(20, min(iw, w))
            img_h = max(20, min(ih, h))
            img_x = max(0, min(w - margem_h - img_w, w - img_w))
            img_y = margem_v + (area_h - img_h) // 2
        else:
            # Sem configuração: mesma regra do compositor (lado a lado 55%).
            asp = ow / max(1, oh)
            iw = max(120, int(area_w * 0.55))
            ih = int(iw / asp)
            if ih > area_h:
                ih = int(area_h)
                iw = max(120, int(ih * asp))
            img_w = max(20, min(iw, w))
            img_h = max(20, min(ih, h))
            img_x = max(0, min(w - margem_h - img_w, w - img_w))
            img_y = margem_v + (area_h - img_h) // 2

        self._imagem_rect_base = (img_x, img_y, img_w, img_h)
        self._imagem_orig_pil = img_orig

        # Anúncio de imagem nunca mostra temperatura/referência da Bíblia.
        self.canvas.itemconfig(self.temp_text, text="", state="hidden")
        self.canvas.itemconfig(self.ref_text, text="", state="hidden")

        # Texto como digitado pelo usuário, dentro da caixa ajustada no editor.
        texto = (texto or "").strip()
        if not texto:
            # Slide só de imagem: esconde o texto de um slide anterior
            # (overlay_text foi usado pela projeção/tela anterior).
            self.canvas.itemconfig(self.overlay_text, text="", state="hidden")
            self._current_text = ""
        self._composicao_aspect_imagem = ow / max(1.0, oh)
        caixa = _caixa_texto_config(config_midia, texto,
                                    aspect_imagem=ow / max(1.0, oh))
        escala_x = w / 1440.0
        escala_y = h / 1080.0
        cx = max(0, min(int(caixa["x"] * escala_x), w - 1))
        cy = max(0, min(int(caixa["y"] * escala_y), h - 1))
        cw = max(40, min(int(caixa["w"] * escala_x), w - cx))
        ch = max(40, min(int(caixa["h"] * escala_y), h - cy))
        self._texto_box = (cx, cy, cw, ch)
        self._texto_escala = float(caixa.get("s") or 1.0)
        self._texto_largura_base = None
        if texto:
            self._desenhar_texto_anuncio(texto)

        try:
            ok = self._renderizar_imagem_projetada()
        except Exception as e:
            print(f"⚠️ Não foi possível exibir a imagem + texto no telão: {e}")
            ok = False
        return ok

    def _desenhar_texto_anuncio(self, texto: str) -> None:
        """Desenha o texto do anúncio (caixa) no telão, respeitando a escala.

        O texto é desenhado centralizado na caixa (posição/tamanho salvos no
        editor, tx/ty/tw/th) com fonte proporcional à altura da caixa; a
        escala ('ts') é aplicada em tempo real pelos botões A−/A+ do painel.
        A cor segue a configuração "🎨 Projeção" (cor do texto), como no
        modo só-texto.
        """
        cfg = getattr(self, "_proj_cfg", None)
        if cfg is None:
            self.configurar_projecao()
            cfg = getattr(self, "_proj_cfg", None)
        cor_texto = (cfg or {}).get("cor", "#FFFFFF") or "#FFFFFF"
        cx, cy, cw, ch = self._texto_box
        escala = float(getattr(self, "_texto_escala", 1.0) or 1.0)
        base_pct = 0.10 * escala
        fonte_pil, linhas = _calcular_texto_em_caixa(
            texto, cw, ch, base_pct=base_pct)
        familia = _fonte_familia_do_pil(fonte_pil)
        pt = max(8, min(300, int(fonte_pil.size)))
        passo = fonte_pil.size + max(1, fonte_pil.size // 5)

        self.canvas.itemconfig(
            self.overlay_text,
            text="\n".join(linhas),
            font=(familia, pt, "bold"),
            fill=cor_texto,
            width=cw,
            justify="center",
            state="normal",
        )
        # Centraliza vertical e horizontalmente na caixa.
        topo = cy + (ch - passo * len(linhas)) // 2
        centro_x = cx + cw // 2
        centro_y = topo + (passo * len(linhas)) // 2
        self.canvas.coords(self.overlay_text, centro_x, centro_y)
        self._current_text = texto
        self._current_temp = ""
        self.root.update_idletasks()

    def _mostrar_slide(self, indice: int) -> bool:
        """Exibe o slide no índice dado (se válido) e retorna True."""
        if not self._slides:
            return False
        if indice < 0 or indice >= len(self._slides):
            return False
        self._slide_index = indice
        slide = self._slides[indice]
        if isinstance(slide, dict):
            # Anúncio multi-slide texto+imagem (ou só texto por slide).
            texto = (slide.get("texto") or "").strip()
            caminho = (slide.get("imagem") or "").strip()
            if caminho and os.path.exists(caminho):
                self._mostrando_imagem = True
                self._mostrando_imagem_com_texto = True
                ok = self._composicao_anuncio(
                    caminho, texto, slide.get("config") or "")
                if ok:
                    # Lembra que ainda estamos em slides (não em imagem única):
                    # a navegação por setas continua valendo para o próximo.
                    self._em_slides = True
                    return True
                # Se a composição falhar, mostra ao menos o texto.
                self._limpar_camada_imagem()
            else:
                self._limpar_camada_imagem()
            self._desenhar_texto_no_canvas(texto or "ANÚNCIO")
            return True
        if isinstance(slide, tuple):
            texto, ref = slide
        else:
            texto, ref = slide, ""
        self._desenhar_texto_no_canvas(texto, referencia=ref)
        return True

    def slide_proximo(self) -> bool:
        """Avança para o próximo slide.

        Se já estiver no último slide, encerra a apresentação como a tecla
        Esc (volta o relógio + temperatura ao telão) e retorna True.
        """
        if not getattr(self, "_em_slides", False):
            return False
        if self._slide_index >= len(self._slides) - 1:
            self.parar_projecao()
            return True
        return self._mostrar_slide(self._slide_index + 1)

    def slide_anterior(self) -> bool:
        """Volta para o slide anterior (retorna False se não houver)."""
        if not getattr(self, "_em_slides", False):
            return False
        return self._mostrar_slide(self._slide_index - 1)

    def _ao_pressionar_esc(self, event: object = None) -> Optional[str]:
        """Esc durante projeção encerra a projeção e volta o relógio ao telão.

        Fora de uma projeção, mantém o comportamento de fechar a janela.
        """
        if getattr(self, "mostrando_letra", False):
            self.parar_projecao()
            return "break"
        self.fechar()
        return None

    def _retornar_ao_relogio(self) -> None:
        """Retorna relógio + temperatura ao telão ao fim da projeção."""
        self._proj_timer = None
        if not getattr(self, "mostrando_letra", False):
            return
        self.mostrando_letra = False
        self._em_slides = False
        self._slides = []
        self._slide_index = 0
        self.mostrando_relogio = True
        # Limpa a projeção de imagem (se houver)
        if getattr(self, "_imagem_item", None) is not None:
            try:
                self.canvas.delete(self._imagem_item)
            except tk.TclError:
                pass
            self._imagem_item = None
        self._imagem_pil = None
        self._imagem_orig_pil = None
        self._imagem_escala = 1.0
        self._imagem_rect_base = None
        self._texto_largura_base = None
        self._texto_box = (0, 0, 100, 100)
        self._texto_escala = 1.0
        self._mostrando_imagem = False
        self._mostrando_imagem_com_texto = False
        # Remove a imagem de fundo da projeção (o modo relógio usa a própria
        # cor de fundo configurada no "Configura Relógio").
        if getattr(self, "_fundo_imagem_item", None) is not None:
            try:
                self.canvas.delete(self._fundo_imagem_item)
            except tk.TclError:
                pass
            self._fundo_imagem_item = None
        self._fundo_imagem_to_tk = None
        self._fundo_imagem_caminho = ""
        # Restaura a aparência padrão do relógio no canvas: fonte Digital-7,
        # cor, e posições originais de hora e temperatura (a projeção troca a
        # fonte e move o texto para o centro da tela).
        self._aplicar_cores_relogio()
        self.canvas.itemconfig(self.overlay_text, width=0,
                               font=self._font_hora, state="normal")
        self.canvas.itemconfig(self.temp_text, width=0,
                               font=self._font_temp)
        self.canvas.itemconfig(self.ref_text, text="", state="hidden")
        self.canvas.coords(self.overlay_text, self._cx, self._cy_hora)
        self.canvas.coords(self.temp_text, self._cx, self._cy_temp)
        self._font_temp_exib = None
        self._font_temp_exib_texto = None
        self._current_text = ""
        self._current_temp = ""
        temp = getattr(self, "_temp_salvo", "") or ""
        self.mostrar_relogio(datetime.now().strftime("%H:%M"), temp)
        self.root.update_idletasks()

    def parar_projecao(self) -> None:
        """Encerra a projeção de texto e restaura o relógio imediatamente."""
        if getattr(self, "_proj_timer", None) is not None:
            try:
                self.root.after_cancel(self._proj_timer)
            except tk.TclError:
                pass
            self._proj_timer = None
        if not getattr(self, "mostrando_letra", False):
            return
        self._retornar_ao_relogio()

    def update(self) -> None:
        """Atualiza a janela com processamento mínimo."""
        if self.rodando:
            try:
                # update_idletasks é mais leve que update() - processa apenas
                # eventos pendentes de redesenho, não a fila de eventos completa
                self.root.update_idletasks()
            except tk.TclError:
                pass

    def fechar(self, event: object = None) -> None:
        self.rodando = False
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _exibir_hora_inicial(self, temperatura: str = "") -> None:
        """Exibe a hora atual e temperatura no telão logo após a criação."""
        hora = datetime.now().strftime("%H:%M")
        self.canvas.itemconfig(self.overlay_text, text=hora, state="normal")
        self._current_text = hora
        if temperatura:
            self.canvas.itemconfig(
                self.temp_text,
                text=temperatura,
                font=self._fonte_temp_para_texto(temperatura),
                state="normal",
            )
            self._current_temp = temperatura
        # update_idletasks é mais leve que update()
        self.root.update_idletasks()

# ────────────────────────────────────────────────────────────────────
# PLAYER DE MÍDIA (mantido)
# ────────────────────────────────────────────────────────────────────


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
    _duracao_cache: Dict[str, float] = {}
    _duracao_cache_lock = threading.Lock()
    _DURACAO_CACHE_MAX: int = 256
    # Mapeamento player -> D-Bus (constante de classe, evita dict recriado)
    _MPRIS_DESTS: dict[str, str] = {
        "smplayer": "org.mpris.MediaPlayer2.smplayer",
        "vlc": "org.mpris.MediaPlayer2.vlc",
    }

    def __init__(self, monitor_index: int = 1, player_cmd: str = PLAYER_PADRAO,
                 telao: Optional[TelaoWindow] = None) -> None:
        self.playlist: list[str] = []
        self.index: int = 0
        self.is_playing: bool = False
        self.is_paused: bool = False
        self._process: Optional[subprocess.Popen] = None
        self._process_lock: threading.Lock = threading.Lock()
        self.monitor_index: int = monitor_index
        self.player_cmd: str = player_cmd
        self.tempo_inicio: Optional[float] = None
        self.tempo_acumulado: float = 0.0
        self.duracao_total: Optional[float] = None
        self._player_pid: Optional[int] = None
        # Flag para evitar que _monitorar dispare "ended" quando matamos
        # o processo intencionalmente (via stop, próximo, anterior, tocar_indice)
        self._killed_intentionally: bool = False

        # Dependency Injection: TelaoWindow pode ser injetado externamente
        # para testes ou uso compartilhado. Fallback: cria internamente.
        self.telao = telao if telao is not None else TelaoWindow(monitor_index)
        self.on_state_change: Optional[Callable[[str], None]] = None
        self.on_track_change: Optional[Callable[[int, str], None]] = None
        # Referência para o root da janela principal (setado externamente)
        self._root_after: Optional[tk.Misc] = None
        # Inicia monitoramento assíncrono
        self._monitorar()
        # Garante que o telão fique com alpha e lower desde o início
        self.telao.root.lower()

    @property
    def process(self) -> Optional[subprocess.Popen]:
        """Retorna o processo do player (somente leitura)."""
        return self._process

    def _monitorar(self) -> None:
        """Verifica se o player terminou (sem polling, via after)."""
        processo_terminou = False
        with self._process_lock:
            if self._process is not None:
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
            self.telao.restaurar_tela()
            # Só dispara "ended" se o processo NÃO foi morto intencionalmente
            # (stop, próximo, anterior, tocar_indice já tratam a transição)
            if self.on_state_change and not self._killed_intentionally:
                self.on_state_change("ended")
            self._killed_intentionally = False  # Reset para próxima execução

        if self.telao.rodando:
            # Aguarda 500ms entre verificações (usa try para ser seguro)
            # Usa o after da janela principal (AppInterface.root) se disponível,
            # senão usa o do telão
            try:
                if hasattr(self, '_root_after') and self._root_after:
                    self._root_after.after(500, self._monitorar)
                else:
                    self.telao.root.after(500, self._monitorar)
            except tk.TclError:
                pass

    def carregar_playlist(self, arquivos: list[str]) -> None:
        """Define a playlist de arquivos."""
        self.playlist = list(arquivos) if arquivos else []
        self.index = 0

    def _get_monitor_geometry(self) -> tuple[int, int, int, int]:
        """Retorna (x, y, width, height) do monitor alvo."""
        try:
            monitors = get_monitors_config()
            if len(monitors) >= self.monitor_index:
                m = monitors[self.monitor_index - 1]
            elif len(monitors) > 1:
                m = monitors[1]
            else:
                m = monitors[0]
            return m.x, m.y, m.width, m.height
        except Exception:
            return 1920, 0, 1920, 1080

    def _matar_processo(self) -> None:
        """Mata o processo atual e TODOS os seus filhos (grupo de processos).
        
        Como usamos start_new_session=True ao criar o processo, o SMPlayer
        e o mplayer filho pertencem ao mesmo grupo (PGID = PID do pai).
        Matar o grupo inteiro garante que o áudio pare.
        """
        with self._process_lock:
            proc = self._process
            self._process = None
            self._player_pid = None

        if proc is None:
            return

        self._killed_intentionally = True
        pid = proc.pid
        print(f"🛑 Encerrando processo {pid} (grupo)...")

        if _eh_windows():
            # Windows: não existem grupos de processo nem os sinais POSIX.
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
            print(f"Erro ao encerrar processo {pid}: {e}")
            try:
                os.kill(pid, signal.SIGKILL)
            except (OSError, PermissionError):
                pass

    def _obter_duracao_arquivo(self, arquivo: str) -> Optional[float]:
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
        """Inicia a reprodução de um arquivo no player externo (sem sleep)."""
        # Mata processo anterior
        self._matar_processo()

        if not os.path.exists(arquivo):
            print(f"❌ Arquivo não encontrado: {arquivo}")
            return False

        print(f"🎵 Tocando: {os.path.basename(arquivo)}")
        self.telao.preparar_video()
        self.tempo_acumulado = 0.0
        self.tempo_inicio = time.time()
        self.duracao_total = self._obter_duracao_arquivo(arquivo)

        mx, my, mw, mh = self._get_monitor_geometry()

        try:
            cmd = self._montar_comando_player(arquivo, mx, my, mw, mh)

            print(f"🎬 Executando: {' '.join(cmd)}")
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
            return True
        except Exception as e:
            print(f"❌ Erro ao iniciar player: {e}")
            return False

    def _montar_comando_player(
        self, arquivo: str, mx: int, my: int, mw: int, mh: int
    ) -> list[str]:
        """Monta o comando do player conforme o tipo configurado.
        
        ANTES de montar, verifica se o player existe no PATH.
        Se smplayer (padrão) não existir, tenta mpv (melhor alternativa),
        depois vlc, e só por último xdg-open.
        """
        player = self.player_cmd

        # Verifica se o player configurado existe no PATH
        if not self._player_existe(player):
            print(f"\u26a0\ufe0f Player '{player}' n\u00e3o encontrado no sistema!")
            # Tenta alternativas em ordem de prefer\u00eancia
            for alt in ["smplayer", "mpv", "vlc"]:
                if self._player_existe(alt):
                    print(f"   \u27a1\ufe0f Usando '{alt}' como alternativa")
                    player = alt
                    break
            else:
                print("   \u274c Nenhum player encontrado! "
                      "Usando o aplicativo padrão")
                if _eh_windows():
                    return ['cmd', '/c', 'start', '', arquivo]
                return ['xdg-open', arquivo]

        if player == "smplayer":
            return [
                'smplayer', '-close-at-end', '-fullscreen',
                arquivo,
            ]
        elif player == "vlc":
            return [
                'vlc', '--quiet', '--no-osd', '--no-video-title-show',
                '--play-and-exit', '--fullscreen',
                '--no-embedded-video',
                f'--video-x={mx}', f'--video-y={my}',
                f'--width={mw}', f'--height={mh}',
                arquivo,
            ]
        elif player == "mpv":
            return [
                'mpv', '--fullscreen', '--screen=1',
                '--really-quiet', '--no-terminal',
                f'--geometry={mw}x{mh}+{mx}+{my}',
                arquivo,
            ]
        else:
            if _eh_windows():
                # Abre com o aplicativo padrão do Windows (sem console).
                return ['cmd', '/c', 'start', '', arquivo]
            return ['xdg-open', arquivo]

    @staticmethod
    def _player_existe(player: str) -> bool:
        """Verifica se um player est\u00e1 dispon\u00edvel no PATH.
        
        Verifica tanto no PATH do ambiente atual quanto nos locais comuns
        do sistema (/usr/bin, /run/host/usr/bin para sandbox AppImage).
        """
        # 1. PATH padr\u00e3o
        if shutil.which(player) is not None:
            return True
        # 2. Caminhos absolutos comuns (incluindo sandbox AppImage)
        for path in ["/usr/bin", "/usr/local/bin", "/run/host/usr/bin"]:
            full = os.path.join(path, player)
            if os.path.exists(full) and os.access(full, os.X_OK):
                return True
        return False

    def _pausar_player(self) -> bool:
        """Pausa/continua o player externo.

        No Linux usa D-Bus (MPRIS) ou SIGSTOP/SIGCONT (fallback). No Windows
        não há esses mecanismos; o app apenas deixa o player seguir e o estado
        interno acompanha (o tempo decorrido continua correndo).
        """
        if not _eh_linux():
            return False
        # Tenta D-Bus com o player ativo primeiro (evita loop em ambos)
        dest = self._MPRIS_DESTS.get(self.player_cmd)
        if dest:
            try:
                subprocess.run(
                    ['dbus-send', '--type=method_call',
                     f'--dest={dest}',
                     '/org/mpris/MediaPlayer2',
                     'org.mpris.MediaPlayer2.Player.PlayPause'],
                    timeout=1, capture_output=True, env=_ambiente_sem_appimage()
                )
                return True
            except Exception:
                pass

        # Fallback: tenta o outro player
        other_dest = "org.mpris.MediaPlayer2.vlc" if dest == "org.mpris.MediaPlayer2.smplayer" else "org.mpris.MediaPlayer2.smplayer"
        try:
            subprocess.run(
                ['dbus-send', '--type=method_call',
                 f'--dest={other_dest}',
                 '/org/mpris/MediaPlayer2',
                 'org.mpris.MediaPlayer2.Player.PlayPause'],
                timeout=1, capture_output=True, env=_ambiente_sem_appimage()
            )
            return True
        except Exception:
            pass

        # Fallback SIGSTOP/SIGCONT
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

    def obter_tempo_decorrido(self) -> float:
        """Retorna o tempo decorrido em segundos."""
        if self.tempo_inicio is not None:
            return self.tempo_acumulado + (time.time() - self.tempo_inicio)
        return self.tempo_acumulado

    def sincronizar_tempo_dbus(self, player: str = "") -> None:
        """Sincroniza o tempo via D-Bus (SMPlayer ou VLC). Uma única chamada unificada."""
        # Sem D-Bus no Windows: o tempo decorrido é acompanhado localmente.
        if not _eh_linux() or not self.is_playing:
            return

        dest = player or self.player_cmd
        mpris_dest = self._MPRIS_DESTS.get(dest)

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
            position_us: Optional[int] = None

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

    # ── Controles principais ──────────────────────────────────────

    def play_pause(self) -> None:
        """Alterna entre play e pause (sem busy waiting)."""
        if self.is_playing and not self.is_paused:
            if self._pausar_player():
                self.is_paused = True
                if self.tempo_inicio is not None:
                    self.tempo_acumulado += time.time() - self.tempo_inicio
                    self.tempo_inicio = None
        elif self.is_paused:
            if self._pausar_player():
                self.is_paused = False
                self.is_playing = True
                self.tempo_inicio = time.time()
        else:
            if self.playlist and self.index < len(self.playlist):
                arquivo = self.playlist[self.index]
                if self._tocar_arquivo(arquivo):
                    if self.on_track_change:
                        self.on_track_change(self.index, arquivo)

    def stop(self) -> None:
        """Para o player completamente."""
        self._matar_processo()
        self.is_playing = False
        self.is_paused = False
        self.tempo_inicio = None
        self.tempo_acumulado = 0.0
        self.duracao_total = None
        self.telao.restaurar_tela()
        print("✅ Player parado")

    def proximo(self) -> bool:
        """Avança para o próximo item da playlist (sem sleep)."""
        if not self.playlist or self.index >= len(self.playlist) - 1:
            return False
        print("⏭ Indo para próximo...")
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
            print("⚠️ Não há item anterior")
            return False
        print("⏮ Voltando para anterior...")
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
        print(f"🎯 Tocando índice {indice}...")
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

# ────────────────────────────────────────────────────────────────────
# INTERFACE PRINCIPAL (REFATORADA)
# ────────────────────────────────────────────────────────────────────


def _numero_do_titulo(titulo: str) -> Optional[int]:
    """Extrai o número inicial do título de um hino ("11 - Nome")."""
    m = re.match(r"^\s*(\d+)", titulo or "")
    return int(m.group(1)) if m else None


def _montar_slides_letra(titulo: str, letra_completa: str) -> list:
    """Monta os slides de uma letra de hino (título + uma linha de verso por
    slide, em maiúsculas), no mesmo formato usado pela janela Hinos/Letras."""
    slides = []
    titulo = (titulo or "").strip().upper()
    if titulo:
        slides.append(titulo)
    letra = (letra_completa or "").strip()
    for verso in re.split(r'\n\s*\n', letra):
        for linha in verso.split('\n'):
            linha = linha.strip().upper()
            if linha:
                slides.append(linha)
    if not slides:
        slides = [titulo or "HINO"]
    return slides


def _buscar_hino_por_termo(termo: str) -> List[Dict]:
    """Busca hino por número no início do título ou por trecho (título/artista).

    Ex.: '46' ou '46 - Dia de Chuva' encontra o hino cujo título começa com o
    número 46; qualquer outro termo busca por título/artista/letra (LIKE).
    """
    termo = (termo or "").strip()
    if not termo:
        return []
    m = re.match(r"^\s*(\d+)", termo)
    if m:
        num = int(m.group(1))
        rows = [r for r in db_query("SELECT * FROM letras WHERE ativo = 1 ORDER BY titulo")
                if _numero_do_titulo(r["titulo"]) == num]
        if rows:
            return rows
    busca_like = f"%{termo}%"
    return db_query(
        "SELECT * FROM letras WHERE ativo = 1 AND "
        "(titulo LIKE ? OR artista LIKE ? OR letra_completa LIKE ?) "
        "ORDER BY titulo", (busca_like, busca_like, busca_like))


def _buscar_midia_por_termo(termo: str, tipo: str = 'video') -> List[Dict]:
    """Busca mídia (video/audio) por número no início do nome ou por trecho.

    Para termos numéricos, prioriza correspondência com o nome (ex.: '46'
    acha '46 - Dia de Chuva'); só cai no id interno da tabela caso nenhum
    nome comece pelo número. Isso evita que o id do banco (não relacionado
    ao número do hino) seja escolhido por engano.
    """
    termo = (termo or "").strip()
    if not termo:
        return []
    if termo.isdigit():
        num = termo
        rows = db_query(
            "SELECT * FROM midia WHERE ativo = 1 AND tipo = ? AND ("
            "nome_exibicao = ? OR nome_exibicao LIKE ? OR nome_exibicao LIKE ?"
            ") ORDER BY nome_exibicao",
            (tipo, num, f"{num} -%", f"{num}-%"))
        if not rows:
            rows = db_query(
                "SELECT * FROM midia WHERE ativo = 1 AND tipo = ? AND id = ?",
                (tipo, num))
        return rows
    busca_like = f"%{unicodedata.normalize('NFC', termo).casefold()}%"
    return db_query(
        "SELECT * FROM midia WHERE ativo = 1 AND tipo = ? AND ("
        "LOWER(nome_exibicao) LIKE ? OR LOWER(nome_original) LIKE ?"
        ") ORDER BY nome_exibicao", (tipo, busca_like, busca_like))


# ────────────────────────────────────────────────────────────────────
# ANÚNCIOS — ARMAZENAMENTO EM ARQUIVO JSON (FORA DO BANCO DE DADOS)
# ────────────────────────────────────────────────────────────────────


def _carregar_anuncios_json() -> List[Dict]:
    """Lê ~/.navepro/anuncios.json e devolve a lista de anúncios.

    O arquivo fica permanentemente FORA do banco de dados: cada anúncio é
    um dict {id, titulo, categoria, texto, criado_em}.
    """
    try:
        with open(ANUNCIOS_FILE, "r", encoding="utf-8") as f:
            dados = json.load(f)
        if isinstance(dados, list):
            return [d for d in dados if isinstance(d, dict)]
    except (OSError, ValueError):
        pass
    return []


def _salvar_anuncios_json(anuncios: List[Dict]) -> bool:
    """Persiste a lista de anúncios em ~/.navepro/anuncios.json.

    Retorna True em caso de sucesso (ou False se o disco recusar a gravação).
    """
    try:
        with open(ANUNCIOS_FILE, "w", encoding="utf-8") as f:
            json.dump(anuncios, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        print(f"⚠️ Erro ao salvar anúncios: {e}")
        return False


# ────────────────────────────────────────────────────────────────────
# ANÚNCIOS — PERSISTÊNCIA NO BANCO SQLite (a partir desta versão)
# ────────────────────────────────────────────────────────────────────
#
# O arquivo anuncios.json legado continua existindo e é migrado UMA vez
# para a tabela "anuncios" (não é mais usado para leitura/escrita).


def _tipo_midia_para_arquivo(caminho: str) -> str:
    """Classifica um arquivo para anúncio: 'video' | 'audio' | 'imagem' | ''."""
    ext = os.path.splitext(caminho)[1].lower()
    if ext in EXTENSOES_VIDEO:
        return "video"
    if ext in EXTENSOES_AUDIO:
        return "audio"
    if ext in SUFIXOS_IMAGEM:
        return "imagem"
    return ""


def _copiar_arquivo_uploads(caminho: str) -> Optional[str]:
    """Copia o arquivo para UPLOAD_FOLDER evitando colisões de nome.

    Retorna o caminho de destino (ou o próprio caminho se já estiver na
    pasta de uploads); None se a cópia falhar.
    """
    try:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        nome = os.path.basename(caminho)
        destino = os.path.join(UPLOAD_FOLDER, nome)
        if os.path.normcase(os.path.abspath(caminho)) == os.path.normcase(os.path.abspath(destino)):
            return destino
        base, ext = os.path.splitext(nome)
        contador = 1
        while os.path.exists(destino):
            destino = os.path.join(UPLOAD_FOLDER, f"{base}_{contador}{ext}")
            contador += 1
        shutil.copy2(caminho, destino)
        return destino
    except OSError as e:
        print(f"⚠️ Erro ao copiar para uploads: {e}")
        return None


def _listar_anuncios_db(busca: str = "") -> List[Dict]:
    """Lista os anúncios ativos da tabela 'anuncios' (SQLite)."""
    termo = (busca or "").strip().lower()
    try:
        if termo:
            como = f"%{termo}%"
            rows = db_query(
                "SELECT * FROM anuncios WHERE ativo = 1 AND "
                "(LOWER(titulo) LIKE ? OR LOWER(categoria) LIKE ? OR LOWER(texto) LIKE ?) "
                "ORDER BY id DESC", (como, como, como))
        else:
            rows = db_query("SELECT * FROM anuncios WHERE ativo = 1 ORDER BY id DESC")
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"⚠️ Erro ao listar anúncios: {e}")
        return []


def _buscar_anuncio_por_ref(ref_id: object) -> Optional[dict]:
    """Busca um anúncio ativo pelo id da tabela 'anuncios' (None se não achar)."""
    try:
        rid = int(ref_id) if ref_id is not None else None
    except (TypeError, ValueError):
        return None
    if not rid:
        return None
    for a in _listar_anuncios_db():
        if int(a.get('id') or 0) == rid:
            return a
    return None


def _buscar_anuncio_por_termo(termo: str) -> List[dict]:
    """Busca anúncio por número (id ou nº inicial do título) ou por nome/trecho."""
    termo = (termo or "").strip()
    if not termo:
        return []
    anuncios = _listar_anuncios_db()
    if termo.isdigit():
        tid = int(termo)
        for a in anuncios:
            if int(a.get('id') or 0) == tid:
                return [a]
        return [a for a in anuncios
                if _numero_do_titulo(a.get('titulo') or '') == tid]
    norm = remover_acentos(termo).casefold()
    norm_anuncios = [
        (remover_acentos((a.get('titulo') or '')).casefold(), a)
        for a in anuncios]
    exatos = [a for n, a in norm_anuncios if n == norm]
    if exatos:
        return exatos
    por_titulo = [a for n, a in norm_anuncios if norm in n]
    if por_titulo:
        return por_titulo
    return [a for a in anuncios
            if norm in remover_acentos((a.get('categoria') or '')).casefold()
            or norm in remover_acentos((a.get('texto') or '')).casefold()]


def _montar_slides_anuncio_servico(anuncio: dict) -> list:
    """Monta os slides de um anúncio (slide 0 = título; 1 parágrafo por slide),
    no mesmo formato usado pela janela Anúncios."""
    titulo = (anuncio.get('titulo') or '').strip()
    texto = (anuncio.get('texto') or '').strip()
    paragrafos = [seg.strip() for seg in re.split(r'\n\s*\n', texto) if seg.strip()]
    slides = [titulo] if titulo else []
    for paragrafo in paragrafos:
        slides.append(paragrafo)
    if not slides:
        slides = [titulo or "ANÚNCIO"]
    return slides


def _projetar_anuncio_ordserv(telao: object, anuncio: dict) -> bool:
    """Projeta um anúncio no telão, como a janela Anúncios faz.

    O anúncio multi-slide (config_midia.mslides) projeta cada slide com seu
    texto E imagem; anúncio de imagem única usa imagem+texto; caso contrário
    projeta os slides de texto. Retorna True se algo foi projetado.
    """
    if not anuncio:
        return False
    tipo_an = (anuncio.get('tipo_midia') or 'slide').strip().lower()
    arquivo = (anuncio.get('arquivo_midia') or '')
    cfg_a: dict = {}
    try:
        cfg_a = json.loads(anuncio.get('config_midia') or '{}')
        if not isinstance(cfg_a, dict):
            cfg_a = {}
    except (ValueError, TypeError, AttributeError):
        cfg_a = {}
    if isinstance(cfg_a, dict) and isinstance(cfg_a.get("mslides"), list):
        # Anúncio multi-slide texto+imagem (cada slide pode ter imagem).
        slides = []
        for s in cfg_a["mslides"]:
            if not isinstance(s, dict):
                continue
            texto_s = (s.get("texto") or '').strip()
            imagem_s = (s.get("imagem") or '').strip()
            if not texto_s and not imagem_s:
                continue
            slides.append({"texto": texto_s, "imagem": imagem_s,
                           "config": s.get("config") or ''})
        if not slides:
            slides = [{"texto": "ANÚNCIO", "imagem": '', "config": ''}]
        telao.projetar_slides(slides)
        return True
    if tipo_an == 'imagem' and arquivo and os.path.exists(arquivo):
        if telao.projetar_imagem_com_texto(
                arquivo, (anuncio.get('texto') or '').strip(),
                anuncio.get('config_midia') or ''):
            return True
        if telao.projetar_imagem(arquivo):
            return True
        return False
    telao.projetar_slides(_montar_slides_anuncio_servico(anuncio))
    return True


def _proximo_id_anuncio_livre() -> int:
    """Menor id positivo ainda não usado na tabela 'anuncios'.

    Permite reaproveitar o menor número vazio após uma exclusão.
    """
    try:
        rows = db_query("SELECT id FROM anuncios ORDER BY id")
    except Exception:
        return None
    usados = {r["id"] for r in rows}
    cand = 1
    while cand in usados:
        cand += 1
    return cand


def _inserir_anuncio_db(dados: Dict) -> Optional[int]:
    """Insere um anúncio na tabela 'anuncios'. Retorna o id (None se falhar).

    Informa explicitamente o id = menor número livre, de forma que um
    anúncio deletado tenha seu número reaproveitado pelo próximo criado.
    """
    novo_id = _proximo_id_anuncio_livre()
    if not novo_id:
        print("⚠️ Não foi possível calcular um id livre para o anúncio.")
        return None
    try:
        db_execute(
            "INSERT INTO anuncios (id, titulo, categoria, texto, tipo_midia, "
            "arquivo_midia, nome_arquivo_midia, config_midia) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                novo_id,
                (dados.get("titulo") or "").strip(),
                (dados.get("categoria") or "").strip(),
                (dados.get("texto") or "").strip(),
                dados.get("tipo_midia") or "slide",
                dados.get("arquivo_midia") or "",
                dados.get("nome_arquivo_midia") or "",
                dados.get("config_midia") or "",
            ))
        return novo_id
    except Exception as e:
        print(f"⚠️ Erro ao inserir anúncio: {e}")
        return None


def _atualizar_anuncio_db(anuncio_id: int, dados: Dict) -> bool:
    """Atualiza um anúncio existente na tabela 'anuncios'."""
    try:
        db_execute(
            "UPDATE anuncios SET titulo = ?, categoria = ?, texto = ?, "
            "tipo_midia = ?, arquivo_midia = ?, nome_arquivo_midia = ?, "
            "config_midia = ? WHERE id = ?",
            (
                (dados.get("titulo") or "").strip(),
                (dados.get("categoria") or "").strip(),
                (dados.get("texto") or "").strip(),
                dados.get("tipo_midia") or "slide",
                dados.get("arquivo_midia") or "",
                dados.get("nome_arquivo_midia") or "",
                dados.get("config_midia") or "",
                anuncio_id,
            ))
        return True
    except Exception as e:
        print(f"⚠️ Erro ao atualizar anúncio: {e}")
        return False


def _excluir_anuncios_db(ids) -> bool:
    """Remove definitivamente os anúncios com os ids informados.

    Usa DELETE (e não soft delete) justamente para o SQLite liberar os IDs,
    permitindo que novos anúncios reaproveitem os números vazios.
    """
    if not ids:
        return True
    try:
        marks = ", ".join("?" for _ in ids)
        db_execute(f"DELETE FROM anuncios WHERE id IN ({marks})", tuple(ids))
        return True
    except Exception as e:
        print(f"⚠️ Erro ao excluir anúncios: {e}")
        return False


def _migrar_anuncios_do_json() -> int:
    """Migra UMA vez os anúncios legados de anuncios.json para o SQLite.

    Roda apenas se a tabela 'anuncios' estiver vazia e o arquivo JSON tiver
    dados (idempotente). Retorna a quantidade importada.
    """
    if not os.path.exists(ANUNCIOS_FILE):
        return 0
    try:
        existentes = db_query("SELECT COUNT(*) AS n FROM anuncios WHERE ativo = 1")
        if existentes and existentes[0]["n"] > 0:
            return 0
    except Exception:
        return 0
    importados = 0
    for a in _carregar_anuncios_json():
        if _inserir_anuncio_db({
                "titulo": a.get("titulo", ""),
                "categoria": a.get("categoria", ""),
                "texto": a.get("texto", ""),
                "tipo_midia": "slide"}):
            importados += 1
    if importados:
        print(f"✅ {importados} anúncio(s) migrado(s) de anuncios.json para o banco.")
    return importados


# ────────────────────────────────────────────────────────────────────
# COMPOSIÇÃO IMAGEM + TEXTO (anúncios de imagem)
# ────────────────────────────────────────────────────────────────────
# Medição e ajuste de caixas de texto em espaço virtual 1440x1080,
# usados de forma IDÊNTICA pelo editor (prévia) e pelo telão (projeção).


def _carregar_fonte_pil(tamanho: int):
    """Carrega uma fonte Truetype (DejaVuSans) com fallback para a padrão."""
    try:
        from PIL import ImageFont
    except Exception:
        return None
    if _eh_windows():
        candidatos = [
            os.path.join(os.environ.get('WINDIR', 'C:/Windows'),
                         'Fonts', 'arialbd.ttf'),
            os.path.join(os.environ.get('WINDIR', 'C:/Windows'),
                         'Fonts', 'arial.ttf'),
        ]
    else:
        candidatos = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    for p in candidatos:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, tamanho)
            except Exception:
                continue
    return ImageFont.load_default()


def _quebrar_linhas_medindo(draw, texto: str, largura_max: int, fonte) -> List[str]:
    """Quebra o texto em linhas que cabem em 'largura_max' (medição real)."""
    linhas: List[str] = []
    for bloco in (texto or "").split("\n"):
        if not bloco.strip():
            linhas.append("")
            continue
        palavras = bloco.split()
        atual = ""
        for p in palavras:
            tent = f"{atual} {p}".strip()
            try:
                cabe = draw.textlength(tent, font=fonte) <= largura_max
            except Exception:
                cabe = len(tent) * fonte.size * 0.6 <= largura_max
            if cabe:
                atual = tent
            else:
                if atual:
                    linhas.append(atual)
                atual = p
        if atual:
            linhas.append(atual)
    return linhas


def _carregar_fonte_atual(draw, texto: str, largura_max: int, altura_max: int):
    """Escolhe a maior fonte cujo texto (quebrado) cabe na área."""
    for tamanho in (120, 96, 72, 64, 48, 40, 36, 32, 28, 24, 22, 20, 18, 16, 14, 12):
        fonte = _carregar_fonte_pil(tamanho)
        linhas = _quebrar_linhas_medindo(draw, texto, largura_max, fonte)
        tam_linha = fonte.size + max(1, fonte.size // 5)
        if tam_linha * len(linhas) <= altura_max:
            return fonte, linhas
    fonte = _carregar_fonte_pil(12)
    return fonte, _quebrar_linhas_medindo(draw, texto, largura_max, fonte)


_DUMMY_DRAW: list = [None]


def _draw_pil_reciclavel():
    """Devolve um objeto de desenho PIL reutilizável para medir texto."""
    from PIL import Image, ImageDraw
    if _DUMMY_DRAW[0] is None:
        _DUMMY_DRAW[0] = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    return _DUMMY_DRAW[0]


def _fonte_familia_do_pil(fonte) -> str:
    """Nome da família da fonte PIL (para usar no canvas do Tk)."""
    if fonte is None:
        return "Helvetica"
    try:
        return fonte.getname()[0] or "Helvetica"
    except Exception:
        return "Helvetica"


def _calcular_texto_em_caixa(texto: str, caixa_larg: int, caixa_alt: int,
                             base_pct: float = 0.10) -> tuple:
    """Calcula fonte + linhas para desenhar 'texto' dentro de uma caixa.

    Usado pelo editor de anúncio (prévia) e pelo telão de forma IDÊNTICA:
    a fonte é proporcional à ALTURA DA CAIXA (base_pct * caixa_alt) e as
    linhas são quebradas na largura da caixa. Se o texto não couber
    verticalmente, encolhe até caber (respeitando um mínimo legível).
    Retorna (fonte_pil, linhas).
    """
    desenho = _draw_pil_reciclavel()
    larg = max(60, caixa_larg)
    alt = max(60, caixa_alt)
    texto_fonte = (texto or "")
    base = max(12, int(round(alt * (base_pct or 0.10))))
    tamanhos = list(dict.fromkeys([base, 108, 88, 72, 60, 52, 44, 36, 30, 26, 22, 18, 14, 12]))
    for tam in tamanhos:
        tam = max(12, min(tam, 400))
        fonte = _carregar_fonte_pil(tam)
        linhas = _quebrar_linhas_medindo(desenho, texto_fonte, larg, fonte)
        tam_linha = fonte.size + max(1, fonte.size // 5)
        if tam_linha * max(1, len(linhas)) <= alt:
            return fonte, linhas
    fonte = _carregar_fonte_pil(12)
    return fonte, _quebrar_linhas_medindo(desenho, texto_fonte, larg, fonte)


def _caixa_texto_padrao(texto: str, area_larg: int, area_alt: int,
                        margem_h: int, margem_v: int,
                        aspect_imagem: Optional[float] = None, espaco: int = 20) -> dict:
    """Caixa inicial (espaço virtual 1440x1080) para o texto do anúncio.

    Usa o mesmo layout lado a lado do compositor legado (texto à esquerda,
    imagem à direita). O tamanho é escolhido para que o texto inicial couba
    exatamente como na projeção/composição antiga. Se 'aspect_imagem' for
    dado, a largura do texto reflete o espaço real que sobra após a imagem
    (55%) + espaçamento. Retorna dict com x/y/w/h (posição/tamanho da caixa)
    e s (fator de escala de fonte).
    """
    if aspect_imagem is not None and aspect_imagem > 0:
        asp = aspect_imagem
        img_w = max(120, int(area_larg * 0.55))
        img_h = int(img_w / asp)
        if img_h > area_alt:
            img_h = int(area_alt)
            img_w = max(120, int(img_h * asp))
        text_w = max(120, area_larg - img_w - max(0, espaco))
    else:
        text_w = max(120, int(area_larg * 0.55))
    texto_fonte = (texto or "")
    desenho = _draw_pil_reciclavel()
    fonte_enc, _ = _carregar_fonte_atual(desenho, texto_fonte, text_w,
                                         max(120, int(area_alt * 0.55)))
    passo = fonte_enc.size + max(1, fonte_enc.size // 5)
    altura_caixa = max(120, min(int(area_alt), passo * 4))
    largura_caixa = max(120, min(text_w, int(area_larg)))
    x = margem_h
    y = max(margem_v, (area_alt - altura_caixa) // 2)
    return {"x": x, "y": y, "w": largura_caixa, "h": altura_caixa, "s": 1.0}


def _caixa_texto_config(config_midia: str = "", texto: str = "",
                        aspect_imagem: Optional[float] = None) -> dict:
    """Lê a caixa de texto (tx/ty/tw/th/ts) do config_midia, com defaults.

    Retorna dict já preenchido com x/y/w/h/s (posição da caixa + escala de
    fonte). Para configs antigas sem caixa de texto usa o layout lado a lado
    (o mesmo do compositor legado), calculado conforme o espaço virtual
    1440x1080.
    """
    try:
        c = json.loads(config_midia or "{}") or {}
    except (ValueError, TypeError, AttributeError):
        c = {}
    if not isinstance(c, dict):
        c = {}
    tx = int(c.get("tx") or 0)
    ty = int(c.get("ty") or 0)
    tw = int(c.get("tw") or 0)
    th = int(c.get("th") or 0)
    if th > 0 and (tw > 0 or tx > 0):
        return {"x": tx, "y": ty, "w": tw, "h": th, "s": float(c.get("ts") or 1.0)}
    if not texto:
        return {"x": 0, "y": 0, "w": 0, "h": 0, "s": 1.0}
    mh = int(1440 * 0.04) or 40
    mv = int(1080 * 0.06) or 60
    area_larg = 1440 - mh * 2
    area_alt = 1080 - mv * 2
    if tw > 0 and th > 0:
        return {"x": tx, "y": ty, "w": tw, "h": th, "s": float(c.get("ts") or 1.0)}
    return _caixa_texto_padrao(texto, area_larg, area_alt, mh, mv,
                               aspect_imagem=aspect_imagem)


# ────────────────────────────────────────────────────────────────────
# ORDENS DE SERVIÇO — ARMAZENAMENTO EM ARQUIVO JSON
# ────────────────────────────────────────────────────────────────────
#
# A partir desta versão as ordens de serviço ficam em ~/.navepro/servicos.json
# (o banco servicos/itens_servico é migrado UMA vez e mantido como backup).


def _carregar_servicos_json() -> Dict:
    """Lê ~/.navepro/servicos.json e devolve a estrutura de ordens de serviço.

    Estrutura:
      {"servicos": [{"id", "nome", "data_servico", "criado_em", "itens": [
          {"id", "tipo", "referencia_id", "titulo_custom", "letra_snapshot",
           "duracao_estimada_segundos"}...]}],
       "_proximo_id_servico": int, "_proximo_id_item": int}
    """
    try:
        with open(SERVICOS_FILE, "r", encoding="utf-8") as f:
            dados = json.load(f)
        if isinstance(dados, dict) and isinstance(dados.get("servicos"), list):
            dados.setdefault("_proximo_id_servico", 1)
            dados.setdefault("_proximo_id_item", 1)
            # Remove a data automática (não editável) de versões anteriores.
            for _s in dados.get("servicos", []):
                if isinstance(_s, dict):
                    _s.pop("data_servico", None)
            return dados
    except (OSError, ValueError):
        pass
    return {"servicos": [], "_proximo_id_servico": 1, "_proximo_id_item": 1}


def _salvar_servicos_json(dados: Dict) -> bool:
    """Persiste as ordens de serviço em ~/.navepro/servicos.json (atômico)."""
    try:
        os.makedirs(os.path.dirname(SERVICOS_FILE), exist_ok=True)
        tmp = SERVICOS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SERVICOS_FILE)
        return True
    except OSError as e:
        print(f"⚠️ Erro ao salvar ordens de serviço: {e}")
        return False


def _migrar_servicos_do_banco() -> bool:
    """Migra UMA vez as ordens de serviço do SQLite para servicos.json.

    Se servicos.json ainda não existir e o banco tiver dados, copia tudo
    (idempotente). As tabelas servicos/itens_servico NÃO são apagadas:
    ficam como backup invisível (sem quebrar o reuso de IDs existente).
    """
    if os.path.exists(SERVICOS_FILE):
        return False
    try:
        rows = db_query(
            "SELECT id, nome, data_servico, criado_em FROM servicos "
            "WHERE ativo = 1 ORDER BY id")
    except Exception:
        return False
    if not rows:
        return False
    dados = {"servicos": [], "_proximo_id_servico": 1, "_proximo_id_item": 1}
    for r in rows:
        sid = r["id"]
        try:
            itens = db_query(
                "SELECT id, tipo, referencia_id, titulo_custom, letra_snapshot, "
                "duracao_estimada_segundos FROM itens_servico WHERE servico_id = ? "
                "ORDER BY ordem", (sid,))
        except Exception:
            itens = []
        novos_itens = []
        for it in itens or []:
            novos_itens.append({
                "id": it.get("id"),
                "tipo": it.get("tipo") or "slide",
                "referencia_id": it.get("referencia_id"),
                "titulo_custom": it.get("titulo_custom") or "",
                "letra_snapshot": it.get("letra_snapshot") or "",
                "duracao_estimada_segundos": it.get("duracao_estimada_segundos") or 0,
            })
            dados["_proximo_id_item"] = max(
                dados["_proximo_id_item"], (it.get("id") or 0) + 1)
        dados["servicos"].append({
            "id": sid,
            "nome": r["nome"],
            "data_servico": r.get("data_servico"),
            "criado_em": r.get("criado_em")
                         or datetime.now().isoformat(timespec="seconds"),
            "itens": novos_itens,
        })
        dados["_proximo_id_servico"] = max(dados["_proximo_id_servico"], sid + 1)
    if _salvar_servicos_json(dados):
        print(f"✅ Ordens de serviço migradas do banco para {SERVICOS_FILE}")
        return True
    return False


# Ponteiro de execução por serviço (janela "Ordem de Serviço"): cada clique
# em "Executar Serviço" reproduz APENAS o próximo item da lista e para.
# Chave = id do serviço (ou nome como fallback). Valor = índice do item
# que deve ser reproduzido no próximo clique.
_SERVICO_PROXIMO_ITEM: dict = {}


def _reordenar_itens_servico(itens: List[Dict], id_origem: int, id_destino: int) -> List[Dict]:
    """Move o item id_origem para a posição de id_destino, preservando o resto.

    Retorna a nova lista (mesma list se origem/destino inexistentes ou iguais).
    """
    nova = list(itens)
    idx_orig = next((i for i, it in enumerate(nova) if it.get("id") == id_origem), None)
    idx_dest = next((i for i, it in enumerate(nova) if it.get("id") == id_destino), None)
    if idx_orig is None or idx_dest is None or idx_orig == idx_dest:
        return nova
    item = nova.pop(idx_orig)
    nova.insert(idx_dest, item)
    return nova


def _extrair_texto_pdf(caminho: str) -> Optional[str]:
    """Extrai o texto de um PDF usando pypdf (com fallback para pdftotext).

    Retorna string de texto (páginas separadas por linha em branco) ou None
    se o PDF não tiver texto extraível (ex.: só imagens).
    """
    try:
        from pypdf import PdfReader
        leitor = PdfReader(caminho)
        paginas: List[str] = []
        for pagina in leitor.pages:
            texto = (pagina.extract_text() or "").strip()
            if texto:
                paginas.append(texto)
        if paginas:
            return "\n\n".join(paginas)
    except Exception as e:
        print(f"⚠️ pypdf falhou ao ler {caminho}: {e}")

    try:
        resultado = subprocess.run(
            ["pdftotext", "-layout", caminho, "-"],
            capture_output=True, text=True, timeout=30)
        if resultado.returncode == 0 and resultado.stdout.strip():
            return resultado.stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        print(f"⚠️ pdftotext falhou ao ler {caminho}: {e}")
    return None


def _carregar_icone(nome: str):
    """Carrega um PNG de icones/ como PhotoImage do Tk para usar em botões.

    Retorna None se o arquivo não existir ou o Tk falhar (fallback: o botão
    usa o caractere emoji/texto). Ícones PNG não dependem de fontes emoji do
    sistema — em qualquer Linux aparecem iguais (em vez de "sombra"/tofu).
    """
    try:
        from PIL import Image, ImageTk
        caminho = _caminho_recurso(os.path.join("icones", f"{nome}.png"))
        if not os.path.exists(caminho):
            return None
        with Image.open(caminho) as img:
            return ImageTk.PhotoImage(img)
    except Exception as e:
        print(f"⚠️ Ícone '{nome}' indisponível: {e}")
        return None


def _listar_pastas_arquivos_usuario(
        caminho: str,
        sufixos: Tuple[str, ...] = (".xml", ".txt", ".json")
) -> List[Tuple[str, str, bool]]:
    """Lista pastas e arquivos com os sufixos informados.

    Esconde tudo que começa com "." (pastas/arquivos ocultos do sistema).
    Retorna (caminho_completo, nome, é_pasta).
    """
    import os
    itens = []
    try:
        for e in os.scandir(caminho):
            if e.name.startswith("."):
                continue
            try:
                e_dir = e.is_dir()
            except OSError:
                continue
            if e_dir or e.name.lower().endswith(sufixos):
                itens.append((os.path.join(caminho, e.name), e.name, e_dir))
    except OSError:
        return []
    itens.sort(key=lambda t: (not t[2], t[1].lower()))
    return itens


def _escolher_arquivos_usuario(
        parent: Optional[tk.Toplevel],
        titulo: str,
        pasta_inicial: Optional[str] = None,
        sufixos: Tuple[str, ...] = (".xml", ".txt", ".json"),
) -> Tuple[str, ...]:
    """Seletor de arquivos que inicia no diretório do usuário (~).

    Mostra apenas as pastas/arquivos do usuário — esconde tudo que começa
    com "." (ocultos do sistema) e filtra os arquivos pelos sufixos dados.
    """
    import os
    pasta = {"atual": os.path.abspath(os.path.expanduser(pasta_inicial or "~"))}
    escolhidos: List[str] = []
    _itens: List[Tuple[str, bool]] = []  # (caminho, é_pasta)

    dial = tk.Toplevel(parent)
    dial.title(titulo)
    dial.geometry("560x500")
    dial.configure(bg='#0d1117')
    if parent is not None:
        dial.transient(parent)

    def _encurtar(texto: str, limite: int = 58) -> str:
        return texto if len(texto) <= limite else "…" + texto[-(limite - 1):]

    def _entrar(caminho: str) -> None:
        caminho = os.path.abspath(caminho)
        itens = _listar_pastas_arquivos_usuario(caminho, sufixos)
        _itens[:] = [(cam, is_dir) for cam, _, is_dir in itens]
        pasta["atual"] = caminho
        lbl_pasta.config(text=_encurtar(caminho))
        listbox.delete(0, tk.END)
        for cam, nome, is_dir in itens:
            listbox.insert(tk.END, f"{'📁 ' if is_dir else '📄 '}{nome}")

    def _subir() -> None:
        _entrar(os.path.dirname(pasta["atual"]))

    barra = tk.Frame(dial, bg='#161b22')
    barra.pack(fill='x', padx=6, pady=(8, 4))
    tk.Button(barra, text="⌂ Início", font=("Arial", 10, "bold"),
              bg='#21262d', fg='#c9d1d9', activebackground='#30363d',
              command=lambda: _entrar(os.path.expanduser("~"))
              ).pack(side='left', padx=(0, 4), pady=2)
    tk.Button(barra, text="⬆ Subir", font=("Arial", 10, "bold"),
              bg='#21262d', fg='#c9d1d9', activebackground='#30363d',
              command=_subir).pack(side='left', pady=2)
    lbl_pasta = tk.Label(barra, text="", fg='#f0c040', bg='#161b22',
                         font=("Arial", 10), anchor='w')
    lbl_pasta.pack(side='left', fill='x', expand=True, padx=6)

    listbox = tk.Listbox(dial, bg='#21262d', fg='#c9d1d9',
                         font=("Arial", 11), selectmode='extended',
                         highlightthickness=0, bd=0, activestyle='none')
    listbox.pack(fill='both', expand=True, padx=6, pady=4)
    scroll = tk.Scrollbar(listbox, orient='vertical', command=listbox.yview)
    listbox.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y')

    def _fechar_ok(*idxs: int) -> None:
        caminhos = [_itens[i][0] for i in idxs if not _itens[i][1]]
        escolhidos[:] = caminhos
        dial.destroy()

    def _clicar_duplo(event) -> None:
        idx = listbox.nearest(event.y)
        if not (0 <= idx < len(_itens)):
            return
        caminho, is_dir = _itens[idx]
        if is_dir:
            _entrar(caminho)
        else:
            _fechar_ok(idx)

    def _ok(_event=None) -> None:
        _fechar_ok(*listbox.curselection())

    def _cancelar(_event=None) -> None:
        escolhidos[:] = []
        dial.destroy()

    _entrar(pasta["atual"])
    listbox.bind("<Double-Button-1>", _clicar_duplo)
    dial.bind("<Return>", _ok)
    dial.bind("<Escape>", _cancelar)

    rodape = tk.Frame(dial, bg='#0d1117')
    rodape.pack(fill='x', padx=6, pady=6)
    tk.Button(rodape, text="Importar", font=("Arial", 11, "bold"),
              bg='#238636', fg='white', activebackground='#2ea043',
              command=_ok).pack(side='right', padx=(4, 0))
    tk.Button(rodape, text="Cancelar", font=("Arial", 11, "bold"),
              bg='#da3633', fg='white', activebackground='#f85149',
              command=_cancelar).pack(side='right')

    dial.grab_set()
    dial.wait_window()
    return tuple(escolhidos)


class AppInterface:
    """Interface gráfica principal do sistema de projeção."""

    def __init__(self) -> None:
        # Força GDK backend X11 para evitar conflito GTK Wayland no Ubuntu 22.04
        if 'GDK_BACKEND' not in os.environ:
            os.environ['GDK_BACKEND'] = 'x11'
        self.root = tk.Tk(className="NavePro")
        # Normaliza a escala de fontes (AppImage usa o python do sistema,
        # que pode ter 'tk scaling' baixo e deixar tudo minúsculo)
        _normalizar_escala_tk(self.root)
        # Força tema clam via Tcl (acima do ttk.Style)
        try:
            self.root.tk.call('tk', 'Theme', 'SetTheme', 'clam')
        except Exception:
            pass
        try:
            style = ttk.Style()
            style.theme_use('clam')
        except Exception:
            pass
        # tk_setPalette força base escura no Tk inteiro
        try:
            self.root.tk.call('tk_setPalette',
                '#0d1117', '#f0c040', '#6e40c9', '#ffffff', '#6e40c9', '#0d1117')
        except Exception:
            pass
        # option_add para tk.Button (GTK pode ignorar, mas tenta)
        self.root.option_add('*Button.background', '#21262d')
        self.root.option_add('*Button.foreground', '#f0c040')
        self.root.option_add('*Button.activeBackground', '#6e40c9')
        self.root.option_add('*Button.activeForeground', '#f0c040')
        self.root.option_add('*Button.highlightBackground', '#21262d')
        self.root.option_add('*Button.highlightColor', '#21262d')
        self.root.option_add('*Button.relief', 'flat')
        self.root.option_add('*Button.borderWidth', '0')
        self.root.option_add('*TCombobox*Listbox.background', '#21262d')
        self.root.option_add('*TCombobox*Listbox.foreground', '#c9d1d9')
        self.root.title("NAVE PRO - PRO")
        _aplicar_icone_janela(self.root)
        self.root.configure(bg='#0d1117')
        # Tamanho mínimo e estado inicial maximizado
        self.root.minsize(900, 800)
        self._maximizado = True
        try:
            monitors = get_monitors_config()
            if monitors:
                m = monitors[0]
                # Salva geometria do monitor para restaurar depois
                self._monitor_geo = (m.width, m.height, m.x, m.y)
                self.root.geometry(f"{m.width}x{m.height}+{m.x}+{m.y}")
            else:
                self._monitor_geo = None
                self.root.state('zoomed')
        except Exception:
            self._monitor_geo = None
            self.root.state('zoomed')

        self.config_data: dict[str, Any] = self.carregar_config()
        self.tema: str = self.config_data.get("tema", "escuro")
        if self.tema not in ("escuro", "claro"):
            self.tema = "escuro"
        self.monitor_index: int = self.config_data.get("monitor", 2)
        self.player_cmd: str = self.config_data.get("player", PLAYER_PADRAO)
        self.placeholder_busca: str = "Buscar hino... [BD]"
        self.arquivos_encontrados: list[str] = []
        self.arquivo_atual: Optional[str] = None
        
        self.cidade_salva: str = self.config_data.get("cidade", "")
        self.estado_salvo: str = self.config_data.get("estado", "")
        self.temperatura_atual: str = ""

        self._focus_timer: Optional[str] = None
        self._debounce_timer: Optional[str] = None

        print(f"🎮 Player: {self.player_cmd} | Monitor: {self.monitor_index}")

        # Garante recursos
        inicializar_banco()
        inicializar_config()
        garantir_pasta_uploads()
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)

        # Cache e worker (DatabaseManager carrega o cache na construção)
        self.db = DatabaseManager()
        self.search_worker = SearchWorker()
        self._versao_busca: int = 0
        self._ultima_lista: List[str] = []  # para evitar redesenho desnecessário

        # Cria o player e o telão (rápido - só cria as janelas Tk)
        self.player = MediaPlayer(self.monitor_index, self.player_cmd)
        self.player.on_state_change = self.quando_midia_terminar
        self.player.on_track_change = self.quando_faixa_muda
        self.player._root_after = self.root

        # Aplica configuração de aparência da projeção (letra/versículo)
        self.player.telao.configurar_projecao(self.config_data.get("projecao", {}))

        # Aplica configuração de aparência do relógio/temperatura
        self.player.telao.configurar_relogio(self.config_data.get("relogio", {}))

        self._criar_menu()

        # Corrige corrida do Tk 8.6 + XWayland (GNOME Wayland): força o flush
        # síncrono dos pedidos X pendentes (telão com alpha/fullscreen) antes de
        # criar os widgets da barra de controles. Sem isso, algumas distros
        # travam em _XReply/XSync ao medir fontes ("Falha de segmentação") e a
        # janela mal abre e fecha sozinha.
        try:
            self.root.update_idletasks()
        except Exception:
            pass

        self.criar_widgets()
        self.atualizar_relogio()

        # Aplica o tema (claro/escuro) lido do config logo após criar a UI,
        # sem alterar nenhuma cor hardcoded da construção padrão (escuro).
        self._aplicar_tema()

        # Mostra hora inicial no telão (sem temperatura ainda)
        self.player.telao._exibir_hora_inicial()

        # ============================================================
        # Tarefas pesadas executadas APÓS a interface aparecer
        # ============================================================
        # Inicia servidor HTTP (thread separada) e carrega temperatura
        # em paralelo, sem travar a interface
        self.root.after(100, self._inicializar_em_segundo_plano)

        self.root.bind('<space>', self._on_space)
        self.root.protocol("WM_DELETE_WINDOW", self.fechar)

        # Captura eventos de estado da janela (maximizar/minimizar)
        self.root.bind("<Map>", self._on_window_map)
        self.root.bind("<Configure>", self._on_window_configure)
        # Atalho F11 para alternar entre maximizado e 800x600
        self.root.bind("<F11>", lambda e: self._alternar_maximizar())
        # Atalho Ctrl+T para alternar o tema (claro/escuro)
        self.root.bind("<Control-t>", lambda e: self._alternar_tema())
        # Detecta duplo clique na barra de título (maximizar/restaurar)
        self.root.bind("<Double-Button-1>", self._on_title_double_click)

    def _on_window_map(self, event: object = None) -> None:
        """Quando a janela é mapeada (restaurada/minimizada)."""
        if not hasattr(self, '_maximizado'):
            return
        estado = self.root.state()
        if estado == 'zoomed':
            self._maximizado = True

    def _on_window_configure(self, event: object = None) -> None:
        """Detecta quando o usuário clica no botão Maximizar via mouse."""
        if not hasattr(self, '_maximizado'):
            return
        estado = self.root.state()
        if estado == 'zoomed':
            self._maximizado = True

    def _on_title_double_click(self, event: object = None) -> None:
        """Alterna maximizar/restaurar ao dar duplo clique na barra de título."""
        # Só ativa se o clique foi no topo da janela (barra de título)
        if event and event.y < 30:
            self._alternar_maximizar()



    @staticmethod
    def _chave_ordenacao_busca(rec: dict) -> tuple:
        """Chave de ordenação para resultados de busca (usa DatabaseManager)."""
        return DatabaseManager._compute_sort_key(rec.get('nome_exibicao', ''))

    # ── Foco e atalhos ────────────────────────────────────────────

    def _reset_focus_timer(self, event: object = None) -> None:
        """Reinicia o timer que remove o foco dos campos de entrada."""
        if self._focus_timer:
            self.root.after_cancel(self._focus_timer)
        self._focus_timer = self.root.after(5000, self._clear_focus_timeout)

    def _cancel_focus_timer(self) -> None:
        """Cancela o timer de foco."""
        if self._focus_timer:
            self.root.after_cancel(self._focus_timer)
            self._focus_timer = None

    def _clear_focus_timeout(self) -> None:
        """Remove o foco de campos para permitir atalhos globais."""
        self.root.focus_set()
        self._focus_timer = None

    def _on_space(self, event: object = None) -> str:
        """Espaço = Play/Pause (exceto quando digitando no campo de busca)."""
        focused = self.root.focus_get()
        if focused == self.entry_busca:
            conteudo = self.entry_busca.get().strip()
            if conteudo and conteudo != self.placeholder_busca:
                return "break"  # Deixa o Entry consumir o espaço
        self.player.play_pause()
        return "break"

    # ── Widgets de cidade ─────────────────────────────────────────

    def _on_focus_cidade(self) -> None:
        if self.entry_cidade.get() == "Cidade":
            self.entry_cidade.delete(0, tk.END)
            self.entry_cidade.config(fg='white')
        self._reset_focus_timer()

    def _on_focus_out_cidade(self) -> None:
        if not self.entry_cidade.get().strip():
            self.entry_cidade.delete(0, tk.END)
            self.entry_cidade.insert(0, "Cidade")
            self.entry_cidade.config(fg='gray')
        self._cancel_focus_timer()

    def _on_focus_estado(self) -> None:
        if self.entry_estado.get() == "UF":
            self.entry_estado.delete(0, tk.END)
            self.entry_estado.config(fg='white')
        self._reset_focus_timer()

    def _on_focus_out_estado(self) -> None:
        if not self.entry_estado.get().strip():
            self.entry_estado.delete(0, tk.END)
            self.entry_estado.insert(0, "UF")
            self.entry_estado.config(fg='gray')
        self._cancel_focus_timer()

    def _on_focus_in(self, event: object = None) -> None:
        if self.entry_busca.get() == self.placeholder_busca:
            self.entry_busca.delete(0, tk.END)
            self.entry_busca.config(fg='#F5BE08')
        self._reset_focus_timer()

    def _on_focus_in_busca(self, event: object = None) -> None:
        """FocusIn do campo de busca - destaca borda e mostra botão X."""
        if self.entry_busca.get() == self.placeholder_busca:
            self.entry_busca.delete(0, tk.END)
            self.entry_busca.config(fg='#f0c040')
        # Mostra botão X
        self._clear_btn.pack(side='left', padx=(0, 8))
        # Destaca borda do card
        try:
            busca_card = self.entry_busca.master.master
            busca_card.config(highlightbackground='#6e40c9')
        except Exception:
            pass
        self._reset_focus_timer()

    def _on_focus_out_busca(self, event: object = None) -> None:
        """FocusOut do campo de busca - restaura borda."""
        termo = self.entry_busca.get().strip()
        if not termo or termo == self.placeholder_busca:
            self.entry_busca.delete(0, tk.END)
            self.entry_busca.insert(0, self.placeholder_busca)
            self.entry_busca.config(fg='#8b949e')
            self._clear_btn.pack_forget()
        try:
            busca_card = self.entry_busca.master.master
            busca_card.config(highlightbackground='#30363d')
        except Exception:
            pass
        self._cancel_focus_timer()

    def _limpar_busca(self, event: object = None) -> None:
        """Limpa o campo de busca e redefine placeholder."""
        self.entry_busca.delete(0, tk.END)
        self.entry_busca.insert(0, self.placeholder_busca)
        self.entry_busca.config(fg='#8b949e')
        self._clear_btn.pack_forget()
        try:
            busca_card = self.entry_busca.master.master
            busca_card.config(highlightbackground='#30363d')
        except Exception:
            pass
        self.arquivos_encontrados = []
        self.player.carregar_playlist([])
        self.atualizar_lista()
        self.root.focus_set()

    def _on_entry_keyrelease(self, event: object) -> None:
        """Handler único para KeyRelease no entry_busca."""
        self.on_busca_digitada(event)
        self._reset_focus_timer(event)

    def _on_focus_out(self, event: object = None) -> None:
        if not self.entry_busca.get().strip():
            self.entry_busca.delete(0, tk.END)
            self.entry_busca.insert(0, self.placeholder_busca)
            self.entry_busca.config(fg='#F5BE08')
        self._cancel_focus_timer()

    # ── Configurações ─────────────────────────────────────────────

    def carregar_config(self) -> dict[str, Any]:
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def salvar_config_projecao(self, cfg: dict) -> None:
        """Persiste a configuração de aparência da projeção e aplica ao telão."""
        self.config_data["projecao"] = cfg
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config_data, f, indent=2)
        except Exception as e:
            print(f"Erro ao salvar config de projeção: {e}")
        if self.player and self.player.telao:
            self.player.telao.configurar_projecao(cfg)

    def abrir_config_projecao_dialogo(self, parent=None,
                                      mostrar_cor_ref: bool = False) -> None:
        """Abre a janela de ajuste da aparência da projeção no telão.

        Compartilhada entre as janelas de Anúncios, Hinos e de Bíblia.
        A opção "Cor da referência bíblica" só faz sentido onde há Bíblia
        para projetar, por isso aparece somente com mostrar_cor_ref=True.
        """
        janela = parent or self.root
        cfg_atual = dict(getattr(self.player.telao, "_proj_cfg", {}))
        cfg_atual.setdefault("fonte", "Montserrat")
        cfg_atual.setdefault("tamanho_pct", 5.0)
        cfg_atual.setdefault("cor", "#FFFFFF")
        cfg_atual.setdefault("duracao_seg", 30)
        cfg_atual.setdefault("cor_ref", "#A0A0A0")
        cfg_atual.setdefault("cor_fundo", "#000000")
        cfg_atual.setdefault("fundo_opaco", True)
        cfg_atual.setdefault("fundo_imagem", "")

        cfg_win = tk.Toplevel(janela)
        cfg_win.title("🎨 Aparência da Projeção (Telão)")
        cfg_win.geometry("620x760")
        cfg_win.configure(bg='#0d1117')
        cfg_win.transient(janela)
        cfg_win.after(50, cfg_win.grab_set)

        c_main = tk.Frame(cfg_win, bg='#0d1117')
        c_main.pack(fill='both', expand=True, padx=15, pady=15)

        tk.Label(c_main, text="🎨 Configuração da Projeção",
                 font=("Arial", 15, "bold"), fg='#f0c040', bg='#0d1117'
                 ).pack(pady=(0, 12))

        # ── Fonte ──
        tk.Label(c_main, text="Fonte:", font=("Arial", 11, "bold"),
                 fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x')
        var_fonte = tk.StringVar(value=str(cfg_atual["fonte"]))
        combo_fonte = ttk.Combobox(
            c_main, textvariable=var_fonte, state="readonly",
            values=["Montserrat", "Roboto", "Digital-7"],
            font=("Arial", 11))
        combo_fonte.pack(fill='x', pady=(0, 10), ipady=2)

        # ── Tamanho do texto ──
        tk.Label(c_main, text="Tamanho do texto (relativo à altura da tela):",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117', anchor='w'
                 ).pack(fill='x')
        var_tamanho = tk.DoubleVar(value=float(cfg_atual["tamanho_pct"]))
        scale_tamanho = tk.Scale(
            c_main, from_=1.0, to=15.0, resolution=0.2, orient="horizontal",
            variable=var_tamanho, bg='#0d1117', fg='#c9d1d9',
            troughcolor='#21262d', highlightthickness=0, font=("Arial", 10))
        scale_tamanho.pack(fill='x', pady=(0, 10))

        # ── Cor do texto ──
        tk.Label(c_main, text="Cor do texto:", font=("Arial", 11, "bold"),
                 fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x')
        lista_cores = [
            ("Branco", "#FFFFFF"), ("Amarelo", "#F5BE08"),
            ("Vermelho", "#FF5555"), ("Azul", "#58A6FF"),
            ("Verde", "#3FB950"), ("Roxo", "#D2A8FF"),
            ("Ciano", "#00E5FF"), ("Laranja", "#FF9800")]
        var_cor = tk.StringVar(value=str(cfg_atual["cor"]))
        cor_frame = tk.Frame(c_main, bg='#0d1117')
        cor_frame.pack(fill='x', pady=(0, 10))
        for nome, codigo in lista_cores:
            rb = tk.Radiobutton(
                cor_frame, text=nome, value=codigo, variable=var_cor,
                bg='#0d1117', fg='#c9d1d9', selectcolor='#0d1117',
                activebackground='#0d1117', activeforeground='#f0c040',
                font=("Arial", 10))
            rb.pack(side='left', padx=2)

        if mostrar_cor_ref:
            # ── Cor da referência bíblica (livro cap:vers. — canto inferior direito) ──
            tk.Label(c_main, text="Cor da referência bíblica (livro cap:vers.):",
                     font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117', anchor='w'
                     ).pack(fill='x')
            var_cor_ref = tk.StringVar(value=str(cfg_atual["cor_ref"]))
            cor_ref_frame = tk.Frame(c_main, bg='#0d1117')
            cor_ref_frame.pack(fill='x', pady=(0, 10))
            for nome, codigo in lista_cores:
                rb = tk.Radiobutton(
                    cor_ref_frame, text=nome, value=codigo, variable=var_cor_ref,
                    bg='#0d1117', fg='#c9d1d9', selectcolor='#0d1117',
                    activebackground='#0d1117', activeforeground='#f0c040',
                    font=("Arial", 10))
                rb.pack(side='left', padx=2)

        # ── Cor de fundo ──
        tk.Label(c_main, text="Cor de fundo:", font=("Arial", 11, "bold"),
                 fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x')
        var_cor_fundo = tk.StringVar(value=str(cfg_atual["cor_fundo"]))
        cor_fundo_frame = tk.Frame(c_main, bg='#0d1117')
        cor_fundo_frame.pack(fill='x', pady=(0, 8))
        cores_fundo = [
            ("Preto", "#000000"), ("Cinza escuro", "#1a1a2e"),
            ("Azul escuro", "#0d1b2a"), ("Verde escuro", "#0a1f0a"),
            ("Vinho", "#2d0a0a")]
        for nome, codigo in cores_fundo:
            tk.Radiobutton(
                cor_fundo_frame, text=nome, value=codigo, variable=var_cor_fundo,
                bg='#0d1117', fg='#c9d1d9', selectcolor='#0d1117',
                activebackground='#0d1117', activeforeground='#f0c040',
                font=("Arial", 10)).pack(side='left', padx=2)

        # ── Fundo opaco (sem transparência) ──
        var_fundo_opaco = tk.BooleanVar(value=bool(cfg_atual["fundo_opaco"]))
        tk.Checkbutton(
            c_main, text="Fundo opaco (sem transparência)", variable=var_fundo_opaco,
            bg='#0d1117', fg='#c9d1d9', selectcolor='#0d1117',
            activebackground='#0d1117', activeforeground='#f0c040',
            font=("Arial", 11, "bold")).pack(anchor='w', pady=(0, 8))

        # ── Imagem de fundo (opcional) ──
        tk.Label(c_main, text="Imagem de fundo (opcional):",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117', anchor='w'
                 ).pack(fill='x')
        linha_imagem = tk.Frame(c_main, bg='#0d1117')
        linha_imagem.pack(fill='x', pady=(0, 12))
        var_fundo_imagem = tk.StringVar(value=str(cfg_atual["fundo_imagem"]))
        entry_imagem = tk.Entry(
            linha_imagem, textvariable=var_fundo_imagem, font=("Arial", 10),
            bg='#21262d', fg='#c9d1d9', insertbackground='#f0c040',
            bd=0, highlightthickness=0)
        entry_imagem.pack(side='left', fill='x', expand=True, ipady=3)

        def _escolher_imagem_fundo():
            escolhido = tkinter.filedialog.askopenfilename(
                parent=cfg_win, title="Escolher imagem de fundo",
                filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp *.webp *.gif"),
                           ("Todos os arquivos", "*.*")])
            if escolhido:
                var_fundo_imagem.set(escolhido)

        tk.Button(linha_imagem, text="Procurar…", font=("Arial", 10, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_escolher_imagem_fundo, cursor='hand2', padx=8, pady=2
                  ).pack(side='left', padx=3)
        tk.Button(linha_imagem, text="✖ Limpar", font=("Arial", 10, "bold"),
                  bg='#da3633', fg='white', activebackground='#f85149',
                  command=lambda: var_fundo_imagem.set(""), cursor='hand2',
                  padx=8, pady=2).pack(side='left')

        # ── Duração antes de voltar ao relógio ──
        tk.Label(c_main, text="Duração antes de voltar ao relógio (segundos):",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117', anchor='w'
                 ).pack(fill='x')
        var_duracao = tk.IntVar(value=int(cfg_atual["duracao_seg"]))
        entry_duracao = tk.Entry(c_main, textvariable=var_duracao,
                                 font=("Arial", 11), bg='#21262d', fg='#c9d1d9',
                                 insertbackground='#f0c040', bd=0, highlightthickness=0)
        entry_duracao.pack(fill='x', pady=(0, 14), ipady=3)

        def _salvar_cfg():
            try:
                duracao = max(1, int(var_duracao.get()))
            except (ValueError, TypeError):
                duracao = 1
            novo = {
                "fonte": var_fonte.get(),
                "tamanho_pct": float(var_tamanho.get()),
                "cor": var_cor.get(),
                "duracao_seg": duracao,
                "cor_fundo": var_cor_fundo.get(),
                "fundo_opaco": bool(var_fundo_opaco.get()),
                "fundo_imagem": var_fundo_imagem.get().strip(),
            }
            if mostrar_cor_ref:
                novo["cor_ref"] = var_cor_ref.get()
            self.salvar_config_projecao(novo)
            cfg_win.destroy()

        tk.Button(c_main, text="💾 Salvar", font=("Arial", 12, "bold"),
                  bg='#238636', fg='white', activebackground='#2ea043',
                  command=_salvar_cfg, cursor='hand2', padx=20, pady=5
                  ).pack(pady=6)

    def salvar_config_relogio(self, cfg: dict) -> None:
        """Persiste a configuração de aparência do relógio e aplica ao telão."""
        self.config_data["relogio"] = cfg
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config_data, f, indent=2)
        except Exception as e:
            print(f"Erro ao salvar config do relógio: {e}")
        if self.player and self.player.telao:
            self.player.telao.configurar_relogio(cfg)

    def abrir_config_relogio_dialogo(self) -> None:
        """Abre a janela de configuração do relógio/temperatura no telão."""
        cfg_atual = dict(getattr(self.player.telao, "_relogio_cfg", {}))
        cfg_atual.setdefault("cor_hora", "#F5BE08")
        cfg_atual.setdefault("cor_temp", "#F5BE08")
        cfg_atual.setdefault("cor_fundo", "#000000")
        cfg_atual.setdefault("fator_hora", 1.0)
        cfg_atual.setdefault("fator_temp", 1.0)
        cfg_atual.setdefault("espacamento", 1.0)
        cfg_atual.setdefault("fundo_opaco", False)
        cfg_atual.setdefault("fundo_imagem", "")

        cfg_win = tk.Toplevel(self.root)
        cfg_win.title("⚙️ Configura Relógio")
        cfg_win.geometry("620x740")
        cfg_win.configure(bg='#0d1117')
        cfg_win.transient(self.root)
        cfg_win.after(50, cfg_win.grab_set)

        c_main = tk.Frame(cfg_win, bg='#0d1117')
        c_main.pack(fill='both', expand=True, padx=15, pady=15)

        tk.Label(c_main, text="⚙️ Configura Relógio",
                 font=("Arial", 15, "bold"), fg='#f0c040', bg='#0d1117'
                 ).pack(pady=(0, 12))

        lista_cores = [
            ("Amarelo", "#F5BE08"), ("Branco", "#FFFFFF"),
            ("Vermelho", "#FF5555"), ("Azul", "#58A6FF"),
            ("Verde", "#3FB950"), ("Roxo", "#D2A8FF"),
            ("Ciano", "#00E5FF"), ("Laranja", "#FF9800")]

        # ── Cor do relógio ──
        tk.Label(c_main, text="Cor do relógio:", font=("Arial", 11, "bold"),
                 fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x')
        var_cor_hora = tk.StringVar(value=str(cfg_atual["cor_hora"]))
        cor_hora_frame = tk.Frame(c_main, bg='#0d1117')
        cor_hora_frame.pack(fill='x', pady=(0, 8))
        for nome, codigo in lista_cores:
            tk.Radiobutton(
                cor_hora_frame, text=nome, value=codigo, variable=var_cor_hora,
                bg='#0d1117', fg='#c9d1d9', selectcolor='#0d1117',
                activebackground='#0d1117', activeforeground='#f0c040',
                font=("Arial", 10)).pack(side='left', padx=2)

        # ── Cor da temperatura ──
        tk.Label(c_main, text="Cor da temperatura:", font=("Arial", 11, "bold"),
                 fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x')
        var_cor_temp = tk.StringVar(value=str(cfg_atual["cor_temp"]))
        cor_temp_frame = tk.Frame(c_main, bg='#0d1117')
        cor_temp_frame.pack(fill='x', pady=(0, 8))
        for nome, codigo in lista_cores:
            tk.Radiobutton(
                cor_temp_frame, text=nome, value=codigo, variable=var_cor_temp,
                bg='#0d1117', fg='#c9d1d9', selectcolor='#0d1117',
                activebackground='#0d1117', activeforeground='#f0c040',
                font=("Arial", 10)).pack(side='left', padx=2)

        # ── Cor de fundo ──
        tk.Label(c_main, text="Cor de fundo:", font=("Arial", 11, "bold"),
                 fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x')
        var_cor_fundo = tk.StringVar(value=str(cfg_atual["cor_fundo"]))
        cor_fundo_frame = tk.Frame(c_main, bg='#0d1117')
        cor_fundo_frame.pack(fill='x', pady=(0, 8))
        cores_fundo = [
            ("Preto", "#000000"), ("Cinza escuro", "#1a1a2e"),
            ("Azul escuro", "#0d1b2a"), ("Verde escuro", "#0a1f0a"),
            ("Vinho", "#2d0a0a")]
        for nome, codigo in cores_fundo:
            tk.Radiobutton(
                cor_fundo_frame, text=nome, value=codigo, variable=var_cor_fundo,
                bg='#0d1117', fg='#c9d1d9', selectcolor='#0d1117',
                activebackground='#0d1117', activeforeground='#f0c040',
                font=("Arial", 10)).pack(side='left', padx=2)

        # ── Fundo opaco (sem transparência) ──
        var_fundo_opaco = tk.BooleanVar(value=bool(cfg_atual["fundo_opaco"]))
        tk.Checkbutton(
            c_main, text="Fundo opaco (sem transparência)", variable=var_fundo_opaco,
            bg='#0d1117', fg='#c9d1d9', selectcolor='#0d1117',
            activebackground='#0d1117', activeforeground='#f0c040',
            font=("Arial", 11, "bold")).pack(
                anchor='w', pady=(0, 8))

        # ── Imagem de fundo (opcional) ──
        tk.Label(c_main, text="Imagem de fundo (opcional):",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117', anchor='w'
                 ).pack(fill='x')
        linha_imagem = tk.Frame(c_main, bg='#0d1117')
        linha_imagem.pack(fill='x', pady=(0, 12))
        var_fundo_imagem = tk.StringVar(value=str(cfg_atual["fundo_imagem"]))
        entry_imagem = tk.Entry(
            linha_imagem, textvariable=var_fundo_imagem, font=("Arial", 10),
            bg='#21262d', fg='#c9d1d9', insertbackground='#f0c040',
            bd=0, highlightthickness=0)
        entry_imagem.pack(side='left', fill='x', expand=True, ipady=3)

        def _escolher_imagem_fundo_relogio():
            escolhido = tkinter.filedialog.askopenfilename(
                parent=cfg_win, title="Escolher imagem de fundo",
                filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp *.webp *.gif"),
                           ("Todos os arquivos", "*.*")])
            if escolhido:
                var_fundo_imagem.set(escolhido)

        tk.Button(linha_imagem, text="Procurar…", font=("Arial", 10, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_escolher_imagem_fundo_relogio, cursor='hand2',
                  padx=8, pady=2).pack(side='left', padx=3)
        tk.Button(linha_imagem, text="✖ Limpar", font=("Arial", 10, "bold"),
                  bg='#da3633', fg='white', activebackground='#f85149',
                  command=lambda: var_fundo_imagem.set(""), cursor='hand2',
                  padx=8, pady=2).pack(side='left')

        # ── Tamanho do relógio ──
        tk.Label(c_main, text="Tamanho do relógio:", font=("Arial", 11, "bold"),
                 fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x')
        var_fator_hora = tk.DoubleVar(value=float(cfg_atual["fator_hora"]))
        tk.Scale(c_main, from_=0.3, to=2.0, resolution=0.1, orient="horizontal",
                 variable=var_fator_hora, bg='#0d1117', fg='#c9d1d9',
                 troughcolor='#21262d', highlightthickness=0,
                 font=("Arial", 10)).pack(fill='x', pady=(0, 8))

        # ── Tamanho da temperatura ──
        tk.Label(c_main, text="Tamanho da temperatura:", font=("Arial", 11, "bold"),
                 fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x')
        var_fator_temp = tk.DoubleVar(value=float(cfg_atual["fator_temp"]))
        tk.Scale(c_main, from_=0.3, to=2.0, resolution=0.1, orient="horizontal",
                 variable=var_fator_temp, bg='#0d1117', fg='#c9d1d9',
                 troughcolor='#21262d', highlightthickness=0,
                 font=("Arial", 10)).pack(fill='x', pady=(0, 8))

        # ── Espaçamento ──
        tk.Label(c_main, text="Espaçamento (hora ↔ temperatura):",
                 font=("Arial", 11, "bold"),
                 fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x')
        var_espacamento = tk.DoubleVar(value=float(cfg_atual["espacamento"]))
        tk.Scale(c_main, from_=0.0, to=3.0, resolution=0.05, orient="horizontal",
                 variable=var_espacamento, bg='#0d1117', fg='#c9d1d9',
                 troughcolor='#21262d', highlightthickness=0,
                 font=("Arial", 10)).pack(fill='x', pady=(0, 12))

        def _salvar_cfg_relogio():
            novo = {
                "cor_hora": var_cor_hora.get(),
                "cor_temp": var_cor_temp.get(),
                "cor_fundo": var_cor_fundo.get(),
                "fator_hora": float(var_fator_hora.get()),
                "fator_temp": float(var_fator_temp.get()),
                "espacamento": float(var_espacamento.get()),
                "fundo_opaco": bool(var_fundo_opaco.get()),
                "fundo_imagem": var_fundo_imagem.get().strip(),
            }
            self.salvar_config_relogio(novo)
            cfg_win.destroy()

        tk.Button(c_main, text="💾 Salvar", font=("Arial", 12, "bold"),
                  bg='#238636', fg='white', activebackground='#2ea043',
                  command=_salvar_cfg_relogio, cursor='hand2', padx=20, pady=5
                  ).pack(pady=4)

    def _temperatura_valida(self, temp: Optional[str] = None) -> bool:
        """Verifica se a string de temperatura é válida para exibição."""
        t = temp if temp is not None else self.temperatura_atual
        return bool(t and "Erro" not in t and "não encontrada" not in t and t != "--")

    def salvar_cidade(self) -> None:
        cidade = self.entry_cidade.get().strip()
        estado = self.entry_estado.get().strip().upper()

        if not cidade or cidade == "Cidade" or not estado or estado == "UF":
            self.status_label.config(text="⚠️ Preencha cidade e UF!")
            return

        self.config_data["cidade"] = cidade
        self.config_data["estado"] = estado
        self.cidade_salva = cidade
        self.estado_salvo = estado

        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config_data, f, indent=2)
        except Exception as e:
            print(f"Erro ao salvar config: {e}")

        self.status_label.config(text=f"✅ Local salvo: {cidade}/{estado}")
        # Carrega temperatura em background
        def _carregar_temp():
            temp = obter_temperatura(self.cidade_salva, self.estado_salvo)
            self.root.after(0, lambda: self._aplicar_temperatura(temp))
        threading.Thread(target=_carregar_temp, daemon=True).start()

    # ── Temperatura ──────────────────────────────────────────────

    def atualizar_temperatura(self) -> None:
        if not self.cidade_salva or not self.estado_salvo:
            return

        # Executa requisição HTTP em thread para NÃO travar a interface
        threading.Thread(target=self._atualizar_temperatura_async, daemon=True).start()

    def _atualizar_temperatura_async(self) -> None:
        """Carrega temperatura em background e atualiza interface via after()."""
        temp = obter_temperatura(self.cidade_salva, self.estado_salvo)
        self.root.after(0, lambda: self._aplicar_temperatura_com_timer(temp))

    def _aplicar_temperatura_com_timer(self, temp: str) -> None:
        """Aplica temperatura na interface e agenda próxima atualização."""
        self.temperatura_atual = temp
        if self._temperatura_valida():
            self.player.telao._exibir_hora_inicial(temp)
            self.temp_label.config(
                text=f"🌡️ {self.cidade_salva}: {temp}"
            )
        else:
            self.temp_label.config(text="🌡️ Temperatura indisponível")
            self.temperatura_atual = "--"

        # Cancela timer anterior antes de agendar novo
        if hasattr(self, '_temp_timer') and self._temp_timer:
            self.root.after_cancel(self._temp_timer)
        self._temp_timer = self.root.after(1_800_000, self.atualizar_temperatura)

    # ── Callbacks do player ──────────────────────────────────────

    def quando_faixa_muda(self, indice: int, arquivo: str) -> None:
        self.arquivo_atual = arquivo
        self.atualizar_status()
        # Força redesenho completo da lista para destacar a música atual
        self.atualizar_lista()

    def quando_midia_terminar(self, estado: str) -> None:
        if estado == "ended" and not getattr(self, '_shutting_down', False):
            self._tocar_proxima()

    def _tocar_proxima(self) -> None:
        """Toca a próxima música da playlist. Se não houver, repete ou para."""
        if getattr(self, '_shutting_down', False):
            return
        playlist = self.player.playlist
        if not playlist:
            return
        
        prox_index = self.player.index + 1
        
        # Se ainda há próxima música
        if prox_index < len(playlist):
            self.player.proximo()
            return
        
        # Chegou ao fim da lista
        if self.repetir_var.get():
            # Reproduzir TUDO novamente do início
            self._repetir_playlist()
        else:
            # Parar e fechar SMPlayer
            self.parar()

    def _repetir_playlist(self) -> None:
        """Reproduz toda a playlist novamente do início."""
        if not self.arquivos_encontrados:
            if self.arquivo_atual:
                self.tocar_arquivo(self.arquivo_atual)
            return
        self.player.carregar_playlist(self.arquivos_encontrados)
        self.player.tocar_indice(0)

    # ── Busca (nova implementação com worker e cache) ────────────

    def enter_busca(self, event: object = None) -> None:
        """Enter: toca o primeiro resultado da busca."""
        termo = self.entry_busca.get().strip()
        if not termo or termo == self.placeholder_busca:
            return
        # Cancela timer pendente e faz busca imediata com toque
        if self._debounce_timer:
            self.root.after_cancel(self._debounce_timer)
            self._debounce_timer = None
        self._fazer_busca(termo, tocar_primeiro=True)

    def on_busca_digitada(self, event: object = None) -> None:
        """Debounce: executa a busca 500ms após parar de digitar."""
        # Ignora teclas de navegação e modificadoras que não alteram o texto
        keysym = event.keysym if event else ""
        if keysym in ("Shift_L", "Shift_R", "Control_L", "Control_R",
                      "Alt_L", "Alt_R", "Meta_L", "Meta_R", "Caps_Lock"):
            return

        # Se for tecla Delete, BackSpace, ou qualquer tecla que altere texto,
        # reiniciamos o debounce.
        if self._debounce_timer:
            self.root.after_cancel(self._debounce_timer)
        self._debounce_timer = self.root.after(500, self._executar_busca_debounce)

    def _executar_busca_debounce(self) -> None:
        self._debounce_timer = None
        termo = self.entry_busca.get().strip()
        # Se o termo estiver vazio ou for placeholder, limpar resultados
        if not termo or termo == self.placeholder_busca:
            self.arquivos_encontrados = []
            self.player.carregar_playlist([])
            self.atualizar_lista()
            return
        self._fazer_busca(termo, tocar_primeiro=False)

    def _fazer_busca(self, termo: str, tocar_primeiro: bool = False) -> None:
        """Enfileira uma busca no worker."""
        self._versao_busca += 1
        versao = self._versao_busca

        # Submete ao worker
        self.search_worker.submit(termo, versao, self._on_search_complete)

        # Se tocar_primeiro, faremos após o retorno da busca (no callback)
        self._pending_play = tocar_primeiro

    def _on_search_complete(self, results: List[Dict[str, Any]], version: int) -> None:
        """Callback chamado pelo worker na thread principal."""
        if version != self._versao_busca:
            return  # Resultado obsoleto

        # Extrair caminhos dos resultados (vazio rápido)
        caminhos = [rec['caminho_arquivo'] for rec in results] if results else []
        # Ordenar por nome_exibicao (numérico crescente)
        # Usa o nome_exibicao do registro (que já está no results) para ordenar
        # Ordena os registros (cópia para não modificar o cache do DatabaseManager)
        results_ordenados = sorted(results, key=self._chave_ordenacao_busca)
        caminhos = [rec['caminho_arquivo'] for rec in results_ordenados]
        self.arquivos_encontrados = caminhos
        self.player.carregar_playlist(caminhos)

        # Se tocar_primeiro estava pendente e há resultados
        if getattr(self, '_pending_play', False) and caminhos:
            self.tocar_arquivo(caminhos[0])
            self._pending_play = False

        self.atualizar_lista()

    # ── Criação de widgets ─────────────────────────────────────────

    def _criar_menu(self) -> None:
        """Cria a barra de menu no topo da janela."""
        menubar = tk.Menu(self.root, bg='#161b22', fg='#f0c040',
                          activebackground='#6e40c9', activeforeground='#f0c040',
                          font=("Arial", 10))

        # ── Arquivo (placeholder) ──
        menu_arquivo = tk.Menu(menubar, tearoff=0, bg='#21262d', fg='#c9d1d9',
                               activebackground='#6e40c9', activeforeground='#f0c040',
                               font=("Arial", 10))
        menu_arquivo.add_command(label="Sair", command=self.fechar,
                                 accelerator="Ctrl+Q")
        menubar.add_cascade(label="Arquivo", menu=menu_arquivo)

        # ── Editar (placeholder) ──
        menu_editar = tk.Menu(menubar, tearoff=0, bg='#21262d', fg='#c9d1d9',
                              activebackground='#6e40c9', activeforeground='#f0c040',
                              font=("Arial", 10))
        menu_editar.add_command(label="Gerenciar Banco",
                                command=self.abrir_gerenciador)
        menu_editar.add_separator()
        menu_editar.add_command(label="Hinos / Letras",
                                command=self.janela_hinos)
        menu_editar.add_command(label="Bíblia",
                                command=self.janela_biblia)
        menu_editar.add_command(label="Ordem de Serviço",
                                command=self.janela_ordem_servico)
        menubar.add_cascade(label="Editar", menu=menu_editar)

        # ── Visualizar ──
        menu_visualizar = tk.Menu(menubar, tearoff=0, bg='#21262d', fg='#c9d1d9',
                                  activebackground='#6e40c9', activeforeground='#f0c040',
                                  font=("Arial", 10))
        menu_visualizar.add_command(label="Alternar modo Repetir",
                                    command=self._toggle_repetir)
        menu_visualizar.add_separator()
        menu_visualizar.add_command(label="Alternar Tela Cheia",
                                    command=self._alternar_maximizar,
                                    accelerator="F11")
        menu_visualizar.add_separator()
        self._var_tema_claro = tk.BooleanVar(value=(self.tema == 'claro'))
        menu_visualizar.add_checkbutton(label="Tema Claro",
                                        variable=self._var_tema_claro,
                                        command=self._alternar_tema,
                                        accelerator="Ctrl+T")
        menubar.add_cascade(label="Visualizar", menu=menu_visualizar)

        # ── Ajuda > Sobre ──
        menu_ajuda = tk.Menu(menubar, tearoff=0, bg='#21262d', fg='#c9d1d9',
                             activebackground='#6e40c9', activeforeground='#f0c040',
                             font=("Arial", 10))
        menu_ajuda.add_command(label="Verificar atualizações…",
                               command=lambda: self.verificar_atualizacao(manual=True))
        menu_ajuda.add_separator()
        menu_ajuda.add_command(label="Sobre", command=self._mostrar_sobre)
        menubar.add_cascade(label="Ajuda", menu=menu_ajuda)

        # Guarda referências para recolorir os menus ao trocar o tema
        self._menus = [menubar, menu_arquivo, menu_editar,
                       menu_visualizar, menu_ajuda]

        self.root.config(menu=menubar)

    def _toggle_repetir(self) -> None:
        """Alterna o estado do checkbox Repetir."""
        self.repetir_var.set(not self.repetir_var.get())

    # ── Tema (claro/escuro) ───────────────────────────────────────

    def _alternar_tema(self) -> None:
        """Alterna entre tema escuro (padrão) e claro, persistindo a escolha."""
        novo = 'claro' if self.tema != 'claro' else 'escuro'
        self.tema = novo
        self.config_data['tema'] = novo
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Erro ao salvar tema: {e}")
        if getattr(self, '_var_tema_claro', None) is not None:
            self._var_tema_claro.set(novo == 'claro')
        self._aplicar_tema()

    def _aplicar_tema(self) -> None:
        """Aplica o tema ativo (claro/escuro) a toda a interface."""
        self._aplicar_tema_ttk()
        self._aplicar_tema_menu()
        try:
            self._recolorir_arvore(self.root)
        except tk.TclError:
            pass

    def _aplicar_tema_ttk(self) -> None:
        """Ajusta os estilos globais ttk (Treeview/Scrollbar) ao tema."""
        try:
            style = ttk.Style()
            if self.tema == 'claro':
                style.configure(
                    "Treeview",
                    background="#ffffff", foreground="#1f2328",
                    fieldbackground="#ffffff", font=("Arial", 10))
                style.configure(
                    "Treeview.Heading",
                    background="#f6f8fa", foreground="#24292f",
                    font=("Arial", 10, "bold"))
                style.map('Treeview',
                          background=[('selected', '#0969da')],
                          foreground=[('selected', '#ffffff')])
                style.configure(
                    "Vertical.TScrollbar",
                    background="#ffffff", troughcolor="#eaeef2",
                    arrowcolor="#57606a")
            else:
                style.configure(
                    "Treeview",
                    background="#21262d", foreground="#c9d1d9",
                    fieldbackground="#21262d", font=("Arial", 10))
                style.configure(
                    "Treeview.Heading",
                    background="#161b22", foreground="#f0c040",
                    font=("Arial", 10, "bold"))
                style.map('Treeview',
                          background=[('selected', '#6e40c9')],
                          foreground=[('selected', '#ffffff')])
                style.configure(
                    "Vertical.TScrollbar",
                    background="#21262d", troughcolor="#161b22",
                    arrowcolor="#f0c040")
        except (Exception, tk.TclError):
            pass

    def _aplicar_tema_menu(self) -> None:
        """Recolore a barra de menu e os menus suspensos."""
        menus = getattr(self, '_menus', [])
        if not menus:
            return
        if self.tema == 'claro':
            menubar_cfg = dict(bg='#f6f8fa', fg='#24292f',
                               activebackground='#eaeef2',
                               activeforeground='#24292f')
            menu_cfg = dict(bg='#ffffff', fg='#1f2328',
                            activebackground='#eaeef2',
                            activeforeground='#24292f')
        else:
            menubar_cfg = dict(bg='#161b22', fg='#f0c040',
                               activebackground='#6e40c9',
                               activeforeground='#f0c040')
            menu_cfg = dict(bg='#21262d', fg='#c9d1d9',
                            activebackground='#6e40c9',
                            activeforeground='#f0c040')
        for i, menu in enumerate(menus):
            try:
                menu.configure(**(menubar_cfg if i == 0 else menu_cfg))
            except (Exception, tk.TclError):
                pass

    def _recolorir_arvore(self, base) -> None:
        """Aplica a recoloração de tema a `base` e a todos os seus filhos."""
        self._aplicar_tema_widget(base)
        try:
            for filho in base.winfo_children():
                self._recolorir_arvore(filho)
        except tk.TclError:
            pass

    def _varrer_toplevels_tema(self) -> None:
        """Recoloriza janelas auxiliares (Toplevel) criadas após o app.

        Chamado periodicamente (junto do loop do telão). Cada janela
        recria estilos escuros ao ser aberta; aqui garantimos que o tema
        ativo seja sempre respeitado sem tocar no código de criação.
        """
        try:
            self._aplicar_tema_ttk()
            if self.tema != 'claro':
                return
            self._recolorir_arvore(self.root)
            for filho in self.root.winfo_children():
                try:
                    if filho.winfo_class() == 'Toplevel':
                        self._recolorir_arvore(filho)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass

    def _aplicar_tema_widget(self, widget) -> None:
        """Ajusta as cores de um único widget conforme o tema ativo.

        No tema ESCURO restaura as cores escura originais (gravadas na
        primeira visita em claro). No CLARO registra as cores atuais como
        origem e aplica a equivalência clara. Pergunta valores sobrescritos
        dinamicamente (ex.: linha tocando na lista) como nova origem, para
        a troca de tema nunca perder o estado visual.
        """
        try:
            if not widget.winfo_exists():
                return
            if isinstance(widget, ttk.Widget):
                return
            keys = set(widget.keys())
        except tk.TclError:
            return

        ops = [o for o in _OPCOES_COR_TK if o in keys]

        def _ler(op):
            try:
                return widget.cget(op)
            except tk.TclError:
                return None

        origem = getattr(widget, '_navepro_tema_origem', None)
        aplicado = getattr(widget, '_navepro_tema_aplicado', None)

        if self.tema == 'escuro':
            if not origem:
                return
            cfg = {}
            for o in ops:
                v = origem.get(o)
                if v:
                    cfg[o] = v
            try:
                widget.configure(**cfg)
            except Exception:
                for o, v in cfg.items():
                    try:
                        widget.configure(**{o: v})
                    except Exception:
                        pass
            try:
                widget._navepro_tema_origem = None
                widget._navepro_tema_aplicado = None
            except Exception:
                pass
            return

        # ── Tema CLARO ──
        if origem is None:
            origem = {}
        if aplicado is None:
            aplicado = {}

        # Passo 1: mapeia as opções que funcionam como FUNDO e guarda o
        # resultado para decidir as cores de texto em passo 2.
        bg_final = None
        base: dict[str, str] = {}
        cfg: dict[str, str] = {}
        for o in ops:
            atual = _ler(o)
            if atual is None:
                continue
            if o in ('background', 'activebackground', 'selectbackground',
                     'troughcolor'):
                clara = _cor_clara(atual)
                if o == 'background':
                    bg_final = clara
                if aplicado.get(o) != atual:
                    origem[o] = atual
                base[o] = clara
                aplicado[o] = clara
                cfg[o] = clara

        # Passo 2: opções de TEXTO decididas com o fundo correspondente.
        def _fundo_para(op: str) -> Optional[str]:
            if op == 'activeforeground':
                return base.get('activebackground', bg_final)
            if op == 'selectforeground':
                return base.get('selectbackground', bg_final)
            return bg_final

        for o in ops:
            if o in ('background', 'activebackground', 'selectbackground',
                     'troughcolor'):
                continue
            atual = _ler(o)
            if atual is None:
                continue
            if aplicado.get(o) != atual:
                origem[o] = atual
            escura = origem.get(o)
            if not escura:
                continue
            if o in _OPCOES_TEXTO:
                clara = _cor_clara(escura, _fundo_para(o))
            else:
                clara = _cor_clara(escura)
            aplicado[o] = clara
            cfg[o] = clara

        try:
            widget.configure(**cfg)
        except Exception:
            for o, v in cfg.items():
                try:
                    widget.configure(**{o: v})
                except Exception:
                    pass

        try:
            widget._navepro_tema_origem = origem
            widget._navepro_tema_aplicado = aplicado
        except Exception:
            pass

    def _mostrar_sobre(self) -> None:
        """Exibe a janela Sobre com informações do programa."""
        tkinter.messagebox.showinfo(
            "Sobre o NavePro",
            "NavePro - Sistema de Projeção para Igrejas\n"
            f"Versão: {APP_VERSION}\n"
            "Licença: GPLv3\n"
            "Autor: José Edes Neves - Julho 2026\n"
            "edes.neves7@gmail.com\n\n"
            "Aplicação para reprodução de mídia com projeção em\n"
            "telão, busca inteligente no banco de dados e\n"
            "informações climáticas.",
            parent=self.root
        )

    # ── Atualização automática (GitHub Releases) ──

    def verificar_atualizacao(self, manual: bool = False) -> None:
        """Verifica (em thread) se há versão nova no GitHub e notifica."""
        def _worker() -> None:
            release = _buscar_release_latest()
            if release is None:
                if manual:
                    self.root.after(0, lambda: tkinter.messagebox.showinfo(
                        "Atualizações",
                        "Não foi possível consultar o GitHub agora.\n"
                        "Verifique sua conexão e tente novamente.",
                        parent=self.root))
                return
            versao = str(release.get('tag_name', '')).lstrip('vV')
            if not _versao_nova(versao):
                if manual:
                    self.root.after(0, lambda: tkinter.messagebox.showinfo(
                        "Atualizações",
                        f"Você já está na versão mais recente "
                        f"({APP_VERSION}).",
                        parent=self.root))
                return
            self.root.after(0, lambda: self._oferecer_atualizacao(release))

        threading.Thread(target=_worker, daemon=True).start()

    def _oferecer_atualizacao(self, release: dict) -> None:
        """Pergunta se o usuário quer baixar a versão nova e baixa."""
        versao = str(release.get('tag_name', '')).lstrip('vV')
        corpo = str(release.get('body') or '').strip()
        if len(corpo) > 400:
            corpo = corpo[:400].rstrip() + '…'
        sufixo = ".exe" if _eh_windows() else ".AppImage"
        mensagem = (
            f"NavePro {APP_VERSION} → {versao}\n\n"
            "Uma nova versão está disponível no GitHub.\n"
        )
        if corpo:
            mensagem += f"\nNovidades:\n{corpo}\n"
        mensagem += f"\nDeseja baixar o novo {sufixo} agora?"
        if not tkinter.messagebox.askyesno(
                "🔄 Atualização disponível", mensagem, parent=self.root):
            return
        asset = _procurar_asset_instalador(release)
        if asset is None:
            tkinter.messagebox.showwarning(
                "Atualização",
                f"O release não contém um arquivo {sufixo}.",
                parent=self.root)
            return
        self._baixar_atualizacao(
            versao,
            str(asset.get('browser_download_url', '')),
            str(asset.get('name', f'NavePro-{versao}{sufixo}')),
        )

    def _baixar_atualizacao(self, versao: str, url: str,
                            nome_arquivo: str) -> None:
        """Baixa o novo instalador para ~/Downloads com barra de progresso."""
        destino = os.path.join(_pasta_downloads(), nome_arquivo)

        janela = tk.Toplevel(self.root)
        janela.title("⬇️ Baixando atualização")
        janela.geometry("440x150")
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        janela.grab_set()

        def _atualizar_progresso(pct: int, baixado: int, total: int) -> None:
            try:
                progresso['value'] = pct
                lbl.config(
                    text=f"{pct}%  ({baixado // 1024 // 1024} de "
                         f"{total // 1024 // 1024} MB)"
                )
            except tk.TclError:
                pass

        tk.Label(janela, text=f"Baixando {nome_arquivo}…",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117'
                 ).pack(pady=(18, 6))
        progresso = ttk.Progressbar(janela, mode='determinate', length=380)
        progresso.pack(pady=6)
        lbl = tk.Label(janela, text="0%", font=("Arial", 9), fg='#c9d1d9',
                       bg='#0d1117')
        lbl.pack(pady=2)

        def _worker() -> None:
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": f"NavePro/{APP_VERSION}"})
                with urllib.request.urlopen(req, timeout=120,
                                            context=_ssl_context()) as resp:
                    total = int(resp.headers.get('Content-Length', 0) or 0)
                    temporario = destino + '.part'
                    baixado = 0
                    with open(temporario, 'wb') as f:
                        while True:
                            bloco = resp.read(8192)
                            if not bloco:
                                break
                            f.write(bloco)
                            baixado += len(bloco)
                            if total > 0:
                                pct = int(baixado * 100 / total)
                                self.root.after(
                                    0, lambda p=pct, b=baixado, t=total:
                                    _atualizar_progresso(p, b, t))
                    os.replace(temporario, destino)
                    if not _eh_windows():
                        os.chmod(destino, 0o744)
                    self.root.after(0, lambda: self._instrucoes_troca_instalador(
                        destino))
            except Exception as e:
                print(f"⚠️  Erro ao baixar atualização: {e}")
                self.root.after(0, lambda: (janela.destroy(),
                             tkinter.messagebox.showerror(
                                 "Erro",
                                 f"Não foi possível baixar a atualização:\n{e}",
                                 parent=self.root)))
            else:
                janela.after(300, janela.destroy)

        threading.Thread(target=_worker, daemon=True).start()

    def _instrucoes_troca_instalador(self, destino: str) -> None:
        """Mostra como substituir o instalador antigo pelo baixado e abre Downloads."""
        if _eh_windows():
            msg = (
                "O novo executável foi salvo em:\n\n"
                f"  {destino}\n\n"
                "Para instalar:\n"
                "1. Feche o NavePro.\n"
                "2. Substitua o arquivo atual por este novo "
                "(mova-o para o mesmo lugar do antigo).\n"
                "3. Abra o novo arquivo para rodar a versão atualizada.\n\n"
                "Dica: o NavePro é portátil — basta copiar o .exe novo."
            )
        else:
            msg = (
                "O novo AppImage foi salvo em:\n\n"
                f"  {destino}\n\n"
                "Para instalar:\n"
                "1. Feche o NavePro.\n"
                "2. Substitua o AppImage atual por este novo arquivo "
                "(mova-o para o mesmo lugar do antigo).\n"
                "3. Dê permissão de execução se precisar:\n"
                "     chmod +x \"<novo arquivo>\"\n"
                "4. Abra o novo arquivo para rodar a versão atualizada."
            )
        tkinter.messagebox.showinfo("✅ Download concluído", msg,
                                    parent=self.root)
        try:
            if _eh_windows():
                os.startfile(_pasta_downloads())
            else:
                subprocess.Popen(['xdg-open', _pasta_downloads()],
                                 stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _alternar_maximizar(self) -> None:
        """Alterna entre maximizado (tela cheia) e minimizado (900x800 centralizado)."""
        if self._maximizado:
            # Minimizar para 900x800 centralizado
            self.root.state('normal')
            if hasattr(self, '_monitor_geo') and self._monitor_geo:
                mw, mh, mx, my = self._monitor_geo
                w, h = 900, 800
                x = mx + (mw - w) // 2
                y = my + (mh - h) // 2
                self.root.geometry(f"{w}x{h}+{x}+{y}")
            else:
                self.root.geometry("900x800+200+100")
            self._maximizado = False
        else:
            # Maximizar para ocupar todo o monitor
            if hasattr(self, '_monitor_geo') and self._monitor_geo:
                mw, mh, mx, my = self._monitor_geo
                self.root.geometry(f"{mw}x{mh}+{mx}+{my}")
            else:
                self.root.state('zoomed')
            self._maximizado = True

    def criar_widgets(self) -> None:
        """Cria todos os widgets da interface principal."""
        main_frame = tk.Frame(self.root, bg='#0d1117')
        main_frame.pack(fill='both', expand=True, padx=32, pady=24)

        # ── Logo / Identidade visual ──
        logo_frame = tk.Frame(main_frame, bg='#0d1117')
        logo_frame.pack(pady=(0, 8))
        try:
            from PIL import Image, ImageTk
            logo_img = Image.open(_caminho_recurso('Icon.png')).resize((48, 48), Image.LANCZOS)
            self._logo_tk = ImageTk.PhotoImage(logo_img)
            tk.Label(logo_frame, image=self._logo_tk, bg='#0d1117').pack(side='left', padx=(0, 10))
        except Exception:
            # Fallback: texto estilizado
            tk.Label(logo_frame, text="🎬", font=("Arial", 28), bg='#0d1117', fg='#f0c040'
                    ).pack(side='left', padx=(0, 10))

        tk.Label(logo_frame, text="NAVEPRO",
                font=("Arial", 18, "bold"), bg='#0d1117', fg='#f0c040'
                ).pack(side='left')
        tk.Label(logo_frame, text=f"Versão {APP_VERSION}",
                font=("Arial", 9), bg='#0d1117', fg='#8b949e'
                ).pack(side='left', padx=(8, 0))

        # Título
        tk.Label(
            main_frame,
            text="Sistema de Projeção Multimídia",
            font=("Adventist Sans", 20, "bold"),
            fg='#f0c040', bg='#0d1117'
        ).pack(pady=(10, 5))

        # Separador sutil
        sep1 = tk.Frame(main_frame, bg='#30363d', height=1)
        sep1.pack(fill='x', padx=40, pady=(0, 8))

        # Relógio
        self.hora_label = tk.Label(
            main_frame, text="",
            font=("Digital-7", 30, "bold"),
            fg="#f0c040", bg='#0d1117'
        )
        self.hora_label.pack(pady=5)

        # Temperatura
        self.temp_label = tk.Label(
            main_frame, text="",
            font=("Digital-7", 24, "bold"),
            fg="#58a6ff", bg='#0d1117'
        )
        self.temp_label.pack(pady=2)

        # Status
        self.status_label = tk.Label(
            main_frame, text="",
            font=("Arial", 14),
            fg='#f0c040', bg='#0d1117'
        )
        self.status_label.pack(pady=5)

        # ── Cidade / Clima ──
        # Card de clima com visual destacado
        clima_card = tk.Frame(main_frame, bg='#161b22', highlightbackground='#30363d',
                               highlightthickness=1)
        clima_card.pack(pady=5, ipady=8, ipadx=15)

        # Linha 1: Cidade + Estado + Salvar
        clima_linha1 = tk.Frame(clima_card, bg='#161b22')
        clima_linha1.pack(pady=(2, 0))

        tk.Label(
            clima_linha1, text="📍",
            font=("Arial", 14),
            fg='#f0c040', bg='#161b22'
        ).pack(side='left', padx=(0, 8))

        self.entry_cidade = tk.Entry(
            clima_linha1, width=15, font=("Arial", 11),
            bg='#21262d', fg='#f0c040', insertbackground='#f0c040',
            bd=0, highlightthickness=0
        )
        self.entry_cidade.pack(side='left', padx=2, ipady=3)
        self.entry_cidade.insert(0, "Cidade")
        self.entry_cidade.bind("<FocusIn>", lambda e: self._on_focus_cidade())
        self.entry_cidade.bind("<FocusOut>", lambda e: self._on_focus_out_cidade())
        self.entry_cidade.bind("<KeyRelease>", self._reset_focus_timer)

        if self.cidade_salva:
            self.entry_cidade.delete(0, tk.END)
            self.entry_cidade.insert(0, self.cidade_salva)
            self.entry_cidade.config(fg='#f0c040')

        self.entry_estado = tk.Entry(
            clima_linha1, width=5, font=("Arial", 11),
            bg='#21262d', fg='#f0c040', insertbackground='#f0c040',
            bd=0, highlightthickness=0
        )
        self.entry_estado.pack(side='left', padx=2, ipady=3)
        self.entry_estado.insert(0, "UF")
        self.entry_estado.bind("<FocusIn>", lambda e: self._on_focus_estado())
        self.entry_estado.bind("<FocusOut>", lambda e: self._on_focus_out_estado())
        self.entry_estado.bind("<KeyRelease>", self._reset_focus_timer)

        if self.estado_salvo:
            self.entry_estado.delete(0, tk.END)
            self.entry_estado.insert(0, self.estado_salvo)
            self.entry_estado.config(fg='#f0c040')

        tk.Button(
            clima_linha1, text="Salvar",
            font=("Arial", 10, "bold"),
            bg="#6e40c9", fg='#f0c040', activebackground='#8b5cf6',
            command=self.salvar_cidade, cursor='hand2', bd=0,
            padx=10, pady=2
        ).pack(side='left', padx=8)

        # Separador
        sep2 = tk.Frame(main_frame, bg='#30363d', height=1)
        sep2.pack(fill='x', padx=40, pady=(8, 8))

        # ── Busca ──
        busca_container = tk.Frame(main_frame, bg='#0d1117')
        busca_container.pack(pady=5)

        busca_frame = tk.Frame(busca_container, bg='#161b22')
        busca_frame.pack(ipady=8, ipadx=10)

        tk.Label(
            busca_frame, text="🔍",
            fg='#f0c040', bg='#161b22', font=("Arial", 16)
        ).pack(side='left', padx=(10, 5))

        self.entry_busca = tk.Entry(
            busca_frame, width=20, font=("Arial", 16),
            bg='#21262d', fg='#f0c040', insertbackground='#f0c040',
            justify='center'
        )
        self.entry_busca.pack(side='left', padx=5, ipady=5)
        self.entry_busca.insert(0, self.placeholder_busca)
        self.entry_busca.bind("<FocusIn>", self._on_focus_in)
        self.entry_busca.bind("<FocusOut>", self._on_focus_out)
        self.entry_busca.bind("<Return>", self.enter_busca)
        self.entry_busca.bind("<KeyRelease>", self._on_entry_keyrelease)

        self.repetir_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            busca_frame,
            text="🔁 Repetir",
            variable=self.repetir_var,
            bg='#161b22',
            fg='#f0c040',
            selectcolor='#21262d',
            activebackground='#161b22',
            activeforeground='#f0c040',
            font=("Arial", 11),
            cursor='hand2'
        ).pack(side='left', padx=(5, 10))

        # Separador
        sep3 = tk.Frame(main_frame, bg='#30363d', height=1)
        sep3.pack(fill='x', padx=40, pady=(8, 8))

        # ── Lista de resultados ──
        list_container = tk.Frame(main_frame, bg='#161b22')
        list_container.pack(fill='both', expand=True, pady=10)

        self.canvas_lista = tk.Canvas(
            list_container, bg='#161b22', highlightthickness=0
        )
        scrollbar = tk.Scrollbar(
            list_container, orient="vertical", command=self.canvas_lista.yview,
            bg='#21262d', troughcolor='#161b22', activebackground='#6e40c9'
        )
        self.scroll_frame = tk.Frame(self.canvas_lista, bg='#161b22')

        self.scroll_frame.bind(
            "<Configure>",
            lambda e: self.canvas_lista.configure(
                scrollregion=self.canvas_lista.bbox("all")
            )
        )
        self.canvas_inner_id = self.canvas_lista.create_window(
            (0, 0), window=self.scroll_frame, anchor="nw"
        )

        # Faz o frame interno acompanhar a largura do canvas
        def _ajustar_largura_canvas(event):
            self.canvas_lista.itemconfig(self.canvas_inner_id, width=event.width)

        self.canvas_lista.bind("<Configure>", _ajustar_largura_canvas)
        self.canvas_lista.configure(yscrollcommand=scrollbar.set)

        self.canvas_lista.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")


        # ── Controles ──
        controls_frame = tk.Frame(main_frame, bg='#161b22')
        controls_frame.pack(fill='x', pady=(10, 0), ipady=8)

        # Botões de controle em estilo "pill" (ícones grandes, sem texto)
        pill_frame = tk.Frame(controls_frame, bg='#21262d', highlightthickness=0)
        pill_frame.pack(side='left', padx=5)

        def _criar_botao_pill(parent, icone, tooltip, comando, icone_png=None):
            """Botão-pílula: usa o PNG `icone_png` (ícone fixo) quando existe;
            senão cai para o caractere `icone` (emoji/texto do sistema)."""
            args = dict(
                bg='#21262d', fg='#f0c040', activebackground='#6e40c9',
                activeforeground='#f0c040',
                command=comando, cursor='hand2',
                bd=0, highlightthickness=0,
                padx=14, pady=6
            )
            imagem = _carregar_icone(icone_png) if icone_png else None
            if imagem is not None:
                # Botão com ícone PNG (não depende de fontes do sistema)
                args.update(text="", image=imagem, width=40, height=40,
                            compound="center")
                btn = tk.Button(parent, **args)
                btn._navepro_imagem = imagem  # mantém ref para não sumir
            else:
                args.update(text=icone, font=("Arial", 18))
                btn = tk.Button(parent, **args)
            btn.pack(side='left', padx=0)
            # Cria tooltip
            _criar_tooltip(btn, tooltip)
            return btn

        def _criar_tooltip(widget, texto):
            tooltip_win = None
            def mostrar(event):
                nonlocal tooltip_win
                if tooltip_win:
                    return
                x = widget.winfo_rootx() + widget.winfo_width() // 2
                y = widget.winfo_rooty() + widget.winfo_height() + 5
                tooltip_win = tk.Toplevel(widget)
                tooltip_win.wm_overrideredirect(True)
                tooltip_win.wm_geometry(f"+{x}+{y}")
                tooltip_win.configure(bg='#161b22')
                lbl = tk.Label(tooltip_win, text=texto, bg='#161b22',
                               fg='#f0c040', font=("Arial", 9),
                               padx=8, pady=3)
                lbl.pack()
            def esconder(event):
                nonlocal tooltip_win
                if tooltip_win:
                    tooltip_win.destroy()
                    tooltip_win = None
            widget.bind("<Enter>", mostrar)
            widget.bind("<Leave>", esconder)

        _criar_botao_pill(pill_frame, "⏮", "Anterior", self.tocar_anterior)
        _criar_botao_pill(pill_frame, "⏯", "Play / Pause", self.player.play_pause)
        _criar_botao_pill(pill_frame, "⏹", "Parar", self.parar)
        _criar_botao_pill(pill_frame, "⏭", "Próximo", self.tocar_proximo)

        # Espaçador flexível
        tk.Frame(controls_frame, bg='#161b22').pack(side='left', fill='x', expand=True)

        # Botões dos novos módulos (frame separado à direita)
        modulos_frame = tk.Frame(controls_frame, bg='#21262d', highlightthickness=0)
        modulos_frame.pack(side='right', padx=5)
        _criar_botao_pill(modulos_frame, "📖", "Hinos / Letras", self.janela_hinos)
        _criar_botao_pill(modulos_frame, "✝️", "Bíblia", self.janela_biblia)
        _criar_botao_pill(modulos_frame, "📋", "Ordem de Serviço", self.janela_ordem_servico)
        _criar_botao_pill(modulos_frame, "📢", "Anúncios", self.janela_anuncios)

        # Botão Gerenciar Banco (também em estilo pill)
        args_gerenciar = dict(
            bg='#21262d', fg='#f0c040', activebackground='#6e40c9',
            command=self.abrir_gerenciador, cursor='hand2',
            bd=0, highlightthickness=0,
            padx=14, pady=6
        )
        args_gerenciar.update(text="📦", font=("Arial", 16))
        btn_gerenciar = tk.Button(controls_frame, **args_gerenciar)
        btn_gerenciar.pack(side='right', padx=5)
        _criar_tooltip(btn_gerenciar, "Gerenciar Banco")

        # Botão Configura Relógio (barra de controles)
        btn_config_relogio = tk.Button(
            controls_frame, text="🕐", font=("Arial", 16),
            bg='#21262d', fg='#f0c040', activebackground='#6e40c9',
            command=self.abrir_config_relogio_dialogo, cursor='hand2',
            bd=0, highlightthickness=0, padx=14, pady=6
        )
        btn_config_relogio.pack(side='right', padx=5)
        _criar_tooltip(btn_config_relogio, "Configura Relógio")

    # ── Lista de resultados (com cache para evitar redesenho e centralização) ────

    def _iniciar_pulse(self) -> None:
        """Inicia animação do ícone ▶ no item tocando (pisca suave)."""
        if not hasattr(self, '_pool_botoes'):
            return
        self._parar_pulse()
        self._pulse_state = 0
        self._animar_pulse()

    def _parar_pulse(self) -> None:
        """Para a animação do ícone pulsante."""
        if self._pulse_timer:
            try:
                self.root.after_cancel(self._pulse_timer)
            except (tk.TclError, ValueError):
                pass
            self._pulse_timer = None

    def _animar_pulse(self) -> None:
        """Anima o ícone ▶ alternando entre ▶ e ▷, e atualiza barra de progresso."""
        if not self.arquivo_atual or not self.player or not self.player.is_playing:
            return
        if not hasattr(self, '_pool_botoes'):
            return

        dados = self.arquivos_encontrados
        if not dados or self.arquivo_atual not in dados:
            return

        idx = dados.index(self.arquivo_atual)
        if idx >= 80:
            self._pulse_timer = self.root.after(1000, self._animar_pulse)
            return

        # Alterna entre ▶ e ▷
        self._pulse_state = 1 - self._pulse_state
        btn = self._pool_botoes[idx]
        current_text = btn.cget('text')

        if current_text.startswith('▶') or current_text.startswith('▷'):
            novo_prefixo = '▶' if self._pulse_state == 0 else '▷'
            novo_texto = novo_prefixo + current_text[1:]
            btn.config(text=novo_texto)

        # Atualiza barra de progresso (preenche proporcionalmente toda a largura)
        progress_frame, progress_bar = self._pool_progress_bars[idx]
        duracao = self.player.duracao_total
        if duracao and duracao > 0:
            elapsed = self.player.obter_tempo_decorrido()
            frac = min(elapsed / duracao, 1.0)
            progress_bar.place(relwidth=frac, relheight=1.0)

        self._pulse_timer = self.root.after(800, self._animar_pulse)

    def _criar_pool_botoes(self) -> None:
        """Cria o pool de itens recicláveis (cabeçalho + 80 linhas)."""
        self._pool_botoes = []
        self._pool_frames = []
        self._pool_progress_bars = []
        self._pool_label_count = tk.Label(
            self.scroll_frame, text="", fg='#8b949e', bg='#161b22', font=("Arial", 11)
        )
        self._pool_label_count.pack(pady=5, anchor='center')
        for i in range(80):  # Cria 80 linhas
            # Frame container (cor alternada)
            item_frame = tk.Frame(self.scroll_frame, bg='#1c2128' if i % 2 == 0 else '#21262d')
            item_frame.pack(fill='x', padx=100, pady=1)

            # Barra de progresso (inicialmente oculta) - usa place para largura relativa
            progress_frame = tk.Frame(item_frame, bg='#161b22', height=3)
            progress_bar = tk.Frame(progress_frame, bg='#6e40c9', height=3)
            progress_frame.pack_forget()  # Oculta inicialmente

            # Botão principal
            btn = tk.Button(
                item_frame,
                text="", anchor='center',
                font=("Arial", 11),
                bg='#1c2128' if i % 2 == 0 else '#21262d',
                fg='#c9d1d9',
                activebackground='#6e40c9',
                cursor='hand2', bd=0, highlightthickness=0
            )
            btn.pack(fill='x', side='top')

            self._pool_botoes.append(btn)
            self._pool_frames.append(item_frame)
            self._pool_progress_bars.append((progress_frame, progress_bar))

        # Label de vazio (inicialmente oculto)
        self._pool_label_vazio = tk.Label(
            self.scroll_frame, text="🔍 Nenhum arquivo encontrado",
            fg='#8b949e', bg='#161b22', font=("Arial", 12)
        )
        # Guarda referência do caminho atual para cada botão
        self._pool_caminhos: list[Optional[str]] = [None] * 80
        # Timer para animação do ícone pulsante
        self._pulse_timer: Optional[str] = None
        self._pulse_index: int = -1
        self._pulse_state: int = 0

    def atualizar_lista(self) -> None:
        """Atualiza a lista reciclando itens do pool (cores alternadas, barra de progresso)."""
        if not hasattr(self, '_pool_botoes'):
            self._criar_pool_botoes()

        # Esconde label vazio, mostra contagem
        self._pool_label_vazio.pack_forget()
        dados = self.arquivos_encontrados
        total = len(dados)

        if not dados:
            self._pool_label_count.config(text="")
            self._pool_label_vazio.pack(pady=20, anchor='center')
            for frame in self._pool_frames:
                frame.pack_forget()
            return

        self._pool_label_count.config(text=f"📋 {total} arquivo(s)")

        num_visiveis = min(total, 80)
        for i in range(80):
            if i < num_visiveis:
                caminho = dados[i]
                nome = os.path.basename(caminho)
                tipo = "🎵" if caminho.lower().endswith(('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac')) else "🎬"

                # Extrai número do hino do nome do arquivo (para exibição)
                match_num = re.match(r'^(\d+)', nome)
                if match_num:
                    num_hino = match_num.group(1)
                    resto_nome = nome[len(num_hino):].lstrip(' -._')
                else:
                    num_hino = ""
                    resto_nome = nome

                # Verifica se é a música atual
                is_current = (self.arquivo_atual and caminho == self.arquivo_atual)

                # Monta texto: contagem sequencial + número do hino entre parênteses
                if num_hino:
                    texto = f"  {i+1}. {tipo} ({num_hino}) {resto_nome}"
                else:
                    texto = f"  {i+1}. {tipo} {nome}"

                # Se for a música atual, prefixo muda conforme pulse
                if is_current:
                    texto = "▶" + texto[1:] if getattr(self, '_pulse_state', 0) == 0 else "▷" + texto[1:]

                frame = self._pool_frames[i]
                btn = self._pool_botoes[i]

                # Cor de fundo: verde se tocando, alternado caso contrário
                if is_current:
                    bg_cor = '#238636'
                    fg_cor = '#f0c040'
                else:
                    bg_cor = '#1c2128' if i % 2 == 0 else '#21262d'
                    fg_cor = '#c9d1d9'

                btn.config(text=texto, bg=bg_cor, fg=fg_cor)
                self._pool_caminhos[i] = caminho
                btn.config(command=lambda c=caminho: self.tocar_arquivo(c))

                frame.pack(fill='x', padx=100, pady=1)

                # Barra de progresso para item atual (ocupa toda a largura do frame)
                progress_frame, progress_bar = self._pool_progress_bars[i]
                if is_current and self.player and self.player.is_playing:
                    duracao = self.player.duracao_total
                    if duracao and duracao > 0:
                        elapsed = self.player.obter_tempo_decorrido()
                        frac = min(elapsed / duracao, 1.0)
                        progress_frame.pack(fill='x', side='top', before=btn)
                        # place com relwidth = fração, ocupando toda a largura
                        progress_bar.place(relwidth=frac, relheight=1.0)
                    else:
                        # Se não tem duração, mostra barra cheia (indeterminado)
                        progress_frame.pack(fill='x', side='top', before=btn)
                        progress_bar.place(relwidth=1.0, relheight=1.0)
                else:
                    progress_frame.pack_forget()
            else:
                self._pool_frames[i].pack_forget()

        # Inicia animação do ícone pulsante se há música tocando
        if self.arquivo_atual and self.player and self.player.is_playing:
            self._iniciar_pulse()
        else:
            self._parar_pulse()


    # ── Controles de reprodução ──────────────────────────────────

    def tocar_arquivo(self, caminho: str) -> None:
        """Inicia a reprodução de um arquivo específico."""
        if self.arquivos_encontrados and caminho in self.arquivos_encontrados:
            self.player.carregar_playlist(self.arquivos_encontrados)
            self.player.tocar_indice(
                self.arquivos_encontrados.index(caminho)
            )
        else:
            self.arquivo_atual = caminho
            self.player.carregar_playlist([caminho])
            self.player.play_pause()

        self._cancel_focus_timer()
        self.root.focus_set()

    def tocar_proximo(self) -> bool:
        return self.player.proximo()

    def tocar_anterior(self) -> bool:
        return self.player.anterior()

    def atualizar_status(self) -> None:
        """Atualiza o label de status com informações da faixa atual."""
        self.player.sincronizar_tempo_dbus()

        arquivo_atual = self.arquivo_atual
        if not arquivo_atual:
            self.status_label.config(text="")
            return

        nome = os.path.basename(arquivo_atual)
        arquivos = self.arquivos_encontrados
        player = self.player

        if player.is_playing:
            if arquivos and arquivo_atual in arquivos:
                pos = arquivos.index(arquivo_atual) + 1
                base_text = f"▶ {nome} ({pos}/{len(arquivos)})"
            else:
                base_text = f"▶ {nome}"
        elif player.is_paused:
            base_text = f"⏸️ {nome} (Pausado)"
        else:
            base_text = ""

        tempo_info = player.tempo_inicio is not None or player.tempo_acumulado > 0
        if tempo_info and nome:
            elapsed = player.obter_tempo_decorrido()
            duracao = player.duracao_total
            tempo_str = f" • ⏱️ {self._formatar_tempo(elapsed)}"
            if duracao:
                tempo_str += f" / {self._formatar_tempo(duracao)}"
            base_text += tempo_str

        self.status_label.config(text=base_text)

    @staticmethod
    def _formatar_tempo(segundos: Optional[float]) -> str:
        if segundos is None:
            return "00:00"
        total_seg = int(segundos)
        h, resto = divmod(total_seg, 3600)
        m, s = divmod(resto, 60)
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def parar(self) -> None:
        """Para a reprodução."""
        self._parar_pulse()
        self.player.stop()
        self.arquivo_atual = None
        self.atualizar_status()
        self.atualizar_lista()

    def atualizar_relogio(self) -> None:
        """Atualiza o relógio na interface e no telão.

        Otimizado: só chama mostrar_relogio() se a hora mudou e
        usa _ultima_hora_telao para evitar redesenho do Canvas
        quando o texto não mudou.
        """
        try:
            hora_atual = datetime.now().strftime("%H:%M")
            self.hora_label.config(text=hora_atual)

            # Status a cada 2 segundos para reduzir chamadas D-Bus
            # (o relógio é a cada 1s, status a cada 2s)
            now_sec = datetime.now().second
            if now_sec % 2 == 0:
                self.atualizar_status()

            # Telão: só atualiza se estiver no modo relógio
            if self.player and self.player.telao.mostrando_relogio:
                # Verifica se a hora mudou antes de chamar o telão
                ultima_hora = getattr(self, '_ultima_hora_telao', None)
                if ultima_hora is None or ultima_hora != hora_atual:
                    self._ultima_hora_telao = hora_atual
                    temp_display = self.temperatura_atual if self._temperatura_valida() else ""
                    self.player.mostrar_relogio(hora_atual, temp_display)
        except Exception:
            pass
        self.root.after(1000, self.atualizar_relogio)

    # ── Gerenciador de Banco (mantido, com recarga de cache) ────

    def abrir_gerenciador(self) -> None:
        """Abre a janela de gerenciamento de mídias."""
        self._janela_gerenciar_midias()

    def _janela_gerenciar_midias(self) -> None:
        """Janela completa para gerenciar as mídias do banco."""
        janela = tk.Toplevel(self.root)
        janela.title("📦 Gerenciar Banco de Mídia")
        janela.geometry("800x900")
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        janela.after(50, janela.grab_set)

        main = tk.Frame(janela, bg='#0d1117')
        main.pack(fill='both', expand=True, padx=15, pady=15)

        # Info (variável local)
        gerenciador_info = tk.Label(
            main, text="📊 Carregando...",
            font=("Arial", 14, "bold"), fg='#f0c040', bg='#0d1117'
        )
        gerenciador_info.pack(fill='x')

        # Botões
        btn_frame = tk.Frame(main, bg='#0d1117')
        btn_frame.pack(fill='x', pady=10)

        # Filtros (variável local)
        filtro_var = tk.StringVar(value="todos")

        # TreeView (variável local)
        list_container = tk.Frame(main, bg='#161b22')
        list_container.pack(fill='both', expand=True, pady=5)

        colunas = ("ID", "Nome", "Tipo", "Tamanho", "Arquivo")
        gerenciador_tree = ttk.Treeview(
            list_container, columns=colunas,
            show='headings', height=15
        )
        for col in colunas:
            gerenciador_tree.heading(col, text=col)
            widths = {
                "ID": 40, "Nome": 250, "Tipo": 70,
                "Tamanho": 80, "Arquivo": 300,
            }
            gerenciador_tree.column(col, width=widths.get(col, 100))

        scrollbar_y = tk.Scrollbar(
            list_container, orient="vertical",
            command=gerenciador_tree.yview
        )
        gerenciador_tree.configure(yscrollcommand=scrollbar_y.set)
        gerenciador_tree.pack(side='left', fill='both', expand=True)
        scrollbar_y.pack(side='right', fill='y')

        # Estilo
        style = ttk.Style()
        style.theme_use('clam')
        style.configure(
            "Treeview",
            background="#21262d", foreground="#c9d1d9",
            fieldbackground="#21262d", font=("Arial", 10)
        )
        style.configure(
            "Treeview.Heading",
            background="#161b22", foreground="#f0c040",
            font=("Arial", 10, "bold")
        )
        style.map('Treeview', background=[('selected', '#6e40c9')],
                  foreground=[('selected', '#ffffff')])
        style.configure("Vertical.TScrollbar", background="#21262d",
                        troughcolor="#161b22", arrowcolor="#f0c040")

        def _atualizar_lista():
            """Atualiza a TreeView (closure)."""
            try:
                tipo_filtro = filtro_var.get()
                filtro = "" if tipo_filtro == "todos" else f"?tipo={tipo_filtro}"
                req = urllib.request.Request(f"{BACKEND_URL}/api/midia{filtro}")
                with _baixar(req, timeout=5) as resp:
                    midias: list[dict] = json.loads(resp.read().decode())
            except Exception:
                midias = []

            total = len(midias)
            videos = sum(1 for m in midias if m['tipo'] == 'video')
            audios = sum(1 for m in midias if m['tipo'] == 'audio')
            textos = sum(1 for m in midias if m['tipo'] == 'texto')

            try:
                gerenciador_info.config(
                    text=f"📊 {total} mídia(s)  |  🎬 {videos}  🎵 {audios}  📄 {textos}"
                )
            except tk.TclError:
                pass

            for item in gerenciador_tree.get_children():
                gerenciador_tree.delete(item)

            for m in midias:
                tamanho = m.get('tamanho_bytes', 0)
                if tamanho > 1024 * 1024:
                    tamanho_str = f"{tamanho / 1024 / 1024:.1f} MB"
                elif tamanho > 1024:
                    tamanho_str = f"{tamanho / 1024:.1f} KB"
                else:
                    tamanho_str = f"{tamanho} B"

                icone = {"video": "🎬", "audio": "🎵", "texto": "📄"}
                icon = icone.get(m['tipo'], "📁")
                gerenciador_tree.insert(
                    "", tk.END, iid=str(m['id']),
                    values=(
                        m['id'],
                        f"{icon} {m['nome_exibicao']}",
                        m['tipo'],
                        tamanho_str,
                        os.path.basename(m.get('caminho_arquivo', '')),
                    )
                )

        # Botões (usam closures em vez de self._*)
        tk.Button(
            btn_frame, text="📂 Adicionar Mídias",
            font=("Arial", 11, "bold"),
            bg='#238636', fg='white', activebackground='#2ea043',
            command=lambda: self._adicionar_midias_ao_banco(
                janela, _atualizar_lista),
            cursor='hand2', padx=15, pady=5
        ).pack(side='left', padx=5)

        def _remover():
            """Remove selecionadas (closure)."""
            selecionados = gerenciador_tree.selection()
            if not selecionados:
                tkinter.messagebox.showwarning(
                    "Seleção", "Selecione pelo menos uma mídia na lista!",
                    parent=janela,
                )
                return

            if not tkinter.messagebox.askyesno(
                "Confirmar",
                f"Remover {len(selecionados)} mídia(s)?",
                parent=janela,
            ):
                return

            for midia_id in selecionados:
                db_execute(
                    "UPDATE midia SET ativo = 0, data_modificacao = datetime('now') WHERE id = ?",
                    (int(midia_id),),
                )

            self.db.reload_cache()
            tkinter.messagebox.showinfo(
                "✅",
                f"{len(selecionados)} mídia(s) removida(s)!",
                parent=janela,
            )
            _atualizar_lista()

        tk.Button(
            btn_frame, text="🗑️ Remover Selecionadas",
            font=("Arial", 11, "bold"),
            bg='#da3633', fg='white', activebackground='#f85149',
            command=_remover,
            cursor='hand2', padx=15, pady=5
        ).pack(side='left', padx=5)

        tk.Button(
            btn_frame, text="🔄 Atualizar Lista",
            font=("Arial", 11, "bold"),
            bg='#21262d', fg='#f0c040', activebackground='#30363d',
            command=_atualizar_lista,
            cursor='hand2', padx=15, pady=5
        ).pack(side='left', padx=5)

        # Filtros (usam closure)
        filtro_frame = tk.Frame(main, bg='#161b22')
        filtro_frame.pack(fill='x', pady=5, ipady=3)

        for texto, valor in [
            ("📋 Todos", "todos"),
            ("🎬 Vídeos", "video"),
            ("🎵 Áudios", "audio"),
            ("📄 Textos", "texto"),
        ]:
            tk.Radiobutton(
                filtro_frame, text=texto,
                variable=filtro_var, value=valor,
                bg='#161b22', fg='#c9d1d9', selectcolor='#21262d',
                activebackground='#161b22',
                command=_atualizar_lista
            ).pack(side='left', padx=8)

        # Carrega dados iniciais
        _atualizar_lista()



    # ── Seletor de arquivos personalizado (mantido) ──────────────

    def _selecionar_arquivos_personalizado(
        self, janela_pai: tk.Toplevel
    ) -> list[str]:
        """Janela personalizada para selecionar arquivos de mídia.

        Mostra apenas pastas do usuário que NÃO começam com '.'
        (ocultas). Carregamento rápido e assíncrono.
        """
        EXTENSOES_VALIDAS = {
            '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.webm',
            '.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac',
            '.txt', '.pdf',
        }

        selecionados: list[str] = []
        home = os.path.expanduser("~")
        pasta_atual: list[str] = [home]
        carregando = [False]  # Flag para evitar carregamento concorrente

        def _chave_ordenacao_natural(nome: str) -> tuple:
            """Gera chave para ordenação numérica natural."""
            match = re.match(r"(\d+)[\s\-._]+(.+)", nome)
            if match:
                return (0, int(match.group(1)), match.group(2).casefold())
            match = re.match(r"(\d+)", nome)
            if match:
                num = int(match.group(1))
                resto = nome[len(match.group(1)):].lstrip(' -._').casefold()
                return (0, num, resto)
            return (1, 0, nome.casefold())

        def escanear_pastas_rapido(caminho: str) -> list[str]:
            """Escaneia apenas subpastas não ocultas (rápido, sem stat)."""
            try:
                with os.scandir(caminho) as it:
                    return sorted(
                        (e.name for e in it
                         if e.is_dir(follow_symlinks=False)
                         and not e.name.startswith('.')),
                        key=_chave_ordenacao_natural
                    )
            except (PermissionError, OSError):
                return []

        def escanear_arquivos_rapido(caminho: str) -> list[str]:
            """Escaneia apenas arquivos de mídia não ocultos."""
            try:
                with os.scandir(caminho) as it:
                    return sorted(
                        (e.name for e in it
                         if e.is_file(follow_symlinks=False)
                         and not e.name.startswith('.')
                         and os.path.splitext(e.name)[1].lower() in EXTENSOES_VALIDAS),
                        key=_chave_ordenacao_natural
                    )
            except (PermissionError, OSError):
                return []

        def atualizar_conteudo() -> None:
            """Atualiza a lista na thread principal (rápido, sem bloquear)."""
            if carregando[0]:
                return
            carregando[0] = True

            caminho = pasta_atual[0]

            # Atualiza label do caminho
            caminho_label.config(text=f"📁 {caminho}")
            estado_label.config(text="⏳ Carregando...")
            lista.delete(0, tk.END)
            lista.insert(tk.END, "⏳ Carregando...")
            janela.update_idletasks()

            # Escaneia em background
            def _carregar():
                try:
                    pastas = escanear_pastas_rapido(caminho)
                    arquivos = escanear_arquivos_rapido(caminho)

                    janela.after(0, lambda: _preencher_lista(pastas, arquivos))
                except Exception as e:
                    janela.after(0, lambda: _preencher_lista([], [], erro=str(e)))

            def _preencher_lista(pastas: list[str], arquivos: list[str], erro: str = "") -> None:
                lista.delete(0, tk.END)

                if erro:
                    lista.insert(tk.END, f"❌ Erro: {erro}")
                    estado_label.config(text="Erro ao acessar diretório")
                    carregando[0] = False
                    return

                # Pastas (com ícone e cor diferente)
                for p in pastas:
                    lista.insert(tk.END, f"📂 {p}")
                    lista.itemconfig(tk.END, {'fg': '#f0c040', 'bg': '#21262d'})

                # Separador visual se houver pastas e arquivos
                if pastas and arquivos:
                    lista.insert(tk.END, "")
                    lista.itemconfig(tk.END, {'bg': '#161b22', 'selectbackground': '#161b22'})

                # Arquivos
                for arq in arquivos:
                    ext = os.path.splitext(arq)[1].lower()
                    if ext in EXTENSOES_VIDEO:
                        icon = "🎬"
                    elif ext in EXTENSOES_AUDIO:
                        icon = "🎵"
                    else:
                        icon = "📄"
                    lista.insert(tk.END, f"{icon} {arq}")
                    lista.itemconfig(tk.END, {'fg': '#c9d1d9', 'bg': '#21262d'})

                # Se não há nada
                if not pastas and not arquivos:
                    lista.insert(tk.END, "📭 (vazio)")
                    lista.itemconfig(tk.END, {'fg': '#8b949e', 'bg': '#21262d'})

                # Atualiza estado
                selecionar_todos_btn.config(
                    state=tk.NORMAL if arquivos else tk.DISABLED
                )
                estado_label.config(
                    text=f"{len(pastas)} pasta(s), {len(arquivos)} arquivo(s) | "
                         f"{len(selecionados)} selecionado(s)"
                )
                adicionar_btn.config(text=f"📥 Adicionar ({len(selecionados)})")
                carregando[0] = False

            threading.Thread(target=_carregar, daemon=True).start()

        def ao_duplo_clicar(event: object = None) -> None:
            """Abre pasta ou seleciona arquivo ao dar duplo clique."""
            if carregando[0]:
                return
            selecao = lista.curselection()
            if not selecao:
                return
            item = lista.get(selecao[0])

            if item.startswith("📂"):
                nome_pasta = item[2:].strip()
                novo_caminho = os.path.join(pasta_atual[0], nome_pasta)
                if os.path.isdir(novo_caminho):
                    pasta_atual[0] = novo_caminho
                    atualizar_conteudo()
                    voltar_btn.config(
                        state=tk.NORMAL if pasta_atual[0] != home else tk.DISABLED
                    )
            elif item.startswith(("🎬", "🎵", "📄")):
                nome_arquivo = item[2:].strip()
                caminho_completo = os.path.join(pasta_atual[0], nome_arquivo)
                idx = selecao[0]
                if caminho_completo in selecionados:
                    selecionados.remove(caminho_completo)
                    lista.itemconfig(idx, {'bg': '#21262d'})
                else:
                    selecionados.append(caminho_completo)
                    lista.itemconfig(idx, {'bg': '#238636'})
                estado_label.config(
                    text=f"{len(selecionados)} selecionado(s)"
                )
                adicionar_btn.config(text=f"📥 Adicionar ({len(selecionados)})")

        def atualizar_contador_selecao() -> None:
            """Atualiza contador com base na seleção visual da lista (EXTENDED)."""
            if carregando[0]:
                return
            selecionados.clear()
            indices_selecionados = lista.curselection()
            for i in indices_selecionados:
                item = lista.get(i)
                if item.startswith(("🎬", "🎵", "📄")):
                    nome_arquivo = item[2:].strip()
                    caminho_completo = os.path.join(pasta_atual[0], nome_arquivo)
                    selecionados.append(caminho_completo)
            estado_label.config(text=f"{len(selecionados)} selecionado(s)")
            adicionar_btn.config(text=f"📥 Adicionar ({len(selecionados)})")

        def selecionar_todos() -> None:
            """Alterna seleção de todos os arquivos de mídia."""
            if carregando[0]:
                return
            indices_arquivos = [
                i for i in range(lista.size())
                if lista.get(i).startswith(("🎬", "🎵", "📄"))
            ]
            if not indices_arquivos:
                return

            selecao_atual = set(lista.curselection())
            todos_selecionados = all(i in selecao_atual for i in indices_arquivos)

            if todos_selecionados:
                for i in indices_arquivos:
                    lista.selection_clear(i)
            else:
                for i in indices_arquivos:
                    lista.selection_set(i)

            atualizar_contador_selecao()

        def voltar() -> None:
            """Volta para a pasta anterior."""
            if carregando[0]:
                return
            pasta_anterior = os.path.dirname(pasta_atual[0])
            if pasta_anterior != pasta_atual[0] and os.path.isdir(pasta_anterior):
                pasta_atual[0] = pasta_anterior
                atualizar_conteudo()
                voltar_btn.config(
                    state=tk.NORMAL if pasta_atual[0] != home else tk.DISABLED
                )

        def confirmar() -> None:
            """Confirma a seleção e fecha a janela."""
            atualizar_contador_selecao()  # Sincroniza antes de fechar
            janela.destroy()

        def cancelar() -> None:
            """Cancela e limpa a seleção."""
            selecionados.clear()
            janela.destroy()

        # ── Cria a janela ──
        janela = tk.Toplevel(janela_pai)
        janela.title("📂 Selecionar mídias")
        janela.geometry("700x500")
        janela.configure(bg='#0d1117')
        janela.transient(janela_pai)
        janela.after(50, janela.grab_set)

        # Caminho atual
        caminho_label = tk.Label(
            janela, text=f"📁 {home}",
            font=("Arial", 10), fg='#f0c040', bg='#0d1117',
            anchor='w'
        )
        caminho_label.pack(fill='x', padx=10, pady=(10, 2))

        # Lista com scroll
        frame_lista = tk.Frame(janela, bg='#161b22')
        frame_lista.pack(fill='both', expand=True, padx=10, pady=5)

        lista = tk.Listbox(
            frame_lista, font=("Arial", 12),
            bg='#21262d', fg='#c9d1d9', selectbackground='#6e40c9',
            selectforeground='white', highlightthickness=0,
            borderwidth=0, activestyle='none',
            selectmode=tk.EXTENDED
        )
        scrollbar = tk.Scrollbar(
            frame_lista, orient="vertical", command=lista.yview,
            bg='#21262d', troughcolor='#161b22', activebackground='#6e40c9'
        )
        lista.configure(yscrollcommand=scrollbar.set)
        lista.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        lista.bind("<Double-Button-1>", ao_duplo_clicar)
        lista.bind("<<ListboxSelect>>", lambda e: atualizar_contador_selecao())

        # Estado
        estado_label = tk.Label(
            janela, text="",
            font=("Arial", 10), fg='#8b949e', bg='#0d1117'
        )
        estado_label.pack(fill='x', padx=10, pady=2)

        # Botões
        botoes_frame = tk.Frame(janela, bg='#0d1117')
        botoes_frame.pack(fill='x', padx=10, pady=(5, 10))

        voltar_btn = tk.Button(
            botoes_frame, text="⬆️ Voltar",
            font=("Arial", 10, "bold"),
            bg='#21262d', fg='#f0c040', activebackground='#30363d',
            command=voltar, cursor='hand2',
            state=tk.DISABLED
        )
        voltar_btn.pack(side='left', padx=2)

        selecionar_todos_btn = tk.Button(
            botoes_frame, text="✅ Selecionar Todos",
            font=("Arial", 10, "bold"),
            bg='#238636', fg='white', activebackground='#2ea043',
            command=selecionar_todos, cursor='hand2',
            state=tk.DISABLED
        )
        selecionar_todos_btn.pack(side='left', padx=2)

        # Espaço flexível
        tk.Frame(botoes_frame, bg='#0d1117').pack(side='left', fill='x', expand=True)

        adicionar_btn = tk.Button(
            botoes_frame, text="📥 Adicionar (0)",
            font=("Arial", 11, "bold"),
            bg='#6e40c9', fg='#f0c040', activebackground='#8b5cf6',
            command=confirmar, cursor='hand2', padx=15
        )
        adicionar_btn.pack(side='right', padx=2)

        cancelar_btn = tk.Button(
            botoes_frame, text="❌ Cancelar",
            font=("Arial", 11, "bold"),
            bg='#da3633', fg='white', activebackground='#f85149',
            command=cancelar, cursor='hand2', padx=15
        )
        cancelar_btn.pack(side='right', padx=2)

        # Centraliza
        janela.update_idletasks()
        x = janela_pai.winfo_x() + 50
        y = janela_pai.winfo_y() + 50
        janela.geometry(f"+{x}+{y}")

        # Carrega conteúdo inicial
        atualizar_conteudo()

        # Aguarda o fechamento
        janela.wait_window()

        return selecionados

    def _adicionar_midias_ao_banco(
        self, janela_pai: tk.Toplevel,
        apos_adicionar: Optional[Callable[[], None]] = None,
    ) -> None:
        """Abre seletor de arquivos e adiciona ao banco."""
        arquivos = self._selecionar_arquivos_personalizado(janela_pai)
        if not arquivos:
            return

        adicionados = 0
        for caminho in arquivos:
            if not os.path.exists(caminho):
                continue
            tipo = detectar_tipo_arquivo(caminho)
            if not tipo:
                continue
            nome = os.path.basename(caminho)
            nome_exib = os.path.splitext(nome)[0]
            tamanho = os.path.getsize(caminho)
            mime, _ = mimetypes.guess_type(caminho)

            destino = os.path.join(UPLOAD_FOLDER, nome)
            contador = 1
            while os.path.exists(destino):
                nome_base, ext = os.path.splitext(nome)
                destino = os.path.join(
                    UPLOAD_FOLDER, f"{nome_base}_{contador}{ext}"
                )
                contador += 1

            try:
                shutil.copy2(caminho, destino)
            except Exception as e:
                print(f"Erro ao copiar {caminho}: {e}")
                continue

            db_execute(
                """INSERT INTO midia
                (nome_original, nome_exibicao, tipo, caminho_arquivo,
                 tamanho_bytes, mime_type, data_upload, data_modificacao)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
                (os.path.basename(destino), nome_exib, tipo, destino,
                 tamanho, mime or ''),
            )
            adicionados += 1

        if adicionados > 0:
            # Recarregar cache
            self.db.reload_cache()
            tkinter.messagebox.showinfo(
                "✅ Sucesso",
                f"{adicionados} mídia(s) adicionada(s) ao banco!",
                parent=janela_pai,
            )
            if apos_adicionar is not None:
                apos_adicionar()
        else:
            tkinter.messagebox.showwarning(
                "⚠️", "Nenhuma mídia válida foi adicionada.",
                parent=janela_pai,
            )

    # ────────────────────────────────────────────────────────────────────
    # JANELA DE HINOS / LETRAS
    # ────────────────────────────────────────────────────────────────────

    def janela_hinos(self) -> None:
        """Abre a janela de gerenciamento de hinos e letras."""
        janela = tk.Toplevel(self.root)
        janela.title("📖 Hinos / Letras")
        janela.geometry("950x750")
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        janela.after(50, janela.grab_set)

        main = tk.Frame(janela, bg='#0d1117')
        main.pack(fill='both', expand=True, padx=15, pady=15)

        tk.Label(main, text="📖 Biblioteca de Hinos e Letras",
                 font=("Arial", 16, "bold"), fg='#f0c040', bg='#0d1117'
                 ).pack(pady=(0, 10))

        # ── Barra de busca ──
        busca_frame = tk.Frame(main, bg='#161b22')
        busca_frame.pack(fill='x', pady=5, ipady=5)

        tk.Label(busca_frame, text="🔍", fg='#f0c040', bg='#161b22',
                 font=("Arial", 14)).pack(side='left', padx=(8, 5))

        placeholder = "Buscar por número, título, artista ou letra..."
        entry_busca = tk.Entry(busca_frame, font=("Arial", 13),
                               bg='#21262d', fg='#8b949e', insertbackground='#f0c040',
                               bd=0, highlightthickness=0)
        entry_busca.pack(side='left', fill='x', expand=True, padx=5, ipady=4)
        entry_busca.insert(0, placeholder)

        def _on_focus_entry():
            if entry_busca.get().strip() == placeholder:
                entry_busca.delete(0, tk.END)
                entry_busca.config(fg='#f0c040')

        def _on_focus_out_entry():
            if not entry_busca.get().strip():
                entry_busca.delete(0, tk.END)
                entry_busca.insert(0, placeholder)
                entry_busca.config(fg='#8b949e')

        entry_busca.bind("<FocusIn>", lambda e: _on_focus_entry())
        entry_busca.bind("<FocusOut>", lambda e: _on_focus_out_entry())

        # ── TreeView ──
        tree_frame = tk.Frame(main, bg='#161b22')
        tree_frame.pack(fill='both', expand=True, pady=5)

        colunas = ("ID", "Título", "Artista", "Categoria", "CCLI")
        tree = ttk.Treeview(tree_frame, columns=colunas, show='headings', height=18)
        for col in colunas:
            tree.heading(col, text=col)
        tree.column("ID", width=40)
        tree.column("Título", width=250)
        tree.column("Artista", width=200)
        tree.column("Categoria", width=120)
        tree.column("CCLI", width=100)

        scroll_y = tk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll_y.set)
        tree.pack(side='left', fill='both', expand=True)
        scroll_y.pack(side='right', fill='y')

        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Treeview", background="#21262d", foreground="#c9d1d9",
                        fieldbackground="#21262d", font=("Arial", 10))
        style.configure("Treeview.Heading", background="#161b22", foreground="#f0c040",
                        font=("Arial", 10, "bold"))
        style.map('Treeview', background=[('selected', '#6e40c9')],
                  foreground=[('selected', '#ffffff')])

        def _carregar_hinos(busca: str = ""):
            for item in tree.get_children():
                tree.delete(item)
            if busca and busca != placeholder:
                if busca.isdigit():
                    # Número do hino está no começo do título (ex.: "11 - ...").
                    num = int(busca)
                    rows = [r for r in db_query(
                                "SELECT * FROM letras WHERE ativo = 1 ORDER BY titulo")
                            if _numero_do_titulo(r["titulo"]) == num]
                else:
                    busca_like = f"%{busca}%"
                    rows = db_query(
                        "SELECT * FROM letras WHERE ativo = 1 AND "
                        "(titulo LIKE ? OR artista LIKE ? OR letra_completa LIKE ?) "
                        "ORDER BY titulo", (busca_like, busca_like, busca_like))
            else:
                rows = db_query(
                    "SELECT * FROM letras WHERE ativo = 1 ORDER BY titulo")
            for r in rows:
                tree.insert("", tk.END, iid=str(r['id']),
                            values=(r['id'], r['titulo'], r['artista'],
                                    r['categoria'], r['ccli_numero']))

        def _buscar(event=None):
            termo = entry_busca.get().strip()
            if termo == placeholder or termo.startswith(placeholder):
                termo = termo[len(placeholder):].strip()
            _carregar_hinos(termo)

        def _buscar_e_projetar(event=None):
            """Enter na busca: filtra e já projeta o primeiro resultado.

            Mesmo efeito de buscar, selecionar a 1ª linha com o mouse e
            clicar em "📺 Projetar". Com o campo vazio não projeta nada.
            """
            termo = entry_busca.get().strip()
            if termo == placeholder or termo.startswith(placeholder):
                termo = termo[len(placeholder):].strip()
            _carregar_hinos(termo)
            if not termo:
                return "break"
            primeiro = tree.get_children()
            if not primeiro:
                tkinter.messagebox.showwarning(
                    "Busca", "Nenhum hino encontrado para projetar.", parent=janela)
                return "break"
            tree.selection_set(primeiro[0])
            tree.focus(primeiro[0])
            _projetar_hino_selecionado()
            return "break"

        entry_busca.bind("<Return>", _buscar_e_projetar)
        # Busca em tempo real com debounce
        _debounce_id = [None]
        def _on_key(event=None):
            if _debounce_id[0]:
                janela.after_cancel(_debounce_id[0])
            _debounce_id[0] = janela.after(400, _buscar)
        entry_busca.bind("<KeyRelease>", _on_key)

        # ── Importação de letras (XML / TXT) ──
        _NS_OPENLYRICS = "http://openlyrics.info/namespace/2009/song"

        def _texto_no(tag: str, el: Optional[ET.Element]) -> str:
            """Retorna o texto concatenado do primeiro elemento filho com a tag dada."""
            if el is None:
                return ""
            for filho in el.iter():
                if filho.tag == f"{{{_NS_OPENLYRICS}}}{tag}":
                    return "".join(filho.itertext()).strip()
            return ""

        def _parsear_xml_letra(caminho: str) -> Optional[Dict]:
            """Extrai {titulo, artista, letra} de um arquivo XML no formato OpenLyrics/OpenLP."""
            try:
                with open(caminho, "r", encoding="utf-8", errors="replace") as f:
                    conteudo = f.read()
                raiz = ET.fromstring(conteudo)

                propriedades = raiz.find(f"{{{_NS_OPENLYRICS}}}properties")
                titulo = _texto_no("title", propriedades)
                artista = _texto_no("author", propriedades)
                if not titulo:
                    titulo = os.path.splitext(os.path.basename(caminho))[0]

                letra = []
                lyrics = raiz.find(f"{{{_NS_OPENLYRICS}}}lyrics")
                if lyrics is not None:
                    versos = []
                    for verse in lyrics.findall(f"{{{_NS_OPENLYRICS}}}verse"):
                        linhas = verse.find(f"{{{_NS_OPENLYRICS}}}lines")
                        if linhas is None:
                            continue
                        texto_verso = "".join(linhas.itertext())
                        texto_verso = re.sub(r"[ \t]+", " ", texto_verso)
                        texto_verso = re.sub(r"\n{3,}", "\n\n", texto_verso)
                        texto_verso = texto_verso.strip("\n")
                        if texto_verso:
                            versos.append(texto_verso)
                    letra = versos

                return {
                    "titulo": titulo,
                    "artista": artista,
                    "letra_completa": "\n\n".join(letra),
                }
            except Exception as e:
                print(f"⚠️ Erro ao ler XML {caminho}: {e}")
                return None

        def _parsear_txt_letra(caminho: str) -> Optional[Dict]:
            """Extrai {titulo, artista, letra} de um arquivo TXT (1ª linha = título)."""
            try:
                conteudo = None
                for enc in ("utf-8", "latin-1"):
                    try:
                        with open(caminho, "r", encoding=enc) as f:
                            conteudo = f.read()
                        break
                    except (UnicodeDecodeError, UnicodeError):
                        continue
                if conteudo is None:
                    with open(caminho, "r", encoding="utf-8", errors="replace") as f:
                        conteudo = f.read()

                linhas = [l.strip() for l in conteudo.splitlines()]
                linhas = [l for l in linhas if l]
                if not linhas:
                    return None

                titulo = linhas[0]
                letra = "\n".join(linhas[1:])
                return {
                    "titulo": titulo,
                    "artista": "",
                    "letra_completa": letra,
                }
            except Exception as e:
                print(f"⚠️ Erro ao ler TXT {caminho}: {e}")
                return None

        def _importar_letras(caminhos: tuple) -> None:
            """Importa letras de arquivos XML/TXT para a tabela letras."""
            if not caminhos:
                return
            importados, ja_existem, erros = 0, 0, 0
            for caminho in caminhos:
                ext = os.path.splitext(caminho)[1].lower()
                if ext == ".xml":
                    dados = _parsear_xml_letra(caminho)
                elif ext == ".txt":
                    dados = _parsear_txt_letra(caminho)
                else:
                    erros += 1
                    continue

                if not dados or not dados.get("titulo"):
                    erros += 1
                    continue

                titulo = dados["titulo"]
                existente = db_query(
                    "SELECT id FROM letras WHERE titulo = ? AND ativo = 1", (titulo,))
                if existente:
                    ja_existem += 1
                    continue

                _inserir_com_id_reuso(
                    "letras",
                    ("titulo", "artista", "compositor", "ccli_numero",
                     "categoria", "letra_completa"),
                    (titulo, dados["artista"], "", "", "",
                     dados["letra_completa"]))
                importados += 1

            _carregar_hinos()
            msg = f"✅ {importados} importados, {ja_existem} já existentes (pulados)."
            if erros:
                msg += f"\n⚠️ {erros} arquivo(s) com erro."
            tkinter.messagebox.showinfo("Importação", msg, parent=janela)

        def _importar_arquivos() -> None:
            selecionados = _escolher_arquivos_usuario(
                parent=janela,
                titulo="Importar letras (XML / TXT)",
                sufixos=(".xml", ".txt"))
            if selecionados:
                _importar_letras(tuple(selecionados))

        # ── Ajustes da projeção no telão ──
        def _configurar_projecao():
            """Abre janela para ajustar a aparência da projeção no telão."""
            self.abrir_config_projecao_dialogo(janela)

        # ── Botões ──
        btn_frame = tk.Frame(main, bg='#0d1117')
        btn_frame.pack(fill='x', pady=8)

        def _novo_hino():
            _abrir_editor_hino(None)

        def _editar_hino():
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um hino.", parent=janela)
                return
            _abrir_editor_hino(int(sel[0]))

        def _excluir_hino():
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um hino.", parent=janela)
                return
            if not tkinter.messagebox.askyesno("Confirmar",
                    f"Excluir {len(sel)} hino(s)?", parent=janela):
                return
            for hino_id in sel:
                db_execute("DELETE FROM letras WHERE id = ?", (int(hino_id),))
            _carregar_hinos(entry_busca.get().strip())

        tk.Button(btn_frame, text="➕ Novo Hino", font=("Arial", 11, "bold"),
                  bg='#238636', fg='white', activebackground='#2ea043',
                  command=_novo_hino, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="✏️ Editar", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_editar_hino, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="🗑️ Excluir", font=("Arial", 11, "bold"),
                  bg='#da3633', fg='white', activebackground='#f85149',
                  command=_excluir_hino, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="📥 Importar (XML/TXT)", font=("Arial", 11, "bold"),
                  bg='#8b5cf6', fg='white', activebackground='#a78bfa',
                  command=_importar_arquivos, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="🎨 Projeção", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_configurar_projecao, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="📺 Projetar", font=("Arial", 11, "bold"),
                  bg='#6e40c9', fg='#f0c040', activebackground='#8b5cf6',
                  command=lambda: _projetar_hino_selecionado(), cursor='hand2', padx=12, pady=4
                  ).pack(side='right', padx=3)

        # ── Painel de controle da projeção (slides) ──
        nav_frame = tk.Frame(main, bg='#161b22')
        nav_frame.pack(fill='x', pady=(4, 2), ipady=4)

        tk.Label(nav_frame, text="🎬 Controle da Projeção:",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#161b22'
                 ).pack(side='left', padx=(10, 8))

        tk.Button(nav_frame, text="◀ Anterior", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=lambda: _slide_anterior(), cursor='hand2', padx=12, pady=2
                  ).pack(side='left', padx=3)
        tk.Button(nav_frame, text="Próximo ▶", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=lambda: _slide_proximo(), cursor='hand2', padx=12, pady=2
                  ).pack(side='left', padx=3)
        tk.Button(nav_frame, text="⏹ Parar (Esc)", font=("Arial", 11, "bold"),
                  bg='#da3633', fg='white', activebackground='#f85149',
                  command=lambda: _parar_projecao(), cursor='hand2', padx=12, pady=2
                  ).pack(side='left', padx=3)

        tk.Label(nav_frame, text="🔠 Tamanho:",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#161b22'
                 ).pack(side='left', padx=(14, 2))
        tk.Button(nav_frame, text="A−", font=("Arial", 11, "bold"),
                  bg='#8957e5', fg='white', activebackground='#a371f7',
                  command=lambda: _ajustar_fonte(-0.8), cursor='hand2', padx=10, pady=2
                  ).pack(side='left', padx=2)
        tk.Button(nav_frame, text="A+", font=("Arial", 11, "bold"),
                  bg='#8957e5', fg='white', activebackground='#a371f7',
                  command=lambda: _ajustar_fonte(0.8), cursor='hand2', padx=10, pady=2
                  ).pack(side='left', padx=2)

        label_slide = tk.Label(nav_frame, text="Sem projeção",
                               font=("Arial", 11, "bold"), fg='#8b949e', bg='#161b22')
        label_slide.pack(side='right', padx=10)

        def _atualizar_indicador_slide():
            try:
                if not label_slide.winfo_exists():
                    return
            except tk.TclError:
                return
            telao = self.player.telao
            em_slides = getattr(telao, "_em_slides", False)
            if em_slides and telao._slides:
                label_slide.config(
                    text=f"Slide {telao._slide_index + 1} de {len(telao._slides)}",
                    fg='#3fb950', bg='#161b22')
            elif getattr(telao, "_mostrando_imagem", False):
                label_slide.config(text="🖼️ Imagem ativa", fg='#3fb950', bg='#161b22')
            elif getattr(telao, "mostrando_letra", False):
                label_slide.config(text="Projeção ativa", fg='#f0c040', bg='#161b22')
            else:
                label_slide.config(text="Sem projeção", fg='#8b949e', bg='#161b22')

        def _slide_anterior(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if telao.slide_anterior():
                _atualizar_indicador_slide()
            return "break"

        def _slide_proximo(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if telao.slide_proximo():
                _atualizar_indicador_slide()
            return "break"

        def _parar_projecao(event: object = None):
            if not getattr(self.player.telao, "mostrando_letra", False):
                return None
            self.player.telao.parar_projecao()
            _atualizar_indicador_slide()
            return "break"

        def _ajustar_fonte(delta: float):
            """Aumenta/diminui a fonte da projeção e redesenha o que está ativo."""
            telao = self.player.telao
            cfg = getattr(telao, "_proj_cfg", None)
            if cfg is None:
                telao.configurar_projecao()
                cfg = telao._proj_cfg
            novo = min(15.0, max(1.0, float(cfg.get("tamanho_pct", 5.0)) + delta))
            cfg["tamanho_pct"] = novo
            telao._proj_cfg = cfg
            if getattr(telao, "_em_slides", False) and telao._slides:
                telao._mostrar_slide(telao._slide_index)
            elif getattr(telao, "mostrando_letra", False) and telao._current_text:
                telao._desenhar_texto_no_canvas(telao._current_text)
            self.salvar_config_projecao(dict(cfg))
            _atualizar_indicador_slide()

        # Setas do teclado e Esc (janela de hinos).
        # No root substituímos a ligação a cada abertura para evitar acumular
        # handlers duplicados de chamadas repetidas a janela_hinos.
        janela.bind("<Left>", _slide_anterior)
        janela.bind("<Up>", _slide_anterior)
        janela.bind("<Right>", _slide_proximo)
        janela.bind("<Down>", _slide_proximo)
        janela.bind("<Escape>", _parar_projecao)
        self.root.bind("<Left>", _slide_anterior)
        self.root.bind("<Up>", _slide_anterior)
        self.root.bind("<Right>", _slide_proximo)
        self.root.bind("<Down>", _slide_proximo)
        self.root.bind("<Escape>", _parar_projecao)

        def _montar_slides_hino(hino: dict) -> list:
            """Monta os slides de um hino em MAIÚSCULAS: slide 0 é o título,
            os demais são uma linha de verso por slide."""
            titulo = (hino.get('titulo') or '').strip().upper()
            letra = (hino.get('letra_completa') or '').strip()
            versos = [seg.strip() for seg in re.split(r'\n\s*\n', letra) if seg.strip()]
            slides = [titulo] if titulo else []
            for verso in versos:
                for linha in verso.split('\n'):
                    linha = linha.strip().upper()
                    if linha:
                        slides.append(linha)
            if not slides:
                slides = [titulo or "HINO"]
            return slides

        def _projetar_hino_selecionado():
            """Inicia a projeção em slides (título + versos) no telão.

            O administrador navega com as setas do teclado ou nos botões
            do painel; Esc encerra e volta o relógio + temperatura ao telão.
            """
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um hino.", parent=janela)
                return
            hino_id = int(sel[0])
            rows = db_query("SELECT * FROM letras WHERE id = ? AND ativo = 1", (hino_id,))
            if not rows:
                return
            hino = rows[0]
            slides = _montar_slides_hino(dict(hino))
            self.player.telao.projetar_slides(slides)
            _atualizar_indicador_slide()

        # ── Editor de hino ──
        def _abrir_editor_hino(hino_id: Optional[int] = None):
            editar_win = tk.Toplevel(janela)
            editar_win.title("Editar Hino" if hino_id else "Novo Hino")
            editar_win.geometry("600x600")
            editar_win.configure(bg='#0d1117')
            editar_win.transient(janela)
            editar_win.after(50, editar_win.grab_set)

            e_main = tk.Frame(editar_win, bg='#0d1117')
            e_main.pack(fill='both', expand=True, padx=15, pady=15)

            # Campos
            campos = {}
            for label_text, campo, default in [
                ("Título:", "titulo", ""),
                ("Artista:", "artista", ""),
                ("Compositor:", "compositor", ""),
                ("Nº CCLI:", "ccli_numero", ""),
                ("Categoria:", "categoria", ""),
            ]:
                row = tk.Frame(e_main, bg='#0d1117')
                row.pack(fill='x', pady=2)
                tk.Label(row, text=label_text, font=("Arial", 11, "bold"),
                         fg='#f0c040', bg='#0d1117', width=12, anchor='e').pack(side='left')
                entry = tk.Entry(row, font=("Arial", 11), bg='#21262d', fg='#c9d1d9',
                                 insertbackground='#f0c040', bd=0, highlightthickness=0)
                entry.pack(side='left', fill='x', expand=True, padx=5, ipady=3)
                campos[campo] = entry

            tk.Label(e_main, text="Letra completa:", font=("Arial", 11, "bold"),
                     fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x', pady=(8, 2))
            letra_text = tk.Text(e_main, font=("Arial", 11), bg='#21262d', fg='#c9d1d9',
                                 insertbackground='#f0c040', wrap='word', height=18)
            letra_text.pack(fill='both', expand=True, pady=2)

            # Carrega dados se editando
            dados_hino = {}
            if hino_id:
                rows = db_query("SELECT * FROM letras WHERE id = ?", (hino_id,))
                if rows:
                    dados_hino = rows[0]
                    campos['titulo'].insert(0, dados_hino.get('titulo', ''))
                    campos['artista'].insert(0, dados_hino.get('artista', ''))
                    campos['compositor'].insert(0, dados_hino.get('compositor', ''))
                    campos['ccli_numero'].insert(0, dados_hino.get('ccli_numero', ''))
                    campos['categoria'].insert(0, dados_hino.get('categoria', ''))
                    letra_text.insert('1.0', dados_hino.get('letra_completa', ''))

            def _salvar():
                titulo = campos['titulo'].get().strip()
                if not titulo:
                    tkinter.messagebox.showwarning("Erro", "Título é obrigatório.", parent=editar_win)
                    return
                artista = campos['artista'].get().strip()
                compositor = campos['compositor'].get().strip()
                ccli = campos['ccli_numero'].get().strip()
                categoria = campos['categoria'].get().strip()
                letra = letra_text.get('1.0', tk.END).strip()

                if hino_id:
                    db_execute(
                        "UPDATE letras SET titulo=?, artista=?, compositor=?, "
                        "ccli_numero=?, categoria=?, letra_completa=?, "
                        "atualizado_em=datetime('now') WHERE id=?",
                        (titulo, artista, compositor, ccli, categoria, letra, hino_id))
                else:
                    _inserir_com_id_reuso(
                        "letras",
                        ("titulo", "artista", "compositor", "ccli_numero",
                         "categoria", "letra_completa"),
                        (titulo, artista, compositor, ccli, categoria, letra))
                _carregar_hinos()
                editar_win.destroy()

            tk.Button(e_main, text="💾 Salvar", font=("Arial", 12, "bold"),
                      bg='#238636', fg='white', activebackground='#2ea043',
                      command=_salvar, cursor='hand2', padx=20, pady=5
                      ).pack(pady=10)

        _carregar_hinos()

    # ────────────────────────────────────────────────────────────────────
    # JANELA DE ANÚNCIOS (armazenados em JSON, FORA do banco de dados)
    # ────────────────────────────────────────────────────────────────────

    def janela_anuncios(self) -> None:
        """Abre a janela de gerenciamento de anúncios.

        Mesma cara da janela "Hinos / Letras", mas:
          - o botão "Novo Anúncio" cria anúncio;
          - o botão "Importar" aceita TXT e PDF (vira slide de texto);
          - "Importar Mídia" aceita vídeo, áudio e imagem (slide de imagem);
          - TUDO é salvo no banco de dados SQLite (tabela "anuncios"),
            inclusive o caminho do arquivo de mídia importado.
        """
        janela = tk.Toplevel(self.root)
        janela.title("📢 Anúncios")
        janela.geometry("950x700")
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        janela.after(50, janela.grab_set)

        main = tk.Frame(janela, bg='#0d1117')
        main.pack(fill='both', expand=True, padx=15, pady=15)

        titulo_label = tk.Label(main, text="📢 Anúncios",
                font=("Arial", 16, "bold"), fg='#f0c040', bg='#0d1117')
        titulo_label.pack(pady=(0, 2))
        tk.Label(main, text="Salvos no banco de dados SQLite — aceitam texto, vídeo, áudio e slide (imagem)",
                font=("Arial", 9), fg='#8b949e', bg='#0d1117').pack(pady=(0, 8))

        # ── Barra de busca ──
        busca_frame = tk.Frame(main, bg='#161b22')
        busca_frame.pack(fill='x', pady=5, ipady=5)

        tk.Label(busca_frame, text="🔍", fg='#f0c040', bg='#161b22',
                 font=("Arial", 14)).pack(side='left', padx=(8, 5))

        placeholder = "Buscar por título ou texto..."
        entry_busca = tk.Entry(busca_frame, font=("Arial", 13),
                               bg='#21262d', fg='#8b949e', insertbackground='#f0c040',
                               bd=0, highlightthickness=0)
        entry_busca.pack(side='left', fill='x', expand=True, padx=5, ipady=4)
        entry_busca.insert(0, placeholder)

        def _on_focus_entry():
            if entry_busca.get().strip() == placeholder:
                entry_busca.delete(0, tk.END)
                entry_busca.config(fg='#f0c040')

        def _on_focus_out_entry():
            if not entry_busca.get().strip():
                entry_busca.delete(0, tk.END)
                entry_busca.insert(0, placeholder)
                entry_busca.config(fg='#8b949e')

        entry_busca.bind("<FocusIn>", lambda e: _on_focus_entry())
        entry_busca.bind("<FocusOut>", lambda e: _on_focus_out_entry())

        # ── TreeView ──
        tree_frame = tk.Frame(main, bg='#161b22')
        tree_frame.pack(fill='both', expand=True, pady=5)

        colunas = ("ID", "Título", "Categoria", "Tipo")
        tree = ttk.Treeview(tree_frame, columns=colunas, show='headings', height=18)
        for col in colunas:
            tree.heading(col, text=col)
        tree.column("ID", width=50)
        tree.column("Título", width=360)
        tree.column("Categoria", width=170)
        tree.column("Tipo", width=150)

        scroll_y = tk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll_y.set)
        tree.pack(side='left', fill='both', expand=True)
        scroll_y.pack(side='right', fill='y')

        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Treeview", background="#21262d", foreground="#c9d1d9",
                        fieldbackground="#21262d", font=("Arial", 10))
        style.configure("Treeview.Heading", background="#161b22", foreground="#f0c040",
                        font=("Arial", 10, "bold"))
        style.map('Treeview', background=[('selected', '#6e40c9')],
                  foreground=[('selected', '#ffffff')])

        def _carregar_anuncios(busca: str = ""):
            for item in tree.get_children():
                tree.delete(item)
            termo = (busca or "").strip()
            # Ignora o placeholder (ex.: "Buscar por título ou texto...")
            if placeholder and (termo == placeholder or termo.startswith(placeholder)):
                termo = termo[len(placeholder):].strip()
            termo = termo.lower()
            for a in _listar_anuncios_db():
                if termo and termo != "":
                    alvo = " ".join([
                        a.get('titulo', ''),
                        a.get('categoria', ''),
                        a.get('texto', ''),
                    ]).lower()
                    if termo not in alvo:
                        continue
                tipo = a.get('tipo_midia') or 'slide'
                rotulo_tipo = {"slide": "📄 Texto", "video": "🎬 Vídeo",
                               "audio": "🎵 Áudio",
                               "imagem": "🖼️ Imagem"}.get(tipo, tipo)
                tree.insert("", tk.END, iid=str(a.get('id')),
                            values=(a.get('id'), a.get('titulo', ''),
                                    a.get('categoria', ''), rotulo_tipo))

        def _buscar(event=None):
            termo = entry_busca.get().strip()
            if termo == placeholder or termo.startswith(placeholder):
                termo = termo[len(placeholder):].strip()
            _carregar_anuncios(termo)

        def _buscar_e_projetar(event=None):
            """Enter na busca: filtra e já projeta o primeiro anúncio.

            Mesmo efeito de buscar, selecionar a 1ª linha com o mouse e
            clicar em "📺 Projetar". Com o campo vazio não projeta nada.
            """
            termo = entry_busca.get().strip()
            if termo == placeholder or termo.startswith(placeholder):
                termo = termo[len(placeholder):].strip()
            _carregar_anuncios(termo)
            if not termo:
                return "break"
            primeiro = tree.get_children()
            if not primeiro:
                tkinter.messagebox.showwarning(
                    "Busca", "Nenhum anúncio encontrado para projetar.", parent=janela)
                return "break"
            tree.selection_set(primeiro[0])
            tree.focus(primeiro[0])
            _projetar_anuncio_selecionado()
            return "break"

        entry_busca.bind("<Return>", _buscar_e_projetar)
        _debounce_id = [None]

        def _on_key(event=None):
            if _debounce_id[0]:
                janela.after_cancel(_debounce_id[0])
            _debounce_id[0] = janela.after(400, _buscar)

        entry_busca.bind("<KeyRelease>", _on_key)

        # ── Importação TXT / PDF ──
        def _parsear_txt_anuncio(caminho: str) -> Optional[Dict]:
            """Extrai {titulo, categoria, texto} de um TXT (1ª linha = título)."""
            try:
                conteudo = None
                for enc in ("utf-8", "latin-1"):
                    try:
                        with open(caminho, "r", encoding=enc) as f:
                            conteudo = f.read()
                        break
                    except (UnicodeDecodeError, UnicodeError):
                        continue
                if conteudo is None:
                    with open(caminho, "r", encoding="utf-8", errors="replace") as f:
                        conteudo = f.read()

                linhas = [l.strip() for l in conteudo.splitlines() if l.strip()]
                if not linhas:
                    return None
                return {
                    "titulo": linhas[0],
                    "categoria": "",
                    "texto": "\n".join(linhas[1:]),
                }
            except Exception as e:
                print(f"⚠️ Erro ao ler TXT de anúncio {caminho}: {e}")
                return None

        def _parsear_pdf_anuncio(caminho: str) -> Optional[Dict]:
            """Extrai {titulo, categoria, texto} de um PDF (título = nome do arquivo)."""
            try:
                texto = _extrair_texto_pdf(caminho)
                if not texto:
                    return None
                texto_limpo = re.sub(r"[ \t]+", " ", texto)
                texto_limpo = re.sub(r"\n{3,}", "\n\n", texto_limpo).strip("\n")
                return {
                    "titulo": os.path.splitext(os.path.basename(caminho))[0],
                    "categoria": "",
                    "texto": texto_limpo,
                }
            except Exception as e:
                print(f"⚠️ Erro ao ler PDF de anúncio {caminho}: {e}")
                return None

        def _adicionar_anuncio(dados: Dict) -> bool:
            """Adiciona um anúncio na tabela 'anuncios'. True se salvou."""
            return _inserir_anuncio_db(dados) is not None

        def _importar_anuncios(caminhos: tuple) -> tuple:
            """Importa TXT/PDF como anúncios tipo 'slide'.

            Retorna (importados, ja_existem, erros).
            """
            importados, ja_existem, erros = 0, 0, 0
            if not caminhos:
                return importados, ja_existem, erros
            titulos_existentes = {str(a.get('titulo', '')).lower()
                                  for a in _listar_anuncios_db()}
            for caminho in caminhos:
                ext = os.path.splitext(caminho)[1].lower()
                if ext == ".txt":
                    dados = _parsear_txt_anuncio(caminho)
                elif ext == ".pdf":
                    dados = _parsear_pdf_anuncio(caminho)
                else:
                    erros += 1
                    continue

                if not dados or not dados.get("titulo"):
                    erros += 1
                    continue

                titulo = dados["titulo"].strip()
                if titulo.lower() in titulos_existentes:
                    ja_existem += 1
                    continue

                if _inserir_anuncio_db({
                        "titulo": titulo,
                        "categoria": (dados.get('categoria') or '').strip(),
                        "texto": (dados.get('texto') or '').strip(),
                        "tipo_midia": "slide"}):
                    titulos_existentes.add(titulo.lower())
                    importados += 1
                else:
                    erros += 1
            return importados, ja_existem, erros

        def _importar_midias() -> None:
            """Importa TXT/PDF/vídeo/áudio/imagem: cada arquivo vira um anúncio.

            TXT/PDF viram anúncios tipo 'slide' (texto), as mídias mantêm o
            tipo detectado pela extensão.
            """
            sufixos = tuple(sorted(
                EXTENSOES_VIDEO | EXTENSOES_AUDIO | SUFIXOS_IMAGEM | {".txt", ".pdf"}))
            selecionados = _escolher_arquivos_usuario(
                parent=janela,
                titulo="Importar arquivos (TXT / PDF / vídeo / áudio / imagem)",
                sufixos=sufixos)
            if not selecionados:
                return
            importados, ja_existem, erros = 0, 0, 0

            # TXT/PDF primeiro (geram anúncios de texto)
            docs = [c for c in selecionados
                    if os.path.splitext(c)[1].lower() in (".txt", ".pdf")]
            if docs:
                di, dj, de = _importar_anuncios(tuple(docs))
                importados += di
                ja_existem += dj
                erros += de

            for caminho in selecionados:
                ext = os.path.splitext(caminho)[1].lower()
                if not caminho or not os.path.isfile(caminho) or ext in (".txt", ".pdf"):
                    continue
                tipo = _tipo_midia_para_arquivo(caminho)
                if not tipo:
                    erros += 1
                    continue
                destino = _copiar_arquivo_uploads(caminho)
                if destino is None:
                    erros += 1
                    continue
                titulo = os.path.splitext(os.path.basename(caminho))[0]
                if _inserir_anuncio_db({
                        "titulo": titulo,
                        "categoria": "",
                        "texto": "",
                        "tipo_midia": tipo,
                        "arquivo_midia": destino,
                        "nome_arquivo_midia": os.path.basename(destino)}):
                    importados += 1
                else:
                    erros += 1

            _carregar_anuncios()
            msg = f"✅ {importados} anúncio(s) importado(s)."
            if ja_existem:
                msg += f"  ({ja_existem} já existente(s) pulado(s).)"
            if erros:
                msg += f"\n⚠️ {erros} arquivo(s) com erro."
            tkinter.messagebox.showinfo("Importação", msg, parent=janela)

        # ── Ajustes da projeção no telão ──
        def _configurar_projecao():
            self.abrir_config_projecao_dialogo(janela)

        # ── Botões ──
        btn_frame = tk.Frame(main, bg='#0d1117')
        btn_frame.pack(fill='x', pady=8)

        def _novo_anuncio():
            _abrir_editor_anuncio(None)

        def _editar_anuncio():
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um anúncio.", parent=janela)
                return
            _abrir_editor_anuncio(int(sel[0]))

        def _excluir_anuncio():
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um anúncio.", parent=janela)
                return
            if not tkinter.messagebox.askyesno("Confirmar",
                    f"Excluir {len(sel)} anúncio(s)?", parent=janela):
                return
            ids_excluir = {int(i) for i in sel}
            if not _excluir_anuncios_db(ids_excluir):
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível gravar a exclusão no banco.",
                    parent=janela)
                return
            _carregar_anuncios(entry_busca.get().strip())

        tk.Button(btn_frame, text="➕ Novo Anúncio", font=("Arial", 11, "bold"),
                  bg='#238636', fg='white', activebackground='#2ea043',
                  command=_novo_anuncio, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="✏️ Editar", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_editar_anuncio, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="🗑️ Excluir", font=("Arial", 11, "bold"),
                  bg='#da3633', fg='white', activebackground='#f85149',
                  command=_excluir_anuncio, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="📥 Importar Mídia", font=("Arial", 11, "bold"),
                  bg='#8b5cf6', fg='white', activebackground='#a78bfa',
                  command=_importar_midias, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="🎨 Projeção", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_configurar_projecao, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="📺 Projetar", font=("Arial", 11, "bold"),
                  bg='#6e40c9', fg='#f0c040', activebackground='#8b5cf6',
                  command=lambda: _projetar_anuncio_selecionado(), cursor='hand2',
                  padx=12, pady=4).pack(side='right', padx=3)

        # ── Painel de controle da projeção (slides) ──
        nav_frame = tk.Frame(main, bg='#161b22')
        nav_frame.pack(fill='x', pady=(4, 2), ipady=4)

        tk.Label(nav_frame, text="🎬 Controle da Projeção:",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#161b22'
                 ).pack(side='left', padx=(10, 8))

        tk.Button(nav_frame, text="◀ Anterior", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=lambda: _slide_anterior(), cursor='hand2', padx=12, pady=2
                  ).pack(side='left', padx=3)
        tk.Button(nav_frame, text="Próximo ▶", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=lambda: _slide_proximo(), cursor='hand2', padx=12, pady=2
                  ).pack(side='left', padx=3)
        tk.Button(nav_frame, text="⏹ Parar (Esc)", font=("Arial", 11, "bold"),
                  bg='#da3633', fg='white', activebackground='#f85149',
                  command=lambda: _parar_projecao(), cursor='hand2', padx=12, pady=2
                  ).pack(side='left', padx=3)

        tk.Label(nav_frame, text="🔠 Tamanho:",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#161b22'
                 ).pack(side='left', padx=(14, 2))
        tk.Button(nav_frame, text="A−", font=("Arial", 11, "bold"),
                  bg='#8957e5', fg='white', activebackground='#a371f7',
                  command=lambda: _ajustar_fonte(-0.8), cursor='hand2', padx=10, pady=2
                  ).pack(side='left', padx=2)
        tk.Button(nav_frame, text="A+", font=("Arial", 11, "bold"),
                  bg='#8957e5', fg='white', activebackground='#a371f7',
                  command=lambda: _ajustar_fonte(0.8), cursor='hand2', padx=10, pady=2
                  ).pack(side='left', padx=2)

        tk.Label(nav_frame, text="🖼️ Imagem:",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#161b22'
                 ).pack(side='left', padx=(14, 2))
        tk.Button(nav_frame, text="−", font=("Arial", 11, "bold"),
                  bg='#8957e5', fg='white', activebackground='#a371f7',
                  command=lambda: _ajustar_imagem(False), cursor='hand2', padx=10, pady=2
                  ).pack(side='left', padx=2)
        tk.Button(nav_frame, text="+", font=("Arial", 11, "bold"),
                  bg='#8957e5', fg='white', activebackground='#a371f7',
                  command=lambda: _ajustar_imagem(True), cursor='hand2', padx=10, pady=2
                  ).pack(side='left', padx=2)

        label_slide = tk.Label(nav_frame, text="Sem projeção",
                               font=("Arial", 11, "bold"), fg='#8b949e', bg='#161b22')
        label_slide.pack(side='right', padx=10)

        def _atualizar_indicador_slide():
            try:
                if not label_slide.winfo_exists():
                    return
            except tk.TclError:
                return
            telao = self.player.telao
            em_slides = getattr(telao, "_em_slides", False)
            if em_slides and telao._slides:
                label_slide.config(
                    text=f"Slide {telao._slide_index + 1} de {len(telao._slides)}",
                    fg='#3fb950', bg='#161b22')
            elif getattr(telao, "_mostrando_imagem", False):
                label_slide.config(text="🖼️ Imagem ativa", fg='#3fb950', bg='#161b22')
            elif getattr(telao, "mostrando_letra", False):
                label_slide.config(text="Projeção ativa", fg='#f0c040', bg='#161b22')
            else:
                label_slide.config(text="Sem projeção", fg='#8b949e', bg='#161b22')

        def _slide_anterior(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if telao.slide_anterior():
                _atualizar_indicador_slide()
            return "break"

        def _slide_proximo(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if telao.slide_proximo():
                _atualizar_indicador_slide()
            return "break"

        def _parar_projecao(event: object = None):
            if not getattr(self.player.telao, "mostrando_letra", False):
                return None
            self.player.telao.parar_projecao()
            _atualizar_indicador_slide()
            return "break"

        # Anúncio atualmente projetado (para gravar ao vivo o tamanho da fonte
        # em anúncios de imagem + texto, do mesmo jeito que o modo só-texto já
        # grava a configuração de projeção em config.json).
        _anuncio_proj = {"id": None, "dados": {}, "config": {},
                         "mslides": None, "idx_map": []}

        def _persistir_escala_texto(escala: float) -> None:
            """Grava a nova escala de fonte ('ts') no anúncio em projeção.

            Anúncio de imagem única: grava 'ts' no JSON de config_midia.
            Anúncio multi-slide com imagem: grava 'ts' no config do slide
            atualmente exibido. Não faz nada se não houver anúncio sendo
            projetado ou se o slide em exibição não tiver imagem.
            """
            pid = _anuncio_proj.get("id")
            if not pid:
                return
            try:
                cfg_dic = _anuncio_proj.get("config") or {}
                if not isinstance(cfg_dic, dict):
                    cfg_dic = {}
                c: dict = {}
                texto_local = ""
                mslides: list = []
                idx_ms = -1
                if _anuncio_proj.get("mslides") is not None:
                    idx_map = _anuncio_proj.get("idx_map") or []
                    tela_index = int(
                        getattr(self.player.telao, "_slide_index", 0) or 0)
                    if not (0 <= tela_index < len(idx_map)):
                        return
                    mslides = cfg_dic.get("mslides") or []
                    idx_ms = idx_map[tela_index]
                    if not (0 <= idx_ms < len(mslides)) or not isinstance(
                            mslides[idx_ms], dict):
                        return
                    try:
                        c = json.loads(mslides[idx_ms].get("config") or "{}")
                        if not isinstance(c, dict):
                            c = {}
                    except (ValueError, TypeError, AttributeError):
                        c = {}
                    texto_local = (mslides[idx_ms].get("texto") or "").strip()
                else:
                    c = cfg_dic
                    texto_local = (_anuncio_proj.get("dados") or {}).get(
                        "texto") or ""
                tw = int(c.get("tw") or 0)
                th = int(c.get("th") or 0)
                if tw <= 0 or th <= 0:
                    # Config sem caixa de texto (legada): cria a caixa padrão
                    # para a nova escala 'ts' valer na próxima projeção também.
                    mh = int(1440 * 0.04) or 40
                    mv = int(1080 * 0.06) or 60
                    caixa = _caixa_texto_padrao(
                        texto_local, 1440 - mh * 2, 1080 - mv * 2, mh, mv,
                        aspect_imagem=float(getattr(
                            self.player.telao, "_composicao_aspect_imagem", 0.0)
                            or 0.0))
                    c.update({"tx": int(caixa["x"]), "ty": int(caixa["y"]),
                              "tw": int(caixa["w"]), "th": int(caixa["h"])})
                c["ts"] = round(escala, 3)
                if _anuncio_proj.get("mslides") is not None:
                    mslides[idx_ms]["config"] = json.dumps(c, ensure_ascii=False)
                dados_proj = dict(_anuncio_proj.get("dados") or {})
                dados_proj["config_midia"] = json.dumps(
                    cfg_dic, ensure_ascii=False)
                _anuncio_proj["dados"] = dados_proj
                _anuncio_proj["config"] = cfg_dic
                _atualizar_anuncio_db(pid, dados_proj)
            except Exception as _e_persist:
                import traceback as _tb_persist
                _tb_persist.print_exc()
                print(f"⚠️ Falha ao autosalvar escala do anúncio {pid}: {_e_persist}")

        def _ajustar_fonte(delta: float):
            telao = self.player.telao
            if getattr(telao, "_mostrando_imagem_com_texto", False):
                # Anúncio de imagem + texto: ajusta o tamanho da fonte (escala
                # 'ts' da caixa de texto) em tempo real, sem tocar na imagem.
                texto = getattr(telao, "_current_text", "")
                if texto:
                    escala = float(getattr(telao, "_texto_escala", 1.0) or 1.0)
                    telao._texto_escala = min(2.5, max(0.25, escala + delta * 0.1))
                    telao._desenhar_texto_anuncio(texto)
                    _persistir_escala_texto(float(telao._texto_escala))
                _atualizar_indicador_slide()
                return
            cfg = getattr(telao, "_proj_cfg", None)
            if cfg is None:
                telao.configurar_projecao()
                cfg = telao._proj_cfg
            novo = min(15.0, max(1.0, float(cfg.get("tamanho_pct", 5.0)) + delta))
            cfg["tamanho_pct"] = novo
            telao._proj_cfg = cfg
            if getattr(telao, "_em_slides", False) and telao._slides:
                telao._mostrar_slide(telao._slide_index)
            elif getattr(telao, "mostrando_letra", False) and telao._current_text:
                telao._desenhar_texto_no_canvas(telao._current_text)
            self.salvar_config_projecao(dict(cfg))
            _atualizar_indicador_slide()

        def _ajustar_imagem(aumentar: bool):
            """Redimensiona SOMENTE a imagem já projetada no telão (ao vivo).

            Em anúncios de imagem + texto, é a camada da imagem que muda —
            o texto fica intacto. Em imagem pura, o comportamento é o mesmo
            de antes (escala centralizada).
            """
            telao = self.player.telao
            if not getattr(telao, "_mostrando_imagem", False):
                return
            if aumentar:
                telao.imagem_aumentar()
            else:
                telao.imagem_diminuir()

        # Setas do teclado e Esc (janela de anúncios), mesmo esquema da de hinos.
        janela.bind("<Left>", _slide_anterior)
        janela.bind("<Up>", _slide_anterior)
        janela.bind("<Right>", _slide_proximo)
        janela.bind("<Down>", _slide_proximo)
        janela.bind("<Escape>", _parar_projecao)
        self.root.bind("<Left>", _slide_anterior)
        self.root.bind("<Up>", _slide_anterior)
        self.root.bind("<Right>", _slide_proximo)
        self.root.bind("<Down>", _slide_proximo)
        self.root.bind("<Escape>", _parar_projecao)

        def _montar_slides_anuncio(anuncio: dict) -> list:
            """Monta os slides de um anúncio respeitando o texto digitado:
            slide 0 é o título, os demais são os parágrafos do texto (cada
            parágrafo = 1 slide, exatamente como o editor adiciona telas)."""
            titulo = (anuncio.get('titulo') or '').strip()
            texto = (anuncio.get('texto') or '').strip()
            paragrafos = [seg.strip() for seg in re.split(r'\n\s*\n', texto) if seg.strip()]
            slides = [titulo] if titulo else []
            for paragrafo in paragrafos:
                slides.append(paragrafo)
            if not slides:
                slides = [titulo or "ANÚNCIO"]
            return slides

        def _projetar_anuncio_selecionado():
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um anúncio.", parent=janela)
                return
            anuncio_id = int(sel[0])
            anuncio = next(
                (a for a in _listar_anuncios_db()
                 if int(a.get('id', 0)) == anuncio_id), None)
            if not anuncio:
                return
            tipo = anuncio.get('tipo_midia') or 'slide'
            arquivo = anuncio.get('arquivo_midia') or ''
            if tipo in ('video', 'audio') and arquivo and os.path.exists(arquivo):
                _anuncio_proj["id"] = None
                self.arquivos_encontrados = [arquivo]
                self.player.carregar_playlist([arquivo])
                self.player.tocar_indice(0)
                self.atualizar_lista()
                _atualizar_indicador_slide()
                return
            if tipo == 'imagem' and arquivo and os.path.exists(arquivo):
                texto_anuncio = (anuncio.get('texto') or '').strip()
                cfg_imagem: dict = {}
                try:
                    _ci = json.loads(anuncio.get('config_midia') or '{}')
                    if isinstance(_ci, dict):
                        cfg_imagem = _ci
                except (ValueError, TypeError, AttributeError):
                    cfg_imagem = {}
                _anuncio_proj.update({
                    "id": anuncio_id, "dados": dict(anuncio),
                    "config": cfg_imagem, "mslides": None, "idx_map": []})
                if self.player.telao.projetar_imagem_com_texto(
                        arquivo, texto_anuncio,
                        anuncio.get('config_midia') or ''):
                    _atualizar_indicador_slide()
                    return
                _anuncio_proj["id"] = None
                # Falhou a composição projetada: tenta a imagem pura
                if self.player.telao.projetar_imagem(arquivo):
                    _atualizar_indicador_slide()
                    return
                tkinter.messagebox.showwarning(
                    "Imagem", f"Não foi possível projetar:\n{arquivo}", parent=janela)
                return
            cfg_a: dict = {}
            try:
                _p = json.loads(anuncio.get('config_midia') or '{}')
                if isinstance(_p, dict):
                    cfg_a = _p
            except (ValueError, TypeError, AttributeError):
                cfg_a = {}
            if isinstance(cfg_a, dict) and isinstance(cfg_a.get("mslides"), list):
                # Anúncio multi-slide texto+imagem (cada slide pode ter imagem).
                mslides_orig = cfg_a["mslides"]
                slides = []
                idx_map = []
                for i, s in enumerate(mslides_orig):
                    if not isinstance(s, dict):
                        continue
                    texto_s = (s.get("texto") or '').strip()
                    imagem_s = (s.get("imagem") or '').strip()
                    if not texto_s and not imagem_s:
                        continue
                    slides.append({"texto": texto_s, "imagem": imagem_s,
                                   "config": s.get("config") or ''})
                    idx_map.append(i)
                if not slides:
                    slides = [{"texto": "ANÚNCIO", "imagem": '', "config": ''}]
                _anuncio_proj.update({
                    "id": anuncio_id, "dados": dict(anuncio),
                    "config": cfg_a, "mslides": mslides_orig, "idx_map": idx_map})
            else:
                slides = _montar_slides_anuncio(dict(anuncio))
                _anuncio_proj.update({
                    "id": None, "dados": {}, "config": {},
                    "mslides": None, "idx_map": []})
            self.player.telao.projetar_slides(slides)
            _atualizar_indicador_slide()

        # ── Editor de anúncio ──
        def _abrir_editor_anuncio(anuncio_id: Optional[int] = None):
            editar_win = tk.Toplevel(janela)
            editar_win.title("Editar Anúncio" if anuncio_id else "Novo Anúncio")
            editar_win.geometry("680x860")
            editar_win.configure(bg='#0d1117')
            editar_win.transient(janela)
            editar_win.after(50, editar_win.grab_set)

            e_main = tk.Frame(editar_win, bg='#0d1117')
            e_main.pack(fill='both', expand=True, padx=15, pady=15)

            # Campos
            campos = {}
            for label_text, campo, default in [
                ("Título:", "titulo", ""),
                ("Categoria:", "categoria", ""),
            ]:
                row = tk.Frame(e_main, bg='#0d1117')
                row.pack(fill='x', pady=2)
                tk.Label(row, text=label_text, font=("Arial", 11, "bold"),
                         fg='#f0c040', bg='#0d1117', width=12, anchor='e').pack(side='left')
                entry = tk.Entry(row, font=("Arial", 11), bg='#21262d', fg='#c9d1d9',
                                 insertbackground='#f0c040', bd=0, highlightthickness=0)
                entry.pack(side='left', fill='x', expand=True, padx=5, ipady=3)
                campos[campo] = entry

            # Carrega dados se editando
            dados_anuncio = {}
            if anuncio_id:
                para_editar = next(
                    (a for a in _listar_anuncios_db()
                     if int(a.get('id', 0)) == anuncio_id), None)
                if para_editar:
                    dados_anuncio = dict(para_editar)

            tk.Label(e_main, text="Tipo de conteúdo:", font=("Arial", 11, "bold"),
                     fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x', pady=(8, 2))
            rotulos_tipo = {
                "slide": "📄 Slide (texto)",
                "video": "🎬 Vídeo",
                "audio": "🎵 Áudio",
                "imagem": "🖼️ Imagem (slide)",
            }
            tipo_inicial = (dados_anuncio.get('tipo_midia') or 'slide') or 'slide'
            tipo_var = tk.StringVar(
                value=rotulos_tipo.get(tipo_inicial, rotulos_tipo["slide"]))
            tipo_combo = ttk.Combobox(
                e_main, textvariable=tipo_var, state='readonly',
                values=[rotulos_tipo[k] for k in ("slide", "video", "audio", "imagem")],
                font=("Arial", 11))
            tipo_combo.pack(fill='x', pady=2)

            def _tipo_interno() -> str:
                atual = tipo_var.get()
                if atual in rotulos_tipo:
                    return atual
                for k, v in rotulos_tipo.items():
                    if atual == v:
                        return k
                return "slide"

            arquivo_var = tk.StringVar(value=dados_anuncio.get('arquivo_midia') or '')

            arquivo_row = tk.Frame(e_main, bg='#0d1117')
            arquivo_row.pack(fill='x', pady=(6, 0))
            arquivo_label = tk.Label(arquivo_row, text="Nenhum arquivo selecionado",
                                     font=("Arial", 10), fg='#8b949e', bg='#0d1117',
                                     anchor='w')
            arquivo_label.pack(side='left', fill='x', expand=True, padx=5)

            def _atualizar_arquivo_label():
                caminho = arquivo_var.get().strip()
                if caminho:
                    arquivo_label.config(text=f"📎 {os.path.basename(caminho)}",
                                         fg='#3fb950')
                else:
                    arquivo_label.config(text="Nenhum arquivo selecionado", fg='#8b949e')

            def _escolher_arquivo():
                sufixos = {
                    "video": tuple(sorted(EXTENSOES_VIDEO)),
                    "audio": tuple(sorted(EXTENSOES_AUDIO)),
                    "imagem": tuple(sorted(SUFIXOS_IMAGEM)),
                    "slide": (),
                }[_tipo_interno()]
                if not sufixos:
                    tkinter.messagebox.showinfo(
                        "Dica", "Para tipo 'Slide (texto)' escreva o texto abaixo — "
                                "não precisa de arquivo. Para vídeo/áudio/imagem, "
                                "altere o tipo e selecione o arquivo.", parent=editar_win)
                    return
                titulo_dialogo = f"Escolher arquivo ({_tipo_interno()})"
                selecionados = _escolher_arquivos_usuario(
                    parent=editar_win, titulo=titulo_dialogo, sufixos=sufixos)
                if selecionados:
                    arquivo_var.set(selecionados[0])
                    _atualizar_arquivo_label()
                    _montar_area_conteudo()

            tk.Button(arquivo_row, text="📂 Selecionar arquivo",
                      font=("Arial", 10, "bold"),
                      bg='#1f6feb', fg='white', activebackground='#388bfd',
                      command=_escolher_arquivo, cursor='hand2', padx=10, pady=2
                      ).pack(side='right', padx=5)

            tk.Label(e_main, text="Texto do anúncio:", font=("Arial", 11, "bold"),
                     fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x', pady=(8, 2))

            area_conteudo = tk.Frame(e_main, bg='#0d1117')
            area_conteudo.pack(fill='both', expand=True, pady=2)

            # Estado compartilhado do modo imagem (posição/tamanho no espaço 1440x1080)
            _widget_texto = {"w": None}
            _texto_salvo = {"t": dados_anuncio.get('texto', '') if dados_anuncio else ''}
            # Estado do MODO SLIDE (múltiplas telas): lista de slides + índice atual.
            # Cada slide é {"texto", "imagem", "nome"} (imagem opcional).
            # São persistidos: textos separados por linha em branco na coluna
            # texto (mesmo formato da projeção) e, havendo imagens, o JSON
            # {"mslides": [...]} em config_midia.
            texto_original = dados_anuncio.get('texto', '') if dados_anuncio else ''
            mslides_ini: list = []
            if dados_anuncio:
                try:
                    _cfg_e = json.loads(dados_anuncio.get('config_midia') or '{}')
                    if isinstance(_cfg_e, dict) and isinstance(_cfg_e.get("mslides"), list):
                        mslides_ini = _cfg_e["mslides"]
                except (ValueError, TypeError, AttributeError):
                    mslides_ini = []
            if mslides_ini:
                lista_inicial = [
                    {"texto": (s.get("texto") or '') if isinstance(s, dict) else str(s),
                     "imagem": (s.get("imagem") or '') if isinstance(s, dict) else '',
                     "nome": (s.get("nome") or '') if isinstance(s, dict) else '',
                     "config": (s.get("config") or '') if isinstance(s, dict) else ''}
                    for s in mslides_ini]
            else:
                lista_inicial = [
                    {"texto": seg.strip(), "imagem": '', "nome": ''}
                    for seg in re.split(r'\n\s*\n', texto_original) if seg.strip()]
                if not lista_inicial and texto_original.strip():
                    lista_inicial = [{"texto": texto_original.strip(), "imagem": '', "nome": ''}]
                elif not lista_inicial:
                    lista_inicial = [{"texto": '', "imagem": '', "nome": ''}]
            _slides_estado = {
                "modo": False,
                "lista": lista_inicial,
                "idx": 0,
                "w": None,
            }
            _tam_img = {"w": None, "h": None, "x": None, "y": None, "orig": None}
            # Estado da CAIXA DE TEXTO (mesma prévia): posição/tamanho/escala.
            _tam_txt = {"w": None, "h": None, "x": None, "y": None, "s": 1.0}
            if dados_anuncio:
                try:
                    cfg = json.loads(dados_anuncio.get('config_midia') or '{}')
                    if isinstance(cfg, dict) and cfg.get("w"):
                        _tam_img["w"] = int(cfg["w"])
                        _tam_img["h"] = int(cfg["h"] or 0)
                        _tam_img["x"] = int(cfg.get("x") or 0)
                        _tam_img["y"] = int(cfg.get("y") or 0)
                        # Caixa de texto salva (tx/ty/tw/th/ts), se houver.
                        tw = int(cfg.get("tw") or 0)
                        th = int(cfg.get("th") or 0)
                        if tw > 0 and th > 0:
                            _tam_txt["w"] = tw
                            _tam_txt["h"] = th
                            _tam_txt["x"] = int(cfg.get("tx") or 0)
                            _tam_txt["y"] = int(cfg.get("ty") or 0)
                            _tam_txt["s"] = float(cfg.get("ts") or 1.0)
                except (ValueError, TypeError):
                    pass

            def _ler_texto() -> str:
                """Lê o texto atual (widget ou slides abertos) e sincroniza.

                Para anúncios de slide (múltiplas telas), devolve o texto que
                representa TODOS os slides separados por linha em branco
                (um slide por parágrafo — mesmo formato da projeção).
                """
                if _slides_estado["modo"]:
                    lista = _slides_estado["lista"]
                    idx = _slides_estado["idx"]
                    if 0 <= idx < len(lista):
                        _widget_texto_slide = _slides_estado.get("w")
                        if _widget_texto_slide is not None:
                            lista[idx]["texto"] = _widget_texto_slide.get(
                                '1.0', tk.END).strip()
                        _texto_salvo["t"] = "\n\n".join(
                            s.get("texto", '') for s in lista)
                    return _texto_salvo["t"]
                w = _widget_texto.get("w")
                if w is not None:
                    _texto_salvo["t"] = w.get('1.0', tk.END).strip()
                return _texto_salvo["t"]

            def _montar_painel_imagem(container, texto_widget, caminho,
                                      tam_img=None, tam_txt=None,
                                      texto_salvo=None, widget_texto=None) -> None:
                """Prévia única: o texto + a imagem no MESMO canvas, como será projetado.

                Coordenadas em espaço virtual 1440x1080 (o mesmo da composição no
                telão); o canvas mostra uma miniatura proporcional. A imagem fica
                por cima do texto, arrastável e redimensionável pelas alças.

                Por padrão usa o estado compartilhado do anúncio de imagem única.
                Passando tam_img/tam_txt/texto_salvo/widget_texto (e o container
                de um Toplevel), a MESMA prévia edita um slide específico do modo
                multi-slide, sem tocar no estado do editor principal.
                """
                if tam_img is None:
                    tam_img = _tam_img
                if tam_txt is None:
                    tam_txt = _tam_txt
                if texto_salvo is None:
                    texto_salvo = _texto_salvo
                if widget_texto is None:
                    widget_texto = _widget_texto
                try:
                    from PIL import Image
                    with Image.open(caminho) as im:
                        tam_img["orig"] = im.size
                except Exception:
                    tam_img["orig"] = None

                VW, VH = 1440, 1080
                ESCALA = 1 / 3.0
                CW = int(VW * ESCALA)
                CH = int(VH * ESCALA)
                LIN_V = 1
                MINV_V = 120
                margem_hv = int(VW * 0.04) or 40
                margem_vv = int(VH * 0.06) or 60
                area_wv = VW - margem_hv * 2
                area_hv = VH - margem_vv * 2

                def _clamp_v(v, lo, hi):
                    return max(lo, min(hi, v))

                painel = tk.Frame(container, bg='#0d1117')
                painel.pack(fill='both', expand=True)

                texto_widget.config(height=5)
                texto_widget.pack(fill='x', side='top', pady=(0, 6))
                widget_texto["w"] = texto_widget

                quadro = tk.Frame(painel, bg='#0d1117')
                quadro.pack(fill='both', expand=True)
                canvas = tk.Canvas(quadro, bg='#0d1117', width=CW, height=CH,
                                   highlightthickness=0)
                canvas.pack(anchor='center')

                origem_img = tam_img.get("orig")
                if not origem_img:
                    canvas.create_text(CW // 2, CH // 2,
                                       text="Imagem inválida", fill='#8b949e',
                                       font=("Arial", 11))
                    return
                ow, oh = origem_img
                aspect = ow / max(1, oh)

                prefe_w = tam_img.get("w")
                prefe_h = tam_img.get("h")
                prefe_x = tam_img.get("x")
                prefe_y = tam_img.get("y")
                tem_posicao = bool(prefe_w and prefe_h and prefe_x and prefe_y)

                if tem_posicao:
                    # Formato novo (virtual 1440x1080): usa o que foi salvo.
                    novo_w = _clamp_v(int(prefe_w), MINV_V, area_wv)
                    novo_h = _clamp_v(int(prefe_h), MINV_V, area_hv)
                    novo_x = _clamp_v(int(prefe_x), LIN_V, VW - LIN_V - novo_w)
                    novo_y = _clamp_v(int(prefe_y), LIN_V, VH - LIN_V - novo_h)
                elif prefe_w and prefe_h:
                    # Migra config antiga (canvas 320x250, sem posição): escala
                    # para o espaço virtual e mantém o layout à direita.
                    s = min(VW / 320.0, VH / 250.0)
                    novo_w = _clamp_v(int(prefe_w * s), MINV_V, area_wv)
                    novo_h = _clamp_v(int(prefe_h * s), MINV_V, area_hv)
                    novo_x = VW - margem_hv - novo_w
                    novo_y = (VH - novo_h) // 2
                else:
                    novo_w = min(int(area_wv * 0.5), int(area_hv * aspect))
                    novo_h = max(MINV_V, int(novo_w / aspect))
                    if novo_h > area_hv:
                        novo_h = int(area_hv)
                        novo_w = max(MINV_V, int(novo_h * aspect))
                    novo_w = max(MINV_V, novo_w)
                    novo_x = VW - margem_hv - novo_w
                    novo_y = (VH - novo_h) // 2

                pos = {"x": novo_x, "y": novo_y, "w": novo_w, "h": novo_h}
                tam = pos
                tam_img.update({"w": novo_w, "h": novo_h, "x": novo_x, "y": novo_y})

                PREVIEW_OK = [True]
                _photo_atual = [None]
                try:
                    from PIL import Image, ImageTk
                except Exception:
                    PREVIEW_OK[0] = False

                def _gerar_foto(w, h):
                    if not PREVIEW_OK[0]:
                        return None
                    try:
                        from PIL import Image, ImageTk
                        with Image.open(caminho) as im:
                            orig = im.convert("RGBA")
                        redim = getattr(Image, "LANCZOS", None) or getattr(Image, "BICUBIC", None)
                        pw, ph = max(1, int(w * ESCALA)), max(1, int(h * ESCALA))
                        foto = ImageTk.PhotoImage(orig.resize((pw, ph), redim), master=canvas)
                        _photo_atual[0] = foto
                        return foto
                    except Exception:
                        return None

                itens = {}

                # Caixa de texto padrão quando o anúncio ainda não salvou uma
                # (layout lado a lado, com a mesma largura/dimensão da projeção).
                if tam_txt.get("w") is None:
                    caixa = _caixa_texto_padrao(
                        texto_salvo.get("t") or "", area_wv, area_hv,
                        margem_hv, margem_vv, aspect_imagem=aspect)
                    tam_txt.update({"w": caixa["w"], "h": caixa["h"],
                                     "x": caixa["x"], "y": caixa["y"],
                                     "s": float(caixa.get("s") or 1.0)})

                def _limpar_canvas():
                    for valor in list(itens.values()):
                        lista = valor if isinstance(valor, (list, tuple)) else (valor,)
                        for it in lista:
                            try:
                                canvas.delete(it)
                            except tk.TclError:
                                pass
                    itens.clear()

                def _desenhar_alcas(x, y, w, h, prefixo, cor):
                    s = 10
                    posicoes = {
                        "nw": (x, y), "n": (x + w // 2, y), "ne": (x + w, y),
                        "w": (x, y + h // 2), "e": (x + w, y + h // 2),
                        "sw": (x, y + h), "s": (x + w // 2, y + h),
                        "se": (x + w, y + h),
                    }
                    for nome, (px, py) in posicoes.items():
                        itens[prefixo + "_" + nome] = canvas.create_rectangle(
                            px - s // 2, py - s // 2, px + s // 2, py + s // 2,
                            fill=cor, outline='white')

                def _alca_em(px, py, prefixo):
                    for nome in ("nw", "n", "ne", "w", "e", "sw", "s", "se"):
                        it_id = itens.get(prefixo + "_" + nome)
                        if it_id is None:
                            continue
                        try:
                            bx1, by1, bx2, by2 = canvas.coords(it_id)
                        except tk.TclError:
                            continue
                        if bx1 <= px <= bx2 and by1 <= py <= by2:
                            return nome
                    return None

                def _renderizar_texto_caixa():
                    """Desenha a caixa de texto (contorno + alças + conteúdo).

                    A caixa é SEMPRE desenhada (mesmo com texto vazio) para que
                    o usuário possa arrastá-la pelo centro e redimensioná-la.
                    O preenchimento translúcido deixa o "meio" da caixa visível
                    e arrastável, exatamente como o meio da imagem.
                    """
                    for chave in list(itens):
                        if chave.startswith("t_"):
                            try:
                                canvas.delete(itens[chave])
                            except tk.TclError:
                                pass
                            del itens[chave]

                    tx = tam_txt.get("x") or 0
                    ty = tam_txt.get("y") or 0
                    tw = max(60, int(tam_txt.get("w") or 60))
                    th = max(60, int(tam_txt.get("h") or 60))
                    px, py = int(tx * ESCALA), int(ty * ESCALA)
                    pw, ph = max(1, int(tw * ESCALA)), max(1, int(th * ESCALA))
                    # Preenchimento translúcido que torna a região arrastável.
                    itens["t_fill"] = canvas.create_rectangle(
                        px, py, px + pw, py + ph, fill='#5c4304', outline='')
                    itens["t_box"] = canvas.create_rectangle(
                        px, py, px + pw, py + ph, outline='#f0c040',
                        dash=(4, 3), width=2)

                    ww = widget_texto.get("w")
                    txt = ww.get('1.0', tk.END).strip() if ww else (
                        str(texto_salvo.get("t") or ""))
                    if not txt:
                        return
                    escala = float(tam_txt.get("s") or 1.0)
                    fonte_pil, linhas = _calcular_texto_em_caixa(
                        txt, tw, th, base_pct=0.10 * escala)
                    familia = _fonte_familia_do_pil(fonte_pil)
                    passo = fonte_pil.size + max(1, fonte_pil.size // 5)
                    cx = px + pw // 2
                    cy_txt = py + ph // 2 - (passo * len(linhas) * ESCALA) // 2
                    for i, ln in enumerate(linhas):
                        if ln:
                            itens["t_txt_" + str(i)] = canvas.create_text(
                                cx, cy_txt + i * passo * ESCALA, text=ln,
                                anchor='n', width=pw, fill='#c9d1d9',
                                font=(familia, max(
                                    8, int(fonte_pil.size * ESCALA)), 'bold'))
                    # Alças do texto por cima do conteúdo.
                    _desenhar_alcas(px, py, pw, ph, "t_", '#e3b341')

                def _redesenhar(final=False):
                    _limpar_canvas()
                    w, h = tam["w"], tam["h"]
                    x, y = pos["x"], pos["y"]
                    tam_img["x"] = int(x)
                    tam_img["y"] = int(y)
                    tam_img["w"] = int(w)
                    tam_img["h"] = int(h)
                    # 1) texto em caixa ajustável (posição/tamanho próprios)
                    _renderizar_texto_caixa()
                    # 2) imagem, na posição ajustada
                    px, py = int(x * ESCALA), int(y * ESCALA)
                    pw, ph = max(1, int(w * ESCALA)), max(1, int(h * ESCALA))
                    itens["fundo"] = canvas.create_rectangle(
                        px, py, px + pw, py + ph, fill='#0d1117',
                        outline=('#58a6ff' if not final else '#3fb950'),
                        width=2 if final else 1)
                    foto = _gerar_foto(w, h) if final else None
                    if foto is not None:
                        itens["foto"] = canvas.create_image(px, py, image=foto, anchor="nw")
                    else:
                        itens["placeholder"] = canvas.create_text(
                            px + pw // 2, py + ph // 2,
                            text="", fill='#8b949e', font=("Arial", 12))
                    # 3) alças da imagem por cima de tudo
                    _desenhar_alcas(px, py, pw, ph, "h_", '#58a6ff')

                _estado = {"modo": None, "alvo": None, "alca": None,
                           "press_px": (0, 0), "ix": 0, "iy": 0, "iw": 0, "ih": 0}
                _estado_final = [True]

                def _em_retangulo_img(px, py):
                    vx = px / ESCALA
                    vy = py / ESCALA
                    return (pos["x"] <= vx <= pos["x"] + tam["w"]
                            and pos["y"] <= vy <= pos["y"] + tam["h"])

                def _em_retangulo_txt(px, py):
                    vx = px / ESCALA
                    vy = py / ESCALA
                    tx = int(tam_txt.get("x") or 0)
                    ty = int(tam_txt.get("y") or 0)
                    tw = max(60, int(tam_txt.get("w") or 60))
                    th = max(60, int(tam_txt.get("h") or 60))
                    return (tx <= vx <= tx + tw and ty <= vy <= ty + th)

                def _on_press(e):
                    _estado.update({"modo": None, "alvo": None, "alca": None})
                    alca_i = _alca_em(e.x, e.y, "h_")
                    if alca_i:
                        _estado.update({"modo": "resize", "alvo": "img",
                                        "alca": alca_i, "press_px": (e.x, e.y),
                                        "ix": pos["x"], "iy": pos["y"],
                                        "iw": tam["w"], "ih": tam["h"]})
                        return
                    if _em_retangulo_img(e.x, e.y):
                        _estado.update({"modo": "move", "alvo": "img",
                                        "alca": None, "press_px": (e.x, e.y),
                                        "ix": pos["x"], "iy": pos["y"],
                                        "iw": tam["w"], "ih": tam["h"]})
                        return
                    alca_t = _alca_em(e.x, e.y, "t_")
                    if alca_t:
                        _estado.update({"modo": "resize", "alvo": "txt",
                                        "alca": alca_t, "press_px": (e.x, e.y),
                                        "ix": tam_txt["x"], "iy": tam_txt["y"],
                                        "iw": tam_txt["w"], "ih": tam_txt["h"]})
                        return
                    if _em_retangulo_txt(e.x, e.y):
                        _estado.update({"modo": "move", "alvo": "txt",
                                        "alca": None, "press_px": (e.x, e.y),
                                        "ix": tam_txt["x"], "iy": tam_txt["y"],
                                        "iw": tam_txt["w"], "ih": tam_txt["h"]})
                        return

                def _mover_reg(vals, dx, dy, lw, lh):
                    vals["x"] = _clamp_v(_estado["ix"] + dx, LIN_V,
                                         max(LIN_V, VW - LIN_V - _estado["iw"]))
                    vals["y"] = _clamp_v(_estado["iy"] + dy, LIN_V,
                                         max(LIN_V, VH - LIN_V - _estado["ih"]))
                    if lw is not None and lw.get("w"):
                        lw["x"] = int(vals["x"])
                        lw["y"] = int(vals["y"])
                        lw["w"] = int(_estado["iw"])
                        lw["h"] = int(_estado["ih"])

                def _redimensionar_alca(vals, e, final):
                    alca = _estado["alca"]
                    dx = (e.x - _estado["press_px"][0]) / ESCALA
                    dy = (e.y - _estado["press_px"][1]) / ESCALA
                    esq = alca in ("nw", "w", "sw")
                    top = alca in ("nw", "n", "ne")
                    dir_ = alca in ("ne", "e", "se")
                    bot = alca in ("sw", "s", "se")
                    w_lim = ((VW - LIN_V) - _estado["ix"]) if dir_ \
                        else ((_estado["ix"] + _estado["iw"]) - LIN_V)
                    h_lim = ((VH - LIN_V) - _estado["iy"]) if bot \
                        else ((_estado["iy"] + _estado["ih"]) - LIN_V)
                    eh_imagem = _estado.get("alvo") == "img"
                    if alca in ("n", "s"):
                        novo_h = _clamp_v(_estado["ih"] + (dy if bot else -dy),
                                          MINV_V, h_lim)
                        if top:
                            vals["y"] = _estado["iy"] + (_estado["ih"] - novo_h)
                        vals["h"] = novo_h
                    elif alca in ("w", "e"):
                        novo_w = _clamp_v(_estado["iw"] + (dx if dir_ else -dx),
                                          MINV_V, w_lim)
                        if esq:
                            vals["x"] = _estado["ix"] + (_estado["iw"] - novo_w)
                        vals["w"] = novo_w
                    else:
                        # Cantos: preserva a proporção atual do elemento
                        # (imagem ou caixa de texto) — comportamento idêntico
                        # para os dois.
                        rap = _estado["ih"] / max(1, _estado["iw"])
                        delta = dx if abs(dx) >= abs(dy) else dy
                        novo_w = _clamp_v(_estado["iw"] + (delta if dir_ else -delta),
                                          MINV_V, w_lim)
                        novo_h = int(novo_w * rap)
                        if novo_h > h_lim:
                            novo_h = int(h_lim)
                            novo_w = _clamp_v(int(novo_h / rap), MINV_V, w_lim)
                            novo_h = int(novo_w * rap)
                        if novo_h < MINV_V:
                            novo_h = MINV_V
                            novo_w = _clamp_v(int(novo_h / rap), MINV_V, w_lim)
                        if esq:
                            vals["x"] = _estado["ix"] + (_estado["iw"] - novo_w)
                        if top:
                            vals["y"] = _estado["iy"] + (_estado["ih"] - novo_h)
                        vals["w"], vals["h"] = novo_w, novo_h
                    if final:
                        if vals is pos:
                            tam_img.update({"w": int(vals["w"]), "h": int(vals["h"]),
                                             "x": int(vals["x"]), "y": int(vals["y"])})
                        else:
                            tam_txt.update({"w": int(vals["w"]), "h": int(vals["h"]),
                                             "x": int(vals["x"]), "y": int(vals["y"])})

                def _on_motion(e):
                    if not _estado["modo"]:
                        return
                    if _estado["alvo"] == "img":
                        vals, lw = pos, tam_img
                    else:
                        vals, lw = tam_txt, tam_txt
                    if _estado["modo"] == "move":
                        dx = (e.x - _estado["press_px"][0]) / ESCALA
                        dy = (e.y - _estado["press_px"][1]) / ESCALA
                        _mover_reg(vals, dx, dy, lw, None)
                        _redesenhar(final=True)
                        return
                    _redimensionar_alca(vals, e, final=False)
                    _redesenhar(final=False)

                def _on_release(e):
                    if _estado["modo"]:
                        if _estado.get("alvo") == "txt" and _estado["modo"] == "resize":
                            _redimensionar_alca(tam_txt, e, final=True)
                        elif _estado.get("alvo") == "img" and _estado["modo"] == "resize":
                            _redimensionar_alca(pos, e, final=True)
                        elif _estado.get("modo") == "move":
                            if _estado.get("alvo") == "txt":
                                tam_txt.update({"x": int(tam_txt["x"]),
                                                 "y": int(tam_txt["y"])})
                            else:
                                tam_img.update({"x": int(pos["x"]),
                                                 "y": int(pos["y"])})
                        _estado["modo"] = None
                        _estado["alvo"] = None
                        _estado["alca"] = None
                        # Re-aplica alças sob a prévia final
                        _redesenhar(final=True)

                def _ao_digitar(e):
                    if _estado["modo"] is None:
                        _redesenhar(final=_estado_final[0])

                canvas.bind("<ButtonPress-1>", _on_press)
                canvas.bind("<B1-Motion>", _on_motion)
                canvas.bind("<ButtonRelease-1>", _on_release)
                texto_widget.bind("<KeyRelease>", _ao_digitar)

                _redesenhar(final=True)
                tk.Label(painel,
                         text="A prévia mostra tudo como será projetado (texto + imagem "
                              "no mesmo quadro).\n"
                              "IMAGEM: arraste no meio para mover, puxe as alças "
                              "(laterais/cantos) para redimensionar.\n"
                              "TEXTO: a caixa amarela funciona igual — arraste no meio "
                              "para mover, puxe as alças para redimensionar.",
                         bg='#0d1117', fg='#8b949e', justify='left',
                         font=("Arial", 9)).pack(fill='x', pady=(6, 0))

            def _montar_editor_slides(container) -> None:
                """Editor de MÚLTIPLOS slides.

                Cada slide é um texto (com imagem opcional); o operador adiciona
                quantos quiser (botão ➕), remove (➖), atribui imagem por slide
                (🖼️) e edita o conteúdo do slide selecionado no campo abaixo.
                Na gravação, os textos vão separados por linha em branco
                (parágrafo) e, havendo imagens, o JSON {"mslides": [...]} em
                config_midia.
                """
                _slides_estado["modo"] = True
                if not _slides_estado["lista"]:
                    _slides_estado["lista"] = [
                        {"texto": "", "imagem": "", "nome": "", "config": ""}]
                if not (0 <= _slides_estado["idx"] < len(_slides_estado["lista"])):
                    _slides_estado["idx"] = 0

                info = tk.Label(
                    container,
                    text="Adicione quantos slides quiser (texto e, se quiser, "
                         "uma imagem por slide — botão 🖼️):",
                    font=("Arial", 10, "bold"), fg='#f0c040',
                    bg='#0d1117', anchor='w')
                info.pack(fill='x', pady=(0, 4))

                barra = tk.Frame(container, bg='#0d1117')
                barra.pack(fill='x', pady=2)
                tk.Button(barra, text="➕ Adicionar slide",
                          font=("Arial", 10, "bold"),
                          bg='#1f6feb', fg='white', activebackground='#388bfd',
                          command=lambda: _adicionar_slide(), cursor='hand2',
                          padx=10, pady=2).pack(side='left')
                tk.Button(barra, text="➖ Remover slide",
                          font=("Arial", 10, "bold"),
                          bg='#f85149', fg='white', activebackground='#da3633',
                          command=lambda: _remover_slide(), cursor='hand2',
                          padx=10, pady=2).pack(side='left', padx=6)
                tk.Button(barra, text="🖼️ Imagem do slide",
                          font=("Arial", 10, "bold"),
                          bg='#6e40c9', fg='white', activebackground='#8957e5',
                          command=lambda: _escolher_imagem_slide(),
                          cursor='hand2', padx=10, pady=2).pack(side='left')
                tk.Button(barra, text="🗑️ Sem imagem",
                          font=("Arial", 10, "bold"),
                          bg='#30363d', fg='#c9d1d9',
                          activebackground='#484f58',
                          command=lambda: _remover_imagem_slide(),
                          cursor='hand2', padx=10, pady=2).pack(side='left', padx=6)
                contador = tk.Label(barra, text="slide 1 de 1",
                                    font=("Arial", 10),
                                    fg='#8b949e', bg='#0d1117')
                contador.pack(side='right')

                coluna = tk.Frame(container, bg='#0d1117')
                coluna.pack(fill='both', expand=True, pady=2)

                lista_box = tk.Listbox(
                    coluna, height=4, font=("Arial", 10), bg='#21262d',
                    fg='#c9d1d9', selectbackground='#1f6feb',
                    selectforeground='white', activestyle='none')
                lista_box.pack(fill='x', side='top', pady=(0, 2))
                barra_lista = tk.Scrollbar(coluna, orient='vertical',
                                           command=lista_box.yview)
                lista_box.configure(yscrollcommand=barra_lista.set)

                w_texto = tk.Text(coluna, font=("Arial", 11),
                                  bg='#21262d', fg='#c9d1d9',
                                  insertbackground='#f0c040',
                                  wrap='word', height=8)
                _slides_estado["w"] = w_texto
                w_texto.pack(side='bottom', fill='both', expand=True)

                previa = tk.Label(coluna, text="🖼 Sem imagem neste slide",
                                  font=("Arial", 9), fg='#8b949e', bg='#161b22',
                                  height=4, anchor='center')
                previa.pack(fill='x', side='top', pady=(0, 4))

                def _atualizar_previa():
                    """Mostra a imagem do slide selecionado (miniatura)."""
                    idx = _slides_estado["idx"]
                    lista = _slides_estado["lista"]
                    caminho = ''
                    if 0 <= idx < len(lista):
                        caminho = (lista[idx].get("imagem") or '')
                    if caminho and os.path.isfile(caminho):
                        try:
                            from PIL import Image, ImageTk
                            with Image.open(caminho) as im:
                                im = im.convert("RGBA")
                                metodo = (
                                    getattr(Image, "LANCZOS", None)
                                    or getattr(Image, "BICUBIC", None)
                                    or getattr(Image, "ANTIALIAS", None))
                                im.thumbnail((max(80, coluna.winfo_width() - 12), 150),
                                             metodo)
                                foto = ImageTk.PhotoImage(im, master=editar_win)
                            previa.config(text='', image=foto, bg='#161b22',
                                          height=0)
                            previa.imagem = foto
                        except Exception as e:
                            print(f"⚠️ Não foi possível mostrar a miniatura: {e}")
                            previa.config(text="⚠️ Não foi possível exibir a imagem",
                                          image='', bg='#0d1117', height=2)
                    else:
                        previa.config(text="🖼 Sem imagem neste slide", image='',
                                      bg='#161b22', height=4)

                def _atualizar_contador():
                    total = len(_slides_estado["lista"])
                    atual = total if _slides_estado["idx"] >= total else _slides_estado["idx"] + 1
                    contador.config(text=f"slide {max(atual, 1)} de {total}")

                def _atualizar_lista():
                    lista_box.delete(0, tk.END)
                    for i, t in enumerate(_slides_estado["lista"]):
                        rotulo = (t.get("texto") or '').strip().split('\n')[0] or f"(slide {i + 1})"
                        if len(rotulo) > 36:
                            rotulo = rotulo[:36] + "…"
                        marcador = "🖼" if t.get("imagem") else "·"
                        lista_box.insert(tk.END, f"{i + 1}. {marcador} {rotulo}")

                def _commit_slide():
                    """Grava o conteúdo do campo no slide atualmente selecionado."""
                    lista = _slides_estado["lista"]
                    idx = _slides_estado["idx"]
                    if 0 <= idx < len(lista):
                        lista[idx]["texto"] = w_texto.get('1.0', tk.END).strip()

                def _carregar_slide():
                    idx = _slides_estado["idx"]
                    lista = _slides_estado["lista"]
                    w_texto.delete('1.0', tk.END)
                    if 0 <= idx < len(lista):
                        w_texto.insert('1.0', lista[idx]["texto"])
                    if idx < lista_box.size():
                        lista_box.selection_clear(0, tk.END)
                        lista_box.selection_set(idx)
                        lista_box.see(idx)
                    _atualizar_contador()
                    _atualizar_previa()

                def _escolher_slide(event=None):
                    _commit_slide()
                    sel = lista_box.curselection()
                    if sel:
                        _slides_estado["idx"] = int(sel[0])
                    _carregar_slide()

                def _adicionar_slide():
                    _commit_slide()
                    _slides_estado["lista"].append(
                        {"texto": "", "imagem": "", "nome": "", "config": ""})
                    _slides_estado["idx"] = len(_slides_estado["lista"]) - 1
                    _atualizar_lista()
                    _carregar_slide()
                    w_texto.focus_set()

                def _remover_slide():
                    _commit_slide()
                    lista = _slides_estado["lista"]
                    if len(lista) <= 1:
                        tkinter.messagebox.showinfo(
                            "Dica", "É necessário manter pelo menos um slide.",
                            parent=editar_win)
                        return
                    idx = min(_slides_estado["idx"], len(lista) - 1)
                    lista.pop(idx)
                    _slides_estado["idx"] = max(0, idx - 1)
                    _atualizar_lista()
                    _carregar_slide()

                def _escolher_imagem_slide():
                    """Associa uma imagem ao slide atualmente selecionado."""
                    _commit_slide()
                    idx = _slides_estado["idx"]
                    lista = _slides_estado["lista"]
                    if not (0 <= idx < len(lista)):
                        return
                    try:
                        selecionados = _escolher_arquivos_usuario(
                            parent=editar_win, titulo="Escolher imagem do slide",
                            sufixos=tuple(sorted(SUFIXOS_IMAGEM)))
                    except Exception:
                        selecionados = ()
                    if not selecionados:
                        return
                    caminho = selecionados[0]
                    if not os.path.normcase(os.path.abspath(caminho)).startswith(
                            os.path.normcase(os.path.abspath(UPLOAD_FOLDER))):
                        copiado = _copiar_arquivo_uploads(caminho)
                        if copiado is None:
                            tkinter.messagebox.showwarning(
                                "⚠️", "Não foi possível copiar a imagem para uploads.",
                                parent=editar_win)
                            return
                        caminho = copiado
                    lista[idx]["imagem"] = caminho
                    lista[idx]["nome"] = os.path.basename(caminho)
                    _atualizar_lista()
                    _carregar_slide()

                def _remover_imagem_slide():
                    """Remove a imagem do slide atualmente selecionado."""
                    _commit_slide()
                    idx = _slides_estado["idx"]
                    lista = _slides_estado["lista"]
                    if not (0 <= idx < len(lista)) or not lista[idx].get("imagem"):
                        return
                    lista[idx]["imagem"] = ""
                    lista[idx]["nome"] = ""
                    _atualizar_lista()
                    _carregar_slide()

                def _abrir_previa_slide(idx):
                    """Abre a prévia interativa (imagem + texto) de um slide."""
                    lista = _slides_estado["lista"]
                    if not (0 <= idx < len(lista)):
                        return
                    _commit_slide()
                    slide = lista[idx]
                    caminho = (slide.get("imagem") or '').strip()
                    if not os.path.isfile(caminho):
                        tkinter.messagebox.showinfo(
                            "Prévia",
                            "Este slide não tem imagem para posicionar.\n"
                            "Associe uma imagem com o botão 🖼️ Imagem deste slide.",
                            parent=editar_win)
                        return

                    tam_img = {"w": None, "h": None, "x": None, "y": None,
                               "orig": None}
                    tam_txt = {"w": None, "h": None, "x": None, "y": None,
                               "s": 1.0}
                    txt_salvo = {"t": (slide.get("texto") or '').strip()}
                    try:
                        cfg_s = json.loads(slide.get("config") or '{}')
                        if isinstance(cfg_s, dict) and cfg_s.get("w"):
                            tam_img.update(w=int(cfg_s["w"]),
                                           h=int(cfg_s.get("h") or 0),
                                           x=int(cfg_s.get("x") or 0),
                                           y=int(cfg_s.get("y") or 0))
                            if int(cfg_s.get("tw") or 0) > 0 \
                                    and int(cfg_s.get("th") or 0) > 0:
                                tam_txt.update(
                                    w=int(cfg_s["tw"]), h=int(cfg_s["th"]),
                                    x=int(cfg_s.get("tx") or 0),
                                    y=int(cfg_s.get("ty") or 0),
                                    s=float(cfg_s.get("ts") or 1.0))
                    except (ValueError, TypeError, AttributeError):
                        pass

                    prev_win = tk.Toplevel(editar_win)
                    prev_win.title(f"Posicionar imagem e texto — slide {idx + 1}")
                    prev_win.geometry("700x760")
                    prev_win.configure(bg='#0d1117')
                    prev_win.transient(editar_win)

                    def _salvar_previa():
                        slide["texto"] = \
                            w_texto_previa.get('1.0', tk.END).strip()
                        slide["config"] = json.dumps({
                            "w": int(tam_img.get("w") or 0),
                            "h": int(tam_img.get("h") or 0),
                            "x": int(tam_img.get("x") or 0),
                            "y": int(tam_img.get("y") or 0),
                            "tx": int(tam_txt.get("x") or 0),
                            "ty": int(tam_txt.get("y") or 0),
                            "tw": int(tam_txt.get("w") or 0),
                            "th": int(tam_txt.get("h") or 0),
                            "ts": float(tam_txt.get("s") or 1.0),
                        }, separators=(',', ':'))
                        _atualizar_lista()
                        if _slides_estado["idx"] == idx:
                            _carregar_slide()
                        prev_win.destroy()

                    def _fechar_previa(event=None):
                        prev_win.destroy()

                    barra = tk.Frame(prev_win, bg='#0d1117')
                    barra.pack(fill='x', side='bottom', pady=8)
                    tk.Button(barra, text="💾 Salvar posição deste slide",
                              font=("Arial", 11, "bold"), bg='#238636',
                              fg='white', activebackground='#2ea043',
                              command=_salvar_previa, cursor='hand2',
                              padx=18, pady=4).pack(side='left', padx=(12, 6))
                    tk.Button(barra, text="✖ Fechar", font=("Arial", 11),
                              bg='#30363d', fg='#f0f6fc',
                              activebackground='#484f58',
                              command=_fechar_previa, cursor='hand2',
                              padx=12, pady=4).pack(side='left')
                    tk.Label(barra, text="", bg='#0d1117')\
                        .pack(side='left', expand=True)

                    w_texto_previa = tk.Text(prev_win, font=("Arial", 11),
                                             bg='#21262d', fg='#c9d1d9',
                                             insertbackground='#f0c040',
                                             wrap='word', height=8)
                    _montar_painel_imagem(prev_win, w_texto_previa,
                                          caminho, tam_img, tam_txt,
                                          txt_salvo, {"w": None})
                    w_texto_previa.delete('1.0', tk.END)
                    w_texto_previa.insert('1.0', txt_salvo["t"])
                    prev_win.after(60, prev_win.grab_set)
                    prev_win.bind('<Escape>', _fechar_previa)

                def _previa_duplo_clique(event=None):
                    sel = lista_box.curselection()
                    if not sel:
                        return
                    idx = int(sel[0])
                    if idx != _slides_estado["idx"]:
                        _slides_estado["idx"] = idx
                        _carregar_slide()
                    _abrir_previa_slide(idx)

                w_texto.bind('<KeyRelease>', lambda e: _commit_slide())
                lista_box.bind('<<ListboxSelect>>', _escolher_slide)
                lista_box.bind('<Double-Button-1>', _previa_duplo_clique)
                lista_box.bind('<Delete>', lambda e: _remover_slide())
                lista_box.bind('<Up>', _carregar_slide)
                lista_box.bind('<Down>', _carregar_slide)
                _atualizar_lista()
                _carregar_slide()

            def _montar_area_conteudo() -> None:
                """Constrói a área de conteúdo conforme o tipo selecionado.

                - 'imagem' com arquivo: prévia única com o texto do anúncio
                  E a imagem no mesmo canvas (sobre o texto), posicionáveis
                  de forma idêntica à projeção.
                - 'slide': editor de MÚLTIPLOS slides (uma tela por parágrafo).
                - demais: campo de texto em largura total (como antes).
                """
                for w in area_conteudo.winfo_children():
                    w.destroy()
                _widget_texto["w"] = None
                _slides_estado["modo"] = False
                _slides_estado["w"] = None

                tipo = _tipo_interno()
                caminho = arquivo_var.get().strip()

                if tipo == "slide":
                    _montar_editor_slides(area_conteudo)
                    return

                eh_imagem = (tipo == "imagem" and caminho
                             and os.path.isfile(caminho)
                             and os.path.splitext(caminho)[1].lower() in SUFIXOS_IMAGEM)

                texto_atual = tk.Text(area_conteudo, font=("Arial", 11),
                                      bg='#21262d', fg='#c9d1d9',
                                      insertbackground='#f0c040',
                                      wrap='word', height=8)
                if _texto_salvo["t"]:
                    texto_atual.insert('1.0', _texto_salvo["t"])

                if tipo == "imagem":
                    if eh_imagem:
                        _montar_painel_imagem(area_conteudo, texto_atual, caminho)
                    else:
                        texto_atual.pack(fill='both', expand=True, pady=2)
                        _widget_texto["w"] = texto_atual
                        if caminho:
                            tk.Label(area_conteudo,
                                     text="Arquivo selecionado não é uma imagem.",
                                     fg='#f85149', bg='#0d1117',
                                     font=("Arial", 10)).pack(anchor='w')
                    return

                texto_atual.pack(fill='both', expand=True, pady=2)
                _widget_texto["w"] = texto_atual

            tipo_combo.bind("<<ComboboxSelected>>",
                            lambda e: (_ler_texto(), _montar_area_conteudo()))
            _montar_area_conteudo()

            if dados_anuncio:
                campos['titulo'].insert(0, dados_anuncio.get('titulo', ''))
                campos['categoria'].insert(0, dados_anuncio.get('categoria', ''))
            _atualizar_arquivo_label()

            def _salvar():
                titulo = campos['titulo'].get().strip()
                if not titulo:
                    tkinter.messagebox.showwarning("Erro", "Título é obrigatório.",
                                                   parent=editar_win)
                    return
                categoria = campos['categoria'].get().strip()
                texto = _ler_texto()
                tipo = _tipo_interno()
                nome_arquivo = ""
                arquivo = arquivo_var.get().strip()

                if tipo != "slide":
                    if not arquivo or not os.path.exists(arquivo):
                        tkinter.messagebox.showwarning(
                            "Erro", f"Selecione o arquivo de {rotulos_tipo[tipo].lower()}.",
                            parent=editar_win)
                        return
                    if not os.path.normcase(os.path.abspath(arquivo)).startswith(
                            os.path.normcase(os.path.abspath(UPLOAD_FOLDER))):
                        copiado = _copiar_arquivo_uploads(arquivo)
                        if copiado is None:
                            tkinter.messagebox.showwarning(
                                "⚠️", "Não foi possível copiar o arquivo para uploads.",
                                parent=editar_win)
                            return
                        arquivo = copiado
                    nome_arquivo = os.path.basename(arquivo)

                config_midia = ""
                if _slides_estado["modo"]:
                    # Anúncio de slides: se algum slide tem imagem, guarda o
                    # JSON {"mslides": [...]} para a projeção reutilizar.
                    lista_final = _slides_estado["lista"]
                    tem_imagem = any(
                        (s or {}).get("imagem") for s in lista_final)
                    if tem_imagem:
                        mslides = []
                        for s in lista_final:
                            s = s or {}
                            mslides.append({
                                "texto": (s.get("texto") or '').strip(),
                                "imagem": (s.get("imagem") or ''),
                                "nome": (s.get("nome") or ''),
                                "config": (s.get("config") or ''),
                            })
                        config_midia = json.dumps({"mslides": mslides})
                elif tipo == "imagem" and _tam_img.get("w"):
                    cfg_final = {
                        "w": int(_tam_img["w"]),
                        "h": int(_tam_img.get("h") or 0),
                        "x": int(_tam_img.get("x") or 0),
                        "y": int(_tam_img.get("y") or 0)}
                    tw = int(_tam_txt.get("w") or 0)
                    th = int(_tam_txt.get("h") or 0)
                    if tw > 0 and th > 0:
                        cfg_final.update({
                            "tx": int(_tam_txt.get("x") or 0),
                            "ty": int(_tam_txt.get("y") or 0),
                            "tw": tw,
                            "th": th,
                            "ts": float(_tam_txt.get("s") or 1.0)})
                    config_midia = json.dumps(cfg_final)

                dados_finais = {
                    "titulo": titulo,
                    "categoria": categoria,
                    "texto": texto,
                    "tipo_midia": tipo,
                    "arquivo_midia": arquivo,
                    "nome_arquivo_midia": nome_arquivo,
                    "config_midia": config_midia,
                }
                if anuncio_id:
                    if not _atualizar_anuncio_db(anuncio_id, dados_finais):
                        tkinter.messagebox.showwarning(
                            "⚠️", "Não foi possível gravar no banco.", parent=editar_win)
                        return
                else:
                    if _inserir_anuncio_db(dados_finais) is None:
                        tkinter.messagebox.showwarning(
                            "⚠️", "Não foi possível gravar no banco.", parent=editar_win)
                        return
                _carregar_anuncios()
                editar_win.destroy()

            tk.Button(e_main, text="💾 Salvar", font=("Arial", 12, "bold"),
                      bg='#238636', fg='white', activebackground='#2ea043',
                      command=_salvar, cursor='hand2', padx=20, pady=5
                      ).pack(pady=10)

        _migrar_anuncios_do_json()
        _carregar_anuncios()

    # ────────────────────────────────────────────────────────────────────
    # JANELA DE BÍBLIA
    # ────────────────────────────────────────────────────────────────────

    # Lista de livros da Bíblia (ordem canônica)
    LIVROS_BIBLIA = [
        "Gênesis", "Êxodo", "Levítico", "Números", "Deuteronômio",
        "Josué", "Juízes", "Rute", "1 Samuel", "2 Samuel",
        "1 Reis", "2 Reis", "1 Crônicas", "2 Crônicas", "Esdras",
        "Neemias", "Ester", "Jó", "Salmos", "Provérbios",
        "Eclesiastes", "Cânticos", "Isaías", "Jeremias", "Lamentações",
        "Ezequiel", "Daniel", "Oséias", "Joel", "Amós",
        "Obadias", "Jonas", "Miquéias", "Naum", "Habacuque",
        "Sofonias", "Ageu", "Zacarias", "Malaquias",
        "Mateus", "Marcos", "Lucas", "João", "Atos",
        "Romanos", "1 Coríntios", "2 Coríntios", "Gálatas", "Efésios",
        "Filipenses", "Colossenses", "1 Tessalonicenses", "2 Tessalonicenses",
        "1 Timóteo", "2 Timóteo", "Tito", "Filemom", "Hebreus",
        "Tiago", "1 Pedro", "2 Pedro", "1 João", "2 João",
        "3 João", "Judas", "Apocalipse"
    ]

    def janela_biblia(self) -> None:
        """Abre a janela de busca bíblica."""
        janela = tk.Toplevel(self.root)
        janela.title("✝️ Bíblia")
        janela.geometry("950x700")
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        janela.after(50, janela.grab_set)

        main = tk.Frame(janela, bg='#0d1117')
        main.pack(fill='both', expand=True, padx=15, pady=15)

        tk.Label(main, text="✝️ Busca Bíblica",
                 font=("Arial", 16, "bold"), fg='#f0c040', bg='#0d1117'
                 ).pack(pady=(0, 10))

        # ── Referência rápida ──
        ref_frame = tk.Frame(main, bg='#161b22')
        ref_frame.pack(fill='x', pady=5, ipady=5)

        tk.Label(ref_frame, text="📖", fg='#f0c040', bg='#161b22',
                 font=("Arial", 14)).pack(side='left', padx=(8, 5))

        # Combo de versão
        versoes_disponiveis = []
        rows_v = db_query("SELECT DISTINCT versao FROM versiculos ORDER BY versao")
        if rows_v:
            versoes_disponiveis = [r['versao'] for r in rows_v]
        if not versoes_disponiveis:
            versoes_disponiveis = ["Almeida Revista e Corrigida", "Almeida Século 21"]
        versao_padrao = ("Almeida Revista e Corrigida"
                         if "Almeida Revista e Corrigida" in versoes_disponiveis
                         else versoes_disponiveis[0])
        versao_var = tk.StringVar(value=versao_padrao)
        combo_versao = ttk.Combobox(ref_frame, textvariable=versao_var,
                                     values=versoes_disponiveis, width=8,
                                     font=("Arial", 11))
        combo_versao.pack(side='left', padx=5)

        # Combo de livro
        livro_var = tk.StringVar(value="João")
        combo_livro = ttk.Combobox(ref_frame, textvariable=livro_var,
                                    values=self.LIVROS_BIBLIA, width=18,
                                    font=("Arial", 11))
        combo_livro.pack(side='left', padx=5)

        # Capítulo
        tk.Label(ref_frame, text="Cap:", fg='#c9d1d9', bg='#161b22',
                 font=("Arial", 10)).pack(side='left', padx=(5, 2))
        cap_var = tk.StringVar(value="3")
        entry_cap = tk.Entry(ref_frame, textvariable=cap_var, width=4,
                             font=("Arial", 11), bg='#21262d', fg='#f0c040',
                             insertbackground='#f0c040', bd=0, highlightthickness=0)
        entry_cap.pack(side='left', padx=2, ipady=2)

        # Versículo (opcional, vazio = capítulo inteiro)
        tk.Label(ref_frame, text="V:", fg='#c9d1d9', bg='#161b22',
                 font=("Arial", 10)).pack(side='left', padx=(5, 2))
        vers_var = tk.StringVar(value="16")
        entry_vers = tk.Entry(ref_frame, textvariable=vers_var, width=4,
                              font=("Arial", 11), bg='#21262d', fg='#f0c040',
                              insertbackground='#f0c040', bd=0, highlightthickness=0)
        entry_vers.pack(side='left', padx=2, ipady=2)

        # ── Área de texto da Bíblia ──
        biblia_text = tk.Text(main, font=("Arial", 13), bg='#21262d', fg='#c9d1d9',
                              insertbackground='#f0c040', wrap='word', height=20)
        biblia_text.pack(fill='both', expand=True, pady=5)

        # ── Barra de busca por texto ──
        busca_frame = tk.Frame(main, bg='#161b22')
        busca_frame.pack(fill='x', pady=5, ipady=5)

        tk.Label(busca_frame, text="🔍", fg='#f0c040', bg='#161b22',
                 font=("Arial", 14)).pack(side='left', padx=(8, 5))

        entry_busca_texto = tk.Entry(busca_frame, font=("Arial", 12),
                                     bg='#21262d', fg='#f0c040', insertbackground='#f0c040',
                                     bd=0, highlightthickness=0)
        entry_busca_texto.pack(side='left', fill='x', expand=True, padx=5, ipady=3)
        entry_busca_texto.insert(0, "Buscar versículo por texto...")

        def _busca_texto_focus_in():
            if entry_busca_texto.get() == "Buscar versículo por texto...":
                entry_busca_texto.delete(0, tk.END)
                entry_busca_texto.config(fg='#f0c040')

        def _busca_texto_focus_out():
            if not entry_busca_texto.get().strip():
                entry_busca_texto.delete(0, tk.END)
                entry_busca_texto.insert(0, "Buscar versículo por texto...")
                entry_busca_texto.config(fg='#8b949e')

        entry_busca_texto.bind("<FocusIn>", lambda e: _busca_texto_focus_in())
        entry_busca_texto.bind("<FocusOut>", lambda e: _busca_texto_focus_out())

        def _buscar_versiculos_texto():
            """Busca versículos por texto e mostra na área da Bíblia.

            Retorna as linhas encontradas (None se busca vazia ou sem dados).
            """
            termo = entry_busca_texto.get().strip()
            if not termo or termo == "Buscar versículo por texto...":
                return None
            versao = versao_var.get()
            rows = db_query(
                "SELECT * FROM versiculos WHERE versao = ? AND texto LIKE ? "
                "ORDER BY livro, capitulo, versiculo LIMIT 50",
                (versao, f"%{termo}%"))
            biblia_text.config(state='normal')
            biblia_text.delete('1.0', tk.END)
            if rows:
                for r in rows:
                    ref = f"{r['livro']} {r['capitulo']}:{r['versiculo']}"
                    biblia_text.insert(tk.END, f"{ref} - {r['texto']}\n\n")
            else:
                biblia_text.insert(tk.END, "Nenhum versículo encontrado para esta busca.\n\n"
                                    "Dica: use o botão '📥 Importar Bíblia (XML/TXT/JSON)'\n"
                                    "para importar uma Bíblia.")
            biblia_text.config(state='disabled')
            return rows

        def _buscar_e_projetar_biblia(event=None):
            """Enter na busca de versículos: busca e já projeta os resultados.

            Mesmo efeito de buscar e clicar em "📺 Projetar", mas projetando
            exatamente o que a busca retornou ("Livro cap:vers. — texto").
            """
            rows = _buscar_versiculos_texto()
            if rows:
                _cap_numeros[:] = []
                slides = [
                    (r['texto'], f"{r['livro']} {r['capitulo']}:{r['versiculo']}")
                    for r in rows]
                self.player.telao.projetar_slides(slides)
                _atualizar_indicador_slide()
            return "break"

        entry_busca_texto.bind("<Return>", lambda e: _buscar_e_projetar_biblia())

        def _carregar_capitulo(foco: Optional[int] = None):
            """Carrega o capítulo atual na área de texto.

            Se `foco` for informado, exibe o capítulo inteiro e destaca o
            versículo correspondente (usado para sincronizar a janela com a
            projeção no telão).
            """
            versao = versao_var.get()
            livro = livro_var.get()
            cap = cap_var.get().strip()
            vers = vers_var.get().strip()
            if not cap or not cap.isdigit():
                return
            cap = int(cap)

            if foco is not None:
                v_ini, v_fim = 1, 9999
            elif vers and vers.isdigit():
                v_ini = v_fim = int(vers)
            else:
                v_ini, v_fim = 1, 9999

            rows = db_query(
                "SELECT * FROM versiculos WHERE versao = ? AND livro = ? "
                "AND capitulo = ? AND versiculo >= ? AND versiculo <= ? "
                "ORDER BY versiculo",
                (versao, livro, cap, v_ini, v_fim))

            biblia_text.config(state='normal')
            biblia_text.delete('1.0', tk.END)
            biblia_text.tag_remove('verso_atual', '1.0', tk.END)
            try:
                biblia_text.tag_configure('verso_atual', background='#6e40c9',
                                          foreground='#ffffff')
            except tk.TclError:
                pass
            if rows:
                for r in rows:
                    biblia_text.insert(tk.END, f"{r['versiculo']}. {r['texto']}\n")
                    if foco is not None and r['versiculo'] == foco:
                        inicio_linha = biblia_text.index("end-2c")
                        linha = int(inicio_linha.split('.')[0])
                        biblia_text.tag_add('verso_atual', f"{linha}.0",
                                            f"{linha}.0 lineend")
                        biblia_text.see(f"{linha}.0")
            else:
                biblia_text.insert(tk.END,
                    f"Nenhum versículo encontrado para {livro} {cap}:{vers or '*'} "
                    f"({versao}).\n\n"
                    "Dica: use o botão '📥 Importar Bíblia (XML/TXT/JSON)'\n"
                    "para importar uma Bíblia.")
            biblia_text.config(state='disabled')

        # ── Importação de Bíblia (XML / TXT) ──
        def _sem_acentos(texto: str) -> str:
            nf = unicodedata.normalize('NFKD', str(texto))
            return ''.join(c for c in nf if not unicodedata.combining(c)).casefold()

        _LIVROS_FLAT = {_sem_acentos(n): n for n in self.LIVROS_BIBLIA}
        _LIVROS_ALIAS = {
            "cantico dos canticos": "Cânticos",
            "cantares": "Cânticos",
            "lamentacoes de jeremias": "Lamentações",
        }

        def _normalizar_livro_biblia(nome: str) -> Optional[str]:
            """Converte o nome do livro para o padrão da lista do app.

            Insensível a acentos e a variações comuns: números romanos
            (I/II) e nomes completos ('Lamentações de Jeremias',
            'Cântico dos Cânticos'). Retorna None se não reconhecer.
            """
            chave = _sem_acentos(nome or '')
            if not chave:
                return None
            if chave in _LIVROS_FLAT:
                return _LIVROS_FLAT[chave]
            if chave in _LIVROS_ALIAS:
                return _LIVROS_ALIAS[chave]
            for rom, num in (("iii", "3"), ("ii", "2"), ("i", "1")):
                prefixo = rom + " "
                if chave.startswith(prefixo):
                    cand = num + " " + chave[len(prefixo):]
                    return _LIVROS_FLAT.get(cand)
            return None

        def _parsear_biblia_xml(caminho: str) -> tuple:
            """Lê uma Bíblia em XML (estilo Zefania: BIBLEBOOK/CHAPTER/VERS).

            Retorna (versao, versiculos, livros_desconhecidos), onde
            versiculos é uma lista de tuplas (versao, livro, capitulo,
            versiculo, texto).
            """
            tree = ET.parse(caminho)
            raiz = tree.getroot()
            versao = (raiz.get('biblename') or
                      os.path.splitext(os.path.basename(caminho))[0] or
                      "Bíblia")
            versiculos = []
            desconhecidos = set()
            for bb in raiz.findall('BIBLEBOOK'):
                livro = _normalizar_livro_biblia(bb.get('bname'))
                if not livro:
                    desconhecidos.add(bb.get('bname'))
                    continue
                for ch in bb.findall('CHAPTER'):
                    cap_t = ch.get('cnumber')
                    if not cap_t or not cap_t.isdigit():
                        continue
                    cap = int(cap_t)
                    for v in ch.findall('VERS'):
                        nv_t = v.get('vnumber')
                        if not nv_t or not nv_t.isdigit():
                            continue
                        texto = (v.text or '').strip()
                        if not texto:
                            continue
                        versiculos.append((versao, livro, cap, int(nv_t), texto))
            return versao, versiculos, desconhecidos

        def _parsear_biblia_txt(caminho: str) -> tuple:
            """Lê uma Bíblia em TXT (formato Almeida Revista e Corrigida).

            Estrutura: linhas ' LIVRO CAP', linhas 'N texto do versículo',
            separadores com o nome do livro sozinho e possível continuação
            de versículo na linha seguinte. Números romanos (I/II) são
            convertidos e nomes completos são normalizados.
            """
            versao = "Almeida Revista e Corrigida"
            _re_header = re.compile(r'^\s*(.+?)(\d{1,3})\s*$')
            _re_verso = re.compile(r'^\s*(\d{1,3})\s+(.*)$')
            versiculos = []
            desconhecidos = set()
            livro_atual = None
            cap_atual = None
            for linha in open(caminho, encoding='utf-8', errors='replace'):
                s = linha.rstrip('\n')
                t = s.strip()
                if not t:
                    continue
                if t in ("ANTIGO TESTAMENTO", "NOVO TESTAMENTO"):
                    continue
                # Separador com o nome do livro sozinho (ex.: "ÊXODO")
                if _normalizar_livro_biblia(t) is not None:
                    continue
                # Cabeçalho de capítulo: '<nome do livro> <número>'
                m = _re_header.match(s)
                if m:
                    novo_livro = _normalizar_livro_biblia(m.group(1).strip())
                    if novo_livro is not None:
                        livro_atual = novo_livro
                        cap_atual = int(m.group(2))
                        continue
                # Versículo: '<número> <texto>'
                m = _re_verso.match(s)
                if m and livro_atual is not None and cap_atual is not None:
                    versiculos.append((versao, livro_atual, cap_atual,
                                       int(m.group(1)), m.group(2).strip()))
                elif versiculos and livro_atual is not None and cap_atual is not None:
                    # Continuação de versículo na linha seguinte
                    linhas = versiculos[-1][4] + " " + t
                    versiculos[-1] = (versiculos[-1][0], versiculos[-1][1],
                                      versiculos[-1][2], versiculos[-1][3], linhas)
            return versao, versiculos, desconhecidos

        def _parsear_biblia_json(caminho: str) -> tuple:
            """Lê uma Bíblia em JSON e retorna (versao, versiculos, desconhecidos).

            Aceita as estruturas mais comuns:
            - {Livro: {cap: {vers: texto}}}
            - {Livro: {cap: [texto1, texto2, ...]}}
            - {"books": [{"name": ..., "chapters": [[{"verse": n, "text": ...}]]}]}
            - [{"book": ..., "chapter": n, "verse": n, "text": ...}] (lista plana)
            A versão é lida das chaves 'version'/'versao'/'biblename' do objeto
            raiz, ou do nome do arquivo.
            """
            with open(caminho, encoding='utf-8-sig') as f:
                dados = json.load(f)
            versiculos = []
            desconhecidos = set()
            raiz = dados

            # Extrai o nome da versão das chaves de metadados do objeto raiz
            versao = None
            if isinstance(raiz, dict):
                for chave in ("version", "versao", "biblename", "translation",
                              "nome", "name"):
                    v = raiz.get(chave)
                    if isinstance(v, str) and v.strip():
                        versao = v.strip()
                        break
            if not versao:
                versao = (os.path.splitext(os.path.basename(caminho))[0] or "Bíblia")

            def _texto(obj) -> str:
                if isinstance(obj, str):
                    return obj.strip()
                if isinstance(obj, dict):
                    for chave in ("text", "texto"):
                        v = obj.get(chave)
                        if isinstance(v, str):
                            return v.strip()
                        if isinstance(v, (int, float)):
                            return str(v)
                    for v in obj.values():
                        if isinstance(v, str):
                            return v.strip()
                    return ""
                if isinstance(obj, list):
                    partes = [p for p in (_texto(x) for x in obj) if p]
                    return " ".join(partes)
                if isinstance(obj, (int, float)):
                    return str(obj)
                return ""

            def _numero(obj, *chaves) -> Optional[int]:
                if isinstance(obj, dict):
                    for chave in chaves:
                        v = obj.get(chave)
                        if v is None:
                            continue
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            return int(v)
                        m = re.match(r'^\s*(\d+)', str(v))
                        if m:
                            return int(m.group(1))
                return None

            def _versiculos_capitulo(valor, cap, livro) -> None:
                """Extrai os versículos de um capítulo (dict ou lista)."""
                if isinstance(valor, dict):
                    for vk, vv in valor.items():
                        num = _numero({"_": vk}, "_") if str(vk).strip().isdigit() \
                            else _numero(vv, "verse", "versiculo", "n", "num")
                        if num is None:
                            continue
                        texto = _texto(vv)
                        if texto:
                            versiculos.append((versao, livro, cap, num, texto))
                elif isinstance(valor, list):
                    for i, item in enumerate(valor, start=1):
                        if isinstance(item, dict):
                            num = _numero(item, "verse", "versiculo", "n", "num", "v")
                            texto = _texto(item)
                            if num is None or not texto:
                                continue
                            versiculos.append((versao, livro, cap, num, texto))
                        else:
                            texto = _texto(item)
                            if texto:
                                versiculos.append((versao, livro, cap, i, texto))
                elif isinstance(valor, str) and valor.strip():
                    versiculos.append((versao, livro, cap, 1, valor.strip()))

            def _processar_livro(nome, valor) -> None:
                nonlocal versao
                livro = _normalizar_livro_biblia(nome)
                if not livro:
                    desconhecidos.add(str(nome))
                    return
                if isinstance(valor, dict) and any(k in valor for k in
                                                   ("chapters", "textos")):
                    # formato {name/abbrev, chapters: [[verso1, verso2, ...]]}
                    dados = valor.get("chapters")
                    if not isinstance(dados, (list, dict)):
                        dados = valor.get("textos")
                    if isinstance(dados, (list, dict)):
                        valor = dados
                    else:
                        return
                if isinstance(valor, dict):
                    cap = _numero(valor, "chapter", "capitulo", "cnumber")
                    num = _numero(valor, "verse", "versiculo", "n", "v")
                    if cap is not None and num is not None:
                        # objeto de versículo único {book, chapter, verse, text}
                        texto = _texto(valor)
                        if texto:
                            versiculos.append((versao, livro, cap, num, texto))
                        return
                    for ck, cv in valor.items():
                        cap = _numero({"_": ck}, "_") if str(ck).strip().isdigit() \
                            else _numero(cv, "chapter", "capitulo", "cnumber")
                        if cap is None:
                            # formato {livro: [{chapter: 1, verses: [...]}]}
                            if isinstance(cv, list) and cv and all(
                                    isinstance(x, dict) for x in cv):
                                for obj in cv:
                                    c2 = _numero(obj, "chapter", "capitulo")
                                    if c2 is None:
                                        continue
                                    _versiculos_capitulo(obj.get("verses",
                                                                  obj.get("textos",
                                                                         [])), c2, livro)
                                continue
                            continue
                        _versiculos_capitulo(cv, cap, livro)
                elif isinstance(valor, list):
                    if not valor:
                        return
                    if isinstance(valor[0], dict):
                        # lista plana de versículos OU de capítulos
                        tem_cap = any(any(k in v for k in ("chapter", "capitulo"))
                                      for v in valor)
                        tem_ver = any(any(k in v for k in ("verse", "versiculo",
                                                           "v", "n"))
                                      for v in valor)
                        if tem_cap and tem_ver:
                            for obj in valor:
                                cap = _numero(obj, "chapter", "capitulo")
                                num = _numero(obj, "verse", "versiculo", "v", "n")
                                texto = _texto(obj)
                                if cap is None or num is None or not texto:
                                    continue
                                versiculos.append((versao, livro, cap, num, texto))
                        else:
                            # lista de capítulos: [{n/chapter: c, verses/textos: [...]}]
                            for obj in valor:
                                cap = _numero(obj, "chapter", "capitulo", "n")
                                if cap is None:
                                    continue
                                _versiculos_capitulo(
                                    obj.get("verses", obj.get("textos", [])), cap, livro)
                    elif isinstance(valor[0], list):
                        # lista de capítulos, cada um uma lista de versículos
                        for i, cap_lista in enumerate(valor, start=1):
                            _versiculos_capitulo(cap_lista, i, livro)
                    else:
                        # lista de textos (capítulo único)
                        _versiculos_capitulo(valor, 1, livro)

            if isinstance(raiz, dict):
                for chave, valor in raiz.items():
                    if chave.lower() in ("version", "versao", "biblename",
                                         "translation", "nome", "name", "id",
                                         "info", "metadata", "language", "lang"):
                        continue
                    # {"books": [...]} -> cada item tem o nome do livro
                    if chave.lower() == "books" and isinstance(valor, list):
                        for item in valor:
                            nome = item.get("name") or item.get("nome") or \
                                   item.get("book") or item.get("livro")
                            if not nome:
                                continue
                            dados_livro = item.get("chapters") or item.get("textos") \
                                or item
                            _processar_livro(nome, dados_livro)
                    else:
                        _processar_livro(chave, valor)
            elif isinstance(raiz, list):
                for item in raiz:
                    nome = item.get("book") or item.get("livro") or \
                           item.get("name") if isinstance(item, dict) else None
                    if nome:
                        _processar_livro(nome, item)
                    else:
                        desconhecidos.add(str(item)[:40])
            return versao, versiculos, desconhecidos

        def _importar_biblia(caminhos: tuple) -> None:
            """Importa uma ou mais Bíblias (XML/TXT/JSON) para a tabela versiculos."""
            total_inseridos = 0
            total_pulados = 0
            erros = 0
            versoes_importadas = []
            desconhecidos = set()
            for caminho in caminhos:
                ext = os.path.splitext(caminho)[1].lower()
                try:
                    if ext == '.xml':
                        versao, vv, desc = _parsear_biblia_xml(caminho)
                    elif ext == '.txt':
                        versao, vv, desc = _parsear_biblia_txt(caminho)
                    elif ext == '.json':
                        versao, vv, desc = _parsear_biblia_json(caminho)
                    else:
                        erros += 1
                        continue
                except Exception as e:
                    print(f"Erro ao importar bíblia {caminho}: {e}")
                    erros += 1
                    continue
                desconhecidos.update(desc)
                existentes = {
                    (r['versao'], r['livro'], r['capitulo'], r['versiculo'])
                    for r in db_query(
                        "SELECT versao, livro, capitulo, versiculo FROM versiculos "
                        "WHERE versao = ?", (versao,))
                }
                novos = [v for v in vv
                         if (v[0], v[1], v[2], v[3]) not in existentes]
                total_pulados += len(vv) - len(novos)
                if novos:
                    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT)
                    try:
                        ids_livres = list(
                            _gerador_id_livre("versiculos",
                                              limitar=len(novos)))
                        com_id = []
                        sem_id = []
                        for idx, ver in enumerate(novos):
                            if idx < len(ids_livres):
                                com_id.append((ids_livres[idx],) + tuple(ver))
                            else:
                                sem_id.append(tuple(ver))
                        if com_id:
                            conn.executemany(
                                "INSERT INTO versiculos "
                                "(id, versao, livro, capitulo, versiculo, texto) "
                                "VALUES (?, ?, ?, ?, ?, ?)", com_id)
                        if sem_id:
                            conn.executemany(
                                "INSERT INTO versiculos "
                                "(versao, livro, capitulo, versiculo, texto) "
                                "VALUES (?, ?, ?, ?, ?)", sem_id)
                        conn.commit()
                    finally:
                        conn.close()
                    total_inseridos += len(novos)
                if versao not in versoes_importadas:
                    versoes_importadas.append(versao)

            msg = f"✅ {total_inseridos} versículos importados, " \
                  f"{total_pulados} já existentes (pulados)."
            if versoes_importadas:
                msg += f"\n📚 Versões: {', '.join(versoes_importadas)}"
            if desconhecidos:
                msg += f"\n⚠️ {len(desconhecidos)} livro(s) não reconhecidos: " \
                       f"{', '.join(str(x) for x in sorted(desconhecidos))}"
            if erros:
                msg += f"\n⚠️ {erros} arquivo(s) com erro."
            tkinter.messagebox.showinfo("Importação de Bíblia", msg, parent=janela)

            # Atualiza lista de versões e carrega a primeira importada
            atuais = db_query("SELECT DISTINCT versao FROM versiculos ORDER BY versao")
            novas_versoes = [r['versao'] for r in atuais]
            if novas_versoes:
                combo_versao.config(values=novas_versoes)
            if versoes_importadas:
                versao_var.set(versoes_importadas[0])
                _carregar_capitulo()

        def _importar_biblia_dialog() -> None:
            selecionados = _escolher_arquivos_usuario(
                parent=janela,
                titulo="Importar Bíblia (XML / TXT / JSON)",
                pasta_inicial=os.path.expanduser("~"))
            if selecionados:
                _importar_biblia(selecionados)

        # ── Botões ──
        btn_frame = tk.Frame(main, bg='#0d1117')
        btn_frame.pack(fill='x', pady=5)

        tk.Button(btn_frame, text="📖 Carregar", font=("Arial", 11, "bold"),
                  bg='#238636', fg='white', activebackground='#2ea043',
                  command=_carregar_capitulo, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="🔍 Buscar Texto", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_buscar_versiculos_texto, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="📥 Importar Bíblia (XML/TXT)", font=("Arial", 11, "bold"),
                  bg='#8b5cf6', fg='white', activebackground='#a78bfa',
                  command=_importar_biblia_dialog, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="🎨 Projeção", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=lambda: self.abrir_config_projecao_dialogo(janela, mostrar_cor_ref=True),
                  cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="📺 Projetar", font=("Arial", 11, "bold"),
                  bg='#6e40c9', fg='#f0c040', activebackground='#8b5cf6',
                  command=lambda: _projetar_versiculo(), cursor='hand2', padx=12, pady=4
                  ).pack(side='right', padx=3)

        def _projetar_versiculo():
            """Projeta o capítulo aberto como versículos no telão.

            A projeção inicia pelo versículo indicado no campo "V:"
            (padrão: versículo 1). O administrador navega entre versículos
            com as setas do teclado ou do painel; Esc encerra e volta o
            relógio + temperatura ao telão.
            """
            versao = versao_var.get()
            livro = livro_var.get()
            cap_t = cap_var.get().strip()
            if not cap_t.isdigit():
                return
            cap = int(cap_t)
            rows = db_query(
                "SELECT versiculo, texto FROM versiculos WHERE versao = ? "
                "AND livro = ? AND capitulo = ? ORDER BY versiculo",
                (versao, livro, cap))
            if not rows:
                tkinter.messagebox.showwarning(
                    "Projeção", "Nenhum versículo para projetar neste capítulo.",
                    parent=janela)
                return
            vers_t = vers_var.get().strip()
            vers_ini = int(vers_t) if vers_t.isdigit() else 1
            numeros = [r['versiculo'] for r in rows]
            _cap_numeros[:] = numeros
            slides = [(r['texto'], f"{livro} {cap}:{r['versiculo']}") for r in rows]
            inicio = numeros.index(vers_ini) if vers_ini in numeros else 0
            self.player.telao.projetar_slides(slides, indice_inicial=inicio)
            _carregar_capitulo(foco=vers_ini)
            _atualizar_indicador_slide()

        # ── Painel de controle da projeção (versículos) ──
        nav_frame = tk.Frame(main, bg='#161b22')
        nav_frame.pack(fill='x', pady=(4, 2), ipady=4)

        tk.Label(nav_frame, text="🎬 Controle da Projeção:",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#161b22'
                 ).pack(side='left', padx=(10, 8))

        tk.Button(nav_frame, text="◀ Anterior", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=lambda: _slide_anterior(), cursor='hand2', padx=12, pady=2
                  ).pack(side='left', padx=3)
        tk.Button(nav_frame, text="Próximo ▶", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=lambda: _slide_proximo(), cursor='hand2', padx=12, pady=2
                  ).pack(side='left', padx=3)
        tk.Button(nav_frame, text="⏹ Parar (Esc)", font=("Arial", 11, "bold"),
                  bg='#da3633', fg='white', activebackground='#f85149',
                  command=lambda: _parar_projecao(), cursor='hand2', padx=12, pady=2
                  ).pack(side='left', padx=3)

        tk.Label(nav_frame, text="🔠 Tamanho:",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#161b22'
                 ).pack(side='left', padx=(14, 2))
        tk.Button(nav_frame, text="A−", font=("Arial", 11, "bold"),
                  bg='#8957e5', fg='white', activebackground='#a371f7',
                  command=lambda: _ajustar_fonte(-0.8), cursor='hand2', padx=10, pady=2
                  ).pack(side='left', padx=2)
        tk.Button(nav_frame, text="A+", font=("Arial", 11, "bold"),
                  bg='#8957e5', fg='white', activebackground='#a371f7',
                  command=lambda: _ajustar_fonte(0.8), cursor='hand2', padx=10, pady=2
                  ).pack(side='left', padx=2)

        label_slide = tk.Label(nav_frame, text="Sem projeção",
                               font=("Arial", 11, "bold"), fg='#8b949e', bg='#161b22')
        label_slide.pack(side='right', padx=10)

        _cap_numeros = []

        def _atualizar_indicador_slide():
            try:
                if not label_slide.winfo_exists():
                    return
            except tk.TclError:
                return
            telao = self.player.telao
            em_slides = getattr(telao, "_em_slides", False)
            if em_slides and telao._slides:
                idx = telao._slide_index
                if _cap_numeros and 0 <= idx < len(_cap_numeros):
                    num = f"Versículo {_cap_numeros[idx]}"
                else:
                    num = f"Versículo {idx + 1}"
                label_slide.config(
                    text=f"{num} de {len(telao._slides)}",
                    fg='#3fb950', bg='#161b22')
            elif getattr(telao, "mostrando_letra", False):
                label_slide.config(text="Projeção ativa", fg='#f0c040', bg='#161b22')
            else:
                label_slide.config(text="Sem projeção", fg='#8b949e', bg='#161b22')

        def _destacar_versiculo_na_tela(num: int) -> bool:
            """Marca o versículo `num` na área de texto (True se encontrado)."""
            biblia_text.tag_remove('verso_atual', '1.0', tk.END)
            try:
                biblia_text.tag_configure('verso_atual', background='#6e40c9',
                                          foreground='#ffffff')
            except tk.TclError:
                return False
            texto_area = biblia_text.get('1.0', tk.END)
            for i, linha in enumerate(texto_area.split('\n'), start=1):
                if linha.startswith(f"{num}. "):
                    biblia_text.tag_add('verso_atual', f"{i}.0", f"{i}.0 lineend")
                    biblia_text.see(f"{i}.0")
                    return True
            return False

        def _sincronizar_biblia_com_telao():
            """Reflete na janela da Bíblia (monitor 1) o versículo projetado.

            Atualiza o campo "V:", destaca o versículo na área de texto e
            rola a visualização até ele, mantendo as duas telas em sincronia.
            """
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False) or not telao._slides:
                return
            idx = telao._slide_index
            if _cap_numeros and 0 <= idx < len(_cap_numeros):
                num = _cap_numeros[idx]
            else:
                num = idx + 1
            vers_var.set(str(num))
            if not _destacar_versiculo_na_tela(num):
                _carregar_capitulo(foco=num)
            _atualizar_indicador_slide()

        def _slide_anterior(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if telao.slide_anterior():
                _sincronizar_biblia_com_telao()
            return "break"

        def _slide_proximo(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if telao.slide_proximo():
                _sincronizar_biblia_com_telao()
            return "break"

        def _parar_projecao(event: object = None):
            if not getattr(self.player.telao, "mostrando_letra", False):
                return None
            self.player.telao.parar_projecao()
            try:
                biblia_text.tag_remove('verso_atual', '1.0', tk.END)
            except tk.TclError:
                pass
            _atualizar_indicador_slide()
            return "break"

        def _ajustar_fonte(delta: float):
            """Aumenta/diminui a fonte da projeção e redesenha o que está ativo."""
            telao = self.player.telao
            cfg = getattr(telao, "_proj_cfg", None)
            if cfg is None:
                telao.configurar_projecao()
                cfg = telao._proj_cfg
            novo = min(15.0, max(1.0, float(cfg.get("tamanho_pct", 5.0)) + delta))
            cfg["tamanho_pct"] = novo
            telao._proj_cfg = cfg
            if getattr(telao, "_em_slides", False) and telao._slides:
                telao._mostrar_slide(telao._slide_index)
            elif getattr(telao, "mostrando_letra", False) and telao._current_text:
                telao._desenhar_texto_no_canvas(telao._current_text)
            self.salvar_config_projecao(dict(cfg))
            _atualizar_indicador_slide()

        # Setas do teclado e Esc (janela de bíblia).
        # No root substituímos a ligação a cada abertura para evitar acumular
        # handlers duplicados de chamadas repetidas a janela_biblia.
        janela.bind("<Left>", _slide_anterior)
        janela.bind("<Up>", _slide_anterior)
        janela.bind("<Right>", _slide_proximo)
        janela.bind("<Down>", _slide_proximo)
        janela.bind("<Escape>", _parar_projecao)
        self.root.bind("<Left>", _slide_anterior)
        self.root.bind("<Up>", _slide_anterior)
        self.root.bind("<Right>", _slide_proximo)
        self.root.bind("<Down>", _slide_proximo)
        self.root.bind("<Escape>", _parar_projecao)

        # Carrega João 3:16 como padrão
        _carregar_capitulo()

    # ────────────────────────────────────────────────────────────────────
    # JANELA DE ORDEM DE SERVIÇO
    # ────────────────────────────────────────────────────────────────────

    def janela_ordem_servico(self) -> None:
        """Abre a janela de planejamento de ordem de serviço.

        As ordens são salvas em ~/.navepro/servicos.json (nunca importam
        vídeo/slides). Oferece criar, editar e excluir serviços, além de
        arrastar e soltar os itens para reordená-los.
        """
        _migrar_servicos_do_banco()
        _sincronizar_uploads_midia()
        _SERVICO_PROXIMO_ITEM.clear()
        dados = _carregar_servicos_json()
        janela = tk.Toplevel(self.root)
        janela.title("📋 Ordem de Serviço")
        janela.geometry("1100x750")
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        janela.after(50, janela.grab_set)

        main = tk.Frame(janela, bg='#0d1117')
        main.pack(fill='both', expand=True, padx=15, pady=15)

        tk.Label(main, text="📋 Ordem de Serviço",
                 font=("Arial", 16, "bold"), fg='#f0c040', bg='#0d1117'
                 ).pack(pady=(0, 10))

        # ── Lista de serviços salvos ──
        serv_frame = tk.Frame(main, bg='#161b22')
        serv_frame.pack(fill='x', pady=5, ipady=5)

        tk.Label(serv_frame, text="Serviço:", fg='#f0c040', bg='#161b22',
                 font=("Arial", 11, "bold")).pack(side='left', padx=8)

        servico_var = tk.StringVar()
        combo_servico = ttk.Combobox(serv_frame, textvariable=servico_var,
                                      width=40, font=("Arial", 11), state='readonly')
        combo_servico.pack(side='left', padx=5)

        servico_selecionado_id = [None]

        def _rotulo_servico(s: Dict) -> str:
            return f"{s.get('id')} - {s.get('nome', '')}"

        def _servico_atual() -> Optional[Dict]:
            sid = servico_selecionado_id[0]
            if not sid:
                return None
            return next((s for s in dados["servicos"] if s.get("id") == sid), None)

        def _ordenar_servicos():
            return sorted(
                dados["servicos"],
                key=lambda s: s.get('id') or 0,
                reverse=True)

        def _carregar_servicos(escolher: bool = True):
            ord_servicos = _ordenar_servicos()
            opcoes = [_rotulo_servico(s) for s in ord_servicos]
            combo_servico['values'] = opcoes
            combo_servico._servico_ids = [s['id'] for s in ord_servicos]
            if opcoes and escolher:
                combo_servico.current(0)

        def _on_servico_select(event=None):
            sel = combo_servico.get()
            if not sel:
                return
            idx = combo_servico.current()
            ids = getattr(combo_servico, '_servico_ids', [])
            if idx >= 0 and idx < len(ids):
                servico_selecionado_id[0] = ids[idx]
                _carregar_itens()

        combo_servico.bind("<<ComboboxSelected>>", _on_servico_select)

        # ── Itens do serviço (Treeview) ──
        tree_frame = tk.Frame(main, bg='#161b22')
        tree_frame.pack(fill='both', expand=True, pady=5)

        colunas = ("#", "Tipo", "Título", "Duração")
        tree = ttk.Treeview(tree_frame, columns=colunas, show='headings', height=16)
        tree.heading("#", text="#")
        tree.heading("Tipo", text="Tipo")
        tree.heading("Título", text="Título")
        tree.heading("Duração", text="Duração (s)")
        tree.column("#", width=40)
        tree.column("Tipo", width=120)
        tree.column("Título", width=350)
        tree.column("Duração", width=100)

        scroll_y = tk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll_y.set)
        tree.pack(side='left', fill='both', expand=True)
        scroll_y.pack(side='right', fill='y')

        style = ttk.Style()
        style.configure("Treeview", background="#21262d", foreground="#c9d1d9",
                        fieldbackground="#21262d", font=("Arial", 10))
        style.configure("Treeview.Heading", background="#161b22", foreground="#f0c040",
                        font=("Arial", 10, "bold"))
        style.map('Treeview', background=[('selected', '#6e40c9')],
                  foreground=[('selected', '#ffffff')])

        # ── Drag & drop para reordenar itens dentro da tree ──
        _drag_state: Dict[str, Optional[str]] = {"origem": None}

        def _on_tree_button_press(event):
            if tree.identify_region(event.x, event.y) in ("heading", "separator"):
                return
            item = tree.identify_row(event.y)
            if not item:
                return
            _drag_state["origem"] = item

        def _on_tree_button_release(event):
            origem = _drag_state.get("origem")
            _drag_state["origem"] = None
            if not origem:
                return
            destino = tree.identify_row(event.y)
            serv = _servico_atual()
            if not serv or not destino or destino == origem:
                return
            itens = list(serv.get("itens") or [])
            novo = _reordenar_itens_servico(itens, int(origem), int(destino))
            if novo != itens:
                serv["itens"] = novo
                if _salvar_servicos_json(dados):
                    _carregar_itens()
                    tree.selection_set(destino)
                    tree.focus(destino)

        tree.bind("<ButtonPress-1>", _on_tree_button_press)
        tree.bind("<ButtonRelease-1>", _on_tree_button_release)

        def _on_tree_double_click(event):
            if tree.identify_region(event.x, event.y) == "heading":
                return
            if not tree.identify_row(event.y):
                return
            _editar_item_selecionado()

        tree.bind("<Double-1>", _on_tree_double_click)

        def _carregar_itens():
            for item in tree.get_children():
                tree.delete(item)
            serv = _servico_atual()
            if not serv:
                return
            itens = list(serv.get("itens") or [])
            for i, it in enumerate(itens):
                tipo = it.get("tipo") or "slide"
                tipo_emoji = {"hino": "📖", "versiculo": "✝️", "video": "🎬",
                              "audio": "🎵", "slide": "📄", "anuncio": "📢",
                              "sermao": "🎤"}.get(tipo, "📁")
                tree.insert("", tk.END, iid=str(it.get("id")),
                            values=(i + 1, f"{tipo_emoji} {tipo.title()}",
                                    it.get("titulo_custom") or f"Item {i+1}",
                                    it.get("duracao_estimada_segundos") or 0))

        # ── Botões ──
        btn_frame = tk.Frame(main, bg='#0d1117')
        btn_frame.pack(fill='x', pady=5)

        def _novo_servico():
            nome = tkinter.simpledialog.askstring("Novo Serviço",
                "Nome do serviço:", parent=janela) if hasattr(tkinter, 'simpledialog') else None
            if not nome:
                # Fallback se simpledialog não estiver disponível
                nome_win = tk.Toplevel(janela)
                nome_win.title("Novo Serviço")
                nome_win.geometry("350x120")
                nome_win.configure(bg='#0d1117')
                nome_win.transient(janela)
                nome_win.after(50, nome_win.grab_set)
                tk.Label(nome_win, text="Nome do serviço:", fg='#f0c040', bg='#0d1117',
                         font=("Arial", 11)).pack(pady=5)
                nome_entry = tk.Entry(nome_win, font=("Arial", 12), bg='#21262d',
                                      fg='#f0c040', insertbackground='#f0c040')
                nome_entry.pack(padx=15, fill='x', ipady=3)
                nome_entry.focus_set()
                resultado = [None]
                def _ok():
                    resultado[0] = nome_entry.get().strip()
                    nome_win.destroy()
                tk.Button(nome_win, text="OK", font=("Arial", 11, "bold"),
                          bg='#238636', fg='white', command=_ok).pack(pady=5)
                nome_win.wait_window()
                nome = resultado[0]
            if not nome:
                return
            novo_id = dados["_proximo_id_servico"]
            dados["servicos"].append({
                "id": novo_id,
                "nome": nome,
                "criado_em": datetime.now().isoformat(timespec="seconds"),
                "itens": [],
            })
            dados["_proximo_id_servico"] = novo_id + 1
            if not _salvar_servicos_json(dados):
                dados["servicos"] = [s for s in dados["servicos"]
                                     if s.get("id") != novo_id]
                dados["_proximo_id_servico"] = novo_id
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar em servicos.json.", parent=janela)
                return
            _carregar_servicos()
            _on_servico_select()

        def _editar_servico():
            serv = _servico_atual()
            if not serv:
                tkinter.messagebox.showwarning("Seleção", "Selecione um serviço.", parent=janela)
                return
            nome = (tkinter.simpledialog.askstring(
                "Editar Serviço", "Nome do serviço:",
                initialvalue=serv.get("nome", ""), parent=janela)
                if hasattr(tkinter, 'simpledialog') else None)
            if not nome:
                return
            nome = nome.strip()
            if not nome:
                return
            serv["nome"] = nome
            if not _salvar_servicos_json(dados):
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar em servicos.json.", parent=janela)
                return
            _carregar_servicos()
            _on_servico_select()

        def _excluir_servico():
            serv = _servico_atual()
            if not serv:
                tkinter.messagebox.showwarning("Seleção", "Selecione um serviço.", parent=janela)
                return
            n_itens = len(list(serv.get("itens") or []))
            if not tkinter.messagebox.askyesno(
                    "Confirmar",
                    f"Excluir o serviço '{serv.get('nome', '')}' "
                    f"com {n_itens} item(ns)?", parent=janela):
                return
            sid = serv.get("id")
            dados["servicos"] = [s for s in dados["servicos"] if s.get("id") != sid]
            if not _salvar_servicos_json(dados):
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar a exclusão em servicos.json.",
                    parent=janela)
                return
            servico_selecionado_id[0] = None
            _carregar_servicos()
            if combo_servico['values']:
                _on_servico_select()

        def _abrir_editor_item(item_edit: Optional[Dict] = None):
            """Abre a janela para adicionar (item_edit=None) ou editar um item."""
            sid = servico_selecionado_id[0]
            if not sid:
                tkinter.messagebox.showwarning("Seleção", "Selecione ou crie um serviço.", parent=janela)
                return
            add_win = tk.Toplevel(janela)
            add_win.title("Editar Item" if item_edit else "Adicionar Item")
            add_win.geometry("700x300")
            add_win.configure(bg='#0d1117')
            add_win.transient(janela)
            add_win.after(50, add_win.grab_set)

            add_main = tk.Frame(add_win, bg='#0d1117')
            add_main.pack(fill='both', expand=True, padx=15, pady=15)

            tk.Label(add_main, text="Tipo:", fg='#f0c040', bg='#0d1117',
                     font=("Arial", 11, "bold")).pack(anchor='w')
            tipo_var = tk.StringVar(value=(item_edit or {}).get("tipo") or "hino")
            tipos = ["hino", "versiculo", "video", "audio", "slide", "anuncio", "sermao"]
            tipo_frame = tk.Frame(add_main, bg='#0d1117')
            tipo_frame.pack(fill='x', pady=2)
            for t in tipos:
                tk.Radiobutton(tipo_frame, text=t.title(), variable=tipo_var, value=t,
                               bg='#0d1117', fg='#c9d1d9', selectcolor='#21262d',
                               font=("Arial", 10)).pack(side='left', padx=3)

            tk.Label(add_main, text="Título:", fg='#f0c040', bg='#0d1117',
                     font=("Arial", 11, "bold")).pack(anchor='w', pady=(8, 0))
            titulo_entry = tk.Entry(add_main, font=("Arial", 11), bg='#21262d',
                                    fg='#f0c040', insertbackground='#f0c040')
            titulo_entry.insert(0, (item_edit or {}).get("titulo_custom") or "")
            titulo_entry.pack(fill='x', ipady=3, pady=2)

            tk.Label(add_main, text="Buscar (nº ou nome do hino/mídia/anúncio):", fg='#8b949e',
                     bg='#0d1117', font=("Arial", 9)).pack(anchor='w')
            ref_entry = tk.Entry(add_main, font=("Arial", 11), bg='#21262d',
                                 fg='#c9d1d9', insertbackground='#f0c040')
            if item_edit:
                _tf = (item_edit.get("tipo") or "").lower()
                _tc = (item_edit.get("titulo_custom") or "").strip()
                if _tf in ("hino", "audio", "video", "anuncio") and _tc and not _tc.startswith("Item "):
                    ref_entry.insert(0, _tc)
                else:
                    ref_entry.insert(0, str(item_edit.get("referencia_id") or ""))
            ref_entry.pack(fill='x', ipady=3, pady=2)

            tk.Label(add_main, text="Duração estimada (segundos):", fg='#8b949e',
                     bg='#0d1117', font=("Arial", 9)).pack(anchor='w')
            dur_entry = tk.Entry(add_main, font=("Arial", 11), bg='#21262d',
                                 fg='#c9d1d9', insertbackground='#f0c040')
            dur_entry.insert(0, str((item_edit or {}).get("duracao_estimada_segundos") or 0))
            dur_entry.pack(fill='x', ipady=3, pady=2)

            def _salvar_item():
                serv = _servico_atual()
                if serv is None:
                    return
                tipo = tipo_var.get()
                titulo = titulo_entry.get().strip()
                termo = ref_entry.get().strip()
                duracao = int(dur_entry.get().strip()) if dur_entry.get().strip().isdigit() else 0

                # ── Resolução da referência por busca (nº ou nome) ──
                # Se o campo "Buscar" estiver vazio, o próprio Título digitado
                # já é usado como termo de busca (hino/mídia por número ou nome).
                ref_id = None
                letra_snap = ""
                _usou_titulo_como_busca = (not termo)
                if not termo:
                    termo = titulo
                if tipo == "hino":
                    rows_match = _buscar_hino_por_termo(termo)
                    if not rows_match and termo.isdigit():
                        rows_match = db_query(
                            "SELECT * FROM letras WHERE id = ? AND ativo = 1", (termo,))
                    if not rows_match:
                        tkinter.messagebox.showwarning(
                            "Busca", f"Nenhum hino encontrado para: \"{termo}\".",
                            parent=janela)
                        return
                    ref_hino = rows_match[0]
                    ref_id = ref_hino.get("id")
                    letra_snap = ref_hino.get("letra_completa", "")
                    if not titulo or _usou_titulo_como_busca:
                        titulo = ref_hino.get("titulo", "") or f"Item ({tipo.title()})"
                elif tipo in ("video", "audio"):
                    rows_match = _buscar_midia_por_termo(termo, tipo=tipo)
                    if not rows_match and termo.isdigit():
                        rows_match = db_query(
                            "SELECT * FROM midia WHERE id = ? AND ativo = 1", (termo,))
                    if not rows_match:
                        tkinter.messagebox.showwarning(
                            "Busca", f"Nenhuma {tipo.title()} encontrada para: \"{termo}\".",
                            parent=janela)
                        return
                    ref_midia = rows_match[0]
                    ref_id = ref_midia.get("id")
                    if not titulo or _usou_titulo_como_busca:
                        titulo = ref_midia.get("nome_exibicao", "") or f"Item ({tipo.title()})"
                elif tipo == "anuncio":
                    rows_match = _buscar_anuncio_por_termo(termo)
                    if not rows_match:
                        tkinter.messagebox.showwarning(
                            "Busca", f"Nenhum anúncio encontrado para: \"{termo}\".",
                            parent=janela)
                        return
                    ref_an = rows_match[0]
                    ref_id = ref_an.get("id")
                    letra_snap = ref_an.get("texto") or ""
                    if not titulo or _usou_titulo_como_busca:
                        titulo = ref_an.get("titulo") or f"Item ({tipo.title()})"
                elif termo.isdigit():
                    ref_id = int(termo)
                if not titulo:
                    titulo = f"Item ({tipo.title()})"
                if tipo == "versiculo" and ref_id:
                    rows_v = db_query("SELECT * FROM versiculos WHERE id = ?", (ref_id,))
                    if rows_v:
                        r = rows_v[0]
                        letra_snap = f"{r['livro']} {r['capitulo']}:{r['versiculo']}\n\n{r['texto']}"
                        if titulo.startswith("Item"):
                            titulo = f"{r['livro']} {r['capitulo']}:{r['versiculo']}"

                itens = serv.setdefault("itens", [])
                if item_edit is not None and (item_edit.get("id") or 0):
                    item_id = item_edit.get("id")
                    idx = next((i for i, x in enumerate(itens)
                                if x.get("id") == item_id), None)
                    if idx is None:
                        return
                    original = dict(itens[idx])
                    itens[idx] = dict(original)
                    itens[idx].update({
                        "tipo": tipo,
                        "referencia_id": ref_id,
                        "titulo_custom": titulo,
                        "letra_snapshot": letra_snap,
                        "duracao_estimada_segundos": duracao,
                    })
                    novo_id = item_id
                else:
                    novo_id = dados["_proximo_id_item"]
                    dados["_proximo_id_item"] = novo_id + 1
                    original = None
                    itens.append({
                        "id": novo_id,
                        "tipo": tipo,
                        "referencia_id": ref_id,
                        "titulo_custom": titulo,
                        "letra_snapshot": letra_snap,
                        "duracao_estimada_segundos": duracao,
                    })
                if not _salvar_servicos_json(dados):
                    if original is not None:
                        itens[idx] = original
                    else:
                        serv["itens"] = [it for it in serv.get("itens")
                                         if it.get("id") != novo_id]
                        dados["_proximo_id_item"] = novo_id
                    tkinter.messagebox.showwarning(
                        "⚠️", "Não foi possível salvar em servicos.json.", parent=janela)
                    return
                _carregar_itens()
                tree.selection_set(str(novo_id))
                tree.focus(str(novo_id))
                add_win.destroy()

            tk.Button(add_main, text="💾 Salvar", font=("Arial", 12, "bold"),
                      bg='#238636', fg='white', activebackground='#2ea043',
                      command=_salvar_item, cursor='hand2', padx=20, pady=5
                      ).pack(pady=10)

        def _editar_item_selecionado():
            serv = _servico_atual()
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um item.", parent=janela)
                return
            if not serv:
                return
            it = next((x for x in (serv.get("itens") or [])
                       if x.get("id") == int(sel[0])), None)
            if it is None:
                return
            _abrir_editor_item(it)

        def _remover_item():
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um item.", parent=janela)
                return
            if not tkinter.messagebox.askyesno("Confirmar",
                    f"Remover {len(sel)} item(ns)?", parent=janela):
                return
            serv = _servico_atual()
            if not serv:
                return
            ids_remover = {int(i) for i in sel}
            serv["itens"] = [it for it in serv.get("itens", [])
                             if it.get("id") not in ids_remover]
            if not _salvar_servicos_json(dados):
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar a remoção em servicos.json.",
                    parent=janela)
                return
            _carregar_itens()

        def _mover_item(direcao: int):
            """Move item para cima (-1) ou baixo (+1)."""
            sel = tree.selection()
            if not sel:
                return
            serv = _servico_atual()
            if not serv:
                return
            itens = list(serv.get("itens") or [])
            idx_atual = next((i for i, it in enumerate(itens)
                              if it.get("id") == int(sel[0])), None)
            if idx_atual is None:
                return
            idx_novo = idx_atual + direcao
            if idx_novo < 0 or idx_novo >= len(itens):
                return
            itens[idx_atual], itens[idx_novo] = itens[idx_novo], itens[idx_atual]
            serv["itens"] = itens
            if not _salvar_servicos_json(dados):
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar a reordenação.", parent=janela)
                return
            _carregar_itens()
            tree.selection_set(str(itens[idx_novo].get("id")))
            tree.focus(str(itens[idx_novo].get("id")))

        # Snapshot da janela principal p/ restauração após cada item do
        # serviço (capturado uma única vez por sessão desta janela).
        snapshot_servico: dict = {"guardada": False}

        def _executar_servico():
            """Reproduz APENAS o próximo item da lista e para.

            A cada clique em "Executar Serviço" avança um item, independente
            do tipo (hino/vídeo/áudio/texto): reproduz/projeta só ele e fica
            aguardando o próximo clique. Não altera a playlist nem a opção de
            repetição da janela principal — o estado anterior é restaurado
            quando o item termina.
            """
            serv = _servico_atual()
            if not serv:
                return
            itens = list(serv.get("itens") or [])
            if not itens:
                tkinter.messagebox.showinfo("Vazio", "Serviço sem itens.", parent=janela)
                return
            chave = serv.get("id") or serv.get("nome") or "?"
            prox = _SERVICO_PROXIMO_ITEM.get(chave)
            if prox is None or prox < 0 or prox >= len(itens):
                prox = 0
            item = itens[prox]
            tipo = (item.get('tipo') or '').strip().lower()
            titulo_item = (item.get('titulo_custom') or '').strip()
            letra = (item.get('letra_snapshot') or '').strip()

            # Destaque do item em execução na lista da janela de serviço
            try:
                tree.selection_set(str(item.get('id')))
                tree.see(str(item.get('id')))
            except Exception:
                pass

            iniciado = False
            # Resolve o caminho de mídia do item: vídeo/áudio do item, ou a
            # mídia (vídeo/áudio) anexada a um anúncio.
            caminho_media = None
            if tipo in ('video', 'audio') and item.get('referencia_id'):
                try:
                    rows_m = db_query(
                        "SELECT caminho_arquivo FROM midia WHERE id = ? AND ativo = 1",
                        (item['referencia_id'],))
                    if rows_m:
                        caminho_media = rows_m[0].get('caminho_arquivo') or ''
                except Exception:
                    caminho_media = None
            elif tipo == 'anuncio' and item.get('referencia_id'):
                anun = _buscar_anuncio_por_ref(item['referencia_id'])
                if anun and (anun.get('tipo_midia') or '').strip().lower() in ('video', 'audio'):
                    caminho_media = (anun.get('arquivo_midia') or '')
            if caminho_media and os.path.exists(caminho_media):
                caminho = caminho_media
                # Snapshot da janela principal capturado UMA vez por
                # sessão (restaurado quando o item termina).
                if not snapshot_servico["guardada"]:
                    snapshot_servico["guardada"] = True
                    snapshot_servico["playlist"] = list(self.player.playlist or [])
                    snapshot_servico["index"] = self.player.index
                    snapshot_servico["arquivos"] = list(
                        getattr(self, 'arquivos_encontrados', []) or [])
                    snapshot_servico["atual"] = getattr(
                        self, 'arquivo_atual', None)

                def _fim_item_servico(estado: object = None):
                    # Restaura o handler e o estado anteriores ao item
                    self.player.on_state_change = self.quando_midia_terminar
                    if snapshot_servico["guardada"] and self.player.playlist == [caminho]:
                        snapshot_servico["guardada"] = False
                        self.player.playlist = snapshot_servico["playlist"]
                        self.player.index = snapshot_servico["index"]
                        self.arquivos_encontrados = snapshot_servico["arquivos"]
                        self.arquivo_atual = snapshot_servico["atual"]

                self.player.on_state_change = _fim_item_servico
                self.player.carregar_playlist([caminho])
                if self.player.tocar_indice(0):
                    iniciado = True
                else:
                    self.player.on_state_change = self.quando_midia_terminar

            if not iniciado:
                # Itens sem mídia (hino/anúncio/texto): projeta e para.
                if tipo == 'hino' and (titulo_item or letra):
                    self.player.telao.projetar_slides(
                        _montar_slides_letra(titulo_item, letra))
                    iniciado = True
                elif tipo == 'anuncio':
                    anun = _buscar_anuncio_por_ref(item.get('referencia_id'))
                    if anun:
                        if _projetar_anuncio_ordserv(self.player.telao, anun):
                            iniciado = True
                    else:
                        texto = letra or titulo_item
                        if texto:
                            self.player.telao.projetar_texto(texto)
                            iniciado = True
                else:
                    texto = letra or titulo_item
                    if texto:
                        self.player.telao.projetar_texto(texto)
                        iniciado = True

            if iniciado:
                _SERVICO_PROXIMO_ITEM[chave] = prox + 1
            else:
                tkinter.messagebox.showwarning(
                    "Executar", f"Não foi possível reproduzir o item {prox + 1}.",
                    parent=janela)

        tk.Button(btn_frame, text="➕ Novo Serviço", font=("Arial", 11, "bold"),
                  bg='#238636', fg='white', activebackground='#2ea043',
                  command=_novo_servico, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="✏️ Editar Serviço", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_editar_servico, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="🗑️ Excluir Serviço", font=("Arial", 11, "bold"),
                  bg='#da3633', fg='white', activebackground='#f85149',
                  command=_excluir_servico, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="➕ Ad. Item", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=lambda: _abrir_editor_item(), cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="✏️ Editar Item", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_editar_item_selecionado, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="🗑️ Remover", font=("Arial", 11, "bold"),
                  bg='#da3633', fg='white', activebackground='#f85149',
                  command=_remover_item, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="⬆️", font=("Arial", 11, "bold"),
                  bg='#21262d', fg='#f0c040', activebackground='#30363d',
                  command=lambda: _mover_item(-1), cursor='hand2', padx=8, pady=4
                  ).pack(side='left', padx=2)
        tk.Button(btn_frame, text="⬇️", font=("Arial", 11, "bold"),
                  bg='#21262d', fg='#f0c040', activebackground='#30363d',
                  command=lambda: _mover_item(1), cursor='hand2', padx=8, pady=4
                  ).pack(side='left', padx=2)
        tk.Button(btn_frame, text="▶️ Executar Serviço", font=("Arial", 11, "bold"),
                  bg='#6e40c9', fg='#f0c040', activebackground='#8b5cf6',
                  command=_executar_servico, cursor='hand2', padx=12, pady=4
                  ).pack(side='right', padx=3)

        # ── Navegação por teclado dos slides projetados (sem sair da janela) ──
        def _slide_anterior(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            telao.slide_anterior()
            return "break"

        def _slide_proximo(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            telao.slide_proximo()
            return "break"

        def _parar_projecao(event: object = None):
            if not getattr(self.player.telao, "mostrando_letra", False):
                return None
            self.player.telao.parar_projecao()
            return "break"

        janela.bind("<Left>", _slide_anterior)
        janela.bind("<Up>", _slide_anterior)
        janela.bind("<Right>", _slide_proximo)
        janela.bind("<Down>", _slide_proximo)
        janela.bind("<Escape>", _parar_projecao)
        self.root.bind("<Left>", _slide_anterior)
        self.root.bind("<Up>", _slide_anterior)
        self.root.bind("<Right>", _slide_proximo)
        self.root.bind("<Down>", _slide_proximo)
        self.root.bind("<Escape>", _parar_projecao)

        _carregar_servicos()
        # Se há serviços, seleciona o primeiro
        if combo_servico['values']:
            _on_servico_select()



    def _aplicar_temperatura(self, temp: str) -> None:
        """Aplica a temperatura carregada em background na interface."""
        self.temperatura_atual = temp
        print(f"🌡️ Temperatura carregada: {temp}")
        if self._temperatura_valida():
            self.player.telao._exibir_hora_inicial(temp)
            self.temp_label.config(
                text=f"🌡️ {self.cidade_salva}: {temp}"
            )
        else:
            self.temp_label.config(text="🌡️ Temperatura indisponível")
            self.temperatura_atual = "--"

    def _inicializar_em_segundo_plano(self) -> None:
        """Tarefas de inicialização que rodam após a interface aparecer."""
        # Registra no banco os arquivos de mídia da pasta uploads
        _sincronizar_uploads_midia()
        # Inicia servidor HTTP
        self._servidor_thread = ServidorAsyncHTTP()
        self._servidor_thread.iniciar()
        print(f"✅ Servidor async rodando em {BACKEND_URL}")
        
        # Carrega temperatura em thread separada (não bloqueia interface)
        if self.cidade_salva and self.estado_salvo:
            def _carregar_temp():
                temp = obter_temperatura(self.cidade_salva, self.estado_salvo)
                self.root.after(0, lambda: self._aplicar_temperatura(temp))
            threading.Thread(target=_carregar_temp, daemon=True).start()
        
        # Agenda atualização da temperatura a cada 30 minutos (timer cancelável)
        if hasattr(self, '_temp_timer') and self._temp_timer:
            self.root.after_cancel(self._temp_timer)
        self._temp_timer = self.root.after(1_800_000, self.atualizar_temperatura)

        # Verifica (em thread, silencioso) se há versão nova no GitHub
        self.root.after(SEGUNDOS_PARA_VERIFICAR_ATUALIZACAO * 1000,
                        lambda: self.verificar_atualizacao(manual=False))

    # ── Loop principal ────────────────────────────────────────────

    def run(self) -> None:
        """Inicia o loop principal da interface.

        O telão usa update_idletasks() (mais leve) a cada 500ms, mas
        só quando está no modo relógio. Quando o vídeo está tocando
        (mostrando_relogio=False), pula o ciclo desnecessário.
        """
        def _update_telao_lazy() -> None:
            if self.player and self.player.telao.rodando:
                # Só atualiza se o telão estiver no modo relógio
                # (quando vídeo está tocando, telão está oculto)
                if self.player.telao.mostrando_relogio:
                    self.player.telao.update()
            # Mantém o tema (claro/escuro) aplicado a janelas abertas depois
            self._varrer_toplevels_tema()
            self.root.after(500, _update_telao_lazy)

        _update_telao_lazy()
        self.root.mainloop()

    def fechar(self) -> None:
        """Encerra a aplicação com shutdown completo e ordenado."""
        # Flag para evitar que callbacks disparem durante shutdown
        self._shutting_down = True
        print("🛑 Encerrando NavePro...")
        try:
            # 1. Para a reprodução
            if self.player:
                self.player.stop()
                self.player.telao.fechar()
            # 2. Para o worker de busca
            if hasattr(self, 'search_worker'):
                self.search_worker.stop()
            # 3. Para o servidor HTTP
            if hasattr(self, '_servidor_thread') and self._servidor_thread:
                self._servidor_thread.parar()
            # 4. Libera recursos do banco
            if hasattr(self, 'db') and self.db:
                if self.db._conn:
                    try:
                        self.db._conn.close()
                    except Exception:
                        pass
                    self.db._conn = None
        except Exception as e:
            print(f"Erro no shutdown: {e}")
        finally:
            try:
                self.root.destroy()
            except tk.TclError:
                pass
        print("✅ NavePro encerrado com sucesso.")


# ────────────────────────────────────────────────────────────────────
# PONTO DE ENTRADA
# ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🎵 NavePro - Iniciando...")
    app = AppInterface()
    app.run()