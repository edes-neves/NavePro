# NavPro — Sistema de Projeção para Igreja

Aplicativo desktop (Python/Tkinter) para **projeção multimídia em dois monitores**: o monitor principal (1) controla tudo e o segundo monitor (2) exibe o **telão** (letras de hinos, Bíblia, mídias) em tela cheia para a congregação.

Desenvolvido para Ubuntu (Python 3 + Tkinter), empacotado como AppImage.

---

## Funcionalidades

| Área | Descrição |
|---|---|
| **Projeção** | Exibe letras, versículos e mídias no monitor 2 (telão), com configuração de fonte, cor e tamanho. |
| **📖 Hinos / Letras** | CRUD de hinos (artista, CCLI, categoria, letra completa), importação XML/TXT, busca, projeção com navegação por slides. |
| **✝️ Bíblia** | Importação de bíblias em XML/TXT/JSON, seleção de versão/livro/capítulo/versículo, busca por texto e projeção sincronizada com o telão. |
| **📋 Ordem de Serviço** | Montagem de roteiros de culto com itens (hinos, mídias), com letras em snapshot e tempo estimado. |
| **📦 Gerenciar Banco de Mídia** | Organização das mídias utilizadas nas apresentações. |
| **🎨 Projeção (config)** | Mesmo diálogo de ajustes de aparência usado por Hinos e Bíblia. |

---

## Janela Hinos / Letras

- **Busca** (campo `Buscar por número, título, artista ou letra...`):
  - É um **placeholder real**: cinza quando vazio, some ao focar e volta ao sair sem digitar.
  - **Termo numérico** → busca pelo **número do hino que está no começo do título** (ex.: digitar `11` encontra `"11 - Maior Que Tudo"`), **não** pelo ID interno.
  - **Termo de texto** → busca por fragmento em título, artista e letra completa.
- **➕ Novo Hino / ✏️ Editar**: formulário com título, artista, compositor, CCLI, categoria e letra.
- **🗑️ Excluir**: **exclusão física** (`DELETE FROM letras`) — o ID sai do banco junto com o conteúdo.
- **📥 Importar (XML/TXT)**: abre o **seletor de arquivos do usuário** (home), escondendo pastas ocultas (`.`) e mostrando só `*.xml`/`*.txt`; importa coleções em formato OpenLyrics (como as pastas `NHA/` e `HASD/`).
- **📺 Projetar**: projeta o hino selecionado em slides no telão, com painel **◀ Anterior / ▶ Próximo / ⏹ Parar (Esc)**, ajuste de tamanho **A−/A+** e navegação também por **setas do teclado**.

### Onde fica o "número" do hino?
O número exibido na primeira coluna é o **ID** interno. O número real do hinário está no **título** (`"13 - ..."`). Por isso a busca numérica lê o número inicial do título (função `_numero_do_titulo`), evitando confusão quando IDs foram apagados ou há registros desativados.

---

## Janela Bíblia

- **Versão padrão**: ao abrir, seleciona **"Almeida Revista e Corrigida"** se ela existir no banco (senão, a primeira versão disponível). A lista de versões é lida do banco (`DISTINCT versao`).
- **Importar Bíblia** (`📥`): o botão abre um **seletor no home do usuário**, sem pastas ocultas (`.`) e com apenas `*.xml` / `*.txt` / `*.json`.
- **Navegação**: Livro + Cap + Versículo (V vazio = capítulo inteiro) + botão **Ir**.
- **Busca por texto** (`Buscar versículo por texto...`): LIKE no texto da versão selecionada.
- **📺 Projetar** (controle de projeção 🎬): exibe o capítulo na janela com o versículo atual **destacado** (fundo roxo `#6e40c9`) e projeta cada versículo no telão.
- **Sincronização Monitor 1 ↔ Monitor 2**: ao navegar (botões ◀ ▶ **ou** setas do teclado) o versículo avança **junto** no telão e na janela — o campo "V:" acompanha, o destaque se move e a tela rola até o versículo. **⏹ / Esc** encerra e limpa o destaque.

### Formatos aceitos na importação de Bíblia

**XML (Zefania)** — `AS21.xml`:
```xml
<XMLBIBLE biblename="Almeida Século 21">
  <BIBLEBOOK bnumber="1" bname="Gênesis">
    <CHAPTER cnumber="1"><VERS vnumber="1">...</VERS></CHAPTER>
  </BIBLEBOOK>
</XMLBIBLE>
```

**TXT (Almeida Revista e Corrigida)** — `biblia-em-txt.txt`:
```
GÊNESIS
1
No princípio criou Deus os céus e a terra.
...
```
Autodetecção de livro (romanos I/II, nomes com acentos, cabeçalhos colados como `AMÓS1`).

**JSON** — 4 estruturas aceitas:

1. Objeto aninhado (versículo → texto):
```json
{"Gênesis": {"1": {"1": "No princípio..."}}}
```
2. Objeto com capítulos como listas:
```json
{"Gênesis": {"1": ["No princípio...", "Era a terra..."]}}
```
3. `books` com capítulos por objetos de versículo (formato GetBible):
```json
{
  "version": "nvi",
  "books": [{"name": "Gênesis", "chapters": [[{"verse": 1, "text": "..."}]]}]
}
```
4. Lista plana de versículos:
```json
[{"book": "Gênesis", "chapter": 1, "verse": 1, "text": "..."}]
```

Particularidades tratadas:
- Arquivos com **BOM UTF-8** são aceitos (abertura com `utf-8-sig`).
- Livros são **normalizados sem acentos** e com apelidos (`1 Coríntios`, `II Reis`, `Cânticos`, `Lamentações`...).
- A versão é lida de `version/versao/biblename/translation/nome/name` ou do **nome do arquivo**.
- Livros não reconhecidos são listados no aviso ao final da importação.

---

## Banco de dados

Localização: **`~/.navepro/midia.db`** (SQLite).

Tabelas principais:

| Tabela | Uso |
|---|---|
| `letras` | Hinos: `id`, `titulo`, `artista`, `compositor`, `ccli_numero`, `categoria`, `idioma`, `letra_completa`, `ativo` |
| `versiculos` | Bíblia: `id`, `versao`, `livro`, `capitulo`, `versiculo`, `texto` |
| `midia` | Mídias do acervo (com FTS em `midia_fts` para busca) |
| `servicos` / `itens_servico` | Ordem de Serviço: itens com `letra_snapshot` (cópia da letra) e `referencia_id` |

Notas:
- A exclusão de hinos é **física**; não há chave estrangeira para `letras.id` (a Ordem de Serviço guarda cópia da letra).
- SQLite não suporta `COUNT(DISTINCT a, b)` — contagens compostas usam concatenação.

---

## Como executar

**Requisitos:** Python 3 + Tkinter (no Ubuntu: `sudo apt install python3-tk`).

```bash
python3 NavePro.py
```

### Gerar AppImage
Siga o passo a passo em `Gerar.AppImage` (resumo):
```bash
cp NavePro.py AppDir/usr/bin/NavePro.py
chmod +x AppDir/AppRun AppDir/navepro.desktop
ARCH=x86_64 appimagetool AppDir NavePro.AppImage
./NavePro.AppImage
```

> Importante: **edite sempre `NavePro.py` na raiz** e só depois copie para `AppDir/usr/bin/`. As cópias em `AppDir/`, `tmp/` e `Sistema.AppDir/` são artefatos de build (ignorados pelo git).

---

## Estrutura do projeto

```
NavPro.py            # Aplicativo principal (interface + projeção + importadores)
AS21.xml             # Bíblia Almeida Século 21 (XML Zefania)
biblia-em-txt.txt    # Bíblia Almeida Revista e Corrigida (TXT)
NHA/                 # Hinário (OpenLyrics XML) — Novo Hinário Adventista
HASD/                # Hinário (OpenLyrics XML)
backend/             # Upload remoto (servidor + template)
img/, Icon*.ico/png/xbm  # Ícones do app
Gerar.AppImage       # Passo a passo para empacotar o AppImage
.gitignore
```

---

## Ajustes comuns

- **Tamanho das janelas**: `janela.geometry("LARGURAxALTURA")` em `janela_hinos` (Hinos) e `janela_biblia` (Bíblia).
- **Configuração local** (`config.json`, ignorado do git): cidade/estado, monitor do telão e player.

---

## Histórico recente

- Importação de Bíblia em **XML/TXT** com normalização de livros (acentos/apelidos).
- Importação de Bíblia em **JSON** (4 formatos, suporte a BOM UTF-8).
- Janela Bíblia com os mesmos recursos de projeção da janela Hinos (painel 🎬, atalhos de teclado, 🎨 Projeção).
- **Sincronização da projeção** entre a janela Bíblia (monitor 1) e o telão (monitor 2), com destaque do versículo atual.
- Filtro de busca de hinos: numérico = número do hino no título; texto = fragmento.
- **Placeholder** real no campo de busca de hinos.
- **Exclusão física** de hinos (remove o ID do banco).
- Versão padrão da Bíblia = **Almeida Revista e Corrigida**; remoção da versão `nvi` não utilizada.
- **Seletor de arquivos do usuário** para Importar Bíblia e Importar Hinos: abre no home, esconde pastas/arquivos ocultos (`.*`) e filtra extensões.