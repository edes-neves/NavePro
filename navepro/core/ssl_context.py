"""Contexto SSL com os certificados do sistema e o helper _baixar()."""

import os
import ssl
import threading
import urllib.request
from typing import Optional


_SSL_CONTEXTO: Optional[ssl.SSLContext] = None
_SSL_CONTEXTO_LOCK: threading.Lock = threading.Lock()
# Locais comuns do bundle de CA do sistema
_CAMINHOS_CACERT: tuple[str, ...] = (
    "/etc/ssl/certs/ca-certificates.crt",   # Debian/Ubuntu/derivados (BigLinux)
    "/etc/ssl/cert.pem",                    # macOS/Fedora
    "/etc/pki/tls/certs/ca-bundle.crt",     # RHEL/Fedora
    "/etc/ssl/ca-bundle.pem",               # openSUSE
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
)
# Caminhos onde o host pode ter CAs corporativas (MITM/proxy) adicionais
_CAMINHOS_CLIENTE: tuple[str, ...] = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/cert.pem",
)


def _ssl_context() -> ssl.SSLContext:
    """Retorna um contexto SSL com as CAs do SISTEMA (não as embutidas).

    Dentro do AppImage, o Python embutido usa um bundle de CA próprio que
    nem sempre confia nas raízes (ex.: proxy corporativo, ou distribuições
    em que as CAs ficam em local específico — como no BigLinux). Isso
    causa "SSL: CERTIFICATE_VERIFY_FAILED". Aqui carregamos o bundle de CA
    do sistema do host de verdade.
    """
    global _SSL_CONTEXTO
    if _SSL_CONTEXTO is not None:
        return _SSL_CONTEXTO
    with _SSL_CONTEXTO_LOCK:
        if _SSL_CONTEXTO is not None:
            return _SSL_CONTEXTO

        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED

        # 1) Tenta carregar explicitamente o bundle de CA do sistema.
        for cafile in _CAMINHOS_CACERT:
            try:
                if os.path.isfile(cafile):
                    ctx.load_verify_locations(cafile=cafile)
                    break
            except (ssl.SSLError, OSError):
                continue

        # 2) Tenta um bundle de cliente/CA corporativa (evita MITM falso).
        for cafile in _CAMINHOS_CLIENTE:
            try:
                if os.path.isfile(cafile):
                    ctx.load_verify_locations(cafile=cafile)
                    break
            except (ssl.SSLError, OSError):
                continue

        _SSL_CONTEXTO = ctx
        return ctx


def _baixar(url, timeout: int = 8, **kwargs):
    """Faz uma requisição HTTPS usando o certificado do sistema.

    Aceita uma URL (str) ou um urllib.request.Request já montado
    (headers/User-Agent etc.). Encapsular um Request em outro Request
    quebra a URL e levanta 'ValueError: unknown url type'.
    """
    if not isinstance(url, urllib.request.Request):
        url = urllib.request.Request(url, **kwargs)
    return urllib.request.urlopen(url, timeout=timeout, context=_ssl_context())