"""Atalhos globais do painel e janela de dicas (mixin).

Concentra os atalhos de teclado da janela principal e a janelinha de ajuda
que aparece no arranque. O usuário pode marcar "não exibir mais" e reabrir a
qualquer momento pelo menu Visualizar > Ver Atalhos do Sistema.
"""

from __future__ import annotations

import json
import tkinter as tk

from navepro.core.log import get_logger
from navepro.core.paths import CONFIG_FILE
from navepro.core.util_tk import _centralizar_sobre
from navepro.core.widgets_arredondados import TkArredondado

log = get_logger("atalhos")

# Botões e campos desenham cantos arredondados (fachada do tkinter).
tk = TkArredondado(tk)

# Chave no config.json: True/missing = mostra as dicas no arranque.
CHAVE_DICAS = "dicas_atalhos"

# Seções exibidas na janelinha: (título, ((combinação, descrição), ...)).
SECOES_ATALHOS = (
    ("Atalhos do sistema", (
        ("Ctrl+B", "Bíblia"),
        ("Ctrl+L", "Ordem de Projeção"),
        ("Ctrl+A", "Anúncios"),
        ("Ctrl+S", "Sorteio Profissional"),
        ("Ctrl+G", "Gerenciar Banco"),
        ("Ctrl+F", "Configurações"),
        ("Ctrl+T", "Alternar tema claro/escuro"),
        ("F11", "Alternar tela cheia"),
        ("Espaço", "Reproduzir/Pausar (na projeção: próximo slide)"),
    )),
    ("Durante a projeção em slides", (
        ("→ / ↓ / Page Down / F5", "Próximo slide"),
        ("← / ↑ / Page Up / Backspace", "Slide anterior"),
    )),
)

# Tecla (minúscula) -> método da AppInterface que ela abre.
_ACOES = {
    "b": "janela_biblia",
    "l": "janela_ordem_servico",
    "a": "janela_anuncios",
    "s": "abrir_sorteio",
    "g": "abrir_gerenciador",
    "f": "abrir_config_relogio_dialogo",
}


def deve_mostrar_dicas(config_data: dict | None) -> bool:
    """True se a janelinha de dicas deve abrir no arranque (padrão: sim)."""
    if not isinstance(config_data, dict):
        return True
    return config_data.get(CHAVE_DICAS, True) is not False


class AtalhosMixin:
    def _registrar_atalhos(self) -> None:
        """Liga os atalhos globais na janela principal.

        O bind fica no ``root`` (e não em ``bind_all``) de propósito: assim
        as janelas auxiliares mantêm os atalhos próprios (ex.: Ctrl+F da
        Bíblia em grade, Ctrl+T do Sorteio) sem disparar dois comandos.
        """
        for tecla, metodo in _ACOES.items():
            acao = getattr(self, metodo, None)
            if not callable(acao):
                continue
            for sequencia in (f"<Control-{tecla}>",
                              f"<Control-{tecla.upper()}>"):
                try:
                    self.root.bind(sequencia, self._atalho_para(acao))
                except tk.TclError:
                    pass

    @staticmethod
    def _atalho_para(acao):
        def _executar(event: object = None) -> str:
            acao()
            return "break"
        return _executar

    def _dicas_atalhos_ativas(self) -> bool:
        return deve_mostrar_dicas(getattr(self, "config_data", None))

    def _mostrar_dicas_atalhos_iniciais(self) -> None:
        """Abre as dicas no arranque, salvo se o usuário desativou."""
        if getattr(self, "_shutting_down", False):
            return
        if not self._dicas_atalhos_ativas():
            return
        self.abrir_dicas_atalhos()

    def _salvar_preferencia_dicas(self, mostrar: bool) -> None:
        """Persiste no config se as dicas devem abrir no próximo arranque."""
        config = getattr(self, "config_data", None)
        if not isinstance(config, dict):
            return
        config[CHAVE_DICAS] = bool(mostrar)
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as arquivo:
                json.dump(config, arquivo, indent=2, ensure_ascii=False)
        except Exception as e:
            log.exception(f"Erro ao salvar as dicas de atalhos: {e}")

    def abrir_dicas_atalhos(self) -> None:
        """Abre (ou traz para frente) a janelinha com os atalhos do sistema."""
        aberta = getattr(self, "_janela_atalhos", None)
        if aberta is not None:
            try:
                if aberta.winfo_exists():
                    aberta.deiconify()
                    aberta.lift()
                    aberta.focus_force()
                    return
            except tk.TclError:
                pass
        self._janela_atalhos = None

        janela = tk.Toplevel(self.root)
        janela.title("⌨️ Atalhos do Sistema")
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        janela.resizable(False, False)

        # A variável precisa de referência viva (collector apagaria a
        # variável Tcl e o checkbutton apareceria vazio).
        var_nao_exibir = tk.BooleanVar(
            value=not self._dicas_atalhos_ativas())
        janela._navepro_var_nao_exibir = var_nao_exibir

        main = tk.Frame(janela, bg='#0d1117')
        main.pack(fill='both', expand=True, padx=18, pady=16)

        tk.Label(main, text="⌨️ Atalhos do Sistema",
                 font=("Arial", 16, "bold"), fg='#f0c040', bg='#0d1117'
                 ).pack(pady=(0, 4))
        tk.Label(main,
                 text="Use estas combinações na janela principal do NavePro.",
                 font=("Arial", 10), fg='#8b949e', bg='#0d1117'
                 ).pack(pady=(0, 8))

        for titulo_secao, itens in SECOES_ATALHOS:
            tk.Label(main, text=titulo_secao, font=("Arial", 11, "bold"),
                     fg='#c9d1d9', bg='#0d1117', anchor='w'
                     ).pack(fill='x', pady=(10, 4))
            cartao = tk.Frame(main, bg='#161b22')
            cartao.pack(fill='x')
            for linha, (combinacao, descricao) in enumerate(itens):
                tk.Label(cartao, text=combinacao, font=("Arial", 10, "bold"),
                         fg='#f0c040', bg='#21262d', padx=10, pady=4,
                         anchor='w'
                         ).grid(row=linha, column=0, sticky='w',
                                padx=(12, 12), pady=4)
                tk.Label(cartao, text=descricao, font=("Arial", 11),
                         fg='#c9d1d9', bg='#161b22', anchor='w'
                         ).grid(row=linha, column=1, sticky='w',
                                padx=(0, 14), pady=4)
            cartao.columnconfigure(1, weight=1)

        check = tk.Checkbutton(
            main, text="Não exibir estas dicas ao iniciar",
            variable=var_nao_exibir,
            font=("Arial", 10), fg='#c9d1d9', bg='#0d1117',
            activeforeground='#f0c040', activebackground='#0d1117',
            selectcolor='#21262d', bd=0, highlightthickness=0,
            anchor='w', cursor='hand2')
        check.pack(anchor='w', pady=(14, 6))

        def _ao_alternar(*_args) -> None:
            self._salvar_preferencia_dicas(not var_nao_exibir.get())

        var_nao_exibir.trace_add("write", _ao_alternar)

        def _fechar() -> None:
            self._janela_atalhos = None
            try:
                janela.destroy()
            except tk.TclError:
                pass

        janela.protocol("WM_DELETE_WINDOW", _fechar)

        tk.Button(main, text="Fechar", command=_fechar,
                  bg='#6e40c9', fg='#f0c040', activebackground='#8957e5',
                  activeforeground='#f0c040', font=("Arial", 11, "bold"),
                  bd=0, highlightthickness=0, padx=18, pady=6,
                  cursor='hand2').pack(pady=(4, 0))

        self._janela_atalhos = janela
        _centralizar_sobre(janela, self.root,
                           area=self._area_monitor_operador())

        def _trazer_para_frente() -> None:
            # Roda depois do after(0) do ToplevelTematico (tema claro), que
            # deiconifica a janela oculta durante a montagem.
            try:
                janela.deiconify()
                janela.lift()
                janela.focus_force()
            except tk.TclError:
                pass

        try:
            janela.after(0, _trazer_para_frente)
        except tk.TclError:
            pass
