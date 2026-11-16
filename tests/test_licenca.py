#!/usr/bin/env python3
"""Testes headless do licenciamento (assinatura, limites e revogação)."""

import base64
import datetime as dt
import json
import os
import sys
import tempfile

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402

import license_manager as lm  # noqa: E402

falhas = 0


def checar(desc, cond, extra=""):
    global falhas
    print(f"{'OK ' if cond else 'X  '} {desc}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas += 1


def _chave_teste():
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    publico = chave.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return chave, publico


def _gravar_licenca(caminho, chave, payload, assinar=True):
    assinatura = chave.sign(
        lm._payload_canonico(payload),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    ) if assinar else b"assinatura-invalida"
    envelope = {
        "payload": payload,
        "assinatura": base64.b64encode(assinatura).decode("ascii"),
    }
    with open(caminho, "w", encoding="utf-8") as fh:
        fh.write(base64.b64encode(json.dumps(envelope).encode()).decode())


def _payload(mid, dias=30):
    hoje = dt.date.today()
    return {
        "cliente": "Cliente Teste",
        "machine_id": mid,
        "emitida_em": hoje.isoformat(),
        "expira_em": (hoje + dt.timedelta(days=dias)).isoformat(),
    }


def _rodar() -> int:
    mid = lm.obter_id_maquina()
    checar("machine_id tem 16 hexadecimais",
           len(mid) == 16 and all(c in "0123456789ABCDEF" for c in mid), mid)
    checar("machine_id é estável", lm.obter_id_maquina() == mid)

    chave, publico = _chave_teste()
    publico_original = lm.CHAVE_PUBLICA_PEM
    dirs_original = lm._diretorios_licenca
    estado_original = dict(lm._ESTADO)
    blacklist_original = lm.esta_na_lista_negra
    lm.CHAVE_PUBLICA_PEM = publico

    try:
        with tempfile.TemporaryDirectory() as tmp:
            lm._diretorios_licenca = lambda: [tmp]
            caminho = os.path.join(tmp, lm.NOME_ARQUIVO_LICENCA)

            ok, motivo, _ = lm.verificar_licenca(consultar_lista_negra=False)
            checar("sem arquivo → modo demonstração",
                   not ok and motivo == "Modo Demonstração")

            _gravar_licenca(caminho, chave, _payload(mid, dias=5))
            ok, motivo, _ = lm.verificar_licenca(consultar_lista_negra=False)
            checar("licença assinada válida", ok
                   and motivo == "Licenciado para Cliente Teste", motivo)

            _gravar_licenca(caminho, chave, _payload(mid, dias=5),
                            assinar=False)
            ok, motivo, _ = lm.verificar_licenca(consultar_lista_negra=False)
            checar("assinatura inválida é recusada",
                   not ok and motivo == "Licença inválida", motivo)

            _gravar_licenca(caminho, chave, _payload("0000000000000000"))
            ok, motivo, _ = lm.verificar_licenca(consultar_lista_negra=False)
            checar("licença de outra máquina é recusada",
                   not ok and motivo == "Licença de outra máquina", motivo)

            _gravar_licenca(caminho, chave, _payload(mid, dias=-1))
            ok, motivo, _ = lm.verificar_licenca(consultar_lista_negra=False)
            checar("licença expirada é recusada",
                   not ok and motivo == "Licença expirada", motivo)

            _gravar_licenca(caminho, chave, _payload(mid, dias=5))
            lm.esta_na_lista_negra = lambda machine_id: True
            ok, motivo, _ = lm.verificar_licenca(consultar_lista_negra=True)
            checar("revogação remove a licença",
                   not ok and motivo == "Licença revogada"
                   and not os.path.exists(caminho), motivo)

            lm.esta_na_lista_negra = lambda machine_id: False
            _gravar_licenca(caminho, chave, _payload(mid, dias=5))
            ok, _, _ = lm.verificar_licenca(consultar_lista_negra=False)
            lm._definir_estado(False, "Modo Demonstração", machine_id=mid)
            checar("modo demo limita anúncios a 3 slides",
                   lm.limitar_slides_anuncio(["a", "b", "c", "d", "e"])
                   == ["a", "b", "c"])
            lm._definir_estado(True, "Licenciado", machine_id=mid)
            checar("modo licenciado não limita anúncios",
                   len(lm.limitar_slides_anuncio(["a", "b", "c", "d", "e"]))
                   == 5)
    finally:
        lm.CHAVE_PUBLICA_PEM = publico_original
        lm._diretorios_licenca = dirs_original
        lm.esta_na_lista_negra = blacklist_original
        lm._ESTADO.clear()
        lm._ESTADO.update(estado_original)

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
