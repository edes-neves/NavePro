"""Janela de janela_ordem_servico do painel do operador (mixin).

Extraída de NavePro.py sem alteração de comportamento: a AppInterface
herda deste mixin para montar a janela.
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
import tkinter.messagebox
import tkinter.simpledialog
from datetime import datetime
from tkinter import ttk

from license_manager import (
    LIMITE_DEMO_ITENS_PROJECAO,
    modo_demonstracao,
)
from navepro.config import EXTENSOES_AUDIO, EXTENSOES_VIDEO
from navepro.core.anuncios import (
    _buscar_anuncio_por_ref,
    _buscar_anuncio_por_termo,
    _listar_anuncios_db,
)
from navepro.core.banco import db_query
from navepro.core.fontes_pil import _texto_simples
from navepro.core.inicializacao import _sincronizar_uploads_midia
from navepro.core.log import get_logger
from navepro.core.servicos import (
    _SERVICO_ITEM_REPRODUZINDO,
    _SERVICO_PROXIMO_ITEM,
    _analisar_faixa_versiculos,
    _carregar_servicos_json,
    _faixa_versiculo_item,
    _formatar_duracao_segundos,
    _migrar_servicos_do_banco,
    _proximo_id_servico_livre,
    _salvar_servicos_json,
    definir_manter_videos_servico,
    definir_marcar_reproduzidos,
    esquecer_manter_videos_servico,
    servico_manter_videos,
)
from navepro.core.slides import (
    _buscar_hino_por_termo,
    _buscar_hino_por_termo_ou_id,
    _buscar_midia_por_termo,
    _buscar_midia_por_termo_ou_id,
)
from navepro.core.textos import _numero_do_titulo
from navepro.core.util_tk import (
    _centralizar_sobre,
    _habilitar_maximizar_janela,
    _limitar_ao_monitor,
)
from navepro.core.widgets_arredondados import TkArredondado
from navepro.core.youtube import (
    _eh_url_youtube,
    _obter_info_youtube,
    obter_video_youtube,
    video_youtube_baixado,
)
from navepro.ui.apoio import (
    _colar_texto_campo,
    _escolher_arquivos_usuario,
    _menu_contexto_campo,
)

log = get_logger("janela_ordem_servico")

# Consultas de duração (ffprobe/yt-dlp) rodam em segundo plano. Limitar a
# concorrência evita abrir um subprocesso por item de uma vez só (a lista
# pode ter dezenas de mídias) e mantém a interface responsiva.
_DURACAO_MAX_WORKERS = 2

# Cliques seguidos na caixinha "reproduzido" são agrupados antes de gravar
# o servicos.json (evita um read+fsync por clique sem perder a marcação).
_MARCACAO_SALVAR_MS = 500

# Contagem regressiva: rápida enquanto há player tocando; em repouso a
# checagem é mais espaçada (só para detectar quando a reprodução começa).
_CONTAGEM_ATIVA_MS = 500
_CONTAGEM_REPOUSO_MS = 1000

# Metadados do YouTube: espera o operador parar de digitar, mas um link
# colado consulta quase de imediato (é o caso mais comum).
_YOUTUBE_INFO_DEBOUNCE_MS = 700
_YOUTUBE_INFO_COLAR_MS = 100
# Ao salvar com uma consulta já em andamento, espera o resultado dela em
# vez de disparar uma segunda consulta ao yt-dlp.
_YOUTUBE_INFO_ESPERA_S = 16.0

# Botões e campos desenham cantos arredondados (fachada do tkinter).
tk = TkArredondado(tk)


class JanelaOrdemServicoMixin:
    def _baixar_video_youtube_ui(self, parent, url: str) -> tuple[str | None, str]:
        """Baixa o vídeo com uma janela de progresso e devolve (caminho, erro).

        O download roda em uma thread para a interface continuar respondendo;
        a janela só fecha quando o yt-dlp termina (ou falha). O `parent` deve
        ser a janela que está na frente (Ordem de Projeção/editor): no GNOME
        do Ubuntu 26.04 uma Toplevel transient da janela principal fica
        atrás da janela de Ordem de Projeção e o operador não vê o progresso.
        """
        # Já baixado nesta sessão: reproduz direto, sem criar janela nenhuma
        # (nem por um frame). Só mostra o progresso quando há download real.
        caminho_existente = video_youtube_baixado(url)
        if caminho_existente:
            return caminho_existente, ""
        try:
            if parent is None or not parent.winfo_exists():
                parent = getattr(self, "root", None)
        except (AttributeError, tk.TclError):
            parent = getattr(self, "root", None)
        janela = tk.Toplevel(parent)
        janela.title("📥 Baixando vídeo do YouTube")
        janela.configure(bg='#0d1117')
        if parent is not None:
            janela.transient(parent)
        janela.resizable(False, False)
        janela.protocol("WM_DELETE_WINDOW", lambda: None)
        try:
            _centralizar_sobre(janela, parent)
        except Exception:
            pass

        main = tk.Frame(janela, bg='#0d1117')
        main.pack(fill='both', expand=True, padx=24, pady=18)
        tk.Label(main, text="📥 Baixando vídeo do YouTube...",
                 bg='#0d1117', fg='#f0c040',
                 font=("Arial", 12, "bold")).pack(anchor='w')
        tk.Label(main, text=url, bg='#0d1117', fg='#8b949e',
                 font=("Arial", 9), wraplength=520,
                 justify='left').pack(anchor='w', pady=(6, 10))
        barra = ttk.Progressbar(main, mode='determinate', maximum=100,
                                length=520)
        barra.pack(fill='x')
        rodape = tk.Frame(main, bg='#0d1117')
        rodape.pack(fill='x', pady=(6, 0))
        lbl_pct = tk.Label(rodape, text="0%", bg='#0d1117', fg='#f0c040',
                           font=("Arial", 11, "bold"))
        lbl_pct.pack(side='left')
        lbl_status = tk.Label(rodape, text="Preparando...",
                              bg='#0d1117', fg='#c9d1d9',
                              font=("Arial", 9), wraplength=440,
                              justify='left')
        lbl_status.pack(side='left', padx=(10, 0))
        tk.Label(main, text=("O vídeo será reproduzido do computador. "
                             "Aguarde o download terminar."),
                 bg='#0d1117', fg='#8b949e',
                 font=("Arial", 9)).pack(anchor='w', pady=(8, 0))

        # Garante que a janela seja mapeada e fique na frente antes do grab.
        # Em Wayland/mutter o mapeamento é assíncrono: sem wait_visibility
        # o grab_set pode valer para uma janela ainda não visível.
        try:
            janela.deiconify()
            janela.lift()
            janela.update_idletasks()
        except tk.TclError:
            pass
        try:
            janela.wait_visibility()
        except tk.TclError:
            pass
        try:
            janela.grab_set()
        except tk.TclError:
            pass

        def _soltar_topmost() -> None:
            try:
                janela.attributes("-topmost", False)
            except tk.TclError:
                pass

        try:
            janela.focus_force()
            janela.attributes("-topmost", True)
            janela.after(250, _soltar_topmost)
        except tk.TclError:
            pass

        resultado: dict[str, str] = {}
        concluido = threading.Event()
        fila_progresso: queue.Queue[tuple[float, str]] = queue.Queue()

        def _ao_progresso(percentual: float, texto: str) -> None:
            fila_progresso.put((float(percentual), texto or ""))

        def _trabalho() -> None:
            try:
                resultado["caminho"] = obter_video_youtube(
                    url, ao_progresso=_ao_progresso)
            except Exception as exc:
                resultado["erro"] = str(exc)
                log.exception("Falha ao baixar vídeo do YouTube: %s", exc)
            finally:
                concluido.set()

        threading.Thread(target=_trabalho, daemon=True,
                         name="navepro-baixar-youtube").start()

        def _drenar_progresso() -> None:
            while True:
                try:
                    percentual, texto = fila_progresso.get_nowait()
                except queue.Empty:
                    return
                try:
                    barra['value'] = max(0.0, min(100.0, percentual))
                    lbl_pct.config(text=f"{percentual:.0f}%")
                    if texto:
                        lbl_status.config(text=texto)
                except tk.TclError:
                    return

        def _verificar() -> None:
            _drenar_progresso()
            if concluido.is_set():
                _drenar_progresso()
                try:
                    barra['value'] = 100
                    lbl_pct.config(text="100%")
                except tk.TclError:
                    pass
                try:
                    janela.destroy()
                except tk.TclError:
                    pass
                return
            try:
                janela.after(100, _verificar)
            except tk.TclError:
                pass

        janela.after(100, _verificar)
        try:
            janela.wait_window()
        finally:
            try:
                janela.destroy()
            except tk.TclError:
                pass
        return resultado.get("caminho"), resultado.get("erro", "")

    def janela_ordem_servico(self) -> None:
        """Abre a janela de planejamento de ordem de serviço.

        As ordens são salvas em ~/.navepro/servicos.json (nunca importam
        vídeo/slides). As programações são separadas por dia da semana
        (Domingo a Sábado); dentro de cada dia pode haver várias. Oferece
        criar e editar programações (o nome pode ser renomeado direto na
        caixa "Programação", com salvamento automático), excluir
        programações (com confirmação) e itens (botão da barra ou botão
        direito na lista) e arrastar e soltar os itens para reordená-los.
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
        janela.title("📋 Ordem de Projeção")
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

        def _atualizar_botao_max(maximizada: bool) -> None:
            try:
                btn_max.configure(text="⛶ Restaurar" if maximizada
                                  else "⛶ Maximizar")
            except (tk.TclError, NameError):
                pass

        alternar_maximizar = _habilitar_maximizar_janela(
            janela, area=self._area_monitor_operador(),
            ao_mudar_estado=_atualizar_botao_max)

        def _alternar_maximizar() -> None:
            alternar_maximizar()

        main = tk.Frame(janela, bg='#0d1117')
        main.pack(fill='both', expand=True, padx=15, pady=15)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        tk.Label(main, text="📋 Ordem de Projeção",
                 font=("Arial", 16, "bold"), fg='#f0c040', bg='#0d1117'
                 ).grid(row=0, column=0, sticky='ew', pady=(0, 10))

        # ── Dias da semana + programações do dia ──
        _CHAVES_DIA = ("domingo", "segunda", "terca", "quarta",
                       "quinta", "sexta", "sabado")
        _ROTULOS_DIA = ("Domingo", "Segunda", "Terça", "Quarta",
                        "Quinta", "Sexta", "Sábado")

        def _normalizar_dia(valor) -> str:
            texto = (valor or "").strip().lower()
            texto = (texto.replace("ç", "c").replace("á", "a")
                     .replace("ã", "a").replace("é", "e")
                     .replace("í", "i").replace("ó", "o").replace("ú", "u"))
            return texto if texto in _CHAVES_DIA else ""

        def _dia_de_hoje() -> str:
            # datetime.weekday(): segunda=0 ... domingo=6.
            return _CHAVES_DIA[(datetime.now().weekday() + 1) % 7]

        dia_salvo = _normalizar_dia(dados.get("_dia_selecionado"))
        dia_selecionado = [dia_salvo or _dia_de_hoje()]

        serv_frame = tk.Frame(main, bg='#161b22')
        serv_frame.grid(row=1, column=0, sticky='ew', pady=5, ipady=5)

        dias_frame = tk.Frame(serv_frame, bg='#161b22')
        dias_frame.pack(fill='x')

        botoes_dia: dict[str, object] = {}

        def _atualizar_botoes_dia() -> None:
            for chave, botao in botoes_dia.items():
                selecionado = chave == dia_selecionado[0]
                try:
                    botao.configure(
                        bg='#6e40c9' if selecionado else '#21262d',
                        fg='white' if selecionado else '#c9d1d9',
                        activebackground=('#8b5cf6' if selecionado
                                          else '#30363d'),
                        activeforeground='white')
                except tk.TclError:
                    pass

        for _chave, _rotulo in zip(_CHAVES_DIA, _ROTULOS_DIA, strict=True):
            _botao = tk.Button(
                dias_frame, text=_rotulo, font=("Arial", 10, "bold"),
                bg='#21262d', fg='#c9d1d9', activebackground='#30363d',
                activeforeground='white',
                command=lambda c=_chave: _selecionar_dia(c),
                cursor='hand2', padx=7, pady=3)
            _botao.pack(side='left', padx=2)
            botoes_dia[_chave] = _botao

        btn_max = tk.Button(
            dias_frame, text="⛶ Maximizar", font=("Arial", 10, "bold"),
            bg='#21262d', fg='#f0c040', activebackground='#30363d',
            activeforeground='#f0c040', command=_alternar_maximizar,
            cursor='hand2', padx=10, pady=3)
        btn_max.pack(side='right', padx=8)

        prog_frame = tk.Frame(serv_frame, bg='#161b22')
        prog_frame.pack(fill='x', pady=(5, 0))

        tk.Label(prog_frame, text="Programação:", fg='#f0c040',
                 bg='#161b22', font=("Arial", 11, "bold")
                 ).pack(side='left', padx=8)

        servico_var = tk.StringVar()
        combo_servico = ttk.Combobox(prog_frame, textvariable=servico_var,
                                      width=40, font=("Arial", 11), state='readonly')
        # Mantém a StringVar viva enquanto o combobox existir; sem esta
        # referência o garbage collector apaga a variável Tcl e a programação
        # selecionada some da tela (a lista continua carregada).
        combo_servico._navepro_servico_var = servico_var
        combo_servico.pack(side='left', padx=5)

        manter_videos_var = tk.BooleanVar(value=False)
        chk_manter = tk.Checkbutton(
            serv_frame, text="Manter vídeos do YouTube desta programação",
            variable=manter_videos_var,
            command=lambda: _alternar_manter_videos(),
            bg='#161b22', fg='#c9d1d9', activebackground='#161b22',
            activeforeground='#f0c040', selectcolor='#6e40c9',
            disabledforeground='#6b7280',
            highlightthickness=0, bd=0, font=("Arial", 10, "bold"))
        chk_manter._navepro_var = manter_videos_var
        chk_manter.pack(anchor='w', padx=8, pady=(4, 0))

        marcar_reproduzidos_var = tk.BooleanVar(
            value=bool(dados.get("_marcar_reproduzidos", False)))

        def _alternar_marcar_reproduzidos() -> None:
            ativo = bool(marcar_reproduzidos_var.get())
            dados["_marcar_reproduzidos"] = ativo
            if not definir_marcar_reproduzidos(ativo):
                log.debug("Não foi possível guardar a opção de marcar "
                          "itens reproduzidos em servicos.json.")

        chk_marcar = tk.Checkbutton(
            prog_frame, text="Marcar reproduzidos",
            variable=marcar_reproduzidos_var,
            command=_alternar_marcar_reproduzidos,
            bg='#161b22', fg='#c9d1d9', activebackground='#161b22',
            activeforeground='#f0c040', selectcolor='#6e40c9',
            highlightthickness=0, bd=0, font=("Arial", 10, "bold"))
        chk_marcar._navepro_var = marcar_reproduzidos_var
        chk_marcar.pack(side='right', padx=8)

        servico_selecionado_id = [None]

        def _rotulo_servico(s: dict) -> str:
            return str(s.get("nome") or "").strip()

        def _servico_atual() -> dict | None:
            sid = servico_selecionado_id[0]
            if not sid:
                return None
            return next((s for s in dados["servicos"] if s.get("id") == sid), None)

        def _atualizar_manter_videos() -> None:
            serv = _servico_atual()
            ativo = bool(servico_manter_videos(serv)) if serv else False
            try:
                manter_videos_var.set(ativo)
                chk_manter.configure(state='normal' if serv else 'disabled')
            except tk.TclError:
                pass

        def _alternar_manter_videos() -> None:
            serv = _servico_atual()
            if serv is None:
                _atualizar_manter_videos()
                return
            ativo = bool(manter_videos_var.get())
            anterior = servico_manter_videos(serv)
            if not definir_manter_videos_servico(serv.get("id"), ativo):
                try:
                    manter_videos_var.set(anterior)
                except tk.TclError:
                    pass
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar a opção de manter os "
                    "vídeos do YouTube em servicos.json.", parent=janela)

        def _dia_do_servico(s: dict) -> str:
            """Dia da programação (legado: infere pela data de criação)."""
            dia = _normalizar_dia(s.get("dia"))
            if dia:
                return dia
            criado = (s.get("criado_em") or "").strip()
            try:
                data = datetime.fromisoformat(criado).date()
                return _CHAVES_DIA[(data.weekday() + 1) % 7]
            except (TypeError, ValueError):
                # Programação antiga sem data: fica no Domingo para não
                # desaparecer da janela.
                return "domingo"

        def _ordenar_servicos():
            dia = dia_selecionado[0]
            servicos = [s for s in dados["servicos"]
                        if _dia_do_servico(s) == dia]
            return sorted(
                servicos,
                key=lambda s: s.get('id') or 0,
                reverse=True)

        def _carregar_servicos(escolher: bool = True):
            ord_servicos = _ordenar_servicos()
            opcoes = [_rotulo_servico(s) for s in ord_servicos]
            combo_servico['values'] = opcoes
            ids = [s['id'] for s in ord_servicos]
            combo_servico._servico_ids = ids
            if opcoes and escolher:
                # Restaura a programação escolhida na última sessão. Se ela
                # não existir mais (ou for de outro dia), cai na primeira.
                salvo = dados.get("_servico_selecionado")
                combo_servico.current(
                    ids.index(salvo) if salvo in ids else 0)
            elif not opcoes:
                combo_servico.set("")
                servico_selecionado_id[0] = None

        def _on_servico_select(event=None):
            sel = combo_servico.get()
            if not sel:
                return
            idx = combo_servico.current()
            ids = getattr(combo_servico, '_servico_ids', [])
            if idx >= 0 and idx < len(ids):
                sid = ids[idx]
                servico_selecionado_id[0] = sid
                # Trocar a programação na lista cancela uma edição inline em
                # andamento (o texto digitado não pertence à nova).
                _cancelar_renomear_sem_salvar()
                # Fixa a escolha no servicos.json para reabrir nesta ordem.
                if dados.get("_servico_selecionado") != sid:
                    dados["_servico_selecionado"] = sid
                    if not _salvar_servicos_json(dados):
                        log.debug("Não foi possível guardar a programação "
                                  "selecionada em servicos.json.")
                _carregar_itens()
                _atualizar_manter_videos()

        combo_servico.bind("<<ComboboxSelected>>", _on_servico_select)

        def _selecionar_dia(chave: str) -> None:
            if chave not in _CHAVES_DIA or chave == dia_selecionado[0]:
                return
            _cancelar_renomear_sem_salvar()
            dia_selecionado[0] = chave
            if dados.get("_dia_selecionado") != chave:
                dados["_dia_selecionado"] = chave
                if not _salvar_servicos_json(dados):
                    log.debug("Não foi possível guardar o dia selecionado "
                              "em servicos.json.")
            _atualizar_botoes_dia()
            _carregar_servicos()
            if combo_servico['values']:
                _on_servico_select()
            else:
                servico_selecionado_id[0] = None
                _restaurar_rotulo_servico()
                _carregar_itens()

        # ── Renomear a programação direto na caixa "Programação" ──
        # Um clique na caixa transforma o seletor (normalmente só leitura) num
        # campo editável com o nome da programação. O novo nome é salvo
        # automaticamente ao clicar em qualquer outro ponto da janela, ao
        # pressionar Enter ou ao sair do campo (Tab). Esc cancela e restaura.
        _renomear = {"id": None, "nome_original": ""}

        def _rotulo_atual_servico() -> str:
            serv = _servico_atual()
            return _rotulo_servico(serv) if serv else ""

        def _definir_botao_exclusao(ativo: bool) -> None:
            """Durante a edição, "+ Nova Projeção" vira "Del Projeção" (vermelho)."""
            try:
                if ativo:
                    btn_novo.configure(
                        text="🗑️ Del Projeção", bg='#da3633',
                        activebackground='#f85149', activeforeground='white')
                else:
                    btn_novo.configure(
                        text="➕ Nova Projeção", bg='#238636',
                        activebackground='#2ea043', activeforeground='white')
            except (tk.TclError, NameError):
                pass

        def _restaurar_rotulo_servico() -> None:
            try:
                combo_servico.configure(state='readonly')
                combo_servico.set(_rotulo_atual_servico())
            except tk.TclError:
                pass
            _atualizar_manter_videos()

        def _selecionar_nome_servico() -> None:
            if _renomear["id"] is None:
                return
            atual = (servico_var.get() or "").strip()
            if atual != _renomear["nome_original"]:
                return
            try:
                combo_servico.selection_range(0, 'end')
                combo_servico.icursor('end')
            except tk.TclError:
                pass

        def _iniciar_renomear_servico(event=None) -> None:
            if _renomear["id"] is not None:
                return
            serv = _servico_atual()
            if not serv:
                return
            _renomear["id"] = serv.get("id")
            _renomear["nome_original"] = (serv.get("nome") or "").strip()
            try:
                combo_servico.configure(state='normal')
                servico_var.set(serv.get("nome") or "")
                combo_servico.focus_set()
                combo_servico.icursor('end')
                combo_servico.after_idle(_selecionar_nome_servico)
            except tk.TclError:
                pass
            _definir_botao_exclusao(True)

        def _finalizar_renomear_servico(event=None, cancelar: bool = False) -> None:
            """Salva o nome editado (ou restaura o antigo, se cancelar)."""
            sid = _renomear["id"]
            if sid is None:
                return
            original = _renomear["nome_original"]
            novo = "" if cancelar else (servico_var.get() or "").strip()
            _renomear["id"] = None
            _definir_botao_exclusao(False)
            serv = next((s for s in dados["servicos"]
                         if s.get("id") == sid), None)
            if (cancelar or serv is None or servico_selecionado_id[0] != sid
                    or not novo or novo == original):
                _restaurar_rotulo_servico()
                return
            serv["nome"] = novo
            if not _salvar_servicos_json(dados):
                serv["nome"] = original
                _restaurar_rotulo_servico()
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar o nome do serviço "
                    "em servicos.json.", parent=janela)
                return
            _carregar_servicos()
            _on_servico_select()
            _restaurar_rotulo_servico()

        def _cancelar_renomear_sem_salvar() -> None:
            """Descarta a edição inline (ex.: o operador trocou de serviço)."""
            if _renomear["id"] is None:
                return
            _renomear["id"] = None
            _definir_botao_exclusao(False)
            _restaurar_rotulo_servico()

        def _cancelar_renomear_tecla(event=None):
            _finalizar_renomear_servico(cancelar=True)
            return "break"

        combo_servico.bind("<Button-1>", _iniciar_renomear_servico, add="+")
        combo_servico.bind("<FocusOut>", _finalizar_renomear_servico, add="+")
        combo_servico.bind("<Return>", _finalizar_renomear_servico, add="+")
        combo_servico.bind("<KP_Enter>", _finalizar_renomear_servico, add="+")
        combo_servico.bind("<Escape>", _cancelar_renomear_tecla, add="+")

        # ── Itens do serviço (cartões com rolagem) ──
        # Cada item é um Frame com borda (sua própria "caixa"), título em
        # negrito e rolagem própria. O botão "Cartões" remove as caixas e o
        # negrito sem perder seleção múltipla, arrastar ou menu de contexto.
        COR_FUNDO_LISTA = '#161b22'
        COR_CARD = '#21262d'
        COR_BORDA = '#30363d'
        COR_SELECAO = '#6e40c9'
        COR_TEXTO = '#c9d1d9'
        COR_TEXTO_FRACO = '#8b949e'
        COR_TITULO = '#f0f0f0'
        COR_DESTAQUE = '#f0c040'
        COR_IND = '#58a6ff'
        COR_IND_BRILHO = '#79c0ff'

        cartoes_ativo = {"on": True}

        lista_frame = tk.Frame(main, bg=COR_FUNDO_LISTA)
        lista_frame.grid(row=2, column=0, sticky='nsew', pady=5)
        lista_frame.rowconfigure(0, weight=1)
        lista_frame.columnconfigure(0, weight=1)

        lista_canvas = tk.Canvas(lista_frame, bg=COR_FUNDO_LISTA,
                                 highlightthickness=0, bd=0,
                                 yscrollincrement=24)
        scroll_y = tk.Scrollbar(lista_frame, orient="vertical",
                                command=lista_canvas.yview)
        lista_canvas.configure(yscrollcommand=scroll_y.set)
        lista_canvas.grid(row=0, column=0, sticky='nsew')
        scroll_y.grid(row=0, column=1, sticky='ns')

        cards_host = tk.Frame(lista_canvas, bg=COR_FUNDO_LISTA)
        _canvas_window = lista_canvas.create_window(
            (0, 0), window=cards_host, anchor='nw')

        _cards: dict[str, dict] = {}
        _ordem: list[str] = []
        _selecionados: set[str] = set()
        _ancora: dict[str, str | None] = {"id": None}
        _foco: dict[str, str | None] = {"id": None}

        def _card_existe(iid: str) -> bool:
            return iid in _cards

        def _definir_duracao_card(iid: str, texto: str) -> None:
            dados = _cards.get(iid)
            if dados is None:
                return
            try:
                dados["duracao"].configure(text=texto)
            except tk.TclError:
                pass

        def _estilo_do_card(iid: str) -> None:
            """Aplica fundo/cores de UM cartão (seleção e ``reproduzido``)."""
            dados_card = _cards.get(iid)
            if dados_card is None:
                return
            selecionado = iid in _selecionados
            check_var = dados_card.get("check_var")
            marcado = (bool(check_var.get())
                       if check_var is not None else False)
            fundo = COR_SELECAO if selecionado else (
                COR_CARD if cartoes_ativo["on"] else COR_FUNDO_LISTA)
            try:
                for frame in dados_card["frames"]:
                    frame.configure(bg=fundo)
                for widget, cor_normal in dados_card["fundos"]:
                    if selecionado:
                        cor = '#ffffff'
                    elif marcado:
                        cor = COR_TEXTO_FRACO
                    else:
                        cor = cor_normal
                    widget.configure(bg=fundo, fg=cor)
                chk = dados_card.get("check")
                if chk is not None:
                    chk.configure(bg=fundo, activebackground=fundo)
            except tk.TclError:
                pass

        def _atualizar_selecao_visual(iids=None) -> None:
            """Atualiza os cartões de ``iids`` (None = todos).

            Evita varrer a lista inteira quando o clique só mudou um ou
            dois cartões (caso comum em seleção com Ctrl/Shift e ao marcar
            um item como reproduzido).
            """
            alvos = _cards.keys() if iids is None else tuple(iids)
            for iid in alvos:
                _estilo_do_card(iid)

        def _fonte_com_risco(fonte, riscado: bool):
            if not riscado:
                return fonte
            familia, tamanho = fonte[0], fonte[1]
            estilos = [str(p) for p in fonte[2:] if p]
            if "overstrike" not in estilos:
                estilos.append("overstrike")
            return (familia, tamanho, " ".join(estilos))

        def _aplicar_estilo_reproduzido(
                iid: str, atualizar_selecao: bool = True) -> None:
            dados_card = _cards.get(iid)
            if not dados_card:
                return
            check_var = dados_card.get("check_var")
            marcado = (bool(check_var.get())
                       if check_var is not None else False)
            for widget, fonte in dados_card.get("fontes", []):
                try:
                    widget.configure(
                        font=_fonte_com_risco(fonte, marcado))
                except tk.TclError:
                    pass
            if atualizar_selecao:
                _atualizar_selecao_visual((iid,))

        _marcacoes_pendentes: dict[tuple[object, str], tuple[bool, bool]] = {}
        _marcacao_timer: dict[str, str | None] = {"id": None}

        def _cancelar_salvamento_marcacoes() -> None:
            timer = _marcacao_timer["id"]
            _marcacao_timer["id"] = None
            if timer is None:
                return
            try:
                janela.after_cancel(timer)
            except tk.TclError:
                pass

        def _agendar_salvamento_marcacoes() -> None:
            _cancelar_salvamento_marcacoes()
            try:
                _marcacao_timer["id"] = janela.after(
                    _MARCACAO_SALVAR_MS, _salvar_marcacoes_pendentes)
            except tk.TclError:
                _marcacao_timer["id"] = None

        def _salvar_marcacoes_pendentes(avisar: bool = True) -> None:
            """Grava as marcações agrupadas, relendo o JSON antes de salvar.

            Reler evita sobrescrever uma marcação feita enquanto a janela
            estava aberta. Se o item mudou por outra via (controle remoto ou
            execução), a marcação mais recente prevalece e a pendente é
            descartada.
            """
            _cancelar_salvamento_marcacoes()
            if not _marcacoes_pendentes:
                return
            pendentes = dict(_marcacoes_pendentes)
            _marcacoes_pendentes.clear()

            dados_disco = _carregar_servicos_json()
            aplicadas: list[tuple[object, str, bool]] = []
            for (sid, iid), (marcado, anterior) in pendentes.items():
                serv = next((s for s in (dados_disco.get("servicos") or [])
                             if str(s.get("id")) == str(sid)), None)
                if serv is None:
                    continue
                item = next((x for x in (serv.get("itens") or [])
                             if str(x.get("id")) == str(iid)), None)
                if item is None:
                    continue
                atual = bool(item.get("reproduzido"))
                if atual == bool(marcado):
                    continue
                if atual != bool(anterior):
                    continue
                item["reproduzido"] = bool(marcado)
                aplicadas.append((sid, iid, bool(anterior)))

            if not aplicadas:
                return
            if _salvar_servicos_json(dados_disco):
                return

            log.debug("Não foi possível guardar as marcações de reproduzido "
                      "em servicos.json.")
            for sid, iid, anterior in aplicadas:
                serv = next((s for s in (dados.get("servicos") or [])
                             if str(s.get("id")) == str(sid)), None)
                item = next((x for x in ((serv or {}).get("itens") or [])
                             if str(x.get("id")) == iid), None)
                if item is not None:
                    item["reproduzido"] = anterior
                atual_serv = _servico_atual()
                if str((atual_serv or {}).get("id")) != str(sid):
                    continue
                dados_card = _cards.get(iid)
                if dados_card is None:
                    continue
                check_var = dados_card.get("check_var")
                if check_var is not None:
                    try:
                        check_var.set(anterior)
                    except tk.TclError:
                        pass
                _aplicar_estilo_reproduzido(iid)
            if not avisar:
                return
            try:
                existe = bool(janela.winfo_exists())
            except tk.TclError:
                existe = False
            if existe:
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar a marcação dos itens.",
                    parent=janela)

        def _alternar_reproduzido(iid: str) -> None:
            serv = _servico_atual()
            dados_card = _cards.get(iid)
            if serv is None or dados_card is None:
                return
            item = next((x for x in (serv.get("itens") or [])
                         if str(x.get("id")) == iid), None)
            if item is None:
                return
            check_var = dados_card.get("check_var")
            marcado = (bool(check_var.get())
                       if check_var is not None else False)
            chave = (serv.get("id"), iid)
            pendente = _marcacoes_pendentes.get(chave)
            anterior = (pendente[1] if pendente is not None
                        else bool(item.get("reproduzido")))
            item["reproduzido"] = marcado
            _marcacoes_pendentes[chave] = (marcado, anterior)
            _agendar_salvamento_marcacoes()
            _aplicar_estilo_reproduzido(iid)

        def _sincronizar_marca_item(item_id) -> None:
            if item_id is None:
                return
            iid = str(item_id)
            dados_card = _cards.get(iid)
            serv = _servico_atual()
            if dados_card is None or serv is None:
                return
            item = next((x for x in (serv.get("itens") or [])
                         if str(x.get("id")) == iid), None)
            if item is None:
                return
            check_var = dados_card.get("check_var")
            if check_var is not None:
                try:
                    check_var.set(bool(item.get("reproduzido")))
                except tk.TclError:
                    return
            _aplicar_estilo_reproduzido(iid)

        def _definir_selecao(novos) -> None:
            anteriores = set(_selecionados)
            _selecionados.clear()
            _selecionados.update(i for i in novos if i in _cards)
            if _foco["id"] not in _selecionados:
                _foco["id"] = next(iter(_selecionados), None)
            mudaram = anteriores ^ _selecionados
            if mudaram:
                _atualizar_selecao_visual(mudaram)

        def _ids_selecionados() -> list[str]:
            return [iid for iid in _ordem if iid in _selecionados]

        def _ver_item(iid: str) -> None:
            dados = _cards.get(iid)
            if dados is None:
                return
            try:
                lista_canvas.update_idletasks()
                frame = dados["frame"]
                total = max(1, cards_host.winfo_height())
                topo = frame.winfo_y()
                base = topo + frame.winfo_height()
                visivel_topo = lista_canvas.canvasy(0)
                visivel_base = visivel_topo + lista_canvas.winfo_height()
                if topo < visivel_topo:
                    lista_canvas.yview_moveto(max(0.0, topo / total))
                elif base > visivel_base:
                    lista_canvas.yview_moveto(
                        max(0.0, (base - lista_canvas.winfo_height()) / total))
            except tk.TclError:
                pass

        def _selecionar_item(iid: str | None, ver: bool = False) -> None:
            if not iid or iid not in _cards:
                return
            _definir_selecao({iid})
            _ancora["id"] = iid
            _foco["id"] = iid
            if ver:
                _ver_item(iid)

        _layout: dict[str, object] = {
            "largura": None, "wrap": None, "timer": None}

        def _cancelar_layout_agendado() -> None:
            timer = _layout.get("timer")
            _layout["timer"] = None
            if timer is None:
                return
            try:
                lista_canvas.after_cancel(timer)
            except tk.TclError:
                pass

        def _atualizar_layout_canvas(event=None) -> None:
            """Ajusta largura/wraplength só quando o valor muda de fato."""
            _layout["timer"] = None
            try:
                largura = lista_canvas.winfo_width()
                if largura <= 1:
                    # Ainda não mapeado: o <Configure> real fará o layout.
                    return
                wrap = max(180, largura - 255)
                if largura != _layout["largura"]:
                    lista_canvas.itemconfigure(_canvas_window, width=largura)
                    _layout["largura"] = largura
                if wrap != _layout["wrap"]:
                    for dados in _cards.values():
                        dados["titulo"].configure(wraplength=wrap)
                        url = dados.get("url")
                        if url is not None:
                            url.configure(wraplength=wrap)
                    _layout["wrap"] = wrap
                lista_canvas.configure(
                    scrollregion=lista_canvas.bbox('all'))
            except tk.TclError:
                pass

        def _agendar_layout_canvas(event=None) -> None:
            """Debounce do <Configure> para não varrer os cartões por evento."""
            _cancelar_layout_agendado()
            try:
                _layout["timer"] = lista_canvas.after(
                    60, _atualizar_layout_canvas)
            except tk.TclError:
                _layout["timer"] = None

        lista_canvas.bind('<Configure>', _agendar_layout_canvas)
        cards_host.bind(
            '<Configure>',
            lambda _e: lista_canvas.configure(
                scrollregion=lista_canvas.bbox('all')))

        def _rolar_lista(event):
            delta = getattr(event, 'delta', 0)
            if getattr(event, 'num', None) == 4 or delta > 0:
                unidades = -3
            elif getattr(event, 'num', None) == 5 or delta < 0:
                unidades = 3
            else:
                return None
            try:
                lista_canvas.yview_scroll(unidades, 'units')
            except tk.TclError:
                pass
            return "break"

        def _ligar_rolagem(widget) -> None:
            widget.bind('<MouseWheel>', _rolar_lista)
            widget.bind('<Button-4>', _rolar_lista)
            widget.bind('<Button-5>', _rolar_lista)

        _ligar_rolagem(lista_canvas)
        _ligar_rolagem(cards_host)

        btn_cartoes = tk.Button(
            serv_frame, text="🗂️ Cartões", font=("Arial", 10, "bold"),
            bg=COR_SELECAO, fg='white', activebackground='#8b5cf6',
            activeforeground='white', cursor='hand2', padx=10, pady=3)
        btn_cartoes.pack(side='right', padx=8)

        def _atualizar_botao_cartoes() -> None:
            if cartoes_ativo["on"]:
                btn_cartoes.config(text="🗂️ Cartões", bg=COR_SELECAO,
                                   fg='white')
            else:
                btn_cartoes.config(text="🗂️ Sem caixas", bg='#21262d',
                                   fg=COR_DESTAQUE)

        def _alternar_cartoes() -> None:
            cartoes_ativo["on"] = not cartoes_ativo["on"]
            _atualizar_botao_cartoes()
            _carregar_itens()

        btn_cartoes.config(command=_alternar_cartoes)
        _atualizar_botao_cartoes()

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

        def _precarregar_referencias(itens) -> tuple[dict[str, str],
                                                      dict[str, dict]]:
            """Carrega numa passada os caminhos de mídia e anúncios dos itens.

            Antes cada cartão consultava o banco separadamente (e os anúncios
            reliam a tabela inteira por item). Aqui as referências da lista
            são reunidas e resolvidas antes da montagem dos cartões.
            """
            ids_midia: list[object] = []
            ids_anuncio: set[str] = set()
            for it in itens or []:
                tipo = (it.get("tipo") or "").strip().lower()
                ref = it.get("referencia_id")
                if ref is None:
                    continue
                if tipo in ("video", "audio"):
                    # Só tipos que o SQLite aceita como parâmetro; um JSON
                    # malformado não pode derrubar a montagem da lista.
                    if isinstance(ref, (int, float, str, bytes)):
                        ids_midia.append(ref)
                elif tipo == "anuncio":
                    ids_anuncio.add(str(ref))

            caminhos_midia: dict[str, str] = {}
            unicos = list(dict.fromkeys(ids_midia))
            for inicio in range(0, len(unicos), 500):
                lote = unicos[inicio:inicio + 500]
                marcadores = ", ".join("?" for _ in lote)
                try:
                    rows = db_query(
                        "SELECT id, caminho_arquivo FROM midia "
                        f"WHERE id IN ({marcadores}) AND ativo = 1",
                        tuple(lote))
                except Exception:
                    continue
                for row in rows or []:
                    caminho = (row.get("caminho_arquivo") or "").strip()
                    if caminho:
                        caminhos_midia[str(row.get("id"))] = caminho

            anuncios: dict[str, dict] = {}
            if ids_anuncio:
                try:
                    rows = _listar_anuncios_db()
                except Exception:
                    rows = []
                for anuncio in rows or []:
                    chave = str(anuncio.get("id"))
                    if chave in ids_anuncio:
                        anuncios[chave] = anuncio
            return caminhos_midia, anuncios

        def _caminho_item(it: dict, referencias=None) -> str | None:
            """Resolve o arquivo/URL de mídia de um item da Ordem de Serviço.

            ``referencias`` (opcional) é o par devolvido por
            ``_precarregar_referencias``; sem ele, consulta o banco item a
            item como antes.
            """
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
                if referencias is not None:
                    encontrado = (referencias[0].get(str(ref)) or "").strip()
                    if encontrado:
                        caminho = encontrado
                else:
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
                if referencias is not None:
                    anuncio = referencias[1].get(str(ref)) or {}
                else:
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

        def _texto_duracao_item(it: dict, caminho: str | None = None,
                                referencias=None) -> str:
            if caminho is None:
                caminho = _caminho_item(it, referencias)
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

        def _persistir_duracoes(resultados: dict[str, float]) -> None:
            """Guarda as durações reais no item (um único save por lote)."""
            serv = _servico_atual()
            if not serv or not resultados:
                return
            alterou = False
            for it in serv.get("itens") or []:
                caminho = _linhas_path.get(str(it.get("id")))
                if not caminho or caminho not in resultados:
                    continue
                duracao = resultados[caminho]
                if not duracao:
                    continue
                try:
                    valor = int(round(float(duracao)))
                except (TypeError, ValueError):
                    continue
                if it.get("duracao_estimada_segundos") != valor:
                    it["duracao_estimada_segundos"] = valor
                    alterou = True
            if alterou and not _salvar_servicos_json(dados):
                log.debug("Não foi possível guardar as durações em "
                          "servicos.json.")

        def _persistir_duracao(caminho: str, duracao) -> None:
            """Guarda a duração real no item (usado pela contagem ao vivo)."""
            if not caminho or not duracao:
                return
            _persistir_duracoes({caminho: duracao})

        # Fila de durações: os cartões apenas enfileiram; a consulta começa
        # no idle (depois do primeiro desenho), roda com concorrência limitada
        # e os resultados são aplicados em lote, numa única passada de UI.
        _duracao_fila: dict[str, bool] = {}
        _duracao_jobs: dict[str, bool] = {}
        _duracao_resultados: queue.SimpleQueue = queue.SimpleQueue()
        _duracao_timers: dict[str, str | None] = {"inicio": None,
                                                  "poll": None}

        def _agendar_inicio_duracoes() -> None:
            if _duracao_timers["inicio"] is not None or not _duracao_fila:
                return
            try:
                _duracao_timers["inicio"] = self.root.after_idle(
                    _iniciar_duracoes)
            except tk.TclError:
                _duracao_timers["inicio"] = None

        def _despachar_duracoes() -> None:
            """Inicia no máximo ``_DURACAO_MAX_WORKERS`` consultas por vez."""
            player = getattr(self, "player", None)
            while (_duracao_jobs
                   and len(_duracao_pendente) < _DURACAO_MAX_WORKERS):
                caminho = next(iter(_duracao_jobs))
                eh_youtube = _duracao_jobs.pop(caminho)
                if (caminho in _duracao_cache
                        or caminho in _duracao_pendente):
                    continue
                if not eh_youtube and (player is None
                                       or not os.path.isfile(caminho)):
                    continue
                _duracao_pendente.add(caminho)
                threading.Thread(
                    target=_trabalho_duracao,
                    args=(caminho, eh_youtube, player), daemon=True,
                    name="navepro-duracao-item").start()
            if _duracao_pendente:
                _agendar_poll_duracoes()

        def _iniciar_duracoes() -> None:
            _duracao_timers["inicio"] = None
            for caminho, eh_youtube in list(_duracao_fila.items()):
                _duracao_fila.pop(caminho, None)
                if (caminho in _duracao_cache
                        or caminho in _duracao_pendente
                        or caminho in _duracao_jobs):
                    continue
                _duracao_jobs[caminho] = eh_youtube
            _despachar_duracoes()

        def _trabalho_duracao(caminho: str, eh_youtube: bool,
                              player) -> None:
            try:
                if eh_youtube:
                    info = _obter_info_youtube(caminho)
                    duracao = (info or {}).get("duracao") or None
                else:
                    duracao = player._obter_duracao_arquivo(caminho)
            except Exception as exc:
                log.debug("Falha ao obter a duração de %s: %s", caminho, exc)
                duracao = None
            _duracao_resultados.put((caminho, duracao))

        def _agendar_poll_duracoes() -> None:
            if _duracao_timers["poll"] is not None or not _duracao_pendente:
                return
            try:
                _duracao_timers["poll"] = janela.after(
                    50, _drenar_duracoes)
            except tk.TclError:
                _duracao_timers["poll"] = None

        def _drenar_duracoes() -> None:
            _duracao_timers["poll"] = None
            resultados: dict[str, float] = {}
            while True:
                try:
                    caminho, duracao = _duracao_resultados.get_nowait()
                except queue.Empty:
                    break
                _duracao_pendente.discard(caminho)
                _duracao_cache[caminho] = duracao
                if duracao:
                    resultados[caminho] = duracao
            if resultados:
                try:
                    existe = bool(janela.winfo_exists())
                except tk.TclError:
                    existe = False
                if existe:
                    alteracoes: dict[str, str] = {}
                    for caminho, duracao in resultados.items():
                        texto = _formatar_duracao_segundos(duracao)
                        for iid, path in list(_linhas_path.items()):
                            if path != caminho:
                                continue
                            _textos_base[iid] = texto
                            if _contagem["iid"] != iid:
                                alteracoes[iid] = texto
                    for iid, texto in alteracoes.items():
                        _definir_duracao_card(iid, texto)
                    _persistir_duracoes(resultados)
            if _duracao_jobs:
                _despachar_duracoes()
            elif _duracao_pendente:
                _agendar_poll_duracoes()

        def _pedir_duracao(caminho: str) -> None:
            """Enfileira a consulta da duração real (ffprobe/yt-dlp).

            A consulta só começa no idle e os resultados são aplicados em
            lote, para não criar threads/repinturas durante a montagem.
            """
            if (not caminho or caminho in _duracao_cache
                    or caminho in _duracao_pendente
                    or caminho in _duracao_fila
                    or caminho in _duracao_jobs):
                return
            eh_youtube = _eh_url_youtube(caminho)
            if not eh_youtube and not os.path.isfile(caminho):
                return
            if not eh_youtube and getattr(self, "player", None) is None:
                return
            _duracao_fila[caminho] = eh_youtube
            _agendar_inicio_duracoes()

        # ── Indicador animado de inserção (drag & drop) ──
        _ind: dict[str, object] = {
            "line": None, "anim": None, "visivel": False, "fase": False}

        def _pulsar_indicador():
            _ind["anim"] = None
            line = _ind.get("line")
            if line is None or not _ind.get("visivel"):
                return
            fase = not bool(_ind.get("fase"))
            _ind["fase"] = fase
            try:
                line.configure(bg=COR_IND_BRILHO if fase else COR_IND)
                _ind["anim"] = janela.after(280, _pulsar_indicador)
            except tk.TclError:
                return

        def _mostrar_indicador(y: int) -> None:
            if _ind.get("line") is None:
                try:
                    _ind["line"] = tk.Frame(cards_host, bg=COR_IND, height=3)
                except tk.TclError:
                    return
            _ind["visivel"] = True
            try:
                _ind["line"].place(x=4, y=max(0, int(y) - 1),
                                   relwidth=1, height=3)
                _ind["line"].lift()
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
            line = _ind.get("line")
            if line is not None:
                try:
                    line.place_forget()
                except tk.TclError:
                    pass

        # ── Arrastar e soltar para reordenar os cartões ──
        _drag_state: dict[str, object] = {
            "origem": None, "press_y": None, "dragging": False, "pos": None,
            "geometria": None}

        def _geometria_dos_cards() -> list[tuple[str, int, int]]:
            """Posições/alturas dos cartões no início do arraste.

            Guardar uma vez evita dois ``winfo_*`` (ida ao X) por cartão a
            cada evento de movimento do mouse.
            """
            geometria: list[tuple[str, int, int]] = []
            for iid in _ordem:
                dados = _cards.get(iid)
                if dados is None:
                    continue
                frame = dados.get("frame")
                if frame is None:
                    continue
                try:
                    geometria.append(
                        (iid, frame.winfo_y(), frame.winfo_height()))
                except tk.TclError:
                    continue
            return geometria

        def _calcular_posicao(y: int, geometria=None):
            """Devolve (posição de inserção, y da linha) para o y informado.

            ``geometria`` vem de ``_geometria_dos_cards`` e permite achar a
            posição por busca binária durante o arraste.
            """
            if geometria is None:
                geometria = _geometria_dos_cards()
            if not geometria:
                return None
            esq, dir_ = 0, len(geometria)
            while esq < dir_:
                meio = (esq + dir_) // 2
                _iid, topo, altura = geometria[meio]
                if y < topo + altura / 2:
                    dir_ = meio
                else:
                    esq = meio + 1
            if esq < len(geometria):
                _iid, topo, _altura = geometria[esq]
                return esq, topo
            _iid, topo, altura = geometria[-1]
            return len(geometria), topo + altura

        def _on_card_button_press(event, iid):
            # Clique nos cartões não chega ao bind da janela (o handler
            # devolve "break"), então confirma a edição inline aqui.
            _finalizar_renomear_servico()
            _fechar_menu_contexto()
            _registrar_escolha(iid)
            _foco["id"] = iid
            ctrl = bool(event.state & 0x4)
            shift = bool(event.state & 0x1)
            if shift and _ancora["id"] in _ordem and iid in _ordem:
                idx_a = _ordem.index(_ancora["id"])
                idx_b = _ordem.index(iid)
                ini, fim = sorted((idx_a, idx_b))
                _definir_selecao(set(_ordem[ini:fim + 1]))
            elif ctrl:
                novos = set(_selecionados)
                if iid in novos:
                    novos.discard(iid)
                else:
                    novos.add(iid)
                _definir_selecao(novos)
                _ancora["id"] = iid
            else:
                _definir_selecao({iid})
                _ancora["id"] = iid
            _drag_state.update(origem=iid, press_y=event.y_root,
                               dragging=False, pos=None, geometria=None)
            return "break"

        def _on_card_motion(event):
            origem = _drag_state.get("origem")
            if not origem:
                return None
            press_y = _drag_state.get("press_y")
            if not _drag_state.get("dragging"):
                if press_y is None or abs(event.y_root - press_y) < 6:
                    return None
                _drag_state["dragging"] = True
                _drag_state["geometria"] = _geometria_dos_cards()
                try:
                    lista_canvas.configure(cursor="fleur")
                except tk.TclError:
                    pass
            try:
                y = event.y_root - cards_host.winfo_rooty()
            except tk.TclError:
                return None
            alvo = _calcular_posicao(y, _drag_state.get("geometria"))
            if alvo is None:
                _drag_state["pos"] = None
                _esconder_indicador()
            else:
                pos, linha_y = alvo
                _drag_state["pos"] = pos
                _mostrar_indicador(linha_y)
            try:
                topo_tela = lista_canvas.winfo_rooty()
                altura_tela = lista_canvas.winfo_height()
                if event.y_root < topo_tela + 30:
                    lista_canvas.yview_scroll(-1, "units")
                elif event.y_root > topo_tela + altura_tela - 30:
                    lista_canvas.yview_scroll(1, "units")
            except tk.TclError:
                pass
            return "break"

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

        def _on_card_button_release(event):
            origem = _drag_state.get("origem")
            pos = _drag_state.get("pos")
            arrastou = bool(_drag_state.get("dragging"))
            _drag_state.update(origem=None, press_y=None,
                               dragging=False, pos=None, geometria=None)
            _esconder_indicador()
            try:
                lista_canvas.configure(cursor="")
            except tk.TclError:
                pass
            if not origem or not arrastou:
                return "break"
            serv = _servico_atual()
            if not serv:
                return "break"
            novo = _reordenar_com_posicao(serv, str(origem), pos)
            if novo is None:
                return "break"
            itens_antigos = serv.get("itens")
            serv["itens"] = novo
            if not _salvar_servicos_json(dados):
                serv["itens"] = itens_antigos
                log.warning("Não foi possível salvar a reordenação por arrastar.")
                return "break"
            _ordem[:] = [str(x.get("id")) for x in novo
                         if str(x.get("id")) in _cards]
            _reordenar_cards_visual()
            _selecionar_item(str(origem), ver=True)
            return "break"

        def _on_card_leave(_event=None):
            if _drag_state.get("dragging"):
                _drag_state["pos"] = None
                _esconder_indicador()

        janela.bind("<Escape>", _on_card_leave, add="+")

        def _on_card_double_click(event, iid):
            _finalizar_renomear_servico()
            _definir_selecao({iid})
            _ancora["id"] = iid
            _foco["id"] = iid
            serv = _servico_atual()
            if not serv:
                return "break"
            it = next((x for x in (serv.get("itens") or [])
                       if str(x.get("id")) == iid), None)
            if it is not None:
                _abrir_editor_item(it)
            return "break"

        def _on_card_button_right(event, iid):
            _finalizar_renomear_servico()
            _fechar_menu_contexto()
            _registrar_escolha(iid)
            if iid not in _selecionados:
                _definir_selecao({iid})
                _ancora["id"] = iid
            _foco["id"] = iid
            menu_ctx = tk.Menu(janela, tearoff=0, bg='#21262d', fg='#c9d1d9',
                               activebackground='#6e40c9',
                               activeforeground='#ffffff', font=("Arial", 10))
            menu_ctx.add_command(label="🗑️ Apagar Item(ns) Selecionado(s)",
                                 command=_apagar_item_contexto)
            _menu_ctx_aberto["menu"] = menu_ctx
            menu_ctx.tk_popup(event.x_root, event.y_root, 0)
            return "break"

        def _clique_vazio(event=None):
            if _drag_state.get("dragging"):
                return None
            _definir_selecao(set())
            _ancora["id"] = None
            return None

        lista_canvas.bind("<Button-1>", _clique_vazio)
        cards_host.bind("<Button-1>", _clique_vazio)

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
            """Apaga um ou vários itens selecionados na lista, com confirmação."""
            _fechar_menu_contexto()
            sel = _ids_selecionados()
            if not sel:
                return
            serv = _servico_atual()
            if not serv:
                return
            ids_ordenados = [int(iid) for iid in sel if str(iid).isdigit()]
            itens_por_id = {x.get("id"): x for x in (serv.get("itens") or [])}
            alvos = [itens_por_id[i] for i in ids_ordenados
                     if i in itens_por_id]
            if not alvos:
                return
            titulos = [
                (it.get("titulo_custom") or "").strip()
                or f"Item {it.get('id')}" for it in alvos]
            if len(alvos) == 1:
                mensagem = f'Remover o item "{titulos[0]}"?'
            else:
                resumo = "\n".join(f"• {t}" for t in titulos[:10])
                if len(titulos) > 10:
                    resumo += f"\n… e mais {len(titulos) - 10}"
                mensagem = (f"Remover os {len(alvos)} itens selecionados?\n\n"
                            f"{resumo}")
            if not tkinter.messagebox.askyesno(
                    "Confirmar", mensagem, parent=janela):
                return
            itens_antigos = serv.get("itens")
            ids_remover = {it.get("id") for it in alvos}
            serv["itens"] = [x for x in (serv.get("itens") or [])
                             if x.get("id") not in ids_remover]
            if not _salvar_servicos_json(dados):
                serv["itens"] = itens_antigos
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar a remoção em servicos.json.",
                    parent=janela)
                return
            # A escolha do operador não pode apontar para um item removido.
            if _item_escolhido.get("id") in ids_remover:
                _item_escolhido["id"] = None
            _carregar_itens()

        # Clicar em qualquer outro lugar da janela (ou rolar/teclar Esc) fecha
        # o menu de contexto se ele estiver aberto. O bind na janela propaga
        # para os widgets internos, cobrindo toda a área da janela.
        for _evento in ("<ButtonPress-1>", "<ButtonPress-2>",
                        "<ButtonPress-3>", "<MouseWheel>"):
            janela.bind(_evento, _fechar_menu_contexto)
        janela.bind("<Escape>", _fechar_menu_contexto)

        def _criar_card(it: dict, indice: int,
                        pos: int | None = None, referencias=None) -> None:
            """Monta um cartão (ou linha) para um item da ordem de serviço.

            ``pos`` insere o cartão numa posição existente (edição) em vez
            de anexá-lo ao fim da lista. ``referencias`` (opcional) evita
            consultar o banco de novo durante uma montagem completa.
            """
            tipo = (it.get("tipo") or "slide").strip().lower() or "slide"
            tipo_emoji = {"hino": "📖", "versiculo": "✝️", "video": "🎬",
                          "audio": "🎵", "slide": "📄", "anuncio": "📢",
                          "sermao": "🎤", "youtube": "▶️"}.get(tipo, "📁")
            iid = str(it.get("id"))
            caminho = _caminho_item(it, referencias)
            texto_duracao = _texto_duracao_item(it, caminho, referencias)
            texto_titulo = _texto_titulo_item(it, indice)
            if "\n" in texto_titulo:
                titulo, url = texto_titulo.split("\n", 1)
            else:
                titulo, url = texto_titulo, ""

            ativo = cartoes_ativo["on"]
            fundo = COR_CARD if ativo else COR_FUNDO_LISTA
            # Ao criar só um cartão (add/editar), já usa o wrap atual; numa
            # remontagem completa o _layout ainda está None e o valor real
            # é aplicado no fim de _carregar_itens.
            wrap_inicial = 380
            if _layout.get("wrap") is not None:
                try:
                    wrap_inicial = int(_layout["wrap"])
                except (TypeError, ValueError):
                    wrap_inicial = 380
            card = tk.Frame(cards_host, bg=fundo, bd=0,
                            highlightthickness=1 if ativo else 0,
                            highlightbackground=COR_BORDA,
                            highlightcolor=COR_BORDA)
            card.pack(fill='x', padx=8, pady=4 if ativo else 2)
            card.columnconfigure(2, weight=1)

            marcado = bool(it.get("reproduzido"))
            primeira = tk.Frame(card, bg=fundo)
            primeira.grid(row=0, column=0, sticky='nw',
                          padx=(8, 4), pady=(6, 8))
            check_var = tk.BooleanVar(value=marcado)
            chk = tk.Checkbutton(
                primeira, variable=check_var,
                command=lambda i=iid: _alternar_reproduzido(i),
                bg=fundo, fg='#ffffff', activebackground=fundo,
                activeforeground='#ffffff', selectcolor='#238636',
                highlightthickness=0, bd=0, cursor='hand2')
            chk.pack(side='left')
            lbl_num = tk.Label(primeira, text=str(indice), bg=fundo,
                               fg=COR_DESTAQUE, width=3, anchor='center',
                               font=("Arial", 11, "bold"))
            lbl_num.pack(side='left', padx=(2, 0))

            lbl_tipo = tk.Label(card, text=f"{tipo_emoji} {tipo.title()}",
                                bg=fundo, fg=COR_TEXTO_FRACO, anchor='w',
                                font=("Arial", 9, "bold"))
            lbl_tipo.grid(row=0, column=1, sticky='nw',
                          padx=(0, 10), pady=(9, 8))

            titulo_frame = tk.Frame(card, bg=fundo)
            titulo_frame.grid(row=0, column=2, sticky='ew', pady=(6, 6))
            titulo_frame.columnconfigure(0, weight=1)
            lbl_titulo = tk.Label(
                titulo_frame, text=titulo, bg=fundo, fg=COR_TITULO,
                anchor='w', justify='left', wraplength=wrap_inicial,
                font=("Arial", 11, "bold" if ativo else "normal"))
            lbl_titulo.grid(row=0, column=0, sticky='ew')
            lbl_url = None
            if url:
                lbl_url = tk.Label(titulo_frame, text=url, bg=fundo,
                                   fg='#58a6ff', anchor='w', justify='left',
                                   wraplength=wrap_inicial,
                                   font=("Arial", 9))
                lbl_url.grid(row=1, column=0, sticky='ew', pady=(2, 0))

            lbl_dur = tk.Label(card, text=texto_duracao, bg=fundo,
                               fg=COR_TEXTO, width=12, anchor='e',
                               font=("Arial", 10))
            lbl_dur.grid(row=0, column=3, sticky='ne',
                         padx=(8, 12), pady=(9, 8))

            fundos = [(lbl_num, COR_DESTAQUE),
                      (lbl_tipo, COR_TEXTO_FRACO),
                      (lbl_titulo, COR_TITULO),
                      (lbl_dur, COR_TEXTO)]
            if lbl_url is not None:
                fundos.append((lbl_url, '#58a6ff'))
            fontes = [(lbl_num, ("Arial", 11, "bold")),
                      (lbl_tipo, ("Arial", 9, "bold")),
                      (lbl_titulo, ("Arial", 11,
                                    "bold" if ativo else "normal")),
                      (lbl_dur, ("Arial", 10))]
            if lbl_url is not None:
                fontes.append((lbl_url, ("Arial", 9)))
            _cards[iid] = {
                "frame": card,
                "frames": [card, titulo_frame, primeira],
                "titulo": lbl_titulo,
                "url": lbl_url,
                "duracao": lbl_dur,
                "numero": lbl_num,
                "fundos": fundos,
                "fontes": fontes,
                "check_var": check_var,
                "check": chk,
            }
            if pos is None or pos >= len(_ordem):
                _ordem.append(iid)
            else:
                _ordem.insert(pos, iid)
                # O frame já foi empacotado no fim; reposiciona antes do
                # cartão que ficou logo abaixo dele.
                if pos + 1 < len(_ordem):
                    prox = _ordem[pos + 1]
                    prox_frame = (_cards.get(prox) or {}).get("frame")
                    if prox_frame is not None:
                        try:
                            card.pack_configure(before=prox_frame)
                        except tk.TclError:
                            pass
            _textos_base[iid] = texto_duracao
            if marcado:
                # Durante a montagem aplica só o estilo local: a seleção
                # visual é acertada numa única passada ao final de
                # _carregar_itens. Sem isso, cada item marcado percorria
                # todos os cartões já criados (O(n²) de configure).
                _aplicar_estilo_reproduzido(iid, atualizar_selecao=False)
            if caminho:
                _linhas_path[iid] = caminho
                if _eh_url_youtube(caminho):
                    # Só consulta a rede se o item antigo ainda não tem a
                    # duração capturada do YouTube.
                    if not (it.get("duracao_estimada_segundos") or 0):
                        _pedir_duracao(caminho)
                elif _extensao_midia(caminho) and os.path.isfile(caminho):
                    _pedir_duracao(caminho)

            widgets = [card, lbl_num, lbl_tipo, titulo_frame, lbl_titulo,
                       lbl_dur]
            if lbl_url is not None:
                widgets.append(lbl_url)
            for widget in widgets:
                widget.bind("<ButtonPress-1>",
                            lambda e, i=iid: _on_card_button_press(e, i))
                widget.bind("<B1-Motion>", _on_card_motion)
                widget.bind("<ButtonRelease-1>", _on_card_button_release)
                widget.bind("<Double-1>",
                            lambda e, i=iid: _on_card_double_click(e, i))
                widget.bind("<Button-3>",
                            lambda e, i=iid: _on_card_button_right(e, i))
                _ligar_rolagem(widget)

        def _mostrar_cartoes(mostrar: bool) -> None:
            try:
                lista_canvas.itemconfigure(
                    _canvas_window,
                    state='normal' if mostrar else 'hidden')
            except tk.TclError:
                pass

        def _carregar_itens():
            _cancelar_layout_agendado()
            # Numa remontagem completa força o wrap a ser reaplicado aos
            # cartões recém-criados mesmo que a largura não tenha mudado.
            _layout["wrap"] = None
            # Monta com a lista oculta: o X/Wayland não chega a exibir os
            # cartões vazios no meio da construção.
            _mostrar_cartoes(False)
            try:
                for widget in cards_host.winfo_children():
                    if widget is _ind.get("line"):
                        continue
                    try:
                        widget.destroy()
                    except tk.TclError:
                        pass
                _cards.clear()
                _ordem.clear()
                _linhas_path.clear()
                _textos_base.clear()
                _contagem["iid"] = None
                _esconder_indicador()
                serv = _servico_atual()
                if not serv:
                    _definir_selecao(set())
                else:
                    itens = list(serv.get("itens") or [])
                    referencias = _precarregar_referencias(itens)
                    for i, it in enumerate(itens):
                        _criar_card(it, i + 1, referencias=referencias)
                    _selecionados.intersection_update(_cards)
                    if _ancora["id"] not in _cards:
                        _ancora["id"] = None
                    if _foco["id"] not in _cards:
                        _foco["id"] = None
                    _atualizar_selecao_visual()
                _atualizar_layout_canvas()
            finally:
                # Só revela quando todos os cartões já estão montados.
                _mostrar_cartoes(True)
                try:
                    lista_canvas.configure(
                        scrollregion=lista_canvas.bbox('all'))
                except tk.TclError:
                    pass

        def _indice_do_card(iid: str) -> int | None:
            try:
                return _ordem.index(iid)
            except ValueError:
                return None

        def _destruir_card(iid: str) -> None:
            dados_card = _cards.pop(iid, None)
            if dados_card is not None:
                try:
                    dados_card["frame"].destroy()
                except tk.TclError:
                    pass
            if iid in _ordem:
                _ordem.remove(iid)
            _linhas_path.pop(iid, None)
            _textos_base.pop(iid, None)
            _selecionados.discard(iid)
            if _ancora["id"] == iid:
                _ancora["id"] = None
            if _foco["id"] == iid:
                _foco["id"] = None
            if _contagem["iid"] == iid:
                _contagem["iid"] = None

        def _atualizar_cartao_item(it: dict) -> None:
            """Cria/atualiza SÓ o cartão do item (sem remontar a lista)."""
            iid = str(it.get("id"))
            pos = _indice_do_card(iid)
            selecionado = iid in _selecionados
            focado = _foco["id"] == iid
            ancora = _ancora["id"] == iid
            if pos is not None:
                _destruir_card(iid)
                indice = pos + 1
            else:
                indice = len(_ordem) + 1
            _criar_card(it, indice, pos=pos)
            if selecionado:
                _selecionados.add(iid)
            if focado:
                _foco["id"] = iid
            if ancora:
                _ancora["id"] = iid
            _atualizar_selecao_visual((iid,))
            _cancelar_layout_agendado()
            _atualizar_layout_canvas()

        def _reordenar_cards_visual() -> None:
            """Reordena os widgets existentes sem destruir/recriar cartões."""
            frames = []
            for iid in _ordem:
                dados = _cards.get(iid)
                if dados is not None:
                    frames.append(dados["frame"])
            if not frames:
                return
            atuais = list(cards_host.pack_slaves())
            if atuais and atuais[0] is not frames[0]:
                try:
                    frames[0].pack_configure(before=atuais[0])
                except tk.TclError:
                    pass
            anterior = frames[0]
            for frame in frames[1:]:
                try:
                    frame.pack_configure(after=anterior)
                except tk.TclError:
                    pass
                anterior = frame
            for indice, iid in enumerate(_ordem, start=1):
                dados = _cards.get(iid)
                if dados is None:
                    continue
                numero = dados.get("numero")
                if numero is not None:
                    try:
                        numero.configure(text=str(indice))
                    except tk.TclError:
                        pass
            _cancelar_layout_agendado()
            _atualizar_layout_canvas()

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
            _definir_duracao_card(iid, texto)

        def _atualizar_contagem() -> None:
            player = getattr(self, "player", None)
            alvo = _item_em_reproducao() if player is not None else None
            if alvo is None:
                _restaurar_duracao(_contagem["iid"])
                _contagem["iid"] = None
                return
            _item, iid, caminho = alvo
            if not _card_existe(iid):
                _contagem["iid"] = None
                return
            duracao = getattr(player, "duracao_total", None)
            if not duracao:
                duracao = _duracao_cache.get(caminho)
            if not duracao:
                # URL (ex.: YouTube): o player não mede o arquivo remoto
                # (ffprobe só lê caminho local), então usa a duração já
                # capturada/estimada do item para a contagem regressiva.
                try:
                    duracao = float(
                        (_item or {}).get("duracao_estimada_segundos") or 0)
                except (TypeError, ValueError):
                    duracao = 0.0
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
                            _definir_duracao_card(outro_iid, texto)
            if _contagem["iid"] and _contagem["iid"] != iid:
                _restaurar_duracao(_contagem["iid"])
            restante = float(duracao)
            try:
                restante -= float(player.obter_tempo_decorrido())
            except (TypeError, ValueError):
                pass
            restante = max(0.0, restante)
            icone = "⏸" if pausado else "⏳"
            _definir_duracao_card(
                iid, f"{icone} {_formatar_duracao_segundos(restante)}")
            _contagem["iid"] = iid

        def _tick_contagem():
            _timers["contagem"] = None
            if not janela.winfo_exists():
                return
            player = getattr(self, "player", None)
            tocando = bool(player is not None
                           and getattr(player, "is_playing", False))
            if tocando or _contagem["iid"] is not None:
                try:
                    _atualizar_contagem()
                except Exception as exc:
                    log.debug("Falha ao atualizar a contagem da Ordem "
                              "de Serviço: %s", exc)
                atraso = _CONTAGEM_ATIVA_MS
            else:
                atraso = _CONTAGEM_REPOUSO_MS
            try:
                _timers["contagem"] = janela.after(atraso, _tick_contagem)
            except tk.TclError:
                pass

        def _ao_destruir_janela(event):
            if event.widget is not janela:
                return
            # Não perde um clique que ainda não chegou ao timer de gravação.
            _salvar_marcacoes_pendentes(avisar=False)
            for chave in ("contagem",):
                timer = _timers.get(chave)
                if timer is not None:
                    try:
                        janela.after_cancel(timer)
                    except tk.TclError:
                        pass
                    _timers[chave] = None
            for chave in ("inicio", "poll"):
                timer = _duracao_timers.get(chave)
                if timer is not None:
                    try:
                        janela.after_cancel(timer)
                    except tk.TclError:
                        pass
                    _duracao_timers[chave] = None
            _cancelar_layout_agendado()
            _esconder_indicador()

        janela.bind("<Destroy>", _ao_destruir_janela, add="+")
        _tick_contagem()

        # ── Botões ──
        btn_frame = tk.Frame(main, bg='#0d1117')
        btn_frame.grid(row=3, column=0, sticky='ew', pady=5)

        def _novo_servico():
            nome = tkinter.simpledialog.askstring("Nova Projeção",
                "Nome da programação:", parent=janela) if hasattr(tkinter, 'simpledialog') else None
            if not nome:
                # Fallback se simpledialog não estiver disponível
                nome_win = tk.Toplevel(janela)
                nome_win.title("Nova Projeção")
                nome_win.geometry("350x120")
                nome_win.configure(bg='#0d1117')
                nome_win.transient(janela)
                _centralizar_sobre(nome_win, janela)
                nome_win.after(50, nome_win.grab_set)
                tk.Label(nome_win, text="Nome da programação:", fg='#f0c040', bg='#0d1117',
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
            selecionado_antes = dados.get("_servico_selecionado")
            dados["servicos"].append({
                "id": novo_id,
                "nome": nome,
                "dia": dia_selecionado[0],
                "criado_em": datetime.now().isoformat(timespec="seconds"),
                "itens": [],
            })
            dados["_proximo_id_servico"] = max(
                dados.get("_proximo_id_servico", 1), novo_id + 1)
            dados["_servico_selecionado"] = novo_id
            if not _salvar_servicos_json(dados):
                dados["servicos"] = [s for s in dados["servicos"]
                                     if s.get("id") != novo_id]
                dados["_proximo_id_servico"] = novo_id
                if selecionado_antes is None:
                    dados.pop("_servico_selecionado", None)
                else:
                    dados["_servico_selecionado"] = selecionado_antes
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

        def _excluir_servico():
            """Exclui o serviço selecionado, sempre com confirmação."""
            serv = _servico_atual()
            if not serv:
                tkinter.messagebox.showwarning(
                    "Seleção", "Selecione um serviço.", parent=janela)
                return
            sid = serv.get("id")
            nome = (serv.get("nome") or "").strip() or f"Serviço {sid}"
            total = len(serv.get("itens") or [])
            if total == 1:
                detalhe = "\n\nO item dele também será removido."
            elif total:
                detalhe = f"\n\nOs {total} itens dele também serão removidos."
            else:
                detalhe = ""
            if not tkinter.messagebox.askyesno(
                    "Del Serviço",
                    f'Excluir o serviço "{nome}"?{detalhe}\n\n'
                    "Esta ação não pode ser desfeita.",
                    parent=janela, icon='warning', default='no'):
                return
            servicos_antes = list(dados["servicos"])
            selecionado_antes = dados.get("_servico_selecionado")
            dados["servicos"] = [s for s in dados["servicos"]
                                 if s.get("id") != sid]
            restantes = _ordenar_servicos()
            if restantes:
                dados["_servico_selecionado"] = restantes[0].get("id")
            else:
                dados.pop("_servico_selecionado", None)
            if not _salvar_servicos_json(dados):
                dados["servicos"] = servicos_antes
                if selecionado_antes is None:
                    dados.pop("_servico_selecionado", None)
                else:
                    dados["_servico_selecionado"] = selecionado_antes
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar a remoção em "
                    "servicos.json.", parent=janela)
                return
            # A execução não pode continuar apontando para o serviço removido.
            _SERVICO_PROXIMO_ITEM.pop(sid, None)
            _SERVICO_PROXIMO_ITEM.pop(nome, None)
            if _SERVICO_ITEM_REPRODUZINDO.get("servico_id") == sid:
                _SERVICO_ITEM_REPRODUZINDO.clear()
            esquecer_manter_videos_servico(sid)
            _item_escolhido["id"] = None
            servico_selecionado_id[0] = None
            _carregar_servicos()
            if combo_servico['values']:
                _on_servico_select()
            else:
                _restaurar_rotulo_servico()
                _carregar_itens()

        def _acao_botao_novo():
            """O botão da barra cria um serviço — ou exclui, se em edição."""
            if _renomear["id"] is not None:
                # Salva o nome digitado (clique fora da caixa) e só então
                # pede a confirmação da exclusão.
                _finalizar_renomear_servico()
                _excluir_servico()
            else:
                _novo_servico()

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
            _habilitar_maximizar_janela(add_win, area=self._area_monitor_operador())
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

            def _mostrar_preview_hino(texto: str) -> None:
                """Troca o texto do preview do hino sem depender do botão."""
                try:
                    preview_hino.config(state='normal')
                    preview_hino.delete('1.0', tk.END)
                    preview_hino.insert(tk.END, texto)
                    preview_hino.config(state='disabled')
                except tk.TclError:
                    pass

            def _ver_letra_hino():
                """Resolve o nº/termo digitado → letra do hino e mostra preview."""
                res = _resolver_hino()
                if not res[0]:
                    tkinter.messagebox.showwarning("Hino", res[1], parent=add_win)
                    return
                _, _, letra_snap, ref_display, _rid = res
                _mostrar_preview_hino(letra_snap)

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

            # Prevê a letra enquanto o operador digita o número, sem exigir o
            # clique em "🔍 Ver letra". O timer evita uma consulta por tecla.
            _estado_prev_hino = {"timer": None}

            def _atualizar_preview_hino(*_args) -> None:
                termo = hino_num_var.get().strip()
                if not termo:
                    _mostrar_preview_hino("")
                    return
                rows_match = _buscar_hino_por_termo(termo)
                if not rows_match:
                    _mostrar_preview_hino(
                        f'Nenhum hino encontrado para: "{termo}".')
                    return
                _mostrar_preview_hino(
                    rows_match[0].get("letra_completa", ""))

            def _confirmar_preview_hino() -> None:
                _estado_prev_hino["timer"] = None
                try:
                    if not add_win.winfo_exists():
                        return
                except tk.TclError:
                    return
                _atualizar_preview_hino()

            def _agendar_preview_hino(*_args) -> None:
                timer = _estado_prev_hino.get("timer")
                if timer is not None:
                    try:
                        add_win.after_cancel(timer)
                    except tk.TclError:
                        pass
                    _estado_prev_hino["timer"] = None
                try:
                    _estado_prev_hino["timer"] = add_win.after(
                        300, _confirmar_preview_hino)
                except tk.TclError:
                    pass

            hino_num_var.trace_add("write", _agendar_preview_hino)

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
                    _mostrar_preview_hino(letra_snap)

            hino_frame.pack_forget()

            # ── Painel de vídeo/música (tipos "video" e "audio") ──
            # Espelha o painel do hino: o operador digita o Nº/nome e o
            # resultado (número + nome da mídia) aparece imediatamente no
            # preview, sem precisar clicar em botão. Salva referencia_id
            # (id da tabela midia), como a busca pelo campo "Buscar".
            midia_num_var = tk.StringVar()
            midia_frame = tk.Frame(add_main, bg='#0d1117')
            tk.Label(midia_frame, text="Buscar vídeo/música por número:",
                     fg='#f0c040', bg='#0d1117',
                     font=("Arial", 11, "bold")).pack(anchor='w', pady=(6, 0))

            _linha_midia_num = tk.Frame(midia_frame, bg='#0d1117')
            _linha_midia_num.pack(fill='x', pady=2)
            tk.Label(_linha_midia_num, text="Nº ou nome:", fg='#c9d1d9',
                     bg='#0d1117', font=("Arial", 10)).pack(side='left')
            entry_midia_num = tk.Entry(_linha_midia_num,
                                       textvariable=midia_num_var,
                                       width=8, font=("Arial", 11), bg='#21262d',
                                       fg='#f0c040', insertbackground='#f0c040',
                                       bd=0, highlightthickness=0)
            entry_midia_num.pack(side='left', padx=(4, 8), ipady=2)
            tk.Label(_linha_midia_num, text="(ou trecho do nome)",
                     fg='#8b949e', bg='#0d1117',
                     font=("Arial", 9)).pack(side='left')

            preview_midia = tk.Text(midia_frame, height=3, wrap='word',
                                    font=("Arial", 9), bg='#161b22', fg='#c9d1d9',
                                    relief='flat', state='disabled',
                                    exportselection=False)
            preview_midia.pack(fill='x', pady=4)

            btn_copia_midia = tk.Button(
                midia_frame, text="📋 Copiar", font=("Arial", 9, "bold"),
                bg='#21262d', fg='#f0c040', activebackground='#30363d',
                cursor='hand2', padx=10, pady=1,
                command=lambda: _copiar_previa(preview_midia))
            btn_copia_midia.pack(anchor='e', pady=(0, 2))

            def _rotulo_midia(registro: dict) -> str:
                """Número + nome da mídia, como aparece na busca remota."""
                nome = (registro.get("nome_exibicao")
                        or registro.get("nome_original")
                        or os.path.basename(registro.get("caminho_arquivo") or ""))
                if _numero_do_titulo(nome) is not None:
                    return nome
                numero = registro.get("id")
                return f"{numero}. {nome}" if numero is not None else nome

            def _mostrar_preview_midia(texto: str) -> None:
                try:
                    preview_midia.config(state='normal')
                    preview_midia.delete('1.0', tk.END)
                    preview_midia.insert(tk.END, texto)
                    preview_midia.config(state='disabled')
                except tk.TclError:
                    pass

            def _resolver_midia():
                """Resolve o nº/nome digitado → mídia do acervo.

                Retorna (ok, msg_erro, ref_display, ref_id).
                """
                termo = midia_num_var.get().strip()
                if not termo:
                    return (False,
                            "Informe o número ou o nome do vídeo/música.",
                            "", None)
                tipo_busca = tipo_var.get()
                if tipo_busca not in ("video", "audio"):
                    tipo_busca = "video"
                rows_match = _buscar_midia_por_termo(termo, tipo=tipo_busca)
                if not rows_match:
                    return (False,
                            f'Nenhum vídeo/música encontrado para: "{termo}".',
                            "", None)
                ref_midia = rows_match[0]
                return (True, "", _rotulo_midia(ref_midia),
                        ref_midia.get("id"))

            def _atualizar_preview_midia(*_args) -> None:
                termo = midia_num_var.get().strip()
                if not termo:
                    _mostrar_preview_midia("")
                    return
                res = _resolver_midia()
                _mostrar_preview_midia(res[2] if res[0] else res[1])

            _estado_prev_midia = {"timer": None}

            def _confirmar_preview_midia() -> None:
                _estado_prev_midia["timer"] = None
                try:
                    if not add_win.winfo_exists():
                        return
                except tk.TclError:
                    return
                _atualizar_preview_midia()

            def _agendar_preview_midia(*_args) -> None:
                timer = _estado_prev_midia.get("timer")
                if timer is not None:
                    try:
                        add_win.after_cancel(timer)
                    except tk.TclError:
                        pass
                    _estado_prev_midia["timer"] = None
                try:
                    _estado_prev_midia["timer"] = add_win.after(
                        300, _confirmar_preview_midia)
                except tk.TclError:
                    pass

            midia_num_var.trace_add("write", _agendar_preview_midia)

            # Preenche o preview ao editar um vídeo/áudio existente
            if item_edit and (item_edit.get("tipo") or "").lower() in (
                    "video", "audio"):
                _midia_ed = None
                if item_edit.get("referencia_id"):
                    _rm_ed = db_query(
                        "SELECT * FROM midia WHERE id = ? AND ativo = 1",
                        (item_edit.get("referencia_id"),))
                    if _rm_ed:
                        _midia_ed = _rm_ed[0]
                _mostrar_preview_midia(
                    _rotulo_midia(_midia_ed) if _midia_ed
                    else (item_edit.get("titulo_custom") or ""))

            midia_frame.pack_forget()

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
                    texto = _texto_simples(an.get("texto") or "").strip()
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
            def _colar_url_youtube():
                _colar_texto_campo(youtube_url_entry)
                try:
                    add_win.after_idle(
                        lambda: _agendar_info_youtube(
                            atraso_ms=_YOUTUBE_INFO_COLAR_MS))
                except tk.TclError:
                    pass

            _menu_contexto_campo(
                youtube_url_entry,
                [("📋 Colar", _colar_url_youtube)])

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
                # Resultado da consulta em andamento (compartilhado com o
                # salvamento, que não deve disparar um segundo yt-dlp).
                "evento": None, "resultado": None,
                "resultado_url": "", "resultado_token": 0,
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
                evento = threading.Event()
                _yt_info["evento"] = evento
                _yt_info["resultado"] = None
                _yt_info["resultado_url"] = url
                _yt_info["resultado_token"] = token

                def _trabalho():
                    try:
                        info = _obter_info_youtube(url)
                    except Exception as exc:
                        log.exception("Falha ao obter informações do "
                                      "YouTube: %s", exc)
                        info = None
                    if token == _yt_info.get("token"):
                        _yt_info["resultado"] = info
                        _yt_info["resultado_url"] = url
                        _yt_info["resultado_token"] = token
                    evento.set()
                    try:
                        self.root.after(
                            0, lambda: _aplicar_info_youtube(info, url, token))
                    except (tk.TclError, RuntimeError):
                        pass

                threading.Thread(target=_trabalho, daemon=True,
                                 name="navepro-youtube-info").start()

            def _info_youtube_para_salvar(youtube_url: str):
                """Aproveita a consulta em andamento antes de consultar de novo.

                Sem isso, clicar em Salvar enquanto o yt-dlp já estava
                buscando o título disparava uma segunda consulta e o
                operador esperava duas vezes pela rede.
                """
                if (_yt_info.get("pendente")
                        and _yt_info.get("pendente_url") == youtube_url):
                    evento = _yt_info.get("evento")
                    if isinstance(evento, threading.Event):
                        try:
                            evento.wait(timeout=_YOUTUBE_INFO_ESPERA_S)
                        except Exception:
                            pass
                    if (_yt_info.get("resultado_url") == youtube_url
                            and _yt_info.get("resultado_token")
                            == _yt_info.get("token")):
                        return _yt_info.get("resultado")
                    return None
                return _obter_info_youtube(youtube_url)

            def _agendar_info_youtube(*_args, atraso_ms=None):
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

                espera = (_YOUTUBE_INFO_DEBOUNCE_MS if atraso_ms is None
                          else max(0, int(atraso_ms)))
                try:
                    _yt_info["timer"] = add_win.after(espera, _disparar)
                except tk.TclError:
                    pass

            def _atualizar_youtube():
                if youtube_var.get():
                    youtube_url_row.pack(fill='x', pady=(2, 0))
                else:
                    youtube_url_row.pack_forget()
                _agendar_info_youtube()

            def _ao_colar_url_youtube(event=None):
                # O <<Paste>> ocorre antes de o Entry receber o texto; o
                # after_idle agenda a consulta curta já com a URL final.
                try:
                    add_win.after_idle(
                        lambda: _agendar_info_youtube(
                            atraso_ms=_YOUTUBE_INFO_COLAR_MS))
                except tk.TclError:
                    pass

            youtube_url_entry.bind(
                "<<Paste>>", _ao_colar_url_youtube, add="+")
            youtube_url_entry.bind(
                "<Shift-Insert>", _ao_colar_url_youtube, add="+")
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
                # A busca por número/nome precede o seletor de arquivo, como
                # o painel do hino. Fica visível só para vídeo/áudio.
                if t in ("video", "audio"):
                    midia_frame.pack(fill='x', pady=(2, 0))
                else:
                    midia_frame.pack_forget()
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
                _aplicar_geometria("700x620" if t == "video"
                                   else "700x570" if t == "audio"
                                   else "700x600" if t == "versiculo"
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
                            info = _info_youtube_para_salvar(youtube_url)
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
                _usou_painel_midia = bool(
                    tipo in ("video", "audio")
                    and midia_num_var.get().strip())

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
                elif _usou_painel_midia:
                    res_m = _resolver_midia()
                    if not res_m[0]:
                        tkinter.messagebox.showwarning("Vídeo", res_m[1],
                                                       parent=add_win)
                        return
                    _, _, ref_display, ref_id = res_m
                    if not titulo or _usou_titulo_como_busca:
                        titulo = ref_display
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
                    letra_snap = _texto_simples(ref_an.get("texto") or "")
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
                    letra_snap = _texto_simples(ref_an.get("texto") or "")
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
                    if (modo_demonstracao()
                            and len(itens) >= LIMITE_DEMO_ITENS_PROJECAO):
                        tkinter.messagebox.showwarning(
                            "Modo Demonstração",
                            ("Esta projeção já tem o limite de "
                             f"{LIMITE_DEMO_ITENS_PROJECAO} itens do modo "
                             "demonstração.\nAtive a licença para adicionar "
                             "mais itens."),
                            parent=add_win)
                        return
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
                if tipo == "youtube" and youtube_url:
                    _, erro_download = self._baixar_video_youtube_ui(
                        add_win, youtube_url)
                    if erro_download:
                        tkinter.messagebox.showwarning(
                            "YouTube",
                            ("O item foi salvo, mas o vídeo não pôde ser "
                             "baixado agora.\nEle será baixado novamente "
                             "ao executar.\n\n" + erro_download),
                            parent=add_win)
                if getattr(self, "_shutting_down", False):
                    return
                item_salvo = itens[idx] if item_edit else novo_item
                _atualizar_cartao_item(item_salvo)
                _selecionar_item(str(novo_id), ver=True)
                add_win.destroy()

            tk.Button(add_main, text="💾 Salvar", font=("Arial", 12, "bold"),
                      bg='#238636', fg='white', activebackground='#2ea043',
                      command=_salvar_item, cursor='hand2', padx=20, pady=5
                      ).pack(pady=10)

        def _item_focado_id() -> str | None:
            """Item focado na lista (ou o primeiro selecionado)."""
            foco = _foco["id"]
            if foco in _selecionados:
                return foco
            sel = _ids_selecionados()
            return sel[0] if sel else None

        def _editar_item_selecionado():
            serv = _servico_atual()
            alvo = _item_focado_id()
            if not alvo:
                tkinter.messagebox.showwarning("Seleção", "Selecione um item.", parent=janela)
                return
            if not serv:
                return
            it = next((x for x in (serv.get("itens") or [])
                       if str(x.get("id")) == alvo), None)
            if it is None:
                return
            _abrir_editor_item(it)

        def _mover_item(direcao: int):
            """Move item para cima (-1) ou baixo (+1)."""
            alvo = _item_focado_id()
            if not alvo:
                return
            serv = _servico_atual()
            if not serv:
                return
            itens = list(serv.get("itens") or [])
            idx_atual = next((i for i, it in enumerate(itens)
                              if str(it.get("id")) == alvo), None)
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
            if idx_atual < len(_ordem) and idx_novo < len(_ordem):
                _ordem[idx_atual], _ordem[idx_novo] = (
                    _ordem[idx_novo], _ordem[idx_atual])
            _reordenar_cards_visual()
            _selecionar_item(alvo, ver=True)

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
            # Persiste os cliques pendentes antes de executar: a execução
            # pode marcar o mesmo item e deve ver o estado mais recente.
            _salvar_marcacoes_pendentes()
            escolhido = _item_escolhido["id"]
            # Consome a escolha do operador (uma única vez). A partir daqui a
            # seleção da lista é ignorada: o botão só avança item a item e, ao
            # terminar, volta ao primeiro — nunca mais volta ao item escolhido.
            _item_escolhido["id"] = None
            marcar = bool(marcar_reproduzidos_var.get())

            def _ao_terminar_item(item) -> None:
                if item is not None:
                    _sincronizar_marca_item(item.get("id"))

            res = self.executar_proximo_item_servico(
                serv, escolhido=escolhido,
                ao_destacar=lambda it: _selecionar_item(
                    str(it.get('id')), ver=True),
                parent=janela,
                marcar_reproduzido=marcar,
                ao_terminar=_ao_terminar_item)
            anterior = res.get('anterior_reproduzido_id')
            if anterior is not None:
                _sincronizar_marca_item(anterior)
            if not res.get('ok'):
                if res.get('codigo') == 'vazio':
                    tkinter.messagebox.showinfo(
                        "Vazio", res.get('erro', ''), parent=janela)
                else:
                    tkinter.messagebox.showwarning(
                        "Executar", res.get('erro', ''), parent=janela)

        btn_novo = tk.Button(
            btn_frame, text="➕ Nova Projeção", font=("Arial", 11, "bold"),
            bg='#238636', fg='white', activebackground='#2ea043',
            command=_acao_botao_novo, cursor='hand2', padx=16, pady=4)
        btn_editar = tk.Button(
            btn_frame, text="✏️ Editar Serviço", font=("Arial", 11, "bold"),
            bg='#1f6feb', fg='white', activebackground='#388bfd',
            command=_editar_servico, cursor='hand2', padx=12, pady=4)
        btn_excluir = tk.Button(
            btn_frame, text="🗑️ Excluir Itens", font=("Arial", 11, "bold"),
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

        def _clique_pertence(widget, alvo) -> bool:
            while widget is not None:
                if widget is alvo:
                    return True
                widget = getattr(widget, "master", None)
            return False

        def _confirmar_renomear_ao_clicar(event=None) -> None:
            """Salva a edição inline ao clicar fora da caixa "Programação"."""
            if _renomear["id"] is None:
                return
            widget = getattr(event, "widget", None)
            if widget is not None and (
                    _clique_pertence(widget, combo_servico)
                    or _clique_pertence(widget, btn_novo)):
                return
            _finalizar_renomear_servico()

        # O bind da janela cobre os widgets que não devolvem "break"; os
        # cartões (que devolvem) confirmam a edição nos seus próprios
        # handlers, e a barra de rolagem ganha um bind direto.
        janela.bind("<ButtonPress-1>", _confirmar_renomear_ao_clicar, add="+")
        scroll_y.bind("<ButtonPress-1>",
                      lambda e: _finalizar_renomear_servico(), add="+")

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

        _atualizar_botoes_dia()
        _carregar_servicos()
        # Se há programações no dia, seleciona a primeira
        if combo_servico['values']:
            _on_servico_select()
        else:
            servico_selecionado_id[0] = None
            _restaurar_rotulo_servico()
            _carregar_itens()
