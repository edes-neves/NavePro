"""Inicialização do banco e recursos (uploads/config).

Extraído de NavePro.py sem alterar o comportamento (ver AGENTS.md).
"""

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
    DB_EMBUTIDO,
    DB_PATH,
    DIR_BASE,
    UPLOAD_FOLDER,
    UPLOADS_EMBUTIDO,
    _caminho_recurso,
)
from navepro.core.textos import detectar_tipo_arquivo

log = get_logger("inicializacao")


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
                vals = dict(zip(colunas, row, strict=False))
                placeholders = ", ".join("?" for _ in vals)
                cols = ", ".join(vals.keys())
                cursor.execute(
                    f"INSERT INTO anuncios ({cols}) VALUES ({placeholders})",
                    tuple(vals.values()),
                )
            cursor.execute("DROP TABLE IF EXISTS _anuncios_backup_old_ai")
            log.info("✅ Migração anuncios: AUTOINCREMENT removido (IDs passam a reaproveitar).")
    except Exception as e:
        log.warning(f"⚠️ Migração AUTOINCREMENT ignorada (nova tabela ou já migrada): {e}")

    # ── Migração: garantir a coluna config_midia em bancos já existentes ──
    # Aditiva e idempotente: se a coluna já existe (banco novo ou já migrado),
    # não faz nada.
    try:
        colunas_existentes = {desc[1] for desc in cursor.execute(
            "PRAGMA table_info(anuncios)").fetchall()}
        if colunas_existentes and 'config_midia' not in colunas_existentes:
            cursor.execute("ALTER TABLE anuncios ADD COLUMN config_midia TEXT DEFAULT ''")
            log.info("✅ Migração anuncios: coluna 'config_midia' adicionada.")
    except Exception as e:
        log.warning(f"⚠️ Migração config_midia ignorada: {e}")

    conn.commit()
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


def inicializar_config() -> None:
    """Copia config embutido para ~/.navepro/ se necessário."""
    config_embutido = _caminho_recurso("config.json")
    if not os.path.exists(CONFIG_FILE) and os.path.exists(config_embutido):
        log.info(f"📦 Copiando config embutido para {CONFIG_FILE}")
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
        except Exception:
            continue
    if novos:
        DatabaseManager().reload_cache()
        log.info(f"📦 {novos} mídia(s) sincronizada(s) da pasta uploads.")
    return novos
