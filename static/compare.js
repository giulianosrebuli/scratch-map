/* scratch map — Perfil → "Comparar com": este perfil e outro da casa. Cada
   lugar visitado por algum dos dois cai numa de quatro categorias
   (/api/compare): juntos (os dois, com um mês em comum nas datas de visita),
   os dois em datas diferentes (ou sem data: mesma cor, mais clara e
   tracejada), só você, só a outra pessoa. Mapa pequeno, contagens e listas. */
(() => {
  const { $, esc, api, el, t } = window.SM;
  const box = $('#compare');
  if (!box) return;
  const result = $('#compare-result');
  const KINDS = ['country', 'state', 'city', 'airport'];
  const KIND_LABEL = { country: t('Países'), state: t('Estados'), city: t('Cidades'), airport: t('Aeroportos') };
  const COLOR = { together: '#7c3aed', apart: '#a78bda', me: '#2563eb', them: '#ea7a1e' };
  const CATS = ['together', 'apart', 'me', 'them'];

  // MapLibre só quando alguém compara (o Perfil não precisa dele)
  let libs;
  const loadLibs = () => (libs ??= new Promise((done) => {
    const [js, pm, css] = window.MAPLIB;
    document.head.append(Object.assign(document.createElement('link'), { rel: 'stylesheet', href: css }));
    const s1 = Object.assign(document.createElement('script'), { src: js });
    s1.onload = () => {
      const s2 = Object.assign(document.createElement('script'), { src: pm });
      s2.onload = done;
      document.head.append(s2);
    };
    document.head.append(s1);
  }));

  // tracejado: listras na cor de "juntos", sobre um fundo claro dela
  function hatch() {
    const n = 16, k = 2, c = document.createElement('canvas');
    c.width = c.height = n * k;
    const g = c.getContext('2d');
    g.scale(k, k);
    g.fillStyle = 'rgba(167, 139, 218, .45)';
    g.fillRect(0, 0, n, n);
    g.strokeStyle = 'rgba(124, 58, 237, .85)';
    g.lineWidth = 2.2;
    for (const o of [-n, 0, n]) { g.beginPath(); g.moveTo(o, n); g.lineTo(o + n, 0); g.stroke(); }
    return { width: n * k, height: n * k, data: g.getImageData(0, 0, n * k, n * k).data };
  }

  let map;
  async function drawMap(d) {
    await loadLibs();
    const holder = $('.compare-map', result);
    const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
    const FID = ['coalesce', ['get', 'id'], ['get', 'oid']];
    const ids = (k, cat) => ['literal', d.places[k][cat]];
    const pts = (k) => ({
      type: 'FeatureCollection',
      features: CATS.flatMap((cat) => d.places[k][cat].map((id) => {
        const p = d.info[k][id];
        return p && { type: 'Feature', properties: { cat }, geometry: { type: 'Point', coordinates: [p.lon, p.lat] } };
      }).filter(Boolean)),
    });
    if (!map) {
      const protocol = new pmtiles.Protocol();
      maplibregl.addProtocol('pmtiles', protocol.tile);
    }
    map?.remove();
    map = new maplibregl.Map({
      container: holder, attributionControl: false, dragRotate: false, pitchWithRotate: false,
      style: { version: 8, sources: {}, layers: [{ id: 'water', type: 'background', paint: { 'background-color': css('--water') } }] },
      center: [-30, 10], zoom: 0.6,
    });
    map.touchZoomRotate.disableRotation();
    map.on('load', () => {
      map.addImage('hatch', hatch(), { pixelRatio: 2 });
      map.addSource('admin', { type: 'vector', url: `pmtiles://${location.origin}/geo/world.pmtiles?v=${window.GEO_V}` });
      const A = (layer) => ({ source: 'admin', 'source-layer': layer });
      map.addLayer({ id: 'land', type: 'fill', ...A('countries'), paint: { 'fill-color': css('--land') } });
      for (const [kind, layer] of [['country', 'countries'], ['state', 'states']]) {
        for (const cat of ['together', 'me', 'them']) {
          map.addLayer({ id: `${kind}-${cat}`, type: 'fill', ...A(layer), filter: ['in', FID, ids(kind, cat)],
            paint: { 'fill-color': COLOR[cat], 'fill-opacity': kind === 'state' ? 0.95 : 0.85 } });
        }
        map.addLayer({ id: `${kind}-apart`, type: 'fill', ...A(layer), filter: ['in', FID, ids(kind, 'apart')],
          paint: { 'fill-pattern': 'hatch' } });
      }
      map.addLayer({ id: 'lines', type: 'line', ...A('countries'), paint: { 'line-color': 'rgba(255,255,255,.7)', 'line-width': 0.7 } });
      for (const k of ['city', 'airport']) {
        map.addSource(k, { type: 'geojson', data: pts(k) });
        map.addLayer({ id: `${k}-pts`, type: 'circle', source: k, paint: {
          'circle-radius': k === 'city' ? 4.5 : 3.5,
          // "os dois em datas diferentes": miolo claro, contorno de "juntos"
          'circle-color': ['match', ['get', 'cat'], 'together', COLOR.together, 'apart', '#ede5fb', 'me', COLOR.me, COLOR.them],
          'circle-stroke-color': ['match', ['get', 'cat'], 'apart', COLOR.together, '#ffffff'],
          'circle-stroke-width': ['match', ['get', 'cat'], 'apart', 2, 1.2],
        } });
      }
      // enquadra cidades e aeroportos dos dois (sem nenhum: o mundo)
      const all = [...pts('city').features, ...pts('airport').features].map((f) => f.geometry.coordinates);
      if (all.length) {
        const b = all.reduce((acc, [x, y]) => [Math.min(acc[0], x), Math.min(acc[1], y), Math.max(acc[2], x), Math.max(acc[3], y)], [180, 90, -180, -90]);
        map.fitBounds(b, { padding: 30, maxZoom: 6, duration: 0 });
      }
    });
  }

  function render(d, other) {
    const label = { together: t('Juntos'), apart: t('Os dois, em datas diferentes'), me: t('Só você'), them: t('Só {nome}', { nome: other }) };
    const count = (k, cat) => d.places[k][cat].length;
    result.innerHTML = '';
    result.append(el(`<div class="compare-legend">${CATS.map((cat) => `<span><i class="sw ${cat}"></i>${esc(label[cat])}</span>`).join('')}</div>`));
    result.append(el('<div class="compare-map"></div>'));
    result.append(el(`<p class="hint">${t('Juntos: os dois visitaram, com um mês em comum nas datas de visita. Sem data, ou em datas diferentes: tracejado.')}</p>`));
    // contagens: uma linha por tipo, uma coluna por categoria
    result.append(el(`<table class="compare-table"><thead><tr><th></th>${CATS.map((cat) => `<th><i class="sw ${cat}"></i></th>`).join('')}</tr></thead>
      <tbody>${KINDS.map((k) => `<tr><td>${KIND_LABEL[k]}</td>${CATS.map((cat) => `<td>${count(k, cat) || '·'}</td>`).join('')}</tr>`).join('')}</tbody></table>`));
    // listas de países e estados por categoria (cidades e aeroportos: só a contagem)
    for (const cat of CATS) {
      const items = ['country', 'state'].flatMap((k) => d.places[k][cat].map((id) => ({ k, id, name: d.info[k][id]?.name || id })));
      if (!items.length) continue;
      const block = el(`<div class="compare-list"><p class="group-title"><i class="sw ${cat}"></i>${esc(label[cat])}</p><div class="chips"></div></div>`);
      for (const it of items) {
        const a = el(`<a class="chip" href="/?open=${it.k}:${encodeURIComponent(it.id)}"><i class="dot ${it.k}"></i>${esc(it.name)}</a>`);
        $('.chips', block).append(a);
      }
      result.append(block);
    }
    result.hidden = false;
    drawMap(d).catch(() => {});
  }

  box.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-pid]');
    if (!b) return;
    box.querySelectorAll('[data-pid]').forEach((x) => x.setAttribute('aria-pressed', x === b));
    try {
      render(await api(`/api/compare/${b.dataset.pid}`), b.dataset.name);
    } catch (err) {
      result.hidden = false;
      result.textContent = t('Erro ao carregar: {erro}', { erro: err.message });
    }
  });
})();
