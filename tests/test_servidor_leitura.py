#!/usr/bin/env python3
"""Testes da leitura de requisição do servidor HTTP (servidor_http.py).

Trava o `_ler_requisicao`: antes ele fazia uma única `reader.read(65536)`,
o que truncava qualquer corpo maior que 64 KB (uploads de mídia) e ainda
decodificava o corpo binário como UTF-8. Agora lê em blocos até o
Content-Length, com limites de cabeçalho/corpo (431/413).
"""

import ast
import asyncio
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

_SRC = open(os.path.join(RAIZ, "navepro", "core", "servidor_http.py"),
            encoding="utf-8").read()
_TREE = ast.parse(_SRC)


def _fonte_metodo(nome: str) -> str:
    for no in _TREE.body:
        if isinstance(no, ast.ClassDef):
            for item in no.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and item.name == nome:
                    return ast.get_source_segment(_SRC, item)
    raise AssertionError(
        f"método {nome} não encontrado em navepro/core/servidor_http.py")


def _carregar():
    """Extrai _ler_requisicao + as constantes de limite via AST."""
    ns: dict = {"asyncio": asyncio}
    for no in _TREE.body:
        if isinstance(no, ast.Assign) \
                and isinstance(no.targets[0], ast.Name) \
                and no.targets[0].id in ("_LIMITE_CABECALHO", "_LIMITE_CORPO"):
            exec(ast.get_source_segment(_SRC, no), ns)
    exec(compile(_fonte_metodo("_ler_requisicao"),
                 "<_ler_requisicao>", "exec"), ns)
    return ns["_ler_requisicao"], ns["_LIMITE_CABECALHO"], ns["_LIMITE_CORPO"]


class ServidorFake:
    def _responder_erro_bytes(self, msg, codigo=400):
        return f"ERRO:{codigo}:{msg}".encode()


def _executar(metodo, servidor, dados: bytes):
    async def _correr():
        reader = asyncio.StreamReader()
        reader.feed_data(dados)
        reader.feed_eof()
        return await metodo(servidor, reader)
    return asyncio.run(_correr())


def _requisicao(method, path, headers=None, body=b"") -> bytes:
    linhas = [f"{method} {path} HTTP/1.1"]
    for chave, valor in (headers or {}).items():
        linhas.append(f"{chave}: {valor}")
    return ("\r\n".join(linhas) + "\r\n\r\n").encode("utf-8") + body


def _rodar() -> int:
    ler, limite_cab, limite_corpo = _carregar()
    servidor = ServidorFake()
    falhas = 0

    def checar(desc, cond):
        nonlocal falhas
        print(f"{'OK ' if cond else 'X  '} {desc}")
        if not cond:
            falhas += 1

    # ── GET simples sem corpo ───────────────────────────────────────
    req = _executar(ler, servidor,
                    b"GET /api/midia?tipo=video HTTP/1.1\r\nHost: x\r\n\r\n")
    checar("GET sem corpo → (method, path, headers, b'')",
           isinstance(req, tuple) and req[0] == "GET"
           and req[1] == "/api/midia?tipo=video"
           and req[2].get("host") == "x" and req[3] == b"")

    # ── Corpo grande (>64 KB) NÃO é truncado ────────────────────────
    corpo = bytes(range(256)) * 1000  # 256 KB, binário
    req = _executar(ler, servidor, _requisicao(
        "POST", "/api/midia/upload",
        {"Content-Length": str(len(corpo)), "Content-Type": "video/mp4"},
        corpo))
    checar("corpo de 256 KB chega inteiro (não mais 64 KB)",
           req[3] == corpo and len(req[3]) == len(corpo))

    # ── Corpo com CRLFCRLF interno não confunde o parser ────────────
    corpo = b"AAA\r\n\r\nBBB" * 10
    req = _executar(ler, servidor, _requisicao(
        "POST", "/x", {"Content-Length": str(len(corpo))}, corpo))
    checar("CRLFCRLF dentro do corpo não quebra o parser", req[3] == corpo)

    # ── Cabeçalhos fragmentados em várias leituras ──────────────────
    corpo_json = b'{"acao":"prox"}'
    req = _executar(ler, servidor, _requisicao(
        "POST", "/api/remoto/slide",
        {"Content-Length": str(len(corpo_json)), "X-Token": "abc"},
        corpo_json))
    checar("headers + corpo pequeno parseados juntos",
           req[0] == "POST" and req[2].get("x-token") == "abc"
           and req[3] == corpo_json)

    # ── Header grande demais → 431 ──────────────────────────────────
    req = _executar(ler, servidor, _requisicao(
        "GET", "/", {"X-Grande": "a" * (limite_cab + 10)}))
    checar("cabeçalho > limite → 431",
           isinstance(req, bytes) and req.startswith(b"ERRO:431:"))

    # ── Corpo anunciado acima do limite → 413 ───────────────────────
    req = _executar(ler, servidor, _requisicao(
        "POST", "/api/midia/upload",
        {"Content-Length": str(limite_corpo + 1)}, b"x"))
    checar("Content-Length > limite → 413",
           isinstance(req, bytes) and req.startswith(b"ERRO:413:"))

    # ── Content-Length inválido é tratado como 0 ────────────────────
    req = _executar(ler, servidor, _requisicao(
        "POST", "/x", {"Content-Length": "abc"}, b"ignorado"))
    checar("Content-Length inválido → corpo vazio",
           isinstance(req, tuple) and req[3] == b"")

    # ── Conexão fechada sem dados → None ────────────────────────────
    checar("conexão vazia → None", _executar(ler, servidor, b"") is None)

    # ── Linha de requisição inválida → None ─────────────────────────
    checar("linha de requisição inválida → None",
           _executar(ler, servidor, b"LIXO\r\n\r\n") is None)

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
