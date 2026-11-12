"""atualizacao (mixin).

Extraído de NavePro.py sem alteração de comportamento: a AppInterface
herda deste mixin.
"""

from __future__ import annotations

import os
import subprocess
import threading
import tkinter as tk
import tkinter.messagebox
import tkinter.simpledialog
import urllib.request
from tkinter import ttk

from navepro.config import APP_VERSION
from navepro.core.ambiente import _ambiente_sem_appimage, _eh_appimage, _eh_windows
from navepro.core.atualizacao import (
    FORMATO_FLATPAK,
    _buscar_release_latest,
    _comando_atualizacao_flatpak,
    _formato_instalado,
    _ler_checksum_sha256,
    _nome_arquivo_seguro,
    _pasta_downloads,
    _procurar_asset_instalador,
    _procurar_checksum_sha256,
    _rotulo_instalador,
    _sha256_do_arquivo,
    _url_asset_valida,
    _versao_nova,
)
from navepro.core.log import get_logger
from navepro.core.ssl_context import _ssl_context
from navepro.core.util_tk import (
    _centralizar_sobre,
    _habilitar_maximizar_janela,
)
from navepro.core.widgets_arredondados import TkArredondado

log = get_logger("atualizacao_ui")

# Botões e campos desenham cantos arredondados (fachada do tkinter).
tk = TkArredondado(tk)


class AtualizacaoMixin:
    def verificar_atualizacao(self, manual: bool = False) -> None:
        """Verifica (em thread) se há versão nova no GitHub e notifica."""
        def _worker() -> None:
            release = _buscar_release_latest()
            if release is None:
                if manual:
                    self.root.after(0, lambda: tkinter.messagebox.showinfo(
                        "Atualizações",
                        "Não foi possível consultar o GitHub agora.\n"
                        "Verifique sua conexão e tente novamente.",
                        parent=self.root))
                return
            versao = str(release.get('tag_name', '')).lstrip('vV')
            if not _versao_nova(versao):
                if manual:
                    self.root.after(0, lambda: tkinter.messagebox.showinfo(
                        "Atualizações",
                        f"Você já está na versão mais recente "
                        f"({APP_VERSION}).",
                        parent=self.root))
                return
            self.root.after(0, lambda: self._oferecer_atualizacao(release))

        threading.Thread(target=_worker, daemon=True).start()
    def _oferecer_atualizacao(self, release: dict) -> None:
        """Pergunta se o usuário quer atualizar e leva ao caminho certo.

        Flatpak não baixa arquivo: a atualização é `flatpak update`. AppImage
        e Windows continuam baixando o instalador para ~/Downloads.
        """
        versao = str(release.get('tag_name', '')).lstrip('vV')
        corpo = str(release.get('body') or '').strip()
        if len(corpo) > 400:
            corpo = corpo[:400].rstrip() + '…'
        formato = _formato_instalado()
        rotulo = _rotulo_instalador(formato)
        pergunta = (
            f"NavePro {APP_VERSION} → {versao}\n\n"
            "Uma nova versão está disponível no GitHub.\n"
        )
        if corpo:
            pergunta += f"\nNovidades:\n{corpo}\n"
        if formato == FORMATO_FLATPAK:
            pergunta += (
                "\nO NavePro está instalado como Flatpak, então a "
                "atualização será feita\npelo próprio Flatpak "
                "(sem baixar arquivo).\n\n"
                "Deseja atualizar agora?"
            )
        else:
            pergunta += f"\nDeseja baixar o novo {rotulo} agora?"
        if not tkinter.messagebox.askyesno(
                "🔄 Atualização disponível", pergunta, parent=self.root):
            return
        if formato == FORMATO_FLATPAK:
            self._atualizar_como_flatpak(versao)
            return
        asset = _procurar_asset_instalador(release)
        if asset is None:
            tkinter.messagebox.showwarning(
                "Atualização",
                f"O release não contém um arquivo {rotulo}.",
                parent=self.root)
            return
        self._baixar_atualizacao(
            versao,
            str(asset.get('browser_download_url', '')),
            str(asset.get('name', f'NavePro-{versao}{rotulo}')),
            release,
        )
    def _atualizar_como_flatpak(self, versao: str) -> None:
        """Roda `flatpak update` no host e mostra o resultado."""
        comando = _comando_atualizacao_flatpak()
        texto_cmd = ' '.join(comando[2:])

        janela = tk.Toplevel(self.root)
        janela.title("⬇️ Atualizando via Flatpak")
        janela.geometry("560x300")
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        _centralizar_sobre(janela, self.root)
        _habilitar_maximizar_janela(janela, area=self._area_monitor_operador())
        janela.grab_set()

        saida = tk.Text(janela, height=9, font=("monospace", 9),
                        bg='#161b22', fg='#c9d1d9', bd=0,
                        highlightthickness=0, wrap='word')
        saida.pack(fill='both', expand=True, padx=10, pady=10)
        saida.insert('end', f"$ {texto_cmd}\n\n")
        saida.configure(state='disabled')

        def _escrever(linha: str) -> None:
            saida.configure(state='normal')
            saida.insert('end', linha)
            saida.see('end')
            saida.configure(state='disabled')

        def _worker() -> None:
            codigo = -1
            try:
                proc = subprocess.run(
                    comando, capture_output=True, text=True,
                    stdin=subprocess.DEVNULL, timeout=600,
                    env=_ambiente_sem_appimage(), cwd='/',
                )
                codigo = proc.returncode
                linhas = [linha for linha in
                          ((proc.stdout or '') + (proc.stderr or '')).splitlines()
                          if linha.strip()]
                if not linhas:
                    linhas = ["(sem saída)"]
                for linha in linhas:
                    self.root.after(0, lambda linha=linha: _escrever(linha + "\n"))
            except Exception as e:
                codigo = -1
                self.root.after(
                    0, lambda e=e: _escrever(f"Falha ao executar: {e}\n"))
            finally:
                self.root.after(0, lambda: _finalizar(codigo))

        def _finalizar(codigo: int) -> None:
            janela.grab_release()
            janela.destroy()
            if codigo == 0:
                tkinter.messagebox.showinfo(
                    "✅ Atualização concluída",
                    f"O NavePro foi atualizado para a versão {versao}.\n\n"
                    "Feche e abra o NavePro para usar a versão nova.",
                    parent=self.root)
            else:
                tkinter.messagebox.showerror(
                    "Não foi possível atualizar",
                    "O comando do Flatpak falhou.\n\n"
                    "Rode no terminal:\n\n"
                    f"  {texto_cmd}\n\n"
                    "Se pedir senha de administrador, o NavePro está "
                    "instalado no sistema (não no seu usuário) e a "
                    "atualização precisa ser feita por um administrador.",
                    parent=self.root)

        tk.Button(janela, text="Fechar", font=("Arial", 11, "bold"),
                  bg='#21262d', fg='#c9d1d9', activebackground='#30363d',
                  command=lambda: (janela.grab_release(), janela.destroy()),
                  cursor='hand2').pack(pady=(0, 10))

        threading.Thread(target=_worker, daemon=True).start()
    def _baixar_atualizacao(self, versao: str, url: str,
                            nome_arquivo: str,
                            release: dict | None = None) -> None:
        """Baixa o novo instalador para ~/Downloads com barra de progresso."""
        # O nome vem do JSON da API: sem basename, um nome "..\..\evil"
        # escaparia de ~/Downloads (path traversal).
        nome_arquivo = (_nome_arquivo_seguro(nome_arquivo)
                        or f'NavePro-{versao}{_rotulo_instalador()}')
        destino = os.path.join(_pasta_downloads(), nome_arquivo)

        janela = tk.Toplevel(self.root)
        janela.title("⬇️ Baixando atualização")
        janela.geometry("440x150")
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        _centralizar_sobre(janela, self.root)
        janela.grab_set()

        def _atualizar_progresso(pct: int, baixado: int, total: int) -> None:
            try:
                progresso['value'] = pct
                lbl.config(
                    text=f"{pct}%  ({baixado // 1024 // 1024} de "
                         f"{total // 1024 // 1024} MB)"
                )
            except tk.TclError:
                pass

        tk.Label(janela, text=f"Baixando {nome_arquivo}…",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117'
                 ).pack(pady=(18, 6))
        progresso = ttk.Progressbar(janela, mode='determinate', length=380)
        progresso.pack(pady=6)
        lbl = tk.Label(janela, text="0%", font=("Arial", 9), fg='#c9d1d9',
                       bg='#0d1117')
        lbl.pack(pady=2)

        def _worker() -> None:
            try:
                if not _url_asset_valida(url):
                    raise ValueError(
                        "A URL do instalador é inválida (não é HTTPS).")
                # Verificação de integridade opcional e retroativa: se o
                # release publicar um .sha256 ao lado do instalador, o
                # arquivo baixado é conferido; releases sem .sha256 seguem
                # como antes (HTTPS verificado, sem execução automática).
                hex_esperado = None
                url_checksum = _procurar_checksum_sha256(
                    release, nome_arquivo)
                if url_checksum:
                    hex_esperado = _ler_checksum_sha256(url_checksum)
                req = urllib.request.Request(url, headers={
                    "User-Agent": f"NavePro/{APP_VERSION}"})
                with urllib.request.urlopen(req, timeout=120,
                                            context=_ssl_context()) as resp:
                    if not str(getattr(resp, 'url', '')).lower().startswith(
                            'https://'):
                        raise ValueError(
                            "O download foi redirecionado para fora do "
                            "HTTPS; atualização cancelada.")
                    total = int(resp.headers.get('Content-Length', 0) or 0)
                    temporario = destino + '.part'
                    baixado = 0
                    with open(temporario, 'wb') as f:
                        while True:
                            bloco = resp.read(8192)
                            if not bloco:
                                break
                            f.write(bloco)
                            baixado += len(bloco)
                            if total > 0:
                                pct = int(baixado * 100 / total)
                                self.root.after(
                                    0, lambda p=pct, b=baixado, t=total:
                                    _atualizar_progresso(p, b, t))
                if hex_esperado is not None and \
                        _sha256_do_arquivo(temporario) != hex_esperado:
                    try:
                        os.remove(temporario)
                    except OSError:
                        pass
                    raise ValueError(
                        "A verificação de integridade do arquivo baixado "
                        "falhou; a atualização foi cancelada.")
                os.replace(temporario, destino)
                if not _eh_windows():
                    os.chmod(destino, 0o744)
                self.root.after(0, lambda: self._instrucoes_troca_instalador(
                    destino))
            except Exception as e:
                log.exception(f"⚠️  Erro ao baixar atualização: {e}")
                self.root.after(0, lambda e=e: (janela.destroy(),
                             tkinter.messagebox.showerror(
                                 "Erro",
                                 f"Não foi possível baixar a atualização:\n{e}",
                                 parent=self.root)))
            else:
                janela.after(300, janela.destroy)

        threading.Thread(target=_worker, daemon=True).start()
    def _instrucoes_troca_instalador(self, destino: str) -> None:
        """Mostra como substituir o instalador antigo pelo baixado e abre Downloads."""
        rotulo = _rotulo_instalador()
        if rotulo == ".exe":
            msg = (
                "O novo executável foi salvo em:\n\n"
                f"  {destino}\n\n"
                "Para instalar:\n"
                "1. Feche o NavePro.\n"
                "2. Substitua o arquivo atual por este novo "
                "(mova-o para o mesmo lugar do antigo).\n"
                "3. Abra o novo arquivo para rodar a versão atualizada.\n\n"
                "Dica: o NavePro é portátil — basta copiar o .exe novo."
            )
        else:
            msg = (
                "O novo AppImage foi salvo em:\n\n"
                f"  {destino}\n\n"
                "Para instalar:\n"
                "1. Feche o NavePro.\n"
                "2. Substitua o AppImage atual por este novo arquivo "
                "(mova-o para o mesmo lugar do antigo).\n"
                "3. Dê permissão de execução se precisar:\n"
                "     chmod +x \"<novo arquivo>\"\n"
                "4. Abra o novo arquivo para rodar a versão atualizada."
            )
            if not _eh_appimage():
                msg += (
                    "\n\nObs.: você está rodando o NavePro a partir do "
                    "código-fonte,\n então o AppImage baixado é só uma "
                    "cópia para usar\n à vontade — não substitui nada."
                )
        tkinter.messagebox.showinfo("✅ Download concluído", msg,
                                    parent=self.root)
        try:
            if _eh_windows():
                os.startfile(_pasta_downloads())
            else:
                subprocess.Popen(['xdg-open', _pasta_downloads()],
                                 stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        except Exception:
            pass
