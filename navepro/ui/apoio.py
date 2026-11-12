"""Helpers de interface compartilhados pelas janelas do painel do operador.

Extraídos de NavePro.py sem alteração de comportamento:
  * menu de clique direito e colar em campos de texto;
  * listagem de pastas/arquivos do usuário (oculta ocultos, filtra sufixos);
  * seletor de arquivos próprio (abre em ~, modo "salvar como" opcional);
  * faixas de seção e área cinza-clara do tema.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.messagebox

from navepro.core.util_tk import (
    _centralizar_sobre,
    _habilitar_maximizar_janela,
)
from navepro.core.widgets_arredondados import TkArredondado

# Botões e campos de digitação desenham cantos arredondados: `tk` vira uma
# fachada que delega tudo ao tkinter real, trocando apenas Button e Entry.
tk = TkArredondado(tk)


def _menu_contexto_campo(campo, acoes) -> tk.Menu:
    """Liga um menu de clique direito a um campo de texto.

    `acoes` é uma lista de pares (rótulo, função) e o menu abre junto ao
    ponteiro. O `bind` cai no Entry interno dos campos arredondados, de
    modo que a mesma chamada serve para `tk.Entry` e `CampoArredondado`.
    """
    menu = tk.Menu(campo, tearoff=0, bg='#21262d', fg='#c9d1d9',
                   activebackground='#6e40c9', activeforeground='#ffffff',
                   font=("Arial", 10))

    def _abrir(event) -> str:
        try:
            menu.tk_popup(event.x_root, event.y_root, 0)
        finally:
            menu.grab_release()
        return "break"

    for rotulo, comando in acoes:
        menu.add_command(label=rotulo, command=comando)
    campo.bind("<Button-3>", _abrir)
    return menu


def _colar_texto_campo(campo) -> None:
    """Cola a área de transferência no campo (substitui a seleção)."""
    try:
        texto = campo.clipboard_get()
    except tk.TclError:
        return
    try:
        if campo.selection_present():
            campo.delete('sel.first', 'sel.last')
    except tk.TclError:
        pass
    campo.insert('insert', texto)


def _listar_pastas_arquivos_usuario(
        caminho: str,
        sufixos: tuple[str, ...] = (".xml", ".txt", ".json")
) -> list[tuple[str, str, bool]]:
    """Lista pastas e arquivos com os sufixos informados.

    Esconde tudo que começa com "." (pastas/arquivos ocultos do sistema).
    Retorna (caminho_completo, nome, é_pasta).
    """
    import os
    itens = []
    try:
        for e in os.scandir(caminho):
            if e.name.startswith("."):
                continue
            try:
                e_dir = e.is_dir()
            except OSError:
                continue
            if e_dir or e.name.lower().endswith(sufixos):
                itens.append((os.path.join(caminho, e.name), e.name, e_dir))
    except OSError:
        return []
    itens.sort(key=lambda t: (not t[2], t[1].lower()))
    return itens


def _escolher_arquivos_usuario(
        parent: tk.Toplevel | None,
        titulo: str,
        pasta_inicial: str | None = None,
        sufixos: tuple[str, ...] = (".xml", ".txt", ".json"),
        nome_para_salvar: str = "",
) -> tuple[str, ...]:
    """Seletor de arquivos que inicia no diretório do usuário (~).

    Mostra apenas as pastas/arquivos do usuário — esconde tudo que começa
    com "." (ocultos do sistema) e filtra os arquivos pelos sufixos dados.

    Com `nome_para_salvar` informado vira um "salvar como": mostra um campo
    com o nome sugerido, o botão principal vira "💾 Salvar" e o retorno é um
    único caminho. Nesse modo, duas cliques num arquivo existente apenas
    colocam o nome dele no campo.
    """
    import os
    pasta = {"atual": os.path.abspath(os.path.expanduser(pasta_inicial or "~"))}
    escolhidos: list[str] = []
    _itens: list[tuple[str, bool]] = []  # (caminho, é_pasta)
    salvando = bool(nome_para_salvar)
    ent_nome: tk.Entry | None = None

    dial = tk.Toplevel(parent)
    dial.title(titulo)
    dial.geometry("560x545" if salvando else "560x500")
    dial.configure(bg='#0d1117')
    if parent is not None:
        dial.transient(parent)
    _centralizar_sobre(dial, parent)
    _habilitar_maximizar_janela(dial)

    def _encurtar(texto: str, limite: int = 58) -> str:
        return texto if len(texto) <= limite else "…" + texto[-(limite - 1):]

    def _entrar(caminho: str) -> None:
        caminho = os.path.abspath(caminho)
        itens = _listar_pastas_arquivos_usuario(caminho, sufixos)
        _itens[:] = [(cam, is_dir) for cam, _, is_dir in itens]
        pasta["atual"] = caminho
        lbl_pasta.config(text=_encurtar(caminho))
        listbox.delete(0, tk.END)
        for _cam, nome, is_dir in itens:
            listbox.insert(tk.END, f"{'📁 ' if is_dir else '📄 '}{nome}")

    def _subir() -> None:
        _entrar(os.path.dirname(pasta["atual"]))

    barra = tk.Frame(dial, bg='#161b22')
    barra.pack(fill='x', padx=6, pady=(8, 4))
    tk.Button(barra, text="⌂ Início", font=("Arial", 10, "bold"),
              bg='#21262d', fg='#c9d1d9', activebackground='#30363d',
              command=lambda: _entrar(os.path.expanduser("~"))
              ).pack(side='left', padx=(0, 4), pady=2)
    tk.Button(barra, text="⬆ Subir", font=("Arial", 10, "bold"),
              bg='#21262d', fg='#c9d1d9', activebackground='#30363d',
              command=_subir).pack(side='left', pady=2)
    lbl_pasta = tk.Label(barra, text="", fg='#f0c040', bg='#161b22',
                         font=("Arial", 10), anchor='w')
    lbl_pasta.pack(side='left', fill='x', expand=True, padx=6)

    listbox = tk.Listbox(dial, bg='#21262d', fg='#c9d1d9',
                         font=("Arial", 11), selectmode='extended',
                         highlightthickness=0, bd=0, activestyle='none')
    listbox.pack(fill='both', expand=True, padx=6, pady=4)
    scroll = tk.Scrollbar(listbox, orient='vertical', command=listbox.yview)
    listbox.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y')

    def _validar_salvar() -> str | None:
        """Monta o caminho final ou None para manter o diálogo aberto."""
        nome = ent_nome.get().strip() if ent_nome is not None else ""
        if not nome:
            tkinter.messagebox.showwarning(
                "Salvar", "Escreva o nome do arquivo para salvar.", parent=dial)
            return None
        caminho = os.path.abspath(os.path.join(pasta["atual"], nome))
        if os.path.isdir(caminho):
            # Apontou para uma pasta: entra nela em vez de salvar.
            _entrar(caminho)
            return None
        if os.path.exists(caminho) and not tkinter.messagebox.askyesno(
                "Arquivo já existe",
                f"Já existe um arquivo com esse nome:\n\n{caminho}\n\n"
                "Quer sobrescrever?",
                parent=dial):
            return None
        return caminho

    def _fechar_ok(*idxs: int) -> None:
        if salvando:
            caminho = _validar_salvar()
            if caminho is None:
                return
            escolhidos[:] = [caminho]
            dial.destroy()
            return
        caminhos = [_itens[i][0] for i in idxs if not _itens[i][1]]
        escolhidos[:] = caminhos
        dial.destroy()

    def _clicar_duplo(event) -> None:
        idx = listbox.nearest(event.y)
        if not (0 <= idx < len(_itens)):
            return
        caminho, is_dir = _itens[idx]
        if is_dir:
            _entrar(caminho)
        elif salvando and ent_nome is not None:
            ent_nome.delete(0, tk.END)
            ent_nome.insert(0, os.path.basename(caminho))
            ent_nome.icursor(tk.END)
        else:
            _fechar_ok(idx)

    def _ok(_event=None) -> None:
        _fechar_ok(*listbox.curselection())

    def _cancelar(_event=None) -> None:
        escolhidos[:] = []
        dial.destroy()

    _entrar(pasta["atual"])
    listbox.bind("<Double-Button-1>", _clicar_duplo)
    dial.bind("<Return>", _ok)
    dial.bind("<Escape>", _cancelar)

    # ── Nome do arquivo (modo "salvar como") ──
    if salvando:
        linha_nome = tk.Frame(dial, bg='#0d1117')
        linha_nome.pack(fill='x', padx=6, pady=(2, 0))
        tk.Label(linha_nome, text="Nome do arquivo:", font=("Arial", 10, "bold"),
                 fg='#f0c040', bg='#0d1117').pack(side='left', padx=(4, 6))
        ent_nome = tk.Entry(linha_nome, font=("Arial", 11), bg='#21262d',
                            fg='#f0c040', insertbackground='#f0c040',
                            bd=0, highlightthickness=0)
        ent_nome.pack(side='left', fill='x', expand=True, padx=(0, 6), ipady=3)
        ent_nome.insert(0, nome_para_salvar)
        # O nome vem selecionado: é só digitar para trocar.
        ent_nome.selection_range(0, tk.END)
        ent_nome.focus_set()

    rodape = tk.Frame(dial, bg='#0d1117')
    rodape.pack(fill='x', padx=6, pady=6)
    tk.Button(rodape, text=("💾 Salvar" if salvando else "Importar"),
              font=("Arial", 11, "bold"),
              bg=('#1f6feb' if salvando else '#238636'), fg='white',
              activebackground=('#388bfd' if salvando else '#2ea043'),
              command=_ok).pack(side='right', padx=(4, 0))
    tk.Button(rodape, text="Cancelar", font=("Arial", 11, "bold"),
              bg='#da3633', fg='white', activebackground='#f85149',
              command=_cancelar).pack(side='right')

    dial.grab_set()
    dial.wait_window()
    return tuple(escolhidos)


def _criar_faixa_secao(parent, topo: bool = True):
    """Faixa cinza no topo/base de uma seção do painel do operador.

    No tema ESCURO a faixa assume a cor do cartão e fica invisível (o visual
    escuro permanece idêntico). No tema CLARO a faixa fica num cinza carvão,
    delimitando as seções. A cor é aplicada em ``_aplicar_tema_widget`` a partir
    do atributo ``_navepro_faixa_secao``.
    """
    faixa = tk.Frame(parent, bg='#161b22', height=6)
    faixa._navepro_faixa_secao = True
    faixa.pack(fill='x', side='top' if topo else 'bottom')
    return faixa


def _marcar_area_cinza_clara(widget, escuro: str = '#21262d',
                             claro: str | None = None):
    """Marca um widget para ficar cinza no tema CLARO (no escuro usa `escuro`).

    Usado na faixa inferior de controles do painel do operador, que deve virar
    um bloco cinza apenas no tema claro. A cor é aplicada em
    ``_aplicar_tema_widget`` (atributo ``_navepro_area_cinza_clara``).

    `claro` define um tom próprio para o tema claro (ex.: a faixa de controles
    e o campo de resultados usam ``COR_AREA_CONTROLES_CLARA``). Sem ele, usa a
    equivalência clara de `escuro`, preservando o comportamento anterior.
    """
    widget._navepro_area_cinza_clara = True
    widget._navepro_area_cinza_escuro = escuro
    if claro is not None:
        widget._navepro_area_cinza_claro = claro
    # Campos arredondados desenham um Entry interno por cima: ele precisa
    # acompanhar a mesma cor, senão o miolo do campo fica com outra cor no
    # tema claro (o frame vira cinza e o Entry interno permanece).
    interno = getattr(widget, '_entry', None)
    if interno is not None:
        interno._navepro_area_cinza_clara = True
        interno._navepro_area_cinza_escuro = escuro
        if claro is not None:
            interno._navepro_area_cinza_claro = claro
    return widget
