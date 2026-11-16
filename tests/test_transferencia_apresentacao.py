#!/usr/bin/env python3
"""Apresentações das ordens de serviço na transferência .navepro.

Antes, só o caminho da apresentação era exportado (com o token {{HOME}});
o arquivo .pptx/.odp ficava no computador de origem e a ordem quebrava no
outro. Agora o arquivo entra no ZIP em apresentacoes/ e a importação copia
para os uploads, apontando o item para a cópia local.

Cobre também o membro malicioso com ".." (não pode ler fora do temp_dir).
"""

import json
import os
import shutil
import sys
import tempfile
import zipfile

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import navepro.core.transferencia as tr  # noqa: E402


def _item_servico(caminho: str) -> dict:
    return {
        "id": 1,
        "tipo": "sermao",
        "referencia_id": None,
        "titulo_custom": os.path.splitext(os.path.basename(caminho))[0],
        "caminho_arquivo": caminho,
        "letra_snapshot": "",
    }


def _rodar() -> int:
    falhas = 0

    def checar(desc, cond, extra=""):
        nonlocal falhas
        print(f"{'OK ' if cond else 'X  '} {desc}"
              f"{(' -> ' + extra) if extra else ''}")
        if not cond:
            falhas += 1

    checar("membro seguro dentro da pasta é aceito",
           tr._membro_local_seguro("/tmp/base", "apresentacoes/a.pptx")
           == os.path.join("/tmp/base", "apresentacoes", "a.pptx"))
    checar("membro com .. é recusado",
           tr._membro_local_seguro(
               "/tmp/base", "apresentacoes/../../etc/passwd") is None)
    checar("membro absoluto é recusado",
           tr._membro_local_seguro("/tmp/base", "/etc/passwd") is None)

    with tempfile.TemporaryDirectory() as raiz:
        pasta = os.path.join(raiz, "Igreja")
        os.makedirs(pasta)
        apresentacao = os.path.join(pasta, "Culto de domingo.pptx")
        video = os.path.join(pasta, "sermao.mp4")
        with open(apresentacao, "wb") as f:
            f.write(b"pptx-conteudo")
        with open(video, "wb") as f:
            f.write(b"video-conteudo")

        servicos = {
            "servicos": [{
                "id": 7, "nome": "Culto", "itens": [
                    _item_servico(apresentacao),
                    _item_servico(video),
                ]}],
            "_proximo_id_servico": 8, "_proximo_id_item": 3,
        }
        pacote = os.path.join(raiz, "culto.navepro")
        resumo = tr.exportar_transferencia(
            pacote, [], servicos, incluir_midia=False)

        checar("exportação inclui a apresentação mesmo sem mídia dos anúncios",
               resumo.get("apresentacoes") == 1, str(resumo))
        with zipfile.ZipFile(pacote, "r") as zf:
            membros = set(zf.namelist())
            exportado = json.loads(
                zf.read(tr.ARQ_SERVICOS).decode("utf-8"))
        checar("arquivo da apresentação entra no pacote",
               "apresentacoes/Culto de domingo.pptx" in membros,
               str(sorted(membros)))
        checar("vídeo escolhido no item continua fora do pacote",
               not any(m.lower().endswith(".mp4") for m in membros))
        itens_exp = exportado["servicos"][0]["itens"]
        caminhos_exp = [it.get("caminho_arquivo") for it in itens_exp]
        checar("item aponta para o membro do ZIP",
               "apresentacoes/Culto de domingo.pptx" in caminhos_exp,
               str(caminhos_exp))
        checar("exportação não altera o item em memória",
               servicos["servicos"][0]["itens"][0]["caminho_arquivo"]
               == apresentacao)

        uploads = os.path.join(raiz, "uploads")
        os.makedirs(uploads)

        def copiar_midia(origem: str):
            destino = os.path.join(uploads, os.path.basename(origem))
            shutil.copy2(origem, destino)
            return destino

        backup_original = tr.criar_backup
        tr.criar_backup = lambda *a, **k: "backup-fake"
        try:
            recebido = {}

            def _salvar(dados):
                recebido.update(dados)
                return True

            resumo_imp = tr.importar_transferencia(
                pacote,
                {"servicos": [], "_proximo_id_servico": 1,
                 "_proximo_id_item": 1},
                listar_anuncios=lambda: [],
                inserir_anuncio=lambda _dados: None,
                atualizar_anuncio=lambda _id, _dados: False,
                copiar_midia=copiar_midia,
                salvar_servicos=_salvar,
            )
        finally:
            tr.criar_backup = backup_original

        checar("importação conta a apresentação copiada",
               resumo_imp.get("apresentacoes_copiadas") == 1, str(resumo_imp))
        itens = (recebido.get("servicos") or [{}])[0].get("itens") or []
        item_apres = next(
            (it for it in itens
             if (it.get("caminho_arquivo") or "").lower().endswith(".pptx")),
            {})
        caminho_local = item_apres.get("caminho_arquivo") or ""
        checar("item importado aponta para a cópia local",
               os.path.dirname(caminho_local) == uploads,
               caminho_local)
        checar("apresentação importada existe e mantém o conteúdo",
               bool(caminho_local) and os.path.isfile(caminho_local)
               and open(caminho_local, "rb").read() == b"pptx-conteudo")

        # Reexportar sem apresentações (usado no backup) não inclui o arquivo.
        sem_apres = os.path.join(raiz, "backup.navepro")
        resumo_backup = tr.exportar_transferencia(
            sem_apres, [], servicos, incluir_midia=False,
            incluir_apresentacoes=False)
        with zipfile.ZipFile(sem_apres, "r") as zf:
            membros_backup = set(zf.namelist())
        checar("exportação sem apresentações não inclui o arquivo",
               resumo_backup.get("apresentacoes") == 0
               and not any(m.startswith("apresentacoes/")
                           for m in membros_backup))

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
