#!/usr/bin/env python3
"""Testes de segurança do servidor HTTP (navepro/core/servidor_http.py).

Trava dois pontos:
1. `_remoto_autorizado` — comparação do token com `hmac.compare_digest`
   (tempo constante; bytes, para não explodir com não-ASCII vindo da rede).
2. `_handle_upload_bytes` — o `filename` do multipart vem do cliente e não
   pode escapar de UPLOAD_FOLDER (basename + recusa de "."/"..").
"""

import ast
import mimetypes
import os
import re
import sys
import tempfile
from types import SimpleNamespace

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import hmac  # noqa: E402

from navepro.core.textos import detectar_tipo_arquivo  # noqa: E402

_SRC = open(os.path.join(RAIZ, "navepro", "core", "servidor_http.py"),
            encoding="utf-8").read()
_TREE = ast.parse(_SRC)


def _fonte_metodo(nome: str) -> str:
    """Pega um método de ServidorAsyncHTTP via AST, sem importar o app."""
    for no in _TREE.body:
        if isinstance(no, ast.ClassDef):
            for item in no.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and item.name == nome:
                    return ast.get_source_segment(_SRC, item)
    raise AssertionError(
        f"método {nome} não encontrado em navepro/core/servidor_http.py")


def _carregar_autorizado():
    """Executa _remoto_autorizado como função simples (self explícito)."""
    ns: dict = {"hmac": hmac}
    exec(compile(_fonte_metodo("_remoto_autorizado"),
                 "<_remoto_autorizado>", "exec"), ns)
    return ns["_remoto_autorizado"]


def _carregar_upload(pasta_uploads: str):
    """Executa _handle_upload_bytes com stubs de banco/pasta."""
    ns: dict = {
        "os": os,
        "re": re,
        "mimetypes": mimetypes,
        "UPLOAD_FOLDER": pasta_uploads,
        "detectar_tipo_arquivo": detectar_tipo_arquivo,
        # O teste não exercita o INSERT: o handler grava o arquivo antes.
        "db_execute": lambda *a, **k: 1,
        "DatabaseManager": lambda: SimpleNamespace(reload_cache=lambda: None),
    }
    exec(compile(_fonte_metodo("_handle_upload_bytes"),
                 "<_handle_upload_bytes>", "exec"), ns)
    return ns["_handle_upload_bytes"]


class ServidorFake:
    """Self mínimo para os métodos extraídos."""

    def __init__(self, token=None, uploads=""):
        self.token = token
        self.uploads = uploads
        self.ultima_resposta: tuple[int, str] | None = None

    def _responder_erro_bytes(self, msg, codigo=400):
        self.ultima_resposta = (codigo, msg)
        return b""

    def _responder_json_bytes(self, obj, codigo=200):
        self.ultima_resposta = (codigo, "json")
        return b""


def _corpo_multipart(filename: str, conteudo=b"ola") -> tuple[dict, bytes]:
    """Monta headers+body como o _handle_upload_bytes espera."""
    boundary = "----NaveProTeste"
    corpo = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="arquivo"; '
        f'filename="{filename}"\r\n'
        f"Content-Type: text/plain\r\n"
        f"\r\n"
    ).encode() + conteudo + f"\r\n--{boundary}--\r\n".encode()
    headers = {
        "content-type": f"multipart/form-data; boundary={boundary}",
    }
    return headers, corpo


def _rodar() -> int:
    falhas = 0

    def checar(desc, cond):
        nonlocal falhas
        print(f"{'OK ' if cond else 'X  '} {desc}")
        if not cond:
            falhas += 1

    autorizado = _carregar_autorizado()

    def autoriza(token, headers=None, params=None):
        self = SimpleNamespace(token=token)
        return autorizado(self, headers or {}, params or {})

    # ── 1. Token (compare_digest) ───────────────────────────────────
    checar("token válido via x-token autoriza",
           autoriza("abc123", {"x-token": "abc123"}))
    checar("token válido via ?t= autoriza",
           autoriza("abc123", {}, {"t": "abc123"}))
    checar("x-token tem prioridade sobre ?t= errado",
           autoriza("abc123", {"x-token": "abc123"}, {"t": "errado"}))
    checar("token errado nega",
           not autoriza("abc123", {"x-token": "errado"}))
    checar("token vazio nega",
           not autoriza("abc123", {"x-token": ""}))
    checar("sem token configurado nega (controle remoto off)",
           not autoriza(None, {"x-token": "qualquer"}))
    try:
        nao_ascii_ok = isinstance(autoriza("abc123", {"x-token": "ñéñç"}),
                                  bool)
    except TypeError:
        nao_ascii_ok = False
    checar("não-ASCII em x-token não levanta TypeError", nao_ascii_ok)
    checar("token com espaços externos é normalizado",
           autoriza("abc123", {"x-token": "  abc123  "}))

    # ── 2. Upload: filename malicioso ───────────────────────────────
    with tempfile.TemporaryDirectory() as raiz, \
            tempfile.TemporaryDirectory() as uploads:
        fora = os.path.join(raiz, "escape.txt")
        for nome_mal, desc in (
            ("../../escape.txt", "filename com ../ não escapa"),
            ("..\\..\\escape.txt", "filename com backslash não escapa"),
            ("/etc/escape.txt", "filename absoluto vira basename"),
        ):
            handler = _carregar_upload(uploads)
            self = ServidorFake(uploads=uploads)
            headers, corpo = _corpo_multipart(nome_mal)
            handler(self, headers, corpo)
            dentro = os.listdir(uploads)
            checar(f"{desc} (arquivo só em uploads)",
                   dentro == ["escape.txt"]
                   and not os.path.exists(fora)
                   and self.ultima_resposta
                   and self.ultima_resposta[0] == 201)
            # limpa para o próximo caso
            for nome in dentro:
                os.unlink(os.path.join(uploads, nome))

        for nome_invalido in ("..", ".", "", "pasta/"):
            handler = _carregar_upload(uploads)
            self = ServidorFake(uploads=uploads)
            headers, corpo = _corpo_multipart(nome_invalido)
            handler(self, headers, corpo)
            codigo = self.ultima_resposta[0] if self.ultima_resposta else None
            checar(f"filename {nome_invalido!r} recusado sem gravar",
                   codigo in (400,) and os.listdir(uploads) == [])

        # filename comum continua funcionando
        handler = _carregar_upload(uploads)
        self = ServidorFake(uploads=uploads)
        headers, corpo = _corpo_multipart("avisos.txt")
        handler(self, headers, corpo)
        checar("filename comum é aceito normalmente",
               os.listdir(uploads) == ["avisos.txt"]
               and self.ultima_resposta == (201, "json"))

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
