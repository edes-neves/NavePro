"""Cores e mapas do tema da interface (painel do administrador / monitor 1).

O tema ESCURO atual permanece intacto e é o padrão. O tema CLARO é uma
opção extra: as cores escuras hardcoded na interface são convertidas em
tempo de execução pela tabela abaixo, sem alterar nenhuma cor do código
existente. As cores de projeção/relógio do TELÃO NÃO são tocadas.
"""

from typing import Optional


# Mapa: cor ESCURA atual -> cor equivalente no tema CLARO.
MAPA_COR_CLARA: dict[str, str] = {
    # Fundos
    '#0d1117': '#f6f8fa',   # fundo principal da janela
    '#161b22': '#ffffff',   # cards/containers
    '#21262d': '#ffffff',   # entradas/botões neutros/lista
    '#1c2128': '#f6f8fa',   # linha alternada (par) da lista
    '#30363d': '#d0d7de',   # bordas/separadores/hover neutro
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
    '#8b949e': '#656d76',   # texto secundário/muted
}

_MAPA_COR_CLARA_UP: dict[str, str] = {
    chave.upper(): valor for chave, valor in MAPA_COR_CLARA.items()
}

# Cores fortes do tema claro (mantêm texto branco por cima)
_CORES_FORTES_CLARO: frozenset = frozenset({
    '#8250df', '#6e40c9',                                              # roxos
    '#1a7f37', '#2ea043', '#238636', '#2ea043',                        # verdes
    '#0969da', '#388bfd', '#1f6feb', '#58a6ff',                        # azuis
    '#cf222e', '#da3633', '#f85149',                                   # vermelhos
})

# Fundos claros (texto branco fica ilegível em cima)
_FUNDOS_CLAROS: frozenset = frozenset({
    '#ffffff', '#f6f8fa', '#eaeef2',
})

# Opções de cor do Tk que o tema pode recolorir por widget
_OPCOES_COR_TK: tuple[str, ...] = (
    'background', 'foreground',
    'activebackground', 'activeforeground',
    'highlightbackground', 'highlightcolor',
    'selectcolor', 'insertbackground',
    'selectbackground', 'selectforeground',
    'troughcolor', 'arrowcolor',
)

# Opções que representam TEXTO (precisam decidir a cor com base no fundo)
_OPCOES_TEXTO: frozenset = frozenset({
    'foreground', 'activeforeground', 'arrowcolor',
    'insertbackground', 'selectforeground',
})


def _cor_clara(cor: Optional[str], bg_final: Optional[str] = None) -> str:
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