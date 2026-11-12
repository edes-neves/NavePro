"""Janela de janela_transferencia do painel do operador (mixin).

Extraída de NavePro.py sem alteração de comportamento: a AppInterface
herda deste mixin para montar a janela.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
import tkinter.messagebox
import tkinter.simpledialog
from collections.abc import Callable
from typing import Any

from navepro.core.anuncios import (
    _atualizar_anuncio_db,
    _copiar_arquivo_uploads,
    _excluir_anuncios_db,
    _inserir_anuncio_db,
    _listar_anuncios_db,
)
from navepro.core.log import get_logger
from navepro.core.paths import _aplicar_icone_janela
from navepro.core.servicos import _carregar_servicos_json, _salvar_servicos_json
from navepro.core.transferencia import (
    EXTENSAO_TRANSFERENCIA,
    exportar_transferencia,
    importar_transferencia,
)
from navepro.core.transferencia import (
    _nome_arquivo as _nome_arquivo_transferencia,
)
from navepro.core.util_tk import (
    _centralizar_sobre,
    _habilitar_maximizar_janela,
)
from navepro.core.widgets_arredondados import TkArredondado
from navepro.ui.apoio import _escolher_arquivos_usuario

log = get_logger("janela_transferencia")

# Botões e campos desenham cantos arredondados (fachada do tkinter).
tk = TkArredondado(tk)


class JanelaTransferenciaMixin:
    def janela_transferencia(
            self, parent: tk.Misc | None = None) -> None:
        """Janela para levar anúncios e ordens de serviço a outro computador.

        Exporta um arquivo .navepro (anúncios + ordens + mídias) e importa de
        volta. A importação cria um backup antes de mexer em qualquer coisa.
        """
        janela = tk.Toplevel(self.root)
        janela.title("🔄 Transferir Anúncios e Ordens de Serviço")
        janela.geometry("640x620")
        janela.configure(bg='#0d1117')
        if parent is not None:
            janela.transient(parent)
        _centralizar_sobre(janela, parent if parent is not None else self.root)
        _habilitar_maximizar_janela(janela, area=self._area_monitor_operador())
        _aplicar_icone_janela(janela)

        estado = {"ocupado": False}
        var_status = tk.StringVar(value="")
        var_modo = tk.StringVar(value="somar")
        botoes: list[tk.Widget] = []

        def _caixa(titulo: str) -> tk.Frame:
            box = tk.Frame(janela, bg='#161b22', highlightthickness=1,
                           highlightbackground='#30363d')
            box.pack(fill='x', padx=14, pady=6, ipady=8)
            tk.Label(box, text=titulo, font=("Arial", 12, "bold"),
                     fg='#f0c040', bg='#161b22').pack(anchor='w', padx=12,
                                                      pady=(8, 2))
            return box

        def _botao(pai, texto: str, bg: str, fg: str, comando) -> tk.Button:
            b = tk.Button(pai, text=texto, font=("Arial", 11, "bold"),
                          bg=bg, fg=fg, activebackground=bg,
                          activeforeground='white', command=comando,
                          cursor='hand2', padx=12, pady=5)
            b.pack(side='left', padx=6)
            botoes.append(b)
            return b

        # ── Explicação ──
        tk.Label(
            janela,
            text=("Gere um arquivo .navepro no computador de origem e importe-o "
                  "no outro.\nVem junto: os anúncios, as ordens de serviço "
                  "(com os itens\napontando para os anúncios certos) e as mídias "
                  "usadas pelos anúncios.\n\n🛡️ Antes de importar, o NavePro "
                  "salva um backup em ~/.navepro/backups —\nnada do que já "
                  "existe é apagado sem esse backup."),
            justify='left', font=("Arial", 10), fg='#c9d1d9', bg='#0d1117',
            wraplength=590).pack(anchor='w', padx=18, pady=(12, 2))

        # ── Exportar ──
        box_exp = _caixa("📤  Exportar deste computador")
        tk.Label(box_exp, font=("Arial", 10), fg='#8b949e', bg='#161b22',
                 justify='left', wraplength=560,
                 text=("Cria um arquivo para levar em um pendrive, e-mail ou "
                       "nuvem. Ele fica, por\npadrão, na pasta que você "
                       "escolher (sugerimos a sua pasta pessoal).")
                 ).pack(anchor='w', padx=12)

        def _exportar():
            if estado["ocupado"]:
                return
            # Seletor do próprio app (e não o diálogo do sistema): mostra só as
            # pastas do usuário, sem as ocultas, e não pisca ao abrir.
            escolhidos = _escolher_arquivos_usuario(
                janela, "Salvar transferência para levar a outro computador",
                pasta_inicial=os.path.expanduser("~"),
                sufixos=(EXTENSAO_TRANSFERENCIA, ".zip"),
                nome_para_salvar=_nome_arquivo_transferencia(
                    prefixo="NavePro-Transferencia"))
            if not escolhidos:
                return
            destino = escolhidos[0]
            incluir = tkinter.messagebox.askyesno(
                "📤 Incluir as mídias dos anúncios?",
                "Incluir imagens, PDFs, áudio e vídeo usados nos anúncios?\n\n"
                "✅ Sim (recomendado): o arquivo fica maior, mas os anúncios\n"
                "    funcionam no outro computador com as mídias.\n\n"
                "⚠️ Não: o arquivo fica pequeno, mas as mídias NÃO vêm junto\n"
                "    (os textos e as ordens vêm de qualquer forma).",
                parent=janela)
            _rodar(
                "Exportando…",
                lambda prog: exportar_transferencia(
                    destino, _listar_anuncios_db(), _carregar_servicos_json(),
                    incluir_midia=incluir, progresso=prog),
                _exportou)

        _botao(box_exp, "📤  Exportar…", '#1f6feb', 'white', _exportar)

        # ── Importar ──
        box_imp = _caixa("📥  Importar para este computador")
        tk.Label(box_imp, font=("Arial", 10), fg='#8b949e', bg='#161b22',
                 justify='left', wraplength=560,
                 text="Escolha o arquivo .navepro e o que fazer com o que já "
                      "existe aqui:"
                 ).pack(anchor='w', padx=12)

        MODOS = (
            ("somar",
             "➕  Somar — acrescenta o que ainda não existe (recomendado)"),
            ("atualizar",
             "🔄  Atualizar — troca o conteúdo do anúncio/ordem de mesmo nome"),
            ("substituir",
             "♻️  Substituir tudo — apaga os anúncios e ordens deste PC"),
        )
        for valor, rotulo in MODOS:
            tk.Radiobutton(box_imp, text=rotulo, variable=var_modo,
                           value=valor, font=("Arial", 10), fg='#c9d1d9',
                           bg='#161b22', selectcolor='#161b22',
                           activebackground='#161b22', activeforeground='#f0c040',
                           cursor='hand2', anchor='w'
                           ).pack(fill='x', padx=14, pady=1)

        def _importar():
            if estado["ocupado"]:
                return
            escolhidos = _escolher_arquivos_usuario(
                janela, "Escolher transferência para importar",
                pasta_inicial=os.path.expanduser("~"),
                sufixos=(EXTENSAO_TRANSFERENCIA, ".zip"))
            if not escolhidos:
                return
            arquivo = escolhidos[0]
            modo = var_modo.get()
            if modo == "substituir" and not tkinter.messagebox.askyesno(
                    "♻️  Substituir tudo mesmo?",
                    "Os anúncios e as ordens de serviço DESTE computador serão\n"
                    "apagados e trocados pelos que estão no arquivo.\n\n"
                    "🛡️ Antes disso, o NavePro salva um backup em\n"
                    "~/.navepro/backups.\n\nTem certeza que deseja continuar?",
                    parent=janela):
                return
            _rodar(
                "Importando…",
                lambda prog: importar_transferencia(
                    arquivo, _carregar_servicos_json(),
                    listar_anuncios=_listar_anuncios_db,
                    inserir_anuncio=_inserir_anuncio_db,
                    atualizar_anuncio=_atualizar_anuncio_db,
                    copiar_midia=_copiar_arquivo_uploads,
                    excluir_anuncios=_excluir_anuncios_db,
                    salvar_servicos=_salvar_servicos_json,
                    modo=modo, progresso=prog),
                _importou)

        _botao(box_imp, "📥  Importar…", '#8b5cf6', 'white', _importar)

        # ── Rodapé ──
        tk.Label(janela, textvariable=var_status, font=("Arial", 10, "bold"),
                 fg='#f0c040', bg='#0d1117', anchor='w', wraplength=600,
                 justify='left').pack(fill='x', padx=18, pady=(10, 2))
        tk.Button(janela, text="Fechar", font=("Arial", 11, "bold"),
                  bg='#21262d', fg='#c9d1d9', activebackground='#30363d',
                  command=janela.destroy, cursor='hand2', padx=16, pady=4,
                  ).pack(pady=(2, 14))

        def _exportou(resumo: dict):
            midia = resumo.get("midia") or 0
            linhas = [f"Arquivo salvo em:\n\n{resumo['destino']}",
                      f"\n{resumo['anuncios']} anúncio(s) e "
                      f"{resumo['servicos']} ordem(ns) de serviço."]
            if midia:
                linhas.append(f"{midia} mídia(s) foram incluídas.")
            elif resumo["anuncios"]:
                linhas.append("\nNenhuma mídia foi incluída (você escolheu "
                              "não incluir).")
            tkinter.messagebox.showinfo(
                "✅ Transferência exportada", "\n".join(linhas), parent=janela)

        def _importou(resumo: dict):
            self._reabrir_janelas_de_ordem()
            linhas = [
                f"Anúncios novos: {resumo['anuncios_novos']}",
                f"Anúncios atualizados: {resumo['anuncios_atualizados']}",
                f"Anúncios mantidos como estavam: {resumo['anuncios_ignorados']}",
                f"Ordens de serviço novas: {resumo['servicos_novos']}",
                f"Ordens atualizadas: {resumo['servicos_atualizados']}",
                f"Mídias copiadas para este computador: {resumo['midia_copiada']}",
            ]
            if resumo.get("backup"):
                linhas.append(f"\n🛡️ Backup do que estava aqui antes:\n"
                              f"{resumo['backup']}")
            if resumo.get("avisos"):
                linhas.append("\nAvisos:\n• " +
                              "\n• ".join(resumo["avisos"][:8]))
            tkinter.messagebox.showinfo(
                "✅ Importação concluída", "\n".join(linhas), parent=janela)

        def _rodar(titulo: str, acao: Callable[[Callable[[str], None]], Any],
                   ao_terminar: Callable[[Any], None]) -> None:
            """Roda a exportação/importação em segundo plano (não trava a tela)."""
            if estado["ocupado"]:
                return
            estado["ocupado"] = True
            var_status.set(titulo)
            for b in botoes:
                b.config(state='disabled')
            res: dict[str, Any] = {}

            def _trabalho():
                try:
                    res["valor"] = acao(
                        lambda msg: res.__setitem__("progresso", msg))
                except Exception as e:  # noqa: BLE001 - mostra na interface
                    log.exception(f"Erro na transferência: {e}")
                    res["erro"] = e

            def _conferir():
                if "progresso" in res:
                    var_status.set(res["progresso"])
                if "erro" in res:
                    _fim()
                    tkinter.messagebox.showerror(
                        "❌ Não foi possível concluir",
                        f"{res['erro']}\n\nNada foi alterado.", parent=janela)
                    return
                if "valor" in res:
                    _fim()
                    ao_terminar(res["valor"])
                    return
                janela.after(150, _conferir)

            def _fim():
                estado["ocupado"] = False
                var_status.set("")
                for b in botoes:
                    b.config(state='normal')

            threading.Thread(target=_trabalho, daemon=True).start()
            janela.after(150, _conferir)
