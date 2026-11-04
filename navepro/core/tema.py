"""Cores e mapas do tema da interface (painel do administrador / monitor 1).

O tema ESCURO atual permanece intacto e é o padrão. O tema CLARO é uma
opção extra: as cores escuras hardcoded na interface são convertidas em
tempo de execução pela tabela abaixo, sem alterar nenhuma cor do código
existente. As cores de projeção/relógio do TELÃO NÃO são tocadas.
"""


# Tom cinza próprio da faixa de controles (botões do rodapé) e do campo de
# resultados da busca no tema CLARO. Serve de referência: o restante do painel
# usa tons um pouco mais escuros que este, para que essas duas áreas se
# destaquem.
COR_AREA_CONTROLES_CLARA: str = '#c2cad3'

# Mapa: cor ESCURA atual -> cor equivalente no tema CLARO.
MAPA_COR_CLARA: dict[str, str] = {
    # Superfícies: mesma hierarquia do tema ESCURO (janela < cartões <
    # entradas), em tons de cinza mais escuros que a faixa de controles/lista
    # (#c2cad3) — a janela é a base, os cartões sobem um tom e as entradas
    # ficam um pouco mais claras.
    '#0d1117': '#aeb9c4',   # fundo principal da janela (base)
    '#161b22': '#b5c0ca',   # cards/containers (um pouco mais claro)
    '#1c2128': '#b5c0ca',   # linha alternada (par) da lista
    '#21262d': '#bcc6d0',   # entradas/botões neutros/lista (mais claro)
    '#30363d': '#93a0ac',   # bordas/separadores/hover (mais escuro que a base)
    '#eaeef2': '#bcc6d0',   # campos Cidade/UF (fundo claro fixo no escuro)
    # Roxos (accent)
    '#6e40c9': '#8250df',
    '#8b5cf6': '#8250df',
    '#8957e5': '#8250df',
    '#a371f7': '#8250df',
    '#a78bfa': '#8250df',
    # Verdes (sucesso)
    '#238636': '#1a7f37',
    '#2ea043': '#2ea043',
    '#3fb950': '#2ea043',
    # Azuis (info)
    '#1f6feb': '#0969da',
    '#388bfd': '#388bfd',
    '#58a6ff': '#0969da',
    # Vermelhos (perigo)
    '#da3633': '#cf222e',
    '#f85149': '#f85149',
    # Textos fixos
    '#c9d1d9': '#1f2328',   # texto normal
    '#8b949e': '#4b5563',   # texto secundário/muted
}

_MAPA_COR_CLARA_UP: dict[str, str] = {
    chave.upper(): valor for chave, valor in MAPA_COR_CLARA.items()
}

# Cores fortes do tema claro (mantêm texto branco por cima)
_CORES_FORTES_CLARO: frozenset = frozenset({
    '#8250df', '#6e40c9',                                              # roxos
    '#1a7f37', '#2ea043', '#238636',                                    # verdes
    '#0969da', '#388bfd', '#1f6feb', '#58a6ff',                        # azuis
    '#cf222e', '#da3633', '#f85149',                                   # vermelhos
})

# Fundos claros (texto branco fica ilegível em cima). As superfícies do tema
# claro usam a hierarquia '#aeb9c4', '#b5c0ca', '#bcc6d0' com '#93a0ac' para
# bordas e '#c2cad3' para a faixa de controles/lista; também mantém cores
# legadas (#ffffff/#f6f8fa/#eaeef2/#8b949e/#6e7681) por compatibilidade.
_FUNDOS_CLAROS: frozenset = frozenset({
    '#ffffff', '#f6f8fa', '#eaeef2', '#8b949e', '#6e7681',
    '#aeb9c4', '#b5c0ca', '#bcc6d0', '#93a0ac', '#c2cad3',
})

# Opções de cor do Tk que o tema pode recolorir por widget
_OPCOES_COR_TK: tuple[str, ...] = (
    'background', 'foreground',
    'activebackground', 'activeforeground',
    'highlightbackground', 'highlightcolor',
    'selectcolor', 'insertbackground',
    'selectbackground', 'selectforeground',
    'readonlybackground',
    'troughcolor', 'arrowcolor',
)

# Opções que representam TEXTO (precisam decidir a cor com base no fundo)
_OPCOES_TEXTO: frozenset = frozenset({
    'foreground', 'activeforeground', 'arrowcolor',
    'insertbackground', 'selectforeground',
})


def _cor_clara(cor: str | None, bg_final: str | None = None) -> str:
    """Devolve a equivalente CLARA da cor ESCURA `cor` (ou ela mesma).

    Amarelos e brancos dependem do contexto: sobre um fundo forte
    (roxo/verde/azul/vermelho) mantêm branco; sobre fundo claro viram
    um tom escuro legível.
    """
    if not cor:
        return '#000000'
    mapa = _MAPA_COR_CLARA_UP
    if cor.upper() in mapa:
        return mapa[cor.upper()]
    if cor in ('#f0c040', '#F5BE08'):
        if bg_final in _CORES_FORTES_CLARO:
            return '#ffffff'
        return '#24292f'
    if cor in ('#ffffff', '#FFFFFF'):
        if bg_final in _FUNDOS_CLAROS:
            return '#1f2328'
        return '#ffffff'
    return cor