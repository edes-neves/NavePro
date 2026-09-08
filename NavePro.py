"""
NavePro - Sistema de Projeção para Igrejas
Versão: 1.8.0
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
from typing import Any, Callable, Optional, List, Dict, Tuple
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

APP_VERSION: str = "1.9.0"
CONFIG_FILE: str = "config.json"  # Será redefinido abaixo em UTILITÁRIOS DE CAMINHO
PLAYER_PADRAO: str = "smplayer"
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


def _procurar_asset_appimage(release: dict) -> Optional[dict]:
    """Encontra o primeiro asset .AppImage do release."""
    for asset in release.get('assets', []) or []:
        nome = str(asset.get('name', '')).lower()
        if nome.endswith('.appimage'):
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
        try:
            icon_path = _caminho_recurso("Icon.xbm")
            if os.path.exists(icon_path):
                self.root.wm_iconbitmap("@" + icon_path)
        except Exception:
            pass

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
        self.root.geometry(geometry)
        self.root.configure(bg='black')
        self.root.attributes('-alpha', 0.55)
        self.root.attributes('-topmost', False)
        self._fullscreen: bool = True
        self.root.attributes('-fullscreen', True)
        self.root.lift()
        # Só reafirma a geometria no modo tela cheia; no modo janela o
        # gerenciador de janelas controla livremente (min/max/redimensionar).
        self.root.bind("<Configure>", self._reafirmar_geometria)

        # Cache de estado: evita chamadas repetidas à Tk
        self._current_alpha: float = 0.55
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
            self._cx, self._cy_hora, text="", fill="#F5BE08", anchor="center",
            font=self._font_hora
        )
        # Texto da temperatura
        self.temp_text = self.canvas.create_text(
            self._cx, self._cy_temp, text="", fill="#F5BE08", anchor="center",
            font=self._font_temp
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
        self._slides: list = []
        self._slide_index = 0
        self._proj_cfg: dict = {
            "fonte": "Montserrat",
            "tamanho_pct": 5.0,
            "cor": "#FFFFFF",
            "duracao_seg": 30,
        }
        self._proj_timer = None
        self._temp_salvo = ""
        self.root.protocol("WM_DELETE_WINDOW", self.fechar)
        # Aplica alpha imediatamente
        self.root.attributes('-alpha', 0.55)
        # Exibe hora inicial
        self._exibir_hora_inicial()

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
        margem_lateral = max(16, int(largura * 0.05))
        gap = max(10, int(altura * 0.015))
        hora_px = int(altura * 0.48)
        temp_px = max(24, int(altura * 0.28))
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
        if self._current_alpha != 0.55:
            self.root.attributes('-alpha', 0.55)
            self._current_alpha = 0.55

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

        self._current_alpha = 0.55
        self._is_visible = True
        self.mostrando_relogio = True
        # Reseta cache de hora para forçar redesenho do relógio
        self._current_text = ""
        self._current_temp = ""

        self.root.deiconify()
        self.root.attributes('-alpha', 0.55)
        self.root.lower()

    # ── Projeção de texto (letra / versículo) ─────────────────────

    def configurar_projecao(self, cfg: Optional[dict] = None) -> None:
        """Define as configurações de aparência da projeção de texto."""
        defaults = {
            "fonte": "Montserrat",
            "tamanho_pct": 5.0,
            "cor": "#FFFFFF",
            "duracao_seg": 30,
        }
        merged = dict(defaults)
        if isinstance(cfg, dict):
            for k, v in cfg.items():
                if k in defaults and v not in (None, ""):
                    merged[k] = v
        self._proj_cfg = merged

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

        self.mostrando_letra = True
        self._em_slides = False
        self.mostrando_relogio = False

        # Exibe a janela e opaca
        if not self._is_visible:
            self.root.deiconify()
            self._is_visible = True
        if self._current_alpha != 1.0:
            self.root.attributes('-alpha', 1.0)
            self._current_alpha = 1.0
        self.root.lift()

        # Esconde temperatura
        self.canvas.itemconfig(self.temp_text, text="", state="hidden")

        # Monta o texto final (título em destaque + letra)
        texto_final = f"{titulo}\n\n{texto}" if titulo else texto
        self._desenhar_texto_no_canvas(texto_final)

        # Agenda retorno automático do relógio + temperatura
        seg = max(1, int(float(cfg.get("duracao_seg", 30))))
        self._proj_timer = self.root.after(seg * 1000, self._retornar_ao_relogio)

    def _desenhar_texto_no_canvas(self, texto: str) -> tuple:
        """Desenha texto centralizado no canvas com auto-ajuste de fonte.

        Usado tanto na projeção simples (projetar_texto) quanto nos slides.
        Retorna a tupla de fonte aplicada.
        """
        cfg = getattr(self, "_proj_cfg", None)
        if cfg is None:
            self.configurar_projecao()

        # Calcula largura de quebra e fonte inicial
        w = self.canvas.winfo_width() or self._monitor.width
        h = self.canvas.winfo_height() or self._monitor.height
        wrap_width = max(200, int(w * 0.95))
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
        self.canvas.coords(self.overlay_text, w // 2, h // 2)
        self.root.update_idletasks()
        return fonte

    # ── Projeção em slides (título + versos, navegação do administrador) ──

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

        self._slides = list(slides)
        self._slide_index = 0
        self._em_slides = True
        self.mostrando_letra = True
        self.mostrando_relogio = False

        # Exibe a janela e opaca
        if not self._is_visible:
            self.root.deiconify()
            self._is_visible = True
        if self._current_alpha != 1.0:
            self.root.attributes('-alpha', 1.0)
            self._current_alpha = 1.0
        self.root.lift()

        # Esconde temperatura
        self.canvas.itemconfig(self.temp_text, text="", state="hidden")

        self._mostrar_slide(max(0, min(indice_inicial, len(self._slides) - 1)))

    def _mostrar_slide(self, indice: int) -> bool:
        """Exibe o slide no índice dado (se válido) e retorna True."""
        if not self._slides:
            return False
        if indice < 0 or indice >= len(self._slides):
            return False
        self._slide_index = indice
        self._desenhar_texto_no_canvas(self._slides[indice])
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
        # Restaura a aparência padrão do relógio no canvas: fonte Digital-7,
        # cor, e posições originais de hora e temperatura (a projeção troca a
        # fonte e move o texto para o centro da tela).
        self.canvas.itemconfig(self.overlay_text, fill="#F5BE08", width=0,
                               font=self._font_hora)
        self.canvas.itemconfig(self.temp_text, fill="#F5BE08", width=0,
                               font=self._font_temp)
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
            proc = subprocess.Popen(
                cmd, start_new_session=True, env=_ambiente_sem_appimage()
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
                print("   \u274c Nenhum player encontrado! Usando xdg-open")
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
        """Pausa/continua via D-Bus ou SIGSTOP/SIGCONT (fallback)."""
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
        if not self.is_playing:
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
    dial.geometry("560x430")
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
        try:
            icon_path = _caminho_recurso("Icon.xbm")
            if os.path.exists(icon_path):
                self.root.wm_iconbitmap("@" + icon_path)
        except Exception:
            pass
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

        self._criar_menu()
        self.criar_widgets()
        self.atualizar_relogio()

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

    def abrir_config_projecao_dialogo(self, parent=None) -> None:
        """Abre a janela de ajuste da aparência da projeção no telão.

        Compartilhada entre as janelas de Hinos e de Bíblia.
        """
        janela = parent or self.root
        cfg_atual = dict(getattr(self.player.telao, "_proj_cfg", {}))
        cfg_atual.setdefault("fonte", "Montserrat")
        cfg_atual.setdefault("tamanho_pct", 5.0)
        cfg_atual.setdefault("cor", "#FFFFFF")
        cfg_atual.setdefault("duracao_seg", 30)

        cfg_win = tk.Toplevel(janela)
        cfg_win.title("🎨 Aparência da Projeção (Telão)")
        cfg_win.geometry("520x420")
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
            ("Verde", "#3FB950"), ("Roxo", "#D2A8FF")]
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
                duracao = 30
            novo = {
                "fonte": var_fonte.get(),
                "tamanho_pct": float(var_tamanho.get()),
                "cor": var_cor.get(),
                "duracao_seg": duracao,
            }
            self.salvar_config_projecao(novo)
            cfg_win.destroy()

        tk.Button(c_main, text="💾 Salvar", font=("Arial", 12, "bold"),
                  bg='#238636', fg='white', activebackground='#2ea043',
                  command=_salvar_cfg, cursor='hand2', padx=20, pady=5
                  ).pack(pady=6)

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

        self.root.config(menu=menubar)

    def _toggle_repetir(self) -> None:
        """Alterna o estado do checkbox Repetir."""
        self.repetir_var.set(not self.repetir_var.get())

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
        mensagem = (
            f"NavePro {APP_VERSION} → {versao}\n\n"
            "Uma nova versão está disponível no GitHub.\n"
        )
        if corpo:
            mensagem += f"\nNovidades:\n{corpo}\n"
        mensagem += "\nDeseja baixar o novo AppImage agora?"
        if not tkinter.messagebox.askyesno(
                "🔄 Atualização disponível", mensagem, parent=self.root):
            return
        asset = _procurar_asset_appimage(release)
        if asset is None:
            tkinter.messagebox.showwarning(
                "Atualização",
                "O release não contém um arquivo .AppImage.",
                parent=self.root)
            return
        self._baixar_atualizacao(
            versao,
            str(asset.get('browser_download_url', '')),
            str(asset.get('name', f'NavePro-{versao}.AppImage')),
        )

    def _baixar_atualizacao(self, versao: str, url: str,
                            nome_arquivo: str) -> None:
        """Baixa o novo AppImage para ~/Downloads com barra de progresso."""
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
                    os.chmod(destino, 0o744)
                    self.root.after(0, lambda: self._instrucoes_troca_appimage(
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

    def _instrucoes_troca_appimage(self, destino: str) -> None:
        """Mostra como substituir o AppImage antigo pelo baixado e abre Downloads."""
        tkinter.messagebox.showinfo(
            "✅ Download concluído",
            "O novo AppImage foi salvo em:\n\n"
            f"  {destino}\n\n"
            "Para instalar:\n"
            "1. Feche o NavePro.\n"
            "2. Substitua o AppImage atual por este novo arquivo "
            "(mova-o para o mesmo lugar do antigo).\n"
            "3. Dê permissão de execução se precisar:\n"
            "     chmod +x \"<novo arquivo>\"\n"
            "4. Abra o novo arquivo para rodar a versão atualizada.",
            parent=self.root)
        try:
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

        def _criar_botao_pill(parent, icone, tooltip, comando):
            btn = tk.Button(
                parent, text=icone,
                font=("Arial", 18),
                bg='#21262d', fg='#f0c040', activebackground='#6e40c9',
                activeforeground='#f0c040',
                command=comando, cursor='hand2',
                bd=0, highlightthickness=0,
                padx=14, pady=6
            )
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

        # Botão Gerenciar Banco (também em estilo pill)
        btn_gerenciar = tk.Button(
            controls_frame, text="📦",
            font=("Arial", 16),
            bg='#21262d', fg='#f0c040', activebackground='#6e40c9',
            command=self.abrir_gerenciador, cursor='hand2',
            bd=0, highlightthickness=0,
            padx=14, pady=6
        )
        btn_gerenciar.pack(side='right', padx=5)
        _criar_tooltip(btn_gerenciar, "Gerenciar Banco")

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

        entry_busca.bind("<Return>", _buscar)
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

                db_execute(
                    "INSERT INTO letras (titulo, artista, compositor, ccli_numero, "
                    "categoria, letra_completa) VALUES (?, ?, '', '', '', ?)",
                    (titulo, dados["artista"], dados["letra_completa"]))
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
                    db_execute(
                        "INSERT INTO letras (titulo, artista, compositor, ccli_numero, "
                        "categoria, letra_completa) VALUES (?, ?, ?, ?, ?, ?)",
                        (titulo, artista, compositor, ccli, categoria, letra))
                _carregar_hinos()
                editar_win.destroy()

            tk.Button(e_main, text="💾 Salvar", font=("Arial", 12, "bold"),
                      bg='#238636', fg='white', activebackground='#2ea043',
                      command=_salvar, cursor='hand2', padx=20, pady=5
                      ).pack(pady=10)

        _carregar_hinos()

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
            termo = entry_busca_texto.get().strip()
            if not termo or termo == "Buscar versículo por texto...":
                return
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

        entry_busca_texto.bind("<Return>", lambda e: _buscar_versiculos_texto())

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
                        conn.executemany(
                            "INSERT INTO versiculos "
                            "(versao, livro, capitulo, versiculo, texto) "
                            "VALUES (?, ?, ?, ?, ?)", novos)
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
                  command=lambda: self.abrir_config_projecao_dialogo(janela),
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
            slides = [r['texto'] for r in rows]
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
        """Abre a janela de planejamento de ordem de serviço."""
        janela = tk.Toplevel(self.root)
        janela.title("📋 Ordem de Serviço")
        janela.geometry("850x750")
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
        itens_servico = []

        def _carregar_servicos():
            rows = db_query(
                "SELECT id, nome, data_servico FROM servicos WHERE ativo = 1 "
                "ORDER BY data_servico DESC, nome")
            opcoes = [f"{r['id']} - {r['nome']} ({r['data_servico'] or 'sem data'})"
                      for r in rows]
            combo_servico['values'] = opcoes
            combo_servico._servico_ids = [r['id'] for r in rows]
            if opcoes:
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

        def _carregar_itens():
            nonlocal itens_servico
            for item in tree.get_children():
                tree.delete(item)
            sid = servico_selecionado_id[0]
            if not sid:
                return
            itens_servico = db_query(
                "SELECT * FROM itens_servico WHERE servico_id = ? ORDER BY ordem",
                (sid,))
            for i, it in enumerate(itens_servico):
                tipo_emoji = {"hino": "📖", "versiculo": "✝️", "video": "🎬",
                              "audio": "🎵", "slide": "📄", "anuncio": "📢",
                              "sermao": "🎤"}.get(it['tipo'], "📁")
                tree.insert("", tk.END, iid=str(it['id']),
                            values=(i + 1, f"{tipo_emoji} {it['tipo'].title()}",
                                    it['titulo_custom'] or f"Item {i+1}",
                                    it['duracao_estimada_segundos']))

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
            data = datetime.now().strftime("%Y-%m-%d")
            db_execute(
                "INSERT INTO servicos (nome, data_servico) VALUES (?, ?)",
                (nome, data))
            _carregar_servicos()

        def _adicionar_item_servico():
            sid = servico_selecionado_id[0]
            if not sid:
                tkinter.messagebox.showwarning("Seleção", "Selecione ou crie um serviço.", parent=janela)
                return
            # Janela para adicionar item
            add_win = tk.Toplevel(janela)
            add_win.title("Adicionar Item")
            add_win.geometry("450x300")
            add_win.configure(bg='#0d1117')
            add_win.transient(janela)
            add_win.after(50, add_win.grab_set)

            add_main = tk.Frame(add_win, bg='#0d1117')
            add_main.pack(fill='both', expand=True, padx=15, pady=15)

            tk.Label(add_main, text="Tipo:", fg='#f0c040', bg='#0d1117',
                     font=("Arial", 11, "bold")).pack(anchor='w')
            tipo_var = tk.StringVar(value="hino")
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
            titulo_entry.pack(fill='x', ipady=3, pady=2)

            tk.Label(add_main, text="Referência ID (hino/versículo/mídia):", fg='#8b949e',
                     bg='#0d1117', font=("Arial", 9)).pack(anchor='w')
            ref_entry = tk.Entry(add_main, font=("Arial", 11), bg='#21262d',
                                 fg='#c9d1d9', insertbackground='#f0c040')
            ref_entry.pack(fill='x', ipady=3, pady=2)

            tk.Label(add_main, text="Duração estimada (segundos):", fg='#8b949e',
                     bg='#0d1117', font=("Arial", 9)).pack(anchor='w')
            dur_entry = tk.Entry(add_main, font=("Arial", 11), bg='#21262d',
                                 fg='#c9d1d9', insertbackground='#f0c040')
            dur_entry.pack(fill='x', ipady=3, pady=2)
            dur_entry.insert(0, "0")

            def _salvar_item():
                tipo = tipo_var.get()
                titulo = titulo_entry.get().strip() or f"Item ({tipo.title()})"
                ref_id = int(ref_entry.get().strip()) if ref_entry.get().strip().isdigit() else None
                duracao = int(dur_entry.get().strip()) if dur_entry.get().strip().isdigit() else 0
                # Pega a maior ordem atual
                max_ord = db_query(
                    "SELECT COALESCE(MAX(ordem), 0) as maxo FROM itens_servico WHERE servico_id = ?",
                    (sid,))
                nova_ordem = (max_ord[0]['maxo'] if max_ord else 0) + 1

                # Se hino ou versículo, busca a letra automaticamente
                letra_snap = ""
                if tipo == "hino" and ref_id:
                    rows_l = db_query("SELECT letra_completa, titulo FROM letras WHERE id = ?", (ref_id,))
                    if rows_l:
                        letra_snap = rows_l[0].get('letra_completa', '')
                        if not titulo or titulo.startswith("Item"):
                            titulo = rows_l[0].get('titulo', titulo)
                elif tipo == "versiculo" and ref_id:
                    rows_v = db_query("SELECT * FROM versiculos WHERE id = ?", (ref_id,))
                    if rows_v:
                        r = rows_v[0]
                        letra_snap = f"{r['livro']} {r['capitulo']}:{r['versiculo']}\n\n{r['texto']}"
                        if not titulo or titulo.startswith("Item"):
                            titulo = f"{r['livro']} {r['capitulo']}:{r['versiculo']}"

                db_execute(
                    "INSERT INTO itens_servico (servico_id, ordem, tipo, referencia_id, "
                    "titulo_custom, letra_snapshot, duracao_estimada_segundos) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (sid, nova_ordem, tipo, ref_id, titulo, letra_snap, duracao))
                _carregar_itens()
                add_win.destroy()

            tk.Button(add_main, text="💾 Salvar", font=("Arial", 12, "bold"),
                      bg='#238636', fg='white', activebackground='#2ea043',
                      command=_salvar_item, cursor='hand2', padx=20, pady=5
                      ).pack(pady=10)

        def _remover_item():
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um item.", parent=janela)
                return
            if not tkinter.messagebox.askyesno("Confirmar",
                    f"Remover {len(sel)} item(s)?", parent=janela):
                return
            for item_id in sel:
                db_execute("DELETE FROM itens_servico WHERE id = ?", (int(item_id),))
            _carregar_itens()

        def _mover_item(direcao: int):
            """Move item para cima (-1) ou baixo (+1)."""
            sel = tree.selection()
            if not sel:
                return
            item_id = int(sel[0])
            item_atual = db_query("SELECT * FROM itens_servico WHERE id = ?", (item_id,))
            if not item_atual:
                return
            item = item_atual[0]
            nova_ordem = item['ordem'] + direcao
            if nova_ordem < 1:
                return
            # Troca com o item que está na nova posição
            vizinho = db_query(
                "SELECT * FROM itens_servico WHERE servico_id = ? AND ordem = ?",
                (item['servico_id'], nova_ordem))
            if vizinho:
                db_execute("UPDATE itens_servico SET ordem = ? WHERE id = ?",
                           (nova_ordem, item_id))
                db_execute("UPDATE itens_servico SET ordem = ? WHERE id = ?",
                           (item['ordem'], vizinho[0]['id']))
            _carregar_itens()

        def _executar_servico():
            """Carrega os itens do serviço na playlist e toca o primeiro."""
            sid = servico_selecionado_id[0]
            if not sid:
                return
            itens = db_query(
                "SELECT * FROM itens_servico WHERE servico_id = ? ORDER BY ordem",
                (sid,))
            if not itens:
                tkinter.messagebox.showinfo("Vazio", "Serviço sem itens.", parent=janela)
                return
            # Coleta arquivos de mídia referenciados
            arquivos = []
            for it in itens:
                if it['tipo'] in ('video', 'audio') and it['referencia_id']:
                    rows_m = db_query(
                        "SELECT caminho_arquivo FROM midia WHERE id = ? AND ativo = 1",
                        (it['referencia_id'],))
                    if rows_m and os.path.exists(rows_m[0]['caminho_arquivo']):
                        arquivos.append(rows_m[0]['caminho_arquivo'])
            if arquivos:
                self.arquivos_encontrados = arquivos
                self.player.carregar_playlist(arquivos)
                self.player.tocar_indice(0)
                self.atualizar_lista()
            else:
                # Se só hinos/versículos, exibe o primeiro item no telão
                primeiro = itens[0]
                texto = primeiro.get('letra_snapshot', '') or primeiro.get('titulo_custom', '')
                if texto:
                    self.player.telao.projetar_texto(texto)

        tk.Button(btn_frame, text="➕ Novo Serviço", font=("Arial", 11, "bold"),
                  bg='#238636', fg='white', activebackground='#2ea043',
                  command=_novo_servico, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="➕ Adicionar Item", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_adicionar_item_servico, cursor='hand2', padx=12, pady=4
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