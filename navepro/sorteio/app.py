import os
import re
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import colorchooser

from . import ctk
from .font_manager import is_using_fallback, ui_font
from .history_manager import HistoryManager
from .lottery_engine import LotteryEngine
from .main_window import MainWindow
from .monitor_manager import MonitorManager
from .public_window import PublicWindow
from .settings_manager import SettingsManager
from .sound_manager import SoundManager
from .splash_screen import SplashScreen
from .theme_manager import ThemeManager
from .updater import Updater


class App:

    def __init__(self) -> None:
        self._settings = SettingsManager()
        self._theme = ThemeManager(self._settings)
        self._engine = LotteryEngine()
        self._history = HistoryManager(
            self._settings.get("history", "save_path") or "exports"
        )
        self._sound = SoundManager()
        self._monitor_mgr = MonitorManager()

        self._root: ctk.CTk | None = None
        self._main_window: MainWindow | None = None
        self._public_window: PublicWindow | None = None
        self._telao_dialog: ctk.CTkToplevel | None = None
        self._icon_images: list[tk.PhotoImage] = []
        self._updater: Updater | None = None

        # Modo embutido (integrado ao NavePro): sem mainloop/splash/updater.
        self._embedded: bool = False
        self._on_close: Callable | None = None
        self._public_rect: tuple | None = None
        self._public_master = None

    def _load_window_icon(self) -> None:
        """Loads the app icon and sets it as the default for all windows.

        Multiple pre-scaled PNGs are provided so the window manager can pick
        the best size. (A single large icon, or images created with
        ``subsample``, are written as an empty ``_NET_WM_ICON`` on some X11
        setups.)
        """
        try:
            pacote = Path(__file__).resolve().parent
            assets = pacote / "assets"
            files = [assets / f"icone_{size}.png" for size in (16, 32, 48, 64, 128)]
            self._icon_images = []
            for path in files:
                if path.exists():
                    self._icon_images.append(tk.PhotoImage(file=str(path)))
            if self._icon_images:
                self._root.iconphoto(True, *self._icon_images)
        except Exception:
            self._icon_images = []

    def run(self) -> None:
        window_w, window_h = 900, 850
        self._root = ctk.CTk(className="SorteioProfissional")
        self._root.minsize(900, 850)
        self._root.configure(fg_color=self._theme.c("bg"))
        self._load_window_icon()

        if is_using_fallback():
            ctk.set_widget_scaling(1.5)
            ctk.set_window_scaling(1.2)

        primary = self._monitor_mgr.primary
        if primary is not None:
            x = primary.x + max((primary.width - window_w) // 2, 0)
            y = primary.y + max((primary.height - window_h) // 2, 0)
        else:
            sw = self._root.winfo_screenwidth()
            sh = self._root.winfo_screenheight()
            x = (sw - window_w) // 2
            y = (sh - window_h) // 2
        self._root.geometry(f"{window_w}x{window_h}+{x}+{y}")

        splash = SplashScreen(self._root, self._theme, self._monitor_mgr.primary)
        splash.grab_set()
        self._root.wait_window(splash)

        self._main_window = MainWindow(
            master=self._root,
            theme=self._theme,
            settings=self._settings,
            engine=self._engine,
            history=self._history,
            sound=self._sound,
            on_start_draw=self._on_start_draw,
            on_new_draw=self._on_new_draw,
            on_reset=self._on_reset,
            on_clear=self._on_clear,
            on_settings=self._on_settings,
            on_export=self._on_export,
            on_telao=self._show_telao_dialog,
            on_fullscreen=self._on_fullscreen,
            on_quit=self._on_quit,
            on_toggle_theme=self._toggle_theme,
            on_toggle_minimize=self._on_toggle_minimize,
        )

        self._sound.enabled = bool(self._settings.get("sound", "enabled"))

        self._setup_public_display()
        self._setup_keyboard_shortcuts()

        self._updater = Updater(self._root, self._theme)
        self._root.after(2500, self._updater.check_for_updates)

        self._root.after(150, self._root.lift)
        self._root.after(300, self._root.focus_force)

        self._root.protocol("WM_DELETE_WINDOW", self._on_quit)
        self._root.mainloop()

    def start_embedded(
        self,
        master,
        public_rect: tuple | None = None,
        public_master=None,
        on_close: Callable | None = None,
    ) -> None:
        """Inicia o sorteio dentro do NavePro (sem mainloop próprio).

        ``master`` é a janela do operador (um ``CTkToplevel`` do shim local,
        filha do root do NavePro). ``public_rect`` é a geometria
        ``(x, y, w, h)`` do monitor do telão — quando informada, a tela
        pública do sorteio é aberta ali (sem bordas, sempre no topo, por
        cima do relógio do NavePro). ``on_close`` é chamado ao sair.
        """
        self._embedded = True
        self._on_close = on_close
        self._public_rect = public_rect
        self._public_master = public_master

        self._root = master
        master.configure(fg_color=self._theme.c("bg"))

        self._main_window = MainWindow(
            master=master,
            theme=self._theme,
            settings=self._settings,
            engine=self._engine,
            history=self._history,
            sound=self._sound,
            on_start_draw=self._on_start_draw,
            on_new_draw=self._on_new_draw,
            on_reset=self._on_reset,
            on_clear=self._on_clear,
            on_settings=self._on_settings,
            on_export=self._on_export,
            on_telao=self._show_telao_dialog,
            on_fullscreen=self._on_fullscreen,
            on_quit=self._on_quit,
            on_toggle_theme=self._toggle_theme,
            on_toggle_minimize=self._on_toggle_minimize,
        )

        self._sound.enabled = bool(self._settings.get("sound", "enabled"))

        self._setup_public_display_embedded()
        self._setup_keyboard_shortcuts()

        try:
            master.protocol("WM_DELETE_WINDOW", self._on_quit)
        except Exception:
            pass

    def _setup_public_display_embedded(self) -> None:
        """Abre a tela pública do sorteio na geometria do telão do NavePro.

        Usa ``overrideredirect`` + geometria exata (em vez de ``-fullscreen``
        do Tk) porque no Windows o ``-fullscreen`` sempre vai para o monitor
        primário, ignorando onde a janela está. Assim a tela pública cobre
        exatamente o monitor do telão em qualquer plataforma.
        """
        if not self._public_rect:
            return
        x, y, w, h = self._public_rect
        self._public_window = PublicWindow(self._theme, self._settings)
        self._public_window.create(
            x=x, y=y, w=w, h=h,
            fullscreen=False,
            master=self._public_master,
            borderless=True,
        )
        # No modo embutido a tela pública cobre o relógio do NavePro: força
        # opacidade total (o operador ainda pode ajustar em Configurações).
        self._public_window.set_alpha(1.0)

    def _setup_public_display(self, confirm: bool = True) -> None:
        use_public = False
        public_monitor = None

        if self._monitor_mgr.has_multiple_monitors:
            idx = self._settings.get("display", "public_monitor") or 1
            public_monitor = self._monitor_mgr.get_public_monitor(idx)
            use_public = public_monitor is not None

        if use_public and public_monitor:
            self._public_window = PublicWindow(self._theme, self._settings)
            self._public_window.create(
                x=public_monitor.x,
                y=public_monitor.y,
                w=public_monitor.width,
                h=public_monitor.height,
                fullscreen=True,
            )
        else:
            if confirm:
                answer = tk.messagebox.askyesno(
                    title="Monitor Público",
                    message="Nenhum monitor secundário detectado.\n\n"
                            "Deseja utilizar apenas uma tela?\n\n"
                            "Sim: O sorteio será exibido nesta janela.\n"
                            "Não: O sorteio funcionará apenas no modo operador "
                            "(sem exibição pública).",
                )
            else:
                answer = True
            if answer:
                self._public_window = PublicWindow(self._theme, self._settings)
                self._public_window.create(
                    x=200, y=200, w=800, h=600,
                    fullscreen=False,
                )

    def _setup_keyboard_shortcuts(self) -> None:
        if self._root:
            self._root.bind("<F11>", lambda e: self._on_fullscreen())
            self._root.bind("<space>", lambda e: self._on_space())
            self._root.bind("<Control-r>", lambda e: self._on_reset())
            self._root.bind("<Control-e>", lambda e: self._on_export())
            self._root.bind("<Escape>", lambda e: self._on_quit())
            self._root.bind("<Control-m>", lambda e: self._on_toggle_minimize())
            self._root.bind("<Control-q>", lambda e: self._on_quit())
            self._root.bind("<Control-t>", lambda e: self._toggle_theme())

    # ── Event handlers ──

    def _on_start_draw(self, numbers: list[int]) -> None:
        self._sound.play("transition")
        if self._public_window and self._public_window.is_open:
            if self._engine.mode == "names":
                self._public_window.start_draw_names(
                    numbers,
                    name_pool=self._engine.all_items,
                    on_end=self._on_public_animation_end,
                )
            else:
                self._public_window.start_draw(
                    numbers,
                    range_min=self._engine.start,
                    range_max=self._engine.end,
                    on_end=self._on_public_animation_end,
                )
        else:
            self._sound.play("firework")
            self._check_completed()

    def _on_public_animation_end(self) -> None:
        self._sound.play("firework")
        self._check_completed()

    def _on_new_draw(self) -> None:
        self._check_completed()

    def _on_reset(self) -> None:
        if self._public_window and self._public_window.is_open:
            self._public_window.close()
            self._setup_public_display(confirm=False)

    def _on_clear(self) -> None:
        if self._public_window and self._public_window.is_open:
            self._public_window.show_idle()

    def _on_settings(self) -> None:
        self._show_settings_dialog()

    def _on_export(self) -> None:
        self._show_export_dialog()

    def _show_export_dialog(self) -> None:
        """Custom save dialog that only lists the user's common (non-hidden)
        folders and files, starting at the home directory."""
        from tkinter import messagebox

        dialog = ctk.CTkToplevel(self._root)
        dialog.title("Exportar Histórico")
        dialog.configure(fg_color=self._theme.c("bg"))
        dialog.resizable(False, False)
        dialog.grab_set()

        dialog.geometry(f"680x520+{self._root.winfo_x() + 100}+{self._root.winfo_y() + 100}")

        current_dir = [os.path.expanduser("~")]
        selected = ["sorteios.csv"]

        ctk.CTkLabel(
            dialog,
            text="Exportar Histórico",
            font=(ui_font(), 18, "bold"),
            text_color=self._theme.c("primary"),
        ).pack(anchor="w", padx=15, pady=(15, 5))

        path_bar = ctk.CTkFrame(dialog, fg_color="transparent")
        path_bar.pack(fill="x", padx=15, pady=5)

        def go_home() -> None:
            current_dir[0] = os.path.expanduser("~")
            refresh()

        def go_up() -> None:
            parent = os.path.dirname(current_dir[0])
            if os.path.isdir(parent):
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
            current_dir[0] = os.path.join(current_dir[0], name)
            refresh()

        def pick_file(name: str) -> None:
            selected[0] = name
            entry_filename.delete(0, "end")
            entry_filename.insert(0, name)

        def refresh() -> None:
            for widget in list_frame.winfo_children():
                widget.destroy()

            def bind_row(row, handler) -> None:
                row.bind("<Button-1>", lambda e: handler())
                row.bind("<Double-Button-1>", lambda e: handler())
                for child in row.winfo_children():
                    child.bind("<Button-1>", lambda e: handler())
                    child.bind("<Double-Button-1>", lambda e: handler())

            path = current_dir[0]
            path_lbl.configure(text=path)

            try:
                entries = sorted(os.listdir(path))
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
                and os.path.isdir(os.path.join(path, name))
            ]
            files = [
                name for name in entries
                if not name.startswith(".")
                and os.path.isfile(os.path.join(path, name))
                and name.lower().endswith((".csv", ".txt"))
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
                bind_row(row, lambda n=folder: open_folder(n))

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
                bind_row(row, lambda n=file: pick_file(n))

            if not folders and not files:
                ctk.CTkLabel(
                    list_frame,
                    text="Nenhuma pasta ou arquivo visível aqui.",
                    font=(ui_font(), 12),
                    text_color=self._theme.c("text_secondary"),
                ).pack(pady=10)

        name_row = ctk.CTkFrame(dialog, fg_color="transparent")
        name_row.pack(fill="x", padx=15, pady=(10, 5))

        ctk.CTkLabel(
            name_row,
            text="Nome do arquivo:",
            font=(ui_font(), 12),
            text_color=self._theme.c("text_secondary"),
        ).pack(side="left", padx=(0, 10))

        entry_filename = ctk.CTkEntry(
            name_row,
            font=(ui_font(), 12),
            height=32,
        )
        entry_filename.insert(0, selected[0])
        entry_filename.pack(side="left", fill="x", expand=True)

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(fill="x", padx=15, pady=(5, 15))

        def save() -> None:
            name = entry_filename.get().strip()
            if not name:
                return
            if not name.lower().endswith((".csv", ".txt")):
                name += ".csv"
            filepath = os.path.join(current_dir[0], name)
            dialog.destroy()
            self._perform_export(filepath, messagebox)

        ctk.CTkButton(
            btn_row,
            text="Salvar",
            width=120, height=36,
            font=(ui_font(), 12, "bold"),
            fg_color=self._theme.c("btn_primary"),
            text_color=self._theme.c("btn_text"),
            command=save,
        ).pack(side="right", padx=(10, 0))

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

    def _perform_export(self, filepath: str, messagebox) -> None:
        try:
            if filepath.endswith(".csv"):
                result = self._history.export_csv(filepath)
            else:
                result = self._history.export_txt(filepath)

            messagebox.showinfo(
                title="Exportado",
                message=f"Histórico exportado com sucesso!\n{result}",
            )
        except Exception as e:
            messagebox.showerror(
                title="Erro",
                message=f"Erro ao exportar: {e}",
            )

    def _on_fullscreen(self) -> None:
        if self._public_window and self._public_window.is_open:
            self._public_window.toggle_fullscreen()

    def _on_toggle_minimize(self) -> None:
        if self._public_window and self._public_window.is_open:
            minimized = self._public_window.toggle_minimize()
            if self._main_window:
                self._main_window.set_public_minimized(minimized)

    def _on_quit(self) -> None:
        self._sound.cleanup()
        if self._public_window:
            self._public_window.close()
            self._public_window = None
        if self._embedded:
            if self._on_close:
                self._on_close()
            return
        if self._root:
            self._root.destroy()

    def _on_space(self) -> None:
        widget = self._root.focus_get() if self._root else None
        if isinstance(widget, (tk.Entry, ctk.CTkEntry, ctk.CTkCheckBox)):
            return
        if self._main_window:
            self._main_window._on_new_click()

    def _toggle_theme(self) -> None:
        self._theme.toggle_theme()
        if self._main_window:
            self._main_window.refresh_theme()

    def _check_completed(self) -> None:
        if self._engine.is_completed():
            if self._main_window:
                self._main_window.show_completed_message()
            if self._public_window and self._public_window.is_open:
                self._public_window.show_completed(
                    is_names=self._engine.mode == "names"
                )

    def _show_settings_dialog(self) -> None:
            dialog = ctk.CTkToplevel(self._root)
            dialog.title("Configurações")
            dialog.configure(fg_color=self._theme.c("bg"))
            dialog.resizable(True, True)
            dialog.grab_set()

            x = self._root.winfo_x() + 100
            y = self._root.winfo_y() + 100
            sw = int(self._settings.get("ui", "settings_w") or 820)
            sh = int(self._settings.get("ui", "settings_h") or 720)
            dialog.geometry(f"{sw}x{sh}+{x}+{y}")

            main_frame = ctk.CTkScrollableFrame(
                dialog,
                fg_color="transparent",
            )
            main_frame.pack(fill="both", expand=True, padx=15, pady=15)

            ctk.CTkLabel(
                main_frame,
                text="Configurações",
                font=(ui_font(), 20, "bold"),
                text_color=self._theme.c("primary"),
            ).pack(anchor="w", pady=(0, 15))

            sections = [
                ("Animação", [
                    ("Duração (s)",
                     str(self._settings.get("animation", "duration") or 0.6)),
                    ("Velocidade Inicial (ms)",
                     str(self._settings.get("animation", "initial_speed") or 30)),
                    ("Velocidade Mínima (ms)",
                     str(self._settings.get("animation", "min_speed") or 200)),
                ]),
                ("Áudio", [
                    ("Som Ativado",
                     "Sim" if self._settings.get("sound", "enabled") else "Não"),
                    ("Volume",
                     str(self._settings.get("sound", "volume") or 0.5)),
                ]),
                ("Tela Pública", [
                    ("Tela Transparente",
                     "Sim" if self._settings.get("display", "public_transparent") is not False else "Não"),
                    ("Transparência da Tela",
                     str(self._settings.get("display", "public_alpha") or 1.0)),
                    ("Cor do Fundo",
                     str(self._settings.get("display", "public_bg") or "")),
                    ("Cor dos Títulos",
                     str(self._settings.get("display", "public_primary") or "")),
                    ("Cor dos Textos",
                     str(self._settings.get("display", "public_text") or "")),
                    ("Cor dos Textos Secundários",
                     str(self._settings.get("display", "public_text_secondary") or "")),
                ]),
            ]

            entries = {}

            for section_name, fields in sections:
                section_frame = ctk.CTkFrame(
                    main_frame,
                    fg_color=self._theme.c("bg_card"),
                    corner_radius=8,
                )
                section_frame.pack(fill="x", pady=(0, 10))

                ctk.CTkLabel(
                    section_frame,
                    text=section_name,
                    font=(ui_font(), 16, "bold"),
                    text_color=self._theme.c("primary"),
                ).pack(anchor="w", padx=15, pady=(10, 5))

                for field_name, default in fields:
                    row = ctk.CTkFrame(section_frame, fg_color="transparent")
                    row.pack(fill="x", padx=15, pady=3)

                    ctk.CTkLabel(
                        row,
                        text=field_name,
                        font=(ui_font(), 16),
                        text_color=self._theme.c("text_secondary"),
                    ).pack(side="left")

                    COLOR_DEFAULTS = {
                        "Cor do Fundo": "#050816",
                        "Cor dos Títulos": "#00d4ff",
                        "Cor dos Textos": "#ffffff",
                        "Cor dos Textos Secundários": "#8892b0",
                    }

                    is_color = field_name.startswith("Cor ")
                    entry = ctk.CTkEntry(
                        row,
                        width=180,
                        height=30,
                        font=(ui_font(), 16),
                        placeholder_text=(
                            COLOR_DEFAULTS[field_name] if is_color else ""
                        ),
                    )
                    entry.insert(0, default)
                    entry.pack(side="right")
                    entries[f"{section_name}:{field_name}"] = entry

                    if is_color:
                        ctk.CTkButton(
                            row,
                            text="Escolher...",
                            width=90,
                            height=30,
                            font=(ui_font(), 13, "bold"),
                            fg_color=self._theme.c("btn_primary"),
                            text_color=self._theme.c("btn_text"),
                            command=lambda e=entry: self._pick_color(e),
                        ).pack(side="right", padx=(5, 8))
                        ctk.CTkButton(
                            row,
                            text="Padrão",
                            width=70,
                            height=30,
                            font=(ui_font(), 13),
                            fg_color=self._theme.c("btn_neutral"),
                            text_color=self._theme.c("btn_text"),
                            command=lambda e=entry: e.delete(0, "end"),
                        ).pack(side="right", padx=(0, 8))

            btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
            btn_frame.pack(fill="x", pady=(10, 0))

            ctk.CTkButton(
                btn_frame,
                text="Salvar",
                command=lambda: self._save_settings(dialog, entries),
                width=120,
                height=36,
                font=(ui_font(), 16, "bold"),
                fg_color=self._theme.c("btn_primary"),
                text_color=self._theme.c("btn_text"),
            ).pack(side="right", padx=(10, 0))

            ctk.CTkButton(
                btn_frame,
                text="Cancelar",
                command=lambda: self._close_settings_dialog(dialog),
                width=120,
                height=36,
                font=(ui_font(), 16),
                fg_color=self._theme.c("btn_neutral"),
                text_color=self._theme.c("btn_text"),
            ).pack(side="right")

    def _pick_color(self, entry: ctk.CTkEntry) -> None:
        initial = entry.get().strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", initial):
            initial = None
        dialog = entry.winfo_toplevel()
        dialog.lift()
        dialog.focus_force()
        try:
            dialog.attributes("-topmost", True)
            dialog.update_idletasks()
        except tk.TclError:
            pass
        try:
            _rgb, hexv = colorchooser.askcolor(color=initial, parent=dialog)
        finally:
            try:
                dialog.attributes("-topmost", False)
            except tk.TclError:
                pass
        if hexv:
            entry.delete(0, "end")
            entry.insert(0, hexv)

    def _remember_settings_size(self, dialog: ctk.CTkToplevel) -> None:
        try:
            w = dialog.winfo_width()
            h = dialog.winfo_height()
            if w > 150 and h > 150:
                self._settings.set("ui", "settings_w", w)
                self._settings.set("ui", "settings_h", h)
        except Exception:
            pass

    def _close_settings_dialog(self, dialog: ctk.CTkToplevel) -> None:
        self._remember_settings_size(dialog)
        dialog.destroy()

    def _save_settings(
        self,
        dialog: ctk.CTkToplevel,
        entries: dict,
    ) -> None:
        try:
            self._settings.set(
                "animation", "duration",
                float(entries["Animação:Duração (s)"].get())
            )
            self._settings.set(
                "animation", "initial_speed",
                int(entries["Animação:Velocidade Inicial (ms)"].get())
            )
            self._settings.set(
                "animation", "min_speed",
                int(entries["Animação:Velocidade Mínima (ms)"].get())
            )
            self._settings.set(
                "sound", "volume",
                float(entries["Áudio:Volume"].get())
            )
            self._settings.set(
                "sound", "enabled",
                entries["Áudio:Som Ativado"].get().lower() == "sim"
            )
            alpha = float(entries["Tela Pública:Transparência da Tela"].get())
            if not 0.2 <= alpha <= 1.0:
                raise ValueError("Transparência deve estar entre 0.2 e 1.0")
            self._settings.set("display", "public_alpha", alpha)

            transparent = (
                entries["Tela Pública:Tela Transparente"].get().strip().lower() == "sim"
            )
            self._settings.set("display", "public_transparent", transparent)

            for field_key, field_label in (
                ("public_bg", "Cor do Fundo"),
                ("public_primary", "Cor dos Títulos"),
                ("public_text", "Cor dos Textos"),
                ("public_text_secondary", "Cor dos Textos Secundários"),
            ):
                color = entries[f"Tela Pública:{field_label}"].get().strip()
                if color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                    raise ValueError(
                        f"Cor inválida em '{field_label}'. "
                        "Use o formato #RRGGBB (ex.: #000000) ou deixe "
                        "vazio para o padrão transparente."
                    )
                self._settings.set("display", field_key, color)

            self._sound.volume = self._settings.get("sound", "volume") or 0.5
            self._sound.enabled = self._settings.get("sound", "enabled") or False
            if self._public_window and self._public_window.is_open:
                self._public_window.set_alpha(alpha)
                self._public_window.refresh_public()
            self._remember_settings_size(dialog)
            dialog.destroy()

        except ValueError as e:
            tk.messagebox.showerror(
                title="Erro",
                message=f"Valor inválido: {e}",
            )


    # ──────────────────────────────────────────────────────────────────
    # Aparência do telão (tela pública) — atalho no painel do operador
    # ──────────────────────────────────────────────────────────────────

    _TELAO_CORES_FUNDO = (
        ("Preto", "#000000"),
        ("Cinza escuro", "#1a1a2e"),
        ("Azul escuro", "#0d1b2a"),
        ("Verde escuro", "#0a1f0a"),
        ("Vinho", "#2d0a0a"),
    )

    def _telao_aplicar(
        self, opaco: bool, alpha, bg: str, primary: str, texto: str,
        texto2: str,
    ) -> None:
        """Aplica e persiste a aparência da tela pública do sorteio."""
        self._settings.set("display", "public_transparent", not bool(opaco))
        try:
            alpha = max(0.2, min(1.0, float(alpha)))
        except (TypeError, ValueError):
            alpha = 1.0
        self._settings.set("display", "public_alpha", alpha)
        for chave, valor in (
            ("public_bg", bg),
            ("public_primary", primary),
            ("public_text", texto),
            ("public_text_secondary", texto2),
        ):
            valor = (valor or "").strip()
            if valor and not re.fullmatch(r"#[0-9a-fA-F]{6}", valor):
                continue
            self._settings.set("display", chave, valor)
        if self._public_window and self._public_window.is_open:
            self._public_window.set_alpha(alpha)
            self._public_window.refresh_public()

    def _telao_escolher_cor(self, var: tk.StringVar, aplicar) -> None:
        """Abre o seletor de cor e atualiza a variável/aplicação."""
        inicial = var.get().strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", inicial):
            inicial = None
        try:
            _rgb, hexv = colorchooser.askcolor(
                color=inicial, parent=(self._telao_dialog or self._root)
            )
        except tk.TclError:
            return
        if hexv:
            var.set(hexv)
            aplicar()

    def _show_telao_dialog(self) -> None:
        """Atalho de aparência da tela pública (telão).

        Reúne, para a tela do sorteio projetada no telão, as mesmas opções
        de aparência da janela "Relógio" do NavePro: fundo opaco/transparente,
        nível de transparência e cores (fundo/títulos/textos). Aplica na
        hora, então basta olhar o telão para ver o resultado.
        """
        if not (self._public_window and self._public_window.is_open):
            tk.messagebox.showinfo(
                "Aparência do Telão",
                "A tela pública do sorteio não está ativa.\n\n"
                "Conecte um segundo monitor (telão) e abra o sorteio para "
                "ajustar o que aparece no telão.",
            )
            return

        if self._telao_dialog is not None:
            try:
                if self._telao_dialog.winfo_exists():
                    self._telao_dialog.deiconify()
                    self._telao_dialog.lift()
                    self._telao_dialog.focus_force()
                    return
            except tk.TclError:
                pass
            self._telao_dialog = None

        dialog = ctk.CTkToplevel(self._root)
        dialog.title("🖥️ Aparência do Telão")
        dialog.configure(fg_color=self._theme.c("bg"))
        dialog.resizable(False, False)
        try:
            dialog.transient(self._root)
            x = self._root.winfo_x() + 120
            y = self._root.winfo_y() + 60
            dialog.geometry(f"600x680+{x}+{y}")
        except tk.TclError:
            dialog.geometry("600x680")
        self._telao_dialog = dialog

        def _fechar() -> None:
            self._telao_dialog = None
            try:
                dialog.destroy()
            except tk.TclError:
                pass

        dialog.protocol("WM_DELETE_WINDOW", _fechar)

        container = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=18, pady=18)

        card = self._theme.c("bg_card")
        texto_sec = self._theme.c("text_secondary")
        cor_prim = self._theme.c("primary")

        ctk.CTkLabel(
            container, text="🖥️ Aparência do Telão",
            font=(ui_font(), 20, "bold"), text_color=cor_prim,
        ).pack(anchor="w", pady=(0, 12))

        opaco_var = tk.BooleanVar(
            value=self._settings.get("display", "public_transparent") is False
        )
        alpha_var = tk.DoubleVar(
            value=float(self._settings.get("display", "public_alpha") or 1.0)
        )
        bg_var = tk.StringVar(
            value=str(self._settings.get("display", "public_bg") or "")
        )
        prim_var = tk.StringVar(
            value=str(self._settings.get("display", "public_primary") or "")
        )
        text_var = tk.StringVar(
            value=str(self._settings.get("display", "public_text") or "")
        )
        text2_var = tk.StringVar(
            value=str(self._settings.get("display", "public_text_secondary") or "")
        )

        def _secao(titulo: str) -> ctk.CTkFrame:
            sec = ctk.CTkFrame(container, fg_color=card, corner_radius=8)
            sec.pack(fill="x", pady=(0, 10))
            ctk.CTkLabel(
                sec, text=titulo, font=(ui_font(), 16, "bold"),
                text_color=cor_prim,
            ).pack(anchor="w", padx=15, pady=(10, 4))
            return sec

        # ── Transparência ──
        sec_transp = _secao("Transparência")
        escala = tk.Scale(
            sec_transp, from_=0.2, to=1.0, resolution=0.05,
            orient="horizontal", variable=alpha_var, bg=card,
            fg=self._theme.c("text"), troughcolor=self._theme.c("input_bg"),
            highlightthickness=0, font=(ui_font(), 12),
            label="Nível de transparência",
        )

        def aplicar(*_args) -> None:
            escala.configure(
                state="disabled" if opaco_var.get() else "normal"
            )
            self._telao_aplicar(
                opaco_var.get(), alpha_var.get(), bg_var.get(),
                prim_var.get(), text_var.get(), text2_var.get(),
            )

        ctk.CTkCheckBox(
            sec_transp, text="Fundo opaco (sem transparência)",
            variable=opaco_var, command=aplicar,
            font=(ui_font(), 15, "bold"),
        ).pack(anchor="w", padx=15)
        escala.configure(command=lambda _v: aplicar())
        escala.pack(fill="x", padx=15, pady=(2, 10))

        # ── Cor de fundo ──
        sec_bg = _secao("Cor de fundo do telão")
        linha = tk.Frame(sec_bg, bg=card)
        linha.pack(fill="x", padx=15)
        for nome, codigo in self._TELAO_CORES_FUNDO:
            tk.Radiobutton(
                linha, text=nome, value=codigo, variable=bg_var,
                command=aplicar, bg=card, fg=self._theme.c("text"),
                selectcolor=card, activebackground=card,
                activeforeground=cor_prim, font=(ui_font(), 12),
            ).pack(side="left", padx=3)
        linha_bg = tk.Frame(sec_bg, bg=card)
        linha_bg.pack(fill="x", padx=15, pady=(4, 10))
        ctk.CTkButton(
            linha_bg, text="🎨 Escolher…",
            command=lambda: self._telao_escolher_cor(bg_var, aplicar),
            width=150, height=32, font=(ui_font(), 13, "bold"),
            fg_color=self._theme.c("btn_primary"),
            text_color=self._theme.c("btn_text"),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            linha_bg, text="✖ Padrão",
            command=lambda: (bg_var.set(""), aplicar()),
            width=120, height=32, font=(ui_font(), 13),
            fg_color=self._theme.c("btn_neutral"),
            text_color=self._theme.c("btn_text"),
        ).pack(side="left")

        # ── Cores dos textos ──
        sec_txt = _secao("Cores dos textos no telão")
        for titulo, var in (
            ("Títulos", prim_var),
            ("Textos", text_var),
            ("Secundários", text2_var),
        ):
            row = tk.Frame(sec_txt, bg=card)
            row.pack(fill="x", padx=15, pady=3)
            tk.Label(
                row, text=titulo, bg=card, fg=texto_sec,
                font=(ui_font(), 14), width=14, anchor="w",
            ).pack(side="left")
            entry = ctk.CTkEntry(
                row, width=150, height=32, font=(ui_font(), 14),
                textvariable=var,
            )
            entry.pack(side="left", padx=(6, 6))
            entry.bind("<KeyRelease>", lambda _e: aplicar())
            entry.bind("<FocusOut>", lambda _e: aplicar())
            ctk.CTkButton(
                row, text="🎨",
                command=lambda v=var: self._telao_escolher_cor(v, aplicar),
                width=46, height=32, font=(ui_font(), 13, "bold"),
                fg_color=self._theme.c("btn_primary"),
                text_color=self._theme.c("btn_text"),
            ).pack(side="left", padx=(0, 6))
            ctk.CTkButton(
                row, text="✖",
                command=lambda v=var: (v.set(""), aplicar()),
                width=46, height=32, font=(ui_font(), 13),
                fg_color=self._theme.c("btn_neutral"),
                text_color=self._theme.c("btn_text"),
            ).pack(side="left")

        ctk.CTkLabel(
            container,
            text=("Os valores vazios usam a cor padrão (neon). O fundo "
                  "transparente deixa o relógio/desktop aparecer atrás do "
                  "sorteio no telão."),
            font=(ui_font(), 12), text_color=texto_sec,
            wraplength=540, justify="left",
        ).pack(anchor="w", pady=(0, 10))

        ctk.CTkButton(
            container, text="Fechar", command=_fechar,
            width=140, height=38, font=(ui_font(), 15, "bold"),
            fg_color=self._theme.c("btn_primary"),
            text_color=self._theme.c("btn_text"),
        ).pack(pady=(0, 4))

        aplicar()


def create_app() -> App:
    return App()
