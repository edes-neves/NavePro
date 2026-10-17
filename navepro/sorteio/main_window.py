import tkinter as tk
import webbrowser
from collections.abc import Callable

from . import APP_DEVELOPER, APP_LICENSE, APP_VERSION, APP_YEAR, ctk
from .font_manager import ui_font
from .history_manager import HistoryManager
from .lottery_engine import LotteryEngine
from .settings_manager import SettingsManager
from .sound_manager import SoundManager
from .theme_manager import ThemeManager
from .updater import SUPPORT_EMAIL
from .validator import ValidationError, Validator


class MainWindow:

    def __init__(
        self,
        master: ctk.CTk,
        theme: ThemeManager,
        settings: SettingsManager,
        engine: LotteryEngine,
        history: HistoryManager,
        sound: SoundManager,
        on_start_draw: Callable | None = None,
        on_new_draw: Callable | None = None,
        on_reset: Callable | None = None,
        on_clear: Callable | None = None,
        on_settings: Callable | None = None,
        on_export: Callable | None = None,
        on_telao: Callable | None = None,
        on_fullscreen: Callable | None = None,
        on_quit: Callable | None = None,
        on_toggle_theme: Callable | None = None,
        on_toggle_minimize: Callable | None = None,
    ) -> None:
        self._master = master
        self._theme = theme
        self._settings = settings
        self._engine = engine
        self._history = history
        self._sound = sound
        self._validator = Validator()

        self._on_start_draw = on_start_draw
        self._on_new_draw = on_new_draw
        self._on_reset = on_reset
        self._on_clear = on_clear
        self._on_settings = on_settings
        self._on_export = on_export
        self._on_telao = on_telao
        self._on_fullscreen = on_fullscreen
        self._on_quit = on_quit
        self._on_toggle_theme = on_toggle_theme
        self._on_toggle_minimize = on_toggle_minimize

        self._build_ui()

    def _card_style(self) -> dict:
        """Borda colorida sutil nos cartões de seção, APENAS no tema claro,
        para separar visualmente uma seção da outra. No tema escuro nenhuma
        borda é adicionada (look atual mantido)."""
        if self._theme.theme_name == "light":
            return {
                "border_width": 1,
                "border_color": self._theme.c("border"),
            }
        return {}

    def _accent_bar(self, parent: ctk.CTkFrame, token: str, top: bool = False) -> None:
        """Barra colorida no cartão de seção (tema claro).

        Cada seção ganha uma cor vibrante própria no topo e na base do
        cartão, separando-a das demais. No tema escuro a barra assume a cor
        do cartão, ficando invisível (nenhuma mudança no modo escuro)."""
        color = (
            self._theme.c(token)
            if self._theme.theme_name == "light"
            else self._theme.c("bg_card")
        )
        bar = ctk.CTkFrame(
            parent,
            height=4,
            corner_radius=2,
            fg_color=color,
        )
        bar.place(
            relx=0,
            rely=0.0 if top else 1.0,
            anchor="nw" if top else "sw",
            relwidth=1.0,
        )
        self._accent_bars.append((bar, token))

    def _section_accent(self, token: str) -> str:
        """Cor vibrante da seção (tema claro); no escuro mantém o primary
        de sempre."""
        if self._theme.theme_name == "light":
            return self._theme.c(token)
        return self._theme.c("primary")

    def _track_btn(self, btn: ctk.CTkButton, fg_token: str, hover_token: str) -> None:
        """Registra um botão dinâmico para atualização no refresh_theme."""
        btn._fg_token = fg_token
        btn._hover_token = hover_token
        btn.configure(
            fg_color=self._theme.c(fg_token),
            hover_color=self._theme.c(hover_token),
            text_color=self._theme.c("btn_text"),
        )
        self._dynamic_buttons.append((btn, fg_token, hover_token))

    def _set_btn_theme(
        self, btn: ctk.CTkButton, fg_token: str, hover_token: str | None = None
    ) -> None:
        """Altera tokens de um botão já registrado."""
        hover_token = hover_token or getattr(btn, "_hover_token", "btn_primary_hover")
        btn._fg_token = fg_token
        btn._hover_token = hover_token
        btn.configure(
            fg_color=self._theme.c(fg_token),
            hover_color=self._theme.c(hover_token),
            text_color=self._theme.c("btn_text"),
        )

    def _build_ui(self) -> None:
        self._master.title(f"Sorteio Profissional v{APP_VERSION} - Operador")
        self._master.configure(fg_color=self._theme.c("bg"))

        self._container = ctk.CTkFrame(
            self._master,
            fg_color=self._theme.c("bg"),
        )
        self._container.pack(fill="both", expand=True, padx=20, pady=20)
        self._section_cards: list[ctk.CTkFrame] = []
        self._accent_bars: list[tuple[ctk.CTkFrame, str]] = []
        self._section_labels: list[tuple[ctk.CTkLabel, str]] = []
        self._dynamic_buttons: list[tuple[ctk.CTkButton, str, str]] = []

        self._build_header()
        self._build_status_frame()
        self._build_body()

        self._fit_window_to_content()

    def _build_body(self) -> None:
        body = ctk.CTkFrame(
            self._container,
            fg_color="transparent",
        )
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure((0, 1, 2, 3), weight=1)
        body.grid_rowconfigure(0, weight=0)
        body.grid_rowconfigure(1, weight=1)
        self._body = body

        self._build_sorteio_frame()
        self._build_buttons()
        self._build_history()

    def _fit_window_to_content(self) -> None:
        """Grows the window when taller/wider fonts make the layout overflow,
        keeping it fully inside the screen (all items stay visible)."""
        self._master.update_idletasks()
        win_w = self._master.winfo_width()
        win_h = self._master.winfo_height()
        need_w = self._container.winfo_reqwidth() + 65
        need_h = self._container.winfo_reqheight() + 65
        max_w = self._master.winfo_screenwidth() - 80
        max_h = self._master.winfo_screenheight() - 130
        target_w = min(max(win_w, need_w), max_w)
        target_h = min(max(win_h, need_h), max_h)
        if target_w <= win_w and target_h <= win_h:
            return
        x, y = self._master.winfo_x(), self._master.winfo_y()
        if x + target_w > self._master.winfo_screenwidth():
            x = max(self._master.winfo_screenwidth() - target_w - 10, 0)
        if y + target_h > self._master.winfo_screenheight():
            y = max(self._master.winfo_screenheight() - target_h - 10, 0)
        self._master.geometry(f"{target_w}x{target_h}+{x}+{y}")

    def _build_header(self) -> None:
        header = ctk.CTkFrame(
            self._container,
            fg_color=self._theme.c("bg_card"),
            corner_radius=12,
            height=80,
            **self._card_style(),
        )
        self._section_cards.append(header)
        self._accent_bar(header, "primary")
        header.pack(fill="x", pady=(0, 20))
        header.pack_propagate(False)

        title = ctk.CTkLabel(
            header,
            text="SORTEIO PROFISSIONAL",
            font=(ui_font(), 28, "bold"),
            text_color=self._section_accent("primary"),
        )
        title.place(relx=0.5, rely=0.5, anchor="center")
        self._section_labels.append((title, "primary"))
        self._accent_bar(header, "primary", top=True)

    def _build_sorteio_frame(self) -> None:
        frame = ctk.CTkFrame(
            self._body,
            fg_color=self._theme.c("bg_card"),
            corner_radius=12,
            **self._card_style(),
        )
        frame.grid(
            row=0, column=0, columnspan=2,
            sticky="nsew", padx=(0, 15), pady=(0, 15),
        )
        self._section_cards.append(frame)
        self._accent_bar(frame, "secondary")

        title = ctk.CTkLabel(
            frame,
            text="Configuração do Sorteio",
            font=(ui_font(), 18, "bold"),
            text_color=self._section_accent("secondary"),
        )
        title.pack(anchor="w", padx=20, pady=(15, 5))
        self._section_labels.append((title, "secondary"))
        self._accent_bar(frame, "secondary", top=True)

        self._mode = "numbers"
        mode_sel = ctk.CTkSegmentedButton(
            frame,
            values=["Números", "Nomes"],
            command=self._on_mode_change,
            font=(ui_font(), 16, "bold"),
        )
        mode_sel.set("Números")
        mode_sel.pack(anchor="w", padx=20, pady=(0, 10))
        self._mode_sel = mode_sel

        # ── Números panel ──
        self._numbers_panel = ctk.CTkFrame(frame, fg_color="transparent")
        self._numbers_panel.pack(fill="x", padx=20, pady=(0, 5))
        self._build_numbers_inputs(self._numbers_panel)

        # ── Nomes panel ──
        self._names_panel = ctk.CTkFrame(frame, fg_color="transparent")
        self._build_names_inputs(self._names_panel)

        self._error_label = ctk.CTkLabel(
            frame,
            text="",
            font=(ui_font(), 15),
            text_color=self._theme.c("error"),
        )
        self._error_label.pack(anchor="w", padx=20, pady=(0, 10))

    def _build_numbers_inputs(self, inputs: ctk.CTkFrame) -> None:
        self._entry_start = ctk.CTkEntry(
            inputs,
            width=200,
            height=38,
            font=(ui_font(), 18),
            placeholder_text="Ex: 1",
        )
        self._entry_start.grid(row=0, column=1, sticky="w", padx=(0, 20), pady=5)

        ctk.CTkLabel(
            inputs,
            text="Número Inicial:",
            font=(ui_font(), 16, "bold"),
            text_color=self._theme.c("text_secondary"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 5), pady=5)

        ctk.CTkLabel(
            inputs,
            text="Número Final:",
            font=(ui_font(), 16, "bold"),
            text_color=self._theme.c("text_secondary"),
        ).grid(row=1, column=0, sticky="w", padx=(0, 5), pady=5)

        self._entry_end = ctk.CTkEntry(
            inputs,
            width=200,
            height=38,
            font=(ui_font(), 18),
            placeholder_text="Ex: 1000",
        )
        self._entry_end.grid(row=1, column=1, sticky="w", padx=(0, 20), pady=5)

        inputs.grid_columnconfigure(1, weight=1)

        count_frame = ctk.CTkFrame(inputs, fg_color="transparent")
        count_frame.grid(row=2, column=0, columnspan=2, sticky="w", padx=0, pady=(5, 0))

        ctk.CTkLabel(
            count_frame,
            text="Números por vez:",
            font=(ui_font(), 16, "bold"),
            text_color=self._theme.c("text_secondary"),
        ).pack(side="left")

        self._count_vars: list[tuple[tk.BooleanVar, int]] = []
        for n in (2, 3, 4, 5):
            var = tk.BooleanVar(master=self._master, value=False)
            ctk.CTkCheckBox(
                count_frame,
                text=str(n),
                variable=var,
                font=(ui_font(), 16, "bold"),
                width=48,
                checkbox_width=18,
                checkbox_height=18,
                command=lambda v=var: self._on_count_toggle(v),
            ).pack(side="left", padx=(8, 0))
            self._count_vars.append((var, n))

        ctk.CTkLabel(
            inputs,
            text="Sem seleção, o sorteio gera 1 número por vez.",
            font=(ui_font(), 16, "bold"),
            text_color=self._theme.c("text_secondary"),
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=0, pady=(0, 5))

    def _build_names_inputs(self, panel: ctk.CTkFrame) -> None:
        tip = ctk.CTkLabel(
            panel,
            text="Digite um nome por linha ou importe um arquivo.",
            font=(ui_font(), 16, "bold"),
            text_color=self._theme.c("text_secondary"),
        )
        tip.pack(anchor="w", padx=0, pady=(0, 5))

        self._names_import_btn = ctk.CTkButton(
            panel,
            text="Importar Arquivo (.csv .doc .docx .pdf)",
            command=self._on_import_names,
            height=54,
            font=(ui_font(), 16, "bold"),
            corner_radius=8,
        )
        self._names_import_btn.pack(anchor="w", padx=0, pady=(0, 6))
        self._track_btn(self._names_import_btn, "btn_primary", "btn_primary_hover")

        self._names_text = ctk.CTkTextbox(
            panel,
            width=40,
            height=90,
            font=(ui_font(), 17, "bold"),
            fg_color=self._theme.c("input_bg"),
            text_color=self._theme.c("text"),
            border_width=1,
            border_color=self._theme.c("input_border"),
            corner_radius=8,
        )
        self._names_text.pack(fill="x", padx=0, pady=(0, 5))
        self._names_text.bind("<KeyRelease>", self._on_names_text_changed)

        self._names_info = ctk.CTkLabel(
            panel,
            text="Nomes cadastrados: 0",
            font=(ui_font(), 15, "bold"),
            text_color=self._theme.c("success"),
        )
        self._names_info.pack(anchor="w", padx=0, pady=(0, 5))

        names_count_frame = ctk.CTkFrame(panel, fg_color="transparent")
        names_count_frame.pack(anchor="w", padx=0, pady=(5, 0))

        ctk.CTkLabel(
            names_count_frame,
            text="Nomes por vez:",
            font=(ui_font(), 16, "bold"),
            text_color=self._theme.c("text_secondary"),
        ).pack(side="left")

        self._names_count_vars: list[tuple[tk.BooleanVar, int]] = []
        for n in (2, 3, 4, 5):
            var = tk.BooleanVar(master=self._master, value=False)
            ctk.CTkCheckBox(
                names_count_frame,
                text=str(n),
                variable=var,
                font=(ui_font(), 16, "bold"),
                width=48,
                checkbox_width=18,
                checkbox_height=18,
                command=lambda v=var: self._on_names_count_toggle(v),
            ).pack(side="left", padx=(8, 0))
            self._names_count_vars.append((var, n))

        ctk.CTkLabel(
            panel,
            text="Sem seleção, o sorteio gera 1 nome por vez.",
            font=(ui_font(), 16, "bold"),
            text_color=self._theme.c("text_secondary"),
        ).pack(anchor="w", padx=0, pady=(0, 5))

    def _on_mode_change(self, value: str) -> None:
        self._mode = "names" if value == "Nomes" else "numbers"
        if self._mode == "names":
            self._numbers_panel.pack_forget()
            self._names_panel.pack(fill="x", padx=20, pady=(0, 5))
            total = len(self._names_from_input())
            self._names_info.configure(text=f"Nomes cadastrados: {total}")
        else:
            self._names_panel.pack_forget()
            self._numbers_panel.pack(fill="x", padx=20, pady=(0, 5))
        self._error_label.configure(text="")
        self._fit_window_to_content()

    def _names_from_input(self) -> list[str]:
        raw = self._names_text.get("1.0", "end")
        names: list[str] = []
        for line in raw.splitlines():
            for piece in line.split(","):
                name = piece.strip()
                if name and name not in names:
                    names.append(name)
        return names

    # ── Configuração programática (controle remoto pelo celular) ──
    def configurar_numeros(self, inicio: int, fim: int, por_vez: int = 1) -> None:
        """Configura o sorteio por faixa de números.

        Reinicia o sorteio (zera os já sorteados) para que a nova faixa valha
        na próxima vez, devolvendo o telão ao estado de espera — sem recriar a
        janela pública (o que faria o telão piscar durante o culto).
        """
        self._reiniciar_para_config()
        self._on_mode_change("Números")
        self._entry_start.delete(0, "end")
        self._entry_start.insert(0, str(inicio))
        self._entry_end.delete(0, "end")
        self._entry_end.insert(0, str(fim))
        self._aplicar_por_vez(self._count_vars, por_vez)
        # Já configura o motor para o celular ver a faixa (o "Sortear"
        # reconfigura igual antes de sortear, então não há perda).
        self._engine.configure(int(inicio), int(fim))
        self._update_status()

    def configurar_nomes(self, nomes: list, por_vez: int = 1) -> None:
        """Configura o sorteio por lista de nomes (um por linha)."""
        nomes = [str(n) for n in nomes]
        self._reiniciar_para_config()
        self._on_mode_change("Nomes")
        self._names_text.delete("1.0", "end")
        self._names_text.insert("1.0", "\n".join(nomes))
        self._stored_names = list(nomes)
        self._names_info.configure(text=f"Nomes cadastrados: {len(nomes)}")
        self._aplicar_por_vez(self._names_count_vars, por_vez)
        self._engine.configure_names(nomes)
        self._update_status()

    def _aplicar_por_vez(self, vars_: list, por_vez: int) -> None:
        """Marca só a caixinha 'por vez' escolhida (as demais, desmarcadas)."""
        for var, valor in vars_:
            var.set(valor == por_vez)

    def _reiniciar_para_config(self) -> None:
        """Zera o sorteio para aplicar uma nova configuração (telão → espera)."""
        self._engine.reset()
        self._history.clear()
        self._error_label.configure(text="")
        self._update_status()
        self._update_history_display()
        self._draw_state = "start"
        self._btn_iniciar.configure(text="Iniciar Sorteio")
        self._set_btn_theme(self._btn_iniciar, "btn_primary", "btn_primary_hover")
        if self._on_clear:
            self._on_clear()

    def _on_import_names(self) -> None:
        import os as _os

        from .name_importer import SUPPORTED_EXTS, NameImportError, import_names

        dialog = ctk.CTkToplevel(self._master)
        dialog.title("Importar Lista de Nomes")
        dialog.configure(fg_color=self._theme.c("bg"))
        dialog.resizable(False, False)
        dialog.grab_set()

        dialog.geometry(
            f"640x480+{self._master.winfo_x() + 100}+{self._master.winfo_y() + 100}"
        )

        current_dir = [_os.path.expanduser("~")]
        pending = [None]

        ctk.CTkLabel(
            dialog,
            text="Selecione um arquivo (.csv, .doc, .docx, .pdf)",
            font=(ui_font(), 20, "bold"),
            text_color=self._theme.c("primary"),
        ).pack(anchor="w", padx=15, pady=(15, 5))

        path_bar = ctk.CTkFrame(dialog, fg_color="transparent")
        path_bar.pack(fill="x", padx=15, pady=5)

        def go_home() -> None:
            current_dir[0] = _os.path.expanduser("~")
            refresh()

        def go_up() -> None:
            parent = _os.path.dirname(current_dir[0])
            if _os.path.isdir(parent):
                current_dir[0] = parent
                refresh()

        ctk.CTkButton(
            path_bar,
            text="Início",
            width=70, height=28,
            font=(ui_font(), 11),
            fg_color=self._theme.c("btn_primary"),
            text_color=self._theme.c("btn_text"),
            command=go_home,
        ).pack(side="left", padx=(0, 5))

        ctk.CTkButton(
            path_bar,
            text="Subir",
            width=70, height=28,
            font=(ui_font(), 11),
            fg_color=self._theme.c("btn_neutral"),
            text_color=self._theme.c("btn_text"),
            command=go_up,
        ).pack(side="left")

        path_lbl = ctk.CTkLabel(
            path_bar,
            text="",
            font=(ui_font(), 11),
            text_color=self._theme.c("text_secondary"),
            anchor="w",
        )
        path_lbl.pack(side="left", fill="x", expand=True, padx=(10, 0))

        list_frame = ctk.CTkScrollableFrame(
            dialog,
            fg_color=self._theme.c("bg_card"),
            corner_radius=8,
        )
        list_frame.pack(fill="both", expand=True, padx=15, pady=5)

        def open_folder(name: str) -> None:
            current_dir[0] = _os.path.join(current_dir[0], name)
            refresh()

        def pick_file(name: str) -> None:
            pending[0] = _os.path.join(current_dir[0], name)

        def refresh() -> None:
            for widget in list_frame.winfo_children():
                widget.destroy()

            def bind_row(row, single_handler, double_handler) -> None:
                row.bind("<Button-1>", lambda e: single_handler())
                row.bind("<Double-Button-1>", lambda e: double_handler())
                for child in row.winfo_children():
                    child.bind("<Button-1>", lambda e: single_handler())
                    child.bind("<Double-Button-1>", lambda e: double_handler())

            path = current_dir[0]
            path_lbl.configure(text=path)

            try:
                entries = sorted(_os.listdir(path))
            except OSError as e:
                ctk.CTkLabel(
                    list_frame,
                    text=f"Não foi possível abrir a pasta:\n{e}",
                    font=(ui_font(), 12),
                    text_color=self._theme.c("error"),
                ).pack(pady=10)
                return

            folders = [
                name for name in entries
                if not name.startswith(".")
                and _os.path.isdir(_os.path.join(path, name))
            ]
            files = [
                name for name in entries
                if not name.startswith(".")
                and _os.path.isfile(_os.path.join(path, name))
                and name.lower().endswith(SUPPORTED_EXTS)
            ]

            for folder in folders:
                row = ctk.CTkFrame(list_frame, fg_color="transparent")
                row.pack(fill="x", padx=2, pady=1)
                ctk.CTkLabel(
                    row,
                    text=f"  {folder}/",
                    font=(ui_font(), 12),
                    text_color=self._theme.c("text"),
                    anchor="w",
                ).pack(side="left", fill="x", expand=True)
                ctk.CTkLabel(
                    row,
                    text="Pasta",
                    font=(ui_font(), 10),
                    text_color=self._theme.c("text_secondary"),
                ).pack(side="right")
                bind_row(
                    row,
                    lambda n=folder: open_folder(n),
                    lambda n=folder: open_folder(n),
                )

            for file in files:
                row = ctk.CTkFrame(list_frame, fg_color="transparent")
                row.pack(fill="x", padx=2, pady=1)
                ctk.CTkLabel(
                    row,
                    text=f"  {file}",
                    font=(ui_font(), 12),
                    text_color=self._theme.c("text"),
                    anchor="w",
                ).pack(side="left", fill="x", expand=True)
                ctk.CTkLabel(
                    row,
                    text="Arquivo",
                    font=(ui_font(), 10),
                    text_color=self._theme.c("text_secondary"),
                ).pack(side="right")
                bind_row(
                    row,
                    lambda n=file: _confirm_import(n),
                    lambda n=file: _confirm_import(n),
                )

            if not folders and not files:
                ctk.CTkLabel(
                    list_frame,
                    text="Nenhuma pasta ou arquivo visível aqui.",
                    font=(ui_font(), 12),
                    text_color=self._theme.c("text_secondary"),
                ).pack(pady=10)

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(fill="x", padx=15, pady=(5, 15))

        def _do_import(filepath: str) -> None:
            dialog.destroy()
            try:
                names = import_names(filepath)
            except NameImportError as e:
                self._error_label.configure(text=str(e))
                self._sound.play("error")
                return

            current = self._names_text.get("1.0", "end").strip()
            existing = set(n.strip().lower() for n in current.splitlines() if n.strip())
            new_names = [n for n in names if n.lower() not in existing]

            if current:
                self._names_text.insert("end", "\n" + "\n".join(new_names))
            else:
                self._names_text.insert("1.0", "\n".join(new_names))

            self._names_info.configure(
                text=f"Nomes cadastrados: {len(self._names_from_input())}"
            )

        def _confirm_import(name: str) -> None:
            pending[0] = _os.path.join(current_dir[0], name)
            _do_import(pending[0])

        ctk.CTkButton(
            btn_row,
            text="Cancelar",
            width=120, height=36,
            font=(ui_font(), 12),
            fg_color=self._theme.c("btn_neutral"),
            text_color=self._theme.c("btn_text"),
            command=dialog.destroy,
        ).pack(side="right")

        refresh()

    def _on_names_text_changed(self, event=None) -> None:
        total = len(self._names_from_input())
        self._names_info.configure(text=f"Nomes cadastrados: {total}")

    def _build_status_frame(self) -> None:
        frame = ctk.CTkFrame(
            self._container,
            fg_color=self._theme.c("bg_card"),
            corner_radius=12,
            height=72,
            **self._card_style(),
        )
        frame.pack(fill="x", pady=(0, 15))
        frame.pack_propagate(False)
        self._section_cards.append(frame)
        self._accent_bar(frame, "accent")

        stats = [
            ("Sorteados", "0", "_lbl_sorted"),
            ("Restantes", "0", "_lbl_remaining"),
            ("Sorteio #", "0", "_lbl_current"),
            ("Total", "0", "_lbl_total"),
        ]

        for label, value, attr in stats:
            col = ctk.CTkFrame(frame, fg_color="transparent")
            col.pack(side="left", expand=True, fill="both")

            ctk.CTkLabel(
                col,
                text=label,
                font=(ui_font(), 11),
                text_color=self._theme.c("text_secondary"),
            ).pack(pady=(10, 2))

            lbl = ctk.CTkLabel(
                col,
                text=value,
                font=(ui_font(), 18, "bold"),
                text_color=self._section_accent("accent"),
            )
            lbl.pack()
            setattr(self, attr, lbl)
            self._section_labels.append((lbl, "accent"))

        self._accent_bar(frame, "accent", top=True)

    def _build_buttons(self) -> None:
        grid = ctk.CTkFrame(
            self._body,
            fg_color="transparent",
        )
        grid.grid(
            row=1, column=0, columnspan=2,
            sticky="nsew", padx=(0, 15), pady=(0, 15),
        )

        self._draw_state = "start"
        self._clear_state = "clear"

        self._btn_iniciar = ctk.CTkButton(
            grid,
            text="Iniciar Sorteio",
            command=self._on_draw_toggle,
            width=160,
            height=42,
            font=(ui_font(), 15, "bold"),
            corner_radius=8,
        )
        self._btn_iniciar.grid(row=0, column=0, padx=4, pady=4, sticky="ew")
        self._track_btn(self._btn_iniciar, "btn_primary", "btn_primary_hover")

        self._btn_limpar = ctk.CTkButton(
            grid,
            text="Limpar Sorteios",
            command=self._on_clear_toggle,
            width=160,
            height=42,
            font=(ui_font(), 15, "bold"),
            corner_radius=8,
        )
        self._btn_limpar.grid(row=1, column=0, padx=4, pady=4, sticky="ew")
        self._track_btn(self._btn_limpar, "btn_warning", "btn_warning_hover")

        self._sound_var = tk.BooleanVar(
            master=self._master,
            value=bool(self._settings.get("sound", "enabled")),
        )
        sound_btn = ctk.CTkButton(
            grid,
            text="Som: Ligado" if self._sound_var.get() else "Som: Desligado",
            command=self._on_sound_toggle,
            width=130,
            height=38,
            font=(ui_font(), 15, "bold"),
            corner_radius=8,
        )
        sound_btn.grid(row=0, column=1, padx=4, pady=4, sticky="ew")
        self._btn_sound = sound_btn
        self._track_btn(
            sound_btn,
            "btn_success" if self._sound_var.get() else "btn_neutral",
            "btn_success_hover" if self._sound_var.get() else "btn_neutral_hover",
        )

        grid.grid_columnconfigure((0, 1), weight=1)

        self._btn_settings = ctk.CTkButton(
            grid,
            text="Configurações",
            command=self._on_settings_click,
            width=130,
            height=38,
            font=(ui_font(), 14, "bold"),
            corner_radius=8,
        )
        self._btn_settings.grid(row=1, column=1, padx=4, pady=4, sticky="ew")
        self._track_btn(self._btn_settings, "btn_neutral", "btn_neutral_hover")

        self._btn_export = ctk.CTkButton(
            grid,
            text="Exportar",
            command=self._on_export_click,
            width=130,
            height=38,
            font=(ui_font(), 14, "bold"),
            corner_radius=8,
        )
        self._btn_export.grid(row=2, column=0, padx=4, pady=4, sticky="ew")
        self._track_btn(self._btn_export, "btn_neutral", "btn_neutral_hover")

        self._btn_sair = ctk.CTkButton(
            grid,
            text="Sair",
            command=self._on_quit_click,
            width=130,
            height=38,
            font=(ui_font(), 14, "bold"),
            corner_radius=8,
        )
        self._btn_sair.grid(row=2, column=1, padx=4, pady=4, sticky="ew")
        self._track_btn(self._btn_sair, "btn_error", "btn_error_hover")

        self._btn_telao = ctk.CTkButton(
            grid,
            text="🖥️ Aparência do Telão",
            command=self._on_telao_click,
            height=38,
            font=(ui_font(), 14, "bold"),
            corner_radius=8,
        )
        self._btn_telao.grid(
            row=3, column=0, columnspan=2, padx=4, pady=4, sticky="ew"
        )
        self._track_btn(self._btn_telao, "btn_neutral", "btn_neutral_hover")

    def _build_history(self) -> None:
        frame = ctk.CTkFrame(
            self._body,
            fg_color=self._theme.c("bg_card"),
            corner_radius=12,
            **self._card_style(),
        )
        frame.grid(
            row=0, column=2, rowspan=2, columnspan=2,
            sticky="nsew",
        )
        self._section_cards.append(frame)
        self._accent_bar(frame, "success")

        title = ctk.CTkLabel(
            frame,
            text="Histórico de Sorteios",
            font=(ui_font(), 14, "bold"),
            text_color=self._section_accent("success"),
        )
        title.pack(anchor="w", padx=20, pady=(12, 8))
        self._section_labels.append((title, "success"))
        self._accent_bar(frame, "success", top=True)

        self._history_text = ctk.CTkTextbox(
            frame,
            width=40,
            font=(ui_font(), 13, "bold"),
            fg_color=self._theme.c("input_bg"),
            text_color=self._theme.c("text"),
            border_width=1,
            border_color=self._theme.c("input_border"),
            corner_radius=8,
            height=180,
        )
        self._history_text.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        self._history_text.configure(state="disabled")

    def _on_draw_toggle(self) -> None:
        if self._draw_state == "start":
            self._on_start_click()
            if self._draw_state == "start":
                return
        else:
            self._on_new_click()

    def _on_clear_toggle(self) -> None:
        """Limpa e reinicia tudo em um único clique, sem confirmação."""
        self._engine.reset()
        self._history.clear()
        self._entry_start.delete(0, "end")
        self._entry_end.delete(0, "end")
        if self._mode == "names":
            self._names_text.delete("1.0", "end")
            self._stored_names = []
            self._names_info.configure(text="Nomes cadastrados: 0")
        self._error_label.configure(text="")
        self._update_status()
        self._update_history_display()
        self._btn_iniciar.configure(text="Iniciar Sorteio")
        self._set_btn_theme(self._btn_iniciar, "btn_primary", "btn_primary_hover")
        self._draw_state = "start"
        self._clear_state = "clear"
        self._btn_limpar.configure(text="Limpar Sorteios")
        self._sound.play("click")
        if self._on_reset:
            self._on_reset()

    # ── Event handlers ──

    def _on_sound_toggle(self) -> None:
        enabled = not self._sound_var.get()
        self._sound_var.set(enabled)
        self._sound.enabled = enabled
        self._settings.set("sound", "enabled", enabled)
        self._btn_sound.configure(
            text="Som: Ligado" if enabled else "Som: Desligado",
        )
        self._set_btn_theme(
            self._btn_sound,
            "btn_success" if enabled else "btn_error",
            "btn_success_hover" if enabled else "btn_error_hover",
        )
        if enabled:
            self._sound.play("click")

    def _on_count_toggle(self, var: tk.BooleanVar) -> None:
        """Keeps the count checkboxes mutually exclusive (radio behavior)."""
        if not var.get():
            return
        for v, _n in self._count_vars:
            if v is not var and v.get():
                v.set(False)

    def _numbers_per_draw(self) -> int:
        for var, n in self._count_vars:
            if var.get():
                return n
        return 1

    def _on_names_count_toggle(self, var: tk.BooleanVar) -> None:
        """Keeps the names count checkboxes mutually exclusive (radio)."""
        if not var.get():
            return
        for v, _n in self._names_count_vars:
            if v is not var and v.get():
                v.set(False)

    def _names_per_draw(self) -> int:
        for var, n in self._names_count_vars:
            if var.get():
                return n
        return 1

    def _draw_numbers(self, count: int) -> list[int]:
        """Draws up to `count` numbers, records them in the history and
        refreshes the UI. Returns the drawn numbers (empty when the raffle
        is over)."""
        numbers = self._engine.draw_many(count)
        if not numbers:
            self._error_label.configure(
                text=(
                    "Todas as pessoas já foram sorteadas."
                    if self._mode == "names"
                    else "Todos os números já foram sorteados."
                )
            )
            return []

        base = self._engine.drawn_count - len(numbers) + 1
        for i, number in enumerate(numbers):
            self._history.add_entry(base + i, number)
        self._update_status()
        self._update_history_display()
        self._sound.play("click")
        if self._mode == "names":
            self._clear_drawn_names()
            for name in numbers:
                self._remove_name(name)
                self._save_names_to_textbox()
            total = len(self._names_from_input())
            self._names_info.configure(text=f"Nomes cadastrados: {total}")
        return numbers

    def _on_start_names(self) -> None:
        names = self._names_from_input()
        if not names:
            self._error_label.configure(text="Adicione pelo menos um nome para o sorteio.")
            self._sound.play("error")
            return

        self._stored_names = list(names)
        self._engine.configure_names(names)
        self._update_status()
        self._fit_window_to_content()

        drawn = self._draw_numbers(self._names_per_draw())
        if drawn and self._on_start_draw:
            self._draw_state = "new"
            self._btn_iniciar.configure(text="Sortear Próximo")
            self._set_btn_theme(self._btn_iniciar, "btn_start", "btn_start_hover")
            self._on_start_draw(drawn)

    def _on_new_names(self) -> None:
        if self._engine.state == "completed":
            self._error_label.configure(
                text="Todos os nomes foram sorteados. Use 'Limpar Sorteios' para reiniciar."
            )
            self._draw_state = "start"
            self._btn_iniciar.configure(text="Iniciar Sorteio")
            self._set_btn_theme(self._btn_iniciar, "btn_primary", "btn_primary_hover")
            return

        if self._engine.state == "idle":
            self._error_label.configure(
                text="Adicione os nomes e clique em 'Iniciar Sorteio' primeiro."
            )
            return

        drawn = self._draw_numbers(self._names_per_draw())
        if drawn and self._on_start_draw:
            self._on_start_draw(drawn)
            return

        self._draw_state = "start"
        self._btn_iniciar.configure(text="Iniciar Sorteio")
        self._set_btn_theme(self._btn_iniciar, "btn_primary", "btn_primary_hover")
        if self._on_new_draw:
            self._on_new_draw()

    def _clear_drawn_names(self) -> None:
        if not getattr(self, "_stored_names", None):
            self._stored_names = self._names_from_input()

    def _remove_name(self, name: str) -> None:
        def matches(existing: str, target: str) -> bool:
            return (
                existing.casefold() == target.casefold()
                or existing.casefold().startswith(target.casefold())
            )

        target = str(name)
        remaining = [
            n for n in self._stored_names
            if not matches(n, target)
        ]
        if len(remaining) == len(self._stored_names):
            remaining = [n for n in self._names_from_input() if n.casefold() != target.casefold()]
        self._stored_names = remaining

    def _save_names_to_textbox(self) -> None:
        self._names_text.delete("1.0", "end")
        if self._stored_names:
            self._names_text.insert("1.0", "\n".join(self._stored_names))
        self._update_history_display()

    def _on_start_click(self) -> None:
        self._error_label.configure(text="")

        if self._mode == "names":
            self._on_start_names()
            return

        start_val = self._entry_start.get()
        end_val = self._entry_end.get()

        try:
            start, end = self._validator.validate_range(start_val, end_val)
        except ValidationError as e:
            self._error_label.configure(text=str(e))
            self._sound.play("error")
            return

        if self._engine.is_ready() or self._engine.state == "idle":
            self._engine.configure(start, end)
            self._update_status()

        if self._engine.state == "completed":
            self._error_label.configure(
                text="Todos os números já foram sorteados."
            )
            self._sound.play("error")
            return

        numbers = self._draw_numbers(self._numbers_per_draw())
        if numbers and self._on_start_draw:
            self._draw_state = "new"
            self._btn_iniciar.configure(text="Novo Sorteio")
            self._set_btn_theme(self._btn_iniciar, "btn_start", "btn_start_hover")
            self._on_start_draw(numbers)

    def _on_new_click(self) -> None:
        if self._mode == "names":
            self._on_new_names()
            return

        if self._engine.state == "completed":
            self._error_label.configure(
                text="Sorteio encerrado. Use 'Limpar Sorteios' para reiniciar."
            )
            self._draw_state = "start"
            self._btn_iniciar.configure(text="Iniciar Sorteio")
            self._set_btn_theme(self._btn_iniciar, "btn_primary", "btn_primary_hover")
            return

        if self._engine.state == "idle":
            self._error_label.configure(
                text="Configure o intervalo e clique em 'Iniciar Sorteio' primeiro."
            )
            return

        numbers = self._draw_numbers(self._numbers_per_draw())
        if numbers:
            if self._on_start_draw:
                self._on_start_draw(numbers)
            return

        self._draw_state = "start"
        self._btn_iniciar.configure(text="Iniciar Sorteio")
        self._set_btn_theme(self._btn_iniciar, "btn_primary", "btn_primary_hover")
        if self._on_new_draw:
            self._on_new_draw()

    def _on_clear_click(self) -> None:
        self._engine.reset()
        self._history.clear()
        self._error_label.configure(text="")
        self._update_status()
        self._update_history_display()
        self._sound.play("click")
        if self._on_clear:
            self._on_clear()

    def _on_reset_click(self) -> None:
        self._engine.reset()
        self._history.clear()
        self._entry_start.delete(0, "end")
        self._entry_end.delete(0, "end")
        if self._mode == "names":
            self._names_text.delete("1.0", "end")
            self._stored_names = []
            self._names_info.configure(text="Nomes cadastrados: 0")
        self._error_label.configure(text="")
        self._update_status()
        self._update_history_display()
        self._sound.play("click")
        if self._on_reset:
            self._on_reset()

    def _on_fullscreen_click(self) -> None:
        if self._on_fullscreen:
            self._on_fullscreen()

    def _on_minimize_click(self) -> None:
        if self._on_toggle_minimize:
            self._on_toggle_minimize()

    def _on_toggle_theme_click(self) -> None:
        if self._on_toggle_theme:
            self._on_toggle_theme()

    def _on_about_click(self) -> None:
        dialog = ctk.CTkToplevel(self._master)
        dialog.title("Sobre")
        dialog.configure(fg_color=self._theme.c("bg"))
        dialog.resizable(False, False)
        dialog.geometry(
            f"420x330+{self._master.winfo_x() + 180}+{self._master.winfo_y() + 160}"
        )
        dialog.grab_set()

        ctk.CTkLabel(
            dialog,
            text="SORTEIO PROFISSIONAL",
            font=(ui_font(), 22, "bold"),
            text_color=self._theme.c("primary"),
        ).pack(pady=(30, 5))

        ctk.CTkLabel(
            dialog,
            text="Sistema de sorteio profissional com animação em tela pública",
            font=(ui_font(), 12),
            text_color=self._theme.c("text_secondary"),
        ).pack(pady=(0, 20))

        info = [
            ("Versão", APP_VERSION),
            ("Desenvolvedor", APP_DEVELOPER),
            ("Ano de desenvolvimento", APP_YEAR),
            ("Licença", APP_LICENSE),
        ]

        for label, value in info:
            row = ctk.CTkFrame(dialog, fg_color="transparent")
            row.pack(fill="x", padx=40, pady=3)
            ctk.CTkLabel(
                row,
                text=label,
                font=(ui_font(), 12),
                text_color=self._theme.c("text_secondary"),
            ).pack(side="left")
            ctk.CTkLabel(
                row,
                text=value,
                font=(ui_font(), 12, "bold"),
                text_color=self._theme.c("text"),
            ).pack(side="right")

        ctk.CTkButton(
            dialog,
            text="OK",
            width=100,
            height=32,
            font=(ui_font(), 12, "bold"),
            fg_color=self._theme.c("btn_primary"),
            text_color=self._theme.c("btn_text"),
            command=dialog.destroy,
        ).pack(pady=(25, 20))

    def _on_support_email(self) -> None:
        subject = f"[Suporte] Sorteio Profissional v{APP_VERSION}".replace(" ", "%20")
        try:
            webbrowser.open(
                "mailto:" + SUPPORT_EMAIL + "?subject=" + subject
            )
        except Exception:
            dialog = ctk.CTkToplevel(self._master)
            dialog.title("Preciso de ajuda")
            dialog.configure(fg_color=self._theme.c("bg"))
            dialog.resizable(False, False)
            dialog.geometry(
                f"480x200+{self._master.winfo_x() + 100}+{self._master.winfo_y() + 180}"
            )
            dialog.grab_set()
            ctk.CTkLabel(
                dialog,
                text=f"Envie um email para:\n{SUPPORT_EMAIL}",
                font=(ui_font(), 13),
                text_color=self._theme.c("text"),
            ).pack(pady=(40, 20))
            ctk.CTkButton(
                dialog,
                text="OK",
                width=100,
                height=32,
                font=(ui_font(), 12, "bold"),
                fg_color=self._theme.c("btn_primary"),
                text_color=self._theme.c("btn_text"),
                command=dialog.destroy,
            ).pack()

    def _on_settings_click(self) -> None:
        if self._on_settings:
            self._on_settings()

    def _on_export_click(self) -> None:
        if self._on_export:
            self._on_export()

    def _on_telao_click(self) -> None:
        if self._on_telao:
            self._on_telao()

    def _on_quit_click(self) -> None:
        if self._on_quit:
            self._on_quit()

    # ── Public update methods ──

    def show_completed_message(self) -> None:
        self._error_label.configure(
            text=(
                "Todos os nomes foram sorteados!"
                if self._mode == "names"
                else "Todos os números foram sorteados!"
            ),
            text_color=self._theme.c("success"),
        )

    def refresh_theme(self) -> None:
        self._master.configure(fg_color=self._theme.c("bg"))
        self._container.configure(fg_color=self._theme.c("bg"))
        light = self._theme.theme_name == "light"
        for card in getattr(self, "_section_cards", []):
            card.configure(fg_color=self._theme.c("bg_card"))
            if light:
                card.configure(
                    border_width=1,
                    border_color=self._theme.c("border"),
                )
            else:
                card.configure(border_width=0)
        for bar, token in getattr(self, "_accent_bars", []):
            color = (
                self._theme.c(token)
                if self._theme.theme_name == "light"
                else self._theme.c("bg_card")
            )
            bar.configure(fg_color=color)
        for label, token in getattr(self, "_section_labels", []):
            label.configure(text_color=self._section_accent(token))
        for box in (
            getattr(self, "_names_text", None),
            getattr(self, "_history_text", None),
        ):
            if box is not None:
                box.configure(
                    fg_color=self._theme.c("input_bg"),
                    text_color=self._theme.c("text"),
                    border_color=self._theme.c("input_border"),
                )
        for btn, _fg_token, _hover_token in getattr(self, "_dynamic_buttons", []):
            btn.configure(
                fg_color=self._theme.c(btn._fg_token),
                hover_color=self._theme.c(btn._hover_token),
                text_color=self._theme.c("btn_text"),
            )

    def _update_status(self) -> None:
        self._lbl_sorted.configure(
            text=str(self._engine.drawn_count)
        )
        self._lbl_remaining.configure(
            text=str(self._engine.remaining)
        )
        self._lbl_current.configure(
            text=str(self._engine.current_draw_number)
        )
        self._lbl_total.configure(
            text=str(self._engine.total_numbers)
        )

    def _update_history_display(self) -> None:
        self._history_text.configure(state="normal")
        self._history_text.delete("1.0", "end")

        entries = self._history.entries
        if not entries:
            self._history_text.insert("end", "Nenhum sorteio realizado ainda.\n")

        for entry in entries:
            self._history_text.insert(
                "end",
                f"Sorteio #{entry['sorteio']}: {entry['numero']}\n",
            )

        self._history_text.see("end")
        self._history_text.configure(state="disabled")

    def set_public_minimized(self, minimized: bool) -> None:
        btn = getattr(self, "_btn_minimizar", None)
        if btn is not None:
            btn.configure(
                text="Restaurar Tela" if minimized else "Minimizar Tela"
            )
