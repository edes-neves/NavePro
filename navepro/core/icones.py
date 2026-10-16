"""Ícones dos botões do painel do operador.

O Tk 8.6 não desenha emoji por conta própria: o rótulo de um botão é escrito
com uma fonte normal (ex.: "Arial"), que não tem glifo de emoji nenhum, e o
que completa é o fallback de fonte do sistema — diferente em cada plataforma:

* Ubuntu/Flatpak trazem o NotoColorEmoji, mas o fontconfig só recorre a ele
  para os code points que existem SÓ nele; os demais caem em fontes de
  símbolos e saem errados ou não saem.
* Debian (instalação mínima) costuma não ter nenhuma fonte de emoji.
* Windows usa GDI, que não faz fallback para o Segoe UI Emoji e não renderiza
  emoji colorido no Tk.

Resultado: uns botões com ícone, outros sem, mudando de sistema para sistema.

Aqui o emoji é renderizado em PNG com a Pillow usando a fonte de emoji
colorida do sistema, quando existe, e convertido em PhotoImage — assim a
janela do Tk só recebe uma imagem, igual em todo lugar (inclusive no Windows,
onde o Tk/GDI não faz fallback para o Segoe UI Emoji). Sem fonte colorida, o
ícone cai para o PNG amarelo de icones/ (gerado por gerar_icones.py) e, por
fim, para o próprio caractere no rótulo.
"""

from __future__ import annotations

import os
import subprocess

from navepro.core.ambiente import _eh_windows
from navepro.core.log import get_logger
from navepro.core.paths import _caminho_recurso

log = get_logger("icones")

# Tamanho do traço de bitmap do NotoColorEmoji: a fonte só abre nesse valor
# (Pillow/FreeType dá "invalid pixel size" para qualquer outro). Fontes
# vetoriais (Segoe UI Emoji) aceitam qualquer tamanho.
_TAM_TRA_CO = 109

# Code point usado para detectar o glifo .notdef da fonte: quase com certeza
# não existe, então o que a fonte desenha para ele é o retângulo de erro.
_NAO_EXISTE = "\U0010FFFD"

_PROBE_EMOJI = "\U0001F600"

_cache_fonte_emoji: dict = {}
_cache_fotos: dict = {}
_cache_icones: dict = {}
_cache_notdef: dict = {}
_cache_fontes_pil: dict = {}
_cache_image_tk: list = [None]


def _obter_image_tk():
    """PIL.ImageTk, ou None quando indisponível (tentativa única).

    Em Debian, python3-pil e python3-pil-tk são pacotes separados: sem o
    segundo, o import de ImageTk falha e NENHUM ícone de botão pode ser
    convertido em PhotoImage. O aviso é um só, não um por botão.
    """
    guardado = _cache_image_tk[0]
    if guardado is None:
        try:
            from PIL import ImageTk
            _cache_image_tk[0] = ImageTk
        except Exception as e:
            log.warning(f"⚠️ PIL.ImageTk indisponível ({e}); os ícones dos "
                        "botões cairão para o texto")
            _cache_image_tk[0] = False
    return _cache_image_tk[0] or None


def _caixa_desenho(fonte) -> int:
    """Lado do canvas onde desenhar sem cortar o glifo.

    O NotoColorEmoji (traço de bitmap) desenha o emoji maior que o tamanho
    pedido e SEM margem lateral: um canvas "tamanho da fonte + pouca folga"
    cortava a lateral de 📖/📢 e deformava o recorte.
    """
    return int(fonte.size * 1.5) + 8


def _desenhar_imagem(fonte, texto: str, caixa: int):
    """Desenha `texto` centralizado numa imagem RGBA `caixa`x`caixa`.

    Tenta primeiro com as camadas de cor (fontes de emoji, ex.: NotoColorEmoji
    e Segoe UI Emoji), que exigem embedded_color=True; se a fonte não tiver
    cor, redesenha só com o contorno.
    """
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (caixa, caixa), (0, 0, 0, 0))
    desenhador = ImageDraw.Draw(im)
    for kwargs in ({"embedded_color": True}, {}):
        try:
            desenhador.text((caixa // 2, caixa // 2), texto, font=fonte,
                            anchor="mm", **kwargs)
            return im
        except (OSError, TypeError, ValueError, UnicodeEncodeError):
            continue
    return None


def _render_fonte(fonte, texto: str, caixa: int):
    """Imagem RGBA do desenho, ou None se não houver glifo desenhável."""
    im = _desenhar_imagem(fonte, texto, caixa)
    if im is None or im.getbbox() is None:
        return None
    return im


def _e_notdef(fonte, texto: str, caixa: int) -> bool:
    """True se `texto` é desenhado igual ao glifo de erro da fonte.

    TrueType desenha o .notdef como um retângulo COM tinta, então só olhar a
    caixa delimitadora não basta — a comparação com o glifo de erro é o que
    separa "emoji desenhado" de "quadradinho".
    """
    imagem = _render_fonte(fonte, texto, caixa)
    if imagem is None:
        return False
    chave = (id(fonte), caixa)
    guardado = _cache_notdef.get(chave)
    if guardado is None:
        referencia = _render_fonte(fonte, _NAO_EXISTE, caixa)
        if referencia is None:
            return False
        # Guarda a própria fonte junto: mantém o id válido, senão o cache de
        # id() poderia reapontar para outro objeto depois de um coletor.
        _cache_notdef[chave] = (fonte, referencia)
    else:
        referencia = guardado[1]
    return list(imagem.getdata()) == list(referencia.getdata())


def _cromia(imagem) -> float:
    """Fração de pixels com saturação (emoji colorido tem cor; tofu não)."""
    dados = list(imagem.getdata())
    if not dados:
        return 0.0
    com_cor = sum(1 for r, g, b, _a in dados
                  if max(r, g, b) - min(r, g, b) > 40)
    return com_cor / len(dados)


def _candidatos_fonte_emoji() -> list[str]:
    """Arquivos de fonte de emoji prováveis no sistema."""
    if _eh_windows():
        windir = os.environ.get("WINDIR") or "C:/Windows"
        return [os.path.join(windir, "Fonts", "seguiemj.ttf")]

    encontrados: list[str] = []
    # fontconfig: devolve os arquivos que realmente contêm o code point.
    # É mais fiel do que procurar por nome (cobre a fonte que a distro
    # distribuiu, seja qual for o nome do arquivo).
    try:
        saida = subprocess.run(
            ["fc-list", f":charset={ord(_PROBE_EMOJI):X}", "file"],
            capture_output=True, text=True, timeout=10)
        if saida.returncode == 0:
            for linha in saida.stdout.splitlines():
                caminho = linha.strip().rstrip(":").strip()
                if caminho:
                    encontrados.append(caminho)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning(f"⚠️ fc-list indisponível ao procurar emoji: {e}")

    # Varredura por nome para o caso de não haver fontconfig (ou para fontes
    # instaladas só na pasta do usuário).
    alvos = ("emoji", "moji", "symbola", "colr", "twemoji", "emojione")
    for raiz in ("/usr/share/fonts", "/usr/local/share/fonts",
                 os.path.join(os.path.expanduser("~"), ".local/share/fonts"),
                 os.path.join(os.path.expanduser("~"), ".fonts")):
        if not os.path.isdir(raiz):
            continue
        for dirpath, _dirs, arquivos in os.walk(raiz):
            for arquivo in arquivos:
                if (arquivo.lower().endswith((".ttf", ".otf", ".ttc"))
                        and any(a in arquivo.lower() for a in alvos)):
                    encontrados.append(os.path.join(dirpath, arquivo))
    return list(dict.fromkeys(encontrados))


def _fonte_serve_emoji(caminho: str) -> float:
    """Mede o quão bem a fonte desenha emoji. <= 0 = não serve.

    Só serve fonte de emoji COLORIDO: uma que desenhe o glifo em preto puro
    daria um ícone quase invisível sobre o botão escuro (#21262d) — e nesse
    caso o PNG amarelo de icones/ é uma opção melhor.
    """
    try:
        from PIL import ImageFont
    except Exception:
        return -1.0
    for tam in (_TAM_TRA_CO, 128, 64, 48, 40, 32, 24, 16):
        try:
            fonte = ImageFont.truetype(caminho, tam)
        except OSError:
            continue
        caixa = _caixa_desenho(fonte)
        imagem = _render_fonte(fonte, _PROBE_EMOJI, caixa)
        if imagem is None or _e_notdef(fonte, _PROBE_EMOJI, caixa):
            return -1.0
        cromia = _cromia(imagem)
        return cromia if cromia > 0 else -1.0
    return -1.0


def _localizar_fonte_emoji() -> str | None:
    """Localiza (e memoriza) a melhor fonte de emoji COLORIDA do sistema.

    None quando não há nenhuma — aí quem assume é o PNG amarelo de icones/ e,
    no limite, o caractere no rótulo. A monocromática é recusada de propósito
    (ver _fonte_serve_emoji): preto sobre o botão escuro some.
    """
    if "path" in _cache_fonte_emoji:
        return _cache_fonte_emoji["path"]
    melhor: tuple[float, str] | None = None
    for cand in _candidatos_fonte_emoji():
        if not os.path.isfile(cand):
            continue
        nota = _fonte_serve_emoji(cand)
        if nota < 0:
            continue
        if melhor is None or nota > melhor[0]:
            melhor = (nota, cand)
    caminho: str | None = None
    if melhor:
        caminho = melhor[1]
        log.info(f"✅ Fonte de emoji colorida: {caminho} "
                 f"(cromia {melhor[0]:.2f})")
    else:
        log.warning("⚠️ Sem fonte de emoji colorida no sistema: os ícones "
                    "dos botões usarão os PNGs de icones/")
    _cache_fonte_emoji["path"] = caminho
    return caminho


def _carregar_fonte(caminho: str, tamanho: int):
    """Carrega a fonte no tamanho pedido, caindo no traço nativo se preciso."""
    chave = (caminho, tamanho)
    if chave in _cache_fontes_pil:
        return _cache_fontes_pil[chave]
    from PIL import ImageFont
    fonte = None
    try:
        fonte = ImageFont.truetype(caminho, tamanho)
    except OSError:
        try:
            fonte = ImageFont.truetype(caminho, _TAM_TRA_CO)
        except OSError:
            fonte = None
    _cache_fontes_pil[chave] = fonte
    return fonte


def _emoji_para_imagem(emoji: str, tamanho: int):
    """Recorte do emoji em RGBA, reduzido para caber em `tamanho`, ou None."""
    from PIL import Image
    caminho = _localizar_fonte_emoji()
    if not caminho or not emoji:
        return None
    fonte = _carregar_fonte(caminho, tamanho)
    if fonte is None:
        return None
    caixa = _caixa_desenho(fonte)
    imagem = _render_fonte(fonte, emoji, caixa)
    if imagem is None:
        return None
    # Se a fonte escolhida não tem ESTE emoji, ela desenha o quadradinho de
    # erro — deixa o chamador cair para o PNG amarelo de icones/.
    if _e_notdef(fonte, emoji, caixa):
        return None
    glifo = imagem.crop(imagem.getbbox())
    glifo.thumbnail((tamanho, tamanho), Image.LANCZOS)
    return glifo


def _carregar_emoji(emoji: str, tamanho: int = 40, master=None):
    """PhotoImage do Tk com o emoji colorido renderizado, ou None.

    O resultado é memorizado: os mesmos ícones são reutilizados entre botões e
    recargas da interface, e a referência precisa ficar viva senão o Tk apaga
    a imagem do botão.
    """
    chave = (emoji, tamanho, str(master) if master is not None else "")
    if chave in _cache_fotos:
        return _cache_fotos[chave]
    ImageTk = _obter_image_tk()
    if ImageTk is None:
        return None
    from PIL import Image
    imagem = _emoji_para_imagem(emoji, tamanho)
    if imagem is None:
        return None
    quadro = Image.new("RGBA", (tamanho, tamanho), (0, 0, 0, 0))
    quadro.paste(imagem, ((tamanho - imagem.width) // 2,
                          (tamanho - imagem.height) // 2), imagem)
    try:
        foto = ImageTk.PhotoImage(quadro, master=master)
    except Exception as e:
        log.warning(f"⚠️ Falha ao criar PhotoImage do emoji {emoji!r}: {e}")
        return None
    _cache_fotos[chave] = foto
    return foto


def _carregar_icone(nome: str):
    """Carrega um PNG de icones/ como PhotoImage do Tk para usar em botões.

    Retorna None se o arquivo não existir ou o Tk falhar (fallback: o botão
    usa o caractere emoji/texto). Ícones PNG não dependem de fontes emoji do
    sistema — em qualquer Linux aparecem iguais (em vez de "sombra"/tofu).
    """
    if nome in _cache_icones:
        return _cache_icones[nome]
    caminho = _caminho_recurso(os.path.join("icones", f"{nome}.png"))
    if not os.path.exists(caminho):
        return None
    ImageTk = _obter_image_tk()
    if ImageTk is None:
        return None
    try:
        from PIL import Image
        with Image.open(caminho) as img:
            foto = ImageTk.PhotoImage(img)
    except Exception as e:
        log.warning(f"⚠️ Ícone '{nome}' indisponível: {e}")
        return None
    _cache_icones[nome] = foto
    return foto
