#!/usr/bin/env python3
"""Testes headless do licenciamento (teste de 30 dias, assinatura e revogação)."""

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
from navepro.core.slides import _montar_slides_anuncio  # noqa: E402

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


def _gravar_teste(caminho, mid, inicio_dias=0, ultima_dias=None,
                  bloqueado=False):
    hoje = dt.date.today()
    ultima = hoje + dt.timedelta(
        days=0 if ultima_dias is None else ultima_dias)
    dados = {
        "machine_id": mid,
        "inicio": (hoje - dt.timedelta(days=inicio_dias)).isoformat(),
        "ultima_verificacao": ultima.isoformat(),
        "bloqueado": bloqueado,
    }
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump(dados, fh)


def _rodar() -> int:
    dirs = lm._diretorios_licenca()
    checar("pasta de config do usuário vem primeiro na busca da licença",
           dirs[0] == lm._diretorio_config_usuario()
           and os.path.basename(dirs[0]) == "NavePro", repr(dirs))
    checar("diretórios de licença não se repetem",
           len(dirs) == len(set(dirs)), repr(dirs))

    mid = lm.obter_id_maquina()
    checar("machine_id tem 16 hexadecimais",
           len(mid) == 16 and all(c in "0123456789ABCDEF" for c in mid), mid)
    checar("machine_id é estável", lm.obter_id_maquina() == mid)

    chave, publico = _chave_teste()
    publico_original = lm.CHAVE_PUBLICA_PEM
    dirs_original = lm._diretorios_licenca
    trial_original = lm._caminho_registro_teste
    estado_original = dict(lm._ESTADO)
    blacklist_original = lm.esta_na_lista_negra
    lm.CHAVE_PUBLICA_PEM = publico

    try:
        with tempfile.TemporaryDirectory() as tmp:
            lm._diretorios_licenca = lambda: [tmp]
            trial = os.path.join(tmp, lm.NOME_ARQUIVO_TESTE)
            lm._caminho_registro_teste = lambda: trial
            caminho = os.path.join(tmp, lm.NOME_ARQUIVO_LICENCA)

            ok, motivo, _ = lm.verificar_licenca(consultar_lista_negra=False)
            checar("primeiro uso → teste de 30 dias com tudo liberado",
                   ok and motivo.startswith("Período de teste")
                   and lm.em_periodo_teste()
                   and lm.status_licenca()["dias_restantes"] == lm.DIAS_TESTE
                   and not lm.modo_demonstracao(), motivo)

            _gravar_teste(trial, mid, inicio_dias=lm.DIAS_TESTE)
            ok, motivo, _ = lm.verificar_licenca(consultar_lista_negra=False)
            checar("após 30 dias → modo demonstração",
                   not ok and motivo == "Período de teste encerrado"
                   and lm.modo_demonstracao(), motivo)

            _gravar_teste(trial, mid, inicio_dias=lm.DIAS_TESTE - 1)
            ok, motivo, _ = lm.verificar_licenca(consultar_lista_negra=False)
            checar("último dia ainda libera tudo",
                   ok and lm.status_licenca()["dias_restantes"] == 1
                   and not lm.modo_demonstracao(), motivo)

            _gravar_teste(trial, mid, inicio_dias=lm.DIAS_TESTE - 1,
                          ultima_dias=20)
            ok, _, _ = lm.verificar_licenca(consultar_lista_negra=False)
            checar("relógio atrasado não aumenta o teste",
                   not ok and lm.modo_demonstracao())

            _gravar_teste(trial, mid, inicio_dias=1)
            lm.esta_na_lista_negra = lambda machine_id: True
            ok, motivo, _ = lm.verificar_licenca(consultar_lista_negra=True)
            checar("lista negra bloqueia também o teste",
                   not ok and motivo == "Licença revogada", motivo)

            _gravar_teste(trial, mid, inicio_dias=1)
            lm.esta_na_lista_negra = lambda machine_id: False
            ok, _, _ = lm.verificar_licenca(consultar_lista_negra=False)
            checar("teste libera todos os slides de anúncio",
                   ok and lm.em_periodo_teste()
                   and len(lm.limitar_slides_anuncio(
                       ["a", "b", "c", "d", "e"])) == 5)

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
            anuncio_demo = {"titulo": "T", "texto": "a\n\nb\n\nc\n\nd"}
            checar("projeção comum do anúncio continua limitada no demo",
                   len(_montar_slides_anuncio(anuncio_demo)) == 3)
            checar("janela Anúncios projeta todos os slides no demo",
                   len(_montar_slides_anuncio(
                       anuncio_demo, aplicar_limite=False)) == 5)
            lm._definir_estado(True, "Licenciado", machine_id=mid)
            checar("modo licenciado não limita anúncios",
                   len(lm.limitar_slides_anuncio(["a", "b", "c", "d", "e"]))
                   == 5)
    finally:
        lm.CHAVE_PUBLICA_PEM = publico_original
        lm._diretorios_licenca = dirs_original
        lm._caminho_registro_teste = trial_original
        lm.esta_na_lista_negra = blacklist_original
        lm._ESTADO.clear()
        lm._ESTADO.update(estado_original)

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
