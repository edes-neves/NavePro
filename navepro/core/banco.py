"""Camada de banco de dados (SQLite) com cache em memória.

Contém o singleton `DatabaseManager` (conexão persistente serializada com RLock,
cache de mídia em memória e busca com LRU), as funções legadas `db_query` /
`db_execute` e o reuso de IDs (preencher lacunas do AUTOINCREMENT sem colidir
com itens de Ordem de Serviço). Extraído de NavePro.py sem alteração de
comportamento.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Iterator
from typing import Any

from navepro.config import CACHE_LRU_MAXSIZE, SQLITE_TIMEOUT
from navepro.core.log import get_logger
from navepro.core.paths import DB_PATH
from navepro.core.textos import normalizar_texto

log = get_logger("banco")


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
        with DatabaseManager._lock:
            if self._initialized:
                return
            self._initialized = True
            self._conn: sqlite3.Connection | None = None
            # A MESMA conexão é usada pela thread do Tk e pela do servidor HTTP
            # (e pelo worker de busca). Com check_same_thread=False, serializamos
            # todo acesso a ela — sem isso dois `execute` concorrentes podem se
            # entrelaçar no commit ou na criação preguiçosa da conexão.
            self._conn_lock = threading.RLock()
            self._cache: list[dict[str, Any]] = []
            self._cache_loaded: bool = False
            # `search` roda na thread do worker de busca E na do Tk (via controle
            # remoto): a troca de _cache e o LRU de _result_cache precisam ser
            # atômicos, então tudo isso fica sob este lock.
            self._cache_lock = threading.RLock()
            self._result_cache: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
            self._load_cache()

    def _connect(self) -> sqlite3.Connection:
        """Retorna uma conexão persistente (cria se não existir)."""
        with self._conn_lock:
            if self._conn is None:
                self._conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT,
                                             check_same_thread=False)
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=NORMAL")
            return self._conn

    def _load_cache(self) -> None:
        """Carrega todos os registros ativos em memória com seus campos normalizados."""
        carregado = False
        nova: list[dict[str, Any]] = []
        try:
            with self._conn_lock:
                conn = self._connect()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, nome_exibicao, nome_original, caminho_arquivo, tipo
                    FROM midia
                    WHERE ativo = 1
                """)
                rows = cursor.fetchall()
            # Verifica existência dos arquivos em lote (reduz chamadas stat)
            # FORA do lock da conexão: I/O de disco não deve segurá-la.
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
                nova.append(record)
            carregado = True
        except Exception as e:
            log.exception(f"Erro ao carregar cache: {e}")
            nova = []
            carregado = False
        # Troca atômica: quem lê _cache vê o conjunto antigo ou o novo, nunca
        # um cache pela metade. Invalida o LRU de buscas (senão um resultado
        # antigo sobrevive a um upload/remoção de mídia).
        with self._cache_lock:
            self._cache = nova
            self._cache_loaded = carregado
            self._result_cache.clear()

    @staticmethod
    def _compute_sort_key(nome: str) -> tuple[int, int, str]:
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

    def search(self, term: str) -> list[dict[str, Any]]:
        """Busca síncrona em memória usando normalização com cache LRU."""
        with self._cache_lock:
            if not self._cache_loaded or not term:
                return []
            term_norm = normalizar_texto(term)
            if not term_norm:
                return []

            # Verifica cache LRU (usa term_norm como chave para consistência)
            if term_norm in self._result_cache:
                self._result_cache.move_to_end(term_norm)
                return self._result_cache[term_norm]

            results: list[dict[str, Any]] = []

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

    def get_all_ids(self) -> list[int]:
        """Retorna todos os IDs em cache."""
        return [rec['id'] for rec in self._cache]

    def get_by_id(self, midia_id: int) -> dict[str, Any] | None:
        """Retorna um registro pelo ID."""
        for rec in self._cache:
            if rec['id'] == midia_id:
                return rec
        return None

    def get_path_by_id(self, midia_id: int) -> str | None:
        """Retorna o caminho do arquivo pelo ID."""
        rec = self.get_by_id(midia_id)
        return rec['caminho_arquivo'] if rec else None

    # Métodos para operações de banco (INSERT/UPDATE/DELETE) – usam conexão persistente
    def execute(self, query: str, params: tuple = ()) -> int | None:
        """Executa INSERT/UPDATE/DELETE e retorna lastrowid."""
        with self._conn_lock:
            conn = self._connect()
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.lastrowid

    def query(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Executa SELECT e retorna lista de dicionários."""
        with self._conn_lock:
            conn = self._connect()
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

# ────────────────────────────────────────────────────────────────────
# FUNÇÕES DE BANCO LEGADAS (PARA COMPATIBILIDADE COM API E GERENCIADOR)
# ────────────────────────────────────────────────────────────────────

# As funções db_query e db_execute delegam ao DatabaseManager (singleton), que
# serializa o acesso à conexão persistente compartilhada com um RLock — assim a
# thread do Tk e a do servidor HTTP podem consultar o banco sem se atropelar.


def db_query(query: str, params: tuple = ()) -> list[dict]:
    """Executa SELECT usando DatabaseManager (singleton)."""
    return DatabaseManager().query(query, params)

def db_execute(query: str, params: tuple = ()) -> int | None:
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


def _proximo_id_livre(tabela: str) -> int | None:
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
