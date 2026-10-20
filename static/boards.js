/* scratch map — quadros de raspar (boards.py faz o mapa e decide onde vai
   cada nome; aqui se monta o quadro, se pinta e se raspa). /quadros: escolher
   o continente; /quadros/continente/<slug> e /quadros/pais/<id>: o quadro.

   Todo quadro é um SVG só, sempre 3:2 (1500 × 1000), deitado: moldura, título
   no alto à esquerda, a lista (também raspável) embaixo dele e o mapa à
   direita. Tudo escala junto: nada de zoom mexendo nos nomes. */
(() => {
  const { $, esc, api, json, el, t } = window.SM;
  const root = $('#boards');
  const NS = 'http://www.w3.org/2000/svg';
  const [CW, CH] = [1500, 1000];
  const LIST = { x: 100, y: 290, bottom: 900 };  // área da lista (boards.LIST)
  const reduced = () => window.PREFS?.skip_animations || matchMedia('(prefers-reduced-motion: reduce)').matches;

  // cor de cada porção raspada: fixa por id (o mesmo país sempre com a mesma cor)
  const PALETTE = ['#e4572e', '#f3a712', '#5b8e7d', '#669bbc', '#a8c686', '#db2763', '#17bebb', '#9b5de5', '#ef8354', '#4f9d69', '#f15bb5', '#00a6fb'];
  const colorOf = (id) => PALETTE[[...String(id)].reduce((h, ch) => (h * 31 + ch.charCodeAt(0)) >>> 0, 7) % PALETTE.length];

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
    <!-- textura da película: guilhochê (ondas finas cruzadas, como nas
         cartelas de raspar), escuro e claro para parecer gravado no metal -->
    <pattern id="tex1" width="34" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(-28)">
      <path d="M0 4Q8.5 0 17 4T34 4" fill="none" stroke="#4a360c" stroke-opacity=".38" stroke-width=".9"/>
      <path d="M0 5.6Q8.5 1.6 17 5.6T34 5.6" fill="none" stroke="#fff4c4" stroke-opacity=".32" stroke-width=".6"/>
    </pattern>
    <pattern id="tex2" width="40" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(31)">
      <path d="M0 5Q10 1 20 5T40 5" fill="none" stroke="#4a360c" stroke-opacity=".22" stroke-width=".8"/>
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
      grid.append(el(`<a class="board-card" href="/quadros/continente/${b.id}">
        <svg viewBox="0 0 ${CW} ${CH}" aria-hidden="true">${DEFS}${frameSVG()}
          ${b.d.map((d, i) => `<path d="${d}" fill="${isOn('country', b.members[i]) ? colorOf(b.members[i]) : 'url(#gold)'}"/>`).join('')}
          <text x="100" y="175" class="title">${esc(b.title)}</text></svg>
        <small>${t('{n} de {total}', { n, total: b.members.length })}</small></a>`));
    }
    root.append(grid);
    const mine = [...(visited.country?.values() ?? [])];
    if (mine.length) {
      root.append(el(`<p class="group-title">${t('Seus países')}</p>`));
      const chips = el('<div class="chips"></div>');
      for (const c of mine) chips.append(el(`<a class="chip" href="/quadros/pais/${encodeURIComponent(c.id)}">${esc(c.name)}</a>`));
      root.append(chips);
    }
  }

  // ------------------------------------------------------------------ quadro
  async function boardView(kind, id) {
    const b = await api(`/api/boards/${kind}/${encodeURIComponent(id)}`);
    const mk = b.member_kind;
    const all = [...b.members, ...b.off.map((m) => ({ ...m, off: true }))].sort((a, z) => a.name.localeCompare(z.name));
    const crumbs = [`<a href="/quadros">${t('Quadros')}</a>`];
    if (b.kind === 'country' && b.parent) crumbs.push(`<a href="/quadros/continente/${b.parent.id}">${esc(b.parent.title)}</a>`);
    crumbs.push(`<b>${esc(b.title)}</b>`);
    root.append(el(`<nav class="album-crumbs">${crumbs.join(' › ')}</nav>`));

    const L = b.list;  // colunas e tamanho da letra: boards.list_layout
    L.cut ??= Infinity;
    const listSVG = all.map((m, i) => {
      const col = Math.floor(i / L.rows), row = i % L.rows;
      const x = LIST.x + col * L.col_w, y = LIST.y + row * L.row_h + L.size * 0.8;
      const name = m.name.length > L.cut ? `${m.name.slice(0, L.cut - 1)}…` : m.name;
      return `<g class="item" data-id="${esc(m.id)}"><title>${esc(m.name)}</title>
        <rect class="swatch" x="${x}" y="${y - L.size * 0.62}" width="${L.size * 1.15}" height="${L.size * 0.62}" rx="2"/>
        <text x="${x + L.size * 1.5}" y="${y}" font-size="${L.size}">${esc(name)}${m.off ? ' *' : ''}</text></g>`;
    }).join('');

    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${CW} ${CH}`);
    svg.classList.add('board-svg');
    svg.innerHTML = `${DEFS}${frameSVG()}
      <text x="100" y="178" class="title">${esc(b.title)}</text>
      <text x="103" y="226" class="subtitle"></text>
      <line x1="100" y1="250" x2="${100 + Math.max(L.width - 30, 420)}" y2="250" class="rule"/>
      <g class="list">${listSVG}</g>
      ${b.off.length ? `<text x="${LIST.x}" y="${LIST.bottom + 22}" class="note">* ${t('fora do quadro (longe do território principal)')}</text>` : ''}
      <g class="members" filter="url(#lift)">${b.members.map((m) => `<g class="member" data-id="${esc(m.id)}">
        <path class="paint" d="${m.d}" fill="${colorOf(m.id)}"/>
        <g class="foil"><path class="base" d="${m.d}"/><path class="tex1" d="${m.d}"/><path class="tex2" d="${m.d}"/></g></g>`).join('')}</g>
      <g class="callouts">${b.members.filter((m) => m.callout).map((m) => {
        const c = m.callout, left = c.side === 'left';
        return `<g class="callout" data-id="${esc(m.id)}"><line x1="${c.tx}" y1="${c.ty}" x2="${c.x + (left ? 4 : -4)}" y2="${c.y}"/>
          <circle cx="${c.tx}" cy="${c.ty}" r="2.2"/>
          <text x="${c.x}" y="${c.y}" font-size="${c.size}" text-anchor="${left ? 'end' : 'start'}" dominant-baseline="middle">${esc(m.name)}</text></g>`;
      }).join('')}</g>
      <g class="labels">${b.members.filter((m) => m.label).map((m) => {
        const l = m.label, lh = l.size * 1.15, y0 = l.y - ((l.lines.length - 1) * lh) / 2;
        return `<text class="label" data-id="${esc(m.id)}" x="${l.x}" font-size="${l.size}" text-anchor="middle">${l.lines.map((s, i) => `<tspan x="${l.x}" y="${y0 + i * lh}" dominant-baseline="middle">${esc(s)}</tspan>`).join('')}</text>`;
      }).join('')}</g>`;
    root.append(el('<div class="board-wrap"></div>'));
    $('.board-wrap', root).append(svg);

    const paint = () => {
      for (const x of svg.querySelectorAll('[data-id]')) x.classList.toggle('on', isOn(mk, x.dataset.id));
      for (const r of svg.querySelectorAll('.item .swatch')) {
        const on = isOn(mk, r.parentNode.dataset.id);
        r.setAttribute('fill', on ? colorOf(r.parentNode.dataset.id) : 'url(#gold-line)');
      }
      const n = all.filter((m) => isOn(mk, m.id)).length;
      $('.subtitle', svg).textContent = t('{n} de {total} raspados', { n, total: all.length });
    };
    paint();

    svg.addEventListener('click', (e) => {
      const id = e.target.closest('[data-id]')?.dataset.id;
      if (id) actions(all.find((m) => m.id === id));
    });

    // tocou numa porção: raspar / desmarcar / abrir o quadro do país
    function actions(m) {
      $('.board-actions')?.remove();
      const item = visited[mk]?.get(String(m.id));
      const box = el(`<div class="board-actions glass"><b>${esc(m.name)}</b><div class="row"></div></div>`);
      const row = $('.row', box);
      if (!item) row.append(button(t('Raspar'), 'flag', async () => { await scratch(m); box.remove(); }));
      else if (item.explicit) row.append(button(t('Desmarcar'), 'secondary', async () => { await unscratch(m, item); box.remove(); }));
      else row.append(el(`<small>${mk === 'country' ? t('Marcado pelos estados ou cidades.') : t('Marcado pelas cidades.')}</small>`));
      if (mk === 'country' && b.kind === 'continent') row.append(link(t('Abrir quadro'), `/quadros/pais/${encodeURIComponent(m.id)}`));
      row.append(link(t('Ver no mapa'), `/?open=${mk}:${encodeURIComponent(m.id)}`));
      row.append(button('×', 'ghost', () => box.remove()));
      document.body.append(box);
    }
    const button = (label, cls, fn) => { const x = el(`<button class="btn ${cls}">${label}</button>`); x.onclick = fn; return x; };
    const link = (label, href) => el(`<a class="btn secondary" href="${href}">${label}</a>`);

    async function scratch(m) {
      await api('/api/visits', json('POST', { kind: mk, id: m.id }));
      await loadVisited();
      const g = svg.querySelector(`.member[data-id="${CSS.escape(m.id)}"]`);
      if (g && !reduced()) await scratchAnim(g);
      paint();
    }
    async function unscratch(m, item) {
      if (item.photos && !confirm(t('Desmarcar também remove {n} foto(s) deste lugar. Continuar?', { n: item.photos }))) return;
      await api(`/api/visits/${mk}/${encodeURIComponent(m.id)}`, { method: 'DELETE' });
      await loadVisited();
      if (isOn(mk, m.id)) toast(t('Ainda marcado pelo que tem dentro.'));
      paint();
    }

    // raspagem: riscos em zigue-zague apagam a película (máscara) e revelam a cor
    function scratchAnim(g) {
      return new Promise((done) => {
        const foil = $('.foil', g);
        const bb = foil.getBBox();
        const w = Math.max(6, Math.min(bb.width, bb.height) / 4);
        let d = '';
        const rows = Math.ceil(bb.height / (w * 0.7)) + 1;
        for (let i = 0; i < rows; i++) {
          const y = bb.y + i * w * 0.7;
          const [a, z] = i % 2 ? [bb.x + bb.width + w, bb.x - w] : [bb.x - w, bb.x + bb.width + w];
          d += `${i ? 'L' : 'M'}${a},${y + (Math.random() - 0.5) * w * 0.4}L${z},${y + w * 0.35}`;
        }
        const id = `scr-${Math.random().toString(36).slice(2)}`;
        const mask = document.createElementNS(NS, 'mask');
        mask.id = id;
        mask.setAttribute('maskUnits', 'userSpaceOnUse');
        mask.innerHTML = `<rect x="${bb.x - w}" y="${bb.y - w}" width="${bb.width + 2 * w}" height="${bb.height + 2 * w}" fill="#fff"/>
          <path d="${d}" fill="none" stroke="#000" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"/>`;
        svg.querySelector('defs').append(mask);
        const stroke = mask.querySelector('path');
        const len = stroke.getTotalLength();
        stroke.style.strokeDasharray = len;
        stroke.style.strokeDashoffset = len;
        foil.setAttribute('mask', `url(#${id})`);
        g.classList.add('on');  // a cor já está embaixo; a película some aos riscos
        foil.style.display = 'inline';
        requestAnimationFrame(() => {
          stroke.style.transition = `stroke-dashoffset ${Math.min(1800, 500 + len / 3)}ms linear`;
          stroke.style.strokeDashoffset = 0;
        });
        stroke.addEventListener('transitionend', () => {
          foil.style.display = '';
          foil.removeAttribute('mask');
          mask.remove();
          done();
        }, { once: true });
      });
    }
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
      await (kind ? boardView(kind === 'continente' ? 'continente' : 'pais', decodeURIComponent(id)) : index());
    } catch (e) {
      root.append(el(`<p class="empty">${t('Erro ao carregar: {erro}', { erro: esc(e.message) })}</p>`));
    }
  })();
})();
