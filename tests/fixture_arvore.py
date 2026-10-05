"""Árvore de pastas/arquivos usada pelos testes de seletor e de imagens.

Estes testes exercitam a listagem do app, que esconde tudo que começa com
"." e filtra os arquivos pelos sufixos pedidos. Em vez de depender de um
caminho fixo em /tmp — que não existe em máquina limpa nem no CI — o teste
monta a árvore aqui e recebe o caminho.

A lista sai ordenada com as pastas primeiro e depois os arquivos, por nome em
minúsculas (é o `sort` de `_listar_pastas_arquivos_usuario`). Por isso
`Documentos` aparece na posição 0 e precisa estar vazia.
"""

import os
import shutil
import tempfile

# Pastas visíveis; "Documentos" fica vazia de propósito e "Sub" guarda uma
# "Pasta" dentro, para o teste de nome que é pasta ver que o seletor entrou nela.
PASTAS = ('Documentos', 'Imagens', 'Sub')
SUB_PASTAS = ('Pasta',)

# "a.navepro" precisa existir para o teste de sobrescrita; os demais existem
# para provar que o filtro de sufixo esconde o que não foi pedido.
ARQUIVOS = ('a.navepro', 'b.txt', 'foto.png', 'FOTO.JPG', 'imagem.webp', 'nota.txt')

# Ocultos: nenhum deles pode aparecer na lista.
OCULTOS = ('.fundo.png', '.oculta.navepro', '.config')


def criar_arvore() -> str:
    """Cria a árvore num diretório temporário e devolve o caminho dela."""
    raiz = tempfile.mkdtemp(prefix='navepro-arvore-')
    for pasta in PASTAS:
        os.makedirs(os.path.join(raiz, pasta))
    for pasta in SUB_PASTAS:
        os.makedirs(os.path.join(raiz, 'Sub', pasta))
    for nome in ARQUIVOS + OCULTOS:
        with open(os.path.join(raiz, nome), 'w') as arq:
            arq.write(nome)
    return raiz


def limpar_arvore(raiz: str) -> None:
    """Remove a árvore criada por `criar_arvore`."""
    shutil.rmtree(raiz, ignore_errors=True)
