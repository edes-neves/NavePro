"""Medição e desenho de texto com PIL para os anúncios.

Reúne a localização de fonte TTF, o carregamento de fontes PIL, a quebra de
linhas por medição real e o cálculo das caixas de texto em espaço virtual
1440x1080 — usados de forma IDÊNTICA pelo editor (prévia) e pelo telão
(projeção). Extraído de NavePro.py sem alteração de comportamento.
"""

from __future__ import annotations

import json
import os
import re

from navepro.core.ambiente import _eh_windows

_FONTE_PIL_CACHE: dict[str, str | None] = {}


def _procurar_fonte_no_sistema(negrito: bool = True) -> str | None:
    """Procura um TTF/OTF adequado nas pastas de fontes do sistema.

    Primeiro pelos nomes conhecidos (DejaVu, Liberation, FreeSans, Arial).
    Se nenhum existir — caso de distros que só trazem outra família, como
    algumas edições do BigLinux/GNOME — aceita QUALQUER .ttf/.otf instalado,
    preferindo o peso pedido (negrito/normal) e família sans. O que não pode
    acontecer é cair na fonte padrão do PIL (fixa em ~10 px), que deixava o
    texto minúsculo e sem reação ao A−/A+.
    """
    if negrito:
        nomes = ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf",
                 "LiberationSans-Bold.ttf", "LiberationSans-Regular.ttf",
                 "FreeSansBold.ttf", "arialbd.ttf", "arial.ttf")
    else:
        nomes = ("DejaVuSans.ttf", "LiberationSans-Regular.ttf",
                 "FreeSans.ttf", "arial.ttf",
                 "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf",
                 "arialbd.ttf")
    raizes = [
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        "/opt/fonts",
        os.path.join(os.path.expanduser("~"), ".local/share/fonts"),
        os.path.join(os.path.expanduser("~"), ".fonts"),
    ]
    avulsas: list[tuple] = []
    for raiz in raizes:
        if not os.path.isdir(raiz):
            continue
        for dirpath, _dirs, arquivos in os.walk(raiz):
            for nome in nomes:
                if nome in arquivos:
                    return os.path.join(dirpath, nome)
            for arquivo in arquivos:
                if arquivo.lower().endswith((".ttf", ".otf")):
                    avulsas.append((dirpath, arquivo))
    if avulsas:
        # Preferência: peso pedido > sans > ordem alfabética (determinístico).
        def _peso(item: tuple) -> tuple:
            _dir, arquivo = item
            baixo = arquivo.lower()
            return (0 if (("bold" in baixo) == negrito) else 1,
                    0 if ("sans" in baixo or "dejavu" in baixo) else 1,
                    baixo)
        avulsas.sort(key=_peso)
        dirpath, arquivo = avulsas[0]
        return os.path.join(dirpath, arquivo)
    return None


def _localizar_fonte_ttf(negrito: bool = True) -> str | None:
    """Localiza (e memoriza) um TTF usado para medir/desenhar texto.

    Por padrão devolve o peso negrito (comportamento histórico do app); com
    ``negrito=False`` devolve o regular, necessário para o texto rico (só o
    trecho marcado sai em negrito).

    Cobre Debian/Ubuntu, Arch, Fedora e a runtime do Flatpak
    (org.freedesktop.Platform), onde o DejaVu fica em /usr/share/fonts/dejavu
    e NÃO em /usr/share/fonts/truetype/dejavu. Antes, no Flatpak, nenhum
    caminho existia e o PIL caía na fonte padrão de 10 px — o texto saía
    minúsculo no telão e o A−/A+ não surtia efeito.
    """
    cache = _FONTE_PIL_CACHE
    chave = "path" if negrito else "path_regular"
    if chave in cache:
        return cache[chave]
    if _eh_windows():
        if negrito:
            nomes = ('arialbd.ttf', 'arial.ttf')
        else:
            nomes = ('arial.ttf', 'arialbd.ttf')
        candidatos = [
            os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts', n)
            for n in nomes
        ]
        encontrado = next((p for p in candidatos if os.path.exists(p)), None)
    else:
        if negrito:
            candidatos = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/gnu-free/FreeSansBold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            ]
        else:
            candidatos = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/TTF/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/gnu-free/FreeSans.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
            ]
        encontrado = next((p for p in candidatos if os.path.exists(p)), None)
        if encontrado is None:
            encontrado = _procurar_fonte_no_sistema(negrito)
    cache[chave] = encontrado
    return encontrado


def _carregar_fonte_pil(tamanho: int, negrito: bool = True):
    """Carrega uma fonte Truetype com fallback para a padrão do PIL."""
    try:
        from PIL import ImageFont
    except Exception:
        return None
    caminho = _localizar_fonte_ttf(negrito)
    if caminho:
        try:
            return ImageFont.truetype(caminho, tamanho)
        except Exception:
            pass
    # Último recurso antes da fonte embutida: deixa o próprio Pillow procurar
    # pelo nome da família (alguns builds resolvem via fontconfig).
    if negrito:
        nomes = ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf",
                 "LiberationSans-Bold.ttf", "arialbd.ttf")
    else:
        nomes = ("DejaVuSans.ttf", "LiberationSans-Regular.ttf",
                 "arial.ttf", "DejaVuSans-Bold.ttf")
    for _nome in nomes:
        try:
            return ImageFont.truetype(_nome, tamanho)
        except Exception:
            continue
    # Fallback final: a fonte padrão do PIL. No Pillow >= 10.1 ela aceita
    # 'size', então o texto continua acompanhando o redimensionamento (A−/A+)
    # mesmo quando nenhum TTF está acessível.
    try:
        return ImageFont.load_default(size=tamanho)
    except TypeError:
        return ImageFont.load_default()


def _quebrar_linhas_medindo(draw, texto: str, largura_max: int, fonte) -> list[str]:
    """Quebra o texto em linhas que cabem em 'largura_max' (medição real)."""
    linhas: list[str] = []
    for bloco in (texto or "").split("\n"):
        if not bloco.strip():
            linhas.append("")
            continue
        palavras = bloco.split()
        atual = ""
        for p in palavras:
            tent = f"{atual} {p}".strip()
            try:
                cabe = draw.textlength(tent, font=fonte) <= largura_max
            except Exception:
                cabe = len(tent) * fonte.size * 0.6 <= largura_max
            if cabe:
                atual = tent
            else:
                if atual:
                    linhas.append(atual)
                atual = p
        if atual:
            linhas.append(atual)
    return linhas


def _carregar_fonte_atual(draw, texto: str, largura_max: int, altura_max: int):
    """Escolhe a maior fonte cujo texto (quebrado) cabe na área."""
    for tamanho in (120, 96, 72, 64, 48, 40, 36, 32, 28, 24, 22, 20, 18, 16, 14, 12):
        fonte = _carregar_fonte_pil(tamanho)
        linhas = _quebrar_linhas_medindo(draw, texto, largura_max, fonte)
        tam_linha = fonte.size + max(1, fonte.size // 5)
        if tam_linha * len(linhas) <= altura_max:
            return fonte, linhas
    fonte = _carregar_fonte_pil(12)
    return fonte, _quebrar_linhas_medindo(draw, texto, largura_max, fonte)


_DUMMY_DRAW: list = [None]


def _draw_pil_reciclavel():
    """Devolve um objeto de desenho PIL reutilizável para medir texto."""
    from PIL import Image, ImageDraw
    if _DUMMY_DRAW[0] is None:
        _DUMMY_DRAW[0] = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    return _DUMMY_DRAW[0]


def _fonte_familia_do_pil(fonte) -> str:
    """Nome da família da fonte PIL (para usar no canvas do Tk)."""
    if fonte is None:
        return "Helvetica"
    try:
        return fonte.getname()[0] or "Helvetica"
    except Exception:
        return "Helvetica"


# ── Texto rico dos anúncios (negrito e cor por trecho) ──────────────
#
# A formatação é guardada no próprio texto, com marcas simples que o
# operador vê e pode editar/apagar como qualquer outro caractere:
#
#   **texto**              → negrito
#   {c:#RRGGBB}texto{/c}   → cor do trecho
#
# Marca sem fechamento é tratada como texto comum (nunca "engole" o que
# o operador digitou). Texto sem marca continua sendo desenhado pelo
# caminho antigo (tudo em negrito), preservando os anúncios existentes.

_RE_COR_RICA = re.compile(r"#[0-9a-fA-F]{6}")


def _analisar_texto_rico(texto: str) -> tuple[list[tuple[str, bool, str | None]], bool]:
    """Divide o texto em trechos (texto, negrito, cor) e diz se há marcação."""
    runs: list[tuple[str, bool, str | None]] = []
    buffer: list[str] = []
    cores: list[str] = []
    negrito = False
    marcou = False
    texto = texto or ""
    total = len(texto)
    i = 0

    def _descarregar() -> None:
        if buffer:
            cor = cores[-1] if cores else None
            runs.append(("".join(buffer), negrito, cor))
            buffer.clear()

    while i < total:
        if texto.startswith("**", i) and (
                negrito or texto.find("**", i + 2) != -1):
            _descarregar()
            negrito = not negrito
            marcou = True
            i += 2
            continue
        if texto.startswith("{c:", i):
            fim = texto.find("}", i + 3)
            if fim != -1:
                cor = texto[i + 3:fim].strip().lower()
                fecha = texto[fim + 1:].lower().find("{/c}")
                if _RE_COR_RICA.fullmatch(cor) and fecha != -1:
                    _descarregar()
                    cores.append(cor)
                    marcou = True
                    i = fim + 1
                    continue
        if cores and texto[i:i + 4].lower() == "{/c}":
            _descarregar()
            cores.pop()
            marcou = True
            i += 4
            continue
        buffer.append(texto[i])
        i += 1
    _descarregar()
    return runs, marcou


def _parse_texto_rico(texto: str) -> list[tuple[str, bool, str | None]]:
    """Trechos (texto, negrito, cor) do texto, descartando as marcas válidas."""
    return _analisar_texto_rico(texto)[0]


def _texto_tem_formatacao(texto: str) -> bool:
    """True quando o texto usa ao menos uma marca válida de negrito/cor."""
    return _analisar_texto_rico(texto)[1]


def _texto_simples(texto: str) -> str:
    """Texto sem as marcas de formatação (para listas, prévias e slides)."""
    return "".join(trecho for trecho, _negrito, _cor in _parse_texto_rico(texto))


# Fração da ALTURA da caixa de texto que corresponde ao tamanho de fonte
# "de projeto". A caixa do compositor foi desenhada para ~3 linhas de texto
# preenchendo a caixa, ou seja 1/(3 * 1.2) ≈ 0.28. O valor antigo era 0.10,
# que desenhava o anúncio com menos de um terço do tamanho pretendido (letra
# miúda no telão) e ainda fazia o A−/A+ não ter efeito visível.
_PCT_FONTE_CAIXA = 0.28


def _calcular_texto_em_caixa(texto: str, caixa_larg: int, caixa_alt: int,
                             base_pct: float = _PCT_FONTE_CAIXA,
                             limite_alt: int | None = None) -> tuple:
    """Calcula fonte + linhas para desenhar 'texto' dentro de uma caixa.

    Usado pelo editor de anúncio (prévia) e pelo telão de forma IDÊNTICA:
    a fonte é proporcional à ALTURA DA CAIXA (base_pct * caixa_alt) e as
    linhas são quebradas na largura da caixa. Se o texto não couber em
    'limite_alt', encolhe até caber (respeitando um mínimo legível).
    'limite_alt' é a altura máxima do bloco de texto: os dois chamadores
    passam a altura da tela, porque a caixa é um guia de layout (posição e
    largura) e não deve espremer a letra — assim o A−/A+ muda a fonte de
    verdade e o texto, centralizado na caixa, cresce para os dois lados.
    Retorna (fonte_pil, linhas).
    """
    desenho = _draw_pil_reciclavel()
    larg = max(60, caixa_larg)
    alt = max(60, caixa_alt)
    limite = max(60, int(limite_alt)) if limite_alt else alt
    texto_fonte = (texto or "")

    def _medir(tam: int) -> tuple:
        """(fonte, linhas, altura do bloco) para a fonte de tamanho 'tam'."""
        fonte = _carregar_fonte_pil(tam)
        linhas = _quebrar_linhas_medindo(desenho, texto_fonte, larg, fonte)
        tam_linha = fonte.size + max(1, fonte.size // 5)
        return fonte, linhas, tam_linha * max(1, len(linhas))

    base = max(12, min(400, int(round(alt * (base_pct or _PCT_FONTE_CAIXA)))))
    # Procura o MAIOR tamanho que cabe em 'limite'. A lista de tamanhos fixos
    # anterior fazia o A+/A− "empacar" num valor da lista (e às vezes até
    # diminuir a fonte), então o operador não conseguia mexer no tamanho.
    # Primeiro desce (pulando pelo tamanho estimado, para não ficar lento com
    # texto longo) e depois sobe em passos pequenos até não caber mais: assim
    # o resultado acompanha o A−/A+ e nunca diminui sozinho.
    tam = base
    fonte, linhas, bloco = _medir(tam)
    while bloco > limite and tam > 12:
        passo = max(1, int(tam * 0.03))
        alvo = max(12, min(int(tam * limite / max(1, bloco)) - passo, tam - 1))
        tam = alvo
        fonte, linhas, bloco = _medir(tam)
    while tam < base:
        maior = min(base, tam + max(1, int(tam * 0.03)))
        f2, l2, b2 = _medir(maior)
        if b2 > limite:
            break
        tam, fonte, linhas = maior, f2, l2
    return fonte, linhas


def _limite_altura_texto(caixa_alt: int, escala: float = 1.0,
                         tela_alt: int = 0) -> int:
    """Altura máxima do bloco de texto para o auto-ajuste.

    Na escala normal (A−/A+ em 1.0) o texto cabe na PRÓPRIA CAIXA: é o que o
    operador vê na prévia ao redimensioná-la. Escalas maiores que 1.0 podem
    passar da caixa (até 92% da tela), pois são um aumento explícito.
    """
    caixa = max(60, int(caixa_alt or 0))
    if tela_alt:
        limite_tela = int(max(60, tela_alt) * 0.92)
    else:
        limite_tela = caixa
    if float(escala or 1.0) > 1.0 + 1e-9:
        return max(caixa, limite_tela)
    return min(limite_tela, caixa)


def _quebrar_linhas_ricas(runs: list, largura_max: int, fontes: dict,
                          draw) -> tuple[list, list]:
    """Quebra os trechos em linhas, medindo cada palavra com seu peso.

    Devolve (linhas, larguras). Cada linha é uma lista de
    (texto, negrito, cor, largura) já compactada — trechos vizinhos com o
    mesmo estilo viram um só, para o desenho não sair picado.
    """
    tokens: list[tuple[str, bool, str | None]] = []
    for trecho, negrito, cor in runs:
        for parte in re.findall(r"\n|[^\S\n]+|\S+", trecho or ""):
            tokens.append((parte, negrito, cor))
    linhas: list[tuple[list, float]] = []
    atual: list[tuple[str, bool, str | None, float]] = []
    largura_atual = 0.0

    def _largura(parte: str, negrito: bool) -> float:
        fonte = fontes.get(bool(negrito)) or fontes.get(False)
        try:
            return float(draw.textlength(parte, font=fonte))
        except Exception:
            try:
                return float(len(parte) * fonte.size * 0.6)
            except Exception:
                return float(len(parte) * 10)

    def _fechar() -> None:
        nonlocal atual, largura_atual
        while atual and atual[-1][0] and not atual[-1][0].strip():
            removido = atual.pop()
            largura_atual -= removido[3]
        compacta: list[tuple[str, bool, str | None, float]] = []
        for item in atual:
            if (compacta and compacta[-1][1] == item[1]
                    and compacta[-1][2] == item[2]):
                ant = compacta[-1]
                compacta[-1] = (ant[0] + item[0], item[1], item[2],
                                ant[3] + item[3])
            else:
                compacta.append(item)
        linhas.append((compacta, max(0.0, largura_atual)))
        atual = []
        largura_atual = 0.0

    for parte, negrito, cor in tokens:
        if parte == "\n":
            _fechar()
            continue
        if not parte.strip():
            if atual:
                w = _largura(parte, negrito)
                atual.append((parte, negrito, cor, w))
                largura_atual += w
            continue
        w = _largura(parte, negrito)
        if atual and largura_atual + w > largura_max:
            _fechar()
        atual.append((parte, negrito, cor, w))
        largura_atual += w
    if atual or not linhas:
        _fechar()
    resultado = [[(t, n, c, w) for t, n, c, w in linha]
                 for linha, _larg in linhas]
    larguras = [int(round(larg)) for _linha, larg in linhas]
    return resultado, larguras


def _layout_texto_rico(texto: str, caixa_larg: int, caixa_alt: int,
                       base_pct: float = _PCT_FONTE_CAIXA,
                       limite_alt: int | None = None,
                       negrito_base: bool = False,
                       alinhamento: str = "center") -> dict:
    """Calcula fonte, linhas e posição dos trechos dentro da caixa.

    Usado de forma IDÊNTICA pela prévia do editor e pelo telão. A fonte é
    proporcional à altura da caixa e encolhe para o bloco caber em
    'limite_alt' (por padrão, a própria caixa) e na largura útil. Trechos
    com negrito/cor mantêm o estilo por linha.

    Retorna um dict com 'linhas' (cada item: texto, negrito, cor, largura),
    'larguras', 'altura_linha', 'altura_bloco', 'tamanho', 'padding',
    'largura_util', 'altura_util', 'alinhamento', 'fontes' e 'tem_formatacao'.
    """
    runs, tem = _analisar_texto_rico(texto or "")
    if not tem:
        runs = [(texto or "", negrito_base, None)]
    larg = max(60, int(caixa_larg))
    alt = max(60, int(caixa_alt))
    limite = max(60, int(limite_alt)) if limite_alt else alt
    pad = max(2, int(min(larg, alt) * 0.02))
    larg_util = max(20, larg - pad * 2)
    alt_util = max(20, limite - pad * 2)
    desenho = _draw_pil_reciclavel()

    def _medir(tam: int) -> tuple:
        fontes = {False: _carregar_fonte_pil(tam, negrito=False),
                  True: _carregar_fonte_pil(tam, negrito=True)}
        linhas, larguras = _quebrar_linhas_ricas(
            runs, larg_util, fontes, desenho)
        altura_linha = tam + max(1, tam // 5)
        altura_bloco = altura_linha * max(1, len(linhas))
        largura_max = max(larguras, default=0)
        return fontes, linhas, larguras, altura_linha, altura_bloco, largura_max

    base = max(12, min(400, int(round(alt * (base_pct or _PCT_FONTE_CAIXA)))))
    tam = base
    fontes, linhas, larguras, altura_linha, bloco, larg_max = _medir(tam)
    # Mínimo de 8 px: é o menor tamanho que a prévia e o telão desenham, então
    # encolher abaixo disso só faria o layout medir uma coisa e desenhar
    # outra. Texto muito longo numa caixa pequena chega nesse piso.
    while (bloco > alt_util or larg_max > larg_util) and tam > 8:
        fator = min(1.0,
                    alt_util / max(1, bloco),
                    larg_util / max(1, larg_max))
        tam = max(8, min(tam - 1, int(tam * fator) - 1))
        fontes, linhas, larguras, altura_linha, bloco, larg_max = _medir(tam)
    while tam < base:
        maior = min(base, tam + max(1, int(tam * 0.03)))
        f2, l2, larg2, alt_linha2, bloco2, larg_max2 = _medir(maior)
        if bloco2 > alt_util or larg_max2 > larg_util:
            break
        tam = maior
        fontes, linhas, larguras = f2, l2, larg2
        altura_linha, bloco, larg_max = alt_linha2, bloco2, larg_max2
    return {
        "tamanho": tam,
        "linhas": linhas,
        "larguras": larguras,
        "altura_linha": altura_linha,
        "altura_bloco": bloco,
        "largura_max": larg_max,
        "tem_formatacao": tem,
        "negrito_base": negrito_base,
        "padding": pad,
        "largura_util": larg_util,
        "altura_util": alt_util,
        "alinhamento": alinhamento,
        "fontes": fontes,
    }


def _caixa_texto_padrao(texto: str, area_larg: int, area_alt: int,
                        margem_h: int, margem_v: int,
                        aspect_imagem: float | None = None, espaco: int = 20) -> dict:
    """Caixa inicial (espaço virtual 1440x1080) para o texto do anúncio.

    Usa o mesmo layout lado a lado do compositor legado (texto à esquerda,
    imagem à direita). O tamanho é escolhido para que o texto inicial couba
    exatamente como na projeção/composição antiga. Se 'aspect_imagem' for
    dado, a largura do texto reflete o espaço real que sobra após a imagem
    (55%) + espaçamento. Retorna dict com x/y/w/h (posição/tamanho da caixa)
    e s (fator de escala de fonte).
    """
    if aspect_imagem is not None and aspect_imagem > 0:
        asp = aspect_imagem
        img_w = max(120, int(area_larg * 0.55))
        img_h = int(img_w / asp)
        if img_h > area_alt:
            img_h = int(area_alt)
            img_w = max(120, int(img_h * asp))
        text_w = max(120, area_larg - img_w - max(0, espaco))
    else:
        text_w = max(120, int(area_larg * 0.55))
    texto_fonte = (texto or "")
    desenho = _draw_pil_reciclavel()
    fonte_enc, _ = _carregar_fonte_atual(desenho, texto_fonte, text_w,
                                         max(120, int(area_alt * 0.55)))
    passo = fonte_enc.size + max(1, fonte_enc.size // 5)
    altura_caixa = max(120, min(int(area_alt), passo * 4))
    largura_caixa = max(120, min(text_w, int(area_larg)))
    x = margem_h
    y = max(margem_v, (area_alt - altura_caixa) // 2)
    return {"x": x, "y": y, "w": largura_caixa, "h": altura_caixa, "s": 1.0}


def _caixa_texto_config(config_midia: str = "", texto: str = "",
                        aspect_imagem: float | None = None) -> dict:
    """Lê a caixa de texto (tx/ty/tw/th/ts) do config_midia, com defaults.

    Retorna dict já preenchido com x/y/w/h/s (posição da caixa + escala de
    fonte). Para configs antigas sem caixa de texto usa o layout lado a lado
    (o mesmo do compositor legado), calculado conforme o espaço virtual
    1440x1080.
    """
    try:
        c = json.loads(config_midia or "{}") or {}
    except (ValueError, TypeError, AttributeError):
        c = {}
    if not isinstance(c, dict):
        c = {}
    tx = int(c.get("tx") or 0)
    ty = int(c.get("ty") or 0)
    tw = int(c.get("tw") or 0)
    th = int(c.get("th") or 0)
    if th > 0 and (tw > 0 or tx > 0):
        return {"x": tx, "y": ty, "w": tw, "h": th, "s": float(c.get("ts") or 1.0)}
    if not texto:
        return {"x": 0, "y": 0, "w": 0, "h": 0, "s": 1.0}
    mh = int(1440 * 0.04) or 40
    mv = int(1080 * 0.06) or 60
    area_larg = 1440 - mh * 2
    area_alt = 1080 - mv * 2
    if tw > 0 and th > 0:
        return {"x": tx, "y": ty, "w": tw, "h": th, "s": float(c.get("ts") or 1.0)}
    return _caixa_texto_padrao(texto, area_larg, area_alt, mh, mv,
                               aspect_imagem=aspect_imagem)
