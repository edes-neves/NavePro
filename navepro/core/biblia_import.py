"""Importação de Bíblias (XML/TXT/JSON) para a tabela ``versiculos``.

Extraído da janela da Bíblia para ser reutilizado pela janela em grade e
pela janela clássica de busca. O formato de saída de cada parser continua
o mesmo: ``(versao, versiculos, livros_desconhecidos)``, onde cada
versículo é ``(versao, livro, capitulo, versiculo, texto)``.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
import xml.etree.ElementTree as ET
from functools import lru_cache

from navepro.config import SQLITE_TIMEOUT
from navepro.core.banco import _gerador_id_livre, db_query
from navepro.core.log import get_logger
from navepro.core.paths import DB_PATH

log = get_logger("biblia_import")

_LIVROS_ALIAS = {
    "cantico dos canticos": "Cânticos",
    "cantares": "Cânticos",
    "lamentacoes de jeremias": "Lamentações",
}


def sem_acentos(texto: str) -> str:
    """Minúsculas sem acentos, para comparar nomes de livro."""
    nf = unicodedata.normalize('NFKD', str(texto))
    return ''.join(c for c in nf if not unicodedata.combining(c)).casefold()


@lru_cache(maxsize=4)
def _mapa_livros(livros: tuple) -> dict:
    """{nome sem acentos: nome canônico} cacheado por lista de livros."""
    return {sem_acentos(n): n for n in livros}


def normalizar_livro_biblia(nome: str, livros) -> str | None:
    """Converte o nome do livro para o padrão da lista do app.

    Insensível a acentos e a variações comuns: números romanos (I/II) e
    nomes completos ('Lamentações de Jeremias', 'Cântico dos Cânticos').
    Retorna None se não reconhecer.
    """
    chave = sem_acentos(nome or '')
    if not chave:
        return None
    flat = _mapa_livros(tuple(livros))
    if chave in flat:
        return flat[chave]
    if chave in _LIVROS_ALIAS:
        return _LIVROS_ALIAS[chave]
    for rom, num in (("iii", "3"), ("ii", "2"), ("i", "1")):
        prefixo = rom + " "
        if chave.startswith(prefixo):
            cand = num + " " + chave[len(prefixo):]
            return flat.get(cand)
    return None


def parsear_biblia_xml(caminho: str, livros) -> tuple:
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
        livro = normalizar_livro_biblia(bb.get('bname'), livros)
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


def parsear_biblia_txt(caminho: str, livros) -> tuple:
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
    with open(caminho, encoding='utf-8', errors='replace') as arquivo:
        for linha in arquivo:
            s = linha.rstrip('\n')
            t = s.strip()
            if not t:
                continue
            if t in ("ANTIGO TESTAMENTO", "NOVO TESTAMENTO"):
                continue
            # Separador com o nome do livro sozinho (ex.: "ÊXODO")
            if normalizar_livro_biblia(t, livros) is not None:
                continue
            # Cabeçalho de capítulo: '<nome do livro> <número>'
            m = _re_header.match(s)
            if m:
                novo_livro = normalizar_livro_biblia(m.group(1).strip(), livros)
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


def parsear_biblia_json(caminho: str, livros) -> tuple:
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

    def _numero(obj, *chaves) -> int | None:
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
        livro = normalizar_livro_biblia(nome, livros)
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


def importar_biblias(caminhos, livros) -> dict:
    """Importa uma ou mais Bíblias (XML/TXT/JSON) para ``versiculos``.

    Retorna um resumo com as chaves ``inseridos``, ``pulados``, ``erros``,
    ``versoes`` e ``desconhecidos``.
    """
    total_inseridos = 0
    total_pulados = 0
    erros = 0
    versoes_importadas = []
    desconhecidos = set()
    for caminho in caminhos:
        ext = os.path.splitext(caminho)[1].lower()
        try:
            if ext == '.xml':
                versao, vv, desc = parsear_biblia_xml(caminho, livros)
            elif ext == '.txt':
                versao, vv, desc = parsear_biblia_txt(caminho, livros)
            elif ext == '.json':
                versao, vv, desc = parsear_biblia_json(caminho, livros)
            else:
                erros += 1
                continue
        except Exception as e:
            log.exception(f"Erro ao importar bíblia {caminho}: {e}")
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
                    _gerador_id_livre("versiculos", limitar=len(novos)))
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

    return {
        'inseridos': total_inseridos,
        'pulados': total_pulados,
        'erros': erros,
        'versoes': versoes_importadas,
        'desconhecidos': desconhecidos,
    }
