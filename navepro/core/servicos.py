"""Ordens de Serviço — armazenamento em arquivo JSON.

Lê/grava ~/.navepro/servicos.json, migra UMA vez as ordens do banco legado,
reaproveita o menor id livre e reúne helpers de itens (faixa de versículos,
slides de versículo por faixa, reordenação e extração de texto de PDF).
Extraído de NavePro.py sem alteração de comportamento.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess

from navepro.core.banco import db_query
from navepro.core.log import get_logger
from navepro.core.paths import SERVICOS_FILE

log = get_logger("servicos")


def _carregar_servicos_json() -> dict:
    """Lê ~/.navepro/servicos.json e devolve a estrutura de ordens de serviço.

    Estrutura:
      {"servicos": [{"id", "nome", "data_servico", "criado_em", "itens": [
          {"id", "tipo", "referencia_id", "titulo_custom", "letra_snapshot",
           "caminho_arquivo", "youtube_url", "duracao_estimada_segundos"}...]}],
       "_proximo_id_servico": int, "_proximo_id_item": int}
    """
    try:
        with open(SERVICOS_FILE, encoding="utf-8") as f:
            dados = json.load(f)
        if isinstance(dados, dict) and isinstance(dados.get("servicos"), list):
            dados.setdefault("_proximo_id_servico", 1)
            dados.setdefault("_proximo_id_item", 1)
            # Remove a data automática (não editável) de versões anteriores.
            for _s in dados.get("servicos", []):
                if isinstance(_s, dict):
                    _s.pop("data_servico", None)
                    # Migração: "apresentacao" foi unificada com "sermao"
                    # (o tipo "sermao" agora aceita vídeo/áudio/apresentação).
                    for _it in _s.get("itens") or []:
                        if isinstance(_it, dict) and \
                                (_it.get("tipo") or "").lower() == "apresentacao":
                            _it["tipo"] = "sermao"
            return dados
    except (OSError, ValueError):
        pass
    return {"servicos": [], "_proximo_id_servico": 1, "_proximo_id_item": 1}


def _salvar_servicos_json(dados: dict) -> bool:
    """Persiste as ordens de serviço em ~/.navepro/servicos.json (atômico)."""
    try:
        os.makedirs(os.path.dirname(SERVICOS_FILE), exist_ok=True)
        tmp = SERVICOS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SERVICOS_FILE)
        return True
    except OSError as e:
        log.exception(f"⚠️ Erro ao salvar ordens de serviço: {e}")
        return False


def _proximo_id_servico_livre(dados: dict) -> int:
    """Menor id positivo ainda não usado em servicos.json.

    Permite reaproveitar o menor número vazio após uma exclusão
    (mesma lógica do _proximo_id_anuncio_livre).
    """
    usados = {s.get("id") for s in dados.get("servicos", [])
              if isinstance(s, dict)}
    cand = 1
    while cand in usados:
        cand += 1
    return cand


def _migrar_servicos_do_banco() -> bool:
    """Migra UMA vez as ordens de serviço do SQLite para servicos.json.

    Se servicos.json ainda não existir e o banco tiver dados, copia tudo
    (idempotente). As tabelas servicos/itens_servico NÃO são apagadas:
    ficam como backup invisível (sem quebrar o reuso de IDs existente).
    """
    if os.path.exists(SERVICOS_FILE):
        return False
    try:
        rows = db_query(
            "SELECT id, nome, data_servico, criado_em FROM servicos "
            "WHERE ativo = 1 ORDER BY id")
    except Exception:
        return False
    if not rows:
        return False
    dados = {"servicos": [], "_proximo_id_servico": 1, "_proximo_id_item": 1}
    for r in rows:
        sid = r["id"]
        try:
            itens = db_query(
                "SELECT id, tipo, referencia_id, titulo_custom, letra_snapshot, "
                "duracao_estimada_segundos FROM itens_servico WHERE servico_id = ? "
                "ORDER BY ordem", (sid,))
        except Exception:
            itens = []
        novos_itens = []
        for it in itens or []:
            novos_itens.append({
                "id": it.get("id"),
                "tipo": it.get("tipo") or "slide",
                "referencia_id": it.get("referencia_id"),
                "titulo_custom": it.get("titulo_custom") or "",
                "letra_snapshot": it.get("letra_snapshot") or "",
                "duracao_estimada_segundos": it.get("duracao_estimada_segundos") or 0,
            })
            dados["_proximo_id_item"] = max(
                dados["_proximo_id_item"], (it.get("id") or 0) + 1)
        dados["servicos"].append({
            "id": sid,
            "nome": r["nome"],
            "data_servico": r.get("data_servico"),
            "criado_em": r.get("criado_em")
                         or datetime.now().isoformat(timespec="seconds"),
            "itens": novos_itens,
        })
        dados["_proximo_id_servico"] = max(dados["_proximo_id_servico"], sid + 1)
    if _salvar_servicos_json(dados):
        log.info(f"✅ Ordens de serviço migradas do banco para {SERVICOS_FILE}")
        return True
    return False


# Ponteiro de execução por serviço (janela "Ordem de Serviço"): cada clique
# em "Executar Serviço" reproduz APENAS o próximo item da lista e para.
# Chave = id do serviço (ou nome como fallback). Valor = índice do item
# que deve ser reproduzido no próximo clique.
_SERVICO_PROXIMO_ITEM: dict = {}


def _analisar_faixa_versiculos(texto: str) -> tuple:
    """Interpreta o campo "Versículo" do editor de item da Ordem de Serviço.

    Aceita três formas:
      - vazio  → capítulo inteiro (v_ini/v_fim = None)
      - "5"    → um versículo
      - "1-7"  → faixa inclusiva (permite espaços: "1 - 7")

    Retorna (ok, msg_erro, v_ini, v_fim).
    """
    bruto = (texto or "").strip()
    if not bruto:
        return (True, "", None, None)
    if bruto.isdigit():
        v = int(bruto)
        if v < 1:
            return (False, "O versículo deve ser maior que zero.", None, None)
        return (True, "", v, v)
    partes = [p.strip() for p in bruto.split("-")]
    if len(partes) != 2 or not (partes[0].isdigit() and partes[1].isdigit()):
        return (False,
                "O versículo deve ser um número (\"5\"), uma faixa "
                "(\"1-7\") ou vazio para o capítulo inteiro.",
                None, None)
    ini, fim = int(partes[0]), int(partes[1])
    if ini < 1 or fim < 1:
        return (False, "O versículo deve ser maior que zero.", None, None)
    if ini > fim:
        return (False,
                f"A faixa está invertida: \"{ini}-{fim}\". "
                "Escreva do menor para o maior (ex.: \"1-7\").",
                None, None)
    return (True, "", ini, fim)


def _faixa_versiculo_item(item: dict) -> str:
    """Texto do campo "Versículo" de um item já salvo (ex.: "1-7").

    Devolve "" quando o item não tem faixa guardada — ou seja, quando é um
    versículo único ou o capítulo inteiro (que continuam em um slide só).
    """
    pares = item.get("versiculos")
    if not isinstance(pares, list) or len(pares) < 2:
        return ""
    numeros = []
    for par in pares:
        if isinstance(par, (list, tuple)) and par:
            try:
                numeros.append(int(par[0]))
            except (TypeError, ValueError):
                continue
    if len(numeros) < 2:
        return ""
    ini, fim = numeros[0], numeros[-1]
    if ini == fim:
        return str(ini)
    return f"{ini}-{fim}"


def _slides_versiculo_item(item: dict) -> list[tuple]:
    """Slides de projeção de um item do tipo "versiculo".

    Item com faixa (campo "1-7") vira um slide por versículo, navegável com
    ◀/▶ no telão. Item de versículo único ou de capítulo inteiro — inclusive
    os já salvos por versões anteriores — continua em um slide só, com o
    texto do snapshot, exatamente como antes.
    """
    letra = (item.get('letra_snapshot') or '').strip()
    titulo = (item.get('titulo_custom') or '').strip()
    pares = item.get("versiculos")
    if isinstance(pares, list) and len(pares) > 1:
        # O título gerado traz a faixa ("João 3:1-7"); cada slide mostra o
        # versículo específico ("João 3:1"). Título digitado à mão pelo
        # operador não tem faixa: mostramos o número entre parênteses.
        faixa_titulo = re.match(r"^(.*?):\d+\s*-\s*\d+$", titulo)
        slides = []
        for par in pares:
            if not isinstance(par, (list, tuple)) or len(par) < 2:
                continue
            try:
                numero = int(par[0])
            except (TypeError, ValueError):
                continue
            texto = (par[1] or "").strip()
            if not texto:
                continue
            if faixa_titulo:
                ref = f"{faixa_titulo.group(1)}:{numero}"
            elif titulo:
                ref = f"{titulo} ({numero})"
            else:
                ref = str(numero)
            slides.append((texto, ref))
        if slides:
            return slides
    return [(letra, titulo)]


def _reordenar_itens_servico(itens: list[dict], id_origem: int, id_destino: int) -> list[dict]:
    """Move o item id_origem para a posição de id_destino, preservando o resto.

    Retorna a nova lista (mesma list se origem/destino inexistentes ou iguais).
    """
    nova = list(itens)
    idx_orig = next((i for i, it in enumerate(nova) if it.get("id") == id_origem), None)
    idx_dest = next((i for i, it in enumerate(nova) if it.get("id") == id_destino), None)
    if idx_orig is None or idx_dest is None or idx_orig == idx_dest:
        return nova
    item = nova.pop(idx_orig)
    nova.insert(idx_dest, item)
    return nova


def _extrair_texto_pdf(caminho: str) -> str | None:
    """Extrai o texto de um PDF usando pypdf (com fallback para pdftotext).

    Retorna string de texto (páginas separadas por linha em branco) ou None
    se o PDF não tiver texto extraível (ex.: só imagens).
    """
    try:
        from pypdf import PdfReader
        leitor = PdfReader(caminho)
        paginas: list[str] = []
        for pagina in leitor.pages:
            texto = (pagina.extract_text() or "").strip()
            if texto:
                paginas.append(texto)
        if paginas:
            return "\n\n".join(paginas)
    except Exception as e:
        log.warning(f"⚠️ pypdf falhou ao ler {caminho}: {e}")

    try:
        resultado = subprocess.run(
            ["pdftotext", "-layout", caminho, "-"],
            capture_output=True, text=True, timeout=30)
        if resultado.returncode == 0 and resultado.stdout.strip():
            return resultado.stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        log.warning(f"⚠️ pdftotext falhou ao ler {caminho}: {e}")
    return None

