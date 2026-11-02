"""Navegação de slides, indicador e busca — closures compartilhadas.

As janelas de Hinos, Anúncios, Bíblia e Ordem de Serviço repetiam as MESMAS
closures (indicador "Slide x de y", setas/Esc, passador AvPag/RetPag, A−/A+
e busca com placeholder/debounce). Extraídas SEM alteração de comportamento:
cada janela continua com uma closure local fina que delega ao mixin, passando
só o que é dela (rótulo do slide, callback de sincronização).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class NavegacaoSlidesMixin:
    """Fábricas de closures de navegação/projeção (mixin da AppInterface)."""

    def _criar_atualizador_indicador_slide(self, label_slide):
        """Cria o atualizador do rótulo "Slide x de y" (versão padrão).

        A janela da Bíblia NÃO usa esta versão: o rótulo dela mostra o
        número do versículo e a faixa projetada (mantido local lá).
        """
        def _atualizar():
            try:
                if not label_slide.winfo_exists():
                    return
            except tk.TclError:
                return
            telao = self.player.telao
            em_slides = getattr(telao, "_em_slides", False)
            if em_slides and telao._slides:
                label_slide.config(
                    text=f"Slide {telao._slide_index + 1} de {len(telao._slides)}",
                    fg='#3fb950', bg='#161b22')
            elif getattr(telao, "_mostrando_imagem", False):
                label_slide.config(text="🖼️ Imagem ativa", fg='#3fb950', bg='#161b22')
            elif getattr(telao, "mostrando_letra", False):
                label_slide.config(text="Projeção ativa", fg='#f0c040', bg='#161b22')
            else:
                label_slide.config(text="Sem projeção", fg='#8b949e', bg='#161b22')
        return _atualizar

    def _criar_navegacao_slides(self, ao_navegar=None, ao_parar=None):
        """Cria _slide_anterior/_slide_proximo/_parar_projecao.

        `ao_navegar` roda depois de cada navegação bem-sucedida e `ao_parar`
        depois de encerrar a projeção — cada janela passa o seu (indicador,
        sincronização da Bíblia ou nada, na Ordem de Serviço).
        """
        def _slide_anterior(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if telao.slide_anterior() and ao_navegar is not None:
                ao_navegar()
            return "break"

        def _slide_proximo(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if telao.slide_proximo() and ao_navegar is not None:
                ao_navegar()
            return "break"

        def _parar_projecao(event: object = None):
            if not getattr(self.player.telao, "mostrando_letra", False):
                return None
            self.player.telao.parar_projecao()
            if ao_parar is not None:
                ao_parar()
            return "break"

        return _slide_anterior, _slide_proximo, _parar_projecao

    def _criar_passador_slides(self, janela, ao_navegar=None):
        """Passador (AvPag/RetPag, espaço, F5, BackSpace) com foco em campos.

        Usado por Anúncios e Bíblia: fora de campos de texto, essas teclas
        navegam os slides projetados como as setas. `ao_navegar` é o mesmo
        callback da navegação por setas de cada janela.
        """
        def _foco_em_campo_texto() -> bool:
            foco = janela.focus_get() or self.root.focus_get()
            if foco is None:
                return False
            try:
                return foco.winfo_class() in (
                    "Entry", "TEntry", "Text", "Spinbox", "TCombobox")
            except tk.TclError:
                return False

        def _navegar_passador(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if _foco_em_campo_texto():
                return None
            keysym = str(getattr(event, 'keysym', '') or '').lower()
            if keysym in ('next', 'page_next', 'page_down', 'space', 'f5'):
                if telao.slide_proximo() and ao_navegar is not None:
                    ao_navegar()
                return "break"
            if keysym in ('prior', 'page_prior', 'page_up', 'backspace'):
                if telao.slide_anterior() and ao_navegar is not None:
                    ao_navegar()
                return "break"
            return None

        for _seq in ("<Next>", "<Prior>", "<F5>", "<BackSpace>", "<space>"):
            janela.bind(_seq, _navegar_passador)
        for _seq in ("<Next>", "<Prior>", "<F5>", "<BackSpace>"):
            self.root.bind(_seq, _navegar_passador)
        return _navegar_passador

    def _ajustar_fonte_projecao(self, delta: float,
                                atualizar_indicador=None) -> None:
        """A+/A− na projeção de slides/letra (comum a Hinos/Bíblia/Anúncios)."""
        telao = self.player.telao
        cfg = getattr(telao, "_proj_cfg", None)
        if cfg is None:
            telao.configurar_projecao()
            cfg = telao._proj_cfg
        novo = min(15.0, max(1.0, float(cfg.get("tamanho_pct", 5.0)) + delta))
        cfg["tamanho_pct"] = novo
        telao._proj_cfg = cfg
        if getattr(telao, "_em_slides", False) and telao._slides:
            telao._mostrar_slide(telao._slide_index)
        elif getattr(telao, "mostrando_letra", False) and telao._current_text:
            telao._desenhar_texto_no_canvas(telao._current_text)
        self.salvar_config_projecao(dict(cfg))
        if atualizar_indicador is not None:
            atualizar_indicador()

    def _restaurar_fonte_projecao(self, atualizar_indicador=None) -> None:
        """Volta a fonte da projeção ao padrão, desfazendo o A−/A+ manual."""
        telao = self.player.telao
        cfg = getattr(telao, "_proj_cfg", None)
        if cfg is None:
            telao.configurar_projecao()
            cfg = telao._proj_cfg
        cfg["tamanho_pct"] = 5.0
        telao._proj_cfg = cfg
        if getattr(telao, "_em_slides", False) and telao._slides:
            telao._mostrar_slide(telao._slide_index)
        elif getattr(telao, "mostrando_letra", False) and telao._current_text:
            telao._desenhar_texto_no_canvas(telao._current_text)
        self.salvar_config_projecao(dict(cfg))
        if atualizar_indicador is not None:
            atualizar_indicador()

    def _vincular_teclas_slides(self, janela, anterior, proximo,
                                parar) -> None:
        """Setas e Esc navegam os slides na janela E no painel (root).

        A ligação no root é reaplicada a cada abertura da janela, então
        chamadas repetidas não acumulam handlers duplicados.
        """
        janela.bind("<Left>", anterior)
        janela.bind("<Up>", anterior)
        janela.bind("<Right>", proximo)
        janela.bind("<Down>", proximo)
        janela.bind("<Escape>", parar)
        self.root.bind("<Left>", anterior)
        self.root.bind("<Up>", anterior)
        self.root.bind("<Right>", proximo)
        self.root.bind("<Down>", proximo)
        self.root.bind("<Escape>", parar)


def _configurar_estilo_treeview_escuro() -> None:
    """Aparência escura padrão das TreeViews de Hinos e Anúncios."""
    style = ttk.Style()
    style.theme_use('clam')
    style.configure("Treeview", background="#21262d", foreground="#c9d1d9",
                    fieldbackground="#21262d", font=("Arial", 10))
    style.configure("Treeview.Heading", background="#161b22", foreground="#f0c040",
                    font=("Arial", 10, "bold"))
    style.map('Treeview', background=[('selected', '#6e40c9')],
              foreground=[('selected', '#ffffff')])


def _ligar_busca_com_debounce(janela, entry_busca, placeholder, buscar) -> None:
    """Placeholder + foco + busca em tempo real (debounce de 400 ms).

    `buscar` é chamado pelo timer e também pode ser o callback do <Return>.
    O id do timer fica numa LISTA de um elemento: o after() do Tk devolve o
    id como str e, guardado num int (ou chave de dict), o after_cancel
    falharia em silêncio.
    """
    def _on_focus_entry():
        if entry_busca.get().strip() == placeholder:
            entry_busca.delete(0, tk.END)
            entry_busca.config(fg='#f0c040')

    def _on_focus_out_entry():
        if not entry_busca.get().strip():
            entry_busca.delete(0, tk.END)
            entry_busca.insert(0, placeholder)
            entry_busca.config(fg='#8b949e')

    entry_busca.bind("<FocusIn>", lambda e: _on_focus_entry())
    entry_busca.bind("<FocusOut>", lambda e: _on_focus_out_entry())

    _debounce_id: list = [None]

    def _on_key(event=None):
        if _debounce_id[0]:
            janela.after_cancel(_debounce_id[0])
        _debounce_id[0] = janela.after(400, buscar)

    entry_busca.bind("<KeyRelease>", _on_key)


def _termo_da_busca(entry_busca, placeholder) -> str:
    """Texto do campo sem o placeholder ("" quando só o placeholder está)."""
    termo = entry_busca.get().strip()
    if termo == placeholder or termo.startswith(placeholder):
        termo = termo[len(placeholder):].strip()
    return termo
