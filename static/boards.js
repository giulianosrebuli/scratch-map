/* scratch map — quadros de raspar (boards.py faz o desenho e decide onde vai
   cada nome; aqui só se pinta e se raspa). /quadros: escolher o continente;
   /quadros/continente/<slug> e /quadros/pais/<id>: o quadro, com moldura,
   título, o mapa e a lista do que tem dentro (também raspável). */
(() => {
  const { $, esc, api, json, el, t } = window.SM;
  const root = $('#boards');
  const NS = 'http://www.w3.org/2000/svg';
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

  // película: dourado contínuo no quadro inteiro (um gradiente só, como no
  // pôster) e um grão por cima
  function defs(w, h) {
    return `<defs>
      <linearGradient id="gold" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="${w}" y2="${h}">
        <stop offset="0" stop-color="#9c7a24"/><stop offset=".22" stop-color="#e8c766"/><stop offset=".4" stop-color="#b8922e"/>
        <stop offset=".58" stop-color="#f6e27a"/><stop offset=".78" stop-color="#a8822a"/><stop offset="1" stop-color="#e2c063"/>
      </linearGradient>
      <filter id="grain" x="0" y="0" width="100%" height="100%">
        <feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="3"/>
        <feColorMatrix values="0 0 0 0 .3  0 0 0 0 .22  0 0 0 0 .05  0 0 0 .35 0"/>
        <feComposite in2="SourceGraphic" operator="in"/>
        <feBlend in="SourceGraphic" mode="multiply"/>
      </filter>
    </defs>`;
  }

  // ------------------------------------------------------------------ índice
  async function index() {
    const boards = await api('/api/boards');
    root.append(el(`<h1 class="boards-title">${t('Quadros')}</h1>`));
    root.append(el(`<p class="hint">${t('Escolha um continente. Dentro dele, cada país abre o quadro dos seus estados.')}</p>`));
    const grid = el('<div class="board-cards"></div>');
    for (const b of boards) {
      const n = b.members.filter((id) => isOn('country', id)).length;
      const a = el(`<a class="board-card" href="/quadros/continente/${b.id}">
        <svg viewBox="${b.x} 0 ${b.width} ${b.height}" aria-hidden="true">${defs(b.width, b.height)}
          ${b.d.map((d, i) => `<path d="${d}" fill="${isOn('country', b.members[i]) ? colorOf(b.members[i]) : 'url(#gold)'}"/>`).join('')}</svg>
        <b>${esc(b.title)}</b><small>${t('{n} de {total}', { n, total: b.members.length })}</small></a>`);
      grid.append(a);
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
    const all = [...b.members, ...b.off];
    const crumbs = [`<a href="/quadros">${t('Quadros')}</a>`];
    if (b.kind === 'country' && b.parent) crumbs.push(`<a href="/quadros/continente/${b.parent.id}">${esc(b.parent.title)}</a>`);
    crumbs.push(`<b>${esc(b.title)}</b>`);
    root.append(el(`<nav class="album-crumbs">${crumbs.join(' › ')}</nav>`));

    const frame = el(`<div class="board-frame"><div class="board-mat">
      <h1 class="board-name">${esc(b.title)}</h1><p class="board-sub"></p></div></div>`);
    const mat = $('.board-mat', frame);
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', `${b.x} 0 ${b.width} ${b.height}`);
    svg.classList.add('board-svg');
    svg.innerHTML = `${defs(b.width, b.height)}
      <g class="ctx">${b.context.map((d) => `<path d="${d}"/>`).join('')}</g>
      <g class="members">${b.members.map((m) => `<g class="member" data-id="${esc(m.id)}">
        <path class="paint" d="${m.d}" fill="${colorOf(m.id)}"/><path class="foil" d="${m.d}"/></g>`).join('')}</g>
      <g class="callouts">${b.members.filter((m) => m.callout).map((m) => {
        const c = m.callout, left = c.side === 'left';
        return `<g class="callout" data-id="${esc(m.id)}"><line x1="${c.tx}" y1="${c.ty}" x2="${c.x + (left ? 4 : -4)}" y2="${c.y}"/>
          <circle cx="${c.tx}" cy="${c.ty}" r="1.8"/>
          <text x="${c.x}" y="${c.y}" font-size="${c.size}" text-anchor="${left ? 'end' : 'start'}" dominant-baseline="middle">${esc(m.name)}</text></g>`;
      }).join('')}</g>
      <g class="labels">${b.members.filter((m) => m.label).map((m) => {
        const l = m.label, lh = l.size * 1.15, y0 = l.y - ((l.lines.length - 1) * lh) / 2;
        return `<text class="label" data-id="${esc(m.id)}" x="${l.x}" font-size="${l.size}" text-anchor="middle">${l.lines.map((s, i) => `<tspan x="${l.x}" y="${y0 + i * lh}" dominant-baseline="middle">${esc(s)}</tspan>`).join('')}</text>`;
      }).join('')}</g>`;
    mat.append(svg);
    const list = el('<ul class="board-list"></ul>');
    for (const m of [...all].sort((a, b2) => a.name.localeCompare(b2.name))) {
      list.append(el(`<li><button class="scratch-chip" data-id="${esc(m.id)}"><i></i><span>${esc(m.name)}</span>${b.off.includes(m) ? `<small>${t('fora do quadro')}</small>` : ''}</button></li>`));
    }
    mat.append(list);
    root.append(frame);

    const paint = () => {
      for (const g of svg.querySelectorAll('.member')) g.classList.toggle('on', isOn(mk, g.dataset.id));
      for (const x of svg.querySelectorAll('.label, .callout')) x.classList.toggle('on', isOn(mk, x.dataset.id));
      for (const c of list.querySelectorAll('.scratch-chip')) {
        const on = isOn(mk, c.dataset.id);
        c.classList.toggle('on', on);
        $('i', c).style.background = on ? colorOf(c.dataset.id) : '';
      }
      const n = all.filter((m) => isOn(mk, m.id)).length;
      $('.board-sub', mat).textContent = t('{n} de {total} raspados', { n, total: all.length });
    };
    paint();

    const pick = (e) => e.target.closest('[data-id]')?.dataset.id;
    svg.addEventListener('click', (e) => { const id = pick(e); if (id) actions(all.find((m) => m.id === id)); });
    list.addEventListener('click', (e) => { const id = pick(e); if (id) actions(all.find((m) => m.id === id)); });

    // tocou numa porção: raspar / desmarcar / abrir o quadro do país
    function actions(m) {
      $('.board-actions')?.remove();
      const item = visited[mk]?.get(String(m.id));
      const on = !!item;
      const box = el(`<div class="board-actions glass"><b>${esc(m.name)}</b><div class="row"></div></div>`);
      const row = $('.row', box);
      if (!on) row.append(button(t('Raspar'), 'flag', async () => { await scratch(m); box.remove(); }));
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
