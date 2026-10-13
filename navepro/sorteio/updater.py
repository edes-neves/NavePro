"""Verificação automática de atualizações no GitHub.

Ao abrir o aplicativo, uma thread consulta o repositório no GitHub e, se
existir uma versão mais nova que a atual, informa o usuário com a descrição
das melhorias e oferece o download do novo AppImage (salvo em ~/Downloads).
"""

import json
import queue
import re
import ssl
import threading
from collections.abc import Callable
from pathlib import Path
from urllib import request

from . import APP_VERSION, ctk
from .font_manager import ui_font

GITHUB_REPO = "edes-neves/sorteio-profissional"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
SUPPORT_EMAIL = "nevestecnologias@gmail.com"

_UA = f"SorteioProfissional/{APP_VERSION}"


def _version_key(version: str) -> tuple:
    """Converte 'v1.2.3' / '1.2.3' em tupla (1, 2, 3) para comparação."""
    numbers = re.findall(r"\d+", version or "")
    return tuple(int(part) for part in numbers[:3])


def is_newer(latest: str) -> bool:
    """True se `latest` for uma versão maior que a versão atual do app."""
    return _version_key(latest) > _version_key(APP_VERSION)


def fetch_latest_release() -> dict | None:
    """Consulta a última release no GitHub.

    Retorna {"version", "body", "url", "filename"} ou None em caso de
    falha (sem internet, sem releases, sem asset .AppImage etc.).
    Essa função faz rede e deve rodar em uma thread de fundo.
    """
    try:
        ctx = ssl.create_default_context()
        req = request.Request(RELEASES_API, headers={"User-Agent": _UA})
        with request.urlopen(req, timeout=8, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        version = str(data.get("tag_name", "")).lstrip("vV")
        if not version:
            return None

        url = None
        filename = None
        for asset in data.get("assets", []):
            name = str(asset.get("name", ""))
            if name.lower().endswith(".appimage"):
                url = asset.get("browser_download_url")
                filename = name
                break
        if not url:
            return None

        return {
            "version": version,
            "body": str(data.get("body") or ""),
            "url": url,
            "filename": filename or f"SorteioProfissional-{version}-x86_64.AppImage",
        }
    except Exception:
        return None


def _download_file(url: str, target: Path, progress: Callable[[int, int], None]) -> Path | None:
    """Baixa o arquivo para `target` em stream, reportando (bytes, total)."""
    try:
        tmp = target.with_suffix(target.suffix + ".part")
        req = request.Request(url, headers={"User-Agent": _UA})
        with request.urlopen(req, timeout=30) as resp, open(tmp, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            copied = 0
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                copied += len(chunk)
                if total > 0:
                    progress(copied, total)
        tmp.replace(target)
        return target
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return None


def _target_path(filename: str) -> Path | None:
    try:
        downloads = Path.home() / "Downloads"
        downloads.mkdir(exist_ok=True)
        return downloads / filename
    except Exception:
        return None


class Updater:
    """Dialogs e orquestração da atualização; usa o tema atual do app."""

    def __init__(self, master: ctk.CTkToplevel, theme) -> None:
        self._master = master
        self._theme = theme

    # ── Fluxo público ────────────────────────────────────────────────

    def check_for_updates(self) -> None:
        """Inicia a verificação em segundo plano. Sem janela se estiver ok."""
        results: queue.Queue[dict | None] = queue.Queue()

        def worker() -> None:
            results.put(fetch_latest_release())

        threading.Thread(target=worker, daemon=True).start()
        self._poll_results(results, tries=0)

    # ── Poll segura (main thread) ────────────────────────────────────

    def _poll_results(self, results: "queue.Queue[dict | None]", tries: int) -> None:
        try:
            info = results.get_nowait()
        except queue.Empty:
            if tries < 40:  # aguarda até ~20s
                self._master.after(
                    500, lambda: self._poll_results(results, tries + 1)
                )
            return
        if info and is_newer(info["version"]):
            self._show_available(info)

    # ── Janela de aviso ──────────────────────────────────────────────

    def _show_available(self, info: dict) -> None:
        window = ctk.CTkToplevel(self._master)
        window.title("Atualização disponível")
        window.configure(fg_color=self._theme.c("bg"))
        self._center(window, 520, 460)
        window.grab_set()

        ctk.CTkLabel(
            window,
            text="NOVA VERSÃO DISPONÍVEL!",
            font=(ui_font(), 20, "bold"),
            text_color=self._theme.c("primary"),
        ).pack(pady=(22, 4))

        ctk.CTkLabel(
            window,
            text=(
                f"Você está usando a versão {APP_VERSION} e a versão "
                f"{info['version']} já foi publicada."
            ),
            font=(ui_font(), 12),
            text_color=self._theme.c("text_secondary"),
            wraplength=460,
            justify="left",
        ).pack(pady=(0, 12))

        ctk.CTkLabel(
            window,
            text="O que há de novo nesta versão:",
            font=(ui_font(), 12, "bold"),
            text_color=self._theme.c("text"),
        ).pack(anchor="w", padx=22, pady=(0, 4))

        body = info["body"].strip() or "Melhorias e correções de bugs."
        textbox = ctk.CTkTextbox(
            window,
            width=470,
            height=220,
            font=(ui_font(), 12),
            fg_color=self._theme.c("bg_card"),
            text_color=self._theme.c("text"),
            border_color=self._theme.c("border"),
            border_width=1,
        )
        textbox.pack(padx=22, pady=(0, 14), fill="both", expand=True)
        textbox.insert("1.0", body)
        textbox.configure(state="disabled")

        buttons = ctk.CTkFrame(window, fg_color="transparent")
        buttons.pack(pady=(0, 18))
        ctk.CTkButton(
            buttons,
            text="Sim, baixar",
            width=150,
            height=36,
            font=(ui_font(), 13, "bold"),
            fg_color=self._theme.c("btn_primary"),
            text_color=self._theme.c("btn_text"),
            command=lambda: self._download_clicked(window, info),
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            buttons,
            text="Agora não",
            width=150,
            height=36,
            font=(ui_font(), 13, "bold"),
            fg_color=self._theme.c("btn_neutral"),
            text_color=self._theme.c("text"),
            command=window.destroy,
        ).pack(side="left", padx=8)

    # ── Download com barra de progresso ──────────────────────────────

    def _download_clicked(self, notifier, info: dict) -> None:
        try:
            notifier.destroy()
        except Exception:
            pass
        self._start_download(info)

    def _start_download(self, info: dict) -> None:
        target = _target_path(info["filename"])
        if target is None:
            self._show_error("Não foi possível encontrar a pasta Downloads.")
            return

        window = ctk.CTkToplevel(self._master)
        window.title("Baixando atualização")
        window.configure(fg_color=self._theme.c("bg"))
        window.resizable(False, False)
        self._center(window, 480, 200)
        window.grab_set()

        ctk.CTkLabel(
            window,
            text=f"Baixando {info['filename']}...",
            font=(ui_font(), 14, "bold"),
            text_color=self._theme.c("text"),
        ).pack(pady=(24, 14))

        bar = ctk.CTkProgressBar(window, width=420, mode="determinate")
        bar.pack(padx=24, pady=(0, 10))

        status = ctk.CTkLabel(
            window,
            text="0%",
            font=(ui_font(), 12),
            text_color=self._theme.c("text_secondary"),
        )
        status.pack(pady=(0, 20))

        state = {"done": False, "ok": False, "path": None}

        def progress(copied: int, total: int) -> None:
            frac = copied / max(total, 1)
            try:
                window.after(0, lambda: (bar.set(min(frac, 1.0)),
                                          status.configure(
                                              text=f"{copied // 1024} KB / {total // 1024} KB ({int(frac * 100)}%)")))
            except Exception:
                pass

        def worker() -> None:
            path = _download_file(info["url"], target, progress)
            state["done"] = True
            state["ok"] = path is not None
            state["path"] = path

        threading.Thread(target=worker, daemon=True).start()

        self._poll_download(window, bar, status, state)

    def _poll_download(self, window, bar, status, state: dict) -> None:
        if not state["done"]:
            window.after(150, lambda: self._poll_download(window, bar, status, state))
            return
        try:
            window.destroy()
        except Exception:
            pass
        if state["ok"]:
            self._show_instructions(state["path"])
        else:
            self._show_error(
                "Não foi possível baixar a atualização.\n"
                "Verifique sua conexão com a internet e tente novamente."
            )

    # ── Instruções de instalação ─────────────────────────────────────

    def _show_instructions(self, path: Path) -> None:
        window = ctk.CTkToplevel(self._master)
        window.title("Download concluído")
        window.configure(fg_color=self._theme.c("bg"))
        self._center(window, 560, 430)
        window.grab_set()

        ctk.CTkLabel(
            window,
            text="DOWNLOAD CONCLUÍDO COM SUCESSO!",
            font=(ui_font(), 18, "bold"),
            text_color=self._theme.c("success"),
        ).pack(pady=(22, 8))

        ctk.CTkLabel(
            window,
            text=f"O arquivo foi salvo em:\n{path}",
            font=(ui_font(), 12),
            text_color=self._theme.c("text"),
            wraplength=510,
            justify="center",
        ).pack(pady=(0, 10))

        textbox = ctk.CTkTextbox(
            window,
            width=510,
            height=190,
            font=(ui_font(), 12),
            fg_color=self._theme.c("bg_card"),
            text_color=self._theme.c("text"),
            border_color=self._theme.c("border"),
            border_width=1,
        )
        textbox.pack(padx=24, pady=(0, 12), fill="both", expand=True)
        textbox.insert(
            "1.0",
            "Para instalar a nova versão:\n\n"
            "1. Feche a versão atual do Sorteio Profissional.\n"
            "2. Abra o arquivo baixado na pasta Downloads.\n"
            "   Se o sistema perguntar, clique em \"Permitir execução\".\n\n"
            "Ou, se preferir pelo terminal:\n"
            f"   chmod +x {path}\n"
            f"   {path}\n\n"
            "Na próxima edição, a nova versão abre com tudo o que já "
            "existia, incluindo suas configurações e histórico.",
        )
        textbox.configure(state="disabled")

        ctk.CTkButton(
            window,
            text="OK",
            width=140,
            height=36,
            font=(ui_font(), 13, "bold"),
            fg_color=self._theme.c("btn_primary"),
            text_color=self._theme.c("btn_text"),
            command=window.destroy,
        ).pack(pady=(0, 16))

    # ── Erro ─────────────────────────────────────────────────────────

    def _show_error(self, message: str) -> None:
        window = ctk.CTkToplevel(self._master)
        window.title("Atualização")
        window.configure(fg_color=self._theme.c("bg"))
        self._center(window, 460, 180)
        window.grab_set()

        ctk.CTkLabel(
            window,
            text=message,
            font=(ui_font(), 13),
            text_color=self._theme.c("text"),
            wraplength=420,
            justify="center",
        ).pack(pady=(36, 18))

        ctk.CTkButton(
            window,
            text="OK",
            width=110,
            height=34,
            font=(ui_font(), 12, "bold"),
            fg_color=self._theme.c("btn_primary"),
            text_color=self._theme.c("btn_text"),
            command=window.destroy,
        ).pack(pady=(0, 18))

    # ── Helpers ──────────────────────────────────────────────────────

    def _center(self, window: ctk.CTkToplevel, width: int, height: int) -> None:
        try:
            x = self._master.winfo_x() + max((self._master.winfo_width() - width) // 2, 0)
            y = self._master.winfo_y() + max((self._master.winfo_height() - height) // 2, 0)
            window.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            window.geometry(f"{width}x{height}")