#!/usr/bin/env python3
"""Portabilidade da Ordem de Serviço na transferência .navepro.

O caminho_arquivo escolhido no editor de item é absoluto e trazia o nome do
usuário de origem. Ao importar em outra máquina (mesmas pastas/arquivos, mas
outro usuário do sistema) a ordem quebrava e era preciso editar o JSON na mão.

A exportação passa a trocar a pasta do usuário pelo token {{HOME}} e a
importação reexpande para a pasta do usuário atual. Caminhos fora da pasta do
usuário e pacotes antigos (sem token) continuam intactos.
"""

import json
import os
import sys
import tempfile
import zipfile

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import navepro.core.transferencia as tr  # noqa: E402


def _definir_home(caminho: str) -> None:
    os.environ["HOME"] = caminho
    os.environ["USERPROFILE"] = caminho


def _item_servico(caminho: str) -> dict:
    return {
        "id": 1,
        "tipo": "video",
        "referencia_id": None,
        "titulo_custom": "Sermão de domingo",
        "caminho_arquivo": caminho,
        "letra_snapshot": "",
    }


def _rodar() -> int:
    falhas = 0

    def checar(desc, cond):
        nonlocal falhas
        print(f"{'OK ' if cond else 'X  '} {desc}")
        if not cond:
            falhas += 1

    home_antigo = os.environ.get("HOME")
    perfil_antigo = os.environ.get("USERPROFILE")
    try:
        with tempfile.TemporaryDirectory() as raiz:
            origem = os.path.join(raiz, "home-ana")
            destino = os.path.join(raiz, "home-joao")
            relativo = os.path.join("Igreja", "Sermoes", "domingo.mp4")
            arquivo_origem = os.path.join(origem, relativo)
            arquivo_destino = os.path.join(destino, relativo)
            for arquivo in (arquivo_origem, arquivo_destino):
                os.makedirs(os.path.dirname(arquivo), exist_ok=True)
                with open(arquivo, "wb") as f:
                    f.write(b"video")

            # ── 1. helpers isolados ──
            token = tr._caminho_para_portatil(arquivo_origem, home=origem)
            checar("exportação tokeniza a pasta do usuário",
                   token == f"{tr.TOKEN_HOME}/Igreja/Sermoes/domingo.mp4")
            checar("importação reexpande para a pasta do usuário atual",
                   tr._caminho_de_portatil(token, home=destino)
                   == arquivo_destino)
            checar("caminho fora da pasta do usuário fica intacto",
                   tr._caminho_para_portatil(
                       "/mnt/dados/domingo.mp4", home=origem)
                   == "/mnt/dados/domingo.mp4")
            checar("pacote antigo (caminho absoluto) fica intacto",
                   tr._caminho_de_portatil(
                       "/home/ana/Igreja/domingo.mp4", home=destino)
                   == "/home/ana/Igreja/domingo.mp4")

            # ── 2. exportação real: JSON gravado sem o usuário de origem ──
            servicos = {
                "servicos": [{
                    "id": 7, "nome": "Culto", "itens": [
                        _item_servico(arquivo_origem)]}],
                "_proximo_id_servico": 8, "_proximo_id_item": 2,
            }
            _definir_home(origem)
            pacote = os.path.join(raiz, "culto.navepro")
            tr.exportar_transferencia(pacote, [], servicos,
                                      incluir_midia=False)
            with zipfile.ZipFile(pacote, "r") as zf:
                exportado = json.loads(
                    zf.read(tr.ARQ_SERVICOS).decode("utf-8"))
            caminho_exportado = exportado["servicos"][0]["itens"][0][
                "caminho_arquivo"]
            checar("exportação grava o caminho portátil",
                   caminho_exportado
                   == f"{tr.TOKEN_HOME}/Igreja/Sermoes/domingo.mp4")
            checar("exportação não altera a ordem em memória",
                   servicos["servicos"][0]["itens"][0]["caminho_arquivo"]
                   == arquivo_origem)

            # ── 3. importação real: aponta para a pasta do novo usuário ──
            _definir_home(destino)
            capturado = {}

            def _salvar(dados):
                capturado.update(dados)
                return True

            tr.criar_backup = lambda *a, **k: "backup-fake"
            resumo = tr.importar_transferencia(
                pacote,
                {"servicos": [], "_proximo_id_servico": 1,
                 "_proximo_id_item": 1},
                listar_anuncios=lambda: [],
                inserir_anuncio=lambda dados: None,
                atualizar_anuncio=lambda _id, _dados: False,
                copiar_midia=lambda _origem: None,
                salvar_servicos=_salvar,
            )
            itens = (capturado.get("servicos") or [{}])[0].get("itens") or []
            caminho_importado = (itens[0] if itens else {}).get(
                "caminho_arquivo")
            checar("importação remapeia para a pasta do usuário atual",
                   caminho_importado == arquivo_destino)
            checar("arquivo do novo usuário existe (ordem volta a funcionar)",
                   bool(caminho_importado)
                   and os.path.isfile(caminho_importado))
            checar("importação conta a ordem de serviço",
                   resumo.get("servicos_novos") == 1)
    finally:
        if home_antigo is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = home_antigo
        if perfil_antigo is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = perfil_antigo

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
