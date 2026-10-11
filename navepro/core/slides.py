"""Slides de letras/anúncios e busca de hinos/mídia.

Extraído de NavePro.py sem alterar o comportamento (ver AGENTS.md).
"""

import re
import unicodedata

from navepro.core.banco import db_query
from navepro.core.textos import _numero_do_titulo


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


def _previa_slide(slide: object) -> str:
    """Texto curto de um slide para exibir no controle remoto."""
    if isinstance(slide, dict):
        return (slide.get("texto") or "").strip()
    if isinstance(slide, tuple):
        texto = str(slide[0]) if slide else ""
        ref = str(slide[1]) if len(slide) > 1 and slide[1] else ""
        return f"{ref} — {texto}" if ref else texto
    return str(slide or "")


def _montar_slides_anuncio(anuncio: dict) -> list:
    """Monta os slides de um anúncio respeitando o texto digitado:
    slide 0 é o título, os demais são os parágrafos do texto (cada
    parágrafo = 1 slide, exatamente como o editor adiciona telas)."""
    titulo = (anuncio.get('titulo') or '').strip()
    texto = (anuncio.get('texto') or '').strip()
    paragrafos = [seg.strip() for seg in re.split(r'\n\s*\n', texto)
                  if seg.strip()]
    slides = [titulo] if titulo else []
    for paragrafo in paragrafos:
        slides.append(paragrafo)
    if not slides:
        slides = [titulo or "ANÚNCIO"]
    return slides


def _buscar_hino_por_termo(termo: str) -> list[dict]:
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


def _buscar_midia_por_termo(termo: str, tipo: str = 'video') -> list[dict]:
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
