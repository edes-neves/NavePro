"""tema_painel (mixin).

Extraído de NavePro.py sem alteração de comportamento: a AppInterface
herda deste mixin.
"""

from __future__ import annotations

import json
import os
import re
import tkinter as tk
import tkinter.messagebox
import tkinter.simpledialog
from tkinter import ttk

from navepro.core.log import get_logger
from navepro.core.paths import CONFIG_FILE
from navepro.core.tema import (
    _OPCOES_COR_TK,
    _OPCOES_TEXTO,
    COR_AREA_CONTROLES_CLARA,
    _cor_clara,
)
from navepro.core.widgets_arredondados import TkArredondado

log = get_logger("tema_painel")

# Botões e campos desenham cantos arredondados (fachada do tkinter).
tk = TkArredondado(tk)


class TemaPainelMixin:
    def _alternar_tema(self) -> None:
        """Alterna entre tema escuro (padrão) e claro, persistindo a escolha."""
        novo = 'claro' if self.tema != 'claro' else 'escuro'
        self.tema = novo
        self.config_data['tema'] = novo
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.exception(f"Erro ao salvar tema: {e}")
        if getattr(self, '_var_tema_claro', None) is not None:
            self._var_tema_claro.set(novo == 'claro')
        self._aplicar_tema()
    def _aplicar_tema(self) -> None:
        """Aplica o tema ativo (claro/escuro) a toda a interface."""
        self._aplicar_tema_ttk()
        self._aplicar_tema_menu()
        try:
            # No claro, a captura das cores escuras de origem precisa rodar
            # ANTES de qualquer pintura: alguns pais (CampoArredondado)
            # empurram bg/fg para o filho ao serem recoloridos e, se a cor
            # clara chegasse primeiro, ela seria gravada como se fosse a
            # escura (campos Cidade/UF/busca voltavam claros no escuro).
            if self.tema == 'claro':
                self._recolorir_arvore(self.root, capturar=True)
            self._recolorir_arvore(self.root)
            # O campo de resultados é recolorido à parte (fica fora do passe
            # genérico para o cinza claro não distorcer a cada visita).
            self._pintar_lista_cores()
        except tk.TclError:
            pass
        # Rede de segurança: garante o fundo correto de Cidade/UF/busca em
        # cada tema, mesmo que o passe genérico tenha deixado para trás.
        self._garantir_campos_tema()
        # Mantém o Sorteio Profissional (quando aberto) no mesmo tema.
        sync_sorteio = getattr(self, '_sorteio_sync_tema', None)
        if sync_sorteio is not None:
            try:
                sync_sorteio()
            except Exception as e:
                log.debug("Falha ao sincronizar o tema do sorteio: %s", e)
    def _garantir_campos_tema(self) -> None:
        """Reafirma, por tema, a cor de fundo dos campos Cidade/UF/busca.

        Independente do passe genérico de recoloração (que depende das cores
        de origem gravadas). As cores reafirmadas são exatamente as corretas
        de cada tema, então nada muda quando o passe genérico já acertou —
        só corrige o caso em que um campo tivesse ficado com a cor do outro
        tema (ex.: Cidade/UF/busca claros no tema escuro).
        """
        claro = self.tema == 'claro'
        # Cidade/UF: CampoArredondado (área cinza); no escuro usa o próprio
        # fundo escuro gravado ao marcar o campo.
        for campo in (getattr(self, 'entry_cidade', None),
                      getattr(self, 'entry_estado', None)):
            if campo is None:
                continue
            if claro:
                alvo = _cor_clara('#eaeef2')
            else:
                alvo = getattr(
                    campo, '_navepro_area_cinza_escuro', '#eaeef2')
            try:
                campo.configure(bg=alvo)
            except tk.TclError:
                pass
        # Busca: fundo escuro próprio (#21262d) e o mesmo cinza claro.
        busca = getattr(self, 'entry_busca', None)
        if busca is not None:
            try:
                busca.configure(bg=_cor_clara('#21262d') if claro else '#21262d')
            except tk.TclError:
                pass
    def _aplicar_tema_ttk(self) -> None:
        """Ajusta os estilos globais ttk (Treeview/Scrollbar) ao tema."""
        try:
            style = ttk.Style()
            if self.tema == 'claro':
                style.configure(
                    "Treeview",
                    background=_cor_clara('#21262d'), foreground='#1f2328',
                    fieldbackground=_cor_clara('#21262d'), font=("Arial", 10))
                style.configure(
                    "Treeview.Heading",
                    background=_cor_clara('#161b22'), foreground='#1f2328',
                    font=("Arial", 10, "bold"))
                style.map('Treeview',
                          background=[('selected', '#0969da')],
                          foreground=[('selected', '#ffffff')])
                style.configure(
                    "Vertical.TScrollbar",
                    background=_cor_clara('#21262d'), troughcolor=_cor_clara('#161b22'),
                    arrowcolor='#1f2328')
            else:
                style.configure(
                    "Treeview",
                    background="#21262d", foreground="#c9d1d9",
                    fieldbackground="#21262d", font=("Arial", 10))
                style.configure(
                    "Treeview.Heading",
                    background="#161b22", foreground="#f0c040",
                    font=("Arial", 10, "bold"))
                style.map('Treeview',
                          background=[('selected', '#6e40c9')],
                          foreground=[('selected', '#ffffff')])
                style.configure(
                    "Vertical.TScrollbar",
                    background="#21262d", troughcolor="#161b22",
                    arrowcolor="#f0c040")
        except (Exception, tk.TclError):
            pass
    def _aplicar_tema_menu(self) -> None:
        """Recolore a barra de menu e os menus suspensos."""
        menus = getattr(self, '_menus', [])
        if not menus:
            return
        if self.tema == 'claro':
            menubar_cfg = dict(bg='#b5c0ca', fg='#24292f',
                               activebackground=COR_AREA_CONTROLES_CLARA,
                               activeforeground='#24292f')
            menu_cfg = dict(bg='#bcc6d0', fg='#1f2328',
                            activebackground=COR_AREA_CONTROLES_CLARA,
                            activeforeground='#24292f')
        else:
            menubar_cfg = dict(bg='#161b22', fg='#f0c040',
                               activebackground='#6e40c9',
                               activeforeground='#f0c040')
            menu_cfg = dict(bg='#21262d', fg='#c9d1d9',
                            activebackground='#6e40c9',
                            activeforeground='#f0c040')
        for i, menu in enumerate(menus):
            try:
                menu.configure(**(menubar_cfg if i == 0 else menu_cfg))
            except (Exception, tk.TclError):
                pass
    def _recolorir_arvore(self, base, capturar: bool = False) -> None:
        """Aplica a recoloração de tema a `base` e a todos os seus filhos.

        Com `capturar=True` faz só a passada de captura das cores de origem
        (sem pintar), que precisa ocorrer para toda a árvore antes de
        qualquer `configure` (ver `_aplicar_tema`).
        """
        # Janelas que gerenciam o próprio tema (ex.: Sorteio Profissional):
        # a subárvore inteira fica de fora do passe genérico.
        if getattr(base, '_navepro_tema_proprio', False):
            return
        self._aplicar_tema_widget(base, capturar=capturar)
        try:
            for filho in base.winfo_children():
                self._recolorir_arvore(filho, capturar=capturar)
        except tk.TclError:
            pass
    def _varrer_toplevels_tema(self) -> None:
        """Recoloriza janelas auxiliares (Toplevel) criadas após o app.

        Chamado periodicamente (junto do loop do telão). Cada janela
        recria estilos escuros ao ser aberta; aqui garantimos que o tema
        ativo seja sempre respeitado sem tocar no código de criação.
        """
        try:
            self._aplicar_tema_ttk()
            if self.tema != 'claro':
                return
            self._recolorir_arvore(self.root, capturar=True)
            self._recolorir_arvore(self.root)
            for filho in self.root.winfo_children():
                try:
                    if filho.winfo_class() == 'Toplevel':
                        self._recolorir_arvore(filho, capturar=True)
                        self._recolorir_arvore(filho)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass
    def _aplicar_tema_widget(self, widget, capturar: bool = False) -> None:
        """Ajusta as cores de um único widget conforme o tema ativo.

        No tema ESCURO restaura as cores escura originais (gravadas na
        primeira visita em claro). No CLARO registra as cores atuais como
        origem e aplica a equivalência clara. Pergunta valores sobrescritos
        dinamicamente (ex.: linha tocando na lista) como nova origem, para
        a troca de tema nunca perder o estado visual.

        Com `capturar=True` faz apenas o registro das cores de origem (sem
        pintar): é a passada que roda para toda a árvore antes de qualquer
        `configure`, para não gravar cores já empurradas por um pai.
        """
        try:
            if not widget.winfo_exists():
                return
            # Widgets do campo de resultados têm cores próprias por tema
            # (ver _pintar_lista_cores): fora da recolorização genérica para
            # o cinza claro da lista não "escorregar" a cada visita.
            if getattr(widget, '_navepro_tema_ignorar', False):
                return
            # Faixas que delimitam as seções do painel: azul da temperatura no
            # claro; igual ao cartão no escuro, isto é, invisível.
            if getattr(widget, '_navepro_faixa_secao', False):
                if not capturar:
                    try:
                        widget.configure(
                            bg=(_cor_clara('#58a6ff')
                                if self.tema == 'claro' else '#161b22')
                        )
                    except tk.TclError:
                        pass
                return
            # Área de controles do operador: bloco cinza só no tema claro.
            if getattr(widget, '_navepro_area_cinza_clara', False):
                if not capturar:
                    escuro = getattr(
                        widget, '_navepro_area_cinza_escuro', '#161b22')
                    claro = getattr(
                        widget, '_navepro_area_cinza_claro', None)
                    try:
                        if self.tema == 'claro':
                            bg = claro or _cor_clara(escuro)
                        else:
                            bg = escuro
                        widget.configure(bg=bg)
                    except tk.TclError:
                        pass
                return
            if isinstance(widget, ttk.Widget):
                return
            # Menus têm tratamento próprio (_aplicar_tema_menu); recolorir
            # aqui brigaria com ele e restauraria a cor errada ao voltar.
            if str(widget.winfo_class()) == 'Menu':
                return
            keys = set(widget.keys())
        except tk.TclError:
            return

        ops = [o for o in _OPCOES_COR_TK if o in keys]

        def _ler(op):
            try:
                valor = widget.cget(op)
            except tk.TclError:
                return None
            # Alguns widgets (ex.: tk.Menu) devolvem Tcl_Obj em vez de str;
            # sem normalizar, _cor_clara quebra com AttributeError.
            if valor is None or isinstance(valor, str):
                return valor
            return str(valor)

        origem = getattr(widget, '_navepro_tema_origem', None)
        aplicado = getattr(widget, '_navepro_tema_aplicado', None)

        if self.tema == 'escuro':
            if not origem:
                return
            cfg = {}
            for o in ops:
                v = origem.get(o)
                if v:
                    cfg[o] = v
            try:
                widget.configure(**cfg)
            except Exception:
                for o, v in cfg.items():
                    try:
                        widget.configure(**{o: v})
                    except Exception:
                        pass
            try:
                widget._navepro_tema_origem = None
                widget._navepro_tema_aplicado = None
            except Exception:
                pass
            return

        # ── Tema CLARO ──
        # Se já houve a passada de captura, a origem está correta e não deve
        # ser tocada aqui (o valor atual pode ter sido empurrado por um pai).
        pre_capturado = origem is not None
        if origem is None:
            origem = {}
        if aplicado is None:
            aplicado = {}

        if capturar:
            # Passada só de captura, sem pintar: grava as cores escuras
            # atuais como origem. Roda para toda a árvore antes de qualquer
            # `configure`, pois um pai (CampoArredondado) empurra bg/fg ao
            # filho e ler depois gravaria a cor clara como se fosse a escura.
            for o in ops:
                atual = _ler(o)
                if atual is None:
                    continue
                if aplicado.get(o) != atual:
                    origem[o] = atual
            try:
                widget._navepro_tema_origem = origem
                widget._navepro_tema_aplicado = aplicado
            except Exception:
                pass
            return

        # Passo 1: mapeia as opções que funcionam como FUNDO e guarda o
        # resultado para decidir as cores de texto em passo 2.
        bg_final = None
        base: dict[str, str] = {}
        cfg: dict[str, str] = {}
        for o in ops:
            atual = _ler(o)
            if atual is None:
                continue
            if o in ('background', 'activebackground', 'selectbackground',
                     'troughcolor'):
                if not pre_capturado and aplicado.get(o) != atual:
                    origem[o] = atual
                # Mapeia sempre a partir da cor ESCURA de origem: reler a cor
                # atual faz o cinza claro (#8b949e) "escorregar" para #656d76
                # a cada visita, pois #8b949e também é chave do mapa claro.
                clara = _cor_clara(origem.get(o) or atual)
                if o == 'background':
                    bg_final = clara
                base[o] = clara
                aplicado[o] = clara
                cfg[o] = clara

        # Passo 2: opções de TEXTO decididas com o fundo correspondente.
        def _fundo_para(op: str) -> str | None:
            if op == 'activeforeground':
                return base.get('activebackground', bg_final)
            if op == 'selectforeground':
                return base.get('selectbackground', bg_final)
            return bg_final

        for o in ops:
            if o in ('background', 'activebackground', 'selectbackground',
                     'troughcolor'):
                continue
            atual = _ler(o)
            if atual is None:
                continue
            if not pre_capturado and aplicado.get(o) != atual:
                origem[o] = atual
            escura = origem.get(o)
            if not escura:
                continue
            if o in _OPCOES_TEXTO:
                clara = _cor_clara(escura, _fundo_para(o))
            else:
                clara = _cor_clara(escura)
            aplicado[o] = clara
            cfg[o] = clara

        try:
            widget.configure(**cfg)
        except Exception:
            for o, v in cfg.items():
                try:
                    widget.configure(**{o: v})
                except Exception:
                    pass

        try:
            widget._navepro_tema_origem = origem
            widget._navepro_tema_aplicado = aplicado
        except Exception:
            pass
    def _pintar_lista_cores(self) -> None:
        """Recolore o campo de resultados (lista de hinos/músicas) no tema atual.

        No tema claro o campo usa o mesmo tom cinza da faixa de botões do
        rodapé (``COR_AREA_CONTROLES_CLARA``), que se destaca do fundo geral
        (mais escuro) do painel. As cores claras saem sempre das cores
        ESCURAS originais (via ``_cor_clara``), sem reler a cor já clareada —
        reler fazia o cinza "escorregar" para ``#656d76`` a cada visita do tema.
        """
        claro = self.tema == 'claro'

        # No tema claro o campo usa a mesma cor da faixa de botões do rodapé
        # ("por baixo dos botões"), lida direto do frame dos controles.
        face_clara = COR_AREA_CONTROLES_CLARA
        if claro:
            barra = getattr(self, 'controls_frame', None)
            if barra is not None:
                try:
                    face_clara = barra.cget('background')
                except tk.TclError:
                    pass

        def _neutro(escura: str) -> str:
            # Superfícies cinza do campo (container, linha, fundo do rótulo).
            return face_clara if claro else escura

        def _acc(escura: str) -> str:
            # Cores de destaque (verde da linha atual, roxo do hover/progresso).
            return _cor_clara(escura) if claro else escura

        def _fg(escura: str, bg_escura: str) -> str:
            if not claro:
                return escura
            return _cor_clara(escura, _cor_clara(bg_escura))

        superficies = [
            (getattr(self, 'list_container', None), '#161b22'),
            (getattr(self, 'canvas_lista', None), '#161b22'),
            (getattr(self, 'scroll_frame', None), '#161b22'),
        ]
        for w, escura in superficies:
            if w is None:
                continue
            try:
                w.configure(bg=_neutro(escura))
            except tk.TclError:
                pass

        sb = getattr(self, 'scrollbar_lista', None)
        if sb is not None:
            try:
                sb.configure(bg=_neutro('#21262d'), troughcolor=_neutro('#161b22'),
                             activebackground=_acc('#6e40c9'))
            except tk.TclError:
                pass

        if not hasattr(self, '_pool_frames'):
            return

        for lbl in (getattr(self, '_pool_label_count', None),
                    getattr(self, '_pool_label_vazio', None)):
            if lbl is None:
                continue
            try:
                lbl.configure(bg=_neutro('#161b22'), fg=_fg('#8b949e', '#161b22'))
            except tk.TclError:
                pass

        for i in range(len(self._pool_frames)):
            escura = '#1c2128' if i % 2 == 0 else '#21262d'
            frame = self._pool_frames[i]
            btn = self._pool_botoes[i]
            atual = (self.arquivo_atual is not None
                     and self._pool_caminhos[i] == self.arquivo_atual)
            try:
                frame.configure(bg=_neutro(escura))
            except tk.TclError:
                pass
            try:
                if atual:
                    btn.configure(bg=_acc('#238636'),
                                  fg=_fg('#f0c040', '#238636'),
                                  activebackground=_acc('#6e40c9'),
                                  activeforeground=_fg('#c9d1d9', '#6e40c9'))
                else:
                    btn.configure(bg=_neutro(escura), fg=_fg('#c9d1d9', escura),
                                  activebackground=_acc('#6e40c9'),
                                  activeforeground=_fg('#c9d1d9', '#6e40c9'))
            except tk.TclError:
                pass
            progress_frame, progress_bar = self._pool_progress_bars[i]
            try:
                progress_frame.configure(bg=_neutro('#161b22'))
                progress_bar.configure(bg=_acc('#6e40c9'))
            except tk.TclError:
                pass
    def _criar_pool_botoes(self) -> None:
        """Cria o pool de itens recicláveis (cabeçalho + 80 linhas)."""
        self._pool_botoes = []
        self._pool_frames = []
        self._pool_progress_bars = []
        self._pool_label_count = tk.Label(
            self.scroll_frame, text="", fg='#8b949e', bg='#161b22', font=("Arial", 11)
        )
        self._pool_label_count.pack(pady=5, anchor='center')
        for i in range(80):  # Cria 80 linhas
            # Frame container (cor alternada)
            item_frame = tk.Frame(self.scroll_frame, bg='#1c2128' if i % 2 == 0 else '#21262d')
            item_frame.pack(fill='x', padx=100, pady=1)

            # Barra de progresso (inicialmente oculta) - usa place para largura relativa
            progress_frame = tk.Frame(item_frame, bg='#161b22', height=3)
            progress_bar = tk.Frame(progress_frame, bg='#6e40c9', height=3)
            progress_frame.pack_forget()  # Oculta inicialmente

            # Botão principal
            btn = tk.Button(
                item_frame,
                text="", anchor='center',
                font=("Arial", 11),
                bg='#1c2128' if i % 2 == 0 else '#21262d',
                fg='#c9d1d9',
                activebackground='#6e40c9',
                cursor='hand2', bd=0, highlightthickness=0
            )
            btn.pack(fill='x', side='top')

            self._pool_botoes.append(btn)
            self._pool_frames.append(item_frame)
            self._pool_progress_bars.append((progress_frame, progress_bar))

        # Label de vazio (inicialmente oculto)
        self._pool_label_vazio = tk.Label(
            self.scroll_frame, text="🔍 Nenhum arquivo encontrado",
            fg='#8b949e', bg='#161b22', font=("Arial", 12)
        )
        # Guarda referência do caminho atual para cada botão
        self._pool_caminhos: list[str | None] = [None] * 80
        # Timer para animação do ícone pulsante
        self._pulse_timer: str | None = None
        self._pulse_index: int = -1
        self._pulse_state: int = 0
        # Timer que segura um aviso no rodapé (ver mostrar_aviso)
        self._aviso_timer: str | None = None

        # O campo tem cor própria por tema; fora da recolorização genérica.
        for w in (self._pool_label_count, self._pool_label_vazio,
                  *self._pool_frames, *self._pool_botoes):
            try:
                w._navepro_tema_ignorar = True
            except Exception:
                pass
        for progress_frame, progress_bar in self._pool_progress_bars:
            try:
                progress_frame._navepro_tema_ignorar = True
                progress_bar._navepro_tema_ignorar = True
            except Exception:
                pass
        self._pintar_lista_cores()
    def atualizar_lista(self) -> None:
        """Atualiza a lista reciclando itens do pool (cores alternadas, barra de progresso)."""
        if not hasattr(self, '_pool_botoes'):
            self._criar_pool_botoes()

        # Esconde label vazio, mostra contagem
        self._pool_label_vazio.pack_forget()
        dados = self.arquivos_encontrados
        total = len(dados)

        if not dados:
            self._pool_label_count.config(text="")
            self._pool_label_vazio.pack(pady=20, anchor='center')
            for frame in self._pool_frames:
                frame.pack_forget()
            return

        self._pool_label_count.config(text=f"📋 {total} arquivo(s)")

        num_visiveis = min(total, 80)
        for i in range(80):
            if i < num_visiveis:
                caminho = dados[i]
                nome = os.path.basename(caminho)
                tipo = "🎵" if caminho.lower().endswith(('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac')) else "🎬"

                # Extrai número do hino do nome do arquivo (para exibição)
                match_num = re.match(r'^(\d+)', nome)
                if match_num:
                    num_hino = match_num.group(1)
                    resto_nome = nome[len(num_hino):].lstrip(' -._')
                else:
                    num_hino = ""
                    resto_nome = nome

                # Verifica se é a música atual
                is_current = (self.arquivo_atual and caminho == self.arquivo_atual)

                # Monta texto: contagem sequencial + número do hino entre parênteses
                if num_hino:
                    texto = f"  {i+1}. {tipo} ({num_hino}) {resto_nome}"
                else:
                    texto = f"  {i+1}. {tipo} {nome}"

                # Se for a música atual, prefixo muda conforme pulse
                if is_current:
                    texto = "▶" + texto[1:] if getattr(self, '_pulse_state', 0) == 0 else "▷" + texto[1:]

                frame = self._pool_frames[i]
                btn = self._pool_botoes[i]

                btn.config(text=texto)
                self._pool_caminhos[i] = caminho
                btn.config(command=lambda c=caminho: self.tocar_arquivo(c))

                frame.pack(fill='x', padx=100, pady=1)

                # Barra de progresso para item atual (ocupa toda a largura do frame)
                progress_frame, progress_bar = self._pool_progress_bars[i]
                if is_current and self.player and self.player.is_playing:
                    duracao = self.player.duracao_total
                    if duracao and duracao > 0:
                        elapsed = self.player.obter_tempo_decorrido()
                        frac = min(elapsed / duracao, 1.0)
                        progress_frame.pack(fill='x', side='top', before=btn)
                        # place com relwidth = fração, ocupando toda a largura
                        progress_bar.place(relwidth=frac, relheight=1.0)
                    else:
                        # Se não tem duração, mostra barra cheia (indeterminado)
                        progress_frame.pack(fill='x', side='top', before=btn)
                        progress_bar.place(relwidth=1.0, relheight=1.0)
                else:
                    progress_frame.pack_forget()
            else:
                self._pool_frames[i].pack_forget()

        # Aplica as cores do tema ao campo (verde na linha atual, cinza claro
        # no tema claro etc.) sempre a partir das cores escuras originais.
        self._pintar_lista_cores()

        # Inicia animação do ícone pulsante se há música tocando
        if self.arquivo_atual and self.player and self.player.is_playing:
            self._iniciar_pulse()
        else:
            self._parar_pulse()
