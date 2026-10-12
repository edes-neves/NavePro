"""TelaoWindow - janela de projeção no telão (monitor secundário).

Extraído de NavePro.py sem alterar o comportamento (ver AGENTS.md).
"""

import datetime
import json
import os
import tkinter as tk
import tkinter.font as tkfont

from navepro.core.ambiente import _eh_windows
from navepro.core.fontes_pil import (
    _PCT_FONTE_CAIXA,
    _caixa_texto_config,
    _calcular_texto_em_caixa,
    _fonte_familia_do_pil,
)
from navepro.core.log import get_logger
from navepro.core.monitores import _escolher_monitor_telao, get_monitors_config
from navepro.core.paths import _aplicar_icone_janela
from navepro.core.util_tk import _normalizar_escala_tk

log = get_logger("telao")

class TelaoWindow:
    """Janela de projeção exibida no telão (monitor secundário).
    Otimizações:
    - Centralização calculada no init (sem recálculo em cada redesenho)
    - itemconfig só quando o texto realmente muda (evita redraw do Canvas)
    - Atributos '-alpha' e visibilidade mantidos em cache para evitar chamadas Tk
    - root.lower() chamado uma única vez (não repetido via after)
    - update() substituído por update_idletasks() (mais leve) + update() apenas
      quando necessário
    - Fontes calculadas proporcionalmente à altura da tela (uma vez)
    """
    def __init__(self, monitor_index: int = None) -> None:
        self.root = tk.Tk(className="NavePro")
        self.root.title("TELÃO")
        _normalizar_escala_tk(self.root)
        _aplicar_icone_janela(self.root)
        monitors = get_monitors_config()
        log.info(f"🖥️ Monitores detectados: {len(monitors)}")
        for i, m in enumerate(monitors):
            prim = " [primário]" if getattr(m, 'primary', False) else ""
            log.info(f"   Monitor {i+1}: {m.width}x{m.height} em ({m.x},{m.y}){prim}")
        # TelaoWindow (relogio/telão) abre SEMPRE no monitor que NÃO é
        # o primário, conforme definido pelo SO. Se houver apenas um
        # monitor, usa-o.
        monitor = _escolher_monitor_telao(monitors)
        # Cache de geometria privada (evita acessos repetidos)
        self._monitor = monitor
        geometry = f"{monitor.width}x{monitor.height}+{monitor.x}+{monitor.y}"
        log.info(f"✅ TELÃO: {geometry}")
        # Inicia em TELA CHEIA (sem bordas) cobrindo o monitor secundário.
        # A tecla F11 alterna para o modo janela (min/max/redimensionar) e
        # volta à tela cheia.
        # Config do relógio (cores, tamanhos, espaçamento, fundo opaco)
        self._relogio_cfg: dict = {
            "cor_hora": "#F5BE08",
            "cor_temp": "#F5BE08",
            "cor_fundo": "#000000",
            "fator_hora": 1.0,
            "fator_temp": 1.0,
            "espacamento": 1.0,
            "fundo_opaco": False,
            "fundo_imagem": "",
        }
        self._fundo_relogio_item = None
        self._fundo_relogio_to_tk = None
        self._fundo_relogio_caminho = ""
        self.root.geometry(geometry)
        self.root.configure(bg='black')
        self.root.attributes('-alpha', self._alpha_relogio())
        self.root.attributes('-topmost', False)
        self._fullscreen: bool = True
        self._aplicar_tela_cheia(True)
        self.root.lift()
        # Só reafirma a geometria no modo tela cheia; no modo janela o
        # gerenciador de janelas controla livremente (min/max/redimensionar).
        self.root.bind("<Configure>", self._reafirmar_geometria)
        # Cache de estado: evita chamadas repetidas à Tk
        self._current_alpha: float = self._alpha_relogio()
        self._current_text: str = ""
        self._current_temp: str = ""
        self._is_visible: bool = True
        self.main_frame = tk.Frame(self.root, bg='black')
        self.main_frame.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(self.main_frame, bg='black', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        # Calcula fontes e posições sem sobreposição (720p–1080p),
        # medindo a altura real (linha) das fontes na tela atual.
        self._font_hora: tuple | None = None
        self._font_temp: tuple | None = None
        self._tam_hora: int = 0
        self._tam_temp: int = 0
        self._cx = 0
        self._cy_hora = 0
        self._cy_temp = 0
        self._calcular_layout(monitor.width, monitor.height)
        # Texto da hora
        self.overlay_text = self.canvas.create_text(
            self._cx, self._cy_hora, text="",
            fill=self._relogio_cfg["cor_hora"], anchor="center",
            font=self._font_hora
        )
        # Texto da temperatura
        self.temp_text = self.canvas.create_text(
            self._cx, self._cy_temp, text="",
            fill=self._relogio_cfg["cor_temp"], anchor="center",
            font=self._font_temp
        )
        # Referência bíblica (livro cap:vers.) — canto inferior direito
        self.ref_text = self.canvas.create_text(
            0, 0, text="", fill="#A0A0A0", anchor="se", state="hidden",
            font=("DejaVu Sans", 16, "bold")
        )
        # Redimensionamento mantido (caso janela seja movida)
        self.canvas.bind("<Configure>", self._centralizar)
        self.root.bind("<Escape>", self._ao_pressionar_esc)
        self.root.bind("<Control-q>", self.fechar)
        self.root.bind("<F11>", self._alternar_fullscreen)
        # Passador de slides (controle remoto): durante uma projeção em
        # slides, setas, AvPag/RetPag, espaço, F5 e BackSpace navegam. Fora
        # de projeção não faz nada.
        self.root.bind("<KeyPress>", self._navegar_slides_controle)
        self.rodando = True
        self.mostrando_relogio = True
        self.mostrando_letra = False
        self._em_slides = False
        self._modo_extra: str | None = None
        self._mostrando_imagem = False
        self._mostrando_imagem_com_texto = False
        self._imagem_item = None
        self._imagem_rect_base = None
        self._imagem_pil = None
        self._imagem_orig_pil = None
        self._imagem_escala = 1.0
        self._texto_box = (0, 0, 100, 100)
        self._texto_escala = 1.0
        self._texto_largura_base = None
        self._slides: list = []
        self._slide_index = 0
        self._proj_cfg: dict = {
            "fonte": "Montserrat",
            "tamanho_pct": 5.0,
            "cor": "#FFFFFF",
            "duracao_seg": 30,
            "cor_ref": "#A0A0A0",
            "cor_fundo": "#000000",
            "fundo_opaco": True,
            "fundo_imagem": "",
        }
        self._fundo_imagem_item = None
        self._fundo_imagem_to_tk = None
        self._fundo_imagem_caminho = ""
        self._proj_timer = None
        self._temp_salvo = ""
        self.root.protocol("WM_DELETE_WINDOW", self.fechar)
        # Aplica alpha imediatamente
        self.root.attributes('-alpha', self._alpha_relogio())
        self._current_alpha = self._alpha_relogio()
        # Exibe hora inicial
        self._exibir_hora_inicial()
    def _alpha_relogio(self) -> float:
        """Retorna o alpha do telão no modo relógio (opaco se configurado)."""
        if getattr(self, "_relogio_cfg", {}).get("fundo_opaco"):
            return 1.0
        return 0.55
    def _calcular_layout(self, largura: int, altura: int) -> bool:
        """Calcula fontes e posições sem sobreposição (720p–1080p).
        Mede a altura real de linha das fontes na tela atual e empilha
        hora + temperatura com espaçamento pequeno, como um bloco único
        centralizado. Funciona de 720p a 1080p e com qualquer fonte
        (inclusive fallback quando 'Digital-7' não existe).
        Retorna True se o layout mudou.
        IMPORTANTE: as fontes são atribuídas ao canvas como TUPLA
        ("Digital-7", tamanho, "normal") e NÃO como tkfont.Font. No X11,
        quando o telão é o segundo Tk() do processo (janela principal
        criada antes), fontes nomeadas (tkfont.Font) são renderizadas
        minúsculas pelo Tk. A tupla renderiza corretamente.
        """
        r_cfg = self._relogio_cfg
        margem_lateral = max(16, int(largura * 0.05))
        espacamento = r_cfg.get("espacamento", 1.0)
        gap = max(0, int(altura * 0.015 * espacamento))
        fator_hora = r_cfg.get("fator_hora", 1.0)
        fator_temp = r_cfg.get("fator_temp", 1.0)
        hora_px = int(altura * 0.48 * fator_hora)
        temp_px = max(24, int(altura * 0.28 * fator_temp))
        self._largura_temp_max = max(200, largura - 2 * margem_lateral)
        def _tam_para_altura(altura_px: int) -> int:
            # Mede a proporção px/point na tela atual (independe de DPI)
            ref = tkfont.Font(family="Digital-7", size=100)
            px_por_pt = ref.metrics("linespace") / 100.0
            if px_por_pt <= 0:
                px_por_pt = 1.0
            size = max(40, min(620, int(altura_px / px_por_pt)))
            fonte = tkfont.Font(family="Digital-7", size=size)
            # Refina pela altura real
            real = fonte.metrics("linespace")
            if real > 0 and abs(real - altura_px) > 2:
                size = max(40, min(620, int(size * altura_px / real)))
            return size
        def _linespace(tam: int) -> int:
            return tkfont.Font(family="Digital-7", size=tam).metrics("linespace")
        tam_hora = _tam_para_altura(hora_px)
        tam_temp = _tam_para_altura(temp_px)
        font_hora = ("Digital-7", tam_hora, "normal")
        font_temp = ("Digital-7", tam_temp, "normal")
        cx = largura // 2
        h_hora = _linespace(tam_hora)
        h_temp = _linespace(tam_temp)
        # Centraliza o conjunto hora + temperatura como um bloco único:
        # sobra a mesma folga acima da hora e abaixo da temperatura
        # (a altura da hora difere da temperatura, então o meio do espaço
        # entre elas NÃO coincide com o centro vertical da tela).
        total = h_hora + gap + h_temp
        topo = max(0, (altura - total) // 2)
        cy_hora = topo + h_hora // 2
        cy_temp = topo + h_hora + gap + h_temp // 2
        mudou = (
            cx != self._cx or cy_hora != self._cy_hora or
            cy_temp != self._cy_temp or
            tam_hora != self._tam_hora or tam_temp != self._tam_temp
        )
        if mudou:
            self._font_hora = font_hora
            self._font_temp = font_temp
            self._tam_hora = tam_hora
            self._tam_temp = tam_temp
            self._cx = cx
            self._cy_hora = cy_hora
            self._cy_temp = cy_temp
        return mudou
    def _centralizar(self, event: object = None) -> None:
        """Recalcula posições e fontes (só se realmente mudou)."""
        if getattr(self, 'mostrando_letra', False):
            return
        w = self.canvas.winfo_width() if not event else event.width
        h = self.canvas.winfo_height() if not event else event.height
        if w < 100 or h < 100:
            return
        if self._calcular_layout(w, h):
            self.canvas.coords(self.overlay_text, self._cx, self._cy_hora)
            self.canvas.coords(self.temp_text, self._cx, self._cy_temp)
            self.canvas.itemconfig(self.overlay_text, font=self._font_hora)
            self.canvas.itemconfig(self.temp_text, font=self._font_temp)
            self._font_temp_exib_texto = None
    def _reafirmar_geometria(self, event: object = None) -> None:
        """Mantém o telão cobrindo o monitor apenas no modo tela cheia.
        No modo janela não força nada: deixa o usuário minimizar, maximizar,
        redimensionar e mover a janela livremente.
        """
        if not getattr(self, '_fullscreen', False):
            return
        m = self._monitor
        try:
            if (abs(self.root.winfo_width() - m.width) > 4 or
                    abs(self.root.winfo_height() - m.height) > 4 or
                    abs(self.root.winfo_x() - m.x) > 4 or
                    abs(self.root.winfo_y() - m.y) > 4):
                self.root.geometry(f"{m.width}x{m.height}+{m.x}+{m.y}")
        except tk.TclError:
            pass
    def _aplicar_tela_cheia(self, ativo: bool) -> None:
        """Liga/desliga o modo tela cheia do telão no monitor que ele escolheu.
        POR QUE O WINDOWS É DIFERENTE
        O `-fullscreen` do Tk no Windows é implementado com a ÁREA DE TRABALHO
        DO MONITOR PRIMÁRIO (SPI_GETWORKAREA): ele ignora onde a janela está e
        sempre a joga no primário. Medido aqui: uma janela posicionada em
        x=1920 (monitor 2) saía do `-fullscreen` em x=0 — exatamente o sintoma
        "as duas janelas no monitor primário, e o telão só vai para o telão
        quando aperto F11". O F11 parecer consertar é coincidência: ao sair da
        tela cheia o código reaplica a geometria, e aí ela obedece.
        No Windows a tela cheia é então EMULADA: `overrideredirect` remove a
        borda da janela e a geometria exata do monitor faz o resto — o Windows
        respeita posição/tamanho em qualquer monitor.
        No Linux nada muda: continua o `-fullscreen` nativo, que funciona.
        """
        self._fullscreen = bool(ativo)
        monitor = self._monitor
        if monitor is None:
            self.root.attributes('-fullscreen', self._fullscreen)
            return
        geometria = f"{monitor.width}x{monitor.height}+{monitor.x}+{monitor.y}"
        if _eh_windows():
            self.root.overrideredirect(self._fullscreen)
            if self._fullscreen:
                self.root.geometry(geometria)
                # Sem a moldura o Windows não dá foco sozinho; o telão precisa
                # do foco para receber F11, Esc e as setas.
                try:
                    self.root.focus_force()
                except tk.TclError:
                    pass
        else:
            self.root.attributes('-fullscreen', self._fullscreen)
            if self._fullscreen:
                self.root.lift()
        if not self._fullscreen:
            # Saindo da tela cheia a janela volta ao tamanho do monitor, na
            # posição do monitor (e não no canto da tela, como no Tk puro).
            self.root.geometry(geometria)
    def _alternar_fullscreen(self, event: object = None) -> str:
        """Alterna entre tela cheia (sem bordas) e janela redimensionável."""
        self._aplicar_tela_cheia(not getattr(self, '_fullscreen', False))
        return "break"
    def _fonte_temp_para_texto(self, temperatura: str) -> tuple:
        """Retorna a fonte da temperatura ajustada à largura da tela.
        Encolhe a fonte somente quando o texto real não couber na largura
        (ex.: mensagem de erro longa). O resultado é cacheado por texto.
        Retorna TUPLA ("Digital-7", tamanho, "normal") para o canvas
        (fontes nomeadas renderizam minúsculas no segundo Tk do processo).
        """
        if not temperatura:
            return self._font_temp
        if (getattr(self, '_font_temp_exib_texto', None) == temperatura and
                getattr(self, '_font_temp_exib', None) is not None):
            return self._font_temp_exib
        size = int(self._font_temp[1])
        largura_max = getattr(self, '_largura_temp_max', None)
        if largura_max:
            w = tkfont.Font(family="Digital-7", size=size).measure(temperatura)
            if w > largura_max and w > 0:
                size = max(40, int(size * largura_max / w))
        fonte = ("Digital-7", size, "normal")
        self._font_temp_exib = fonte
        self._font_temp_exib_texto = temperatura
        return fonte
    def mostrar_relogio(self, texto: str, temperatura: str = "") -> None:
        """Exibe relógio e temperatura no telão (só redesenha se mudou)."""
        if not self.rodando or not self._raiz_viva():
            return
        if not self.mostrando_relogio:
            # Durante projeções (slides/vídeo/texto/imagem/medidor) o relógio
            # não deve redesenhar hora/temperatura por cima do conteúdo.
            return
        # Evita chamadas Tk desnecessárias se os valores não mudaram
        texto_mudou = texto != self._current_text
        temp_mudou = temperatura != self._current_temp
        if not texto_mudou and not temp_mudou and self.mostrando_relogio:
            return
        self.mostrando_relogio = True
        self._current_text = texto
        self._current_temp = temperatura
        # Só mexe na visibilidade se necessário
        if not self._is_visible:
            self.root.deiconify()
            self._is_visible = True
        # Só mexe no alpha se necessário
        alpha_base = self._alpha_relogio()
        if self._current_alpha != alpha_base:
            self.root.attributes('-alpha', alpha_base)
            self._current_alpha = alpha_base
        # Atualiza apenas o que mudou
        if texto_mudou:
            self.canvas.itemconfig(self.overlay_text, text=texto, state="normal")
        if temperatura:
            if temp_mudou:
                self.canvas.itemconfig(
                    self.temp_text,
                    text=temperatura,
                    font=self._fonte_temp_para_texto(temperatura),
                    state="normal",
                )
        elif self._current_temp:
            self.canvas.itemconfig(self.temp_text, text="", state="hidden")
        # lower() apenas quando necessário (janela pode ter subido)
        # Usamos lower() apenas na primeira vez ou após vídeo
        if not self._is_visible or not self.mostrando_relogio:
            self.root.lower()
    def _raiz_viva(self) -> bool:
        """True se o Tk do telão ainda existe (não foi fechado/destruído)."""
        try:
            return bool(getattr(self, "rodando", False)) and bool(
                self.root.winfo_exists())
        except tk.TclError:
            return False
    def preparar_video(self) -> None:
        """Prepara para exibição de vídeo (esconde o telão)."""
        if not self._raiz_viva():
            return
        self.mostrando_relogio = False
        if self._current_alpha != 0.0:
            try:
                self.root.attributes('-alpha', 0.0)
            except tk.TclError:
                return
            self._current_alpha = 0.0
        if self._is_visible:
            try:
                self.root.withdraw()
            except tk.TclError:
                pass
            self._is_visible = False
    def restaurar_tela(self) -> None:
        """Restaura o telão após o término do vídeo (sem after repetido)."""
        if not self._raiz_viva():
            return
        if self._is_visible and self.mostrando_relogio:
            return  # Já está visível
        self._current_alpha = self._alpha_relogio()
        self._is_visible = True
        self.mostrando_relogio = True
        # Reseta cache de hora para forçar redesenho do relógio
        self._current_text = ""
        self._current_temp = ""
        self.root.deiconify()
        self.root.attributes('-alpha', self._alpha_relogio())
        self.root.lower()
    # ── Projeção de texto (letra / versículo) ─────────────────────
    def configurar_projecao(self, cfg: dict | None = None) -> None:
        """Define as configurações de aparência da projeção de texto."""
        defaults = {
            "fonte": "Montserrat",
            "tamanho_pct": 5.0,
            "cor": "#FFFFFF",
            "duracao_seg": 30,
            "cor_ref": "#A0A0A0",
            "cor_fundo": "#000000",
            "fundo_opaco": True,
            "fundo_imagem": "",
        }
        merged = dict(defaults)
        if isinstance(cfg, dict):
            for k, v in cfg.items():
                if k in defaults and v not in (None, ""):
                    merged[k] = v
        self._proj_cfg = merged
    def _alpha_projecao(self) -> float:
        """Alpha do telão durante uma projeção (opaco por padrão).
        Padrão histórico do NavePro: projeções são opacas (alpha 1.0).
        Se o operador desmarcar "Fundo opaco" na Aparência da Projeção,
        aplica a mesma transparência do modo relógio (0.55).
        """
        if not getattr(self, "_proj_cfg", {}).get("fundo_opaco", True):
            return 0.55
        return 1.0
    def _aplicar_fundo_projecao(self) -> None:
        """Aplica a cor de fundo ou a imagem de fundo configurada no telão.
        A imagem de fundo (se definida) vira um item de canvas posicionado
        abaixo de TODO o conteúdo projetado (tag_lower); sem imagem, aplica
        apenas a cor de fundo. Não afeta o modo relógio: ao retornar para o
        relógio, _retornar_ao_relogio limpa o item de imagem de fundo.
        """
        # Durante a projeção, some com a imagem de fundo do relógio para ela
        # não aparecer por trás (cada modo gerencia seu próprio fundo).
        if getattr(self, "_fundo_relogio_item", None) is not None:
            try:
                self.canvas.delete(self._fundo_relogio_item)
            except tk.TclError:
                pass
            self._fundo_relogio_item = None
            self._fundo_relogio_to_tk = None
            self._fundo_relogio_caminho = ""
        cfg = getattr(self, "_proj_cfg", {})
        cor_fundo = cfg.get("cor_fundo", "#000000")
        caminho = (cfg.get("fundo_imagem") or "").strip()
        atual = getattr(self, "_fundo_imagem_caminho", "")
        if caminho == atual and getattr(self, "_fundo_imagem_item", None) is not None:
            return
        # Remove o item de fundo anterior (se houver)
        if getattr(self, "_fundo_imagem_item", None) is not None:
            try:
                self.canvas.delete(self._fundo_imagem_item)
            except tk.TclError:
                pass
            self._fundo_imagem_item = None
        self._fundo_imagem_to_tk = None
        self._fundo_imagem_caminho = caminho
        ext_ok = caminho.lower().endswith(
            (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"))
        if caminho and os.path.exists(caminho) and ext_ok:
            try:
                with Image.open(caminho) as img:  # noqa: F821
                    img_fundo = img.convert("RGB")
                w = self.canvas.winfo_width() or self._monitor.width
                h = self.canvas.winfo_height() or self._monitor.height
                if w < 1 or h < 1:
                    w, h = self._monitor.width, self._monitor.height
                redimensao = getattr(Image, "LANCZOS", None) or getattr(Image, "BICUBIC", None)  # noqa: F821
                img_fundo = img_fundo.resize((w, h), redimensao)
                self._fundo_imagem_to_tk = ImageTk.PhotoImage(  # noqa: F821
                    img_fundo, master=self.root)
                self._fundo_imagem_item = self.canvas.create_image(
                    w // 2, h // 2, image=self._fundo_imagem_to_tk,
                    anchor="center", tags=("fundo_imagem",))
                try:
                    self.canvas.tag_lower(self._fundo_imagem_item)
                except tk.TclError:
                    pass
                self.canvas.configure(bg=cor_fundo)
            except Exception as e:
                log.warning(f"⚠️ Não foi possível exibir a imagem de fundo: {e}")
                self._fundo_imagem_item = None
                self.canvas.configure(bg=cor_fundo)
        else:
            self.root.configure(bg=cor_fundo)
            self.main_frame.configure(bg=cor_fundo)
            self.canvas.configure(bg=cor_fundo)
        self.root.update_idletasks()
    def configurar_relogio(self, cfg: dict | None = None) -> None:
        """Define a configuração de aparência do relógio/temperatura no telão."""
        defaults = {
            "cor_hora": "#F5BE08",
            "cor_temp": "#F5BE08",
            "cor_fundo": "#000000",
            "fator_hora": 1.0,
            "fator_temp": 1.0,
            "espacamento": 1.0,
            "fundo_opaco": False,
            "fundo_imagem": "",
        }
        merged = dict(defaults)
        if isinstance(cfg, dict):
            for k, v in cfg.items():
                if k in defaults and v not in (None, ""):
                    merged[k] = v
        self._relogio_cfg = merged
        # Aplica cores ao canvas
        self._aplicar_cores_relogio()
        # Recalcula layout com novos tamanhos/espacamento
        w = self.canvas.winfo_width() or self._monitor.width
        h = self.canvas.winfo_height() or self._monitor.height
        if w > 100 and h > 100:
            self._calcular_layout(w, h)
            if self.mostrando_relogio:
                self.canvas.coords(self.overlay_text, self._cx, self._cy_hora)
                self.canvas.coords(self.temp_text, self._cx, self._cy_temp)
                self.canvas.itemconfig(self.overlay_text, font=self._font_hora)
                self.canvas.itemconfig(self.temp_text, font=self._font_temp)
                self.root.update_idletasks()
        # Aplica a opacidade configurada ao telão (apenas no modo relógio)
        if self.mostrando_relogio:
            alpha_base = self._alpha_relogio()
            if self._current_alpha != alpha_base:
                self.root.attributes('-alpha', alpha_base)
                self._current_alpha = alpha_base
    def _aplicar_cores_relogio(self) -> None:
        """Aplica as cores configuradas do relógio e temperatura ao canvas."""
        cfg = self._relogio_cfg
        cor_hora = cfg.get("cor_hora", "#F5BE08")
        cor_temp = cfg.get("cor_temp", "#F5BE08")
        cor_fundo = cfg.get("cor_fundo", "#000000")
        self.canvas.itemconfig(self.overlay_text, fill=cor_hora)
        self.canvas.itemconfig(self.temp_text, fill=cor_temp)
        # Imagem de fundo do relógio (opcional): vira item de canvas abaixo
        # do texto. Sem imagem, aplica apenas a cor de fundo.
        caminho = (cfg.get("fundo_imagem") or "").strip()
        caminho_atual = getattr(self, "_fundo_relogio_caminho", "")
        item_atual = getattr(self, "_fundo_relogio_item", None)
        if caminho != caminho_atual or item_atual is None:
            if item_atual is not None:
                try:
                    self.canvas.delete(item_atual)
                except tk.TclError:
                    pass
                self._fundo_relogio_item = None
            self._fundo_relogio_to_tk = None
            self._fundo_relogio_caminho = caminho
            ext_ok = caminho.lower().endswith(
                (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"))
            if caminho and os.path.exists(caminho) and ext_ok:
                try:
                    with Image.open(caminho) as img:  # noqa: F821
                        img_fundo = img.convert("RGB")
                    w = self.canvas.winfo_width() or self._monitor.width
                    h = self.canvas.winfo_height() or self._monitor.height
                    if w < 1 or h < 1:
                        w, h = self._monitor.width, self._monitor.height
                    redimensao = getattr(Image, "LANCZOS", None) or getattr(Image, "BICUBIC", None)  # noqa: F821
                    img_fundo = img_fundo.resize((w, h), redimensao)
                    self._fundo_relogio_to_tk = ImageTk.PhotoImage(  # noqa: F821
                        img_fundo, master=self.root)
                    self._fundo_relogio_item = self.canvas.create_image(
                        w // 2, h // 2, image=self._fundo_relogio_to_tk,
                        anchor="center", tags=("fundo_relogio",))
                    try:
                        self.canvas.tag_lower(self._fundo_relogio_item)
                    except tk.TclError:
                        pass
                except Exception as e:
                    log.warning(f"⚠️ Não foi possível exibir a imagem de fundo do relógio: {e}")
                    self._fundo_relogio_item = None
                    self._fundo_relogio_caminho = ""
        self.root.configure(bg=cor_fundo)
        self.main_frame.configure(bg=cor_fundo)
        self.canvas.configure(bg=cor_fundo)
    def projetar_texto(self, texto: str, titulo: str = "") -> None:
        """Projeta texto (letra/versículo) no telão com a fonte configurada.
        Esconde relógio e temperatura, exibe o texto formatado no centro e
        agenda o retorno automático do relógio + temperatura após o tempo
        configurado (duracao_seg).
        """
        if not self.rodando or not self._raiz_viva():
            return
        cfg = getattr(self, "_proj_cfg", None)
        if cfg is None:
            self.configurar_projecao()
        # Cancela retorno automático anterior (re-projeção)
        if getattr(self, "_proj_timer", None) is not None:
            try:
                self.root.after_cancel(self._proj_timer)
            except tk.TclError:
                pass
            self._proj_timer = None
        # Guarda a temperatura exibida para restaurar depois
        self._guardar_temp_para_restaurar()
        # Remove qualquer imagem de uma projeção anterior
        self._limpar_camada_imagem()
        self.mostrando_letra = True
        self._em_slides = False
        self.mostrando_relogio = False
        self._modo_extra = None
        # Exibe a janela e aplica o fundo/opacidade configurados
        if not self._is_visible:
            self.root.deiconify()
            self._is_visible = True
        alpha = self._alpha_projecao()
        if self._current_alpha != alpha:
            self.root.attributes('-alpha', alpha)
            self._current_alpha = alpha
        self._aplicar_fundo_projecao()
        self.root.lift()
        # Esconde temperatura
        self.canvas.itemconfig(self.temp_text, text="", state="hidden")
        # Monta o texto final (título em destaque + letra)
        texto_final = f"{titulo}\n\n{texto}" if titulo else texto
        self._desenhar_texto_no_canvas(texto_final)
        # Agenda retorno automático do relógio + temperatura
        seg = max(1, int(float(cfg.get("duracao_seg", 30))))
        self._proj_timer = self.root.after(seg * 1000, self._retornar_ao_relogio)
    def _desenhar_texto_no_canvas(self, texto: str, referencia: str = "",
                                  largura_max: int | None = None) -> tuple:
        """Desenha texto centralizado no canvas com auto-ajuste de fonte.
        Usado tanto na projeção simples (projetar_texto) quanto nos slides.
        Retorna a tupla de fonte aplicada.
        Se referencia for fornecida (ex.: "João 3:16"), exibe no canto inferior direito.
        Se largura_max for fornecida, o texto é quebrado (e centralizado)
        dentro dessa largura máxima — usado pelo anúncio de imagem + texto,
        em que parte da tela é ocupada pela imagem.
        """
        if not self._raiz_viva():
            return ("", 0)
        cfg = getattr(self, "_proj_cfg", None)
        if cfg is None:
            self.configurar_projecao()
        # Calcula largura de quebra e fonte inicial
        w = self.canvas.winfo_width() or self._monitor.width
        h = self.canvas.winfo_height() or self._monitor.height
        wrap_width = max(200, int(w * 0.95))
        if largura_max:
            wrap_width = max(120, min(wrap_width, int(largura_max)))
        centro_x = w // 2
        if largura_max:
            centro_x = int(largura_max) // 2
        tamanho = max(18, int(h * (float(cfg.get("tamanho_pct", 5.0)) / 100.0)))
        familia = cfg.get("fonte", "Montserrat")
        cor = cfg.get("cor", "#FFFFFF")
        # Fallback de fonte: Montserrat/Arial podem não existir no python do
        # sistema usado pelo AppImage; cai para uma fonte sans confirmada.
        disp = set(tkfont.families(self.root))
        if disp and familia not in disp:
            familia = next(
                (f for f in ("DejaVu Sans", "Liberation Sans", "Helvetica",
                             "Noto Sans", "TkDefaultFont") if f in disp),
                "TkDefaultFont")
            cfg["fonte"] = familia
        # Ajusta tamanho para não transbordar verticalmente
        ref = tkfont.Font(family=familia, size=tamanho)
        linhas = 0
        for parte in texto.split("\n"):
            if not parte:
                linhas += 1
            else:
                comp = ref.measure(parte)
                linhas += max(1, int(comp / wrap_width)) if comp > wrap_width else 1
        altura_total = linhas * max(1, ref.metrics("linespace"))
        max_altura = int(h * 0.92)
        if altura_total > max_altura and altura_total > 0:
            fator = max_altura / altura_total
            tamanho = max(12, int(tamanho * fator))
        fonte = (familia, tamanho, "normal")
        self._font_letra = fonte
        self._current_text = texto
        self._current_temp = ""
        # Projeção de texto nunca mostra a temperatura do relógio
        try:
            self.canvas.itemconfig(self.temp_text, text="", state="hidden")
        except (tk.TclError, AttributeError):
            pass
        self.canvas.itemconfig(
            self.overlay_text,
            text=texto,
            font=fonte,
            fill=cor,
            width=wrap_width,
            justify="center",
            state="normal",
        )
        self.canvas.coords(self.overlay_text, centro_x, h // 2)
        # Referência bíblica (livro cap:vers.) — canto inferior direito
        if referencia:
            cor_ref = cfg.get("cor_ref", "#A0A0A0")
            tam_ref = max(12, int(tamanho * 0.45))
            fonte_ref = (familia, tam_ref, "bold")
            self.canvas.itemconfig(
                self.ref_text,
                text=referencia,
                fill=cor_ref,
                font=fonte_ref,
                state="normal",
            )
            self.canvas.coords(self.ref_text, w - 30, h - 30)
        else:
            self.canvas.itemconfig(self.ref_text, text="", state="hidden")
        self.root.update_idletasks()
        return fonte
    # ── Projeção em slides (título + versos, navegação do administrador) ──
    def _limpar_camada_imagem(self) -> None:
        """Remove a camada de imagem projetada (anúncio de imagem/composto).
        Chamado ao projetar um conteúdo só de texto POR CIMA de uma projeção
        anterior com imagem, para não deixar a imagem antiga "colada" no telão
        (o texto novo apareceria por trás da imagem velha).
        """
        if getattr(self, "_imagem_item", None) is not None:
            try:
                self.canvas.delete(self._imagem_item)
            except tk.TclError:
                pass
            self._imagem_item = None
        self._imagem_pil = None
        self._imagem_orig_pil = None
        self._imagem_escala = 1.0
        self._imagem_rect_base = None
        self._texto_largura_base = None
        self._texto_box = (0, 0, 100, 100)
        self._texto_escala = 1.0
        self._mostrando_imagem = False
        self._mostrando_imagem_com_texto = False
    def projetar_slides(self, slides: list, indice_inicial: int = 0) -> None:
        """Inicia projeção em slides (ex.: título do hino e versos).
        Slide 0 deve ser o número/título do hino; os demais, os versos
        (2 linhas por slide). indice_inicial define o primeiro slide
        exibido (usado para iniciar pelo versículo selecionado). Não há
        retorno automático: o administrador navega com as setas
        (slide_proximo/slide_anterior) e encerra com Esc ou
        parar_projecao(), voltando o relógio + temperatura ao telão.
        """
        if not self.rodando or not self._raiz_viva() or not slides:
            return
        # Cancela retorno automático anterior (re-projeção)
        if getattr(self, "_proj_timer", None) is not None:
            try:
                self.root.after_cancel(self._proj_timer)
            except tk.TclError:
                pass
            self._proj_timer = None
        # Guarda a temperatura exibida para restaurar depois
        self._guardar_temp_para_restaurar()
        # Remove qualquer imagem de uma projeção anterior (ex.: anúncio de
        # imagem + texto) para o novo texto aparecer limpo por cima.
        self._limpar_camada_imagem()
        self._slides = list(slides)
        self._slide_index = 0
        self._em_slides = True
        self.mostrando_letra = True
        self.mostrando_relogio = False
        self._modo_extra = None
        # Exibe a janela e aplica o fundo/opacidade configurados
        if not self._is_visible:
            self.root.deiconify()
            self._is_visible = True
        alpha = self._alpha_projecao()
        if self._current_alpha != alpha:
            self.root.attributes('-alpha', alpha)
            self._current_alpha = alpha
        self._aplicar_fundo_projecao()
        self.root.lift()
        # Esconde temperatura
        self.canvas.itemconfig(self.temp_text, text="", state="hidden")
        self._mostrar_slide(max(0, min(indice_inicial, len(self._slides) - 1)))
    def projetar_imagem(self, caminho: str) -> bool:
        """Projeta uma imagem estática centralizada no telão (slide de imagem).
        A imagem é redimensionada para caber na tela preservando a proporção.
        A parada (Esc, parar_projecao, _retornar_ao_relogio) volta o relógio +
        temperatura. Retorna False se o arquivo for inválido/inexistente.
        """
        if not self.rodando or not self._raiz_viva() or not caminho \
                or not os.path.exists(caminho):
            return False
        try:
            from PIL import Image
        except Exception as e:
            log.warning(f"⚠️ PIL indisponível para projetar imagem: {e}")
            return False
        # Cancela retorno automático anterior (re-projeção)
        if getattr(self, "_proj_timer", None) is not None:
            try:
                self.root.after_cancel(self._proj_timer)
            except tk.TclError:
                pass
            self._proj_timer = None
        # Remove qualquer composição anterior (anúncio imagem + texto): o
        # _imagem_rect_base velho redirecionaria a imagem pura para a posição
        # do editor em vez de centralizá-la.
        self._limpar_camada_imagem()
        # Guarda a temperatura exibida para restaurar depois
        self._guardar_temp_para_restaurar()
        self.mostrando_letra = True
        self._em_slides = False
        self._modo_extra = None
        self._mostrando_imagem = True
        self._mostrando_imagem_com_texto = False
        self.mostrando_relogio = False
        # Exibe a janela e aplica o fundo/opacidade configurados
        if not self._is_visible:
            self.root.deiconify()
            self._is_visible = True
        alpha = self._alpha_projecao()
        if self._current_alpha != alpha:
            self.root.attributes('-alpha', alpha)
            self._current_alpha = alpha
        self._aplicar_fundo_projecao()
        self.root.lift()
        # Dá foco de teclado ao telão assim que a projeção começa: sem isso
        # o operador precisa clicar no telão uma vez para o teclado/passador
        # de slides (setas, AvPag/RetPag, espaço, F5) responder.
        self._garantir_foco_teclado()
        # Esconde temperatura
        self.canvas.itemconfig(self.temp_text, text="", state="hidden")
        self.canvas.itemconfig(self.ref_text, text="", state="hidden")
        self.canvas.itemconfig(self.overlay_text, text="", state="hidden")
        try:
            with Image.open(caminho) as img_src:  # noqa: F821
                img_orig = img_src.convert("RGBA")
        except Exception as e:
            log.warning(f"⚠️ Não foi possível abrir a imagem {caminho}: {e}")
            self._retornar_ao_relogio()
            return False
        # Guarda o original para permitir ajustar o tamanho em tempo real
        # (botões "🖼️ −/+" na tela do operador) re-renderizando por cima.
        self._imagem_orig_pil = img_orig
        self._imagem_escala = 1.0
        try:
            ok = self._renderizar_imagem_projetada()
        except Exception as e:
            log.warning(f"⚠️ Não foi possível exibir a imagem no telão: {e}")
            ok = False
        if not ok:
            self._retornar_ao_relogio()
            return False
        return True
    def _renderizar_imagem_projetada(self) -> bool:
        """Renderiza a imagem projetada com a escala atual.
        Quando o anúncio está em modo composição (imagem + texto em camadas
        vivas), renderiza SOMENTE a camada da imagem — o texto continua no
        canvas (overlay_text) intacto. Assim os botões "🖼️ −/+" do painel
        redimensionam apenas a imagem em tempo real.
        """
        orig = getattr(self, "_imagem_orig_pil", None)
        if orig is None or not getattr(self, "_mostrando_imagem", False):
            return False
        try:
            orig.copy()
        except Exception:
            return False
        w = self.canvas.winfo_width() or self._monitor.width
        h = self.canvas.winfo_height() or self._monitor.height
        lar, alt = orig.size
        if lar <= 0 or alt <= 0:
            return False
        escala = float(getattr(self, "_imagem_escala", 1.0) or 1.0)
        rect = getattr(self, "_imagem_rect_base", None)
        if rect is not None:
            # Modo composição (imagem + texto): usa a posição/tamanho salvos
            # no editor (espaço virtual 1440x1080) e redimensiona ao redor
            # do ponto central — nunca escala o texto nem o fundo.
            base_x, base_y, base_w, base_h = rect
            novo_w = max(1, min(int(base_w * escala), w))
            novo_h = max(1, min(int(base_h * escala), h))
            cx = base_x + base_w // 2
            cy = base_y + base_h // 2
            pos_x = max(0, min(cx - novo_w // 2, max(0, w - novo_w)))
            pos_y = max(0, min(cy - novo_h // 2, max(0, h - novo_h)))
            tamanho = (max(1, novo_w), max(1, novo_h))
            pos = (pos_x, pos_y)
        else:
            # Imagem pura: redimensiona para caber na tela preservando a
            # proporção (comportamento original de projetar_imagem).
            fator = min(w / lar, h / alt) * escala
            tamanho = (max(1, int(lar * fator)), max(1, int(alt * fator)))
            pos = None
        redimensao = getattr(Image, "LANCZOS", None) or getattr(Image, "BICUBIC", None)  # noqa: F821
        img_final = orig.resize(tamanho, redimensao)
        try:
            # master=self.root: o telão tem um Tcl/Tk interpreter próprio; sem
            # isso a PhotoImage fica registrada no root da janela principal e
            # o canvas do telão não a enxerga (TclError "image doesn't exist").
            self._imagem_pil = ImageTk.PhotoImage(img_final, master=self.root)  # noqa: F821
            if getattr(self, "_imagem_item", None) is not None:
                try:
                    self.canvas.delete(self._imagem_item)
                except tk.TclError:
                    pass
                self._imagem_item = None
            if pos is None:
                pos = (w // 2, h // 2)
                self._imagem_item = self.canvas.create_image(
                    pos[0], pos[1], image=self._imagem_pil, anchor="center")
            else:
                self._imagem_item = self.canvas.create_image(
                    pos[0], pos[1], image=self._imagem_pil, anchor="nw")
        except Exception as e:
            log.warning(f"⚠️ Não foi possível renderizar a imagem no telão: {e}")
            return False
        self.root.update_idletasks()
        return True
    def imagem_aumentar(self) -> bool:
        """Aumenta a imagem já projetada (redimensionamento ao vivo no telão)."""
        escala = float(getattr(self, "_imagem_escala", 1.0) or 1.0)
        self._imagem_escala = min(2.5, escala + 0.15)
        return self._renderizar_imagem_projetada()
    def imagem_diminuir(self) -> bool:
        """Diminui a imagem já projetada (redimensionamento ao vivo no telão)."""
        escala = float(getattr(self, "_imagem_escala", 1.0) or 1.0)
        self._imagem_escala = max(0.25, escala - 0.15)
        return self._renderizar_imagem_projetada()
    def projetar_imagem_com_texto(self, caminho: str, texto: str,
                                  config_midia: str = "") -> bool:
        """Projeta imagem + texto em CAMADAS separadas no telão.
        A imagem é posicionada/tamanhada conforme config_midia (espaço
        virtual 1440x1080 do editor) e o texto é desenhado por cima como
        camada de canvas (como nos hinos). Assim o operador pode:
          - "🖼️ −/+" redimensionar SÓ a imagem (escala ao vivo);
          - "A−/A+" redimensionar SÓ o texto (fonte ao vivo).
        Sem config_midia (legado), a imagem fica à direita ocupando 55% da
        área útil (mesmo layout lado a lado do compositor antigo).
        Retorna False se o arquivo for inválido/inexistente.
        """
        if not self.rodando or not self._raiz_viva() or not caminho \
                or not os.path.exists(caminho):
            return False
        try:
            pass
        except Exception as e:
            log.warning(f"⚠️ PIL indisponível para projetar imagem + texto: {e}")
            return False
        # Cancela retorno automático anterior (re-projeção)
        if getattr(self, "_proj_timer", None) is not None:
            try:
                self.root.after_cancel(self._proj_timer)
            except tk.TclError:
                pass
            self._proj_timer = None
        # Guarda a temperatura exibida para restaurar depois
        self._guardar_temp_para_restaurar()
        self.mostrando_letra = True
        self._em_slides = False
        self._modo_extra = None
        self._mostrando_imagem = True
        self._mostrando_imagem_com_texto = True
        self._imagem_escala = 1.0
        self.mostrando_relogio = False
        # Exibe a janela e aplica o fundo/opacidade configurados
        if not self._is_visible:
            self.root.deiconify()
            self._is_visible = True
        alpha = self._alpha_projecao()
        if self._current_alpha != alpha:
            self.root.attributes('-alpha', alpha)
            self._current_alpha = alpha
        self._aplicar_fundo_projecao()
        self.root.lift()
        # Esconde temperatura e referência (o texto do anúncio usa o overlay)
        self.canvas.itemconfig(self.temp_text, text="", state="hidden")
        self.canvas.itemconfig(self.ref_text, text="", state="hidden")
        self.canvas.itemconfig(self.overlay_text, text="", state="hidden")
        ok = self._composicao_anuncio(caminho, texto, config_midia)
        if not ok:
            self._retornar_ao_relogio()
            return False
        return True
    def _composicao_anuncio(self, caminho: str, texto: str,
                            config_midia: str = "") -> bool:
        """Composição imagem + texto em camadas (reutilizada pela projeção).
        Desenha a imagem (camada própria) e o texto (overlay na caixa
        ajustada) a partir de config_midia. Não altera os flags de estado
        (/em_slides, /mostrando_*); o chamador decide. Retorna False se o
        arquivo for inválido/inexistente (sem voltar ao relógio).
        """
        if not self.rodando or not caminho or not os.path.exists(caminho):
            return False
        try:
            from PIL import Image
        except Exception as e:
            log.warning(f"⚠️ PIL indisponível para projetar imagem + texto: {e}")
            return False
        try:
            with Image.open(caminho) as img_src:  # noqa: F821
                img_orig = img_src.convert("RGBA")
        except Exception as e:
            log.warning(f"⚠️ Não foi possível abrir a imagem {caminho}: {e}")
            return False
        w = self.canvas.winfo_width() or self._monitor.width
        h = self.canvas.winfo_height() or self._monitor.height
        # Área útil (margens do editor/compositor) para a imagem.
        margem_h = int(w * 0.04) or 40
        margem_v = int(h * 0.06) or 60
        area_w = max(100, w - margem_h * 2)
        area_h = max(100, h - margem_v * 2)
        cfg: dict = {}
        try:
            c = json.loads(config_midia or "{}")
            if isinstance(c, dict):
                cfg = c
        except (ValueError, TypeError, AttributeError):
            cfg = {}
        conf_w = int(cfg.get("w") or 0)
        conf_h = int(cfg.get("h") or 0)
        conf_x = int(cfg.get("x") or 0)
        conf_y = int(cfg.get("y") or 0)
        absoluto = conf_w > 0 and conf_h > 0 and conf_x > 0 and conf_y > 0
        ow, oh = img_orig.size
        if absoluto:
            # Formato novo: converte o espaço virtual 1440x1080 do editor.
            escala_x = w / 1440.0
            escala_y = h / 1080.0
            img_w = max(20, min(int(conf_w * escala_x), w))
            img_h = max(20, min(int(conf_h * escala_y), h))
            img_x = max(0, min(int(conf_x * escala_x), w - img_w))
            img_y = max(0, min(int(conf_y * escala_y), h - img_h))
        elif conf_w > 0 and conf_h > 0:
            # Config legada (320x250 sem posição): imagem à direita, 55%.
            frac = max(0.20, min(0.75, conf_w / (conf_w + 200)))
            asp = ow / max(1, oh)
            iw = max(120, int(area_w * frac))
            ih = int(iw / asp)
            if ih > area_h:
                ih = int(area_h)
                iw = max(120, int(ih * asp))
            img_w = max(20, min(iw, w))
            img_h = max(20, min(ih, h))
            img_x = max(0, min(w - margem_h - img_w, w - img_w))
            img_y = margem_v + (area_h - img_h) // 2
        else:
            # Sem configuração: mesma regra do compositor (lado a lado 55%).
            asp = ow / max(1, oh)
            iw = max(120, int(area_w * 0.55))
            ih = int(iw / asp)
            if ih > area_h:
                ih = int(area_h)
                iw = max(120, int(ih * asp))
            img_w = max(20, min(iw, w))
            img_h = max(20, min(ih, h))
            img_x = max(0, min(w - margem_h - img_w, w - img_w))
            img_y = margem_v + (area_h - img_h) // 2
        self._imagem_rect_base = (img_x, img_y, img_w, img_h)
        self._imagem_orig_pil = img_orig
        # Escala de imagem salva pelos botões 🖼️ −/+ do painel de projeção
        # (persistida em config_midia). Aplica ao vivo sobre a base acima.
        self._imagem_escala = min(2.5, max(0.25, float(cfg.get("img_escala") or 1.0)))
        # Anúncio de imagem nunca mostra temperatura/referência da Bíblia.
        self.canvas.itemconfig(self.temp_text, text="", state="hidden")
        self.canvas.itemconfig(self.ref_text, text="", state="hidden")
        # Texto como digitado pelo usuário, dentro da caixa ajustada no editor.
        texto = (texto or "").strip()
        if not texto:
            # Slide só de imagem: esconde o texto de um slide anterior
            # (overlay_text foi usado pela projeção/tela anterior).
            self.canvas.itemconfig(self.overlay_text, text="", state="hidden")
            self._current_text = ""
        self._composicao_aspect_imagem = ow / max(1.0, oh)
        caixa = _caixa_texto_config(config_midia, texto,
                                    aspect_imagem=ow / max(1.0, oh))
        escala_x = w / 1440.0
        escala_y = h / 1080.0
        cx = max(0, min(int(caixa["x"] * escala_x), w - 1))
        cy = max(0, min(int(caixa["y"] * escala_y), h - 1))
        cw = max(40, min(int(caixa["w"] * escala_x), w - cx))
        ch = max(40, min(int(caixa["h"] * escala_y), h - cy))
        self._texto_box = (cx, cy, cw, ch)
        self._texto_escala = float(caixa.get("s") or 1.0)
        self._texto_largura_base = None
        if texto:
            self._desenhar_texto_anuncio(texto)
        try:
            ok = self._renderizar_imagem_projetada()
        except Exception as e:
            log.warning(f"⚠️ Não foi possível exibir a imagem + texto no telão: {e}")
            ok = False
        return ok
    def _desenhar_texto_anuncio(self, texto: str) -> None:
        """Desenha o texto do anúncio (caixa) no telão, respeitando a escala.
        O texto é desenhado centralizado na caixa (posição/tamanho salvos no
        editor, tx/ty/tw/th) com fonte proporcional à altura da caixa; a
        escala ('ts') é aplicada em tempo real pelos botões A−/A+ do painel.
        A cor segue a configuração "🎨 Projeção" (cor do texto), como no
        modo só-texto.
        """
        cfg = getattr(self, "_proj_cfg", None)
        if cfg is None:
            self.configurar_projecao()
            cfg = getattr(self, "_proj_cfg", None)
        cor_texto = (cfg or {}).get("cor", "#FFFFFF") or "#FFFFFF"
        cx, cy, cw, ch = self._texto_box
        escala = float(getattr(self, "_texto_escala", 1.0) or 1.0)
        alt_tela = self.canvas.winfo_height() or 0
        if alt_tela < 200:
            # Canvas ainda sem tamanho (primeira projeção): usa o monitor.
            alt_tela = int(getattr(self._monitor, "height", 0) or 0) or ch
        # A caixa é guia de layout: a fonte vem do tamanho da caixa * a escala
        # do A−/A+ e o bloco pode ocupar até 92% da altura do telão.
        limite = int(alt_tela * 0.92)
        fonte_pil, linhas = _calcular_texto_em_caixa(
            texto, cw, ch, base_pct=_PCT_FONTE_CAIXA * escala,
            limite_alt=limite)
        familia = _fonte_familia_do_pil(fonte_pil)
        pt = max(8, min(300, int(fonte_pil.size)))
        passo = fonte_pil.size + max(1, fonte_pil.size // 5)
        self.canvas.itemconfig(
            self.overlay_text,
            text="\n".join(linhas),
            font=(familia, pt, "bold"),
            fill=cor_texto,
            width=cw,
            justify="center",
            state="normal",
        )
        # Centraliza vertical e horizontalmente na caixa, sem deixar o bloco
        # sair do telão (a fonte maior pode passar da altura da caixa).
        alt_bloco = passo * len(linhas)
        topo = cy + (ch - alt_bloco) // 2
        if topo < 0:
            topo = 0
        elif topo + alt_bloco > alt_tela:
            topo = max(0, alt_tela - alt_bloco)
        centro_x = cx + cw // 2
        centro_y = topo + alt_bloco // 2
        self.canvas.coords(self.overlay_text, centro_x, centro_y)
        self._current_text = texto
        self._current_temp = ""
        self.root.update_idletasks()
    def _mostrar_slide(self, indice: int) -> bool:
        """Exibe o slide no índice dado (se válido) e retorna True."""
        if not self._slides:
            return False
        if indice < 0 or indice >= len(self._slides):
            return False
        # Garante que a temperatura do relógio não fique sobre o slide (pode
        # ter sido redesenhada por uma atualização de clima em andamento).
        try:
            self.canvas.itemconfig(self.temp_text, text="", state="hidden")
        except (tk.TclError, AttributeError):
            pass
        self._current_temp = ""
        self._slide_index = indice
        slide = self._slides[indice]
        if isinstance(slide, dict):
            # Anúncio multi-slide texto+imagem (ou só texto por slide).
            texto = (slide.get("texto") or "").strip()
            caminho = (slide.get("imagem") or "").strip()
            if caminho and os.path.exists(caminho):
                self._mostrando_imagem = True
                self._mostrando_imagem_com_texto = True
                ok = self._composicao_anuncio(
                    caminho, texto, slide.get("config") or "")
                if ok:
                    # Lembra que ainda estamos em slides (não em imagem única):
                    # a navegação por setas continua valendo para o próximo.
                    self._em_slides = True
                    return True
                # Se a composição falhar, mostra ao menos o texto.
                self._limpar_camada_imagem()
            else:
                self._limpar_camada_imagem()
            self._desenhar_texto_no_canvas(texto or "ANÚNCIO")
            return True
        if isinstance(slide, tuple):
            texto, ref = slide
        else:
            texto, ref = slide, ""
        self._desenhar_texto_no_canvas(texto, referencia=ref)
        return True
    def slide_proximo(self) -> bool:
        """Avança para o próximo slide.
        Se já estiver no último slide, encerra a apresentação como a tecla
        Esc (volta o relógio + temperatura ao telão) e retorna True.
        """
        if not getattr(self, "_em_slides", False):
            return False
        if self._slide_index >= len(self._slides) - 1:
            self.parar_projecao()
            return True
        return self._mostrar_slide(self._slide_index + 1)
    def slide_anterior(self) -> bool:
        """Volta para o slide anterior (retorna False se não houver)."""
        if not getattr(self, "_em_slides", False):
            return False
        return self._mostrar_slide(self._slide_index - 1)
    def _navegar_slides_controle(self, event: object = None) -> str | None:
        """Navega os slides a partir do passador de slides (controle remoto).
        Interpreta as teclas comuns desses aparelhos (setas, AvPag/RetPag,
        espaço, F5, BackSpace) como avançar/voltar slide. Só age durante uma
        projeção em slides; caso contrário, deixa a tecla seguir seu fluxo
        normal (Esc, F11, Ctrl+Q etc. continuam intactos).
        """
        if not getattr(self, "_em_slides", False):
            return None
        keysym = str(getattr(event, 'keysym', '') or '').lower()
        if keysym in ('right', 'down', 'next', 'page_next', 'page_down',
                      'space', 'f5'):
            self.slide_proximo()
            return "break"
        if keysym in ('left', 'up', 'prior', 'page_prior', 'page_up',
                      'backspace'):
            self.slide_anterior()
            return "break"
        return None
    def _garantir_foco_teclado(self) -> None:
        """Traz o foco de teclado para o telão ao iniciar uma projeção.
        O telão é uma janela Tk própria; como o operador costuma acionar a
        projeção pela janela do painel, o foco fica lá e as teclas do
        teclado/passador não chegam ao telão. Aqui o foco é forçado e
        reforçado em alguns ciclos, porque parte dos gerenciadores de
        janelas só o honra depois de processar o mapa/raise da janela.
        """
        try:
            self.root.lift()
            self.root.focus_force()
            self.canvas.focus_set()
            self.root.after_idle(self._reforcar_foco)
            self.root.after(150, self._reforcar_foco)
        except tk.TclError:
            pass
    def _reforcar_foco(self) -> None:
        """Reaplica o foco no telão enquanto ele estiver vivo (best-effort)."""
        try:
            if not getattr(self, "_em_slides", False) or not self._raiz_viva():
                return
            self.root.focus_force()
        except tk.TclError:
            pass
    def _ao_pressionar_esc(self, event: object = None) -> str | None:
        """Esc durante projeção encerra a projeção e volta o relógio ao telão.
        Fora de uma projeção, mantém o comportamento de fechar a janela.
        """
        if getattr(self, "mostrando_letra", False):
            self.parar_projecao()
            return "break"
        self.fechar()
        return None
    def _guardar_temp_para_restaurar(self) -> None:
        """Memoriza a temperatura do relógio para restaurá-la após a projeção.
        Cada texto projetado limpa ``_current_temp`` ao ser desenhado. Em
        projeções encadeadas (ex.: vários itens de um serviço) a projeção
        seguinte encontraria ``_current_temp`` vazio e apagaria o valor salvo,
        fazendo a temperatura não voltar ao encerrar. Só sobrescreve o valor
        memorizado quando há uma temperatura real no relógio.
        """
        if self._current_temp:
            self._temp_salvo = self._current_temp
    def _retornar_ao_relogio(self) -> None:
        """Retorna relógio + temperatura ao telão ao fim da projeção."""
        self._proj_timer = None
        self._modo_extra = None
        if not getattr(self, "mostrando_letra", False):
            return
        self.mostrando_letra = False
        self._em_slides = False
        self._slides = []
        self._slide_index = 0
        self.mostrando_relogio = True
        # Limpa a projeção de imagem (se houver)
        if getattr(self, "_imagem_item", None) is not None:
            try:
                self.canvas.delete(self._imagem_item)
            except tk.TclError:
                pass
            self._imagem_item = None
        self._imagem_pil = None
        self._imagem_orig_pil = None
        self._imagem_escala = 1.0
        self._imagem_rect_base = None
        self._texto_largura_base = None
        self._texto_box = (0, 0, 100, 100)
        self._texto_escala = 1.0
        self._mostrando_imagem = False
        self._mostrando_imagem_com_texto = False
        # Remove a imagem de fundo da projeção (o modo relógio usa a própria
        # cor de fundo configurada no "Configura Relógio").
        if getattr(self, "_fundo_imagem_item", None) is not None:
            try:
                self.canvas.delete(self._fundo_imagem_item)
            except tk.TclError:
                pass
            self._fundo_imagem_item = None
        self._fundo_imagem_to_tk = None
        self._fundo_imagem_caminho = ""
        # Restaura a aparência padrão do relógio no canvas: fonte Digital-7,
        # cor, e posições originais de hora e temperatura (a projeção troca a
        # fonte e move o texto para o centro da tela).
        self._aplicar_cores_relogio()
        self.canvas.itemconfig(self.overlay_text, width=0,
                               font=self._font_hora, state="normal")
        self.canvas.itemconfig(self.temp_text, width=0,
                               font=self._font_temp)
        self.canvas.itemconfig(self.ref_text, text="", state="hidden")
        self.canvas.coords(self.overlay_text, self._cx, self._cy_hora)
        self.canvas.coords(self.temp_text, self._cx, self._cy_temp)
        self._font_temp_exib = None
        self._font_temp_exib_texto = None
        self._current_text = ""
        self._current_temp = ""
        temp = getattr(self, "_temp_salvo", "") or ""
        self.mostrar_relogio(datetime.datetime.now().strftime("%H:%M"), temp)
        self.root.update_idletasks()
    def parar_projecao(self) -> None:
        """Encerra a projeção de texto e restaura o relógio imediatamente."""
        if getattr(self, "_proj_timer", None) is not None:
            try:
                self.root.after_cancel(self._proj_timer)
            except tk.TclError:
                pass
            self._proj_timer = None
        if not getattr(self, "mostrando_letra", False):
            return
        self._retornar_ao_relogio()
    def update(self) -> None:
        """Atualiza a janela com processamento mínimo."""
        if self.rodando:
            try:
                # update_idletasks é mais leve que update() - processa apenas
                # eventos pendentes de redesenho, não a fila de eventos completa
                self.root.update_idletasks()
            except tk.TclError:
                pass
    def fechar(self, event: object = None) -> None:
        self.rodando = False
        try:
            self.root.destroy()
        except tk.TclError:
            pass
    def _exibir_hora_inicial(self, temperatura: str = "") -> None:
        """Exibe a hora atual e temperatura no telão logo após a criação.
        Se houver uma projeção (slides/texto/imagem/medidor) ou vídeo em
        curso, não desenha a hora por cima do conteúdo: apenas atualiza a
        temperatura memorizada, para que ela volte certa quando a projeção
        terminar. O relógio só é redesenhado no modo relógio.
        """
        if not self._raiz_viva():
            return
        if not getattr(self, "mostrando_relogio", True):
            if temperatura:
                self._current_temp = temperatura
                self._guardar_temp_para_restaurar()
            return
        hora = datetime.datetime.now().strftime("%H:%M")
        self.canvas.itemconfig(self.overlay_text, text=hora, state="normal")
        self._current_text = hora
        if temperatura:
            self.canvas.itemconfig(
                self.temp_text,
                text=temperatura,
                font=self._fonte_temp_para_texto(temperatura),
                state="normal",
            )
            self._current_temp = temperatura
        # update_idletasks é mais leve que update()
        self.root.update_idletasks()
    # ── Cronômetro e contagem regressiva (projeção dos medidores) ──
    def _tam_digital(self, altura_px: int, fator: float) -> int:
        """Calcula o tamanho em pt da fonte Digital-7 para o medidor.
        A proporção linha/base da Digital-7 é medida com uma fonte de
        referência e a escala é cravada para ~40% da altura da tela
        (ajustável via fator), como acontece com o relógio.
        """
        ref = tkfont.Font(family="Digital-7", size=100)
        px_por_pt = ref.metrics("linespace") / 100.0
        if px_por_pt <= 0:
            px_por_pt = 1.0
        alvo = max(60, int(altura_px * 0.40 * fator))
        size = max(40, min(620, int(alvo / px_por_pt)))
        fonte = tkfont.Font(family="Digital-7", size=size)
        real = fonte.metrics("linespace")
        if real > 0 and abs(real - alvo) > 2:
            size = max(40, min(620, int(size * alvo / real)))
        return size
    def _projetar_medidor(self, cfg: dict, modo: str,
                          subtitulo: str = "", tempo: str = "00:00") -> None:
        """Inicia/atualiza a projeção de um medidor (cronômetro/contagem).
        Reusa o ciclo de vida das projeções: enquanto ativo, mostrando_
        letra fica True e Esc ou parar_projecao() restauram o relógio.
        Usa a mesma fonte Digital-7, cores, fundo e transparência do
        relógio ("fundo_opaco" => opaco, senão 0.55).
        """
        if not self._raiz_viva():
            return
        # Cancela retorno automático anterior (re-projeção)
        if getattr(self, "_proj_timer", None) is not None:
            try:
                self.root.after_cancel(self._proj_timer)
            except tk.TclError:
                pass
            self._proj_timer = None
        self._guardar_temp_para_restaurar()
        self._limpar_camada_imagem()
        self.mostrando_letra = True
        self._em_slides = False
        self.mostrando_relogio = False
        if not self._is_visible:
            self.root.deiconify()
            self._is_visible = True
        # Transparência igual à do relógio (opaco se fundo_opaco)
        alpha = 1.0 if cfg.get("fundo_opaco") else self._alpha_relogio()
        if self._current_alpha != alpha:
            self.root.attributes('-alpha', alpha)
            self._current_alpha = alpha
        # Fundo (cor lisa; imagem de fundo não é usada nos medidores)
        cor_fundo = cfg.get("cor_fundo", "#000000")
        if getattr(self, "_fundo_imagem_item", None) is not None:
            try:
                self.canvas.delete(self._fundo_imagem_item)
            except tk.TclError:
                pass
            self._fundo_imagem_item = None
        self._fundo_imagem_to_tk = None
        self._fundo_imagem_caminho = ""
        self.root.configure(bg=cor_fundo)
        self.main_frame.configure(bg=cor_fundo)
        self.canvas.configure(bg=cor_fundo)
        self.root.lift()
        w = self.canvas.winfo_width() or self._monitor.width
        h = self.canvas.winfo_height() or self._monitor.height
        if w < 100 or h < 100:
            w, h = self._monitor.width, self._monitor.height
        try:
            fator = float(cfg.get("fator_hora", 1.0) or 1.0)
        except (TypeError, ValueError):
            fator = 1.0
        tam = self._tam_digital(h, fator)
        cor = cfg.get("cor_hora", "#F5BE08")
        cor_sub = cfg.get("cor_temp", cor)
        self.canvas.itemconfig(
            self.overlay_text,
            text=tempo, font=("Digital-7", tam, "normal"),
            fill=cor, width=0, justify="center", state="normal",
        )
        self._current_text = tempo
        if subtitulo:
            if modo == "contagem":
                # Nome/frase da contagem regressiva: fonte/tamanho/negrito/
                # maiúsculas/quebra de linha são configuráveis e valem só
                # para o subtítulo. Guarda o cfg p/ as atualizações seguintes.
                self._sub_cfg_medidor = dict(cfg)
                fam_sub = str(cfg.get("fonte_sub", "Arial") or "Arial")
                try:
                    fator_sub = float(cfg.get("fator_sub", 0.30) or 0.30)
                except (TypeError, ValueError):
                    fator_sub = 0.30
                peso_sub = ("bold"
                            if str(cfg.get("peso_sub", "bold")) != "normal"
                            else "normal")
                tam_sub = max(12, int(tam * fator_sub))
                tam_sub = min(tam_sub, 320)
                texto_sub = subtitulo
                if cfg.get("maiusculas_sub"):
                    texto_sub = subtitulo.upper()
                wrapl = int(w * 0.9) if cfg.get("quebrar_sub") else 0
                self.canvas.itemconfig(
                    self.temp_text,
                    text=texto_sub, font=(fam_sub, tam_sub, peso_sub),
                    fill=cor_sub, width=wrapl, justify="center", state="normal",
                )
                self._current_temp = subtitulo
                self._posicionar_medidor_contagem(
                    w, h, cfg, tam, fam_sub, tam_sub, peso_sub)
            else:
                # Cronômetro (sem subtítulo): mantém o comportamento anterior.
                tam_sub = max(18, int(tam * 0.30))
                tam_sub = min(tam_sub, 160)
                self.canvas.itemconfig(
                    self.temp_text,
                    text=subtitulo, font=("Digital-7", tam_sub, "normal"),
                    fill=cor_sub, width=0, justify="center", state="normal",
                )
                self._current_temp = subtitulo
                self.canvas.coords(self.overlay_text, w // 2, int(h * 0.42))
                self.canvas.coords(self.temp_text, w // 2, int(h * 0.63))
        else:
            self.canvas.itemconfig(self.temp_text, text="", state="hidden")
            self._current_temp = ""
            self.canvas.coords(self.overlay_text, w // 2, h // 2)
        self.canvas.itemconfig(self.ref_text, text="", state="hidden")
        self._modo_extra = modo
        self.root.update_idletasks()
    def _posicionar_medidor_contagem(self, w: int, h: int, cfg: dict,
                                     tam: int, fam_sub: str, tam_sub: int,
                                     peso_sub: str) -> None:
        """Posiciona o nome/frase da contagem acima ou abaixo do número.
        O número fica centralizado na vertical da tela (h/2), como no
        cronômetro. Usa as alturas reais (bbox) do número e do nome/frase
        para garantir que nunca se sobreponham: o afastamento entre a borda
        do número e a borda do nome/frase é proporcional à altura da tela
        ("dist_sub", padrão 0.05) e a posição ("posicao_sub") escolhe acima
        ou abaixo do número.
        """
        cy_num = h // 2
        posicao = str(cfg.get("posicao_sub", "abaixo") or "abaixo")
        try:
            dist = float(cfg.get("dist_sub", 0.05) or 0.05)
        except (TypeError, ValueError):
            dist = 0.05
        dist = max(0.0, min(dist, 0.75))
        gap = int(h * dist) + 1
        try:
            self.root.update_idletasks()
            b_num = self.canvas.bbox(self.overlay_text)
            b_sub = self.canvas.bbox(self.temp_text)
        except tk.TclError:
            b_num = b_sub = None
        if b_num is not None and len(b_num) == 4 and b_num[3] > b_num[1]:
            h_num = b_num[3] - b_num[1]
        else:
            h_num = tkfont.Font(family="Digital-7", size=tam).metrics("linespace")
        if b_sub is not None and len(b_sub) == 4 and b_sub[3] > b_sub[1]:
            h_sub = b_sub[3] - b_sub[1]
        else:
            h_sub = tkfont.Font(family=fam_sub, size=tam_sub,
                                weight=peso_sub).metrics("linespace")
        if posicao == "acima":
            cy_sub = cy_num - h_num // 2 - gap - h_sub // 2
        else:
            cy_sub = cy_num + h_num // 2 + gap + h_sub // 2
        margem = 10
        if h_sub > 0:
            if posicao == "acima":
                topo_ok = margem + h_sub // 2
                if cy_sub < topo_ok:
                    # Não cabe acima com o número centralizado: encosta o
                    # nome/frase no topo e desce o número para abrir espaço.
                    cy_sub = topo_ok
                    cy_num = cy_sub + h_num // 2 + gap + h_sub // 2
                    if cy_num > h - margem - h_num // 2:
                        cy_num = h - margem - h_num // 2
                        cy_sub = cy_num - h_num // 2 - gap - h_sub // 2
            else:
                base_ok = h - margem - h_sub // 2
                if cy_sub > base_ok:
                    # Não cabe abaixo com o número centralizado: encosta o
                    # nome/frase na base e sobe o número para abrir espaço.
                    cy_sub = base_ok
                    cy_num = cy_sub - h_num // 2 - gap - h_sub // 2
                    if cy_num < margem + h_num // 2:
                        cy_num = margem + h_num // 2
                        cy_sub = cy_num + h_num // 2 + gap + h_sub // 2
        self.canvas.coords(self.overlay_text, w // 2, cy_num)
        self.canvas.coords(self.temp_text, w // 2, cy_sub)
    def _atualizar_medidor(self, tempo: str, subtitulo: str = "") -> None:
        """Atualiza o número e o subtítulo do medidor sem redesenhar o layout."""
        if not self._raiz_viva():
            return
        try:
            self.canvas.itemconfig(self.overlay_text, text=tempo)
            self._current_text = tempo
            if subtitulo:
                texto = subtitulo
                scfg = getattr(self, "_sub_cfg_medidor", None)
                if scfg and scfg.get("maiusculas_sub"):
                    texto = subtitulo.upper()
                self.canvas.itemconfig(self.temp_text, text=texto)
                self._current_temp = subtitulo
            self.root.update_idletasks()
        except tk.TclError:
            pass
    def encerrar_medidor(self) -> None:
        """Encerra o medidor ativo e volta o relógio + temperatura ao telão."""
        self._modo_extra = None
        self._sub_cfg_medidor = None
        if getattr(self, "mostrando_letra", False):
            self.parar_projecao()
        else:
            if not self._is_visible:
                self.root.deiconify()
                self._is_visible = True
            self.root.lift()
# ────────────────────────────────────────────────────────────────────