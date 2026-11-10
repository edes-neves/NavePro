"""Inicialização do banco e recursos (uploads/config).

Extraído de NavePro.py sem alterar o comportamento (ver AGENTS.md).
"""

import datetime
import mimetypes
import os
import shutil
import sqlite3
import sys
import tkinter as tk
import tkinter.filedialog
import tkinter.messagebox

from navepro.core.banco import DatabaseManager, db_execute, db_query
from navepro.core.log import get_logger
from navepro.core.paths import (
    CONFIG_FILE,
    DATA_USER_DIR,
    DB_EMBUTIDO,
    DB_PATH,
    DIR_BASE,
    SERVICOS_FILE,
    UPLOAD_FOLDER,
    UPLOADS_EMBUTIDO,
    _caminho_recurso,
)
from navepro.core.textos import detectar_tipo_arquivo

log = get_logger("inicializacao")

# Versão do esquema do banco, gravada em `PRAGMA user_version`. Suba este
# número ao adicionar um novo degrau de migração em `init_db` (e some o
# degrau correspondente lá embaixo, numerado). Bancos anteriores a este
# controle ficam na versão 0 e recebem todos os degraus de uma vez — cada
# degrau confere o estado real antes de agir, então reaplicar é inócuo.
SCHEMA_VERSION = 2

# Quantas cópias diárias de cada arquivo o backup de segurança mantém.
_MAX_BACKUPS_DIARIOS = 30


def init_db() -> None:
    """Cria a estrutura do banco de dados se não existir."""
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Banco corrompido (ou arquivo que nem é SQLite) não pode derrubar o
    # app: preserva o arquivo renomeado e recomeça, em vez de não abrir.
    try:
        estado = cursor.execute("PRAGMA quick_check").fetchone()
        integro = (estado is not None and estado[0] is not None
                   and str(estado[0]).lower() == "ok")
    except sqlite3.DatabaseError:
        integro = False
    if not integro:
        conn.close()
        backup = (DB_PATH + ".corrompido-"
                  + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        try:
            os.replace(DB_PATH, backup)
        except OSError:
            backup = ""
        log.error(
            f"⚠️ Banco de dados corrompido — preservado em {backup or DB_PATH}. "
            "Os dados anteriores NÃO foram apagados; recupere o arquivo "
            "preservado e importe o que for preciso.")
        if os.path.exists(DB_EMBUTIDO):
            # O bundle trouxe banco embutido (biblioteca pronta): restaura
            # dele em vez de começar totalmente vazio.
            shutil.copy2(DB_EMBUTIDO, DB_PATH)
            log.error("📦 Banco recriado a partir do banco embutido.")
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

    # ── Busca textual (FTS5) ───────────────────────────────────────
    # Índice invertido opcional para hinos, versículos e mídias. Se o
    # SQLite da distribuição não trouxer o módulo FTS5, o `try` falha e o
    # app continua com as buscas LIKE (as funções de busca têm fallback).
    # Criado ANTES das migrações para não depender do estado de `anuncios`.
    try:
        _fts_tabelas = (
            ("letras_fts", "letras", ("titulo", "artista", "letra_completa")),
            ("versiculos_fts", "versiculos", ("texto",)),
            ("midia_fts", "midia", ("nome_exibicao", "nome_original")),
        )
        for nome_fts, tabela, colunas in _fts_tabelas:
            existia = cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (nome_fts,)).fetchone()
            cursor.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {nome_fts} USING fts5("
                + ", ".join(colunas)
                + f", content='{tabela}', content_rowid='id', "
                  "tokenize='unicode61 remove_diacritics 2')")
            if not existia:
                # Primeira criação: indexa o conteúdo já existente.
                cursor.execute(
                    f"INSERT INTO {nome_fts}({nome_fts}) VALUES('rebuild')")
            lista_cols = ", ".join(colunas)
            novos = ", ".join(
                f"COALESCE(new.{c}, '')" for c in colunas)
            antigos = ", ".join(
                f"COALESCE(old.{c}, '')" for c in colunas)
            cursor.execute(
                f"CREATE TRIGGER IF NOT EXISTS {tabela}_ai "
                f"AFTER INSERT ON {tabela} BEGIN "
                f"INSERT INTO {nome_fts}(rowid, {lista_cols}) "
                f"VALUES (new.id, {novos}); END")
            cursor.execute(
                f"CREATE TRIGGER IF NOT EXISTS {tabela}_ad "
                f"AFTER DELETE ON {tabela} BEGIN "
                f"INSERT INTO {nome_fts}({nome_fts}, rowid, {lista_cols}) "
                f"VALUES ('delete', old.id, {antigos}); END")
            cursor.execute(
                f"CREATE TRIGGER IF NOT EXISTS {tabela}_au "
                f"AFTER UPDATE ON {tabela} BEGIN "
                f"INSERT INTO {nome_fts}({nome_fts}, rowid, {lista_cols}) "
                f"VALUES ('delete', old.id, {antigos}); "
                f"INSERT INTO {nome_fts}(rowid, {lista_cols}) "
                f"VALUES (new.id, {novos}); END")
    except sqlite3.OperationalError as e:
        log.info(f"ℹ️ FTS5 indisponível; buscas usam LIKE: {e}")

    # Garante o esquema base ANTES de migrar: se uma migração falhar, o
    # rollback dela não desfaz a criação das tabelas.
    conn.commit()

    # ── Migrações versionadas (PRAGMA user_version) ────────────────
    # Cada degrau só roda se a versão gravada for menor que a dele, e
    # ainda confere o estado real do banco antes de agir (idempotente):
    # reaplicar num banco já migrado não faz nada.
    versao = cursor.execute("PRAGMA user_version").fetchone()[0]
    migracao_ok = True

    # Transação explícita: o driver sqlite3 roda DDL em autocommit, então sem
    # este BEGIN um DROP/CREATE ficaria gravado mesmo se o INSERT seguinte
    # falhasse. Assim, uma migração ou aplica tudo, ou é desfeita inteira.
    cursor.execute("BEGIN")

    # v1 — anuncios: remover AUTOINCREMENT (IDs passam a reaproveitar).
    if versao < 1:
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
                    vals = dict(zip(colunas, row, strict=False))
                    placeholders = ", ".join("?" for _ in vals)
                    cols = ", ".join(vals.keys())
                    cursor.execute(
                        f"INSERT INTO anuncios ({cols}) VALUES ({placeholders})",
                        tuple(vals.values()),
                    )
                cursor.execute("DROP TABLE IF EXISTS _anuncios_backup_old_ai")
                log.info("✅ Migração v1: anuncios sem AUTOINCREMENT (IDs reaproveitam).")
        except Exception as e:
            migracao_ok = False
            log.warning(f"⚠️ Migração v1 (AUTOINCREMENT) falhou, será retentada: {e}")

    # v2 — anuncios: garantir a coluna config_midia (aditiva e idempotente).
    if versao < 2:
        try:
            colunas_existentes = {desc[1] for desc in cursor.execute(
                "PRAGMA table_info(anuncios)").fetchall()}
            if colunas_existentes and 'config_midia' not in colunas_existentes:
                cursor.execute("ALTER TABLE anuncios ADD COLUMN config_midia TEXT DEFAULT ''")
                log.info("✅ Migração v2: coluna 'config_midia' adicionada.")
        except Exception as e:
            migracao_ok = False
            log.warning(f"⚠️ Migração v2 (config_midia) falhou, será retentada: {e}")

    # Só marca como migrado se nenhum degrau falhou; senão, desfaz o que a
    # migração mexeu (inclusive um DROP parcial) e tenta de novo no próximo
    # início — os degraus são idempotentes, então repetir é seguro.
    if migracao_ok:
        if versao < SCHEMA_VERSION:
            cursor.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")
        conn.commit()
    else:
        conn.rollback()
    conn.close()


def inicializar_banco() -> None:
    """Copia banco embutido se necessário e inicializa."""
    if not os.path.exists(DB_PATH):
        if os.path.exists(DB_EMBUTIDO):
            log.info(f"📦 Copiando banco embutido para {DB_PATH}")
            shutil.copy2(DB_EMBUTIDO, DB_PATH)
        else:
            log.info(f"📦 Banco não encontrado, criando novo em {DB_PATH}")
    init_db()


def criar_backup_diario() -> None:
    """Backup leve e diário de midia.db e servicos.json (rede de proteção).

    Roda no início do app, antes de qualquer migração: se os dados forem
    corrompidos ou apagados por engano, a cópia do dia anterior continua em
    ~/.navepro/backups/. Mantém no máximo _MAX_BACKUPS_DIARIOS por arquivo.
    """
    try:
        pasta = os.path.join(DATA_USER_DIR, "backups")
        os.makedirs(pasta, exist_ok=True)
        hoje = datetime.date.today().isoformat()
        for origem in (DB_PATH, SERVICOS_FILE):
            if not os.path.isfile(origem):
                continue
            nome = os.path.basename(origem)
            destino = os.path.join(pasta, f"{hoje}_{nome}")
            if not os.path.exists(destino):
                shutil.copy2(origem, destino)
                log.info(f"🛡️ Backup diário criado: {destino}")
            try:
                copias = sorted(
                    (e.path for e in os.scandir(pasta)
                     if e.is_file() and e.name.endswith("_" + nome)),
                    reverse=True)
            except OSError:
                continue
            for velha in copias[_MAX_BACKUPS_DIARIOS:]:
                try:
                    os.unlink(velha)
                except OSError:
                    pass
    except OSError as e:
        log.warning(f"⚠️ Não foi possível criar o backup diário: {e}")


def inicializar_config() -> None:
    """Copia config embutido para ~/.navepro/ se necessário."""
    config_embutido = _caminho_recurso("config.json")
    if not os.path.exists(CONFIG_FILE) and os.path.exists(config_embutido):
        log.info(f"📦 Copiando config embutido para {CONFIG_FILE}")
        shutil.copy2(config_embutido, CONFIG_FILE)
    # O config.json guarda o token do controle remoto: restringe a leitura
    # ao próprio usuário (no Windows a proteção real vem do perfil).
    if os.path.exists(CONFIG_FILE):
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except OSError:
            pass


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
                    log.info(f"📦 Copiando de '{origem}' para '{UPLOAD_FOLDER}'...")
                    shutil.copytree(origem, UPLOAD_FOLDER, dirs_exist_ok=True)
                    return True
            except (PermissionError, OSError):
                continue

    if getattr(sys, 'frozen', False):
        log.warning("\n⚠️ Pasta de músicas não encontrada!")
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
        except Exception as e:
            log.warning(f"⚠️ Falha ao sincronizar '{ent.name}': {e}")
            continue
    if novos:
        DatabaseManager().reload_cache()
        log.info(f"📦 {novos} mídia(s) sincronizada(s) da pasta uploads.")
    return novos
