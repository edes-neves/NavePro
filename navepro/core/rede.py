"""Helpers de rede local.

Extraído de NavePro.py sem alterar o comportamento (ver AGENTS.md).
"""

import socket


def _eh_loopback(ip: str) -> bool:
    """True se o endereço for o próprio computador (127.0.0.1 / ::1)."""
    return ip in ('127.0.0.1', '::1', 'localhost')


def _ip_da_rede() -> str:
    """IP local na rede local (o que o celular digita no navegador).

    Abre um socket UDP para um endereço externo (sem enviar dados) só
    para o SO escolher a rota de saída — é a forma confiável de achar o
    IP da placa que enxerga o celular, mesmo com várias interfaces.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(('1.1.1.1', 80))
        return sock.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return '127.0.0.1'
    finally:
        sock.close()

