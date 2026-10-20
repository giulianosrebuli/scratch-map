/* scratch map — stats: álbum de bandeiras. Países → estados de um país →
   cidades de um estado (#BR, #BR/BR-SP). Visitado em cor cheia, não visitado
   bem apagado. Sem bandeira (a maioria dos estados e todas as cidades, por
   enquanto), o círculo mostra a sigla. Aeroportos e landmarks ficam em lista
   no fim da página inicial. */
(() => {
  const { $, esc, api, el, t } = window.SM;
  const box = $('#visited');
  const MINOR = new Set(['de', 'do', 'da', 'dos', 'das', 'e', 'del', 'la', 'los', 'las', 'el', 'of', 'the']);

  // Sigla do círculo sem bandeira: estado pelo código (BR-SP → SP); cidade
  // pelas iniciais das palavras que contam (São José dos Campos → SJC).
  function initials(kind, it) {
    if (kind === 'state') {
      const code = it.id.split('-')[1];
      if (code && code.length <= 3 && /^[A-Z0-9]+$/.test(code)) return code;
    }
    const words = it.name.split(/[\s-]+/).filter((w) => w && !MINOR.has(w.toLowerCase()));
    return (words.length > 1 ? words.slice(0, 3).map((w) => w[0]) : [...(words[0] || '?').slice(0, 2)]).join('').toUpperCase();
  }

  function disc(kind, it, { sub = '', onClick } = {}) {
    // país: sempre do pacote; estado: a URL vem da API (pacote ou baixada do Wikidata)
    const flag = it.flag || (kind === 'country' ? `/static/vendor/flags/${it.id}.svg` : null);
    const face = flag
      ? `<img src="${esc(flag)}" alt="" loading="lazy">`
      : `<span class="sigla ${kind}">${esc(initials(kind, it))}</span>`;
    const b = el(`<button class="disc${it.visited ? ' on' : ''}" title="${esc(it.name)}">
      <span class="face">${face}</span>
      <span class="label">${esc(it.name)}${sub ? `<small>${esc(sub)}</small>` : ''}</span>
    </button>`);
    if (onClick) b.addEventListener('click', onClick);
    return b;
  }

  // Grade de círculos. `fold`: começa com poucas linhas e um fade embaixo, e o
  // "Ver mais" abre o resto (as listas de não visitados são longas).
  function section(title, items, render, { fold = false } = {}) {
    if (!items.length) return;
    box.append(el(`<p class="group-title">${title} · ${items.length}</p>`));
    const grid = el('<div class="disc-grid"></div>');
    for (const it of items) grid.append(render(it));
    box.append(grid);
    if (!fold) return;
    grid.classList.add('folded');
    // só dobra se de fato passar da altura dobrada
    requestAnimationFrame(() => {
      if (grid.scrollHeight <= grid.clientHeight + 4) { grid.classList.remove('folded'); return; }
      const more = el(`<button class="btn secondary more">${t('Ver mais ({n})', { n: items.length })}</button>`);
      more.addEventListener('click', () => {
        const open = grid.classList.toggle('folded') === false;
        more.textContent = open ? t('Ver menos') : t('Ver mais ({n})', { n: items.length });
        if (!open) grid.previousElementSibling.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      });
      grid.after(more);
    });
  }

  function crumbs(parts) {
    const nav = el('<nav class="album-crumbs"></nav>');
    parts.forEach(([label, hash], i) => {
      if (i) nav.append(' › ');
      nav.append(hash != null ? el(`<a href="#${hash}">${esc(label)}</a>`) : el(`<b>${esc(label)}</b>`));
    });
    return nav;
  }

  const mapLink = (kind, id, label) => el(`<a class="btn secondary map-link" href="/?open=${kind}:${encodeURIComponent(id)}">${label}</a>`);
  const plural = (n, one, many) => t(n === 1 ? one : many, { n });

  // ------------------------------------------------------------------ países
  async function countries() {
    const [d, visited] = await Promise.all([api('/api/stats'), api('/api/visited')]);
    const tot = d.totals;
    box.append(el(`<div class="tiles">
      <div class="tile"><b>${tot.country}<small>/${d.countries_total}</small></b><span><i class="dot country"></i>${t('Países')}</span></div>
      <div class="tile"><b>${tot.state}</b><span><i class="dot state"></i>${t('Estados')}</span></div>
      <div class="tile"><b>${tot.city}</b><span><i class="dot city"></i>${t('Cidades')}</span></div>
      <div class="tile"><b>${tot.airport}</b><span><i class="dot airport"></i>${t('Aeroportos')}</span></div>
      <div class="tile"><b>${tot.landmark}</b><span><i class="dot landmark"></i>${t('Monumentos')}</span></div>
    </div>`));
    const go = (c) => () => { location.hash = c.id; };
    section(t('Países visitados'), d.countries.filter((c) => c.visited), (c) => disc('country', c, { onClick: go(c) }));
    section(t('Ainda não'), d.countries.filter((c) => !c.visited), (c) => disc('country', c, { onClick: go(c) }), { fold: true });
    list(t('Aeroportos'), visited.airport, (p) => [p.id, p.name]);
    list(t('Monumentos'), visited.landmark, (p) => [p.name, [p.city, p.country].filter(Boolean).join(', ')]);
  }

  function list(title, items, text) {
    if (!items.length) return;
    box.append(el(`<p class="group-title">${title} · ${items.length}</p>`));
    const ul = el('<ul class="list"></ul>');
    for (const p of items) {
      const [name, sub] = text(p);
      const icon = p.kind === 'landmark' && p.cover
        ? `<img class="mini-print" src="/photos/thumb/${p.cover}.jpg" alt="">` : `<i class="dot ${p.kind}"></i>`;
      const li = el(`<li>${icon}<div class="name">${esc(name)}${sub ? `<small>${esc(sub)}</small>` : ''}</div>
        <span class="meta">${p.photos ? `📷 ${p.photos}` : ''}</span></li>`);
      li.addEventListener('click', () => { location.href = `/?open=${p.kind}:${encodeURIComponent(p.id)}`; });
      ul.append(li);
    }
    box.append(ul);
  }

  // ------------------------------------------------------------------ estados de um país
  async function country(cid) {
    const d = await api(`/api/stats/country/${encodeURIComponent(cid)}`);
    const c = d.country;
    box.append(crumbs([[t('Países'), ''], [c.name, null]]));
    const head = el('<div class="album-head"></div>');
    head.append(disc('country', c), mapLink('country', c.id, t('Ver no mapa')));
    box.append(head);
    const go = (s) => () => { location.hash = `${c.id}/${s.id}`; };
    const sub = (s) => (s.cities ? plural(s.cities, '{n} cidade', '{n} cidades') : '');
    section(t('Estados visitados'), d.states.filter((s) => s.visited), (s) => disc('state', s, { sub: sub(s), onClick: go(s) }));
    section(t('Ainda não'), d.states.filter((s) => !s.visited), (s) => disc('state', s, { onClick: go(s) }), { fold: true });
    if (!d.states.length) box.append(el(`<p class="empty">${t('Sem estados/províncias no mapa para este país.')}</p>`));
  }

  // ------------------------------------------------------------------ cidades de um estado
  async function state(cid, sid) {
    const d = await api(`/api/stats/state/${encodeURIComponent(sid)}`);
    const s = d.state;
    box.append(crumbs([[t('Países'), ''], [d.country.name, d.country.id], [s.name, null]]));
    const head = el('<div class="album-head"></div>');
    head.append(disc('state', s), mapLink('state', s.id, t('Ver no mapa')));
    box.append(head);
    const open = (c) => () => { location.href = `/?open=city:${encodeURIComponent(c.id)}`; };
    const city = (c) => disc('city', c, { sub: c.photos ? `📷 ${c.photos}` : '', onClick: open(c) });
    section(t('Cidades visitadas'), d.cities.filter((c) => c.visited), city);
    // não visitadas: as maiores primeiro (SP tem ~750)
    section(t('Ainda não'), d.cities.filter((c) => !c.visited), city, { fold: true });
    if (!d.cities.length) box.append(el(`<p class="empty">${t('Sem cidades no mapa para este estado.')}</p>`));
  }

  // ------------------------------------------------------------------ rotas (#BR, #BR/BR-SP)
  let seq = 0;
  async function route() {
    const n = ++seq;
    const [cid, sid] = decodeURIComponent(location.hash.slice(1)).split('/');
    box.innerHTML = '';
    box.classList.add('loading');
    try {
      await (sid ? state(cid, sid) : cid ? country(cid) : countries());
    } catch (e) {
      if (n === seq) box.append(el(`<p class="empty">${t('Erro ao carregar: {erro}', { erro: esc(e.message) })}</p>`));
    } finally {
      if (n === seq) box.classList.remove('loading');
    }
    window.scrollTo(0, 0);
  }
  window.addEventListener('hashchange', route);
  route();
})();
