"""Janela de janela_ordem_servico do painel do operador (mixin).

Extraída de NavePro.py sem alteração de comportamento: a AppInterface
herda deste mixin para montar a janela.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
import tkinter.messagebox
import tkinter.simpledialog
from datetime import datetime
from tkinter import ttk

from navepro.config import EXTENSOES_AUDIO, EXTENSOES_VIDEO
from navepro.core.anuncios import (
    _buscar_anuncio_por_ref,
    _buscar_anuncio_por_termo,
    _listar_anuncios_db,
)
from navepro.core.banco import db_query
from navepro.core.inicializacao import _sincronizar_uploads_midia
from navepro.core.log import get_logger
from navepro.core.servicos import (
    _SERVICO_PROXIMO_ITEM,
    _analisar_faixa_versiculos,
    _carregar_servicos_json,
    _faixa_versiculo_item,
    _formatar_duracao_segundos,
    _migrar_servicos_do_banco,
    _proximo_id_servico_livre,
    _salvar_servicos_json,
)
from navepro.core.slides import (
    _buscar_hino_por_termo,
    _buscar_hino_por_termo_ou_id,
    _buscar_midia_por_termo_ou_id,
)
from navepro.core.util_tk import _centralizar_sobre, _limitar_ao_monitor
from navepro.core.widgets_arredondados import TkArredondado
from navepro.core.youtube import _eh_url_youtube, _obter_info_youtube
from navepro.ui.apoio import (
    _colar_texto_campo,
    _escolher_arquivos_usuario,
    _menu_contexto_campo,
)

log = get_logger("janela_ordem_servico")

# Botões e campos desenham cantos arredondados (fachada do tkinter).
tk = TkArredondado(tk)


class JanelaOrdemServicoMixin:
    def janela_ordem_servico(self) -> None:
        """Abre a janela de planejamento de ordem de serviço.

        As ordens são salvas em ~/.navepro/servicos.json (nunca importam
        vídeo/slides). Oferece criar e editar serviços, excluir itens (botão
        da barra ou botão direito na lista) e arrastar e soltar os itens
        para reordená-los.
        """
        _migrar_servicos_do_banco()
        _sincronizar_uploads_midia()
        # O ponteiro de execução (_SERVICO_PROXIMO_ITEM) NÃO é limpo aqui:
        # ele persiste enquanto a janela principal estiver aberta, então ao
        # reabrir "Ordem de Serviço" a reprodução continua de onde parou.
        # Só volta do primeiro item quando o aplicativo é fechado/reaberto
        # (o dict é recriado vazio ao reiniciar o processo).
        dados = _carregar_servicos_json()
        janela = tk.Toplevel(self.root)
        janela.title("📋 Ordem de Serviço")
        _limitar_ao_monitor(janela, 1100, 750,
                            area=self._area_monitor_operador())
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        _centralizar_sobre(janela, self.root,
                           area=self._area_monitor_operador())

        # A janela pode ser redimensionada/maximizada: a lista fica com todo
        # o espaço extra e a barra de botões permanece sempre visível embaixo.
        try:
            janela.minsize(800, 540)
            janela.resizable(True, True)
        except tk.TclError:
            pass

        _estado_max = {"geo": "", "maximizada": False}

        def _esta_maximizada() -> bool:
            try:
                if bool(janela.attributes('-zoomed')):
                    return True
            except (tk.TclError, ValueError):
                pass
            try:
                return janela.state() == 'zoomed'
            except tk.TclError:
                return False

        def _definir_maximizada(maximizar: bool) -> None:
            if maximizar:
                try:
                    _estado_max["geo"] = janela.geometry()
                    largura_antes = janela.winfo_width()
                    altura_antes = janela.winfo_height()
                except tk.TclError:
                    _estado_max["geo"] = ""
                    largura_antes = altura_antes = 0
                try:
                    janela.attributes('-zoomed', True)
                except (tk.TclError, ValueError):
                    try:
                        janela.state('zoomed')
                    except tk.TclError:
                        area = self._area_monitor_operador()
                        if area:
                            x, y, w, h = area
                            try:
                                janela.geometry(f"{w}x{h}+{x}+{y}")
                            except tk.TclError:
                                pass

                def _conferir_maximizacao():
                    """Fallback p/ WMs que ignoram -zoomed silenciosamente."""
                    if not _estado_max.get("maximizada"):
                        return
                    try:
                        if (janela.winfo_width() > largura_antes + 20
                                or janela.winfo_height() > altura_antes + 20):
                            return
                    except tk.TclError:
                        return
                    area = self._area_monitor_operador()
                    if not area:
                        return
                    x, y, w, h = area
                    if w <= largura_antes and h <= altura_antes:
                        return
                    try:
                        janela.geometry(f"{w}x{h}+{x}+{y}")
                    except tk.TclError:
                        pass

                try:
                    janela.after(150, _conferir_maximizacao)
                except tk.TclError:
                    pass
            else:
                try:
                    janela.attributes('-zoomed', False)
                except (tk.TclError, ValueError):
                    try:
                        janela.state('normal')
                    except tk.TclError:
                        pass
                if _estado_max.get("geo"):
                    try:
                        janela.geometry(str(_estado_max["geo"]))
                    except tk.TclError:
                        pass
            _estado_max["maximizada"] = bool(maximizar)
            try:
                btn_max.configure(text="⛶ Restaurar" if maximizar
                                  else "⛶ Maximizar")
            except tk.TclError:
                pass

        def _alternar_maximizar() -> None:
            _definir_maximizada(not _esta_maximizada())

        main = tk.Frame(janela, bg='#0d1117')
        main.pack(fill='both', expand=True, padx=15, pady=15)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        tk.Label(main, text="📋 Ordem de Serviço",
                 font=("Arial", 16, "bold"), fg='#f0c040', bg='#0d1117'
                 ).grid(row=0, column=0, sticky='ew', pady=(0, 10))

        # ── Lista de serviços salvos ──
        serv_frame = tk.Frame(main, bg='#161b22')
        serv_frame.grid(row=1, column=0, sticky='ew', pady=5, ipady=5)

        tk.Label(serv_frame, text="Serviço:", fg='#f0c040', bg='#161b22',
                 font=("Arial", 11, "bold")).pack(side='left', padx=8)

        servico_var = tk.StringVar()
        combo_servico = ttk.Combobox(serv_frame, textvariable=servico_var,
                                      width=40, font=("Arial", 11), state='readonly')
        # Mantém a StringVar viva enquanto o combobox existir; sem esta
        # referência o garbage collector apaga a variável Tcl e o serviço
        # selecionado some da tela (a lista continua carregada).
        combo_servico._navepro_servico_var = servico_var
        combo_servico.pack(side='left', padx=5)
        btn_max = tk.Button(
            serv_frame, text="⛶ Maximizar", font=("Arial", 10, "bold"),
            bg='#21262d', fg='#f0c040', activebackground='#30363d',
            activeforeground='#f0c040', command=_alternar_maximizar,
            cursor='hand2', padx=10, pady=3)
        btn_max.pack(side='right', padx=8)

        servico_selecionado_id = [None]

        def _rotulo_servico(s: dict) -> str:
            return f"{s.get('id')} - {s.get('nome', '')}"

        def _servico_atual() -> dict | None:
            sid = servico_selecionado_id[0]
            if not sid:
                return None
            return next((s for s in dados["servicos"] if s.get("id") == sid), None)

        def _ordenar_servicos():
            return sorted(
                dados["servicos"],
                key=lambda s: s.get('id') or 0,
                reverse=True)

        def _carregar_servicos(escolher: bool = True):
            ord_servicos = _ordenar_servicos()
            opcoes = [_rotulo_servico(s) for s in ord_servicos]
            combo_servico['values'] = opcoes
            combo_servico._servico_ids = [s['id'] for s in ord_servicos]
            if opcoes and escolher:
                combo_servico.current(0)

        def _on_servico_select(event=None):
            sel = combo_servico.get()
            if not sel:
                return
            idx = combo_servico.current()
            ids = getattr(combo_servico, '_servico_ids', [])
            if idx >= 0 and idx < len(ids):
                servico_selecionado_id[0] = ids[idx]
                _carregar_itens()

        combo_servico.bind("<<ComboboxSelected>>", _on_servico_select)

        # ── Itens do serviço (Treeview) ──
        tree_frame = tk.Frame(main, bg='#161b22')
        tree_frame.grid(row=2, column=0, sticky='nsew', pady=5)

        colunas = ("#", "Tipo", "Título", "Duração")
        tree = ttk.Treeview(tree_frame, columns=colunas, show='headings', height=10,
                            style="OrdemServico.Treeview")
        tree.heading("#", text="#")
        tree.heading("Tipo", text="Tipo")
        tree.heading("Título", text="Título")
        tree.heading("Duração", text="Duração")
        tree.column("#", width=40, anchor='center', stretch=False)
        tree.column("Tipo", width=120, stretch=False)
        tree.column("Título", width=350, stretch=True)
        tree.column("Duração", width=130, anchor='center', stretch=False)

        scroll_y = tk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll_y.set)
        tree.pack(side='left', fill='both', expand=True)
        scroll_y.pack(side='right', fill='y')

        style = ttk.Style()
        style.configure("Treeview", background="#21262d", foreground="#c9d1d9",
                        fieldbackground="#21262d", font=("Arial", 10))
        style.configure("Treeview.Heading", background="#161b22", foreground="#f0c040",
                        font=("Arial", 10, "bold"))
        style.map('Treeview', background=[('selected', '#6e40c9')],
                  foreground=[('selected', '#ffffff')])
        # Espaçamento maior entre os itens (só nesta janela; as demais
        # Treeviews continuam com a altura padrão).
        style.configure("OrdemServico.Treeview", rowheight=32)

        # Escolha do operador na lista de itens: vale UMA única vez no
        # próximo clique em "Executar Serviço". Só é registrada por gestos
        # reais do operador na lista (clique do mouse), nunca pelo destaque
        # automático da reprodução nem por alterações internas da seleção
        # (reordenar, editar, recarregar a lista).
        _item_escolhido: dict[str, int | None] = {"id": None}

        def _registrar_escolha(row_iid: str | None):
            """Grava o item escolhido pelo operador na lista (uso único)."""
            if not row_iid:
                return
            try:
                _item_escolhido["id"] = int(row_iid)
            except (TypeError, ValueError):
                pass

        # ── Duração dos itens (ffprobe em segundo plano) ──
        _duracao_cache: dict[str, float | None] = {}
        _duracao_pendente: set[str] = set()
        _linhas_path: dict[str, str] = {}
        _textos_base: dict[str, str] = {}
        _contagem: dict[str, str | None] = {"iid": None}
        _timers: dict[str, str | None] = {"contagem": None}

        def _extensao_midia(caminho: str | None) -> bool:
            ext = os.path.splitext(caminho or "")[1].lower()
            return ext in EXTENSOES_VIDEO or ext in EXTENSOES_AUDIO

        def _caminho_item(it: dict) -> str | None:
            """Resolve o arquivo/URL de mídia de um item da Ordem de Serviço."""
            tipo = (it.get("tipo") or "").strip().lower()
            if tipo == "youtube":
                url = (it.get("youtube_url") or "").strip()
                return url or None
            caminho = (it.get("caminho_arquivo") or "").strip()
            if caminho and os.path.isfile(caminho):
                if _extensao_midia(caminho) or tipo in ("video", "audio", "sermao"):
                    return caminho
            ref = it.get("referencia_id")
            if tipo in ("video", "audio") and ref is not None:
                try:
                    rows = db_query(
                        "SELECT caminho_arquivo FROM midia "
                        "WHERE id = ? AND ativo = 1", (ref,))
                except Exception:
                    rows = None
                if rows:
                    caminho = (rows[0].get("caminho_arquivo") or "").strip()
                    if caminho:
                        return caminho
            if tipo == "anuncio" and ref is not None:
                try:
                    anuncio = _buscar_anuncio_por_ref(ref) or {}
                except Exception:
                    anuncio = {}
                caminho = (anuncio.get("arquivo_midia") or "").strip()
                if caminho and _extensao_midia(caminho):
                    return caminho
            return caminho or None

        def _texto_titulo_item(it: dict, indice: int) -> str:
            """Título da lista; no YouTube a URL aparece na linha de baixo."""
            titulo = (it.get("titulo_custom") or "").strip() or f"Item {indice}"
            if (it.get("tipo") or "").strip().lower() != "youtube":
                return titulo
            url = (it.get("youtube_url") or "").strip()
            if url and url != titulo:
                return f"{titulo}\n{url}"
            return url or titulo

        def _texto_duracao_item(it: dict, caminho: str | None = None) -> str:
            if caminho is None:
                caminho = _caminho_item(it)
            if caminho and caminho in _duracao_cache:
                duracao = _duracao_cache[caminho]
                if duracao:
                    return _formatar_duracao_segundos(duracao)
            estimado = it.get("duracao_estimada_segundos") or 0
            try:
                estimado = float(estimado)
            except (TypeError, ValueError):
                estimado = 0.0
            if estimado > 0:
                return _formatar_duracao_segundos(estimado)
            return "—"

        def _persistir_duracao(caminho: str, duracao) -> None:
            """Guarda a duração real no item para não depender do ffprobe sempre."""
            if not caminho or not duracao:
                return
            serv = _servico_atual()
            if not serv:
                return
            try:
                valor = int(round(float(duracao)))
            except (TypeError, ValueError):
                return
            alterou = False
            for it in serv.get("itens") or []:
                if _linhas_path.get(str(it.get("id"))) != caminho:
                    continue
                if it.get("duracao_estimada_segundos") != valor:
                    it["duracao_estimada_segundos"] = valor
                    alterou = True
            if alterou and not _salvar_servicos_json(dados):
                log.debug("Não foi possível guardar a duração em servicos.json.")

        def _pedir_duracao(caminho: str) -> None:
            """Consulta a duração real sem travar a interface.

            Arquivos locais usam o ffprobe do player; URLs do YouTube usam
            os metadados do yt-dlp (sem baixar o vídeo).
            """
            if not caminho or caminho in _duracao_cache or caminho in _duracao_pendente:
                return
            player = getattr(self, "player", None)
            eh_youtube = _eh_url_youtube(caminho)
            if not eh_youtube and not os.path.isfile(caminho):
                return
            if not eh_youtube and player is None:
                return
            _duracao_pendente.add(caminho)

            def _trabalho():
                if eh_youtube:
                    info = _obter_info_youtube(caminho)
                    duracao = (info or {}).get("duracao") or None
                else:
                    duracao = player._obter_duracao_arquivo(caminho)

                def _aplicar():
                    _duracao_pendente.discard(caminho)
                    _duracao_cache[caminho] = duracao
                    if not duracao or not janela.winfo_exists():
                        return
                    _persistir_duracao(caminho, duracao)
                    texto = _formatar_duracao_segundos(duracao)
                    for iid, path in list(_linhas_path.items()):
                        if path != caminho:
                            continue
                        _textos_base[iid] = texto
                        if _contagem["iid"] == iid:
                            continue
                        try:
                            if tree.exists(iid):
                                tree.set(iid, "Duração", texto)
                        except tk.TclError:
                            pass

                try:
                    self.root.after(0, _aplicar)
                except (tk.TclError, RuntimeError):
                    pass

            threading.Thread(target=_trabalho, daemon=True,
                             name="navepro-duracao-item").start()

        # ── Indicador animado de inserção (drag & drop) ──
        _cor_ind = "#58a6ff"
        _cor_ind_brilho = "#79c0ff"
        _cor_ind_fundo = "#1f6feb"
        _ind: dict[str, object] = {
            "glow": None, "line": None, "dot": None, "dot_oval": None,
            "anim": None, "visivel": False, "fase": False}

        def _pulsar_indicador():
            _ind["anim"] = None
            line = _ind.get("line")
            if line is None or not _ind.get("visivel"):
                return
            fase = not bool(_ind.get("fase"))
            _ind["fase"] = fase
            try:
                line.configure(bg=_cor_ind_brilho if fase else _cor_ind)
                dot = _ind.get("dot")
                oval = _ind.get("dot_oval")
                if dot is not None and oval is not None:
                    if fase:
                        dot.coords(oval, 4, 4, 14, 14)
                        dot.itemconfigure(oval, fill=_cor_ind_brilho)
                    else:
                        dot.coords(oval, 6, 6, 12, 12)
                        dot.itemconfigure(oval, fill=_cor_ind_fundo)
                _ind["anim"] = janela.after(280, _pulsar_indicador)
            except tk.TclError:
                return

        def _mostrar_indicador(y: int) -> None:
            if _ind.get("line") is None:
                try:
                    _ind["glow"] = tk.Frame(tree, bg=_cor_ind_fundo, height=9)
                    _ind["line"] = tk.Frame(tree, bg=_cor_ind, height=3)
                    dot = tk.Canvas(tree, width=18, height=18,
                                    highlightthickness=0, bd=0)
                    _ind["dot"] = dot
                    _ind["dot_oval"] = dot.create_oval(
                        6, 6, 12, 12, outline=_cor_ind,
                        fill=_cor_ind_fundo, width=2)
                except tk.TclError:
                    return
            _ind["visivel"] = True
            y = max(0, int(y))
            try:
                fundo = ttk.Style().lookup("Treeview", "background") or "#21262d"
                _ind["dot"].configure(bg=fundo)
                _ind["glow"].place(x=0, y=max(0, y - 3), relwidth=1, height=9)
                _ind["line"].place(x=0, y=y, relwidth=1, height=3)
                _ind["dot"].place(x=2, y=max(0, y - 8), width=18, height=18)
                _ind["glow"].lift()
                _ind["line"].lift()
                _ind["dot"].lift()
            except tk.TclError:
                return
            if _ind.get("anim") is None:
                _pulsar_indicador()

        def _esconder_indicador() -> None:
            _ind["visivel"] = False
            anim = _ind.get("anim")
            if anim is not None:
                try:
                    janela.after_cancel(anim)
                except tk.TclError:
                    pass
                _ind["anim"] = None
            for chave in ("glow", "line", "dot"):
                widget = _ind.get(chave)
                if widget is not None:
                    try:
                        widget.place_forget()
                    except tk.TclError:
                        pass

        # ── Drag & drop para reordenar itens dentro da tree ──
        _drag_state: dict[str, object] = {
            "origem": None, "press_y": None, "dragging": False, "pos": None}

        def _calcular_posicao(y: int):
            """Devolve (posição de inserção, y da linha, iid alvo) ou None."""
            linhas = list(tree.get_children())
            if not linhas:
                return None
            alvo = tree.identify_row(y)
            if alvo:
                bbox = tree.bbox(alvo)
                if not bbox:
                    return None
                _x, topo, _w, altura = bbox
                indice = linhas.index(alvo)
                if y < topo + altura / 2:
                    return indice, topo, alvo
                return indice + 1, topo + altura - 1, alvo
            bbox_primeiro = tree.bbox(linhas[0])
            bbox_ultimo = tree.bbox(linhas[-1])
            if not bbox_primeiro or not bbox_ultimo:
                return None
            if y < bbox_primeiro[1]:
                return 0, bbox_primeiro[1], None
            if y > bbox_ultimo[1] + bbox_ultimo[3]:
                return len(linhas), bbox_ultimo[1] + bbox_ultimo[3] - 1, None
            return None

        def _on_tree_button_press(event):
            if tree.identify_region(event.x, event.y) in ("heading", "separator"):
                return
            item = tree.identify_row(event.y)
            if not item:
                return
            _registrar_escolha(item)
            _drag_state.update(origem=item, press_y=event.y,
                               dragging=False, pos=None)

        def _on_tree_motion(event):
            origem = _drag_state.get("origem")
            if not origem:
                return
            press_y = _drag_state.get("press_y")
            if press_y is not None and not _drag_state.get("dragging"):
                if abs(event.y - press_y) < 5:
                    return
                _drag_state["dragging"] = True
                try:
                    tree.configure(cursor="fleur")
                except tk.TclError:
                    pass
            if tree.identify_region(event.x, event.y) == "heading":
                _drag_state["pos"] = None
                _esconder_indicador()
                return
            alvo = _calcular_posicao(event.y)
            if alvo is None:
                _drag_state["pos"] = None
                _esconder_indicador()
                return
            pos, linha_y, _alvo = alvo
            _drag_state["pos"] = pos
            _mostrar_indicador(linha_y)
            try:
                if event.y < 28:
                    tree.yview_scroll(-1, "units")
                elif event.y > tree.winfo_height() - 28:
                    tree.yview_scroll(1, "units")
            except tk.TclError:
                pass

        def _reordenar_com_posicao(serv: dict, origem: str, pos: int | None):
            if pos is None:
                return None
            itens = list(serv.get("itens") or [])
            idx_orig = next((i for i, it in enumerate(itens)
                             if str(it.get("id")) == origem), None)
            if idx_orig is None:
                return None
            if pos > idx_orig:
                pos -= 1
            pos = max(0, min(pos, len(itens) - 1))
            if pos == idx_orig:
                return None
            novo = list(itens)
            item = novo.pop(idx_orig)
            novo.insert(pos, item)
            return novo

        def _on_tree_button_release(event):
            origem = _drag_state.get("origem")
            pos = _drag_state.get("pos")
            arrastou = bool(_drag_state.get("dragging"))
            _drag_state.update(origem=None, press_y=None,
                               dragging=False, pos=None)
            _esconder_indicador()
            try:
                tree.configure(cursor="")
            except tk.TclError:
                pass
            if not origem or not arrastou:
                return
            serv = _servico_atual()
            if not serv:
                return
            novo = _reordenar_com_posicao(serv, str(origem), pos)
            if novo is None:
                return
            itens_antigos = serv.get("itens")
            serv["itens"] = novo
            if not _salvar_servicos_json(dados):
                serv["itens"] = itens_antigos
                log.warning("Não foi possível salvar a reordenação por arrastar.")
                return
            _carregar_itens()
            if tree.exists(str(origem)):
                tree.selection_set(str(origem))
                tree.focus(str(origem))
                tree.see(str(origem))

        tree.bind("<ButtonPress-1>", _on_tree_button_press)
        tree.bind("<B1-Motion>", _on_tree_motion)
        tree.bind("<ButtonRelease-1>", _on_tree_button_release)

        def _on_tree_leave(_event=None):
            _drag_state["pos"] = None
            _esconder_indicador()

        tree.bind("<Leave>", _on_tree_leave)
        janela.bind("<Escape>", _on_tree_leave, add="+")

        def _on_tree_double_click(event):
            if tree.identify_region(event.x, event.y) == "heading":
                return
            if not tree.identify_row(event.y):
                return
            _editar_item_selecionado()

        tree.bind("<Double-1>", _on_tree_double_click)

        # ── Menu de contexto (clique direito): apagar item ──
        _menu_ctx_aberto = {"menu": None}

        def _fechar_menu_contexto(event=None):
            """Fecha o menu de contexto caso esteja aberto (clique fora dele)."""
            m = _menu_ctx_aberto["menu"]
            if m is not None:
                _menu_ctx_aberto["menu"] = None
                try:
                    m.unpost()
                except tk.TclError:
                    pass

        def _apagar_item_contexto():
            _fechar_menu_contexto()
            sel = tree.selection()
            if not sel:
                return
            serv = _servico_atual()
            if not serv:
                return
            item_id = int(sel[0])
            it = next((x for x in (serv.get("itens") or [])
                       if x.get("id") == item_id), None)
            if it is None:
                return
            titulo = (it.get("titulo_custom") or "").strip() or f"Item {item_id}"
            if not tkinter.messagebox.askyesno(
                    "Confirmar", f"Remover o item \"{titulo}\"?", parent=janela):
                return
            serv["itens"] = [x for x in serv.get("itens", [])
                             if x.get("id") != item_id]
            if not _salvar_servicos_json(dados):
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar a remoção em servicos.json.",
                    parent=janela)
                return
            _carregar_itens()

        def _menu_contexto_item(event):
            _fechar_menu_contexto()
            if tree.identify_region(event.x, event.y) in ("heading", "separator"):
                return "break"
            item_id = tree.identify_row(event.y)
            if not item_id:
                return "break"
            _registrar_escolha(item_id)
            tree.selection_set(item_id)
            tree.focus(item_id)
            menu_ctx = tk.Menu(janela, tearoff=0, bg='#21262d', fg='#c9d1d9',
                               activebackground='#6e40c9',
                               activeforeground='#ffffff', font=("Arial", 10))
            menu_ctx.add_command(label="🗑️ Apagar Item",
                                 command=_apagar_item_contexto)
            _menu_ctx_aberto["menu"] = menu_ctx
            menu_ctx.tk_popup(event.x_root, event.y_root, 0)
            return "break"

        tree.bind("<Button-3>", _menu_contexto_item)

        # Clicar em qualquer outro lugar da janela (ou rolar/teclar Esc) fecha
        # o menu de contexto se ele estiver aberto. O bind na janela propaga
        # para os widgets internos, cobrindo toda a área da janela.
        for _evento in ("<ButtonPress-1>", "<ButtonPress-2>",
                        "<ButtonPress-3>", "<MouseWheel>"):
            janela.bind(_evento, _fechar_menu_contexto)
        janela.bind("<Escape>", _fechar_menu_contexto)

        def _carregar_itens():
            for item in tree.get_children():
                tree.delete(item)
            _linhas_path.clear()
            _textos_base.clear()
            _contagem["iid"] = None
            _esconder_indicador()
            serv = _servico_atual()
            if not serv:
                return
            itens = list(serv.get("itens") or [])
            # A URL do YouTube ocupa a segunda linha do título. Só nesse
            # caso as linhas ficam mais altas; serviços sem YouTube mantêm
            # o espaçamento compacto.
            tem_youtube = any((it.get("tipo") or "").strip().lower() == "youtube"
                              for it in itens)
            try:
                style.configure("OrdemServico.Treeview",
                                rowheight=48 if tem_youtube else 32)
            except tk.TclError:
                pass
            for i, it in enumerate(itens):
                tipo = it.get("tipo") or "slide"
                tipo_emoji = {"hino": "📖", "versiculo": "✝️", "video": "🎬",
                              "audio": "🎵", "slide": "📄", "anuncio": "📢",
                              "sermao": "🎤", "youtube": "▶️"}.get(tipo, "📁")
                iid = str(it.get("id"))
                caminho = _caminho_item(it)
                texto = _texto_duracao_item(it, caminho)
                tree.insert("", tk.END, iid=iid,
                            values=(i + 1, f"{tipo_emoji} {tipo.title()}",
                                    _texto_titulo_item(it, i + 1),
                                    texto))
                _textos_base[iid] = texto
                if caminho:
                    _linhas_path[iid] = caminho
                    if _eh_url_youtube(caminho):
                        # Só consulta a rede se o item antigo ainda não tem a
                        # duração capturada do YouTube.
                        if not (it.get("duracao_estimada_segundos") or 0):
                            _pedir_duracao(caminho)
                    elif _extensao_midia(caminho) and os.path.isfile(caminho):
                        _pedir_duracao(caminho)

        def _item_em_reproducao():
            """Item da lista que está tocando agora (ou None)."""
            serv = _servico_atual()
            if not serv:
                return None
            itens = list(serv.get("itens") or [])
            chave = serv.get("id") or serv.get("nome") or "?"
            prox = _SERVICO_PROXIMO_ITEM.get(chave)
            if prox is None or prox <= 0 or prox > len(itens):
                return None
            item = itens[prox - 1]
            iid = str(item.get("id"))
            caminho = _linhas_path.get(iid) or _caminho_item(item)
            player = getattr(self, "player", None)
            if not caminho or player is None:
                return None
            if list(getattr(player, "playlist", None) or []) != [caminho]:
                return None
            return item, iid, caminho

        def _restaurar_duracao(iid: str | None) -> None:
            if not iid:
                return
            texto = _textos_base.get(iid)
            if texto is None:
                return
            try:
                if tree.exists(iid):
                    tree.set(iid, "Duração", texto)
            except tk.TclError:
                pass

        def _atualizar_contagem() -> None:
            player = getattr(self, "player", None)
            alvo = _item_em_reproducao() if player is not None else None
            if alvo is None:
                _restaurar_duracao(_contagem["iid"])
                _contagem["iid"] = None
                return
            _item, iid, caminho = alvo
            if not tree.exists(iid):
                _contagem["iid"] = None
                return
            duracao = getattr(player, "duracao_total", None)
            if not duracao:
                duracao = _duracao_cache.get(caminho)
            tocando = bool(getattr(player, "is_playing", False))
            pausado = bool(getattr(player, "is_paused", False))
            if not duracao or not tocando:
                _restaurar_duracao(_contagem["iid"])
                _contagem["iid"] = None
                return
            # Guarda a duração real conhecida para as próximas aberturas.
            if caminho not in _duracao_cache:
                _duracao_cache[caminho] = float(duracao)
                _persistir_duracao(caminho, duracao)
                texto = _formatar_duracao_segundos(duracao)
                for outro_iid, path in list(_linhas_path.items()):
                    if path == caminho:
                        _textos_base[outro_iid] = texto
                        if outro_iid != iid:
                            try:
                                if tree.exists(outro_iid):
                                    tree.set(outro_iid, "Duração", texto)
                            except tk.TclError:
                                pass
            if _contagem["iid"] and _contagem["iid"] != iid:
                _restaurar_duracao(_contagem["iid"])
            restante = float(duracao)
            try:
                restante -= float(player.obter_tempo_decorrido())
            except (TypeError, ValueError):
                pass
            restante = max(0.0, restante)
            icone = "⏸" if pausado else "⏳"
            try:
                tree.set(iid, "Duração",
                         f"{icone} {_formatar_duracao_segundos(restante)}")
            except tk.TclError:
                return
            _contagem["iid"] = iid

        def _tick_contagem():
            _timers["contagem"] = None
            if not janela.winfo_exists():
                return
            try:
                _atualizar_contagem()
            except Exception as exc:
                log.debug("Falha ao atualizar a contagem da Ordem de Serviço: %s", exc)
            try:
                _timers["contagem"] = janela.after(500, _tick_contagem)
            except tk.TclError:
                pass

        def _ao_destruir_janela(event):
            if event.widget is not janela:
                return
            for chave in ("contagem",):
                timer = _timers.get(chave)
                if timer is not None:
                    try:
                        janela.after_cancel(timer)
                    except tk.TclError:
                        pass
                    _timers[chave] = None
            _esconder_indicador()

        janela.bind("<Destroy>", _ao_destruir_janela, add="+")
        _tick_contagem()

        # ── Botões ──
        btn_frame = tk.Frame(main, bg='#0d1117')
        btn_frame.grid(row=3, column=0, sticky='ew', pady=5)

        def _novo_servico():
            nome = tkinter.simpledialog.askstring("Novo Serviço",
                "Nome do serviço:", parent=janela) if hasattr(tkinter, 'simpledialog') else None
            if not nome:
                # Fallback se simpledialog não estiver disponível
                nome_win = tk.Toplevel(janela)
                nome_win.title("Novo Serviço")
                nome_win.geometry("350x120")
                nome_win.configure(bg='#0d1117')
                nome_win.transient(janela)
                _centralizar_sobre(nome_win, janela)
                nome_win.after(50, nome_win.grab_set)
                tk.Label(nome_win, text="Nome do serviço:", fg='#f0c040', bg='#0d1117',
                         font=("Arial", 11)).pack(pady=5)
                nome_entry = tk.Entry(nome_win, font=("Arial", 12), bg='#21262d',
                                      fg='#f0c040', insertbackground='#f0c040')
                nome_entry.pack(padx=15, fill='x', ipady=3)
                nome_entry.focus_set()
                resultado = [None]
                def _ok():
                    resultado[0] = nome_entry.get().strip()
                    nome_win.destroy()
                tk.Button(nome_win, text="OK", font=("Arial", 11, "bold"),
                          bg='#238636', fg='white', command=_ok).pack(pady=5)
                nome_win.wait_window()
                nome = resultado[0]
            if not nome:
                return
            novo_id = _proximo_id_servico_livre(dados)
            dados["servicos"].append({
                "id": novo_id,
                "nome": nome,
                "criado_em": datetime.now().isoformat(timespec="seconds"),
                "itens": [],
            })
            dados["_proximo_id_servico"] = max(
                dados.get("_proximo_id_servico", 1), novo_id + 1)
            if not _salvar_servicos_json(dados):
                dados["servicos"] = [s for s in dados["servicos"]
                                     if s.get("id") != novo_id]
                dados["_proximo_id_servico"] = novo_id
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar em servicos.json.", parent=janela)
                return
            _carregar_servicos()
            _on_servico_select()

        def _editar_servico():
            serv = _servico_atual()
            if not serv:
                tkinter.messagebox.showwarning("Seleção", "Selecione um serviço.", parent=janela)
                return
            nome = (tkinter.simpledialog.askstring(
                "Editar Serviço", "Nome do serviço:",
                initialvalue=serv.get("nome", ""), parent=janela)
                if hasattr(tkinter, 'simpledialog') else None)
            if not nome:
                return
            nome = nome.strip()
            if not nome:
                return
            serv["nome"] = nome
            if not _salvar_servicos_json(dados):
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar em servicos.json.", parent=janela)
                return
            _carregar_servicos()
            _on_servico_select()

        def _abrir_editor_item(item_edit: dict | None = None):
            """Abre a janela para adicionar (item_edit=None) ou editar um item."""
            sid = servico_selecionado_id[0]
            if not sid:
                tkinter.messagebox.showwarning("Seleção", "Selecione ou crie um serviço.", parent=janela)
                return
            add_win = tk.Toplevel(janela)
            add_win.title("Editar Item" if item_edit else "Adicionar Item")
            add_win.geometry("700x380")
            add_win.configure(bg='#0d1117')
            add_win.transient(janela)
            _centralizar_sobre(add_win, janela)
            add_win.after(50, add_win.grab_set)

            add_main = tk.Frame(add_win, bg='#0d1117')
            add_main.pack(fill='both', expand=True, padx=15, pady=15)

            tk.Label(add_main, text="Tipo:", fg='#f0c040', bg='#0d1117',
                     font=("Arial", 11, "bold")).pack(anchor='w')
            tipo_var = tk.StringVar(value=(item_edit or {}).get("tipo") or "hino")
            tipos = ["hino", "versiculo", "video", "audio", "slide",
                     "anuncio", "sermao"]
            tipo_frame = tk.Frame(add_main, bg='#0d1117')
            tipo_frame.pack(fill='x', pady=2)
            for t in tipos:
                tk.Radiobutton(tipo_frame, text=t.title(), variable=tipo_var, value=t,
                               bg='#0d1117', fg='#c9d1d9', selectcolor='#21262d',
                               font=("Arial", 10)).pack(side='left', padx=3)

            tk.Label(add_main, text="Título:", fg='#f0c040', bg='#0d1117',
                     font=("Arial", 11, "bold")).pack(anchor='w', pady=(8, 0))
            titulo_var = tk.StringVar(
                value=(item_edit or {}).get("titulo_custom") or "")
            titulo_entry = tk.Entry(add_main, textvariable=titulo_var,
                                    font=("Arial", 11), bg='#21262d',
                                    fg='#f0c040', insertbackground='#f0c040',
                                    readonlybackground='#161b22')
            # Sem referência viva o GC apaga a variável Tcl e o campo fica vazio.
            titulo_entry._navepro_titulo_var = titulo_var
            titulo_entry.pack(fill='x', ipady=3, pady=2)
            # Quando o item é um vídeo do YouTube, a URL é exibida aqui,
            # logo abaixo do título capturado automaticamente.
            youtube_titulo_url_lbl = tk.Label(
                add_main, text="", fg='#58a6ff', bg='#0d1117',
                font=("Arial", 9), anchor='w', justify='left', wraplength=660)

            tk.Label(add_main, text="Buscar (nº ou nome do hino/mídia/anúncio):", fg='#8b949e',
                     bg='#0d1117', font=("Arial", 9)).pack(anchor='w')
            ref_entry = tk.Entry(add_main, font=("Arial", 11), bg='#21262d',
                                 fg='#c9d1d9', insertbackground='#f0c040')
            if item_edit:
                _tf = (item_edit.get("tipo") or "").lower()
                _tc = (item_edit.get("titulo_custom") or "").strip()
                if _tf in ("hino", "audio", "video", "anuncio") and _tc and not _tc.startswith("Item "):
                    ref_entry.insert(0, _tc)
                else:
                    ref_entry.insert(0, str(item_edit.get("referencia_id") or ""))
            ref_entry.pack(fill='x', ipady=3, pady=2)

            # ── Seletor de referência bíblica (tipo "versiculo") ──
            biblia_versao_var = tk.StringVar()
            biblia_livro_var = tk.StringVar()
            biblia_cap_var = tk.StringVar()
            biblia_vers_var = tk.StringVar()

            biblia_frame = tk.Frame(add_main, bg='#0d1117')
            tk.Label(biblia_frame, text="Referência bíblica:",
                     fg='#f0c040', bg='#0d1117',
                     font=("Arial", 11, "bold")).pack(anchor='w', pady=(6, 0))

            _linha_vers_livro = tk.Frame(biblia_frame, bg='#0d1117')
            _linha_vers_livro.pack(fill='x', pady=2)
            tk.Label(_linha_vers_livro, text="Versão:", fg='#c9d1d9',
                     bg='#0d1117', font=("Arial", 10)).pack(side='left')
            _versoes_sel = []
            _rows_v = db_query(
                "SELECT DISTINCT versao FROM versiculos ORDER BY versao")
            if _rows_v:
                _versoes_sel = [r["versao"] for r in _rows_v]
            if not _versoes_sel:
                _versoes_sel = ["Almeida Revista e Corrigida", "Almeida Século 21"]
            combo_bversao = ttk.Combobox(_linha_vers_livro,
                                         textvariable=biblia_versao_var,
                                         values=_versoes_sel, width=22,
                                         font=("Arial", 10))
            combo_bversao.pack(side='left', padx=(4, 10))
            tk.Label(_linha_vers_livro, text="Livro:", fg='#c9d1d9',
                     bg='#0d1117', font=("Arial", 10)).pack(side='left')
            combo_blivro = ttk.Combobox(_linha_vers_livro,
                                        textvariable=biblia_livro_var,
                                        values=self.LIVROS_BIBLIA, width=16,
                                        font=("Arial", 10))
            combo_blivro.pack(side='left', padx=(4, 0))

            _linha_cap_vers = tk.Frame(biblia_frame, bg='#0d1117')
            _linha_cap_vers.pack(fill='x', pady=2)
            tk.Label(_linha_cap_vers, text="Capítulo:", fg='#c9d1d9',
                     bg='#0d1117', font=("Arial", 10)).pack(side='left')
            entry_bcap = tk.Entry(_linha_cap_vers, textvariable=biblia_cap_var,
                                  width=4, font=("Arial", 10), bg='#21262d',
                                  fg='#f0c040', insertbackground='#f0c040',
                                  bd=0, highlightthickness=0)
            entry_bcap.pack(side='left', padx=(4, 10), ipady=2)
            tk.Label(_linha_cap_vers, text="Versículo"
                     " (ex.: 5, 1-7 ou vazio = capítulo inteiro):",
                     fg='#c9d1d9', bg='#0d1117',
                     font=("Arial", 10)).pack(side='left')
            entry_bvers = tk.Entry(_linha_cap_vers, textvariable=biblia_vers_var,
                                   width=10, font=("Arial", 10), bg='#21262d',
                                   fg='#f0c040', insertbackground='#f0c040',
                                   bd=0, highlightthickness=0)
            entry_bvers.pack(side='left', padx=(4, 8), ipady=2)
            tk.Button(_linha_cap_vers, text="🔍 Ver texto",
                      font=("Arial", 10, "bold"), bg='#21262d', fg='#f0c040',
                      activebackground='#30363d', cursor='hand2',
                      command=lambda: _preview_biblia()
                      ).pack(side='left')

            preview_text = tk.Text(biblia_frame, height=4, wrap='word',
                                   font=("Arial", 9), bg='#161b22', fg='#c9d1d9',
                                   relief='flat', exportselection=False)
            preview_text.pack(fill='x', pady=4)
            preview_text.config(state='disabled')

            def _copiar_previa(widget: tk.Text) -> None:
                try:
                    conteudo = widget.get('1.0', tk.END).strip()
                except tk.TclError:
                    conteudo = ""
                if not conteudo:
                    tkinter.messagebox.showinfo(
                        "Copiar", "Não há conteúdo para copiar.", parent=add_win)
                    return
                add_win.clipboard_clear()
                add_win.clipboard_append(conteudo)

            btn_copia_biblia = tk.Button(
                biblia_frame, text="📋 Copiar", font=("Arial", 9, "bold"),
                bg='#21262d', fg='#f0c040', activebackground='#30363d',
                cursor='hand2', padx=10, pady=1,
                command=lambda: _copiar_previa(preview_text))
            btn_copia_biblia.pack(anchor='e', pady=(0, 2))

            biblia_frame.pack_forget()

            # ── Painel de hino (tipo "hino") ──
            # O operador digita diretamente o Nº do hino (ex.: '46'); o botão
            # "🔍 Ver letra" resolve o número → título/letra da tabela letras e
            # mostra o preview. Salva referencia_id (id da letra) + snapshot.
            hino_num_var = tk.StringVar()
            hino_frame = tk.Frame(add_main, bg='#0d1117')
            tk.Label(hino_frame, text="Buscar hino por número:",
                     fg='#f0c040', bg='#0d1117',
                     font=("Arial", 11, "bold")).pack(anchor='w', pady=(6, 0))

            _linha_hino_num = tk.Frame(hino_frame, bg='#0d1117')
            _linha_hino_num.pack(fill='x', pady=2)
            tk.Label(_linha_hino_num, text="Nº do hino:", fg='#c9d1d9',
                     bg='#0d1117', font=("Arial", 10)).pack(side='left')
            entry_hino_num = tk.Entry(_linha_hino_num, textvariable=hino_num_var,
                                      width=8, font=("Arial", 11), bg='#21262d',
                                      fg='#f0c040', insertbackground='#f0c040',
                                      bd=0, highlightthickness=0)
            entry_hino_num.pack(side='left', padx=(4, 8), ipady=2)
            tk.Label(_linha_hino_num, text="(ou título/artista)",
                     fg='#8b949e', bg='#0d1117',
                     font=("Arial", 9)).pack(side='left')
            tk.Button(_linha_hino_num, text="🔍 Ver letra",
                      font=("Arial", 10, "bold"), bg='#21262d', fg='#f0c040',
                      activebackground='#30363d', cursor='hand2',
                      command=lambda: _ver_letra_hino()
                      ).pack(side='right')

            preview_hino = tk.Text(hino_frame, height=7, wrap='word',
                                   font=("Arial", 9), bg='#161b22', fg='#c9d1d9',
                                   relief='flat', state='disabled',
                                   exportselection=False)
            preview_hino.pack(fill='x', pady=4)

            btn_copia_hino = tk.Button(
                hino_frame, text="📋 Copiar", font=("Arial", 9, "bold"),
                bg='#21262d', fg='#f0c040', activebackground='#30363d',
                cursor='hand2', padx=10, pady=1,
                command=lambda: _copiar_previa(preview_hino))
            btn_copia_hino.pack(anchor='e', pady=(0, 2))

            def _ver_letra_hino():
                """Resolve o nº/termo digitado → letra do hino e mostra preview."""
                res = _resolver_hino()
                if not res[0]:
                    tkinter.messagebox.showwarning("Hino", res[1], parent=add_win)
                    return
                _, _, letra_snap, ref_display, _rid = res
                preview_hino.config(state='normal')
                preview_hino.delete('1.0', tk.END)
                preview_hino.insert(tk.END, letra_snap)
                preview_hino.config(state='disabled')

            def _resolver_hino():
                """Resolve hino por nº/termo.

                Retorna (ok, msg_erro, letra_snapshot, ref_display, ref_id).
                Aceita número ('46' → hino cujo título começa com '46') ou
                trecho de título/artista/letra.
                """
                termo = hino_num_var.get().strip()
                if not termo:
                    return (False, "Informe o número do hino (ou título/artista).",
                            "", "", None)
                rows_match = _buscar_hino_por_termo(termo)
                if not rows_match:
                    return (False, f"Nenhum hino encontrado para: \"{termo}\".",
                            "", "", None)
                ref_hino = rows_match[0]
                rid = ref_hino.get("id")
                letra_snap = ref_hino.get("letra_completa", "")
                ref_disp = ref_hino.get("titulo", "") or "Item (Hino)"
                return (True, "", letra_snap, ref_disp, rid)

            # Preenche o painel ao editar um hino existente
            if item_edit and (item_edit.get("tipo") or "").lower() == "hino":
                _hid_ed = item_edit.get("referencia_id")
                if _hid_ed:
                    _rh_ed = db_query("SELECT * FROM letras WHERE id = ? AND ativo = 1",
                                      (_hid_ed,))
                    if _rh_ed:
                        _hh = _rh_ed[0]
                        letra_snap = _hh.get("letra_completa", "") or ""
                if letra_snap:
                    preview_hino.config(state='normal')
                    preview_hino.delete('1.0', tk.END)
                    preview_hino.insert(tk.END, letra_snap)
                    preview_hino.config(state='disabled')

            hino_frame.pack_forget()

            # Preenche o painel ao editar um versículo existente
            if item_edit and (item_edit.get("tipo") or "").lower() == "versiculo":
                _rid_ed = item_edit.get("referencia_id")
                if _rid_ed:
                    _rv_ed = db_query("SELECT * FROM versiculos WHERE id = ?",
                                      (_rid_ed,))
                    if _rv_ed:
                        biblia_versao_var.set(_rv_ed[0]["versao"])
                        biblia_livro_var.set(_rv_ed[0]["livro"])
                        biblia_cap_var.set(str(_rv_ed[0]["capitulo"]))
                        # Item com faixa salva (ex.: "1-7") mostra a faixa
                        # inteira no campo; os demais mostram o versículo só.
                        biblia_vers_var.set(_faixa_versiculo_item(item_edit)
                                            or str(_rv_ed[0]["versiculo"]))

            def _resolver_referencia_biblia():
                """Resolve a referência do painel bíblico.

                O campo "Versículo" aceita um número ("5"), uma faixa
                ("1-7") ou vazio (capítulo inteiro).

                Retorna (ok, msg_erro, letra_snap, ref_display, ref_id,
                versiculos). `versiculos` é a lista de [numero, texto] da
                faixa, que faz o item ser projetado um versículo por slide;
                fica vazia no versículo único e no capítulo inteiro, que
                continuam projetando em um slide só (como antes).
                """
                versao = biblia_versao_var.get().strip()
                livro = biblia_livro_var.get().strip()
                cap = biblia_cap_var.get().strip()
                vers = biblia_vers_var.get().strip()
                if not (versao and livro and cap.isdigit()):
                    return (False,
                            "Selecione a versão, o livro e informe o capítulo.",
                            "", "", None, [])
                cap = int(cap)
                ok_faixa, msg_faixa, v_ini, v_fim = _analisar_faixa_versiculos(vers)
                if not ok_faixa:
                    return (False, msg_faixa, "", "", None, [])
                if v_ini is None:
                    v_ini, v_fim = 1, 9999
                rows = db_query(
                    "SELECT * FROM versiculos WHERE versao = ? AND livro = ? "
                    "AND capitulo = ? AND versiculo >= ? AND versiculo <= ? "
                    "ORDER BY versiculo",
                    (versao, livro, cap, v_ini, v_fim))
                if not rows:
                    return (False,
                            "Nenhum versículo encontrado para "
                            f"{livro} {cap}:{vers or '*'} ({versao}).",
                            "", "", None, [])
                # Um versículo só (ou faixa de um número): comportamento antigo.
                if v_ini == v_fim:
                    r = rows[0]
                    return (True, "",
                            f"{livro} {cap}:{vers}\n\n{r['texto']}",
                            f"{livro} {cap}:{vers}", r["id"], [])
                # Capítulo inteiro: um slide só, como sempre foi.
                if v_ini == 1 and v_fim == 9999:
                    partes = [f"{r['versiculo']}. {r['texto']}" for r in rows]
                    return (True, "",
                            f"{livro} {cap}\n\n" + "\n\n".join(partes),
                            f"{livro} {cap}", rows[0]["id"], [])
                # Faixa ("1-7"): um versículo por slide na projeção.
                faixa_ref = f"{livro} {cap}:{v_ini}-{v_fim}"
                partes = [f"{r['versiculo']}. {r['texto']}" for r in rows]
                return (True, "",
                        f"{faixa_ref}\n\n" + "\n\n".join(partes),
                        faixa_ref, rows[0]["id"],
                        [[r['versiculo'], r['texto']] for r in rows])

            def _preview_biblia():
                res = _resolver_referencia_biblia()
                preview_text.config(state='normal')
                preview_text.delete('1.0', tk.END)
                preview_text.insert(tk.END, res[1] if not res[0] else res[2])
                preview_text.config(state='disabled')

            # ── Seletor de anúncio (tipo "anuncio") ──
            anuncio_var = tk.StringVar()
            _anuncios_sel = _listar_anuncios_db()
            _anuncios_titulos = [(a.get("titulo") or "").strip()
                                 for a in _anuncios_sel]

            anuncio_frame = tk.Frame(add_main, bg='#0d1117')
            tk.Label(anuncio_frame, text="Anúncio:",
                     fg='#f0c040', bg='#0d1117',
                     font=("Arial", 11, "bold")).pack(anchor='w', pady=(6, 0))
            combo_anun = ttk.Combobox(anuncio_frame, textvariable=anuncio_var,
                                      values=_anuncios_titulos, width=44,
                                      font=("Arial", 10))
            combo_anun.pack(fill='x', pady=(0, 2))
            anun_preview = tk.Text(anuncio_frame, height=3, wrap='word',
                                   font=("Arial", 9), bg='#161b22', fg='#c9d1d9',
                                   relief='flat', exportselection=False)
            anun_preview.pack(fill='x', pady=(0, 4))
            anun_preview.config(state='disabled')

            btn_copia_anuncio = tk.Button(
                anuncio_frame, text="📋 Copiar", font=("Arial", 9, "bold"),
                bg='#21262d', fg='#f0c040', activebackground='#30363d',
                cursor='hand2', padx=10, pady=1,
                command=lambda: _copiar_previa(anun_preview))
            btn_copia_anuncio.pack(anchor='e', pady=(0, 4))

            def _preview_anuncio(event: object = None):
                sel = anuncio_var.get().strip()
                an = next((a for a in _anuncios_sel
                           if (a.get("titulo") or "").strip() == sel), None)
                anun_preview.config(state='normal')
                anun_preview.delete('1.0', tk.END)
                if an:
                    cat = (an.get("categoria") or "").strip()
                    texto = (an.get("texto") or "").strip()
                    anun_preview.insert(
                        tk.END, ((cat + "\n") if cat else "") + texto[:500])
                else:
                    anun_preview.insert(
                        tk.END, "Selecione o anúncio na lista acima.")
                anun_preview.config(state='disabled')

            combo_anun.bind("<<ComboboxSelected>>", _preview_anuncio)

            anuncio_frame.pack_forget()

            # Preenche o painel ao editar um anúncio existente
            if item_edit and (item_edit.get("tipo") or "").lower() == "anuncio":
                _an_ed = _buscar_anuncio_por_ref(item_edit.get("referencia_id"))
                if _an_ed:
                    anuncio_var.set((_an_ed.get("titulo") or "").strip())
                    _preview_anuncio()

            tk.Label(add_main, text="Duração estimada (segundos):", fg='#8b949e',
                     bg='#0d1117', font=("Arial", 9)).pack(anchor='w')
            dur_entry = tk.Entry(add_main, font=("Arial", 11), bg='#21262d',
                                 fg='#c9d1d9', insertbackground='#f0c040')
            dur_entry.insert(0, str((item_edit or {}).get("duracao_estimada_segundos") or 0))
            dur_entry.pack(fill='x', ipady=3, pady=2)

            arquivo_path_var = tk.StringVar(
                value=(item_edit or {}).get("caminho_arquivo") or "")

            arquivo_frame = tk.Frame(add_main, bg='#0d1117')
            tk.Label(arquivo_frame, text="Arquivo (vídeo/áudio/PowerPoint/Impress/PDF):",
                     fg='#8b949e', bg='#0d1117',
                     font=("Arial", 9)).pack(anchor='w')
            arquivo_row = tk.Frame(arquivo_frame, bg='#0d1117')
            arquivo_row.pack(fill='x', pady=2)
            arquivo_nome_lbl = tk.Label(
                arquivo_row,
                text=os.path.basename(arquivo_path_var.get()) or
                     "Nenhum arquivo selecionado",
                fg='#c9d1d9', bg='#21262d', font=("Arial", 10),
                anchor='w', padx=6, pady=3, width=1)
            arquivo_nome_lbl.pack(side='left', fill='x', expand=True)

            def _selecionar_arquivo():
                _sufixos = (
                    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v",
                    ".flv", ".mp3", ".wav", ".ogg", ".oga", ".m4a", ".flac",
                    ".aac", ".wma", ".ppt", ".pptx", ".pps", ".ppsx", ".odp",
                )
                _titulo_busca = "Selecionar vídeo, áudio ou apresentação"
                if tipo_var.get() == "sermao":
                    # Sermão também aceita PDF (aberto no visualizador do
                    # sistema, como a apresentação).
                    _sufixos = _sufixos + (".pdf",)
                    _titulo_busca = "Selecionar vídeo, áudio, apresentação ou PDF"
                # Usa o seletor do próprio aplicativo (inicia no home do
                # usuário, esconde os "." ocultos e não "pisca" como o
                # diálogo nativo do Tk/GTK).
                escolhidos = _escolher_arquivos_usuario(
                    parent=add_win,
                    titulo=_titulo_busca,
                    pasta_inicial=os.path.expanduser("~"),
                    sufixos=_sufixos)
                if not escolhidos:
                    return
                caminho = escolhidos[0]
                arquivo_path_var.set(caminho)
                arquivo_nome_lbl.config(text=os.path.basename(caminho))
                if not titulo_entry.get().strip() or \
                        titulo_entry.get().strip().startswith("Item "):
                    _nome_base = os.path.splitext(os.path.basename(caminho))[0]
                    titulo_entry.delete(0, tk.END)
                    titulo_entry.insert(0, _nome_base)

            def _limpar_arquivo():
                arquivo_path_var.set("")
                arquivo_nome_lbl.config(text="Nenhum arquivo selecionado")

            tk.Button(arquivo_row, text="📁 Buscar", font=("Arial", 10, "bold"),
                      bg='#1f6feb', fg='white', activebackground='#388bfd',
                      cursor='hand2', padx=10,
                      command=_selecionar_arquivo
                      ).pack(side='left', padx=(5, 0))
            tk.Button(arquivo_row, text="❌", font=("Arial", 10, "bold"),
                      bg='#da3633', fg='white', activebackground='#f85149',
                      cursor='hand2', padx=8, command=_limpar_arquivo
                      ).pack(side='left', padx=(3, 0))
            arquivo_frame.pack_forget()

            # ── Item "YouTube" (caixinha + URL) ──
            # Só aparece quando o tipo é "Vídeo" (ou na edição de um item que
            # já é YouTube): marcando a caixinha, o item passa a ser um vídeo
            # do YouTube e a URL é usada na execução (mpv + yt-dlp).
            youtube_var = tk.BooleanVar(
                value=((item_edit or {}).get("tipo") or "").lower() == "youtube"
                or bool((item_edit or {}).get("youtube_url")))
            youtube_url_var = tk.StringVar(
                value=(item_edit or {}).get("youtube_url") or "")

            youtube_frame = tk.Frame(add_main, bg='#0d1117')
            tk.Checkbutton(
                youtube_frame, text="YouTube", variable=youtube_var,
                bg='#0d1117', fg='#f0c040', selectcolor='#21262d',
                activebackground='#0d1117', activeforeground='#f0c040',
                font=("Arial", 11, "bold"),
                command=lambda: _atualizar_youtube()
            ).pack(anchor='w')

            youtube_url_row = tk.Frame(youtube_frame, bg='#0d1117')
            tk.Label(youtube_url_row, text="URL do vídeo:",
                     fg='#c9d1d9', bg='#0d1117',
                     font=("Arial", 10)).pack(side='left')
            youtube_url_entry = tk.Entry(
                youtube_url_row, textvariable=youtube_url_var,
                font=("Arial", 10), bg='#21262d', fg='#c9d1d9',
                insertbackground='#f0c040')
            youtube_url_entry.pack(side='left', fill='x', expand=True,
                                   padx=(4, 0), ipady=2)
            _menu_contexto_campo(
                youtube_url_entry,
                [("📋 Colar", lambda: _colar_texto_campo(youtube_url_entry))])

            _yt_url_inicial = youtube_url_var.get().strip()
            _yt_titulo_inicial = ((item_edit or {}).get("titulo_custom")
                                  or "").strip()
            if _yt_titulo_inicial == _yt_url_inicial:
                _yt_titulo_inicial = ""
            _yt_info: dict[str, object] = {
                "url": _yt_url_inicial if youtube_var.get() else "",
                "titulo": _yt_titulo_inicial if youtube_var.get() else "",
                "duracao": int((item_edit or {}).get(
                    "duracao_estimada_segundos") or 0) if youtube_var.get() else 0,
                "token": 0, "timer": None, "pendente": False,
                "pendente_url": "",
                # O título é sempre editável. Quando o operador digita, o
                # metadado do yt-dlp não pode mais sobrescrever o texto.
                "editado": bool(_yt_titulo_inicial),
                "preenchendo": False}

            def _titulo_digitado(*_args):
                if not _yt_info.get("preenchendo"):
                    _yt_info["editado"] = True

            titulo_var.trace_add("write", _titulo_digitado)

            def _atualizar_url_abaixo_titulo():
                url = youtube_url_var.get().strip()
                try:
                    if youtube_var.get() and url:
                        youtube_titulo_url_lbl.config(text=url)
                        youtube_titulo_url_lbl.pack(
                            fill='x', pady=(0, 2), after=titulo_entry)
                    else:
                        youtube_titulo_url_lbl.pack_forget()
                except tk.TclError:
                    pass

            def _definir_titulo_youtube(texto: str):
                """Preenche o título automaticamente sem apagar texto digitado."""
                if _yt_info.get("editado"):
                    return
                _yt_info["preenchendo"] = True
                try:
                    titulo_var.set(texto)
                except tk.TclError:
                    pass
                finally:
                    _yt_info["preenchendo"] = False

            def _aplicar_info_youtube(info, url: str, token: int):
                if token != _yt_info.get("token"):
                    return
                try:
                    if not add_win.winfo_exists():
                        return
                except tk.TclError:
                    return
                _yt_info["pendente"] = False
                _yt_info["pendente_url"] = ""
                if not info or not info.get("titulo"):
                    # Metadado indisponível não apaga o que o operador digitou.
                    return
                _yt_info["url"] = url
                _yt_info["titulo"] = str(info.get("titulo") or "")
                try:
                    _yt_info["duracao"] = int(round(float(info.get("duracao") or 0)))
                except (TypeError, ValueError):
                    _yt_info["duracao"] = 0
                _definir_titulo_youtube(str(_yt_info["titulo"]))
                try:
                    dur_entry.delete(0, tk.END)
                    if int(_yt_info["duracao"]) > 0:
                        dur_entry.insert(0, str(_yt_info["duracao"]))
                except tk.TclError:
                    pass

            def _iniciar_info_youtube(url: str, token: int):
                def _trabalho():
                    info = _obter_info_youtube(url)
                    try:
                        self.root.after(
                            0, lambda: _aplicar_info_youtube(info, url, token))
                    except (tk.TclError, RuntimeError):
                        pass

                threading.Thread(target=_trabalho, daemon=True,
                                 name="navepro-youtube-info").start()

            def _agendar_info_youtube(*_args):
                _atualizar_url_abaixo_titulo()
                timer = _yt_info.get("timer")
                if timer is not None:
                    try:
                        add_win.after_cancel(timer)
                    except tk.TclError:
                        pass
                    _yt_info["timer"] = None
                url = youtube_url_var.get().strip()
                if not youtube_var.get() or not url or not _eh_url_youtube(url):
                    # Ao desmarcar o YouTube ou limpar a URL, o título (auto
                    # ou digitado) é mantido: o operador pode salvá-lo assim.
                    _yt_info["token"] = int(_yt_info.get("token") or 0) + 1
                    _yt_info["pendente"] = False
                    _yt_info["pendente_url"] = ""
                    return
                if url != _yt_info.get("url"):
                    url_anterior = str(_yt_info.get("url") or "")
                    _yt_info["url"] = url
                    _yt_info["titulo"] = ""
                    _yt_info["duracao"] = 0
                    if url_anterior:
                        # Trocou de vídeo: o título era do vídeo anterior.
                        _yt_info["editado"] = False
                        _definir_titulo_youtube("")
                    # Se ainda não havia URL, preserva o título digitado.
                if _yt_info.get("url") == url and _yt_info.get("titulo"):
                    return
                if (_yt_info.get("pendente")
                        and _yt_info.get("pendente_url") == url):
                    return
                # Invalida qualquer consulta antiga antes de agendar a nova.
                _yt_info["token"] = int(_yt_info.get("token") or 0) + 1
                token = int(_yt_info["token"])

                def _disparar():
                    _yt_info["timer"] = None
                    if token != _yt_info.get("token"):
                        return
                    try:
                        if not add_win.winfo_exists():
                            return
                    except tk.TclError:
                        return
                    if youtube_url_var.get().strip() != url:
                        return
                    _yt_info["pendente"] = True
                    _yt_info["pendente_url"] = url
                    _iniciar_info_youtube(url, token)

                try:
                    _yt_info["timer"] = add_win.after(700, _disparar)
                except tk.TclError:
                    pass

            def _atualizar_youtube():
                if youtube_var.get():
                    youtube_url_row.pack(fill='x', pady=(2, 0))
                else:
                    youtube_url_row.pack_forget()
                _agendar_info_youtube()

            youtube_url_var.trace_add(
                "write", lambda *a: _agendar_info_youtube())
            youtube_var.trace_add(
                "write", lambda *a: _agendar_info_youtube())
            _atualizar_youtube()

            # A janela é posicionada UMA única vez, na abertura, já
            # centralizada sobre a janela "Ordem de Serviço" (via
            # _centralizar_sobre, acima). Ao trocar o tipo do item, aplicamos
            # a geometria só com o TAMANHO (sem coordenadas): o Tk/gerenciador
            # de janelas mantém a posição atual, inclusive depois de o
            # operador arrastar a janela. Reenviar coordenadas era o que fazia
            # a janela saltar (o pedido era reinterpretado com o deslocamento
            # da moldura e ia parar no canto superior esquerdo).
            def _aplicar_geometria(tamanho: str) -> None:
                """Redimensiona a janela do editor sem mudar a posição."""
                try:
                    add_win.geometry(tamanho)
                except tk.TclError:
                    pass

            def _atualizar_paineis():
                t = tipo_var.get()
                if t in ("video", "audio", "sermao"):
                    arquivo_frame.pack(fill='x')
                else:
                    arquivo_frame.pack_forget()
                if t == "versiculo":
                    biblia_frame.pack(fill='x', pady=(2, 0))
                else:
                    biblia_frame.pack_forget()
                if t == "hino":
                    hino_frame.pack(fill='x', pady=(2, 0))
                else:
                    hino_frame.pack_forget()
                if t == "anuncio":
                    anuncio_frame.pack(fill='x', pady=(2, 0))
                else:
                    anuncio_frame.pack_forget()
                # YouTube (caixinha + URL) só tem sentido com o tipo "Vídeo"
                # (ou na edição de um item que já é YouTube). Ao sair do
                # vídeo a caixinha é desmarcada — senão o _salvar_item forçaria
                # tipo "youtube" por baixo do tipo que o operador acabou de
                # marcar.
                if t in ("video", "youtube"):
                    youtube_frame.pack(fill='x', pady=(6, 0))
                else:
                    youtube_frame.pack_forget()
                    youtube_var.set(False)
                _aplicar_geometria("700x600" if t == "versiculo"
                                   else "700x600" if t == "hino"
                                   else "700x510" if t == "anuncio"
                                   else "700x450")

            tipo_var.trace_add("write", lambda *a: _atualizar_paineis())
            _atualizar_paineis()
            # A janela nasce com 380 de altura e cresce ao mostrar o painel do
            # tipo inicial; centraliza de novo com o tamanho final para não
            # abrir deslocada para baixo. Depois disto a posição nunca mais é
            # reenviada (os redimensionamentos aplicam só o tamanho).
            _centralizar_sobre(add_win, janela)

            def _salvar_item():
                serv = _servico_atual()
                if serv is None:
                    return
                tipo = tipo_var.get()
                titulo = titulo_entry.get().strip()
                termo = ref_entry.get().strip()
                duracao = int(dur_entry.get().strip()) if dur_entry.get().strip().isdigit() else 0
                caminho_arquivo = arquivo_path_var.get().strip()
                # Caixinha "YouTube": quando marcada, o item vira um vídeo do
                # YouTube e guarda a URL (em vez de um arquivo em disco).
                # O título é sempre editável: o metadado do yt-dlp só preenche
                # o campo quando ele está vazio, e uma falha do yt-dlp (ou a
                # ausência dele, como no sandbox do Flatpak) NÃO impede salvar
                # a URL com o título que o operador digitou.
                youtube_url = ""
                if youtube_var.get():
                    youtube_url = youtube_url_var.get().strip()
                    if not _eh_url_youtube(youtube_url):
                        tkinter.messagebox.showwarning(
                            "URL inválida",
                            "URL inválida! Insira uma URL do YouTube",
                            parent=add_win)
                        return
                    tipo = "youtube"
                    caminho_arquivo = ""
                    info = None
                    if (_yt_info.get("url") == youtube_url
                            and _yt_info.get("titulo")):
                        info = {"titulo": _yt_info.get("titulo"),
                                "duracao": _yt_info.get("duracao") or 0}
                    else:
                        try:
                            add_win.configure(cursor="watch")
                            add_win.update_idletasks()
                        except tk.TclError:
                            pass
                        try:
                            info = _obter_info_youtube(youtube_url)
                        finally:
                            try:
                                add_win.configure(cursor="")
                            except tk.TclError:
                                pass
                        if info:
                            _yt_info["url"] = youtube_url
                            _yt_info["titulo"] = str(info.get("titulo") or "")
                            try:
                                _yt_info["duracao"] = int(round(
                                    float(info.get("duracao") or 0)))
                            except (TypeError, ValueError):
                                _yt_info["duracao"] = 0
                    # O campo digitado é a fonte da verdade; o metadado só
                    # entra quando o operador não escreveu nada.
                    if not titulo and info and info.get("titulo"):
                        titulo = str(info.get("titulo") or "").strip()
                    if info:
                        try:
                            duracao_info = int(round(
                                float(info.get("duracao") or 0)))
                        except (TypeError, ValueError):
                            duracao_info = 0
                        if duracao_info > 0:
                            duracao = duracao_info
                if tipo == "youtube" and not youtube_url:
                    # Caixinha desmarcada num item que era YouTube: evita
                    # salvar "youtube" sem URL (que ficaria sem mídia).
                    tipo = "slide"
                if tipo not in ("video", "audio", "sermao"):
                    caminho_arquivo = ""

                # Verdadeiro quando o usuário usou o seletor bíblico do
                # painel "versiculo" (versão + livro + capítulo preenchidos).
                _usou_painel_biblia = bool(
                    tipo == "versiculo"
                    and biblia_versao_var.get().strip()
                    and biblia_livro_var.get().strip()
                    and biblia_cap_var.get().strip().isdigit())
                _usou_painel_anuncio = bool(
                    tipo == "anuncio" and anuncio_var.get().strip())
                _usou_painel_hino = bool(
                    tipo == "hino" and hino_num_var.get().strip())

                # ── Resolução da referência por busca (nº ou nome) ──
                # Se o campo "Buscar" estiver vazio, o próprio Título digitado
                # já é usado como termo de busca (hino/mídia por número ou nome).
                ref_id = None
                letra_snap = ""
                vers_salvos = []
                _usou_titulo_como_busca = (not termo)
                if not termo:
                    termo = titulo
                if tipo == "hino" and _usou_painel_hino:
                    res_h = _resolver_hino()
                    if not res_h[0]:
                        tkinter.messagebox.showwarning("Hino", res_h[1],
                                                       parent=add_win)
                        return
                    _, _, letra_snap, ref_display, ref_id = res_h
                    if not titulo or _usou_titulo_como_busca:
                        titulo = ref_display
                elif tipo == "hino":
                    rows_match = _buscar_hino_por_termo_ou_id(termo)
                    if not rows_match:
                        tkinter.messagebox.showwarning(
                            "Busca", f"Nenhum hino encontrado para: \"{termo}\".",
                            parent=add_win)
                        return
                    ref_hino = rows_match[0]
                    ref_id = ref_hino.get("id")
                    letra_snap = ref_hino.get("letra_completa", "")
                    if not titulo or _usou_titulo_como_busca:
                        titulo = ref_hino.get("titulo", "") or f"Item ({tipo.title()})"
                elif tipo in ("video", "audio", "sermao") and caminho_arquivo:
                    if not os.path.exists(caminho_arquivo):
                        tkinter.messagebox.showwarning(
                            "Arquivo", f"Arquivo não encontrado:\n{caminho_arquivo}",
                            parent=add_win)
                        return
                    if not titulo or _usou_titulo_como_busca:
                        titulo = (os.path.splitext(os.path.basename(caminho_arquivo))[0]
                                  or f"Item ({tipo.title()})")
                elif tipo in ("video", "audio"):
                    rows_match = _buscar_midia_por_termo_ou_id(termo, tipo=tipo)
                    if not rows_match:
                        tkinter.messagebox.showwarning(
                            "Busca", f"Nenhuma {tipo.title()} encontrada para: \"{termo}\".",
                            parent=add_win)
                        return
                    ref_midia = rows_match[0]
                    ref_id = ref_midia.get("id")
                    if not titulo or _usou_titulo_como_busca:
                        titulo = ref_midia.get("nome_exibicao", "") or f"Item ({tipo.title()})"
                elif tipo == "anuncio" and _usou_painel_anuncio:
                    ref_an = next(
                        (a for a in _anuncios_sel
                         if (a.get("titulo") or "").strip()
                         == anuncio_var.get().strip()), None)
                    if ref_an is None:
                        tkinter.messagebox.showwarning(
                            "Anúncios",
                            "O anúncio selecionado não foi encontrado.",
                            parent=add_win)
                        return
                    ref_id = ref_an.get("id")
                    letra_snap = ref_an.get("texto") or ""
                    if not titulo or _usou_titulo_como_busca:
                        titulo = ref_an.get("titulo") or f"Item ({tipo.title()})"
                elif tipo == "anuncio":
                    rows_match = _buscar_anuncio_por_termo(termo)
                    if not rows_match:
                        tkinter.messagebox.showwarning(
                            "Busca", f"Nenhum anúncio encontrado para: \"{termo}\".",
                            parent=add_win)
                        return
                    ref_an = rows_match[0]
                    ref_id = ref_an.get("id")
                    letra_snap = ref_an.get("texto") or ""
                    if not titulo or _usou_titulo_como_busca:
                        titulo = ref_an.get("titulo") or f"Item ({tipo.title()})"
                elif tipo == "versiculo" and _usou_painel_biblia:
                    res = _resolver_referencia_biblia()
                    if not res[0]:
                        tkinter.messagebox.showwarning("Bíblia", res[1],
                                                       parent=add_win)
                        return
                    _, _, letra_snap, ref_display, ref_id, vers_salvos = res
                    if not titulo or _usou_titulo_como_busca:
                        titulo = ref_display
                elif tipo == "youtube":
                    # A URL é a mídia do item, não o título: a caixa "Buscar"
                    # não tem como ser preenchida aqui (não há busca), então
                    # o título digitado nunca deve ser trocado pela URL. Só
                    # quando não há título nenhum é que a URL vira o rótulo.
                    if not titulo:
                        titulo = youtube_url or f"Item ({tipo.title()})"
                elif termo.isdigit():
                    ref_id = int(termo)
                if not titulo:
                    titulo = f"Item ({tipo.title()})"
                if tipo == "versiculo" and ref_id and not _usou_painel_biblia:
                    rows_v = db_query("SELECT * FROM versiculos WHERE id = ?", (ref_id,))
                    if rows_v:
                        r = rows_v[0]
                        letra_snap = f"{r['livro']} {r['capitulo']}:{r['versiculo']}\n\n{r['texto']}"
                        if titulo.startswith("Item"):
                            titulo = f"{r['livro']} {r['capitulo']}:{r['versiculo']}"

                itens = serv.setdefault("itens", [])
                if item_edit is not None and (item_edit.get("id") or 0):
                    item_id = item_edit.get("id")
                    idx = next((i for i, x in enumerate(itens)
                                if x.get("id") == item_id), None)
                    if idx is None:
                        return
                    original = dict(itens[idx])
                    itens[idx] = dict(original)
                    itens[idx].pop("versiculos", None)
                    itens[idx].update({
                        "tipo": tipo,
                        "referencia_id": ref_id,
                        "titulo_custom": titulo,
                        "letra_snapshot": letra_snap,
                        "caminho_arquivo": caminho_arquivo,
                        "youtube_url": youtube_url,
                        "duracao_estimada_segundos": duracao,
                    })
                    # Faixa de versículos: guarda os pares [número, texto] para
                    # a projeção mostrar um versículo por slide. Sem faixa,
                    # a chave é removida e o item volta a um slide só.
                    if vers_salvos:
                        itens[idx]["versiculos"] = vers_salvos
                    novo_id = item_id
                else:
                    novo_id = dados["_proximo_id_item"]
                    dados["_proximo_id_item"] = novo_id + 1
                    original = None
                    novo_item = {
                        "id": novo_id,
                        "tipo": tipo,
                        "referencia_id": ref_id,
                        "titulo_custom": titulo,
                        "letra_snapshot": letra_snap,
                        "caminho_arquivo": caminho_arquivo,
                        "youtube_url": youtube_url,
                        "duracao_estimada_segundos": duracao,
                    }
                    if vers_salvos:
                        novo_item["versiculos"] = vers_salvos
                    itens.append(novo_item)
                if not _salvar_servicos_json(dados):
                    if original is not None:
                        itens[idx] = original
                    else:
                        serv["itens"] = [it for it in serv.get("itens")
                                         if it.get("id") != novo_id]
                        dados["_proximo_id_item"] = novo_id
                    tkinter.messagebox.showwarning(
                        "⚠️", "Não foi possível salvar em servicos.json.", parent=add_win)
                    return
                _carregar_itens()
                tree.selection_set(str(novo_id))
                tree.focus(str(novo_id))
                add_win.destroy()

            tk.Button(add_main, text="💾 Salvar", font=("Arial", 12, "bold"),
                      bg='#238636', fg='white', activebackground='#2ea043',
                      command=_salvar_item, cursor='hand2', padx=20, pady=5
                      ).pack(pady=10)

        def _editar_item_selecionado():
            serv = _servico_atual()
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um item.", parent=janela)
                return
            if not serv:
                return
            it = next((x for x in (serv.get("itens") or [])
                       if x.get("id") == int(sel[0])), None)
            if it is None:
                return
            _abrir_editor_item(it)

        def _mover_item(direcao: int):
            """Move item para cima (-1) ou baixo (+1)."""
            sel = tree.selection()
            if not sel:
                return
            serv = _servico_atual()
            if not serv:
                return
            itens = list(serv.get("itens") or [])
            idx_atual = next((i for i, it in enumerate(itens)
                              if it.get("id") == int(sel[0])), None)
            if idx_atual is None:
                return
            idx_novo = idx_atual + direcao
            if idx_novo < 0 or idx_novo >= len(itens):
                return
            itens[idx_atual], itens[idx_novo] = itens[idx_novo], itens[idx_atual]
            serv["itens"] = itens
            if not _salvar_servicos_json(dados):
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar a reordenação.", parent=janela)
                return
            _carregar_itens()
            tree.selection_set(str(itens[idx_novo].get("id")))
            tree.focus(str(itens[idx_novo].get("id")))

        # Snapshot da janela principal p/ restauração após cada item do
        # serviço vive em self._snapshot_servico (criado no __init__:
        # capturado uma única vez por sessão, compartilhado com o
        # controle remoto — não reatribuir aqui).

        def _executar_servico():
            """Reproduz APENAS o próximo item da lista e para.

            A escolha do operador vale uma única vez: se ele selecionou um
            item na lista, a próxima reprodução começa nele e o botão passa a
            avançar item a item até o fim da lista, voltando ao primeiro ao
            terminar — a escolha anterior é esquecida. Sem seleção, segue o
            mesmo avanço item a item, do começo ao fim. A lógica real está em
            `executar_proximo_item_servico` (reutilizada pelo controle
            remoto); aqui ficam só a seleção da lista e os diálogos.
            """
            serv = _servico_atual()
            if not serv:
                return
            escolhido = _item_escolhido["id"]
            # Consome a escolha do operador (uma única vez). A partir daqui a
            # seleção da lista é ignorada: o botão só avança item a item e, ao
            # terminar, volta ao primeiro — nunca mais volta ao item escolhido.
            _item_escolhido["id"] = None
            res = self.executar_proximo_item_servico(
                serv, escolhido=escolhido,
                ao_destacar=lambda it: (tree.selection_set(str(it.get('id'))),
                                        tree.see(str(it.get('id')))))
            if not res.get('ok'):
                if res.get('codigo') == 'vazio':
                    tkinter.messagebox.showinfo(
                        "Vazio", res.get('erro', ''), parent=janela)
                else:
                    tkinter.messagebox.showwarning(
                        "Executar", res.get('erro', ''), parent=janela)

        btn_novo = tk.Button(
            btn_frame, text="➕ Novo Serviço", font=("Arial", 11, "bold"),
            bg='#238636', fg='white', activebackground='#2ea043',
            command=_novo_servico, cursor='hand2', padx=12, pady=4)
        btn_editar = tk.Button(
            btn_frame, text="✏️ Editar Serviço", font=("Arial", 11, "bold"),
            bg='#1f6feb', fg='white', activebackground='#388bfd',
            command=_editar_servico, cursor='hand2', padx=12, pady=4)
        btn_excluir = tk.Button(
            btn_frame, text="🗑️ Excluir Item", font=("Arial", 11, "bold"),
            bg='#da3633', fg='white', activebackground='#f85149',
            command=_apagar_item_contexto, cursor='hand2', padx=12, pady=4)
        btn_transferir = tk.Button(
            btn_frame, text="🔄 Transferir", font=("Arial", 11, "bold"),
            bg='#2f6f47', fg='white', activebackground='#3f8f57',
            command=lambda: self.janela_transferencia(janela),
            cursor='hand2', padx=12, pady=4)
        btn_add = tk.Button(
            btn_frame, text="➕ Ad. Item", font=("Arial", 11, "bold"),
            bg='#1f6feb', fg='white', activebackground='#388bfd',
            command=lambda: _abrir_editor_item(), cursor='hand2',
            padx=12, pady=4)
        btn_subir = tk.Button(
            btn_frame, text="⬆️", font=("Arial", 11, "bold"),
            bg='#21262d', fg='#f0c040', activebackground='#30363d',
            command=lambda: _mover_item(-1), cursor='hand2', padx=8, pady=4)
        btn_descer = tk.Button(
            btn_frame, text="⬇️", font=("Arial", 11, "bold"),
            bg='#21262d', fg='#f0c040', activebackground='#30363d',
            command=lambda: _mover_item(1), cursor='hand2', padx=8, pady=4)
        btn_exec = tk.Button(
            btn_frame, text="▶️ Executar Serviço", font=("Arial", 11, "bold"),
            bg='#6e40c9', fg='#f0c040', activebackground='#8b5cf6',
            command=_executar_servico, cursor='hand2', padx=12, pady=4)

        botoes_esq = [btn_novo, btn_editar, btn_excluir, btn_transferir,
                      btn_add, btn_subir, btn_descer]
        _layout_botoes = {"modo": None}

        def _reorganizar_botoes(event=None):
            """Uma linha quando cabe; duas quando a janela fica estreita."""
            largura = btn_frame.winfo_width()
            if largura <= 1:
                largura = janela.winfo_width()
            if largura <= 1:
                return
            necessario = sum(b.winfo_reqwidth() + 6 for b in botoes_esq)
            necessario += btn_exec.winfo_reqwidth() + 24
            modo = "linha" if largura >= necessario else "duas"
            if _layout_botoes["modo"] == modo:
                return
            _layout_botoes["modo"] = modo
            for b in botoes_esq + [btn_exec]:
                b.grid_forget()
            for c in range(len(botoes_esq) + 2):
                btn_frame.columnconfigure(c, weight=0)
            for r in range(2):
                btn_frame.rowconfigure(r, weight=0)
            if modo == "linha":
                for col, b in enumerate(botoes_esq):
                    b.grid(row=0, column=col, sticky='w', padx=2, pady=2)
                spacer = len(botoes_esq)
                btn_frame.columnconfigure(spacer, weight=1)
                btn_exec.grid(row=0, column=spacer + 1, sticky='e',
                              padx=(12, 2), pady=2)
            else:
                for col, b in enumerate(botoes_esq):
                    b.grid(row=0, column=col, sticky='w', padx=2, pady=2)
                btn_frame.columnconfigure(len(botoes_esq), weight=1)
                btn_exec.grid(row=1, column=0,
                              columnspan=len(botoes_esq) + 1,
                              sticky='e', padx=2, pady=(0, 2))

        btn_frame.bind("<Configure>", _reorganizar_botoes)
        try:
            janela.update_idletasks()
        except tk.TclError:
            pass
        _reorganizar_botoes()

        def _f11_maximizar(event=None):
            _alternar_maximizar()
            return "break"

        janela.bind("<F11>", _f11_maximizar)

        # ── Navegação por teclado dos slides projetados (sem sair da janela) ──
        _slide_anterior, _slide_proximo, _parar_projecao = \
            self._criar_navegacao_slides()
        self._vincular_teclas_slides(janela, _slide_anterior, _slide_proximo,
                                     _parar_projecao)

        _carregar_servicos()
        # Se há serviços, seleciona o primeiro
        if combo_servico['values']:
            _on_servico_select()
