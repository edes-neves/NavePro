"""Medição e desenho de texto com PIL para os anúncios.

Reúne a localização de fonte TTF, o carregamento de fontes PIL, a quebra de
linhas por medição real e o cálculo das caixas de texto em espaço virtual
1440x1080 — usados de forma IDÊNTICA pelo editor (prévia) e pelo telão
(projeção). Extraído de NavePro.py sem alteração de comportamento.
"""

from __future__ import annotations

import json
import os

from navepro.core.ambiente import _eh_windows

_FONTE_PIL_CACHE: dict[str, str | None] = {}


def _procurar_fonte_no_sistema() -> str | None:
    """Procura um TTF/OTF adequado nas pastas de fontes do sistema.

    Primeiro pelos nomes conhecidos (DejaVu, Liberation, FreeSans, Arial).
    Se nenhum existir — caso de distros que só trazem outra família, como
    algumas edições do BigLinux/GNOME — aceita QUALQUER .ttf/.otf instalado,
    preferindo peso negrito e família sans. O que não pode acontecer é cair na
    fonte padrão do PIL (fixa em ~10 px), que deixava o texto minúsculo e sem
    reação ao A−/A+.
    """
    nomes = ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf",
             "LiberationSans-Bold.ttf", "LiberationSans-Regular.ttf",
             "FreeSansBold.ttf", "arialbd.ttf", "arial.ttf")
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
        # Preferência: negrito > sans > ordem alfabética (determinístico).
        def _peso(item: tuple) -> tuple:
            _dir, arquivo = item
            baixo = arquivo.lower()
            return (0 if "bold" in baixo else 1,
                    0 if ("sans" in baixo or "dejavu" in baixo) else 1,
                    baixo)
        avulsas.sort(key=_peso)
        dirpath, arquivo = avulsas[0]
        return os.path.join(dirpath, arquivo)
    return None


def _localizar_fonte_ttf() -> str | None:
    """Localiza (e memoriza) um TTF em negrito usado para medir/desenhar texto.

    Cobre Debian/Ubuntu, Arch, Fedora e a runtime do Flatpak
    (org.freedesktop.Platform), onde o DejaVu fica em /usr/share/fonts/dejavu
    e NÃO em /usr/share/fonts/truetype/dejavu. Antes, no Flatpak, nenhum
    caminho existia e o PIL caía na fonte padrão de 10 px — o texto saía
    minúsculo no telão e o A−/A+ não surtia efeito.
    """
    cache = _FONTE_PIL_CACHE
    if "path" in cache:
        return cache["path"]
    if _eh_windows():
        candidatos = [
            os.path.join(os.environ.get('WINDIR', 'C:/Windows'),
                         'Fonts', 'arialbd.ttf'),
            os.path.join(os.environ.get('WINDIR', 'C:/Windows'),
                         'Fonts', 'arial.ttf'),
        ]
        encontrado = next((p for p in candidatos if os.path.exists(p)), None)
    else:
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
        encontrado = next((p for p in candidatos if os.path.exists(p)), None)
        if encontrado is None:
            encontrado = _procurar_fonte_no_sistema()
    cache["path"] = encontrado
    return encontrado


def _carregar_fonte_pil(tamanho: int):
    """Carrega uma fonte Truetype (DejaVuSans) com fallback para a padrão."""
    try:
        from PIL import ImageFont
    except Exception:
        return None
    caminho = _localizar_fonte_ttf()
    if caminho:
        try:
            return ImageFont.truetype(caminho, tamanho)
        except Exception:
            pass
    # Último recurso antes da fonte embutida: deixa o próprio Pillow procurar
    # pelo nome da família (alguns builds resolvem via fontconfig).
    for _nome in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf",
                  "LiberationSans-Bold.ttf", "arialbd.ttf"):
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
