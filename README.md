# NavePro — Sistema de Projeção Profissional

Aplicativo desktop (Python/Tkinter) para **projeção multimídia em dois monitores**: o monitor principal (1) controla tudo e o segundo monitor (2) exibe o **telão** (letras de hinos, Bíblia, mídias) em tela cheia para a congregação.

Desenvolvido para **Windows** (Python 3 + Tkinter), distribuído como um
`NavePro.exe` portátil (PyInstaller).

---

## Funcionalidades

| Área | Descrição |
|---|---|
| **Projeção** | Exibe letras, versículos e mídias no monitor 2 (telão), com configuração de fonte, cor e tamanho. |
| **📖 Hinos / Letras** | CRUD de hinos (artista, CCLI, categoria, letra completa), importação XML/TXT, busca, projeção com navegação por slides. |
| **📢 Anúncios** | CRUD na tabela `anuncios` do SQLite (com migração automática do `anuncios.json` legado), importação de **TXT/PDF/vídeo/áudio/imagem** (mídias copiadas para `~/.navepro/uploads`) e projeção com **editor de imagem + texto**. |
| **✝️ Bíblia** | Importação de bíblias em XML/TXT/JSON, seleção de versão/livro/capítulo/versículo com **carga automática**, busca por texto e projeção sincronizada com o telão (um versículo por slide, com opção de faixa). |
| **📋 Ordem de Serviço** | Montagem de roteiros de culto com itens (hinos, mídias), com letras em snapshot e tempo estimado; salva em `~/.navepro/servicos.json` (migração automática do banco legado). |
| **🔄 Transferir** | Exporta/importa anúncios e ordens de serviço num arquivo `.navepro` para levar a outro computador. |
| **🎨 Tema claro/escuro** | Painel do administrador (monitor 1) alterna entre tema claro e escuro — menu **Visualizar** ou atalho **Ctrl+T**; o telão não é afetado. |
| **📦 Gerenciar Banco de Mídia** | Organização das mídias utilizadas nas apresentações. |
| **🎨 Projeção (config)** | Mesmo diálogo de ajustes de aparência usado por Hinos e Bíblia. |
| **🔄 Atualização automática** | Verifica versões novas no GitHub (Releases) e baixa o novo `NavePro.exe` para `~/Downloads` com instruções de instalação. |

---

## Atualizações (GitHub Releases)

O NavePro consulta o repositório **`edes-neves/NavePro`** no GitHub:

1. Ao iniciar, ~20s depois (e também pelo menu **Ajuda ▸ Verificar atualizações…**), o app consulta `https://api.github.com/repos/edes-neves/NavePro/releases/latest` em segundo plano (sem travar a interface).
2. Se a versão do release for **maior** que a instalada, mostra o aviso com as novidades e pergunta se deseja atualizar.

O **passo 3 depende de como o NavePro foi instalado** — o app se detecta sozinho
(Flatpak > Windows > AppImage; sem sinal de instalação, vale o caminho do
AppImage):

| Instalação | O que acontece ao confirmar |
|---|---|
| **Windows** | Baixa o primeiro asset `*.exe` do release para **`~/Downloads`** com barra de progresso. |
| **AppImage** | Baixa o primeiro asset `*.AppImage` do release para **`~/Downloads`**; feche o app, troque o AppImage antigo pelo baixado e abra de novo. |
| **Flatpak** | **Não baixa arquivo**: roda `flatpak update --user` no host (via `flatpak-spawn --host`) e mostra a saída na tela. Os assets `.flatpak` do release são apenas para distribuição manual — a atualização vem do repositório remoto (ex.: Flathub) já configurado na máquina. |
| Código-fonte (python NavePro.py) | Vale como AppImage: baixa o `*.AppImage` do release para usar à vontade (o aviso diz que não substitui nada). |

Para instalar (Windows e Linux): feche o NavePro, abra/substitua pelo arquivo
baixado. Como o `.exe` é portátil, não há instalador nem registro — pode ir
para qualquer pasta (os dados do usuário ficam em `%USERPROFILE%\.navepro`).

> A opção **Verificar atualizações…** (menu Ajuda) mostra uma mensagem mesmo
> quando já está atualizado ou quando o GitHub está inacessível.

### Como publicar uma versão nova

1. Grave a versão em `navepro/config.py` (`APP_VERSION`) — é o que o app exibe
   e compara. Não pule a versão: um release `v2.2.0` com binário em `2.1.1` faz
   o app oferecer "atualizar" baixando a si mesmo.

2. Gere o **AppImage** no Linux (o `.exe` e os bundles `.flatpak` são
   construídos no GitHub Actions a partir da tag):

   ```bash
   ./build.sh 2.1.4                   # gera NavePro-2.1.4.AppImage
   ```

3. Comite, crie a tag e empurre. O push da tag `v*` dispara os workflows
   `NavePro.exe` (runner Windows) e `Flatpak` (x86_64 + aarch64), que
   **anexam os artefatos ao release** e publicam o repositório Flatpak no
   `gh-pages`:

   ```bash
   git add -A && git commit -m "NavePro 2.1.4: ..."
   git tag v2.1.4
   git push origin main v2.1.4
   ```

4. Crie o release com o AppImage (o workflow anexa o `.exe` e os `.flatpak`
   ao mesmo release; se ele já existir, use `gh release upload`):

   ```bash
   gh release create v2.1.4 NavePro-2.1.4.AppImage \
     --title "NavePro 2.1.4" --notes "O que mudou nesta versão..."
   ```

   Quem tem o Flatpak instalado se atualiza por `flatpak update` (repositório
   remoto) — os bundles do release são só para distribuição manual.

O app considera o `tag_name` do release mais recente como a versão a oferecer;
o primeiro asset `*.exe` é o baixado no Windows e o primeiro `*.AppImage`, no
Linux. Se o release não tiver o asset do formato instalado, o aviso diz isso
em vez de quebrar.

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
- **Navegação**: Livro + Cap + Versículo (campo **V:**) + botão **Ir**.
- **Carga automática**: ao trocar versão, livro ou capítulo, o texto é recarregado sozinho (500 ms após a última mudança) — não há botão "Carregar". Se o texto não mudar (ex.: a mesma referência de novo), use **Ir**.
- **Campo "V:"** — o que projetar:
  - **vazio** ou **`1`** → capítulo inteiro;
  - **`16`** → do versículo 16 **até o fim** do capítulo;
  - **`9-16`** → faixa **inclusiva** (9 a 16).

  Quando o texto não couber na janela, o campo mostra a faixa válida (`9 a 16`).
- **Busca por texto** (`Buscar versículo por texto...`): LIKE no texto da versão selecionada.
- **📺 Projetar** (controle de projeção 🎬): exibe o capítulo na janela com o versículo atual **destacado** (fundo roxo `#6e40c9`) e projeta cada versículo no telão. Se o campo "V:" define uma faixa, a projeção **começa no início da faixa** e **termina sozinha** no último versículo (o botão ⏹ passa a ser "⏹ Encerrar"). Enquanto uma faixa parcial está projetada, o painel 🎬 mostra o indicador `faixa 9-16`.
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

### 🔄 Transferir anúncios e Ordem de Serviço

O botão **🔄 Transferir** existe na janela de **Anúncios** e na de **Ordem de Serviço** e usa o mesmo seletor de arquivos do app:

- **Transferir…** grava um arquivo `.navepro` (o campo **Nome do arquivo** já vem preenchido com `NavePro-Transferencia-<data>.navepro`). Navegue até a pasta de destino, ajuste o nome e clique em **💾 Salvar**. Se já existir um arquivo com esse nome, o NavePro pergunta antes de sobrescrever; se o nome digitado for uma **pasta**, ele **entra** na pasta em vez de salvar.
- **Importar…** lê o `.navepro` (ou um `.zip`) e pergunta se quer incluir as mídias — arquivos que não existirem mais no outro PC são avisados e ignorados.
- O seletor **não mostra pastas/arquivos ocultos** (`.`) e **não pisca** ao abrir: é o mesmo diálogo do app, não o do sistema.

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

Para uso na igreja, basta o **`NavePro.exe`** (portátil, sem instalador):
baixe e execute. Os dados do usuário ficam em `%USERPROFILE%\.navepro`.

**Requisitos (desenvolvimento):** Python 3.10+ com **Tk 8.6** e as
dependências do `requirements.txt`. O Tk do Windows não é DPI-aware (o
`NavePro.py` resolve isso chamando `_tornar_dpi_aware()` antes de abrir
qualquer janela — ver `navepro/core/ambiente.py`).

```bat
python -m pip install -r requirements.txt
python NavePro.py
```

### Gerar o NavePro.exe

```bat
build-windows.bat
```

O `build-windows.bat` confere o Tk 8.6, instala as dependências e chama o
PyInstaller com o `NavePro.spec`, que é a **fonte única** do empacotamento.
O `.exe` sai sem janela de console; para ver o log de detecção de monitores
("✅ screeninfo: 2 monitor(es)..."), gere um build de diagnóstico com:

```bat
set NAVEPRO_CONSOLE=1 && build-windows.bat
```

O ícone do executável vem de `img\Icon.ico` (variável `NAVEPRO_ICON`); sem
esse arquivo o `.exe` sai sem ícone próprio, mas as janelas continuam com
ícone.

### Gerar o AppImage (Linux)

```bash
./build.sh 2.1.4          # gera NavePro-2.1.4.AppImage
```

O `build.sh` empacota com o **mesmo `NavePro.spec`** do `.exe` (os dois
sistemas embutem os mesmos recursos e `hiddenimports` — a razão do spec
existir é que o separador do `--add-data` é `:` no Linux e `;` no Windows),
depois monta o `AppDir/` e comprime com o `appimagetool` da raiz
(`APPIMAGE_TOOL` aponta para outro, se quiser). Ele usa o `.venv` do projeto
quando existe — que já tem PyInstaller e as dependências — e só exige Tk 8.6.
O passo a passo detalhado está no `Gerar.AppImage`.

> Os releases precisam carregar o `.exe` **e** o `.AppImage` — é de cada um
> que o app baixa a atualização no Windows e no Linux. No Flatpak a
> atualização não usa os assets: é `flatpak update` via repositório remoto.

### Player de mídia no Windows (mpv)

No Windows o NavePro abre o vídeo em um player externo. O **mpv** é
responsável pelo **pausar/continuar** pelo painel, porque é o único que
aceita comando remoto (IPC JSON). Ele **não** vem embutido no `NavePro.exe`
(seriam +56 MB) e precisa ser instalado **uma vez por máquina**:

```bat
winget install mpv-player.mpv-CI.MSVC
```

Sem o mpv, o NavePro continua funcionando: ele detecta e usa o **VLC** ou o
**SMPlayer** se estiverem instalados, o vídeo abre no telão e o botão
**parar** funciona. Só o **pausar/continuar** fica indisponível — e o NavePro
avisa isso na tela, com o comando de instalação, em vez de falhar calado.

#### Como o player é colocado no monitor do telão

Cada player recebe o tratamento que funciona nele, medido nesta máquina:

| Player | Como entra no telão |
|---|---|
| **VLC** | `--fullscreen` + `--qt-fullscreen-screennumber=<n>`, ou seja, o próprio VLC se posiciona. O NavePro só esconde o painel de controle que ele abre na tela principal. |
| **mpv**, **SMPlayer** | Abertos **sem** `--fullscreen`, e a janela é colocada sobre o telão por Win32 (`posicionar_janela_player` em `navepro/core/player.py`), sem moldura e em cima das outras janelas. |

**Por que o VLC não pode ser reposicionado por código:** redimensionar a janela
de vídeo do VLC 3.0.24 (módulo de saída `direct3d11`) faz o vout renegociar o
tamanho a cada chamada, e a janela cresce sem parar. Medido aqui, indo de
1920x1080 para 5328x9368, depois 10240x21341 e 12864x27737. Com a janela
nesse estado o monitor do telão fica com uma cor só (sem imagem) e o
redimensionamento contínuo trava a máquina. Deixando o VLC se posicionar
sozinho, o vídeo entra no monitor certo e fica estável.

**Por que o mpv e o SMPlayer não podem usar `--fullscreen`:** medido aqui, o
mpv 0.41 ignora `--screen` e `--geometry` em tela cheia e sempre abre no
monitor primário. O mesmo vale para o relógio do telão, em
`TelaoWindow._aplicar_tela_cheia`.

## Testes

As suítes ficam em `tests/` e rodam **sem tela e sem servidor** — quando precisam
de interface, recriam um `Tk` falso e extraem do `NavePro.py` só o trecho que
está sendo testado (via `ast`).

```bat
set PYTHONUTF8=1
python tests\test_logica.py          :: uma suíte
for %f in (tests\test_*.py) do @python %f || echo FALHOU: %f   :: todas
```

> O `PYTHONUTF8=1` importa num console antigo (cmd com cp1252): sem ele, o
> print dos emojis da suíte (✅, ◀, 📁) estoura `UnicodeEncodeError` no
> Windows. No GitHub Actions o workflow já força o modo UTF-8.

No GitHub Actions (`.github/workflows/testes.yml`) a suíte roda nos **dois**
sistemas a cada push e pull request — `ubuntu-latest` e `windows-latest` —,
justo para que uma mudança feita de um lado não quebre o outro sem ninguém
perceber. As suítes de bíblia/projeção apontam para `tests/fixture_biblia.py`,
que monta um banco temporário com o schema real (`init_db` extraído do
`NavePro.py`) — em máquina limpa nem existe o `~/.navepro` do usuário.

| Suíte | O que cobre |
|---|---|
| `test_logica.py` | Regras de texto, versículos, mídia e banco |
| `test_gui.py` | Widgets e callbacks da interface (Tk falso) |
| `test_gui_reload.py` | Carga automática da Bíblia: debounce de 500 ms, timer cancelado ao fechar a janela, recarga ignorada com a janela morta |
| `test_projecao.py` | Projeção de versículo e de hino no telão |
| `test_projecao_faixa.py` | Faixa de versículos (`9-16`): começa no 9, encerra no 16, rótulo `faixa 9-16`, e as entradas inválidas (`abc`, `9-3`, `1-`, `0`, faixa inexistente) |
| `test_indicador.py` | Indicador de progresso |
| `test_seletor.py` | Seletor de arquivos do app (filtros e pastas ocultas) |
| `test_imagens.py` | Imagens de fundo e transferência entre janelas |
| `test_monitores.py` | Escolha do monitor do painel e do telão: nunca os dois no mesmo monitor, mesmo sem primário detectado |
| `test_player_windows.py` | Player no Windows: descoberta de executáveis, pipe do mpv por faixa, flags do comando (mpv sem `--fullscreen`; VLC com `--fullscreen --qt-fullscreen-screennumber`), quem posiciona a janela, fim de faixa sem "ended" falso, aviso de pausa sem `UnboundLocalError` |
| `test_atualizacao.py` | Detecção de instalação e escolha do asset do release |

Duas suítes de verificação ligam o código a esta máquina e servem quando um
problema só aparece na tela (o resto roda sem monitor e sem vídeo):

```bat
python tests\validar_vlc_telao.py   :: toca o MP4 no telão e confere por captura de tela
python tests\validar_aviso.py        :: roda o aviso de pausa com Tk real e caça exceção
```

> Um detalhe que já custou tempo: o `after()` do Tk devolve o id do timer como
> **`str`**. Num Tk falso, guardar o timer sob chave `int` faz o `after_cancel`
> silenciosamente não encontrar nada — o debounce parece quebrado quando não está.

> Outro: toda leitura de arquivo de teste precisa de `encoding="utf-8"`. Sem
> isso o `open()` usa o `cp1252` do Windows e estoura `UnicodeDecodeError` em
> qualquer acento — a suíte passa no Linux e quebra no Windows.

---

## Estrutura do projeto

```
NavePro.py            # Aplicativo principal (interface + projeção + importadores)
navepro/              # Infraestrutura reutilizável (config, caminhos, temas, textos, atualização)
  config.py           # APP_VERSION e constantes de configuração
  core/player.py      # Player de mídia no Windows: acha o executável, IPC do mpv, posiciona a janela
NavePro.spec          # Configuração do PyInstaller (fonte única do empacotamento)
build-windows.bat     # Gera o dist\NavePro.exe
build.sh              # Gera o AppImage do Linux (usa o mesmo NavePro.spec)
Gerar.AppImage        # Passo a passo do empacotamento para o AppImage
README.md             # Este documento
LICENSE               # GPLv3
requirements.txt      # Dependências (runtime + pyinstaller)
Biblias/               # Bíblias para importar (XML do Zefania e TXT): AS21, ARC, ACF, ARA…
  AS21.xml            #   Bíblia Almeida Século 21 (XML Zefania)
  biblia-em-txt.txt   #   Bíblia Almeida Revista e Corrigida (TXT)
NHA/                  # Hinário (OpenLyrics XML) — Novo Hinário Adventista
HASD/                 # Hinário (OpenLyrics XML)
tests/                # Suítes de teste headless (ver "Testes")
img/                    # Ícones do app (Icon.png, Icon.xbm, Icon.ico…)
.gitignore            # Arquivos locais/artefatos de build ignorados
```

---

## Dados locais (`~/.navepro/`)

No Windows esta pasta é `%USERPROFILE%\.navepro`.

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

### 2.1.4

- **Janela de adicionar/editar item da Ordem de Serviço não abre mais no canto
  superior esquerdo**: ela passa a se **centralizar sobre a janela da Ordem de
  Serviço** e a **manter a posição** ao clicar nos campos ou arrastar (o defeito
  aparecia no AppImage, no `.exe` e no Flatpak).
- **Anúncios com texto + imagem deixam de sair minúsculos** e o **A−/A+ volta a
  funcionar** em distros que não têm DejaVu/Liberation (ex.: **BigLinux/GNOME**):
  o app procura qualquer TTF/OTF instalado no sistema e usa o tamanho real no
  Pillow, em vez de cair na fonte padrão fixa (~10 px).

### 2.1.1

- **Atualização corrigida para quem instalou como Flatpak**: o NavePro detecta que está dentro do Flatpak e roda `flatpak update --user` no sistema, em vez de baixar um `.AppImage` que não funcionaria. Era o defeito mais relatado — o app oferecia "baixar novo AppImage" para quem já tinha o Flatpak instalado.
- **Janela de atualização do Flatpak** mostra a saída do comando em tempo real (com o comando exato no alto), avisa para reiniciar o app ao final e, se falhar, mostra o comando para rodar no terminal em vez de sumir com o erro.
- **Textos por tipo de instalação**: a pergunta, o rótulo do arquivo e as instruções de instalação dizem a coisa certa para Flatpak, AppImage, Windows ou execução a partir do código-fonte (nesse caso avisa que o AppImage baixado é só uma cópia).
- **Bíblias extras no Flatpak**: o manifesto passa a copiar `AS21.xml` e `biblia-em-txt.txt` da pasta `Biblias/`, alinhado com o repositório.
- **Suítes de testes no repositório** (pasta `tests/`, antes só existiam na máquina de desenvolvimento): 9 suítes headless, documentação de como rodar e o que cada uma cobre.

### 2.1.0

- **Bíblia carrega sozinha**: trocar versão, livro ou capítulo recarrega o texto em 500 ms (o botão **📖 Carregar** saiu da janela).
- **Faixa de versículos** no campo **V:** — `9-16` projeta só a faixa (inclusiva) e um número (`16`) projeta desse versículo até o fim; vazio/`1` continua sendo o capítulo inteiro.
- **Projeção acompanha a faixa**: começa no primeiro versículo da faixa, **encerra sozinha** no último (o ⏹ vira "⏹ Encerrar") e o painel 🎬 mostra o indicador `faixa 9-16`.
- **Janela do operador sempre no monitor 1** do sistema (antes podia abrir no telão).
- **Seletor de arquivos do app em todo lugar**: salvar transferência, importar transferência e escolher imagem de fundo não usam mais o diálogo do sistema — sem pastas ocultas (`.`) e sem piscar ao abrir.

### 2.0.0 e anteriores

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
- **Seletor de arquivos do usuário** para Importar Bíblia e Importar Hinos: abre no home, esconde pastas/arquivos ocultos (`.*`) e filtra extensões. (Desde 2.1.0 é usado também para salvar transferência e escolher imagem de fundo.)