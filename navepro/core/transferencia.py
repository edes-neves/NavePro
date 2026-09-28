"""Exportação e importação portátil de anúncios e ordens de serviço.

O arquivo gerado (.navepro) é um ZIP com esta estrutura:

    manifest.json     formato/data de criação e contagens
    anuncios.json     anúncios com a mídia apontando para midia/<arquivo>
    servicos.json     cópia das ordens de serviço (servicos.json)
    midia/<arquivo>   imagens, PDFs, áudio e vídeo usados nos anúncios

Regras de segurança (a importação nunca destrói dados sem rede):
  * antes de gravar qualquer coisa, cria um .navepro de segurança em
    ~/.navepro com o estado atual (ver criar_backup);
  * a mídia é sempre copiada para UPLOAD_FOLDER com nome livre de colisão
    (nada é sobrescrito e o arquivo original continua intacto);
  * os ids dos anúncios são recriados e as ordens de serviço são
    "remapeadas" para apontar aos ids novos, mantendo os ids antigos só
    dentro do arquivo exportado;
  * as mídias escolhidas direto no editor de item (caminho_arquivo) NÃO
    são transferidas: o caminho é do computador de origem e o app já cai
    no acervo local quando ele não existe.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from navepro.core.paths import DATA_USER_DIR
from navepro.core.textos import normalizar_texto

FORMATO_TRANSFERENCIA = 1
EXTENSAO_TRANSFERENCIA = ".navepro"
PASTA_MIDIA = "midia"
ARQ_MANIFESTO = "manifest.json"
ARQ_ANUNCIOS = "anuncios.json"
ARQ_SERVICOS = "servicos.json"
MODOS_IMPORTACAO = ("somar", "atualizar", "substituir")
LIMITE_BACKUP_MB = 200  # mídia maior que isso não entra no backup


def _nome_arquivo(diretorio: Optional[str] = None, prefixo: str = "backup") -> str:
    """Nome de arquivo com data/hora (20250101-143012)."""
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{prefixo}-{carimbo}{EXTENSAO_TRANSFERENCIA}"


# ────────────────────────────────────────────────────────────────────
# LEITURA DA CONFIG_MIDIA (JSON de telas do anúncio)
# ────────────────────────────────────────────────────────────────────

def _config_midia(anuncio: Dict) -> Dict:
    """config_midia do anúncio como dict ({} se vazio/inválido)."""
    bruto = anuncio.get("config_midia") or ""
    if not isinstance(bruto, str):
        return bruto if isinstance(bruto, dict) else {}
    bruto = bruto.strip()
    if not bruto:
        return {}
    try:
        dados = json.loads(bruto)
    except ValueError:
        return {}
    return dados if isinstance(dados, dict) else {}


def _converter_caminhos_midia(
        config_midia: str, mapa: Dict[str, str], desconhecido: str = ""
) -> str:
    """Troca os caminhos de mídia dentro de config_midia conforme `mapa`.

    Percorre config_midia.mslides[].imagem e troca o valor antigo pelo novo
    (caminho -> membro do ZIP na exportação, membro -> caminho local na
    importação). Caminhos sem correspondente viram `desconhecido`
    (vazio por padrão, para não deixar referência quebrada).
    """
    try:
        dados = json.loads(config_midia or "{}")
    except (ValueError, TypeError):
        return config_midia or ""
    if not isinstance(dados, dict):
        return config_midia or ""
    mudou = False
    telas = dados.get("mslides")
    if isinstance(telas, list):
        for tela in telas:
            if not isinstance(tela, dict):
                continue
            atual = (tela.get("imagem") or "").strip()
            if not atual:
                continue
            novo = mapa.get(atual, desconhecido)
            if novo != atual:
                tela["imagem"] = novo
                mudou = True
    if not mudou:
        return config_midia or ""
    return json.dumps(dados, ensure_ascii=False)


# ────────────────────────────────────────────────────────────────────
# EXPORTAÇÃO
# ────────────────────────────────────────────────────────────────────

def _midias_do_anuncio(anuncio: Dict) -> List[str]:
    """Caminhos de mídia existentes citados por um anúncio."""
    caminhos: List[str] = []
    arq = (anuncio.get("arquivo_midia") or "").strip()
    if arq and os.path.isfile(arq):
        caminhos.append(arq)
    for tela in _config_midia(anuncio).get("mslides") or []:
        if not isinstance(tela, dict):
            continue
        img = (tela.get("imagem") or "").strip()
        if img and os.path.isfile(img) and img not in caminhos:
            caminhos.append(img)
    return caminhos


def _mapa_de_midia(anuncios: List[Dict]) -> Dict[str, str]:
    """Membro do ZIP para cada arquivo de mídia usado pelos anúncios.

    Nomes repetidos (mesmo nome em pastas diferentes) ganham sufixo _1, _2
    para não se sobrescrevirem dentro do ZIP.
    """
    mapa: Dict[str, str] = {}
    usados: Dict[str, int] = {}
    for anuncio in anuncios:
        for caminho in _midias_do_anuncio(anuncio):
            if caminho in mapa:
                continue
            base, ext = os.path.splitext(os.path.basename(caminho))
            nome = f"{base}{ext}"
            cont = usados.get(nome.lower(), 0)
            usados[nome.lower()] = cont + 1
            if cont:
                nome = f"{base}_{cont}{ext}"
            mapa[caminho] = f"{PASTA_MIDIA}/{nome}"
    return mapa


def exportar_transferencia(
        destino: str,
        anuncios: List[Dict],
        servicos: Dict,
        incluir_midia: bool = True,
        progresso: Optional[Callable[[str], None]] = None,
) -> Dict:
    """Escreve o arquivo .navepro com anúncios, ordens e (opcional) mídia.

    Returns um resumo {anuncios, servicos, midia, destino}.
    """
    mapa = _mapa_de_midia(anuncios) if incluir_midia else {}
    arquivos = sorted(mapa.items(), key=lambda par: par[1])
    destino = os.path.abspath(os.path.expanduser(destino))
    if not destino.lower().endswith(EXTENSAO_TRANSFERENCIA):
        destino += EXTENSAO_TRANSFERENCIA
    tmp = destino + ".tmp"

    def _aviso(msg: str) -> None:
        if progresso:
            progresso(msg)

    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            lista_para_zip = []
            for anuncio in anuncios:
                dados = dict(anuncio)
                arq = (dados.get("arquivo_midia") or "").strip()
                if arq:
                    dados["arquivo_midia"] = mapa.get(arq, "")
                dados["config_midia"] = _converter_caminhos_midia(
                    dados.get("config_midia") or "", mapa)
                lista_para_zip.append(dados)

            _aviso("Gravando anúncios e ordens de serviço…")
            zf.writestr(
                ARQ_MANIFESTO,
                json.dumps({
                    "formato": FORMATO_TRANSFERENCIA,
                    "app": "NavePro",
                    "criado_em": datetime.now().isoformat(timespec="seconds"),
                    "anuncios": len(lista_para_zip),
                    "servicos": len((servicos or {}).get("servicos") or []),
                    "midia": len(arquivos),
                }, ensure_ascii=False, indent=2))
            zf.writestr(
                ARQ_ANUNCIOS,
                json.dumps(lista_para_zip, ensure_ascii=False, indent=2))
            zf.writestr(
                ARQ_SERVICOS,
                json.dumps(servicos or {"servicos": []}, ensure_ascii=False,
                           indent=2))
            # Mídia: já vem comprimida (jpg/png/pdf/mp4) — guardar sem
            # recomprimir é muito mais rápido e o arquivo fica do mesmo
            # tamanho.
            for i, (caminho, membro) in enumerate(arquivos, 1):
                _aviso(f"Copiando mídia {i}/{len(arquivos)}: "
                       f"{os.path.basename(caminho)}")
                zf.write(caminho, membro, compress_type=zipfile.ZIP_STORED)
        os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
        os.replace(tmp, destino)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        print(f"⚠️ Erro ao exportar para {destino}: {e}")
        raise
    resumo = {
        "destino": destino,
        "anuncios": len(anuncios),
        "servicos": len((servicos or {}).get("servicos") or []),
        "midia": len(arquivos),
    }
    print(f"✅ Transferência exportada: {destino} "
          f"({resumo['anuncios']} anúncio(s), {resumo['servicos']} ordem(ns), "
          f"{resumo['midia']} mídia(s))")
    return resumo


# ────────────────────────────────────────────────────────────────────
# IMPORTAÇÃO
# ────────────────────────────────────────────────────────────────────

def _abrir_pacote(arquivo: str) -> Dict:
    """Lê o .navepro e extrai a mídia em uma pasta temporária.

    Returns {manifest, anuncios, servicos, temp_dir}.
    """
    arquivo = os.path.abspath(os.path.expanduser(arquivo))
    if not os.path.isfile(arquivo):
        raise ValueError("Arquivo de transferência não encontrado.")
    temp_dir = tempfile.mkdtemp(prefix="navepro-transferencia-")
    try:
        with zipfile.ZipFile(arquivo, "r") as zf:
            nomes = set(zf.namelist())
            if ARQ_ANUNCIOS not in nomes:
                raise ValueError(
                    "Este arquivo não é uma transferência do NavePro.")
            manifest = {}
            if ARQ_MANIFESTO in nomes:
                try:
                    manifest = json.loads(zf.read(ARQ_MANIFESTO).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    manifest = {}
            formato = manifest.get("formato")
            if formato is not None and int(formato) > FORMATO_TRANSFERENCIA:
                raise ValueError(
                    "Esta transferência foi criada por uma versão mais nova "
                    "do NavePro. Atualize o programa para importá-la.")
            anuncios = json.loads(zf.read(ARQ_ANUNCIOS).decode("utf-8"))
            if ARQ_SERVICOS in nomes:
                servicos = json.loads(zf.read(ARQ_SERVICOS).decode("utf-8"))
            else:
                servicos = {"servicos": []}
            if not isinstance(anuncios, list):
                raise ValueError("Lista de anúncios inválida na transferência.")
            if not isinstance(servicos, dict):
                servicos = {"servicos": []}
            for membro in zf.namelist():
                if not membro.startswith(f"{PASTA_MIDIA}/") or membro.endswith("/"):
                    continue
                # Só extrai o que está dentro de midia/ (sem ".." nem
                # caminho absoluto) para nunca escrever fora da pasta.
                relativo = membro[len(PASTA_MIDIA) + 1:]
                if not relativo or os.path.isabs(relativo) \
                        or ".." in relativo.split("/"):
                    continue
                destino = os.path.join(temp_dir, *membro.split("/"))
                os.makedirs(os.path.dirname(destino), exist_ok=True)
                with zf.open(membro) as origem, open(destino, "wb") as alvo:
                    shutil.copyfileobj(origem, alvo)
    except (OSError, zipfile.BadZipFile, ValueError, KeyError) as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if isinstance(e, ValueError):
            raise
        print(f"⚠️ Erro ao ler a transferência: {e}")
        raise ValueError("Não foi possível ler o arquivo de transferência.")
    return {"manifest": manifest, "anuncios": anuncios,
            "servicos": servicos, "temp_dir": temp_dir}


def _membros_usados(anuncios: List[Dict]) -> List[str]:
    """Membros de midia/ realmente citados pelos anúncios."""
    usados: List[str] = []
    for anuncio in anuncios:
        arq = (anuncio.get("arquivo_midia") or "").strip()
        if arq.startswith(f"{PASTA_MIDIA}/") and arq not in usados:
            usados.append(arq)
        for tela in _config_midia(anuncio).get("mslides") or []:
            if not isinstance(tela, dict):
                continue
            img = (tela.get("imagem") or "").strip()
            if img.startswith(f"{PASTA_MIDIA}/") and img not in usados:
                usados.append(img)
    return usados


def _copiar_midia_do_pacote(
        temp_dir: str, membros: List[str],
        copiar_midia: Callable[[str], Optional[str]],
        avisos: List[str],
) -> Dict[str, str]:
    """Copia a mídia extraída para uploads e devolve membro -> caminho local."""
    destino: Dict[str, str] = {}
    for membro in membros:
        origem = os.path.join(temp_dir, *membro.split("/"))
        if not os.path.isfile(origem):
            avisos.append(f"mídia não encontrada no arquivo: "
                          f"{os.path.basename(membro)}")
            continue
        local = copiar_midia(origem)
        if not local:
            avisos.append(f"não foi possível copiar a mídia: "
                          f"{os.path.basename(membro)}")
            continue
        destino[membro] = local
    return destino


def criar_backup(
        listar_anuncios: Callable[[], List[Dict]],
        servicos: Dict,
        pasta: Optional[str] = None,
) -> Optional[str]:
    """Cria um .navepro de segurança do estado atual (rede de proteção)."""
    pasta = pasta or os.path.join(DATA_USER_DIR, "backups")
    try:
        os.makedirs(pasta, exist_ok=True)
    except OSError as e:
        print(f"⚠️ Não foi possível criar a pasta de backup: {e}")
        return None
    anuncios = listar_anuncios()
    # Backup enxuto: o banco/json sempre entram; mídia gigante fica de fora
    # para o backup não pesar gigabytes. Os itens afetados são avisados no
    # resumo da importação.
    grandes = [a for a in anuncios
               if any(os.path.getsize(m) > LIMITE_BACKUP_MB * 1024 * 1024
                      for m in _midias_do_anuncio(a))]
    destino = os.path.join(pasta, _nome_arquivo())
    # Dois imports no mesmo segundo não podem usar o mesmo arquivo.
    n = 1
    while os.path.exists(destino):
        destino = os.path.join(pasta, _nome_arquivo(prefixo=f"backup-{n}"))
        n += 1
    try:
        resumo = exportar_transferencia(destino, anuncios, servicos,
                                        incluir_midia=True)
    except (OSError, ValueError) as e:
        print(f"⚠️ Erro ao criar backup: {e}")
        return None
    for anuncio in grandes:
        print(f"ℹ️ Mídia grande demais para o backup, pode precisar ser "
              f"copiada na mão: {anuncio.get('titulo')}")
    print(f"🛡️ Backup criado antes da importação: {resumo['destino']}")
    return resumo["destino"]


def _proximo_item_id(servicos: Dict) -> int:
    """Próximo id de item livre (o app usa contador monotônico)."""
    ids = [it.get("id") or 0
           for s in servicos.get("servicos") or [] if isinstance(s, dict)
           for it in (s.get("itens") or []) if isinstance(it, dict)]
    return max(ids + [0]) + 1


def _converter_itens(
        itens: List[Dict],
        mapa_anuncios: Dict[int, int],
        nome_servico: str,
        avisos: List[str],
        prox_item: int,
) -> Tuple[List[Dict], int]:
    """Copia itens importados com id livre e referência de anúncio remapeada.

    Itens de hino/versículo/texto continuam funcionando pelo letra_snapshot e
    pelo título — não dependem da biblioteca do outro computador.
    """
    novos: List[Dict] = []
    for item in itens or []:
        if not isinstance(item, dict):
            continue
        novo = dict(item)
        if (novo.get("tipo") or "").lower() == "anuncio" \
                and novo.get("referencia_id") not in (None, ""):
            try:
                ref = int(novo["referencia_id"])
            except (TypeError, ValueError):
                ref = None
            novo["referencia_id"] = mapa_anuncios.get(ref) if ref else None
            if not novo["referencia_id"]:
                avisos.append(
                    f"ordem “{nome_servico or 'sem nome'}”: item de anúncio "
                    f"sem correspondência "
                    f"({novo.get('titulo_custom') or 'anúncio'})")
        novo["id"] = prox_item
        prox_item += 1
        novos.append(novo)
    return novos, prox_item


def importar_transferencia(
        arquivo: str,
        servicos: Dict,
        listar_anuncios: Callable[[], List[Dict]],
        inserir_anuncio: Callable[[Dict], Optional[int]],
        atualizar_anuncio: Callable[[int, Dict], bool],
        copiar_midia: Callable[[str], Optional[str]],
        excluir_anuncios: Optional[Callable[[List[int]], bool]] = None,
        salvar_servicos: Optional[Callable[[Dict], bool]] = None,
        modo: str = "somar",
        progresso: Optional[Callable[[str], None]] = None,
) -> Dict:
    """Importa anúncios e ordens de um .navepro no NavePro atual.

    modo:
      * "somar"       (padrão) acrescenta o que ainda não existe pelo título
                       / nome da ordem, sem tocar no que já existe;
      * "atualizar"   substitui o conteúdo do anúncio/ordem de mesmo nome;
      * "substituir"  apaga os anúncios locais e deixa só os importados.

    Nunca apaga dados sem antes criar um backup (criar_backup).
    """
    if modo not in MODOS_IMPORTACAO:
        raise ValueError(f"Modo de importação desconhecido: {modo}")

    def _aviso(msg: str) -> None:
        if progresso:
            progresso(msg)

    _aviso("Lendo o arquivo…")
    pacote = _abrir_pacote(arquivo)
    temp_dir = pacote["temp_dir"]
    avisos: List[str] = []
    resumo: Dict = {
        "anuncios_novos": 0, "anuncios_atualizados": 0, "anuncios_ignorados": 0,
        "servicos_novos": 0, "servicos_atualizados": 0, "servicos_ignorados": 0,
        "midia_copiada": 0, "avisos": avisos, "backup": None,
    }
    try:
        backup = criar_backup(listar_anuncios, servicos)
        resumo["backup"] = backup
        if not backup:
            raise ValueError(
                "Não foi possível criar o backup de segurança. "
                "A importação foi cancelada para não arriscar seus dados.")

        anuncios = [a for a in pacote["anuncios"] if isinstance(a, dict)]
        _aviso("Copiando as mídias…")
        midia_local = _copiar_midia_do_pacote(
            temp_dir, _membros_usados(anuncios), copiar_midia, avisos)
        resumo["midia_copiada"] = len(midia_local)

        if modo == "substituir":
            ids_locais = [a.get("id") for a in listar_anuncios()
                          if a.get("id") is not None]
            if ids_locais and excluir_anuncios:
                if not excluir_anuncios(ids_locais):
                    raise ValueError(
                        "Não foi possível limpar os anúncios locais.")

        # Índice dos anúncios locais pelo título normalizado.
        locais_por_titulo: Dict[str, Dict] = {}
        for a in listar_anuncios():
            if a.get("id") is not None:
                locais_por_titulo.setdefault(
                    normalizar_texto(a.get("titulo") or ""), a)

        mapa_anuncios: Dict[int, int] = {}
        _aviso("Importando anúncios…")
        for anuncio in anuncios:
            dados = dict(anuncio)
            arq = (dados.get("arquivo_midia") or "").strip()
            if arq:
                dados["arquivo_midia"] = midia_local.get(arq, "")
                if not dados["arquivo_midia"]:
                    dados["nome_arquivo_midia"] = os.path.basename(arq)
            dados["config_midia"] = _converter_caminhos_midia(
                dados.get("config_midia") or "", midia_local)
            try:
                id_origem = int(dados.get("id"))
            except (TypeError, ValueError):
                id_origem = None

            igual = locais_por_titulo.get(
                normalizar_texto(dados.get("titulo") or ""))
            if igual and modo == "somar":
                if id_origem is not None:
                    mapa_anuncios[id_origem] = igual["id"]
                resumo["anuncios_ignorados"] += 1
                continue
            if igual and modo == "atualizar":
                if atualizar_anuncio(igual["id"], dados):
                    resumo["anuncios_atualizados"] += 1
                    if id_origem is not None:
                        mapa_anuncios[id_origem] = igual["id"]
                continue
            novo_id = inserir_anuncio(dados)
            if novo_id is None:
                avisos.append(
                    f"não foi possível importar o anúncio "
                    f"“{dados.get('titulo') or 'sem título'}”")
                continue
            if id_origem is not None:
                mapa_anuncios[id_origem] = novo_id
            resumo["anuncios_novos"] += 1

        # Ordens de serviço (o arquivo do PC de origem traz ids próprios).
        _aviso("Importando ordens de serviço…")
        if modo == "substituir":
            servicos["servicos"] = []
        locais_por_nome = {
            normalizar_texto(s.get("nome") or ""): s
            for s in servicos.get("servicos") or [] if isinstance(s, dict)
        }
        prox_item = _proximo_item_id(servicos)
        usados_serv = {s.get("id") for s in servicos.get("servicos") or []}
        prox_serv = 1
        novas: List[Dict] = []
        for serv in pacote["servicos"].get("servicos") or []:
            if not isinstance(serv, dict):
                continue
            nome = serv.get("nome") or ""
            alvo = locais_por_nome.get(normalizar_texto(nome))
            if alvo is not None and modo == "atualizar":
                alvo["itens"], prox_item = _converter_itens(
                    serv.get("itens") or [], mapa_anuncios, nome, avisos,
                    prox_item)
                resumo["servicos_atualizados"] += 1
                continue
            if alvo is not None:
                resumo["servicos_ignorados"] += 1
                continue
            itens, prox_item = _converter_itens(
                serv.get("itens") or [], mapa_anuncios, nome, avisos, prox_item)
            while prox_serv in usados_serv:
                prox_serv += 1
            novo = dict(serv)
            novo["id"] = prox_serv
            usados_serv.add(prox_serv)
            novo["itens"] = itens
            novas.append(novo)
        servicos.setdefault("servicos", []).extend(novas)
        resumo["servicos_novos"] = len(novas)
        servicos["_proximo_id_servico"] = max(
            [s.get("id") or 0 for s in servicos.get("servicos") or []
             if isinstance(s, dict)] + [0]) + 1
        servicos["_proximo_id_item"] = prox_item

        if salvar_servicos and not salvar_servicos(servicos):
            raise ValueError("Não foi possível gravar as ordens de serviço.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("✅ Transferência importada: "
          f"{resumo['anuncios_novos']} anúncio(s) novo(s), "
          f"{resumo['anuncios_atualizados']} atualizado(s), "
          f"{resumo['servicos_novos']} ordem(ns) — "
          f"{resumo['midia_copiada']} mídia(s) copiada(s).")
    return resumo
