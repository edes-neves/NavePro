#!/usr/bin/env python3
"""Testes da persistência de anúncios (navepro/core/anuncios.py).

Cobre o que pode causar PERDA/DESORDEM de dados: o reaproveitamento de IDs
(menor id livre), o CRUD na tabela `anuncios`, a migração única do
anuncios.json legado e a montagem de slides. Usa um SQLite temporário com o
schema real (o `init_db` extraído), nunca o banco do usuário.
"""

import ast
import json
import os
import sqlite3
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
if _AQUI not in sys.path:
    sys.path.insert(0, _AQUI)

from fixture_biblia import criar_biblia  # noqa: E402
from fixture_log import log  # noqa: E402

from navepro.config import (  # noqa: E402
    EXTENSOES_AUDIO,
    EXTENSOES_VIDEO,
    SUFIXOS_IMAGEM,
)
from navepro.core.textos import _numero_do_titulo, remover_acentos  # noqa: E402

_MOD = os.path.join(RAIZ, "navepro", "core", "anuncios.py")
_SRC = open(_MOD, encoding="utf-8").read()
_TREE = ast.parse(_SRC)


def _montar_ns(conn, anuncios_file, uploads):
    """Executa TODAS as funções do módulo num ns com SQLite real temporário."""
    def db_query(query, params=()):
        return [dict(r) for r in conn.execute(query, params).fetchall()]

    def db_execute(query, params=()):
        cur = conn.execute(query, params)
        conn.commit()
        return cur.lastrowid

    ns: dict = {
        "os": os,
        "re": __import__("re"),
        "json": json,
        "shutil": __import__("shutil"),
        "db_query": db_query,
        "db_execute": db_execute,
        "log": log,
        "ANUNCIOS_FILE": anuncios_file,
        "UPLOAD_FOLDER": uploads,
        "EXTENSOES_AUDIO": EXTENSOES_AUDIO,
        "EXTENSOES_VIDEO": EXTENSOES_VIDEO,
        "SUFIXOS_IMAGEM": SUFIXOS_IMAGEM,
        "_numero_do_titulo": _numero_do_titulo,
        "remover_acentos": remover_acentos,
    }
    for no in _TREE.body:
        if isinstance(no, ast.FunctionDef):
            exec(ast.get_source_segment(_SRC, no), ns)  # noqa: S102
    return ns


class TelaoFake:
    """Registra o que o anúncio pediu para projetar."""

    def __init__(self, imagem_ok=True):
        self.chamadas: list = []
        self.imagem_ok = imagem_ok
        self.slides_recebidos = None

    def projetar_slides(self, slides):
        self.chamadas.append("slides")
        self.slides_recebidos = slides

    def projetar_imagem_com_texto(self, arquivo, texto, config):
        self.chamadas.append(("imagem_com_texto", arquivo, texto))
        return self.imagem_ok

    def projetar_imagem(self, arquivo):
        self.chamadas.append(("imagem", arquivo))
        return True


def _rodar() -> int:
    raiz, db = criar_biblia()
    uploads = os.path.join(raiz, "uploads")
    anuncios_file = os.path.join(raiz, "anuncios.json")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    ns = _montar_ns(conn, anuncios_file, uploads)

    falhas = 0

    def checar(desc, cond):
        nonlocal falhas
        print(f"{'OK ' if cond else 'X  '} {desc}")
        if not cond:
            falhas += 1

    def ids_listados():
        return sorted(a["id"] for a in ns["_listar_anuncios_db"]())

    # ── 1. Reaproveitamento do menor id livre ───────────────────────
    ns["_inserir_anuncio_db"]({"titulo": "Aviso 1"})
    ns["_inserir_anuncio_db"]({"titulo": "Aviso 2"})
    ns["_inserir_anuncio_db"]({"titulo": "Aviso 3"})
    checar("ids sequenciais 1,2,3", ids_listados() == [1, 2, 3])

    ns["_excluir_anuncios_db"]([2])
    checar("após excluir o id 2, restam 1 e 3", ids_listados() == [1, 3])
    novo = ns["_inserir_anuncio_db"]({"titulo": "Aviso 4"})
    checar("novo anúncio reaproveita o menor id livre (2)", novo == 2)
    checar("lista volta a 1,2,3", ids_listados() == [1, 2, 3])

    checar("excluir lista vazia é no-op bem-sucedido",
           ns["_excluir_anuncios_db"]([]) is True)

    # excluir tudo e inserir volta ao id 1
    ns["_excluir_anuncios_db"]([1, 2, 3])
    checar("tabela vazia após excluir todos", ids_listados() == [])
    checar("primeiro id volta a 1", ns["_inserir_anuncio_db"](
        {"titulo": "Reinício"}) == 1)

    # ── 2. `_listar_anuncios_db` ignora inativos e filtra ───────────
    ns["_inserir_anuncio_db"]({
        "titulo": "Culto de Oração", "categoria": "Cultos",
        "texto": "Toda quarta às 19h"})
    conn.execute("INSERT INTO anuncios (id, titulo, ativo) VALUES (99, 'Inativo', 0)")
    conn.commit()
    titulos = [a["titulo"] for a in ns["_listar_anuncios_db"]()]
    checar("inativo (id 99) não aparece", "Inativo" not in titulos)
    checar("busca por título (case-insensitive)",
           [a["titulo"] for a in ns["_listar_anuncios_db"]("culto")]
           == ["Culto de Oração"])
    checar("busca por categoria",
           len(ns["_listar_anuncios_db"]("cultos")) == 1)
    checar("busca por texto",
           len(ns["_listar_anuncios_db"]("19h")) == 1)
    checar("busca sem resultado devolve []",
           ns["_listar_anuncios_db"]("inexistente") == [])

    # ── 3. Busca por termo / referência ─────────────────────────────
    ns["_inserir_anuncio_db"]({"titulo": "3 - Batismo", "categoria": "Geral"})
    checar("busca por id numérico",
           ns["_buscar_anuncio_por_termo"]("1")[0]["titulo"]
           == "Reinício")
    checar("busca pelo número do título",
           ns["_buscar_anuncio_por_termo"]("3")[0]["titulo"]
           == "3 - Batismo")
    checar("busca exata por título (com acento)",
           ns["_buscar_anuncio_por_termo"]("culto de oracao")[0]["titulo"]
           == "Culto de Oração")
    checar("busca por trecho",
           len(ns["_buscar_anuncio_por_termo"]("Batismo")) == 1)
    checar("termo vazio devolve []", ns["_buscar_anuncio_por_termo"]("") == [])
    checar("_buscar_anuncio_por_ref por id",
           ns["_buscar_anuncio_por_ref"](1)["titulo"] == "Reinício")
    checar("_buscar_anuncio_por_ref inválido → None",
           ns["_buscar_anuncio_por_ref"]("abc") is None)
    checar("_buscar_anuncio_por_ref 0/None → None",
           ns["_buscar_anuncio_por_ref"](0) is None
           and ns["_buscar_anuncio_por_ref"](None) is None)

    # ── 4. Montagem de slides ───────────────────────────────────────
    checar("slides: título + parágrafos",
           ns["_montar_slides_anuncio_servico"](
               {"titulo": "T", "texto": "p1\n\np2\n\n\np3"})
           == ["T", "p1", "p2", "p3"])
    checar("slides: só título",
           ns["_montar_slides_anuncio_servico"]({"titulo": "T", "texto": ""})
           == ["T"])
    checar("slides: vazio → ['ANÚNCIO']",
           ns["_montar_slides_anuncio_servico"]({}) == ["ANÚNCIO"])

    # ── 5. Classificação de mídia ───────────────────────────────────
    tm = ns["_tipo_midia_para_arquivo"]
    checar("classifica mp4/mp3/png e ignora txt",
           tm("a.mp4") == "video" and tm("a.MP3") == "audio"
           and tm("a.png") == "imagem" and tm("a.txt") == "")

    # ── 6. Projeção do anúncio na Ordem de Serviço ──────────────────
    telao = TelaoFake()
    checar("anúncio vazio → False",
           ns["_projetar_anuncio_ordserv"](telao, {}) is False)
    telao = TelaoFake()
    ok = ns["_projetar_anuncio_ordserv"](
        telao, {"tipo_midia": "slide", "titulo": "T", "texto": "corpo"})
    checar("anúncio de texto projeta slides",
           ok and telao.slides_recebidos == ["T", "corpo"])
    telao = TelaoFake()
    ok = ns["_projetar_anuncio_ordserv"](telao, {
        "config_midia": json.dumps({"mslides": [
            {"texto": "s1", "imagem": ""},
            {"texto": "", "imagem": "/x.png"},
            {"texto": "", "imagem": ""},
        ]})})
    checar("multi-slide ignora slide vazio e projeta os demais",
           ok and len(telao.slides_recebidos) == 2)
    img = os.path.join(uploads, "foto.png")
    open(img, "w").close()
    telao = TelaoFake()
    ok = ns["_projetar_anuncio_ordserv"](telao, {
        "tipo_midia": "imagem", "arquivo_midia": img, "texto": "legenda"})
    checar("imagem existente usa projetar_imagem_com_texto",
           ok and telao.chamadas[0][0] == "imagem_com_texto")
    telao = TelaoFake(imagem_ok=False)
    ok = ns["_projetar_anuncio_ordserv"](telao, {
        "tipo_midia": "imagem", "arquivo_midia": img, "texto": "legenda"})
    checar("fallback para projetar_imagem quando com_texto falha",
           ok and [c for c in telao.chamadas if isinstance(c, tuple)][-1][0]
           == "imagem")

    # ── 7. Cópia para uploads (sem colisão, sem sobrescrever) ───────
    origem = os.path.join(raiz, "origem", "video.mp4")
    os.makedirs(os.path.dirname(origem), exist_ok=True)
    open(origem, "w").close()
    d1 = ns["_copiar_arquivo_uploads"](origem)
    d2 = ns["_copiar_arquivo_uploads"](origem)
    checar("cópia para uploads evita colisão de nome",
           d1 == os.path.join(uploads, "video.mp4")
           and d2 == os.path.join(uploads, "video_1.mp4"))
    checar("arquivo já em uploads não é copiado de novo",
           ns["_copiar_arquivo_uploads"](d1) == d1)
    checar("origem inexistente → None",
           ns["_copiar_arquivo_uploads"](os.path.join(raiz, "nao_existe.mp4"))
           is None)

    # ── 8. JSON legado: round-trip e robustez ───────────────────────
    checar("JSON ausente → []",
           ns["_carregar_anuncios_json"]() == [])
    ns["_salvar_anuncios_json"]([{"id": 1, "titulo": "Ação"}])
    checar("round-trip salva/carrega (acentos preservados)",
           ns["_carregar_anuncios_json"]()
           == [{"id": 1, "titulo": "Ação"}])
    with open(anuncios_file, "w", encoding="utf-8") as f:
        f.write("{lixo não json")
    checar("JSON corrompido → [] (não explode)",
           ns["_carregar_anuncios_json"]() == [])

    # ── 9. Migração única do anuncios.json legado ───────────────────
    raiz2, db2 = criar_biblia()
    conn2 = sqlite3.connect(db2)
    conn2.row_factory = sqlite3.Row
    arquivo2 = os.path.join(raiz2, "anuncios.json")
    ns2 = _montar_ns(conn2, arquivo2, os.path.join(raiz2, "uploads"))

    checar("migração sem arquivo JSON → 0",
           ns2["_migrar_anuncios_do_json"]() == 0)
    with open(arquivo2, "w", encoding="utf-8") as f:
        json.dump([{"titulo": "Legado 1", "categoria": "X", "texto": "t1"},
                   {"titulo": "Legado 2"}], f, ensure_ascii=False)
    checar("migra os 2 anúncios do JSON legado",
           ns2["_migrar_anuncios_do_json"]() == 2)
    checar("legado aparece na listagem do banco",
           sorted(a["titulo"] for a in ns2["_listar_anuncios_db"]())
           == ["Legado 1", "Legado 2"])
    checar("migração é idempotente (2ª chamada → 0)",
           ns2["_migrar_anuncios_do_json"]() == 0
           and len(ns2["_listar_anuncios_db"]()) == 2)

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
