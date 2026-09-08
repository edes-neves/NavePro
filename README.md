# NavePro — Sistema de Projeção para Igreja

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
| **🔄 Atualização automática** | Verifica versões novas no GitHub (Releases) e baixa o novo AppImage para `~/Downloads` com instruções de instalação. |

---

## Atualizações (GitHub Releases)

O NavePro consulta o repositório **`edes-neves/NavePro`** no GitHub:

1. Ao iniciar, ~20s depois (e também pelo menu **Ajuda ▸ Verificar atualizações…**), o app consulta `https://api.github.com/repos/edes-neves/NavePro/releases/latest` em segundo plano (sem travar a interface).
2. Se a versão do release for **maior** que a instalada, mostra o aviso com as novidades e pergunta se deseja baixar.
3. Ao confirmar, baixa o `.AppImage` do release para **`~/Downloads`** com barra de progresso.
4. Ao terminar, mostra as instruções de instalação e abre a pasta Downloads:

   ```
   1. Feche o NavePro.
   2. Substitua o AppImage atual pelo baixado (mova-o para o mesmo lugar do antigo).
   3. Dê permissão de execução se precisar: chmod +x "<novo arquivo>"
   4. Abra o novo arquivo para rodar a versão atualizada.
   ```

> A opção **Verificar atualizações…** (menu Ajuda) mostra uma mensagem mesmo quando já está atualizado ou quando o GitHub está inacessível.

### Como publicar uma versão nova

1. Gere o AppImage novo (seção abaixo) e teste.
2. Faça commit das mudanças e crie um **tag** na versão (ex.: `1.9.0`).
3. Crie o release no GitHub anexando o AppImage (nome `NavePro-1.9.0.AppImage`). Exemplo com a CLI `gh`:

   ```bash
   gh release create v1.9.0 NavePro.AppImage --title "NavePro 1.9.0" --notes "O que mudou nesta versão..."
   ```

O app considera o `tag_name` do release mais recente como a versão a oferecer; o primeiro asset `*.AppImage` é o que será baixado.

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

**Requisitos (desenvolvimento):** Python 3 + Tkinter com **Tk 8.6** (o que
resolve os aliases de fonte do fontconfig: "Arial" → Liberation Sans).
O **Tk 9.0** (ex.: python do conda) **não** resolve esses aliases e deixa
fontes minúsculas/botões "quadradinhos" — evite. Para o logo aparecer,
instale o **Pillow (PIL)** no python usado para rodar/empacotar
(`pip install Pillow`). O AppImage usa as fontes instaladas no sistema de
destino; em qualquer Linux desktop (que tenha fontes liberation/dejavu/noto)
o "Arial" resolve para uma sans-serif equivalente.

```bash
python -m pip install -r requirements.txt
python NavePro.py
```

> O AppImage (seção abaixo) embute o mesmo Tk 8.6, então fica idêntico ao
> `python NavePro.py`.

### Gerar AppImage
O AppImage é **autocontido** (PyInstaller embute Python + **Tk 8.6**), então
não precisa de python3/tkinter na máquina de destino e as fontes ficam
idênticas em qualquer lugar. Use `build.sh` (reproduz o passo a passo do
`Gerar.AppImage`) com um python de Tk 8.6:

```bash
./build.sh          # usa o python com Tk 8.6; PYTHON_BIN=/usr/sbin/python ./build.sh
```

Ou, manualmente:
```bash
/usr/sbin/python -m PyInstaller --noconfirm --clean --onefile \
    --name NavePro --hidden-import "PIL._tkinter_finder" \
    --add-data "Icon.xbm:." --add-data "Icon.png:." NavePro.py   # gera dist/NavePro
cp dist/NavePro AppDir/usr/bin/NavePro && chmod +x AppDir/usr/bin/NavePro
ARCH=x86_64 appimagetool AppDir NavePro.AppImage
./NavePro.AppImage
```

> **Por que PyInstaller?** O AppRun antigo usava o `python3` do sistema
> (Tk 8.6), que é o que funciona bem. A troca errada anterior para o **Tk 9.0**
> (conda) quebrava as fontes: o Tk 9.0 não resolve "Arial" → Liberation Sans
> e caía para a fonte bitmap `fixed` (minúscula + quadradinhos). O binário
> PyInstaller garante o **Tk 8.6** dentro do AppImage.
> **Edite sempre `NavePro.py` na raiz** e repita o build;
> `AppDir/usr/bin/NavePro.py` não é mais usado (virou o binário).

---

## Estrutura do projeto

```
NavePro.py            # Aplicativo principal (interface + projeção + importadores)
README.md             # Este documento
LICENSE               # GPLv3
requirements.txt      # Dependências (runtime + pyinstaller)
build.sh              # Gera o AppImage (PyInstaller + appimagetool)
Gerar.AppImage        # Passo a passo (resumo) para empacotar o AppImage
AS21.xml              # Bíblia Almeida Século 21 (XML Zefania)
biblia-em-txt.txt     # Bíblia Almeida Revista e Corrigida (TXT)
NHA/                  # Hinário (OpenLyrics XML) — Novo Hinário Adventista
HASD/                 # Hinário (OpenLyrics XML)
AppDir/               # Estrutura do AppImage (AppRun, .desktop, ícones)
img/, Icon*.ico/png/xbm  # Ícones do app
.gitignore            # Arquivos locais/artefatos de build ignorados
```

---

## Ajustes comuns

- **Tamanho das janelas**: `janela.geometry("LARGURAxALTURA")` em `janela_hinos` (Hinos) e `janela_biblia` (Bíblia).
- **Configuração local** (`~/.navepro/config.json`, ignorado do git): cidade/estado, monitor do telão e player.

---

## Histórico recente

- **Atualização automática** via GitHub Releases com download para `~/Downloads` e instruções de instalação.
- Importação de Bíblia em **XML/TXT** com normalização de livros (acentos/apelidos).
- Importação de Bíblia em **JSON** (4 formatos, suporte a BOM UTF-8).
- Janela Bíblia com os mesmos recursos de projeção da janela Hinos (painel 🎬, atalhos de teclado, 🎨 Projeção).
- **Sincronização da projeção** entre a janela Bíblia (monitor 1) e o telão (monitor 2), com destaque do versículo atual.
- Filtro de busca de hinos: numérico = número do hino no título; texto = fragmento.
- **Placeholder** real no campo de busca de hinos.
- **Exclusão física** de hinos (remove o ID do banco).
- Versão padrão da Bíblia = **Almeida Revista e Corrigida**; remoção da versão `nvi` não utilizada.
- **Seletor de arquivos do usuário** para Importar Bíblia e Importar Hinos: abre no home, esconde pastas/arquivos ocultos (`.*`) e filtra extensões.