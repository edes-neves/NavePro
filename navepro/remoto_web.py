"""Página do controle remoto do NavePro (celular na mesma rede).

Servida pelo ServidorAsyncHTTP na rota `/` quando o controle remoto está
ativo, sempre protegida pelo token (`?t=` na URL). São constantes de string
neste módulo (o CSS e o JS ficam em `_REMOTO_CSS`/`_REMOTO_JS`, costurados em
`PAGINA`) — nada de arquivo estático no bundle, então o PyInstaller, o
AppImage e o Flatpak continuam funcionando sem mudanças.

A API usada (tudo com o header `X-Token`):
  GET  /api/remoto/estado      → estado do telão/medidor/mídia
  GET  /api/remoto/hinos       → lista de hinos (busca opcional)
  GET  /api/remoto/midias      → busca músicas/vídeos na tabela `midia`
  GET  /api/remoto/biblia      → busca de versículos (texto) + versões
  GET  /api/remoto/biblia_ref  → versículos por livro/cap/V: (como no app)
  GET  /api/remoto/biblia_opcoes → opções dos combos Cap:/V: (capítulos e
                                   versículos do livro/capítulo escolhidos)
  GET  /api/remoto/livros      → lista dos livros da Bíblia
  GET  /api/remoto/anuncios    → lista de anúncios
  GET  /api/remoto/servicos    → lista de serviços
  GET  /api/remoto/servico_itens → itens de um serviço (?servico=<id|nome>)
  POST /api/remoto/slide       → {acao: prox|ant|parar}
  POST /api/remoto/hino        → {id}
  POST /api/remoto/biblia      → {q, versao} ou {versao, livro, cap, vers}
  POST /api/remoto/midia       → {id}   (executa áudio/vídeo no telão)
  POST /api/remoto/player      → {acao: play_pause|parar} (pausa/continua/para)
  POST /api/remoto/anuncio     → {id}
  POST /api/remoto/servico     → {id, item?}
  POST /api/remoto/servico_item→ {operacao: add|editar|apagar|mover, servico, ...}
  POST /api/remoto/medidor     → {qual, acao, seg?, titulo?}
  POST /api/remoto/tamanho     → {qual, acao}
  GET  /api/remoto/relogio     → configuração e estado do relógio
  POST /api/remoto/relogio     → {acao: configurar|projetar|
                                   alternar_relogio|alternar_temperatura}
  POST /api/remoto/projecao    → abre no computador a janela Aparência da
                                   Projeção (com as opções da Bíblia)
  GET  /api/remoto/sorteio     → estado e configuração do Sorteio
  POST /api/remoto/sorteio/abrir      → abre o Sorteio
  POST /api/remoto/sorteio/fechar     → fecha o Sorteio
  POST /api/remoto/sorteio/configurar → {modo, inicio, fim, nomes, por_vez}
  POST /api/remoto/sorteio/sortear    → próximo sorteio
  POST /api/remoto/sorteio/reiniciar  → limpa os sorteados"""

_REMOTO_CSS = """
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body {
    margin: 0; background: #0d1117; color: #c9d1d9;
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
    font-size: 16px; padding-bottom: 90px;
  }
  header {
    background: #161b22; border-bottom: 1px solid #30363d;
    padding: 10px 14px; display: flex; align-items: center;
    justify-content: space-between; position: sticky; top: 0; z-index: 5;
  }
  header b { color: #f0c040; font-size: 17px; }
  #status { font-size: 12px; color: #8b949e; text-align: right; }
  nav {
    display: flex; overflow-x: auto; background: #161b22;
    border-bottom: 1px solid #30363d; position: sticky; top: 45px; z-index: 5;
  }
  nav button {
    flex: 1 0 auto; background: none; border: 0; color: #8b949e;
    padding: 11px 12px; font-size: 14px; font-weight: 600;
    border-bottom: 3px solid transparent; white-space: nowrap;
  }
  nav button.on { color: #f0c040; border-bottom-color: #f0c040; }
  section { display: none; padding: 14px; }
  section.on { display: block; }
  .card {
    background: #161b22; border: 1px solid #30363d; border-radius: 10px;
    padding: 12px; margin-bottom: 12px;
  }
  .card h3 { margin: 0 0 8px; font-size: 13px; color: #8b949e;
             text-transform: uppercase; letter-spacing: .05em; }
  .previa {
    min-height: 74px; background: #010409; border-radius: 8px; padding: 10px;
    color: #58a6ff; font-size: 15px; display: flex; align-items: center;
    justify-content: center; text-align: center; word-break: break-word;
  }
  .linha { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .btn {
    border: 0; border-radius: 8px; padding: 13px 0; font-size: 16px;
    font-weight: 700; cursor: pointer; color: #fff; background: #1f6feb;
    flex: 1; min-width: 56px;
  }
  .btn:active { filter: brightness(1.25); }
  .btn.cinza { background: #21262d; color: #c9d1d9; }
  .btn.vermelho { background: #da3633; }
  .btn.verde { background: #238636; }
  .btn.mini { flex: 0 0 auto; padding: 9px 14px; font-size: 14px; }
  .btn.on { background: #6e40c9; }
  input, select, textarea {
    width: 100%; background: #0d1117; color: #c9d1d9; border: 1px solid #30363d;
    border-radius: 8px; padding: 12px; font-size: 16px; margin-bottom: 8px;
  }
  textarea { resize: vertical; min-height: 96px; font-family: inherit; }
  .linha input, .linha select {
    width: auto; flex: 1 1 auto; margin-bottom: 0;
  }
  ul { list-style: none; margin: 0; padding: 0; }
  li {
    display: flex; align-items: center; justify-content: space-between;
    gap: 10px; padding: 11px 10px; border-bottom: 1px solid #21262d;
    font-size: 15px;
  }
  li .nome { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis;
             white-space: nowrap; }
  li .sub { color: #8b949e; font-size: 12px; }
  .vazio { color: #8b949e; padding: 14px 4px; font-size: 14px; }
  .grande { font-size: 26px; font-weight: 800; color: #f0c040;
            text-align: center; font-variant-numeric: tabular-nums; }
  .pill { font-size: 12px; background: #21262d; border-radius: 20px;
          padding: 3px 10px; color: #8b949e; }
  .pill.exec { background: #238636; color: #fff; font-weight: 700; }
  .campo { display: block; font-size: 13px; color: #8b949e;
           margin: 12px 0 4px; }
  .cores { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 10px; }
  .cores button {
    width: 42px; height: 34px; border-radius: 8px; cursor: pointer;
    border: 2px solid #30363d;
  }
  .cores button.on { border-color: #f0c040; }
  .check { display: flex; align-items: center; gap: 8px;
           font-size: 14px; margin: 8px 0; }
  .check input { width: auto; margin: 0; }
  input[type=range] { padding: 0; border: 0; background: none; margin: 0 0 8px; }
  /* Aba Bíblia em grade: livros no topo, capítulos e versículos embaixo.
     No celular tudo empilha; a partir de 640px os capítulos ficam à
     esquerda e os versículos à direita (sem repetir os versículos). */
  .bib-grade { display: grid; gap: 12px; grid-template-columns: 1fr; }
  .bib-bloco { min-width: 0; }
  .bib-grade-botoes {
    display: grid; gap: 6px;
    grid-template-columns: repeat(auto-fill, minmax(44px, 1fr));
  }
  .bib-grade-botoes.livros {
    grid-template-columns: repeat(auto-fill, minmax(56px, 1fr));
  }
  .bib-botao {
    background: #21262d; color: #c9d1d9; border: 0; border-radius: 8px;
    padding: 7px 4px; font-size: 15px; font-weight: 700; cursor: pointer;
    min-height: 38px; line-height: 1.15;
  }
  .bib-botao:active { filter: brightness(1.3); }
  .bib-botao.on { background: #6e40c9; color: #fff; }
  .bib-botao .sigla { display: block; font-size: 16px; line-height: 1.1; }
  .bib-botao .nome {
    display: block; font-size: 10px; line-height: 1.1; color: #8b949e;
    margin-top: 2px; word-break: break-word;
  }
  .bib-botao.on .nome { color: #fff; }
  li.bib-versiculo {
    align-items: flex-start; justify-content: flex-start; gap: 8px;
    cursor: pointer;
  }
  li.bib-versiculo .num {
    color: #f0c040; font-weight: 800; min-width: 24px; text-align: right;
  }
  li.bib-versiculo .texto { flex: 1; font-size: 14px; line-height: 1.4; }
  li.bib-versiculo.on { background: rgba(110, 64, 201, .28); }
  @media (min-width: 640px) {
    .bib-grade {
      grid-template-columns: .8fr 1.5fr;
      grid-template-areas: "livros livros" "capitulos versiculos";
    }
    .bib-livros { grid-area: livros; }
    .bib-capitulos { grid-area: capitulos; }
    .bib-versiculos { grid-area: versiculos; }
    #lista_biblia { max-height: 60vh; overflow-y: auto; }
  }
  /* Aba Serviço: nome e ações empilhados para caber no celular. */
  li.servico-linha { flex-wrap: wrap; row-gap: 8px; }
  li.servico-linha .nome { flex: 1 1 100%; white-space: normal;
                           overflow: visible; text-overflow: clip; }
  li.servico-linha .btn { flex: 1 1 0; padding: 11px 12px; }
  li.item-servico { flex-direction: column; align-items: stretch;
                    gap: 9px; padding: 14px 6px; }
  li.item-servico .nome { flex: none; white-space: normal;
                          overflow: visible; text-overflow: clip; }
  .item-servico .item-titulo { font-size: 15px; line-height: 1.4; }
  .item-servico .item-titulo .ordem { color: #f0c040; font-weight: 800; }
  .item-servico .item-url { font-size: 12px; color: #58a6ff; line-height: 1.35;
    margin: 2px 0 0; word-break: break-all; }
  .item-servico .item-meta { display: flex; flex-wrap: wrap; gap: 6px;
                             margin-top: 7px; }
  .item-servico .item-detalhe { color: #8b949e; font-size: 13px;
                                margin-top: 6px; word-break: break-word; }
  .item-servico .item-previa { color: #c9d1d9; font-size: 13px;
                               margin-top: 7px; line-height: 1.45;
                               display: -webkit-box; -webkit-line-clamp: 3;
                               -webkit-box-orient: vertical; overflow: hidden; }
  .item-servico .item-acoes { display: grid;
                              grid-template-columns: repeat(4, 1fr);
                              gap: 6px; }
  .item-servico .item-acoes .btn { min-width: 0; }
  .item-servico .item-acoes .btn-exec { grid-column: 1 / -1;
                                        padding: 11px 12px; font-size: 15px; }
  .item-servico .item-acoes .btn.mini { width: 100%; padding: 11px 0; }
  .item-servico.em-execucao { background: #0d2818; border-radius: 8px;
                              padding-left: 10px;
                              box-shadow: inset 3px 0 0 #f0c040; }
  #toast {
    position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%);
    background: #da3633; color: #fff; padding: 11px 18px; border-radius: 8px;
    font-size: 14px; display: none; z-index: 20; max-width: 90%;
    text-align: center;
  }
  #token_tela {
    position: fixed; inset: 0; background: #0d1117; z-index: 30;
    padding: 40px 24px; display: none;
  }
"""

_REMOTO_JS = """
var TOKEN = new URLSearchParams(location.search).get('t') || localStorage.getItem('navepro_token') || '';
if (TOKEN) localStorage.setItem('navepro_token', TOKEN);

function rota(path) { return path + (path.indexOf('?') >= 0 ? '&' : '?') + 't=' + encodeURIComponent(TOKEN); }

function aviso(msg, cor) {
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = cor || '#da3633';
  t.style.display = 'block';
  clearTimeout(t._id);
  t._id = setTimeout(function() { t.style.display = 'none'; }, 2600);
}

function apiGet(path) {
  return fetch(rota(path), {headers: {'X-Token': TOKEN}}).then(function(r) {
    if (r.status === 403) { pedirToken(); throw new Error('sem token'); }
    return r.json();
  });
}

function apiPost(path, dados, silencioso) {
  return fetch(rota(path), {
    method: 'POST',
    headers: {'X-Token': TOKEN, 'Content-Type': 'application/json'},
    body: JSON.stringify(dados || {})
  }).then(function(r) {
    if (r.status === 403) { pedirToken(); throw new Error('sem token'); }
    return r.json();
  }).then(function(j) {
    if (j && j.ok === false && j.erro && !silencioso) aviso(j.erro);
    return j;
  });
}

function pedirToken() { document.getElementById('token_tela').style.display = 'block'; }

function salvarToken() {
  TOKEN = document.getElementById('token_digito').value.trim();
  localStorage.setItem('navepro_token', TOKEN);
  document.getElementById('token_tela').style.display = 'none';
  iniciar();
}

// ── Abas ──
document.getElementById('abas').addEventListener('click', function(e) {
  var b = e.target.closest('button');
  if (!b) return;
  [].forEach.call(document.querySelectorAll('nav button'), function(x) { x.classList.remove('on'); });
  [].forEach.call(document.querySelectorAll('section'), function(x) { x.classList.remove('on'); });
  b.classList.add('on');
  document.getElementById('aba-' + b.dataset.aba).classList.add('on');
  if (b.dataset.aba === 'sorteio') carregarConfigSorteio();
  if (b.dataset.aba === 'relogio') carregarRelogio();
});

// ── Slides ──
function slide(acao) { apiPost('/api/remoto/slide', {acao: acao}).then(atualizarEstado); }

// Tamanho do conteúdo projetado (texto e imagem), ao vivo — mesmos
// ajustes dos botões A−/A+ e 🖼️−/+ do painel do operador.
function tamanho(qual, acao) {
  apiPost('/api/remoto/tamanho', {qual: qual, acao: acao})
    .then(function() { atualizarEstado(); });
}

// ── Hinos ──
function buscarHino() {
  var q = document.getElementById('hino_busca').value.trim();
  apiGet('/api/remoto/hinos?busca=' + encodeURIComponent(q)).then(function(j) {
    var ul = document.getElementById('lista_hinos');
    ul.innerHTML = '';
    if (!j.hinos || !j.hinos.length) {
      ul.innerHTML = '<li class="vazio">Nenhum hino encontrado.</li>';
      return;
    }
    j.hinos.forEach(function(h) {
      var li = document.createElement('li');
      var nome = document.createElement('div');
      nome.className = 'nome';
      nome.innerHTML = '<b>' + h.numero + '. ' + esc(h.titulo) + '</b>' +
        (h.artista ? '<div class="sub">' + esc(h.artista) + '</div>' : '');
      var btn = document.createElement('button');
      btn.className = 'btn mini verde';
      btn.textContent = 'Proj';
      btn.onclick = function() {
        apiPost('/api/remoto/hino', {id: h.id}).then(function(j) {
          if (j.ok) aviso('Hino projetado: ' + h.titulo, '#238636');
          atualizarEstado();
        });
      };
      li.appendChild(nome); li.appendChild(btn);
      ul.appendChild(li);
    });
  });
}
document.getElementById('hino_busca').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') buscarHino();
});

// ── Músicas/vídeos (busca no BD, como o campo principal do app) ──
function buscarMidia() {
  var q = document.getElementById('midia_busca').value.trim();
  if (!q) { aviso('Digite um número ou nome'); return; }
  apiGet('/api/remoto/midias?busca=' + encodeURIComponent(q)).then(function(j) {
    var ul = document.getElementById('lista_midias');
    ul.innerHTML = '';
    if (!j.midias || !j.midias.length) {
      ul.innerHTML = '<li class="vazio">Nenhuma m&iacute;dia encontrada.</li>';
      return;
    }
    j.midias.forEach(function(m) {
      var li = document.createElement('li');
      var nome = document.createElement('div');
      nome.className = 'nome';
      nome.innerHTML = '<b>' + (m.numero ? m.numero + '. ' : '') + esc(m.nome) + '</b>' +
        '<div class="sub">' + esc(m.tipo) + '</div>';
      var btn = document.createElement('button');
      btn.className = 'btn mini verde';
      btn.textContent = '\u25B6 Executar';
      btn.onclick = function() {
        apiPost('/api/remoto/midia', {id: m.id}).then(function(j) {
          if (j.ok) aviso('Executando: ' + m.nome, '#238636');
          atualizarEstado();
        });
      };
      li.appendChild(nome); li.appendChild(btn);
      ul.appendChild(li);
    });
  });
}
document.getElementById('midia_busca').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') buscarMidia();
});

// ── Reprodução (pausa/continua e para a mídia no telão) ──
function controlePlayer(acao) {
  apiPost('/api/remoto/player', {acao: acao}).then(function(j) {
    if (j && j.ok) {
      if (acao === 'parar') aviso('M\u00fasica/v\u00eddeo parado', '#238636');
      else aviso(j.pausado ? 'Pausado' : 'Reproduzindo', '#238636');
    }
    atualizarEstado();
  });
}

// ── Relógio (aparência e mostrar/ocultar no telão) ──
var RELOGIO_ESTADO = null;
var RELOGIO_SEL = {hora: '#F5BE08', temp: '#F5BE08', fundo: '#000000'};
var RELOGIO_CORES = [
  ['Amarelo', '#F5BE08'], ['Branco', '#FFFFFF'],
  ['Vermelho', '#FF5555'], ['Azul', '#58A6FF'],
  ['Verde', '#3FB950'], ['Roxo', '#D2A8FF'],
  ['Ciano', '#00E5FF'], ['Laranja', '#FF9800']
];
var RELOGIO_FUNDOS = [
  ['Preto', '#000000'], ['Cinza escuro', '#1a1a2e'],
  ['Azul escuro', '#0d1b2a'], ['Verde escuro', '#0a1f0a'],
  ['Vinho', '#2d0a0a']
];

function relogioMontarCores() {
  relogioMontarGrupo('relogio_cores_hora', RELOGIO_CORES, 'hora');
  relogioMontarGrupo('relogio_cores_temp', RELOGIO_CORES, 'temp');
  relogioMontarGrupo('relogio_cores_fundo', RELOGIO_FUNDOS, 'fundo');
}

function relogioMontarGrupo(id, lista, qual) {
  var box = document.getElementById(id);
  box.innerHTML = '';
  lista.forEach(function(item) {
    var b = document.createElement('button');
    b.type = 'button';
    b.dataset.cor = item[1];
    b.title = item[0];
    b.style.background = item[1];
    b.onclick = function() { relogioEscolher(qual, item[1]); };
    box.appendChild(b);
  });
}

function relogioEscolher(qual, cor) {
  RELOGIO_SEL[qual] = cor;
  var box = document.getElementById('relogio_cores_' + qual);
  var alvo = String(cor || '').toUpperCase();
  [].forEach.call(box.querySelectorAll('button'), function(b) {
    b.classList.toggle('on', String(b.dataset.cor).toUpperCase() === alvo);
  });
}

function relogioNum(valor, padrao) {
  var n = Number(valor);
  return isFinite(n) ? n : padrao;
}

function relogioSlider(qual) {
  var id = qual === 'hora' ? 'relogio_fator_hora'
    : qual === 'temp' ? 'relogio_fator_temp' : 'relogio_espacamento';
  var alvo = id + '_txt';
  var valor = Number(document.getElementById(id).value);
  var digitos = qual === 'espacamento' ? 2 : 1;
  document.getElementById(alvo).textContent =
    valor.toFixed(digitos).replace('.', ',') + (qual === 'espacamento' ? '' : '\u00d7');
}

function relogioMostrar(j) {
  if (!j || j.ok === false) return;
  RELOGIO_ESTADO = j;
  var c = j.config || {};
  relogioEscolher('hora', c.cor_hora || '#F5BE08');
  relogioEscolher('temp', c.cor_temp || '#F5BE08');
  relogioEscolher('fundo', c.cor_fundo || '#000000');
  document.getElementById('relogio_opaco').checked = !!c.fundo_opaco;
  document.getElementById('relogio_fator_hora').value = relogioNum(c.fator_hora, 1);
  document.getElementById('relogio_fator_temp').value = relogioNum(c.fator_temp, 1);
  document.getElementById('relogio_espacamento').value = relogioNum(c.espacamento, 1);
  relogioSlider('hora');
  relogioSlider('temp');
  relogioSlider('espacamento');
  var modos = {relogio: 'no rel\u00f3gio', slides: 'slides',
               midia: 'm\u00eddia', desligado: 'tel\u00e3o desligado'};
  document.getElementById('relogio_modo').textContent =
    'tel\u00e3o: ' + (modos[j.modo] || j.modo || '-');
  document.getElementById('relogio_temp').textContent = j.temperatura
    ? 'temperatura ' + j.temperatura : 'temperatura --';
  document.getElementById('btn_ocultar_relogio').textContent = j.oculto
    ? 'Mostrar rel\u00f3gio no tel\u00e3o' : 'Ocultar rel\u00f3gio do tel\u00e3o';
  document.getElementById('btn_ocultar_temp').textContent = j.temperatura_oculta
    ? 'Mostrar temperatura no tel\u00e3o' : 'Ocultar temperatura do tel\u00e3o';
}

function carregarRelogio() {
  if (!document.getElementById('relogio_cores_hora').children.length) {
    relogioMontarCores();
  }
  apiGet('/api/remoto/relogio').then(relogioMostrar).catch(function() {});
}

function relogioAcao(acao, extra) {
  var dados = {acao: acao};
  if (extra) {
    for (var k in extra) {
      if (Object.prototype.hasOwnProperty.call(extra, k)) dados[k] = extra[k];
    }
  }
  apiPost('/api/remoto/relogio', dados).then(function(j) {
    if (j && j.ok && acao === 'projetar') {
      aviso('Rel\u00f3gio no tel\u00e3o', '#238636');
    }
    relogioMostrar(j);
    atualizarEstado();
  });
}

function relogioAlternar(qual) {
  var atual = RELOGIO_ESTADO || {};
  var oculto = qual === 'relogio' ? !atual.oculto : !atual.temperatura_oculta;
  relogioAcao('alternar_' + qual, {oculto: oculto});
}

function relogioSalvar() {
  var dados = {
    acao: 'configurar',
    cor_hora: RELOGIO_SEL.hora,
    cor_temp: RELOGIO_SEL.temp,
    cor_fundo: RELOGIO_SEL.fundo,
    fator_hora: Number(document.getElementById('relogio_fator_hora').value),
    fator_temp: Number(document.getElementById('relogio_fator_temp').value),
    espacamento: Number(document.getElementById('relogio_espacamento').value),
    fundo_opaco: document.getElementById('relogio_opaco').checked
  };
  apiPost('/api/remoto/relogio', dados).then(function(j) {
    if (j && j.ok) aviso('Apar\u00eancia do rel\u00f3gio salva', '#238636');
    relogioMostrar(j);
    atualizarEstado();
  });
}

// ── Bíblia ──
// Abreviações dos livros (mesma ordem/ideia da janela Bíblia do app).
var BIB_ABREVIACOES = {
  "G\u00EAnesis": "Gn", "\u00CAxodo": "\u00CAx", "Lev\u00EDtico": "Lv",
  "N\u00FAmeros": "Nm", "Deuteron\u00F4mio": "Dt", "Josu\u00E9": "Js",
  "Ju\u00EDzes": "Jz", "Rute": "Rt", "1 Samuel": "1Sm", "2 Samuel": "2Sm",
  "1 Reis": "1Rs", "2 Reis": "2Rs", "1 Cr\u00F4nicas": "1Cr",
  "2 Cr\u00F4nicas": "2Cr", "Esdras": "Ed", "Neemias": "Ne", "Ester": "Et",
  "J\u00F3": "J\u00F3", "Salmos": "Sl", "Prov\u00E9rbios": "Pv",
  "Eclesiastes": "Ec", "C\u00E2nticos": "Ct", "Isa\u00EDas": "Is",
  "Jeremias": "Jr", "Lamenta\u00E7\u00F5es": "Lm", "Ezequiel": "Ez",
  "Daniel": "Dn", "Os\u00E9ias": "Os", "Joel": "Jl", "Am\u00F3s": "Am",
  "Obadias": "Ob", "Jonas": "Jn", "Miqu\u00E9ias": "Mq", "Naum": "Na",
  "Habacuque": "Hc", "Sofonias": "Sf", "Ageu": "Ag", "Zacarias": "Zc",
  "Malaquias": "Ml", "Mateus": "Mt", "Marcos": "Mc", "Lucas": "Lc",
  "Jo\u00E3o": "Jo", "Atos": "At", "Romanos": "Rm",
  "1 Cor\u00EDntios": "1Co", "2 Cor\u00EDntios": "2Co", "G\u00E1latas": "Gl",
  "Ef\u00E9sios": "Ef", "Filipenses": "Fp", "Colossenses": "Cl",
  "1 Tessalonicenses": "1Ts", "2 Tessalonicenses": "2Ts",
  "1 Tim\u00F3teo": "1Tm", "2 Tim\u00F3teo": "2Tm", "Tito": "Tt",
  "Filemom": "Fm", "Hebreus": "Hb", "Tiago": "Tg", "1 Pedro": "1Pe",
  "2 Pedro": "2Pe", "1 Jo\u00E3o": "1Jo", "2 Jo\u00E3o": "2Jo",
  "3 Jo\u00E3o": "3Jo", "Judas": "Jd", "Apocalipse": "Ap"
};

function abrevLivro(nome) {
  return BIB_ABREVIACOES[nome] || String(nome || '').substring(0, 2);
}

function criarBotaoGrade(texto, sigla, dados) {
  var b = document.createElement('button');
  b.type = 'button';
  b.className = 'bib-botao';
  if (sigla) {
    var s = document.createElement('span');
    s.className = 'sigla';
    s.textContent = sigla;
    var n = document.createElement('span');
    n.className = 'nome';
    n.textContent = texto;
    b.appendChild(s);
    b.appendChild(n);
  } else {
    b.textContent = texto;
  }
  if (dados) {
    Object.keys(dados).forEach(function(k) { b.dataset[k] = dados[k]; });
  }
  return b;
}

function renderizarLivrosGrade(livros) {
  var grade = document.getElementById('bib_livros_grade');
  if (!grade) return;
  grade.innerHTML = '';
  (livros || []).forEach(function(livro) {
    var b = criarBotaoGrade(livro, abrevLivro(livro), {livro: livro});
    b.onclick = function() { selecionarLivroGrade(livro); };
    grade.appendChild(b);
  });
  atualizarDestaqueLivro(document.getElementById('bib_livro').value);
}

function selecionarLivroGrade(livro) {
  document.getElementById('bib_livro').value = livro;
  document.getElementById('bib_cap').value = '';
  document.getElementById('bib_vers').value = '';
  atualizarDestaqueLivro(livro);
  carregarOpcoesBiblia();
}

function atualizarDestaqueLivro(livro) {
  var alvo = document.getElementById('bib_livro_atual');
  if (alvo) alvo.textContent = livro || '\u2014';
  [].forEach.call(
    document.querySelectorAll('#bib_livros_grade .bib-botao'),
    function(b) { b.classList.toggle('on', b.dataset.livro === livro); });
}

function renderizarCapitulosGrade(livro, capitulos) {
  var grade = document.getElementById('bib_capitulos_grade');
  if (!grade) return;
  grade.innerHTML = '';
  var titulo = document.getElementById('bib_capitulos_titulo');
  if (titulo) titulo.textContent = livro || '\u2014';
  (capitulos || []).forEach(function(cap) {
    var b = criarBotaoGrade(String(cap), null, {cap: String(cap)});
    b.onclick = function() { selecionarCapituloGrade(cap); };
    grade.appendChild(b);
  });
}

function selecionarCapituloGrade(cap) {
  document.getElementById('bib_cap').value = cap;
  document.getElementById('bib_vers').value = '';
  atualizarDestaqueCapitulo(cap);
  carregarOpcoesBiblia();
}

function atualizarDestaqueCapitulo(cap) {
  [].forEach.call(
    document.querySelectorAll('#bib_capitulos_grade .bib-botao'),
    function(b) {
      b.classList.toggle('on', b.dataset.cap === String(cap));
    });
}

function carregarVersiculosGrade(livro, cap) {
  var ul = document.getElementById('lista_biblia');
  var titulo = document.getElementById('bib_vers_titulo');
  if (titulo) titulo.textContent = (livro && cap) ? livro + ' ' + cap : '\u2014';
  if (!ul) return;
  if (!livro || !cap) {
    ul.innerHTML = '<li class="vazio">Escolha um livro e um cap\u00EDtulo.</li>';
    return;
  }
  var v = document.getElementById('bib_versao').value;
  ul.innerHTML = '<li class="vazio">Carregando...</li>';
  apiGet('/api/remoto/biblia_ref?versao=' + encodeURIComponent(v) +
         '&livro=' + encodeURIComponent(livro) +
         '&cap=' + encodeURIComponent(cap) +
         '&vers=').then(function(j) {
    ul.innerHTML = '';
    if (!j || !j.resultados || !j.resultados.length) {
      ul.innerHTML = '<li class="vazio">' +
        esc((j && j.erro) || 'Nenhum vers\u00EDculo encontrado.') + '</li>';
      return;
    }
    j.resultados.forEach(function(r) {
      var li = document.createElement('li');
      li.className = 'bib-versiculo';
      li.dataset.vers = String(r.versiculo);
      var num = document.createElement('span');
      num.className = 'num';
      num.textContent = r.versiculo;
      var txt = document.createElement('span');
      txt.className = 'texto';
      txt.textContent = r.texto;
      li.appendChild(num);
      li.appendChild(txt);
      li.onclick = function() { selecionarVersiculoGrade(r.versiculo); };
      ul.appendChild(li);
    });
    atualizarDestaqueVersiculo();
  }).catch(function() {
    ul.innerHTML = '<li class="vazio">Erro ao carregar vers\u00EDculos.</li>';
  });
}

function selecionarVersiculoGrade(num) {
  document.getElementById('bib_vers').value = num;
  atualizarDestaqueVersiculo();
  // Como na janela Bíblia do app: o versículo tocado vira o início da
  // projeção e ▶ Próximo continua pelos versículos seguintes do capítulo.
  projetarBibliaRef(num + '-9999');
}

function atualizarDestaqueVersiculo() {
  var alvo = document.getElementById('bib_vers').value.trim();
  [].forEach.call(
    document.querySelectorAll('#lista_biblia li.bib-versiculo'),
    function(li) { li.classList.toggle('on', li.dataset.vers === alvo); });
}

function carregarVersoes(j) {
  var sel = document.getElementById('bib_versao');
  if (!j || !j.versoes) return;
  var anterior = sel.value;
  sel.innerHTML = '';
  j.versoes.forEach(function(v) {
    var o = document.createElement('option');
    o.value = v; o.textContent = v;
    if (j.versao === v) o.selected = true;
    sel.appendChild(o);
  });
  // Só recarrega a grade quando a versão mudou; respostas de busca/ref não
  // devem apagar o capítulo que o operador está vendo.
  if (!anterior || j.versao !== anterior) carregarOpcoesBiblia();
}

function carregarLivros() {
  apiGet('/api/remoto/livros').then(function(j) {
    var sel = document.getElementById('bib_livro');
    if (!j || !j.livros) return;
    sel.innerHTML = '';
    j.livros.forEach(function(l) {
      var o = document.createElement('option');
      o.value = l; o.textContent = l;
      if (l === 'Jo\u00E3o') o.selected = true;
      sel.appendChild(o);
    });
    renderizarLivrosGrade(j.livros);
    carregarOpcoesBiblia();
  }).catch(function() {});
}

// ── Opções dos campos Cap:/V: (como os combos da janela Bíblia) ──
// Lista suspensa atrás de cada input: dá para clicar e escolher, e o campo
// continua digitável (faixa "1-7", vazio = capítulo inteiro).
function preencherOpcoes(id, valores) {
  var dl = document.getElementById(id);
  dl.innerHTML = '';
  (valores || []).forEach(function(v) {
    var o = document.createElement('option');
    o.value = v;
    dl.appendChild(o);
  });
}

function carregarOpcoesBiblia() {
  var v = document.getElementById('bib_versao').value;
  var livro = document.getElementById('bib_livro').value;
  var capEl = document.getElementById('bib_cap');
  var cap = capEl.value.trim();
  return apiGet('/api/remoto/biblia_opcoes?versao=' + encodeURIComponent(v) +
         '&livro=' + encodeURIComponent(livro) +
         '&cap=' + encodeURIComponent(cap)).then(function(j) {
    if (!j || !j.ok) return;
    preencherOpcoes('bib_cap_opcoes', j.capitulos);
    preencherOpcoes('bib_vers_opcoes', j.versiculos);
    renderizarCapitulosGrade(livro, j.capitulos);
    cap = capEl.value.trim();
    if (j.capitulos.length && (!cap || j.capitulos.indexOf(cap) < 0)) {
      // Livro novo (ou capítulo que não existe nesta versão): começa no
      // primeiro capítulo, como na janela Bíblia do app.
      capEl.value = j.capitulos[0];
      carregarOpcoesBiblia();
      return;
    }
    atualizarDestaqueCapitulo(cap);
    carregarVersiculosGrade(livro, cap);
  }).catch(function() {});
}

document.getElementById('bib_versao').addEventListener('change', carregarOpcoesBiblia);
document.getElementById('bib_livro').addEventListener('change', carregarOpcoesBiblia);
document.getElementById('bib_cap').addEventListener('change', carregarOpcoesBiblia);

// ── Projeção automática ao escolher a referência ──
// Terminar de escolher livro/capítulo/versículo já projeta no telão e
// atualiza a lista, sem precisar tocar em botão (os botões da aba viram
// ◀ Anterior / ▶ Próximo). O atraso de 600 ms evita projetar a cada tecla.
// Quando o "V:" digitado ainda pode virar um número maior (ex.: "1" pode
// ser 1, 10, 11...), esperamos um pouco mais: sem isso, quem digita "16"
// devagar via o versículo 1 ser projetado no meio da digitação.
var BIBLIA_AUTO_MS = 600;
var BIBLIA_AUTO_AMBIGUO_MS = 1200;
var _bibTimer = null;

function versiculoPodeContinuar() {
  var el = document.getElementById('bib_vers');
  var lista = document.getElementById('bib_vers_opcoes');
  var valor = el ? el.value.trim() : '';
  if (!el || !lista || !/^[0-9]+$/.test(valor)) return false;
  return [].some.call(lista.options, function(o) {
    return o.value !== valor && o.value.indexOf(valor) === 0;
  });
}

function autoBiblia(ev) {
  clearTimeout(_bibTimer);
  // "change" = operador confirmou (saiu do campo/Enter): usa o tempo curto.
  var espera = (!ev || ev.type === 'change' || !versiculoPodeContinuar())
    ? BIBLIA_AUTO_MS : BIBLIA_AUTO_AMBIGUO_MS;
  _bibTimer = setTimeout(function() {
    var livro = document.getElementById('bib_livro').value;
    var cap = document.getElementById('bib_cap').value.trim();
    var vers = document.getElementById('bib_vers').value.trim();
    // Só projeta com capítulo numérico e "V:" preenchido e completo:
    // "17" ou "1-7"/"1 - 7"; vazio ou "1-" (incompleto) são ignorados.
    if (!livro || !/^[0-9]+$/.test(cap)) return;
    if (!vers || (!/^[0-9]+$/.test(vers) && !/^[0-9]+ *- *[0-9]+$/.test(vers))) return;
    projetarBibliaRef(null, true);
    buscarBibliaRef();
  }, espera);
}
['bib_versao', 'bib_livro', 'bib_cap', 'bib_vers'].forEach(function(id) {
  var el = document.getElementById(id);
  el.addEventListener('input', autoBiblia);
  el.addEventListener('change', autoBiblia);
});

// Abre no computador a janela "Aparência da Projeção" (a mesma da Bíblia
// do app), com todas as opções: cor da referência, caixa e alinhamento.
function abrirProjecaoBiblia() {
  apiPost('/api/remoto/projecao', {}).then(function(j) {
    if (j && j.ok)
      aviso('Janela Apar\u00eancia da Proje\u00e7\u00e3o aberta no computador',
            '#238636');
  });
}

// Projeta por referência (livro + Cap + V:), versículo a versículo.
// Sem `vers`, usa o campo "V:"; com `vers`, começa naquele versículo.
// `silencioso` (usado pela projeção automática) evita o aviso na tela.
function projetarBibliaRef(vers, silencioso) {
  var v = document.getElementById('bib_versao').value;
  var livro = document.getElementById('bib_livro').value;
  var cap = document.getElementById('bib_cap').value.trim();
  var versTxt = (vers != null) ? String(vers)
                               : document.getElementById('bib_vers').value.trim();
  if (!livro || !cap) { if (!silencioso) aviso('Informe livro e capítulo'); return; }
  apiPost('/api/remoto/biblia', {versao: v, livro: livro, cap: cap, vers: versTxt},
          silencioso)
    .then(function(j) {
      if (j.ok && !silencioso) aviso('Projetado: ' + (j.primeiro || ''), '#238636');
      atualizarEstado();
    });
}

function buscarBibliaRef() {
  var v = document.getElementById('bib_versao').value;
  var livro = document.getElementById('bib_livro').value;
  var cap = document.getElementById('bib_cap').value.trim();
  var vers = document.getElementById('bib_vers').value.trim();
  apiGet('/api/remoto/biblia_ref?versao=' + encodeURIComponent(v) +
         '&livro=' + encodeURIComponent(livro) +
         '&cap=' + encodeURIComponent(cap) +
         '&vers=' + encodeURIComponent(vers)).then(function(j) {
    carregarVersoes(j);
    var ul = document.getElementById('lista_biblia');
    ul.innerHTML = '';
    if (!j.resultados || !j.resultados.length) {
      ul.innerHTML = '<li class="vazio">' +
        esc(j.erro || 'Nenhum vers\u00EDculo encontrado.') + '</li>';
      return;
    }
    j.resultados.forEach(function(r) {
      var ref = r.livro + ' ' + r.capitulo + ':' + r.versiculo;
      var li = document.createElement('li');
      var nome = document.createElement('div');
      nome.className = 'nome';
      nome.innerHTML = '<b>' + esc(ref) + '</b><div class="sub">' +
        esc(r.texto.substring(0, 90)) + '</div>';
      var btn = document.createElement('button');
      btn.className = 'btn mini verde';
      btn.textContent = 'Proj';
      btn.onclick = function() { projetarBibliaRef(r.versiculo); };
      li.appendChild(nome); li.appendChild(btn);
      ul.appendChild(li);
    });
  });
}

function buscarBiblia() {
  var q = document.getElementById('bib_busca').value.trim();
  var v = document.getElementById('bib_versao').value;
  apiGet('/api/remoto/biblia?q=' + encodeURIComponent(q) +
         '&versao=' + encodeURIComponent(v)).then(function(j) {
    carregarVersoes(j);
    var ul = document.getElementById('lista_biblia_busca');
    ul.innerHTML = '';
    if (!j.resultados || !j.resultados.length) {
      ul.innerHTML = '<li class="vazio">Nenhum vers&iacute;culo encontrado.</li>';
      return;
    }
    j.resultados.forEach(function(r) {
      var ref = r.livro + ' ' + r.capitulo + ':' + r.versiculo;
      var li = document.createElement('li');
      var nome = document.createElement('div');
      nome.className = 'nome';
      nome.innerHTML = '<b>' + esc(ref) + '</b><div class="sub">' +
        esc(r.texto.substring(0, 90)) + '</div>';
      var btn = document.createElement('button');
      btn.className = 'btn mini verde';
      btn.textContent = 'Proj';
      btn.onclick = function() {
        apiPost('/api/remoto/biblia', {q: q, versao: v}).then(function(j) {
          if (j.ok) aviso('Projeto: ' + ref, '#238636');
          atualizarEstado();
        });
      };
      li.appendChild(nome); li.appendChild(btn);
      ul.appendChild(li);
    });
  });
}
document.getElementById('bib_busca').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') buscarBiblia();
});

// ── Anúncios ──
function carregarAnuncios() {
  apiGet('/api/remoto/anuncios').then(function(j) {
    var ul = document.getElementById('lista_anuncios');
    ul.innerHTML = '';
    if (!j.anuncios || !j.anuncios.length) {
      ul.innerHTML = '<li class="vazio">Nenhum an&uacute;ncio cadastrado.</li>';
      return;
    }
    j.anuncios.forEach(function(a) {
      var li = document.createElement('li');
      var nome = document.createElement('div');
      nome.className = 'nome';
      nome.innerHTML = '<b>' + esc(a.titulo || '(sem t&iacute;tulo)') + '</b>' +
        '<div class="sub">' + esc(a.tipo) + '</div>';
      var btn = document.createElement('button');
      btn.className = 'btn mini verde';
      btn.textContent = 'Proj';
      btn.onclick = function() {
        apiPost('/api/remoto/anuncio', {id: a.id}).then(function(j) {
          if (j.ok) aviso('Anúncio projetado', '#238636');
          atualizarEstado();
        });
      };
      li.appendChild(nome); li.appendChild(btn);
      ul.appendChild(li);
    });
  });
}

// ── Serviço ──
var SERVICO_SEL = null;   // {id, nome} do serviço aberto
var YT_INFO_URL = '';     // URL cujas informações do YouTube já foram confirmadas
var YT_INFO_PENDING = ''; // URL da consulta em andamento
var YT_INFO_TOKEN = 0;    // invalida respostas atrasadas ao trocar a URL
var YT_INFO_TIMER = null; // debounce da consulta ao yt-dlp
var YT_TITULO_MANUAL = false; // operador digitou o título: não sobrescrever
var ITENS_SERVICO = [];   // itens do serviço aberto
var ITEM_EDIT_ID = null;  // id em edição (null = novo item)
var EXECUCAO = null;      // {servico, item, indice, titulo} do último executado
var TIPOS_ITEM = [
  ['hino', '\U0001F3B5 Hino'],
  ['versiculo', '\U0001F4D6 Vers\u00edculo'],
  ['video', '\U0001F3A5 V\u00eddeo'],
  ['audio', '\U0001F3A7 \u00C1udio'],
  ['slide', '\U0001F4C4 Slide'],
  ['anuncio', '\U0001F4E3 An\u00fancio'],
  ['sermao', '\U0001F399 Serm\u00e3o']
];

function emojiTipo(t) {
  var m = {hino: '\U0001F3B5', versiculo: '\U0001F4D6',
           video: '\U0001F3A5', audio: '\U0001F3A7',
           slide: '\U0001F4C4', anuncio: '\U0001F4E3',
           sermao: '\U0001F399', youtube: '\U0001F4FA'};
  return m[t] || '\u2022';
}

function miniBtn(txt, cor, fn) {
  var b = document.createElement('button');
  b.className = 'btn mini ' + (cor || 'cinza');
  b.textContent = txt;
  b.onclick = fn;
  return b;
}

function pill(txt, classe) {
  var s = document.createElement('span');
  s.className = 'pill' + (classe ? ' ' + classe : '');
  s.textContent = txt;
  return s;
}

function rotuloTipo(t) {
  var m = {hino: 'Hino', versiculo: 'Vers\u00edculo', video: 'V\u00eddeo',
           audio: '\u00C1udio', slide: 'Slide', anuncio: 'An\u00fancio',
           sermao: 'Serm\u00e3o', youtube: 'YouTube'};
  return m[t] || (t ? String(t) : 'Item');
}

function fmtDuracao(seg) {
  seg = Math.max(0, parseInt(seg, 10) || 0);
  if (!seg) return '';
  var m = Math.floor(seg / 60), s = seg % 60;
  return m ? (m + 'm' + (s ? ' ' + s + 's' : '')) : (s + 's');
}

// Caminho único de execução da aba Serviço: o botão geral (sem `itemId`)
// avança pelo ponteiro do serviço; o botão do item começa naquele item.
function executarServico(id, itemId, nome) {
  var dados = {id: id};
  if (itemId !== undefined && itemId !== null) dados.item = itemId;
  return apiPost('/api/remoto/servico', dados).then(function(j) {
    if (j.ok) {
      EXECUCAO = {servico: id, item: j.id, indice: j.indice,
                  titulo: j.titulo || ''};
      var st = document.getElementById('serv_status');
      if (st) {
        st.textContent = '\u25B6 ' + (nome ? nome + ' \u00b7 ' : '') +
          (j.indice + 1) + '. ' + (j.titulo || 'Item em execu\u00e7\u00e3o');
      }
      aviso('Item ' + (j.indice + 1) + ' em execu\u00e7\u00e3o', '#238636');
      if (SERVICO_SEL && String(SERVICO_SEL.id) === String(id)) {
        carregarItensServico();
      }
    }
    atualizarEstado();
    return j;
  });
}

function carregarServicos() {
  apiGet('/api/remoto/servicos').then(function(j) {
    var ul = document.getElementById('lista_servicos');
    ul.innerHTML = '';
    if (!j.servicos || !j.servicos.length) {
      ul.innerHTML = '<li class="vazio">Nenhum servi\u00e7o cadastrado.</li>';
      return;
    }
    j.servicos.forEach(function(s) {
      var li = document.createElement('li');
      li.className = 'servico-linha';
      var nome = document.createElement('div');
      nome.className = 'nome';
      nome.innerHTML = '<b>' + esc(s.nome || '') + '</b>' +
        '<div class="sub">' + s.itens + ' item(ns)</div>';
      var btnItens = miniBtn('Itens', 'cinza', function() { abrirServico(s); });
      var btn = miniBtn('Executar', 'verde', function() {
        executarServico(s.id, null, s.nome);
      });
      li.appendChild(nome); li.appendChild(btnItens); li.appendChild(btn);
      ul.appendChild(li);
    });
  });
}

function abrirServico(s) {
  if (SERVICO_SEL && String(SERVICO_SEL.id) === String(s.id)
      && document.getElementById('btn_add_item').style.display !== 'none') {
    fecharServico();
    return;
  }
  SERVICO_SEL = s;
  document.getElementById('serv_cabecalho').innerHTML =
    '<b>' + esc(s.nome || '') + '</b>';
  document.getElementById('btn_add_item').style.display = 'block';
  fecharFormItem();
  carregarItensServico();
}

function fecharServico() {
  SERVICO_SEL = null;
  ITENS_SERVICO = [];
  fecharFormItem();
  document.getElementById('serv_cabecalho').textContent =
    'Toque em "Itens" num servi\u00e7o acima.';
  document.getElementById('lista_itens_servico').innerHTML = '';
  document.getElementById('btn_add_item').style.display = 'none';
}

function carregarItensServico() {
  if (!SERVICO_SEL) return;
  var servId = SERVICO_SEL.id, servNome = SERVICO_SEL.nome;
  apiGet('/api/remoto/servico_itens?servico=' + encodeURIComponent(servId))
    .then(function(j) {
      var ul = document.getElementById('lista_itens_servico');
      ul.innerHTML = '';
      ITENS_SERVICO = (j && j.itens) || [];
      if (!ITENS_SERVICO.length) {
        ul.innerHTML = '<li class="vazio">Sem itens. Toque em "Adicionar item".</li>';
        return;
      }
      ITENS_SERVICO.forEach(function(it, i) {
        var emExec = EXECUCAO &&
          String(EXECUCAO.servico) === String(servId) &&
          String(EXECUCAO.item) === String(it.id);
        var li = document.createElement('li');
        li.className = 'item-servico' + (emExec ? ' em-execucao' : '');
        var info = document.createElement('div');
        info.className = 'nome';
        var titulo = document.createElement('div');
        titulo.className = 'item-titulo';
        titulo.innerHTML = '<span class="ordem">' + (i + 1) + '.</span> ' +
          emojiTipo(it.tipo) + ' <b>' + esc(it.titulo) + '</b>';
        info.appendChild(titulo);
        if (it.tipo === 'youtube' && it.youtube_url) {
          var urlEl = document.createElement('div');
          urlEl.className = 'item-url';
          urlEl.textContent = it.youtube_url;
          info.appendChild(urlEl);
        }
        var meta = document.createElement('div');
        meta.className = 'item-meta';
        meta.appendChild(pill(rotuloTipo(it.tipo)));
        var dur = fmtDuracao(it.duracao);
        if (dur) meta.appendChild(pill('\u23F1 ' + dur));
        if (emExec) meta.appendChild(pill('\u25B6 em execu\u00e7\u00e3o', 'exec'));
        info.appendChild(meta);
        if (it.detalhe) {
          var detalhe = document.createElement('div');
          detalhe.className = 'item-detalhe';
          detalhe.textContent = it.detalhe;
          info.appendChild(detalhe);
        }
        if (it.previa) {
          var previa = document.createElement('div');
          previa.className = 'item-previa';
          previa.textContent = it.previa;
          info.appendChild(previa);
        }
        li.appendChild(info);
        var acoes = document.createElement('div');
        acoes.className = 'item-acoes';
        var btnExec = document.createElement('button');
        btnExec.className = 'btn verde btn-exec';
        btnExec.textContent = '\u25B6 Executar';
        btnExec.onclick = function() {
          executarServico(servId, it.id, servNome);
        };
        acoes.appendChild(btnExec);
        acoes.appendChild(miniBtn('\u25B2', 'cinza', function() { moverItem(it.id, 'subir'); }));
        acoes.appendChild(miniBtn('\u25BC', 'cinza', function() { moverItem(it.id, 'descer'); }));
        acoes.appendChild(miniBtn('\u270E', 'cinza', function() { abrirFormItem(it); }));
        acoes.appendChild(miniBtn('\U0001F5D1', 'vermelho', function() { apagarItem(it); }));
        li.appendChild(acoes);
        ul.appendChild(li);
      });
    });
}

function moverItem(id, direcao) {
  apiPost('/api/remoto/servico_item',
          {operacao: 'mover', servico: SERVICO_SEL.id, id: id, direcao: direcao})
    .then(function(j) { if (j.ok) carregarItensServico(); });
}

function apagarItem(it) {
  if (!confirm('Apagar o item "' + (it.titulo || '') + '"?')) return;
  apiPost('/api/remoto/servico_item',
          {operacao: 'apagar', servico: SERVICO_SEL.id, id: it.id})
    .then(function(j) {
      if (j.ok) { aviso('Item apagado', '#238636'); carregarItensServico(); }
    });
}

function popularTipos() {
  var sel = document.getElementById('item_tipo');
  sel.innerHTML = '';
  TIPOS_ITEM.forEach(function(t) {
    var o = document.createElement('option');
    o.value = t[0]; o.textContent = t[1];
    sel.appendChild(o);
  });
}

function tipoItemMudou() {
  var t = document.getElementById('item_tipo').value;
  var mostrar = function(id, cond) {
    document.getElementById(id).style.display = cond ? 'block' : 'none';
  };
  mostrar('painel_hino', t === 'hino');
  mostrar('painel_versiculo', t === 'versiculo');
  mostrar('painel_anuncio', t === 'anuncio');
  mostrar('painel_arquivo', t === 'video' || t === 'audio' || t === 'sermao');
  mostrar('painel_youtube', t === 'video');
  youtubeMudou();
}

// Aceita o link colado sem "https://" (youtu.be/ID, www.youtube.com/...):
// sem isso a validação recusava o item e o título nunca era buscado.
function normalizarUrlYoutube(url) {
  url = String(url || '').trim();
  if (!url) return '';
  if (url.indexOf('//') === 0) return 'https:' + url;
  var baixo = url.toLowerCase();
  if (baixo.indexOf('http://') !== 0 && baixo.indexOf('https://') !== 0) {
    return 'https://' + url;
  }
  return url;
}

function ehUrlYoutube(url) {
  url = normalizarUrlYoutube(url);
  try {
    var u = new URL(url);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return false;
    var h = u.hostname.toLowerCase();
    return h === 'youtu.be' || h === 'youtube.com' ||
      h.endsWith('.youtube.com') || h === 'youtube-nocookie.com' ||
      h.endsWith('.youtube-nocookie.com');
  } catch (e) { return false; }
}

function tituloItemDigitado() {
  YT_TITULO_MANUAL = true;
}

function agendarInfoYoutube(url) {
  url = normalizarUrlYoutube(url);
  if (YT_INFO_TIMER) { clearTimeout(YT_INFO_TIMER); YT_INFO_TIMER = null; }
  var abaixo = document.getElementById('item_titulo_url');
  var titulo = document.getElementById('item_titulo');
  abaixo.textContent = url || '';
  if (!url || !ehUrlYoutube(url)) {
    YT_INFO_TOKEN++;
    YT_INFO_URL = '';
    YT_INFO_PENDING = '';
    return;
  }
  if (url === YT_INFO_URL) return;
  if (url === YT_INFO_PENDING) return;
  // Trocou de vídeo: o título automático anterior não serve mais. Um título
  // digitado antes de escolher a URL é preservado; depois da URL, o operador
  // pode digitar e o metadado não sobrescreve mais.
  if (YT_INFO_URL) {
    YT_TITULO_MANUAL = false;
    titulo.value = '';
    document.getElementById('item_duracao').value = '';
  }
  var token = ++YT_INFO_TOKEN;
  YT_INFO_PENDING = url;
  YT_INFO_TIMER = setTimeout(function() {
    YT_INFO_TIMER = null;
    apiGet('/api/remoto/youtube_info?url=' + encodeURIComponent(url))
      .then(function(j) {
        if (token !== YT_INFO_TOKEN) return;
        YT_INFO_PENDING = '';
        if (j && j.ok && j.titulo) {
          YT_INFO_URL = url;
          if (!YT_TITULO_MANUAL) titulo.value = j.titulo;
          var dur = document.getElementById('item_duracao');
          if (!dur.value) {
            dur.value = j.duracao ? String(Math.round(j.duracao)) : '';
          }
        } else {
          aviso((j && j.erro) ||
                'Não foi possível obter o título do vídeo do YouTube. ' +
                'Digite o título manualmente se quiser.');
        }
      })
      .catch(function() {
        if (token !== YT_INFO_TOKEN) return;
        YT_INFO_PENDING = '';
        aviso('Não foi possível consultar o YouTube. ' +
              'Digite o título manualmente se quiser.');
      });
  }, 700);
}

function youtubeMudou() {
  var marcado = document.getElementById('item_youtube').checked;
  var titulo = document.getElementById('item_titulo');
  var abaixo = document.getElementById('item_titulo_url');
  document.getElementById('item_youtube_url').style.display =
    marcado ? 'block' : 'none';
  titulo.readOnly = false;
  titulo.placeholder = marcado
    ? 'Título (opcional; capturado do YouTube se vazio)'
    : 'Título (opcional)';
  abaixo.style.display = marcado ? 'block' : 'none';
  if (!marcado) {
    YT_INFO_TOKEN++;
    YT_INFO_URL = '';
    if (YT_INFO_TIMER) { clearTimeout(YT_INFO_TIMER); YT_INFO_TIMER = null; }
    abaixo.textContent = '';
    return;
  }
  var url = document.getElementById('item_youtube_url').value.trim();
  agendarInfoYoutube(url);
}

function carregarSelectsItem() {
  apiGet('/api/remoto/biblia?q=').then(function(j) {
    var sel = document.getElementById('item_bib_versao');
    sel.innerHTML = '';
    ((j && j.versoes) || []).forEach(function(v) {
      var o = document.createElement('option');
      o.value = v; o.textContent = v;
      sel.appendChild(o);
    });
  }).catch(function() {});
  apiGet('/api/remoto/livros').then(function(j) {
    var sel = document.getElementById('item_bib_livro');
    sel.innerHTML = '';
    ((j && j.livros) || []).forEach(function(l) {
      var o = document.createElement('option');
      o.value = l; o.textContent = l;
      if (l === 'Jo\u00e3o') o.selected = true;
      sel.appendChild(o);
    });
  }).catch(function() {});
  apiGet('/api/remoto/anuncios').then(function(j) {
    var sel = document.getElementById('item_anuncio');
    sel.innerHTML = '';
    ((j && j.anuncios) || []).forEach(function(a) {
      var o = document.createElement('option');
      o.value = a.id; o.textContent = a.titulo || '(sem t\u00edtulo)';
      sel.appendChild(o);
    });
  }).catch(function() {});
}

function abrirFormItem(item) {
  ITEM_EDIT_ID = item ? item.id : null;
  document.getElementById('serv_form').style.display = 'block';
  document.getElementById('serv_form_titulo').textContent =
    item ? 'Editar item' : 'Adicionar item';
  popularTipos();
  document.getElementById('item_titulo').value = item ? (item.titulo || '') : '';
  document.getElementById('item_termo').value = '';
  document.getElementById('item_hino').value = '';
  document.getElementById('item_arquivo').value =
    (item && item.caminho_arquivo) || '';
  document.getElementById('item_duracao').value =
    (item && item.duracao) ? item.duracao : '';
  var ref = (item && item.ref) || {};
  document.getElementById('item_bib_cap').value = ref.cap || '';
  document.getElementById('item_bib_vers').value = ref.vers || '';
  if (ref.livro) document.getElementById('item_bib_livro').value = ref.livro;
  if (item && item.tipo === 'hino') {
    document.getElementById('item_hino').value = item.titulo || '';
  }
  document.getElementById('item_tipo').value = item ? item.tipo : 'hino';
  // Item do YouTube: o seletor volta para "Vídeo" e a caixinha é marcada,
  // guardando a URL — o mesmo arranjo do editor do aplicativo.
  var ehYoutube = !!(item && item.tipo === 'youtube');
  document.getElementById('item_youtube').checked = ehYoutube;
  var yurl = (item && item.youtube_url) || '';
  document.getElementById('item_youtube_url').value = yurl;
  if (ehYoutube) document.getElementById('item_tipo').value = 'video';
  // Um item já salvo tem título confirmado para a URL; só consulta de novo
  // se o título estiver vazio ou for a própria URL (itens antigos).
  YT_INFO_TIMER && clearTimeout(YT_INFO_TIMER);
  YT_INFO_TIMER = null;
  YT_INFO_TOKEN++;
  YT_INFO_PENDING = '';
  var ytitulo = item ? String(item.titulo || '').trim() : '';
  YT_TITULO_MANUAL = !!(ehYoutube && ytitulo && ytitulo !== yurl);
  YT_INFO_URL = (ehYoutube && ytitulo && ytitulo !== yurl) ? yurl : '';
  tipoItemMudou();
  document.getElementById('serv_form').scrollIntoView({block: 'start'});
}

function fecharFormItem() {
  document.getElementById('serv_form').style.display = 'none';
  ITEM_EDIT_ID = null;
}

function salvarItem() {
  if (!SERVICO_SEL) return;
  var tipo = document.getElementById('item_tipo').value;
  var dados = {
    operacao: ITEM_EDIT_ID ? 'editar' : 'add',
    servico: SERVICO_SEL.id,
    tipo: tipo,
    titulo: document.getElementById('item_titulo').value.trim(),
    termo: document.getElementById('item_termo').value.trim(),
    duracao: parseInt(document.getElementById('item_duracao').value, 10) || 0,
    caminho_arquivo: document.getElementById('item_arquivo').value.trim()
  };
  if (ITEM_EDIT_ID) dados.id = ITEM_EDIT_ID;
  // Vídeo do YouTube: guarda a URL em vez do arquivo (como no aplicativo).
  if (tipo === 'video' && document.getElementById('item_youtube').checked) {
    var yurl = normalizarUrlYoutube(
      document.getElementById('item_youtube_url').value);
    if (!ehUrlYoutube(yurl)) {
      aviso('URL inválida! Insira uma URL do YouTube');
      return;
    }
    document.getElementById('item_youtube_url').value = yurl;
    // O título pode ser o capturado automaticamente ou o digitado pelo
    // operador. Se o yt-dlp falhar, salva assim mesmo: a URL é a mídia e o
    // título (ou a própria URL) é só o rótulo do item.
    dados.tipo = 'youtube';
    dados.youtube_url = yurl;
    dados.caminho_arquivo = '';
  }
  if (tipo === 'hino') {
    var h = document.getElementById('item_hino').value.trim();
    if (h) dados.hino = h;
  } else if (tipo === 'versiculo') {
    dados.ref = {
      versao: document.getElementById('item_bib_versao').value,
      livro: document.getElementById('item_bib_livro').value,
      cap: document.getElementById('item_bib_cap').value.trim(),
      vers: document.getElementById('item_bib_vers').value.trim()
    };
  } else if (tipo === 'anuncio') {
    var sel = document.getElementById('item_anuncio');
    if (sel.selectedIndex >= 0) {
      dados.referencia_id = sel.value;
      dados.anuncio = sel.options[sel.selectedIndex].text;
    }
  }
  apiPost('/api/remoto/servico_item', dados).then(function(j) {
    if (j.ok) {
      aviso(ITEM_EDIT_ID ? 'Item atualizado' : 'Item adicionado', '#238636');
      fecharFormItem();
      carregarItensServico();
      carregarServicos();
    }
  });
}

// ── Medidor ──
function medidor(qual, acao) {
  apiPost('/api/remoto/medidor', {qual: qual, acao: acao}).then(function(j) {
    if (j.medidor) mostrarMedidor(j.medidor);
  });
}

function segundosDoTempo(txt) {
  var p = String(txt || '').split(':');
  var s = 0;
  for (var i = 0; i < p.length; i++) s = s * 60 + (parseInt(p[i], 10) || 0);
  return s;
}

function iniciarContagem() {
  var seg = segundosDoTempo(document.getElementById('cont_tempo').value);
  if (!seg) { aviso('Informe o tempo (ex.: 5:00)'); return; }
  apiPost('/api/remoto/medidor', {
    qual: 'contagem', acao: 'iniciar', seg: seg,
    titulo: document.getElementById('cont_titulo').value.trim()
  }).then(function(j) { if (j.medidor) mostrarMedidor(j.medidor); });
}

function fmtContagem(s) {
  s = Math.max(0, Math.round(s));
  var m = Math.floor(s / 60), r = s % 60;
  return (m < 10 ? '0' : '') + m + ':' + (r < 10 ? '0' : '') + r;
}

function mostrarMedidor(m) {
  document.getElementById('crono_tempo').textContent = m.cronometro.tempo;
  document.getElementById('cont_restante').textContent =
    fmtContagem(m.contagem.restante || 0);
}

// ── Sorteio ──
function mostrarSorteio(j) {
  if (!j || j.aberto === undefined) return;
  var est = document.getElementById('sorteio_estado');
  var res = document.getElementById('sorteio_resumo');
  var sort = document.getElementById('sorteio_sorteados');
  if (!j.aberto) {
    est.textContent = 'fechado';
    res.textContent = 'toque em Abrir';
    sort.textContent = 'ningu\u00e9m';
    return;
  }
  var rotulo = j.modo === 'names' ? 'nomes' : 'n\u00fameros';
  est.textContent = j.concluido ? 'conclu\u00eddo'
    : (j.pronto ? 'pronto' : 'em andamento');
  res.textContent = rotulo + ': ' + (j.sorteados || []).length + '/' + j.total +
    ' \u00b7 restam ' + j.restantes;
  sort.textContent = (j.sorteados && j.sorteados.length)
    ? j.sorteados.join(' \u00b7 ') : 'ningu\u00e9m';
}

function atualizarSorteio() {
  if (!document.getElementById('aba-sorteio').classList.contains('on')) return;
  apiGet('/api/remoto/sorteio').then(mostrarSorteio).catch(function() {});
}

function sorteioAbrir() {
  apiPost('/api/remoto/sorteio/abrir', {}).then(function(j) {
    if (j.ok) aviso('Sorteio aberto', '#238636');
    carregarConfigSorteio();
  });
}

function sorteioSortear() {
  apiPost('/api/remoto/sorteio/sortear', {}).then(function(j) {
    if (j.ok) aviso('Sorteado!', '#238636');
    atualizarSorteio();
  });
}

function sorteioFechar() {
  if (!confirm('Fechar o Sorteio?')) return;
  apiPost('/api/remoto/sorteio/fechar', {}).then(function(j) {
    if (j.ok) aviso('Sorteio fechado', '#238636');
    atualizarSorteio();
  });
}

var SORTEIO_MODO = 'numbers';
function sorteioModo(m) {
  SORTEIO_MODO = m;
  document.getElementById('sor_panel_numeros').style.display =
    m === 'numbers' ? 'block' : 'none';
  document.getElementById('sor_panel_nomes').style.display =
    m === 'names' ? 'block' : 'none';
  document.getElementById('sor_btn_numeros').classList.toggle('on', m === 'numbers');
  document.getElementById('sor_btn_nomes').classList.toggle('on', m === 'names');
}

function carregarConfigSorteio() {
  apiGet('/api/remoto/sorteio').then(function(j) {
    if (!j || j.aberto === undefined) return;
    mostrarSorteio(j);
    if (!j.aberto) return;
    var c = j.config || {};
    sorteioModo(j.modo === 'names' ? 'names' : 'numbers');
    if (j.modo === 'names') {
      document.getElementById('sor_nomes').value =
        (c.nomes || []).join(String.fromCharCode(10));
      document.getElementById('sor_por_vez_nomes').value = String(c.por_vez || 1);
    } else {
      if (c.inicio) document.getElementById('sor_inicio').value = c.inicio;
      if (c.fim) document.getElementById('sor_fim').value = c.fim;
      document.getElementById('sor_por_vez').value = String(c.por_vez || 1);
    }
  }).catch(function() {});
}

function configurarSorteio() {
  var dados = {modo: SORTEIO_MODO === 'names' ? 'nomes' : 'numeros'};
  if (SORTEIO_MODO === 'names') {
    dados.nomes = document.getElementById('sor_nomes').value;
    dados.por_vez = parseInt(document.getElementById('sor_por_vez_nomes').value, 10) || 1;
    if (!dados.nomes.trim()) { aviso('Digite ao menos um nome.'); return; }
  } else {
    dados.inicio = document.getElementById('sor_inicio').value.trim();
    dados.fim = document.getElementById('sor_fim').value.trim();
    dados.por_vez = parseInt(document.getElementById('sor_por_vez').value, 10) || 1;
  }
  apiPost('/api/remoto/sorteio/configurar', dados).then(function(j) {
    if (j.ok) aviso('Sorteio configurado', '#238636');
    mostrarSorteio(j);
  });
}

// ── Estado geral (polling) ──
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function atualizarEstado() {
  apiGet('/api/remoto/estado').then(function(j) {
    if (j.ok === false) return;
    var st = document.getElementById('status');
    st.innerHTML = 'v' + esc(j.versao) + '<br>' + esc(j.telao.modo);
    var previa = document.getElementById('previa');
    var cont = document.getElementById('cont_slides');
    if (j.telao.em_slides) {
      previa.textContent = j.telao.previa || '(slide)';
      cont.textContent = 'slide ' + (j.telao.slide + 1) + '/' + j.telao.total;
    } else if (j.telao.modo === 'relogio') {
      previa.textContent = 'Relógio no telão';
      cont.textContent = 'sem projeção';
    } else if (j.telao.modo === 'desligado') {
      previa.textContent = 'Telão fechado (será recriado ao projetar)';
      cont.textContent = 'telão fechado';
    } else {
      previa.textContent = 'Mídia em reprodução';
      cont.textContent = 'mídia';
    }
    document.getElementById('midia_atual').textContent =
      j.midia.arquivo ? (j.midia.indice + 1) + '/' + j.midia.total + ' - ' + j.midia.arquivo
                      : 'nenhuma mídia';
    var textoPlayer = !j.midia.tocando ? 'sem m\u00eddia'
      : (j.midia.pausado ? '\u23F8 pausado' : '\u25B6 tocando');
    var pe = document.getElementById('player_estado');
    if (pe) pe.textContent = textoPlayer;
    var pse = document.getElementById('serv_player_estado');
    if (pse) pse.textContent = textoPlayer;
    var t = j.telao.tamanho || {};
    document.getElementById('tam_texto').textContent = t.composicao
      ? 'texto ' + (Number(t.texto_escala) || 1).toFixed(2) + '×'
      : 'texto ' + (Number(t.texto_pct) || 5).toFixed(1) + '%';
    document.getElementById('tam_imagem').textContent =
      'imagem ' + (Number(t.imagem_escala) || 1).toFixed(2) + '×';
    mostrarMedidor(j.medidor);
    var mt = document.getElementById('med_tela');
    mt.textContent = (j.medidor.cronometro.rodando ? 'cronômetro ' + j.medidor.cronometro.tempo : '') +
      (j.medidor.contagem.rodando ? ' contagem ' + fmtContagem(j.medidor.contagem.restante) : '');
  }).catch(function() {});
}

function iniciar() {
  apiGet('/api/remoto/biblia?q=').then(carregarVersoes).catch(function() {});
  carregarLivros();
  carregarSelectsItem();
  carregarAnuncios();
  carregarServicos();
  relogioMontarCores();
  carregarRelogio();
  atualizarEstado();
  setInterval(atualizarEstado, 2500);
  setInterval(function() {
    if (document.getElementById('aba-anuncio').classList.contains('on')) carregarAnuncios();
  }, 15000);
  setInterval(atualizarSorteio, 4000);
}

iniciar();
"""

PAGINA = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>NavePro - Controle Remoto</title>
<style>""" + _REMOTO_CSS + """</style>
</head>
<body>

<header>
  <b>&#127760; NavePro</b>
  <div id="status">conectando...</div>
</header>

<nav id="abas">
  <button data-aba="slides" class="on">&#9654; Slides</button>
  <button data-aba="hino">&#127925; Hino</button>
  <button data-aba="biblia">&#128214; B&iacute;blia</button>
  <button data-aba="anuncio">&#128227; An&uacute;ncio</button>
  <button data-aba="servico">&#128203; Servi&ccedil;o</button>
  <button data-aba="relogio">&#128336; Rel&oacute;gio</button>
  <button data-aba="medidor">&#9201; Medidor</button>
  <button data-aba="sorteio">&#127922; Sorteio</button>
</nav>

<section id="aba-slides" class="on">
  <div class="card">
    <h3>Tel&atilde;o</h3>
    <div class="previa" id="previa">-</div>
    <div class="linha" style="margin-top:10px">
      <span class="pill" id="cont_slides">sem proje&ccedil;&atilde;o</span>
      <span class="pill" id="med_tela"></span>
    </div>
  </div>
  <div class="card">
    <div class="linha">
      <button class="btn" onclick="slide('ant')">&#9664; Voltar</button>
      <button class="btn verde" onclick="slide('prox')">&#9654; Pr&oacute;ximo</button>
    </div>
    <div class="linha" style="margin-top:8px">
      <button class="btn vermelho" onclick="slide('parar')">&#9209; Encerrar (rel&oacute;gio)</button>
    </div>
  </div>
  <div class="card">
    <h3>Tamanho do conte&uacute;do</h3>
    <div class="linha">
      <span class="pill" id="tam_texto">texto 5,0%</span>
      <button class="btn mini" onclick="tamanho('texto','menos')">A&minus;</button>
      <button class="btn mini" onclick="tamanho('texto','mais')">A+</button>
      <button class="btn mini" onclick="tamanho('texto','zerar')">&#8634; Padr&atilde;o</button>
    </div>
    <div class="linha" style="margin-top:8px">
      <span class="pill" id="tam_imagem">imagem 1,00&times;</span>
      <button class="btn mini" onclick="tamanho('imagem','menos')">&#8722;</button>
      <button class="btn mini" onclick="tamanho('imagem','mais')">+</button>
      <button class="btn mini" onclick="tamanho('imagem','zerar')">&#8634; Padr&atilde;o</button>
    </div>
    <div class="linha" style="margin-top:8px">
      <span class="pill">A&minus;/A+ muda o texto &middot; &#8722;/+ muda s&oacute; a imagem, ao vivo</span>
    </div>
  </div>
  <div class="card">
    <h3>M&uacute;sica/v&iacute;deo atual</h3>
    <div id="midia_atual" class="vazio">nenhuma m&iacute;dia</div>
  </div>
</section>

<section id="aba-hino">
  <div class="card">
    <h3>Buscar hino (letra)</h3>
    <input id="hino_busca" placeholder="N&uacute;mero ou trecho..." enterkeyhint="search">
    <button class="btn" onclick="buscarHino()">&#128269; Buscar</button>
  </div>
  <div class="card"><ul id="lista_hinos"><li class="vazio">Busque um hino.</li></ul></div>
  <div class="card">
    <h3>Executar m&uacute;sica/v&iacute;deo (BD)</h3>
    <input id="midia_busca" placeholder="N&uacute;mero ou nome do arquivo..." enterkeyhint="search">
    <button class="btn verde" onclick="buscarMidia()">&#128269; Buscar</button>
  </div>
  <div class="card"><ul id="lista_midias"><li class="vazio">Busque uma m&uacute;sica ou v&iacute;deo.</li></ul></div>
  <div class="card">
    <h3>Reprodu&ccedil;&atilde;o</h3>
    <div class="linha">
      <button class="btn" onclick="controlePlayer('play_pause')">&#9199; Play/Pause</button>
      <button class="btn vermelho" onclick="controlePlayer('parar')">&#9209; Parar</button>
    </div>
    <div class="linha" style="margin-top:8px">
      <span class="pill" id="player_estado">sem m&iacute;dia</span>
    </div>
  </div>
</section>

<section id="aba-biblia">
  <div class="card bib-grade">
    <div class="bib-bloco bib-livros">
      <h3>Livros &middot; <span id="bib_livro_atual">&mdash;</span></h3>
      <div id="bib_livros_grade" class="bib-grade-botoes livros"></div>
    </div>
    <div class="bib-bloco bib-capitulos">
      <h3>Cap&iacute;tulos &middot; <span id="bib_capitulos_titulo">&mdash;</span></h3>
      <div id="bib_capitulos_grade" class="bib-grade-botoes"></div>
    </div>
    <div class="bib-bloco bib-versiculos">
      <h3>Vers&iacute;culos &middot; <span id="bib_vers_titulo">&mdash;</span></h3>
      <ul id="lista_biblia"><li class="vazio">Escolha um livro e um cap&iacute;tulo.</li></ul>
    </div>
  </div>

  <div class="card">
    <h3>Vers&atilde;o e navega&ccedil;&atilde;o</h3>
    <select id="bib_versao"></select>
    <div class="linha" style="margin-top:8px">
      <button class="btn" onclick="slide('ant')">&#9664; Anterior</button>
      <button class="btn verde" onclick="slide('prox')">&#9654; Pr&oacute;ximo</button>
    </div>
    <div class="linha" style="margin-top:8px">
      <button class="btn" onclick="abrirProjecaoBiblia()">&#127912; Proje&ccedil;&atilde;o</button>
      <button class="btn vermelho" onclick="slide('parar')">&#9209; Encerrar (rel&oacute;gio)</button>
    </div>
    <details style="margin-top:10px">
      <summary style="cursor:pointer;color:#8b949e;font-size:13px">
        Digitar refer&ecirc;ncia (Cap: / V:)</summary>
      <div class="linha" style="margin-top:8px">
        <select id="bib_livro"></select>
        <span class="pill">Cap:</span>
        <input id="bib_cap" list="bib_cap_opcoes" inputmode="numeric" placeholder="3" style="max-width:80px">
        <datalist id="bib_cap_opcoes"></datalist>
        <span class="pill">V:</span>
        <input id="bib_vers" list="bib_vers_opcoes" inputmode="numeric" placeholder="16 (ou 1-7)">
        <datalist id="bib_vers_opcoes"></datalist>
      </div>
      <div style="color:#8b949e;font-size:13px;margin-top:6px">
        Preencha o vers&iacute;culo (V:): a proje&ccedil;&atilde;o come&ccedil;a sozinha.
      </div>
    </details>
  </div>

  <div class="card">
    <h3>Buscar vers&iacute;culo (texto)</h3>
    <input id="bib_busca" placeholder="Texto do vers&iacute;culo..." enterkeyhint="search">
    <button class="btn" onclick="buscarBiblia()">&#128269; Buscar</button>
  </div>
  <div class="card"><ul id="lista_biblia_busca"><li class="vazio">Busque um vers&iacute;culo.</li></ul></div>
</section>

<section id="aba-anuncio">
  <div class="card">
    <h3>An&uacute;cios</h3>
    <ul id="lista_anuncios"><li class="vazio">Carregando...</li></ul>
  </div>
</section>

<section id="aba-servico">
  <div class="card">
    <h3>Ordem de servi&ccedil;o</h3>
    <ul id="lista_servicos"><li class="vazio">Carregando...</li></ul>
    <div class="linha" style="margin-top:10px">
      <span class="pill" id="serv_status">pr&oacute;ximo item segue a ordem da lista</span>
    </div>
  </div>
  <div class="card">
    <h3>Reprodu&ccedil;&atilde;o</h3>
    <div class="linha">
      <button class="btn" onclick="controlePlayer('play_pause')">&#9199; Play/Pause</button>
      <button class="btn vermelho" onclick="controlePlayer('parar')">&#9209; Parar</button>
    </div>
    <div class="linha" style="margin-top:8px">
      <span class="pill" id="serv_player_estado">sem m&iacute;dia</span>
    </div>
  </div>
  <div class="card">
    <h3>Itens do servi&ccedil;o</h3>
    <div id="serv_cabecalho" class="vazio">Toque em "Itens" num servi&ccedil;o acima.</div>
    <ul id="lista_itens_servico"></ul>
    <button class="btn verde" id="btn_add_item" style="margin-top:10px;display:none"
            onclick="abrirFormItem(null)">&#10133; Adicionar item</button>
  </div>
  <div class="card" id="serv_form" style="display:none">
    <h3 id="serv_form_titulo">Adicionar item</h3>
    <input id="item_titulo" placeholder="T&iacute;tulo (opcional)"
           oninput="tituloItemDigitado()">
    <div id="item_titulo_url" style="display:none;font-size:12px;color:#58a6ff;
         margin:2px 0 4px;word-break:break-all"></div>
    <select id="item_tipo" onchange="tipoItemMudou()"></select>
    <input id="item_termo" placeholder="Buscar por n&uacute;mero/nome (opcional)">
    <div id="painel_hino" style="display:none">
      <input id="item_hino" placeholder="N&uacute;mero/nome do hino">
    </div>
    <div id="painel_versiculo" style="display:none">
      <select id="item_bib_versao"></select>
      <select id="item_bib_livro"></select>
      <div class="linha">
        <span class="pill">Cap:</span>
        <input id="item_bib_cap" inputmode="numeric" placeholder="3" style="max-width:80px">
        <span class="pill">V:</span>
        <input id="item_bib_vers" inputmode="numeric" placeholder="16 (ou 1-7; vazio = cap.)">
      </div>
    </div>
    <div id="painel_anuncio" style="display:none">
      <select id="item_anuncio"></select>
    </div>
    <div id="painel_arquivo" style="display:none">
      <input id="item_arquivo" placeholder="Caminho completo do arquivo">
    </div>
    <div id="painel_youtube" style="display:none">
      <label style="display:flex;align-items:center;gap:8px;margin-top:6px;font-size:14px">
        <input type="checkbox" id="item_youtube" onchange="youtubeMudou()" style="width:auto">
        <span>V&iacute;deo do YouTube (usar URL)</span>
      </label>
      <input id="item_youtube_url" placeholder="https://youtu.be/..."
             oninput="youtubeMudou()" style="display:none">
    </div>
    <input id="item_duracao" inputmode="numeric" placeholder="Dura&ccedil;&atilde;o (segundos, opcional)">
    <div class="linha" style="margin-top:4px">
      <button class="btn cinza" onclick="fecharFormItem()">Cancelar</button>
      <button class="btn verde" onclick="salvarItem()">&#128190; Salvar</button>
    </div>
  </div>
</section>

<section id="aba-relogio">
  <div class="card">
    <h3>Rel&oacute;gio no tel&atilde;o</h3>
    <div class="linha">
      <span class="pill" id="relogio_modo">tel&atilde;o: -</span>
      <span class="pill" id="relogio_temp">temperatura --</span>
    </div>
    <div class="linha" style="margin-top:10px">
      <button class="btn verde" onclick="relogioAcao('projetar')">&#128336; Mostrar rel&oacute;gio</button>
    </div>
    <div class="linha" style="margin-top:8px">
      <button class="btn cinza" id="btn_ocultar_relogio"
              onclick="relogioAlternar('relogio')">Ocultar rel&oacute;gio do tel&atilde;o</button>
    </div>
    <div class="linha" style="margin-top:8px">
      <button class="btn cinza" id="btn_ocultar_temp"
              onclick="relogioAlternar('temperatura')">Ocultar temperatura do tel&atilde;o</button>
    </div>
  </div>
  <div class="card">
    <h3>Apar&ecirc;ncia do rel&oacute;gio</h3>
    <span class="campo">Cor do rel&oacute;gio</span>
    <div class="cores" id="relogio_cores_hora"></div>
    <span class="campo">Cor da temperatura</span>
    <div class="cores" id="relogio_cores_temp"></div>
    <span class="campo">Cor de fundo</span>
    <div class="cores" id="relogio_cores_fundo"></div>
    <label class="check">
      <input type="checkbox" id="relogio_opaco">
      <span>Fundo opaco (sem transpar&ecirc;ncia)</span>
    </label>
    <span class="campo">Tamanho do rel&oacute;gio
      <span class="pill" id="relogio_fator_hora_txt">1,0&times;</span></span>
    <input type="range" id="relogio_fator_hora" min="0.3" max="2"
           step="0.1" oninput="relogioSlider('hora')">
    <span class="campo">Tamanho da temperatura
      <span class="pill" id="relogio_fator_temp_txt">1,0&times;</span></span>
    <input type="range" id="relogio_fator_temp" min="0.3" max="2"
           step="0.1" oninput="relogioSlider('temp')">
    <span class="campo">Espa&ccedil;amento (hora &harr; temperatura)
      <span class="pill" id="relogio_espacamento_txt">1,00</span></span>
    <input type="range" id="relogio_espacamento" min="0" max="3"
           step="0.05" oninput="relogioSlider('espacamento')">
    <button class="btn verde" style="margin-top:8px" onclick="relogioSalvar()">&#128190; Salvar apar&ecirc;ncia</button>
  </div>
</section>

<section id="aba-medidor">
  <div class="card">
    <h3>Cron&ocirc;metro</h3>
    <div class="grande" id="crono_tempo">00:00.00</div>
    <div class="linha" style="margin-top:10px">
      <button class="btn verde" onclick="medidor('cronometro','iniciar')">&#9654; Iniciar</button>
      <button class="btn cinza" onclick="medidor('cronometro','parar')">&#9208; Parar</button>
    </div>
    <div class="linha" style="margin-top:8px">
      <button class="btn cinza" onclick="medidor('cronometro','continuar')">&#9199; Continuar</button>
      <button class="btn vermelho" onclick="medidor('cronometro','encerrar')">&#9209; Encerrar</button>
    </div>
  </div>
  <div class="card">
    <h3>Contagem regressiva</h3>
    <input id="cont_tempo" inputmode="numeric" placeholder="Tempo (ex.: 5:00)" value="5:00">
    <input id="cont_titulo" placeholder="Nome / frase (opcional)">
    <div class="grande" id="cont_restante">05:00</div>
    <div class="linha" style="margin-top:10px">
      <button class="btn verde" onclick="iniciarContagem()">&#9654; Iniciar</button>
      <button class="btn cinza" onclick="medidor('contagem','parar')">&#9208; Parar</button>
    </div>
    <div class="linha" style="margin-top:8px">
      <button class="btn cinza" onclick="medidor('contagem','continuar')">&#9199; Continuar</button>
      <button class="btn vermelho" onclick="medidor('contagem','encerrar')">&#9209; Encerrar</button>
    </div>
  </div>
</section>

<section id="aba-sorteio">
  <div class="card">
    <h3>Configurar sorteio</h3>
    <div class="linha">
      <button class="btn on" id="sor_btn_numeros" onclick="sorteioModo('numbers')">&#128290; N&uacute;meros</button>
      <button class="btn" id="sor_btn_nomes" onclick="sorteioModo('names')">&#128101; Nomes</button>
    </div>
    <div id="sor_panel_numeros" style="margin-top:8px">
      <div class="linha">
        <span class="pill">De</span>
        <input id="sor_inicio" inputmode="numeric" placeholder="1">
        <span class="pill">At&eacute;</span>
        <input id="sor_fim" inputmode="numeric" placeholder="100">
      </div>
      <div class="linha" style="margin-top:8px">
        <span class="pill">Por vez</span>
        <select id="sor_por_vez">
          <option value="1">1</option><option value="2">2</option>
          <option value="3">3</option><option value="4">4</option>
          <option value="5">5</option>
        </select>
      </div>
    </div>
    <div id="sor_panel_nomes" style="display:none;margin-top:8px">
      <textarea id="sor_nomes" rows="6" placeholder="Um nome por linha"></textarea>
      <div class="linha">
        <span class="pill">Por vez</span>
        <select id="sor_por_vez_nomes">
          <option value="1">1</option><option value="2">2</option>
          <option value="3">3</option><option value="4">4</option>
          <option value="5">5</option>
        </select>
      </div>
    </div>
    <div class="linha" style="margin-top:10px">
      <button class="btn verde" onclick="configurarSorteio()">&#128190; Configurar</button>
    </div>
    <div class="linha" style="margin-top:4px">
      <span class="pill">Configurar reinicia o sorteio (zera os sorteados).</span>
    </div>
  </div>
  <div class="card">
    <h3>Sorteio</h3>
    <div class="grande" id="sorteio_estado">fechado</div>
    <div class="linha" style="margin-top:8px">
      <span class="pill" id="sorteio_resumo">-</span>
    </div>
    <div class="linha" style="margin-top:10px">
      <button class="btn verde" onclick="sorteioAbrir()">&#127922; Abrir</button>
      <button class="btn" onclick="sorteioSortear()">&#127922; Sortear</button>
      <button class="btn vermelho" onclick="sorteioFechar()">&#10006; Fechar</button>
    </div>
  </div>
  <div class="card">
    <h3>Sorteados</h3>
    <div id="sorteio_sorteados" class="vazio">ningu&eacute;m</div>
  </div>
</section>

<div id="toast"></div>

<div id="token_tela">
  <h2 style="color:#f0c040">&#128274; Token de acesso</h2>
  <p style="color:#8b949e;font-size:14px">Cole o token exibido no
  computador (Configura&ccedil;&otilde;es &gt; Controle Remoto).</p>
  <input id="token_digito" placeholder="Token">
  <button class="btn" onclick="salvarToken()">Entrar</button>
</div>

<script>""" + _REMOTO_JS + """</script>
</body>
</html>
"""
