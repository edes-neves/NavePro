# NavePro — Sistema de Projeção para Igreja

Aplicativo desktop (Python/Tkinter) para **projeção multimídia em dois monitores**: o monitor principal (1) controla tudo e o segundo monitor (2) exibe o **telão** (letras de hinos, Bíblia, mídias) em tela cheia para a congregação.

Desenvolvido para Ubuntu (Python 3 + Tkinter), empacotado como AppImage.

---

## Funcionalidades

| Área | Descrição |
|---|---|
| **Projeção** | Exibe letras, versículos e mídias no monitor 2 (telão), com configuração de fonte, cor e tamanho. |
| **📖 Hinos / Letras** | CRUD de hinos (artista, CCLI, categoria, letra completa), importação XML/TXT, busca, projeção com navegação por slides. |
| **📢 Anúncios** | CRUD na tabela `anuncios` do SQLite (com migração automática do `anuncios.json` legado), importação de **TXT/PDF/vídeo/áudio/imagem** (mídias copiadas para `~/.navepro/uploads`) e projeção com **editor de imagem + texto**. |
| **✝️ Bíblia** | Importação de bíblias em XML/TXT/JSON, seleção de versão/livro/capítulo/versículo, busca por texto e projeção sincronizada com o telão. |
| **📋 Ordem de Serviço** | Montagem de roteiros de culto com itens (hinos, mídias), com letras em snapshot e tempo estimado; salva em `~/.navepro/servicos.json` (migração automática do banco legado). |
| **🎨 Tema claro/escuro** | Painel do administrador (monitor 1) alterna entre tema claro e escuro — menu **Visualizar** ou atalho **Ctrl+T**; o telão não é afetado. |
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

1. Gere o AppImage novo **passando a versão** — o `build.sh` atualiza o `APP_VERSION` no `NavePro.py` e nomeia o arquivo com a versão:

   ```bash
   ./build.sh 1.9.1                 # gera NavePro-1.9.1.AppImage com versão 1.9.1 gravada
   ./NavePro-1.9.1.AppImage         # teste
   ```

   > ⚠️ **Não pule a versão**: se criar um release `v1.9.1` com um AppImage ainda em `1.9.0`, o binário se achará desatualizado e oferecerá "atualizar" baixando a si mesmo. O `./build.sh <versão>` previne isso (grava e confere o `APP_VERSION`).

2. Faça commit das mudanças e crie um **tag** na versão (ex.: `v1.9.0`).
3. Crie o release no GitHub anexando o AppImage. Exemplo com a CLI `gh`:

   ```bash
   gh release create v1.9.1 NavePro-1.9.1-AMD.AppImage --title "NavePro 1.9.1" --notes "O que mudou nesta versão..."
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

## Janela Anúncios

- **Banco de dados**: os anúncios ficam na tabela `anuncios` do `~/.navepro/midia.db`. O `anuncios.json` legado é importado **uma única vez** (migração automática); os IDs são reaproveitados quando o anúncio é excluído.
- **Tipos de anúncio**: `slide` (texto), `imagem` (pode ter texto por cima), `vídeo`/`áudio` (tocam no player).
- **📥 Importar Mídia**: TXT/PDF viram anúncios de texto; vídeo/áudio/imagem são copiados para `~/.navepro/uploads` e registrados no banco.
- **📺 Projetar**:
  - Anúncio de texto → slides **respeitando a digitação do operador** (slide 0 = título), navegação ◀/▶.
  - Anúncio com imagem **e** texto → compõe a imagem sobre o texto e projeta como uma única imagem.
  - Anúncio só com imagem → projeta a imagem pura.
  - Anúncio de vídeo/áudio → toca no player (com opção de repetir).
- No painel **🎬 Controle da Projeção**: **A−/A+** ajusta a fonte do texto e **🖼️ Imagem: −/+** redimensiona a imagem ao vivo, sem parar a projeção.

### Editor de anúncio (imagem + texto)

- **Novo Anúncio / Editar Anúncio** abre um editor com **pré-visualização unificada**: o texto digitado é desenhado na base e a imagem é ajustada por cima, no mesmo canvas, com **arrastar para mover** e **alças para redimensionar**.
- O espaço de edição usa um plano virtual de **1440×1080**, independente da resolução do telão; ao salvar, a posição/tamanho da imagem (`w/h/x/y`) fica em `config_midia`.
- Configurações antigas (formato 320×250, sem posição) são **migradas automaticamente**: a imagem é redimensionada e reposicionada à direita, centralizada verticalmente.
- A projeção compõe a imagem + texto na proporção do telão, mantendo exatamente a posição ajustada no editor.

---

## Banco de dados

Localização: **`~/.navepro/midia.db`** (SQLite).

Tabelas principais:

| Tabela | Uso |
|---|---|
| `letras` | Hinos: `id`, `titulo`, `artista`, `compositor`, `ccli_numero`, `categoria`, `idioma`, `letra_completa`, `ativo` |
| `versiculos` | Bíblia: `id`, `versao`, `livro`, `capitulo`, `versiculo`, `texto` |
| `anuncios` | Anúncios: `id`, `titulo`, `categoria`, `texto`, `tipo_midia`, `arquivo_midia`, `nome_arquivo_midia`, `config_midia`, `ativo` |
| `midia` | Mídias do acervo (com FTS em `midia_fts` para busca) |

Notas:
- A exclusão de hinos é **física**; não há chave estrangeira para `letras.id`. Por isso os IDs de `letras`/`versiculos` são **reaproveitados** (preenchimento das lacunas) — exceto os IDs ainda referenciados por itens de ordem de serviço, que ficam preservados; a Ordem de Serviço guarda também a cópia da letra (snapshot).
- A **Ordem de Serviço** migrou do banco para **`~/.navepro/servicos.json`** (migração automática na primeira execução). As tabelas legadas `servicos`/`itens_servico` só existem para migração.
- O `anuncios.json` legado de anúncios é migrado **uma vez** para a tabela `anuncios` e deixa de ser usado.
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
./build.sh 1.9.1       # usa o python com Tk 8.6; PYTHON_BIN=.venv/bin/python ./build.sh
```

Ou, manualmente:
```bash
/usr/sbin/python -m PyInstaller --noconfirm --clean --onefile \
    --name NavePro --hidden-import "PIL._tkinter_finder" \
    --add-data "Icon.xbm:." --add-data "Icon.png:." NavePro.py   # gera dist/NavePro
cp dist/NavePro AppDir/usr/bin/NavePro && chmod +x AppDir/usr/bin/NavePro
ARCH=x86_64 appimagetool AppDir NavePro-1.9.1-AMD.AppImage
./NavePro-1.9.1-AMD.AppImage
```

> **Por que PyInstaller?** O AppRun antigo usava o `python3` do sistema
> (Tk 8.6), que é o que funciona bem. A troca errada anterior para o **Tk 9.0**
> (conda) quebrava as fontes: o Tk 9.0 não resolve "Arial" → Liberation Sans
> e caía para a fonte bitmap `fixed` (minúscula + quadradinhos). O binário
> PyInstaller garante o **Tk 8.6** dentro do AppImage.
> **Edite sempre `NavePro.py` na raiz** e repita o build;
> `AppDir/usr/bin/NavePro.py` não é mais usado (virou o binário).

### Gerar Flatpak

O Flatpak empacotado **não precisa do PyInstaller/imagetool** — o `python3` da
runtime do Flatpak roda o `NavePro.py` direto. O módulo `_tkinter` (ausente
na runtime) é compilado a partir do [tkinter-standalone](https://github.com/iwalton3/tkinter-standalone)
com **Tcl/Tk 8.6.15** (mantém as mesmas fontes do AppImage).

**Build local** (requer `flatpak-builder`):
```bash
sudo apt install flatpak-builder
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install flathub org.freedesktop.Platform//24.08 org.freedesktop.Sdk//24.08

./build-flatpak.sh              # gera io.github.edesneves.NavePro.<arch>.flatpak
./build-flatpak.sh --install    # instala no usuário atual
```

**Build multi-arquitetura (GitHub Actions):**
A workflow `.github/workflows/flatpak.yml` gera bundles para `x86_64` e
`aarch64` em cada release (`git push origin v<versão>`). O `flatpak-builder`
usa QEMU para cross-compile em aarch64.

**Publicar no Flathub:**
O manifesto `flatpak/io.github.edesneves.NavePro.yaml` está pronto para
submissão. O Flathub compila automaticamente para **x86_64**, **aarch64** e
**riscv64** — sem infraestrutura extra. Para submeter, crie um pull request
em [flathub/flathub](https://github.com/flathub/flathub) apontando para este
repositório.

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
flatpak/              # Manifesto Flatpak + .desktop + metainfo + wrapper + repositório
.github/workflows/    # CI/CD: build Flatpak multi-arquitetura (x86_64 + aarch64)
img/, Icon*.ico/png/xbm  # Ícones do app
.gitignore            # Arquivos locais/artefatos de build ignorados
```

---

## Dados locais (`~/.navepro/`)

| Arquivo/pasta | Conteúdo |
|---|---|
| `midia.db` | Banco SQLite: hinos, versículos, anúncios e mídias |
| `servicos.json` | Ordens de Serviço (após migração) |
| `anuncios.json` | Legado — migrado uma vez para `midia.db` e não é mais lido |
| `uploads/` | Cópias das mídias importadas nos anúncios |
| `config.json` | Configuração local (cidade/estado, monitor do telão, player) — ignorado do git |

## Ajustes comuns

- **Tamanho das janelas**: `janela.geometry("LARGURAxALTURA")` em `janela_hinos` (Hinos) e `janela_biblia` (Bíblia).
- **Configuração local** (`~/.navepro/config.json`, ignorado do git): cidade/estado, monitor do telão e player.

---

## Histórico recente

- **Anúncios no banco de dados**: tabela `anuncios` no SQLite, com migração automática do `anuncios.json` legado e reaproveitamento de IDs livres.
- **Ordem de Serviço em `servicos.json`**: migração automática do banco legado; IDs de hinos/versículos referenciados ficam preservados da reutilização.
- **Editor de anúncio unificado (imagem + texto)**: pré-visualização em espaço virtual 1440×1080, mover/redimensionar a imagem sobre o texto, migração de configurações antigas.
- **Redimensionamento ao vivo da imagem no telão**: botões **🖼️ Imagem: −/+** no painel da projeção, além do **A−/A+** da fonte — sem interromper o que está projetado.
- **Tema claro/escuro** no painel do administrador (menu Visualizar ou **Ctrl+T**), sem alterar as cores do telão.
- **Modo Repetir** para mídias do player (menu Visualizar).
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