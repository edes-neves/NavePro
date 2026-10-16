"""Anúncios — persistência e helpers (arquivo JSON legado + SQLite).

Reúne a leitura/gravação do anuncios.json legado, a classificação de mídia,
a cópia para a pasta de uploads, o CRUD na tabela SQLite "anuncios" (com
reaproveitamento do menor id livre) e a migração única do JSON para o banco.
Extraído de NavePro.py sem alteração de comportamento.
"""

from __future__ import annotations

import json
import os
import re
import shutil

from navepro.config import EXTENSOES_AUDIO, EXTENSOES_VIDEO, SUFIXOS_IMAGEM
from navepro.core.banco import db_execute, db_query
from navepro.core.log import get_logger
from navepro.core.paths import ANUNCIOS_FILE, UPLOAD_FOLDER
from navepro.core.textos import _numero_do_titulo, remover_acentos

log = get_logger("anuncios")


def _carregar_anuncios_json() -> list[dict]:
    """Lê ~/.navepro/anuncios.json e devolve a lista de anúncios.

    O arquivo fica permanentemente FORA do banco de dados: cada anúncio é
    um dict {id, titulo, categoria, texto, criado_em}.
    """
    try:
        with open(ANUNCIOS_FILE, encoding="utf-8") as f:
            dados = json.load(f)
        if isinstance(dados, list):
            return [d for d in dados if isinstance(d, dict)]
    except (OSError, ValueError):
        pass
    return []


def _salvar_anuncios_json(anuncios: list[dict]) -> bool:
    """Persiste a lista de anúncios em ~/.navepro/anuncios.json.

    Retorna True em caso de sucesso (ou False se o disco recusar a gravação).
    """
    try:
        with open(ANUNCIOS_FILE, "w", encoding="utf-8") as f:
            json.dump(anuncios, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        log.exception(f"⚠️ Erro ao salvar anúncios: {e}")
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


def _copiar_arquivo_uploads(caminho: str) -> str | None:
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
        log.exception(f"⚠️ Erro ao copiar para uploads: {e}")
        return None


def _listar_anuncios_db(busca: str = "") -> list[dict]:
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
        log.exception(f"⚠️ Erro ao listar anúncios: {e}")
        return []


def _buscar_anuncio_por_ref(ref_id: object) -> dict | None:
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


def _buscar_anuncio_por_termo(termo: str) -> list[dict]:
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
        (remover_acentos(a.get('titulo') or '').casefold(), a)
        for a in anuncios]
    exatos = [a for n, a in norm_anuncios if n == norm]
    if exatos:
        return exatos
    por_titulo = [a for n, a in norm_anuncios if norm in n]
    if por_titulo:
        return por_titulo
    return [a for a in anuncios
            if norm in remover_acentos(a.get('categoria') or '').casefold()
            or norm in remover_acentos(a.get('texto') or '').casefold()]


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
        return 1
    usados = {r["id"] for r in rows}
    cand = 1
    while cand in usados:
        cand += 1
    return cand


def _inserir_anuncio_db(dados: dict) -> int | None:
    """Insere um anúncio na tabela 'anuncios'. Retorna o id (None se falhar).

    Informa explicitamente o id = menor número livre, de forma que um
    anúncio deletado tenha seu número reaproveitado pelo próximo criado.
    """
    novo_id = _proximo_id_anuncio_livre()
    if not novo_id:
        log.warning("⚠️ Não foi possível calcular um id livre para o anúncio.")
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
        log.exception(f"⚠️ Erro ao inserir anúncio: {e}")
        return None


def _atualizar_anuncio_db(anuncio_id: int, dados: dict) -> bool:
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
        log.exception(f"⚠️ Erro ao atualizar anúncio: {e}")
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
        log.exception(f"⚠️ Erro ao excluir anúncios: {e}")
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
        log.info(f"✅ {importados} anúncio(s) migrado(s) de anuncios.json para o banco.")
    return importados
