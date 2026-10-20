/* scratch map — quadros de raspar (boards.py faz o mapa e decide onde vai
   cada nome; aqui se monta o quadro, se pinta e se raspa). /boards: escolher
   o continente; /boards/continent/<slug> e /boards/country/<id>: o quadro.

   Todo quadro é um SVG só, sempre 3:2 (1500 × 1000), deitado: moldura, título
   no alto à esquerda, a lista (também raspável) embaixo dele e o mapa à
   direita. Tudo escala junto: nada de zoom mexendo nos nomes. */
(() => {
  const { $, esc, api, el, t } = window.SM;
  const root = $('#boards');
  const NS = 'http://www.w3.org/2000/svg';
  const [CW, CH] = [1500, 1000];
  // nos quadros, todo nome em caixa alta (boards.CAPS mede a largura assim)
  const up = (s) => s.toLocaleUpperCase(document.documentElement.lang || 'pt-BR');


  let visited = {};   // kind → Map(id → item de /api/visited)
  async function loadVisited() {
    const v = await api('/api/visited');
    visited = Object.fromEntries(Object.entries(v).map(([k, list]) => [k, new Map(list.map((x) => [String(x.id), x]))]));
  }
  const isOn = (kind, id) => visited[kind]?.has(String(id));

  let toastTimer;
  function toast(msg) {
    const box = $('#toast');
    box.textContent = msg;
    box.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { box.hidden = true; }, 4000);
  }

  // película: dourado contínuo no mapa inteiro (um gradiente só, como no
  // pôster) com grão; moldura: madeira escura, filete dourado e cantoneiras
  const DEFS = `<defs>
    <linearGradient id="gold" gradientUnits="userSpaceOnUse" x1="700" y1="80" x2="1420" y2="920">
      <stop offset="0" stop-color="#9c7a24"/><stop offset=".22" stop-color="#e8c766"/><stop offset=".4" stop-color="#b8922e"/>
      <stop offset=".58" stop-color="#f6e27a"/><stop offset=".78" stop-color="#a8822a"/><stop offset="1" stop-color="#e2c063"/>
    </linearGradient>
    <linearGradient id="gold-line" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#8a6a1f"/><stop offset=".35" stop-color="#f3dc8a"/><stop offset=".6" stop-color="#b08a2e"/><stop offset="1" stop-color="#e8c766"/>
    </linearGradient>
    <!-- raspado: folha prateada clara por baixo do ouro (mesma textura) -->
    <linearGradient id="silver" gradientUnits="userSpaceOnUse" x1="700" y1="80" x2="1420" y2="920">
      <stop offset="0" stop-color="#b9bcc1"/><stop offset=".3" stop-color="#e4e6e9"/><stop offset=".55" stop-color="#c7cacf"/>
      <stop offset=".8" stop-color="#eceef0"/><stop offset="1" stop-color="#c3c6cb"/>
    </linearGradient>
    <linearGradient id="silver-line" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#9da1a7"/><stop offset=".45" stop-color="#eef0f2"/><stop offset="1" stop-color="#b5b9be"/>
    </linearGradient>
    <linearGradient id="wood" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#3a2a1a"/><stop offset=".5" stop-color="#21170e"/><stop offset="1" stop-color="#3a2a1a"/>
    </linearGradient>
    <radialGradient id="mat" cx=".5" cy=".45" r=".75">
      <stop offset="0" stop-color="#1b2029"/><stop offset="1" stop-color="#0e1116"/>
    </radialGradient>
    <filter id="grain" x="0" y="0" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="3"/>
      <feColorMatrix values="0 0 0 0 .3  0 0 0 0 .22  0 0 0 0 .05  0 0 0 .35 0"/>
      <feComposite in2="SourceGraphic" operator="in"/>
      <feBlend in="SourceGraphic" mode="multiply"/>
    </filter>
    <!-- textura da película: papel metálico amassado (scripts/foil_texture.py),
         em cinza, aplicada por cima do dourado em modo overlay -->
    <pattern id="paper" width="420" height="420" patternUnits="userSpaceOnUse">
      <image href="/static/textures/foil.png" width="420" height="420"/>
    </pattern>
    <filter id="lift"><feDropShadow dx="0" dy="3" stdDeviation="5" flood-color="#000" flood-opacity=".55"/></filter>
  </defs>`;

  function frameSVG() {
    const corner = (x, y, sx, sy) => `<path transform="translate(${x} ${y}) scale(${sx} ${sy})"
      d="M0 0h46v4H8v38H4V0zm12 12h18v3H15v15h-3zM0 0l22 22" fill="url(#gold-line)" stroke="url(#gold-line)" stroke-width="1.2"/>`;
    return `<rect width="${CW}" height="${CH}" fill="url(#wood)"/>
      <rect x="10" y="10" width="${CW - 20}" height="${CH - 20}" fill="none" stroke="url(#gold-line)" stroke-width="7"/>
      <rect x="22" y="22" width="${CW - 44}" height="${CH - 44}" fill="none" stroke="#120c06" stroke-width="5"/>
      <rect x="30" y="30" width="${CW - 60}" height="${CH - 60}" fill="none" stroke="url(#gold-line)" stroke-width="2"/>
      <rect x="40" y="40" width="${CW - 80}" height="${CH - 80}" fill="url(#mat)"/>
      <rect x="56" y="56" width="${CW - 112}" height="${CH - 112}" fill="none" stroke="#b9a774" stroke-opacity=".55" stroke-width="1.2"/>
      ${corner(62, 62, 1, 1)}${corner(CW - 62, 62, -1, 1)}${corner(62, CH - 62, 1, -1)}${corner(CW - 62, CH - 62, -1, -1)}`;
  }

  // ------------------------------------------------------------------ índice
  async function index() {
    const boards = await api('/api/boards');
    root.append(el(`<h1 class="boards-title">${t('Quadros')}</h1>`));
    root.append(el(`<p class="hint">${t('Escolha um continente. Dentro dele, cada país abre o quadro dos seus estados.')}</p>`));
    const grid = el('<div class="board-cards"></div>');
    for (const b of boards) {
      const n = b.members.filter((id) => isOn('country', id)).length;
      grid.append(el(`<a class="board-card" href="/boards/continent/${b.id}">
        <svg viewBox="0 0 ${CW} ${CH}" aria-hidden="true">${DEFS}${frameSVG()}
          ${b.d.map((d, i) => `<path d="${d}" fill="${isOn('country', b.members[i]) ? 'url(#silver)' : 'url(#gold)'}"/>`).join('')}
          <text x="100" y="175" class="title">${esc(b.title)}</text></svg>
        <small>${t('{n} de {total}', { n, total: b.members.length })}</small></a>`));
    }
    root.append(grid);
    const mine = [...(visited.country?.values() ?? [])];
    if (mine.length) {
      root.append(el(`<p class="group-title">${t('Seus países')}</p>`));
      const chips = el('<div class="chips"></div>');
      for (const c of mine) chips.append(el(`<a class="chip" href="/boards/country/${encodeURIComponent(c.id)}">${esc(c.name)}</a>`));
      root.append(chips);
    }
  }

  // ------------------------------------------------------------------ quadro
  async function boardView(kind, id) {
    const b = await api(`/api/boards/${kind}/${encodeURIComponent(id)}`);
    const mk = b.member_kind;
    const all = [...b.members, ...b.off.map((m) => ({ ...m, off: true }))].sort((a, z) => a.name.localeCompare(z.name));
    const crumbs = [`<a href="/boards">${t('Quadros')}</a>`];
    if (b.parent) crumbs.push(`<a href="/boards/continent/${b.parent.id}">${esc(b.parent.title)}</a>`);
    if (b.kind === 'state' && b.country) crumbs.push(`<a href="/boards/country/${encodeURIComponent(b.country.id)}">${esc(b.country.title)}</a>`);
    crumbs.push(`<b>${esc(b.title)}</b>`);
    root.append(el(`<div class="board-top"><nav class="album-crumbs">${crumbs.join(' › ')}</nav>
      <button class="btn secondary small board-export">${t('Exportar imagem')}</button></div>`));

    // Lista: no quadro de estado, só as cidades visitadas (são centenas), na
    // área que o servidor reservou; nos outros, todos, como boards.list_layout
    // decidiu (colunas e tamanho da letra).
    const cityBoard = mk === 'city';
    const items = cityBoard ? all.filter((m) => isOn(mk, m.id)) : all;
    const L = b.list;
    if (cityBoard) {
      const size = 13, row_h = size * 1.6, rows = Math.max(1, Math.floor((L.bottom - L.top) / row_h));
      const cols = Math.max(1, Math.ceil(items.length / rows)), col_w = L.width / cols;
      Object.assign(L, { size, row_h, rows, col_w, cut: Math.max(4, Math.floor((col_w - 22 - size * 1.5) / (size * 0.68))) });
    }
    L.cut ??= Infinity;
    const nameX = cityBoard ? 1.5 : 4.2;  // cidade não tem sigla na lista
    const listSVG = items.map((m, i) => {
      const col = Math.floor(i / L.rows), row = i % L.rows;
      const x = L.x + col * L.col_w, y = L.top + row * L.row_h + L.size * 0.8;
      const name = up(m.name.length > L.cut ? `${m.name.slice(0, L.cut - 1)}…` : m.name);
      return `<g class="item" data-id="${esc(m.id)}"><title>${esc(m.name)}</title>
        <rect class="swatch" x="${x}" y="${y - L.size * 0.62}" width="${L.size * 1.15}" height="${L.size * 0.62}" rx="2"/>
        ${cityBoard ? '' : `<text x="${x + L.size * 1.5}" y="${y}" font-size="${L.size * 0.82}" class="abbr">${esc(m.abbr)}</text>`}
        <text x="${x + L.size * nameX}" y="${y}" font-size="${L.size}">${esc(name)}${m.off ? ' *' : ''}</text></g>`;
    }).join('') || (cityBoard ? `<text x="${L.x}" y="${L.top + 16}" class="note">${t('Nenhuma cidade visitada ainda.')}</text>` : '');
    const offNote = cityBoard ? (items.some((m) => m.off) ? t('sem contorno no mapa') : '')
      : (b.off.length ? t('fora do quadro (longe do território principal)') : '');

    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${CW} ${CH}`);
    svg.classList.add('board-svg');
    svg.innerHTML = `${DEFS}${frameSVG()}
      <text x="100" y="178" class="title" style="font-size:${Math.min(76, (L.title_cap || 600) / (b.title.length * 0.8))}px">${esc(b.title)}</text>
      <text x="103" y="226" class="subtitle"></text>
      <line x1="100" y1="250" x2="${100 + Math.max(Math.min(L.width, 640) - 30, 420)}" y2="250" class="rule"/>
      <g class="list">${listSVG}</g>
      ${offNote ? `<text x="140" y="${L.bottom + 24}" class="note">* ${offNote}</text>` : ''}
      <g class="members" filter="url(#lift)">${b.base ? `<g class="state-base"><path class="base" d="${b.base}"/><path class="tex" d="${b.base}"/></g>` : ''}${b.members.map((m) => `<g class="member" data-id="${esc(m.id)}">
        <path class="paint" d="${m.d}"/><path class="ptex" d="${m.d}"/>
        <g class="foil"><path class="base" d="${m.d}"/><path class="tex" d="${m.d}"/></g></g>`).join('')}</g>
      <g class="callouts">${b.members.filter((m) => m.callout).map((m) => {
        const c = m.callout, left = c.side === 'left';
        return `<g class="callout" data-id="${esc(m.id)}"><polyline points="${c.path}"/>
          <circle cx="${c.tx}" cy="${c.ty}" r="2.2"/>
          <text x="${c.x}" y="${c.y}" font-size="${c.size}" text-anchor="${left ? 'end' : 'start'}" dominant-baseline="middle">${esc(m.abbr)}</text></g>`;
      }).join('')}</g>
      <g class="labels">${b.members.filter((m) => m.label).map((m) => {
        // sigla (país, estado) ou nome por extenso (cidade), em uma ou duas linhas
        const l = m.label, lh = l.size * 1.12, y0 = l.y - ((l.lines.length - 1) * lh) / 2;
        return `<text class="label${cityBoard ? ' city' : ''}" data-id="${esc(m.id)}" x="${l.x}" font-size="${l.size}" text-anchor="middle"><title>${esc(m.name)}</title>${l.lines.map((s, i) => `<tspan x="${l.x}" y="${y0 + i * lh}" dominant-baseline="middle">${esc(s)}</tspan>`).join('')}</text>`;
      }).join('')}</g>`;
    root.append(el('<div class="board-wrap"></div>'));
    $('.board-wrap', root).append(svg);

    const paint = () => {
      for (const x of svg.querySelectorAll('[data-id]')) x.classList.toggle('on', isOn(mk, x.dataset.id));
      for (const r of svg.querySelectorAll('.item .swatch')) {
        const on = isOn(mk, r.parentNode.dataset.id);
        r.setAttribute('fill', on ? 'url(#silver-line)' : 'url(#gold-line)');
      }
      const n = all.filter((m) => isOn(mk, m.id)).length;
      $('.subtitle', svg).textContent = t('{n} de {total}', { n, total: all.length });
    };
    paint();

    svg.addEventListener('click', (e) => {
      const id = e.target.closest('[data-id]')?.dataset.id;
      if (id) actions(all.find((m) => m.id === id));
    });

    // Só leitura: marcar e desmarcar é no mapa. Tocar numa porção (ou no nome
    // na lista) leva ao quadro de dentro dela ou ao lugar no mapa.
    function actions(m) {
      $('.board-actions')?.remove();
      const box = el(`<div class="board-actions glass"><b>${esc(up(m.name))}</b><div class="row"></div></div>`);
      const row = $('.row', box);
      if (mk === 'country' && b.kind === 'continent') row.append(link(t('Abrir quadro'), `/boards/country/${encodeURIComponent(m.id)}`));
      if (mk === 'state' && b.drill) row.append(link(t('Abrir quadro'), `/boards/state/${encodeURIComponent(m.id)}`));
      row.append(link(t('Ver no mapa'), `/?open=${mk}:${encodeURIComponent(m.id)}`));
      const close = el('<button class="btn ghost">×</button>');
      close.onclick = () => box.remove();
      row.append(close);
      document.body.append(box);
    }
    const link = (label, href) => el(`<a class="btn secondary" href="${href}">${label}</a>`);

    // Exportar: o SVG vira PNG (3000 × 2000) num canvas. A textura vai
    // embutida (data: URL), porque o SVG desenhado como imagem não busca
    // arquivos de fora.
    $('.board-export', root).addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        const clone = svg.cloneNode(true);
        clone.setAttribute('width', CW);
        clone.setAttribute('height', CH);
        const tex = await fetch('/static/textures/foil.png').then((r) => r.blob());
        const dataURL = await new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(tex); });
        clone.querySelectorAll('image').forEach((im) => im.setAttribute('href', dataURL));
        const style = document.createElementNS(NS, 'style');
        style.textContent = [...document.styleSheets].flatMap((sh) => { try { return [...sh.cssRules]; } catch { return []; } })
          .map((r) => r.cssText).filter((c) => c.includes('.board-svg')).join('\n');
        clone.prepend(style);
        const blob = new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml' });
        const img = new Image();
        img.src = URL.createObjectURL(blob);
        await img.decode();
        const canvas = Object.assign(document.createElement('canvas'), { width: CW * 2, height: CH * 2 });
        canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(img.src);
        const png = await new Promise((res) => canvas.toBlob(res, 'image/png'));
        const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(png), download: `scratch-map-${b.id}.png` });
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      } catch (err) {
        toast(t('Não deu para exportar: {erro}', { erro: err.message }));
      } finally {
        btn.disabled = false;
      }
    });
  }

  // ------------------------------------------------------------------ rotas
  (async () => {
    if (root.dataset.ready !== 'true') {
      root.append(el(`<p class="empty">${t('Os quadros precisam dos contornos simplificados: rode scripts/build_boards.py.')}</p>`));
      return;
    }
    await loadVisited();
    const [, , kind, id] = location.pathname.split('/');
    try {
      await (kind ? boardView(['continent', 'state'].includes(kind) ? kind : 'country', decodeURIComponent(id)) : index());
    } catch (e) {
      root.append(el(`<p class="empty">${t('Erro ao carregar: {erro}', { erro: esc(e.message) })}</p>`));
    }
  })();
})();
