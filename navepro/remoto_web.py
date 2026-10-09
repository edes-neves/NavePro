# -*- coding: utf-8 -*-
"""Página do controle remoto do NavePro (celular na mesma rede).

Servida pelo ServidorAsyncHTTP na rota `/` quando o controle remoto está
ativo, sempre protegida pelo token (`?t=` na URL). É uma constante de
string neste módulo — nada de arquivo estático no bundle, então o
PyInstaller, o AppImage e o Flatpak continuam funcionando sem mudanças.

A API usada (tudo com o header `X-Token`):
  GET  /api/remoto/estado      → estado do telão/medidor/mídia
  GET  /api/remoto/hinos       → lista de hinos (busca opcional)
  GET  /api/remoto/midias      → busca músicas/vídeos na tabela `midia`
  GET  /api/remoto/biblia      → busca de versículos (texto) + versões
  GET  /api/remoto/biblia_ref  → versículos por livro/cap/V: (como no app)
  GET  /api/remoto/livros      → lista dos livros da Bíblia
  GET  /api/remoto/anuncios    → lista de anúncios
  GET  /api/remoto/servicos    → lista de serviços
  GET  /api/remoto/servico_itens → itens de um serviço (?servico=<id|nome>)
  POST /api/remoto/slide       → {acao: prox|ant|parar}
  POST /api/remoto/hino        → {id}
  POST /api/remoto/biblia      → {q, versao} ou {versao, livro, cap, vers}
  POST /api/remoto/midia       → {id}   (executa áudio/vídeo no telão)
  POST /api/remoto/anuncio     → {id}
  POST /api/remoto/servico     → {id, item?}
  POST /api/remoto/servico_item→ {operacao: add|editar|apagar|mover, servico, ...}
  POST /api/remoto/medidor     → {qual, acao, seg?, titulo?}
  POST /api/remoto/tamanho     → {qual, acao}"""

PAGINA = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>NavePro - Controle Remoto</title>
<style>
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
  input, select {
    width: 100%; background: #0d1117; color: #c9d1d9; border: 1px solid #30363d;
    border-radius: 8px; padding: 12px; font-size: 16px; margin-bottom: 8px;
  }
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
</style>
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
  <button data-aba="medidor">&#9201; Medidor</button>
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
</section>

<section id="aba-biblia">
  <div class="card">
    <h3>Refer&ecirc;ncia (Cap: V:)</h3>
    <select id="bib_versao"></select>
    <select id="bib_livro"></select>
    <div class="linha" style="margin-top:8px">
      <span class="pill">Cap:</span>
      <input id="bib_cap" inputmode="numeric" placeholder="3" style="max-width:80px">
      <span class="pill">V:</span>
      <input id="bib_vers" inputmode="numeric" placeholder="16 (ou 1-7; vazio = cap.)">
    </div>
    <div class="linha" style="margin-top:8px">
      <button class="btn" onclick="buscarBibliaRef()">&#128269; Buscar</button>
      <button class="btn verde" onclick="projetarBibliaRef()">&#128250; Projetar</button>
    </div>
  </div>
  <div class="card">
    <h3>Buscar vers&iacute;culo (texto)</h3>
    <input id="bib_busca" placeholder="Texto do vers&iacute;culo..." enterkeyhint="search">
    <button class="btn" onclick="buscarBiblia()">&#128269; Buscar</button>
  </div>
  <div class="card"><ul id="lista_biblia"><li class="vazio">Busque um vers&iacute;culo.</li></ul></div>
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
    <h3>Itens do servi&ccedil;o</h3>
    <div id="serv_cabecalho" class="vazio">Toque em "Itens" num servi&ccedil;o acima.</div>
    <ul id="lista_itens_servico"></ul>
    <button class="btn verde" id="btn_add_item" style="margin-top:10px;display:none"
            onclick="abrirFormItem(null)">&#10133; Adicionar item</button>
  </div>
  <div class="card" id="serv_form" style="display:none">
    <h3 id="serv_form_titulo">Adicionar item</h3>
    <input id="item_titulo" placeholder="T&iacute;tulo (opcional)">
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
    <input id="item_duracao" inputmode="numeric" placeholder="Dura&ccedil;&atilde;o (segundos, opcional)">
    <div class="linha" style="margin-top:4px">
      <button class="btn cinza" onclick="fecharFormItem()">Cancelar</button>
      <button class="btn verde" onclick="salvarItem()">&#128190; Salvar</button>
    </div>
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

<div id="toast"></div>

<div id="token_tela">
  <h2 style="color:#f0c040">&#128274; Token de acesso</h2>
  <p style="color:#8b949e;font-size:14px">Cole o token exibido no
  computador (Configura&ccedil;&otilde;es &gt; Controle Remoto).</p>
  <input id="token_digito" placeholder="Token">
  <button class="btn" onclick="salvarToken()">Entrar</button>
</div>

<script>
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

function apiPost(path, dados) {
  return fetch(rota(path), {
    method: 'POST',
    headers: {'X-Token': TOKEN, 'Content-Type': 'application/json'},
    body: JSON.stringify(dados || {})
  }).then(function(r) {
    if (r.status === 403) { pedirToken(); throw new Error('sem token'); }
    return r.json();
  }).then(function(j) {
    if (j && j.ok === false && j.erro) aviso(j.erro);
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

// ── Bíblia ──
function carregarVersoes(j) {
  var sel = document.getElementById('bib_versao');
  if (!j || !j.versoes) return;
  sel.innerHTML = '';
  j.versoes.forEach(function(v) {
    var o = document.createElement('option');
    o.value = v; o.textContent = v;
    if (j.versao === v) o.selected = true;
    sel.appendChild(o);
  });
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
  }).catch(function() {});
}

// Projeta por referência (livro + Cap + V:), versículo a versículo.
// Sem `vers`, usa o campo "V:"; com `vers`, começa naquele versículo.
function projetarBibliaRef(vers) {
  var v = document.getElementById('bib_versao').value;
  var livro = document.getElementById('bib_livro').value;
  var cap = document.getElementById('bib_cap').value.trim();
  var versTxt = (vers != null) ? String(vers)
                               : document.getElementById('bib_vers').value.trim();
  if (!livro || !cap) { aviso('Informe livro e capítulo'); return; }
  apiPost('/api/remoto/biblia', {versao: v, livro: livro, cap: cap, vers: versTxt})
    .then(function(j) {
      if (j.ok) aviso('Projetado: ' + (j.primeiro || ''), '#238636');
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
    var ul = document.getElementById('lista_biblia');
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
var ITENS_SERVICO = [];   // itens do serviço aberto
var ITEM_EDIT_ID = null;  // id em edição (null = novo item)
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
           sermao: '\U0001F399'};
  return m[t] || '\u2022';
}

function miniBtn(txt, cor, fn) {
  var b = document.createElement('button');
  b.className = 'btn mini ' + (cor || 'cinza');
  b.textContent = txt;
  b.onclick = fn;
  return b;
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
      var nome = document.createElement('div');
      nome.className = 'nome';
      nome.innerHTML = '<b>' + esc(s.nome || '') + '</b>' +
        '<div class="sub">' + s.itens + ' item(ns)</div>';
      var btnItens = miniBtn('Itens', 'cinza', function() { abrirServico(s); });
      var btn = miniBtn('Executar', 'verde', function() {
        apiPost('/api/remoto/servico', {id: s.id}).then(function(j) {
          if (j.ok) aviso('Item ' + (j.indice + 1) + ' em execu\u00e7\u00e3o', '#238636');
          atualizarEstado();
        });
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
  apiGet('/api/remoto/servico_itens?servico=' + encodeURIComponent(SERVICO_SEL.id))
    .then(function(j) {
      var ul = document.getElementById('lista_itens_servico');
      ul.innerHTML = '';
      ITENS_SERVICO = (j && j.itens) || [];
      if (!ITENS_SERVICO.length) {
        ul.innerHTML = '<li class="vazio">Sem itens. Toque em "Adicionar item".</li>';
        return;
      }
      ITENS_SERVICO.forEach(function(it, i) {
        var li = document.createElement('li');
        var nome = document.createElement('div');
        nome.className = 'nome';
        var sub = esc(it.tipo) +
          (it.duracao ? ' \u00b7 ' + it.duracao + 's' : '') +
          (it.detalhe ? ' \u00b7 ' + esc(it.detalhe) : '');
        nome.innerHTML = '<b>' + (i + 1) + '. ' + emojiTipo(it.tipo) + ' ' +
          esc(it.titulo) + '</b><div class="sub">' + sub + '</div>';
        li.appendChild(nome);
        li.appendChild(miniBtn('\u25B6', 'verde', function() { executarItem(it.id); }));
        li.appendChild(miniBtn('\u25B2', 'cinza', function() { moverItem(it.id, 'subir'); }));
        li.appendChild(miniBtn('\u25BC', 'cinza', function() { moverItem(it.id, 'descer'); }));
        li.appendChild(miniBtn('\u270E', 'cinza', function() { abrirFormItem(it); }));
        li.appendChild(miniBtn('\U0001F5D1', 'vermelho', function() { apagarItem(it); }));
        ul.appendChild(li);
      });
    });
}

function executarItem(id) {
  apiPost('/api/remoto/servico', {id: SERVICO_SEL.id, item: id}).then(function(j) {
    if (j.ok) aviso('Item ' + (j.indice + 1) + ' em execu\u00e7\u00e3o', '#238636');
    atualizarEstado();
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
  atualizarEstado();
  setInterval(atualizarEstado, 2500);
  setInterval(function() {
    if (document.getElementById('aba-anuncio').classList.contains('on')) carregarAnuncios();
  }, 15000);
}

iniciar();
</script>
</body>
</html>
"""
