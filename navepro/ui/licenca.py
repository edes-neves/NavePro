"""Ativação/consulta de licença e aplicação do modo demonstração.

Mixin herdado pela ``AppInterface``. A validação criptográfica fica em
``license_manager``; aqui ficam apenas a janela "Ativar Licença / Ver ID", a
cópia do ``licenca.key`` escolhido pelo usuário e a aplicação das restrições
do modo demonstração (servidor/API, controle remoto e marca d'água).
"""

from __future__ import annotations

import tkinter as tk
import tkinter.filedialog
import tkinter.messagebox
import webbrowser

from license_manager import (
    EMAIL_CONTATO,
    LIMITE_DEMO_ITENS_PROJECAO,
    LIMITE_DEMO_SLIDES_ANUNCIO,
    LIMITE_DEMO_SORTEIO,
    WHATSAPP_CONTATO,
    importar_arquivo_licenca,
    status_licenca,
)
from navepro.core.log import get_logger
from navepro.core.util_tk import _centralizar_sobre

log = get_logger("licenca")


class LicencaMixin:
    def abrir_licenca(self) -> None:
        """Abre a janela de ativação: status, ID da máquina e importação."""
        janela = tk.Toplevel(self.root)
        janela.title("🔑 Ativar Licença / Ver ID")
        janela.configure(bg='#0d1117')
        janela.resizable(False, False)
        janela.transient(self.root)
        try:
            _centralizar_sobre(janela, self.root,
                               area=self._area_monitor_operador())
        except Exception:
            pass

        main = tk.Frame(janela, bg='#0d1117')
        main.pack(fill='both', expand=True, padx=20, pady=16)

        tk.Label(main, text="🔑 Licença do NavePro", bg='#0d1117',
                 fg='#f0c040', font=("Arial", 15, "bold")
                 ).pack(anchor='w')

        status_lbl = tk.Label(main, bg='#0d1117', fg='#c9d1d9',
                              font=("Arial", 11, "bold"), justify='left',
                              wraplength=520, anchor='w')
        status_lbl.pack(fill='x', pady=(8, 4))

        detalhe_lbl = tk.Label(main, bg='#0d1117', fg='#8b949e',
                               font=("Arial", 9), justify='left',
                               wraplength=520, anchor='w')
        detalhe_lbl.pack(fill='x', pady=(0, 10))

        tk.Label(main, text="ID desta máquina:", bg='#0d1117',
                 fg='#f0c040', font=("Arial", 10, "bold")
                 ).pack(anchor='w')

        linha_id = tk.Frame(main, bg='#0d1117')
        linha_id.pack(fill='x', pady=(3, 10))
        id_var = tk.StringVar(value=getattr(self, "_licenca_machine_id", ""))
        entry_id = tk.Entry(linha_id, textvariable=id_var, state='readonly',
                            bg='#161b22', fg='#58a6ff', relief='flat',
                            readonlybackground='#161b22', font=("Consolas", 12))
        entry_id.pack(side='left', fill='x', expand=True, ipady=5)

        def _copiar_id() -> None:
            self.root.clipboard_clear()
            self.root.clipboard_append(id_var.get())
            btn_copiar.config(text="✅ Copiado")
            janela.after(1500, lambda: btn_copiar.config(text="📋 Copiar"))

        btn_copiar = tk.Button(linha_id, text="📋 Copiar", command=_copiar_id,
                               bg='#1f6feb', fg='white',
                               activebackground='#388bfd', bd=0,
                               font=("Arial", 10, "bold"), cursor='hand2',
                               padx=10, pady=4)
        btn_copiar.pack(side='left', padx=(6, 0))

        def _atualizar_textos() -> None:
            st = status_licenca()
            licenciado = bool(st.get("licenciado"))
            motivo = st.get("motivo") or "Modo Demonstração"
            id_var.set(st.get("machine_id") or id_var.get())
            if licenciado:
                status_lbl.configure(text=f"✅ {motivo}", fg='#3fb950')
                detalhe_lbl.configure(
                    text="Licença válida para esta máquina.")
            else:
                status_lbl.configure(text=f"⚠️ {motivo}", fg='#f85149')
                detalhe_lbl.configure(
                    text=("Modo Demonstração ativo: sem API/controle remoto, "
                          f"até {LIMITE_DEMO_ITENS_PROJECAO} itens por "
                          "projeção, "
                          f"{LIMITE_DEMO_SLIDES_ANUNCIO} slides por anúncio "
                          f"e {LIMITE_DEMO_SORTEIO} números/nomes por "
                          "sorteio. A projeção continua funcionando com a "
                          "marca d'água de teste."))

        def _importar() -> None:
            caminho = tkinter.filedialog.askopenfilename(
                title="Selecione o arquivo licenca.key",
                filetypes=[("Licença NavePro", "*.key"),
                           ("Todos os arquivos", "*.*")],
                parent=janela)
            if not caminho:
                return
            ok, mensagem = importar_arquivo_licenca(caminho)
            st = status_licenca()
            self._aplicar_estado_licenca(
                st.get("licenciado", False),
                st.get("motivo", ""),
                st.get("machine_id", ""))
            _atualizar_textos()
            if ok:
                tkinter.messagebox.showinfo(
                    "Licença ativada", mensagem, parent=janela)
            else:
                tkinter.messagebox.showwarning(
                    "Licença", mensagem, parent=janela)

        linha_botoes = tk.Frame(main, bg='#0d1117')
        linha_botoes.pack(fill='x', pady=(2, 10))
        tk.Button(linha_botoes, text="📂 Importar licenca.key",
                  command=_importar, bg='#238636', fg='white',
                  activebackground='#2ea043', bd=0,
                  font=("Arial", 10, "bold"), cursor='hand2',
                  padx=10, pady=5).pack(side='left')
        tk.Button(linha_botoes, text="Fechar", command=janela.destroy,
                  bg='#21262d', fg='#c9d1d9', activebackground='#30363d',
                  bd=0, font=("Arial", 10), cursor='hand2',
                  padx=10, pady=5).pack(side='right')

        tk.Label(main, text="Precisa de uma licença? Fale com a Neves "
                            "Tecnologias:",
                 bg='#0d1117', fg='#c9d1d9', font=("Arial", 10, "bold"),
                 anchor='w').pack(fill='x', pady=(10, 2))
        linha_contato = tk.Frame(main, bg='#0d1117')
        linha_contato.pack(fill='x')
        tk.Button(linha_contato, text=f"✉️ {EMAIL_CONTATO}",
                  command=lambda: self._abrir_contato_licenca("email"),
                  bg='#161b22', fg='#58a6ff', activebackground='#21262d',
                  bd=0, font=("Arial", 10), cursor='hand2',
                  padx=8, pady=4).pack(side='left', padx=(0, 6))
        tk.Button(linha_contato, text=f"💬 WhatsApp {WHATSAPP_CONTATO}",
                  command=lambda: self._abrir_contato_licenca("whatsapp"),
                  bg='#161b22', fg='#3fb950', activebackground='#21262d',
                  bd=0, font=("Arial", 10), cursor='hand2',
                  padx=8, pady=4).pack(side='left')

        _atualizar_textos()

    def _abrir_contato_licenca(self, canal: str) -> None:
        """Abre e-mail/WhatsApp no navegador; mostra o contato se falhar."""
        try:
            if canal == "whatsapp":
                webbrowser.open("https://wa.me/554431700809")
            else:
                webbrowser.open(
                    f"mailto:{EMAIL_CONTATO}?subject=Licença%20NavePro")
        except Exception:
            tkinter.messagebox.showinfo(
                "Contato",
                f"E-mail: {EMAIL_CONTATO}\nWhatsApp: {WHATSAPP_CONTATO}",
                parent=self.root)

    def _iniciar_servidor_api(self) -> None:
        """Sobe a API/controle remoto local (somente em modo licenciado)."""
        if getattr(self, "_servidor_thread", None):
            return
        from navepro.config import BACKEND_URL
        from navepro.core.servidor_http import ServidorAsyncHTTP

        self._servidor_thread = ServidorAsyncHTTP()
        self._servidor_thread.ui = self._na_thread_ui
        self._servidor_thread.remoto = self._remoto_despacho
        self._aplicar_acesso_remoto()
        self._servidor_thread.iniciar()
        log.info(f"✅ Servidor async rodando em {BACKEND_URL}")

    def _parar_servidor_api(self) -> None:
        servidor = getattr(self, "_servidor_thread", None)
        if not servidor:
            return
        try:
            servidor.parar()
        except Exception as exc:
            log.exception("Falha ao parar o servidor HTTP: %s", exc)
        finally:
            self._servidor_thread = None

    def _aplicar_estado_licenca(self, licenciado: bool, motivo: str,
                                machine_id: str = "") -> None:
        """Reflete o estado da licença na interface e nas restrições."""
        demo = not bool(licenciado)
        self._licenca_licenciada = bool(licenciado)
        self._licenca_motivo = motivo or ""
        if machine_id:
            self._licenca_machine_id = machine_id
        self._modo_demonstracao = demo

        try:
            titulo = "NAVE PRO - PRO"
            if demo:
                titulo += " - MODO DEMONSTRAÇÃO"
            self.root.title(titulo)
        except tk.TclError:
            pass

        banner = getattr(self, "demo_banner", None)
        if banner is not None:
            try:
                if demo:
                    banner.configure(
                        text=("⚠️ MODO DEMONSTRAÇÃO — licença não ativada. "
                              "Limites ativos. Clique para ativar ou fale: "
                              f"{EMAIL_CONTATO} | WhatsApp {WHATSAPP_CONTATO}"))
                    banner.pack(pady=(4, 2))
                else:
                    banner.pack_forget()
            except tk.TclError:
                pass

        telao = getattr(getattr(self, "player", None), "telao", None)
        if telao is not None:
            try:
                telao.definir_marca_dagua_demo(demo)
            except Exception:
                pass

        if demo:
            self._parar_servidor_api()
            remoto = (getattr(self, "config_data", {}) or {}).get("remoto") or {}
            if remoto.get("ativo"):
                try:
                    self.alternar_controle_remoto(False)
                except Exception as exc:
                    log.exception("Falha ao desativar controle remoto: %s", exc)
        elif getattr(self, "_inicializacao_concluida", False):
            self._iniciar_servidor_api()

        log.info(("🔑 Licença: %s" if licenciado else "⚠️ Licença: %s"),
                 motivo)
