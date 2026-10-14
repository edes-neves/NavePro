#!/usr/bin/env python3
"""Gera os ícones PNG usados nos botões-pílula do NavePro.

Ícones planos (flat) no amarelo do tema (#f0c040), desenhados por vetor
com Pillow — NÃO dependem de fontes/emojis do sistema, então ficam
idênticos em qualquer Linux (sem "sombra" nem quadradinho). São o
FALLBACK do ícone do botão: a preferência é o emoji colorido renderizado
em tempo de execução (navepro/core/icones.py); só quando não há fonte
de emoji é que o PNG abaixo aparece.

Uso:  python3 gerar_icones.py
Saída: icones/*.png (40x40, transparente): hinos, biblia, ordem, anuncios,
       banco, sorteio, config, anterior, playpause, parar, proximo

Requisitos: Pillow (já listado em requirements.txt).
"""
import math
import os

from PIL import Image, ImageDraw

COR = (240, 192, 64, 255)      # #f0c040 (amarelo do tema)
FUNDO = (0, 0, 0, 0)
AQUI = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(AQUI, "icones")


class Desenho:
    """Canvas superamostrado (2x) com corte/redimensionamento automático."""

    def __init__(self, grade: int = 64):
        self.g = grade
        self.im = Image.new("RGBA", (grade * 2, grade * 2), FUNDO)
        self.d = ImageDraw.Draw(self.im)

    def _p(self, pts):
        return [(x * 2, y * 2) for x, y in pts]

    def linha(self, pts, largura=2):
        self.d.line(self._p(pts), fill=COR, width=int(largura * 2), joint="curve")

    def ret(self, caixa, lado=None):
        x0, y0, x1, y1 = caixa
        self.d.rectangle(self._p([(x0, y0), (x1, y1)]),
                         fill=COR, outline=None)

    def ret_arred(self, caixa, raio=4):
        x0, y0, x1, y1 = caixa
        self.d.rounded_rectangle(self._p([(x0, y0), (x1, y1)]),
                                 radius=int(raio * 2), fill=COR)

    def poli(self, pts):
        self.d.polygon(self._p(pts), fill=COR)

    def elipse(self, caixa):
        x0, y0, x1, y1 = caixa
        self.d.ellipse(self._p([(x0, y0), (x1, y1)]), fill=COR)

    def vazado(self, caixa):
        """Apaga o interior da caixa (o fundo do botão aparece no lugar).

        O ImageDraw sobrescreve o RGBA, então desenhar com FUNDO corta o
        miolo do dado/engrenagem — serve para os buracos sem ter que pintar
        a forma ao redor.
        """
        x0, y0, x1, y1 = caixa
        self.d.ellipse(self._p([(x0, y0), (x1, y1)]), fill=FUNDO)

    def final(self, tamanho=40):
        """Recorta o glifo, centraliza e grava um PNG quadrado `tamanho`."""
        bbox = self.im.getbbox()
        if not bbox:
            return None
        glifo = self.im.crop(bbox)
        w, h = glifo.size
        escala = tamanho / max(w, h)
        novo = glifo.resize((max(1, int(w * escala)), max(1, int(h * escala))),
                            Image.LANCZOS) if escala < 1 else glifo
        w2, h2 = novo.size
        final = Image.new("RGBA", (tamanho, tamanho), FUNDO)
        final.paste(novo, ((tamanho - w2) // 2, (tamanho - h2) // 2), novo)
        return final


def icon_hinos():
    # Livro aberto
    d = Desenho()
    d.poli([(10, 18), (30, 24), (30, 52), (10, 46)])     # página esquerda
    d.poli([(54, 18), (34, 24), (34, 52), (54, 46)])     # página direita
    d.linha([(32, 20), (32, 52)], largura=2)
    return d.final()


def icon_biblia():
    # Cruz latina
    d = Desenho()
    d.ret((26, 12, 38, 52))
    d.ret((12, 24, 52, 36))
    return d.final()


def icon_ordem():
    # Prancheta com lista (Ordem de Serviço)
    d = Desenho()
    d.ret_arred((14, 20, 50, 54), raio=5)                # corpo da prancheta
    d.ret_arred((25, 10, 39, 22), raio=3)                # clipe
    d.linha([(20, 30), (44, 30)], largura=2)
    d.linha([(20, 38), (44, 38)], largura=2)
    d.linha([(24, 46), (40, 46)], largura=2)
    return d.final()


def icon_anuncios():
    # Megafone (certo para "Anúncios")
    d = Desenho()
    d.poli([(8, 22), (42, 30), (42, 52), (8, 42)])       # corpo (corneta)
    d.ret_arred((30, 50, 46, 62), raio=3)                # cabo inferior
    return d.final()


def icon_banco():
    # Caixa/arquivo (Gerenciar Banco)
    d = Desenho()
    d.poli([(14, 24), (50, 24), (42, 12), (6, 12)])      # tampa (topo)
    d.ret((14, 24, 50, 52))                              # frente
    d.linha([(6, 12), (14, 24)], largura=2)
    d.linha([(42, 12), (50, 24)], largura=2)
    return d.final()


def icon_sorteio():
    # Dado de 5 (Sorteio Profissional): pontinhos vazados
    d = Desenho()
    d.ret_arred((10, 10, 54, 54), raio=8)                 # corpo
    for cx, cy in ((24, 24), (40, 24), (32, 32), (24, 40), (40, 40)):
        d.vazado((cx - 5, cy - 5, cx + 5, cy + 5))        # pip
    return d.final()


def _ret_girado(cx, cy, larg, alt, ang):
    """Retângulo `larg`x`alt` centrado em (cx,cy) girado `ang` radianos."""
    hx, hy = larg / 2, alt / 2
    return [(cx + dx * math.cos(ang) - dy * math.sin(ang),
             cy + dx * math.sin(ang) + dy * math.cos(ang))
            for dx, dy in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))]


def icon_config():
    # Engrenagem (Configurações): roda, 8 dentes e furo central
    d = Desenho()
    d.elipse((12, 12, 52, 52))                            # roda (r=20)
    for i in range(8):
        ang = i * math.pi / 4
        d.poli(_ret_girado(32 + 23 * math.cos(ang),
                           32 + 23 * math.sin(ang), 14, 10, ang))
    d.vazado((23, 23, 41, 41))                            # furo
    return d.final()


def icon_anterior():
    # |◀  pista anterior
    d = Desenho()
    d.ret((10, 16, 17, 48))                               # barra
    d.poli([(44, 14), (44, 50), (25, 32)])                # triângulo p/ esquerda
    return d.final()


def icon_proximo():
    # ▶|  próxima pista
    d = Desenho()
    d.poli([(18, 14), (18, 50), (37, 32)])                # triângulo p/ direita
    d.ret((45, 16, 52, 48))                               # barra
    return d.final()


def icon_play_pause():
    # ▶‖  tocar / pausar
    d = Desenho()
    d.poli([(8, 14), (8, 50), (28, 32)])                  # triângulo
    d.ret((33, 16, 40, 48))                               # barra 1
    d.ret((45, 16, 52, 48))                               # barra 2
    return d.final()


def icon_parar():
    # ■  parar
    d = Desenho()
    d.ret((12, 12, 52, 52))
    return d.final()


def main():
    os.makedirs(DEST, exist_ok=True)
    itens = {
        "hinos": icon_hinos,
        "biblia": icon_biblia,
        "ordem": icon_ordem,
        "anuncios": icon_anuncios,
        "banco": icon_banco,
        "sorteio": icon_sorteio,
        "config": icon_config,
        "anterior": icon_anterior,
        "proximo": icon_proximo,
        "playpause": icon_play_pause,
        "parar": icon_parar,
    }
    for nome, fn in itens.items():
        imagem = fn()
        if imagem is None:
            raise SystemExit(f"falha ao desenhar {nome}")
        caminho = os.path.join(DEST, f"{nome}.png")
        imagem.save(caminho)
        print(f"✅ {caminho} ({imagem.size[0]}x{imagem.size[1]})")


if __name__ == "__main__":
    main()