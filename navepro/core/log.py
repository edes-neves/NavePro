"""Configuração de logging do NavePro.

O app roda como interface gráfica (Tkinter) e é distribuído empacotado
(AppImage/.exe/Flatpak), onde normalmente NÃO há console: os `print()` de
diagnóstico simplesmente desapareciam. Este módulo centraliza o logging para
que dê para investigar uma falha depois que ela aconteceu.

Controle por variáveis de ambiente:

- ``NAVEPRO_LOG``: nível (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``,
  ``CRITICAL``). Padrão: ``WARNING``.
- ``NAVEPRO_LOG_FILE``: arquivo de log — rotativo (1 MB × 3, UTF-8). Padrão:
  ``~/.navepro/navepro.log``. Defina como vazio para desligar o arquivo.
- ``NAVEPRO_LOG_STDERR``: ``1``/``0`` liga/desliga o console. Padrão: ligado
  quando existe ``sys.stderr`` (execução a partir do código-fonte).

Uso::

    from navepro.core.log import get_logger
    log = get_logger("app")
    log.info("iniciando")
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys

from navepro.core.paths import DATA_USER_DIR

_NOME_RAIZ = "navepro"
_FORMATO = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATA = "%Y-%m-%d %H:%M:%S"
_TAMANHO_ARQUIVO = 1_000_000
_ROTACOES = 3

_configurado = False


def _nivel_do_ambiente() -> int:
    """Nível de log vindo de ``NAVEPRO_LOG`` (padrão ``WARNING``)."""
    nome = os.environ.get("NAVEPRO_LOG", "WARNING").strip().upper()
    valor = getattr(logging, nome, None)
    return valor if isinstance(valor, int) else logging.WARNING


def _quer_stderr() -> bool:
    """Console ligado por padrão quando há ``sys.stderr`` (fonte, não frozen)."""
    bruto = os.environ.get("NAVEPRO_LOG_STDERR")
    if bruto is not None:
        return bruto.strip().lower() not in ("0", "", "false")
    return sys.stderr is not None


def configurar_logging() -> logging.Logger:
    """Configura a raiz ``navepro`` uma única vez e devolve o logger raiz."""
    global _configurado
    raiz = logging.getLogger(_NOME_RAIZ)
    if _configurado:
        return raiz

    raiz.setLevel(_nivel_do_ambiente())
    # Não deixa escapar para o root (evita handlers duplicados de bibliotecas).
    raiz.propagate = False
    formato = logging.Formatter(_FORMATO, datefmt=_DATA)

    if _quer_stderr():
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formato)
        raiz.addHandler(console)

    arquivo = os.environ.get(
        "NAVEPRO_LOG_FILE", os.path.join(DATA_USER_DIR, "navepro.log")
    )
    if arquivo:
        try:
            para_arquivo = logging.handlers.RotatingFileHandler(
                arquivo,
                maxBytes=_TAMANHO_ARQUIVO,
                backupCount=_ROTACOES,
                encoding="utf-8",
            )
            para_arquivo.setFormatter(formato)
            raiz.addHandler(para_arquivo)
        except OSError:
            # Diretório só-leitura, disco cheio etc.: segue somente com o console.
            pass

    _configurado = True
    return raiz


def get_logger(nome: str = "app") -> logging.Logger:
    """Logger do NavePro sob a raiz ``navepro`` (``get_logger("db")`` → ``navepro.db``)."""
    return logging.getLogger(f"{_NOME_RAIZ}.{nome}")
