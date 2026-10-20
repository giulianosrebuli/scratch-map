/* scratch map — frontend (vanilla JS + MapLibre, sem build). */
(() => {
  const { $, esc, api, json, fmtDate, fmtMonth, store, el, print, lightbox, t } = window.SM;
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const C = {
    water: css('--water'), land: css('--land'), border: css('--border'),
    country: css('--country'), state: css('--state'), city: css('--city'), airport: css('--airport'),
    landmark: css('--landmark'),
  };
  const KINDS = ['country', 'state', 'city', 'airport', 'landmark'];
  const KIND_LABEL = { country: t('País'), state: t('Estado / província'), city: t('Cidade'), airport: t('Aeroporto'), landmark: t('Monumento') };
  const PIN = 'M12 1.5a8 8 0 0 0-8 8c0 5.6 6.4 11.6 7.4 12.5a.9.9 0 0 0 1.2 0c1-.9 7.4-6.9 7.4-12.5a8 8 0 0 0-8-8zm0 5a3 3 0 1 1 0 6 3 3 0 0 1 0-6z';  // alfinete com furo (evenodd)
  const PLANE = 'M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z';
  const FLAG_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"><path d="M5 21V3.5"/><path class="cloth" d="M5 4h12.5l-2.5 4.25 2.5 4.25H5"/></svg>';
  const THUMB_Z = 8;       // a partir deste zoom o landmark vira a miniatura da foto

  const S = {
    layers: { country: true, state: true, city: true, airport: true, landmark: true, ...store.get('layers', {}) },
    visited: { country: [], state: [], city: [], airport: [], landmark: [] },
    cityShapes: { type: 'FeatureCollection', features: [] },
    view: { type: 'none' },     // none (gaveta fechada) | add | add-city | add-airport | add-list | add-photo | place | landmark-form
    history: [],                // pilha de views para o "voltar"
    placing: null,              // formulário do landmark aberto: {marker, move}
    loaded: false,              // primeira carga feita (só depois disso há raspagem)
  };

  const isMobile = () => window.matchMedia('(max-width: 760px)').matches;
  const isVisited = (kind, id) => S.visited[kind].some((x) => String(x.id) === String(id));

  let toastTimer;
  function toast(msg) {
    const box = $('#toast');
    box.textContent = msg;
    box.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { box.hidden = true; }, 4500);
  }
  // Estado/país visitado só por causa de cidades (ou estados) marcados.
  const IMPLIED_MSG = {
    state: t('Este estado está marcado pelas suas cidades. Desmarque as cidades para tirá-lo.'),
    country: t('Este país está marcado pelas suas cidades e estados. Desmarque-os para tirá-lo.'),
  };

  // ------------------------------------------------------------------ mapa
  const GLOBE = window.SETTINGS?.projection === 'globe';
  // bordas (linha branca), escolhidas na configuração; cidade desligada por padrão
  const BORDERS = window.PREFS?.borders || { borders_country: true, borders_state: true, borders_city: false };
  $('#map').classList.toggle('globe', GLOBE);  // fundo de espaço em volta do globo
  const map = new maplibregl.Map({
    container: 'map',
    style: {
      version: 8, sources: {},
      layers: [{ id: 'water', type: 'background', paint: { 'background-color': C.water } }],
      // halo de atmosfera em volta do globo (só aparece na projeção globo)
      sky: { 'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 4, 0.8, 7, 0] },
      // plano ou globo: escolhido na configuração
      projection: { type: GLOBE ? 'globe' : 'mercator' },
    },
    // nasce de longe: o mundo (poucos tiles) já carrega enquanto vêm as visitas
    center: [-30, 10], zoom: 0.8, minZoom: 0.8, maxZoom: 14,
    attributionControl: false,  // as fontes ficam em Configurações → Sobre
    dragRotate: false, pitchWithRotate: false,
  });
  map.touchZoomRotate.disableRotation();

  const emptyFC = { type: 'FeatureCollection', features: [] };

  // Países e estados vêm de tiles vetoriais (geodata/world.pmtiles): o navegador
  // baixa só os pedaços da área e do zoom na tela. Estado sem código ISO usa o
  // id do Overture (oid).
  const pmtilesProtocol = new pmtiles.Protocol();
  maplibregl.addProtocol('pmtiles', pmtilesProtocol.tile);
  const ADMIN = (layer) => ({ source: 'admin', 'source-layer': layer });
  const FID = ['coalesce', ['get', 'id'], ['get', 'oid']];
  const fid = (f) => String(f.properties.id ?? f.properties.oid);
  // nomes de país e estado no idioma da interface (os das tiles são os da montagem)
  const NAMES = { country: {}, state: {} };
  api('/api/names').then((r) => Object.assign(NAMES, r)).catch(() => {});

  // bbox de um contorno de cidade, só com as partes a menos de 1° da principal:
  // Vitória inclui a ilha da Trindade, a 1.100 km.
  function bboxOf(geom) {
    const polys = geom.type === 'MultiPolygon' ? geom.coordinates : [geom.coordinates];
    const boxes = polys.map((poly) => {
      let b = [180, 90, -180, -90];
      for (const [x, y] of poly[0]) b = [Math.min(b[0], x), Math.min(b[1], y), Math.max(b[2], x), Math.max(b[3], y)];
      return b;
    });
    const area = (b) => (b[2] - b[0]) * (b[3] - b[1]);
    const main = boxes.reduce((a, b) => (area(b) > area(a) ? b : a));
    const near = (b) => b[0] < main[2] + 1 && b[2] > main[0] - 1 && b[1] < main[3] + 1 && b[3] > main[1] - 1;
    return boxes.filter(near)
      .reduce((a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])]);
  }

  // Cidade aparece pelo contorno preenchido; o pin fica só para a que não tem
  // contorno (senão ela sumiria do mapa).
  function cityPointsFC() {
    const shaped = new Set(S.cityShapes.features.map((f) => f.properties.id));
    return {
      type: 'FeatureCollection',
      features: S.visited.city.filter((p) => !shaped.has(String(p.id))).map((p) => ({
        type: 'Feature',
        properties: { id: String(p.id), name: p.name },
        geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
      })),
    };
  }
  const landmarksFC = () => ({
    type: 'FeatureCollection',
    features: S.visited.landmark.map((p) => ({ type: 'Feature', properties: { id: String(p.id), name: p.name }, geometry: { type: 'Point', coordinates: [p.lon, p.lat] } })),
  });
  const airportsFC = () => ({
    type: 'FeatureCollection',
    features: S.visited.airport.map((p) => ({ type: 'Feature', properties: { id: String(p.id), name: `${p.id} — ${p.name}` }, geometry: { type: 'Point', coordinates: [p.lon, p.lat] } })),
  });

  function icon(path, color) {
    const s = 26, k = 2, c = document.createElement('canvas');
    c.width = c.height = s * k;
    const g = c.getContext('2d');
    g.scale(k, k);
    g.translate(1, 1);
    const shape = new Path2D(path);
    g.lineJoin = 'round';
    g.lineWidth = 3;
    g.strokeStyle = '#fff';   // contorno branco para destacar sobre qualquer fundo
    g.stroke(shape);
    g.fillStyle = color;
    g.fill(shape, 'evenodd');
    return { width: s * k, height: s * k, data: g.getImageData(0, 0, s * k, s * k).data };
  }

  const mapReady = new Promise((res) => map.on('load', res));

  async function setupMap() {
    await mapReady;
    map.addImage('airport', icon(PLANE, C.airport), { pixelRatio: 2 });
    map.addImage('landmark', icon(PIN, C.landmark), { pixelRatio: 2 });
    map.addSource('admin', { type: 'vector', url: `pmtiles://${location.origin}/geo/world.pmtiles?v=${window.GEO_V}` });
    map.addSource('cities', { type: 'geojson', data: emptyFC });
    map.addSource('city-shapes', { type: 'geojson', data: emptyFC });
    map.addSource('airports', { type: 'geojson', data: emptyFC });
    map.addSource('landmarks', { type: 'geojson', data: emptyFC });

    const none = ['in', FID, ['literal', []]];
    map.addLayer({ id: 'land', type: 'fill', ...ADMIN('countries'), paint: { 'fill-color': C.land } });
    map.addLayer({ id: 'country-visited', type: 'fill', ...ADMIN('countries'), filter: none, paint: { 'fill-color': C.country } });
    map.addLayer({ id: 'state-hit', type: 'fill', ...ADMIN('states'), paint: { 'fill-opacity': 0 } });
    map.addLayer({ id: 'state-visited', type: 'fill', ...ADMIN('states'), filter: none, paint: { 'fill-color': C.state, 'fill-opacity': 0.92 } });
    map.addLayer({
      id: 'state-lines', type: 'line', ...ADMIN('states'),
      paint: { 'line-color': C.border, 'line-width': 0.5, 'line-opacity': ['interpolate', ['linear'], ['zoom'], 2, 0, 3.5, 0.8] },
    });
    map.addLayer({ id: 'country-lines', type: 'line', ...ADMIN('countries'), paint: { 'line-color': C.border, 'line-width': ['interpolate', ['linear'], ['zoom'], 1, 0.5, 6, 1.4] } });
    map.addLayer({ id: 'city-fill', type: 'fill', source: 'city-shapes', paint: { 'fill-color': C.city, 'fill-opacity': 0.85 } });
    map.addLayer({ id: 'city-outline', type: 'line', source: 'city-shapes', paint: { 'line-color': C.border, 'line-width': 1 } });
    map.addLayer({ id: 'country-hl', type: 'line', ...ADMIN('countries'), filter: none, paint: { 'line-color': '#2b2a27', 'line-width': 2 } });
    map.addLayer({ id: 'state-hl', type: 'line', ...ADMIN('states'), filter: none, paint: { 'line-color': '#2b2a27', 'line-width': 2 } });
    map.addLayer({
      id: 'cities', type: 'circle', source: 'cities',
      paint: {
        'circle-color': C.city, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1.5,
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 1, 3.5, 6, 5],
      },
    });
    map.addLayer({
      id: 'airports', type: 'symbol', source: 'airports',
      layout: { 'icon-image': 'airport', 'icon-allow-overlap': true, 'icon-size': ['interpolate', ['linear'], ['zoom'], 1, 0.7, 6, 1] },
    });
    // alfinete de longe; de perto some e entra a miniatura da foto (marcador HTML)
    map.addLayer({
      id: 'landmarks', type: 'symbol', source: 'landmarks',
      layout: { 'icon-image': 'landmark', 'icon-anchor': 'bottom', 'icon-allow-overlap': true, 'icon-size': ['interpolate', ['linear'], ['zoom'], 1, 0.75, 6, 1] },
      paint: { 'icon-opacity': ['interpolate', ['linear'], ['zoom'], THUMB_Z - 0.4, 1, THUMB_Z, 0] },
    });
    applyLayers();
    paintVisited();
  }

  const KIND_LAYERS = {
    country: ['country-visited'],
    state: ['state-visited', 'state-lines', 'state-hit'],
    city: ['city-fill', 'city-outline', 'cities'],
    airport: ['airports'],
    landmark: ['landmarks'],
  };

  function applyLayers() {
    $('#map').classList.toggle('lm-off', !S.layers.landmark);
    if (!map.getLayer('land')) return;
    const border = { 'state-lines': BORDERS.borders_state, 'city-outline': BORDERS.borders_city };
    for (const k of KINDS) {
      for (const id of KIND_LAYERS[k]) map.setLayoutProperty(id, 'visibility', S.layers[k] && border[id] !== false ? 'visible' : 'none');
    }
    map.setLayoutProperty('country-lines', 'visibility', BORDERS.borders_country ? 'visible' : 'none');
  }

  // Miniaturas "impressas" dos landmarks (marcadores HTML, aparecem a partir de THUMB_Z).
  const thumbs = new Map();
  function syncThumbs() {
    const want = new Map(S.visited.landmark.filter((p) => p.cover).map((p) => [String(p.id), p]));
    for (const [id, m] of thumbs) {
      const p = want.get(id);
      if (!p || m._cover !== p.cover) { m.remove(); thumbs.delete(id); }
    }
    for (const [id, p] of want) {
      const m = thumbs.get(id);
      if (m) { m.setLngLat([p.lon, p.lat]); continue; }
      // o MapLibre usa o transform do elemento externo; a inclinação fica no interno
      const div = el(`<div class="lm-wrap"><div class="lm-thumb" title="${esc(p.name)}"><img src="/photos/thumb/${p.cover}.jpg" alt=""></div></div>`);
      div.firstChild.style.setProperty('--tilt', `${((+id * 37) % 7) - 3}deg`);
      div.addEventListener('click', (e) => {
        e.stopPropagation();
        if (!S.placing) openPlace('landmark', id, { fly: false });
      });
      const mk = new maplibregl.Marker({ element: div }).setLngLat([p.lon, p.lat]).addTo(map);
      mk._cover = p.cover;
      thumbs.set(id, mk);
    }
  }
  const syncThumbZoom = () => $('#map').classList.toggle('lm-near', map.getZoom() >= THUMB_Z);
  map.on('zoom', syncThumbZoom);

  function paintVisited() {
    if (!map.getLayer('land')) return;
    const ids = (k) => ['in', FID, ['literal', S.visited[k].map((p) => String(p.id))]];
    map.setFilter('country-visited', ids('country'));
    map.setFilter('state-visited', ids('state'));
    map.getSource('cities').setData(cityPointsFC());
    map.getSource('city-shapes').setData(S.cityShapes);
    map.getSource('airports').setData(airportsFC());
    map.getSource('landmarks').setData(landmarksFC());
    syncThumbs();
    syncThumbZoom();
  }

  function highlight(kind, id) {
    if (!map.getLayer('land')) return;
    const f = (k) => ['==', FID, kind === k ? String(id) : '__none__'];
    map.setFilter('country-hl', f('country'));
    map.setFilter('state-hl', f('state'));
  }

  // Vista inicial, escolhida na configuração (SETTINGS.start_view):
  //   country: cidades visitadas em home_country (sem cidade lá, todas)
  //   all: todas as cidades visitadas
  //   last: onde o mapa estava da última vez neste aparelho
  //   fixed: centro e zoom gravados (start_fixed = "lon,lat,zoom")
  // Sem start_view: country se houver home_country, senão all.
  // Ao abrir o app (uma vez por sessão), o mapa começa de longe, sobre o
  // destino, e desce até a vista inicial; voltando de outra tela, vai direto.
  // Com "Pular animações" no perfil ou "reduzir movimento" no sistema, vai direto.
  const INTRO_MS = 2400;
  map.on('moveend', () => {
    if (S.intro) return;  // no meio da descida: não grava o "onde parei"
    const c = map.getCenter();
    store.set('last-view', { center: [c.lng, c.lat], zoom: map.getZoom() });
  });
  function homeView({ intro = false } = {}) {
    const show = (cam) => {
      if (!intro) return map.jumpTo(cam);
      S.intro = true;
      map.jumpTo({ center: cam.center, zoom: map.getMinZoom() });
      // desce quando o mundo de longe já estiver desenhado (ou depois de 2,5 s)
      let flying = false;
      const fly = () => {
        if (flying) return;
        flying = true;
        map.once('moveend', () => { S.intro = false; });
        map.flyTo({ ...cam, duration: INTRO_MS, essential: false });
      };
      map.once('idle', fly);
      setTimeout(fly, 2500);
    };
    const st = window.SETTINGS || {};
    const mode = st.start_view || (st.home_country ? 'country' : 'all');
    if (mode === 'fixed' && st.start_fixed) {
      const [lon, lat, zoom] = st.start_fixed.split(',').map(Number);
      return show({ center: [lon, lat], zoom });
    }
    const last = mode === 'last' && store.get('last-view', null);
    if (last) return show(last);
    const home = mode === 'country' && st.home_country;
    let cities = S.visited.city.filter((c) => home && c.country_id === home);
    if (!cities.length) cities = S.visited.city;
    if (!cities.length) return show({ center: [-30, 10], zoom: 1.6 });  // nada marcado: o mundo
    const shapes = new Map(S.cityShapes.features.map((f) => [f.properties.id, f]));
    const b = cities.map((c) => {
      const f = shapes.get(String(c.id));
      return f ? bboxOf(f.geometry) : [c.lon, c.lat, c.lon, c.lat];
    }).reduce((a, x) => [Math.min(a[0], x[0]), Math.min(a[1], x[1]), Math.max(a[2], x[2]), Math.max(a[3], x[3])]);
    const cam = map.cameraForBounds(b, { padding: isMobile() ? 30 : 60, maxZoom: 9 });
    if (cam) show({ center: cam.center, zoom: cam.zoom });
  }

  // Enquadra o lugar na parte do mapa que a gaveta não cobre.
  function focusPlace(p) {
    const pad = isMobile() ? 30 : 60;
    const cover = sheetCover();
    const padding = { top: pad, left: pad, right: pad, bottom: pad + cover };
    const offset = [0, -cover / 2];
    const shape = p.kind === 'city' && S.cityShapes.features.find((f) => f.properties.id === String(p.id));
    if (shape) {
      map.fitBounds(bboxOf(shape.geometry), { padding, maxZoom: 11, duration: 900 });
    } else if (p.kind === 'landmark') {
      if (p.lat != null) map.flyTo({ center: [p.lon, p.lat], zoom: Math.max(map.getZoom(), THUMB_Z + 0.5), duration: 900, offset });
    } else if (p.kind === 'city' || p.kind === 'airport') {
      map.flyTo({ center: [p.lon, p.lat], zoom: Math.max(map.getZoom(), 5), duration: 900, offset });
    } else if (p.bbox) {
      // bbox vem do servidor; quem cruza o antimeridiano já vem com leste > 180
      map.fitBounds(p.bbox, { padding, maxZoom: 9, duration: 900 });
    }
  }

  // Clique/hover: pega o mais específico entre as camadas ligadas. Se nada
  // visitado está embaixo, cai no estado (se ligado) ou no país.
  const PICK_ORDER = [
    ['landmarks', 'landmark'], ['cities', 'city'], ['airports', 'airport'], ['city-fill', 'city'],
    ['state-visited', 'state'], ['state-hit', 'state'],
    ['country-visited', 'country'], ['land', 'country'],
  ];

  function pick(point) {
    const box = [[point.x - 7, point.y - 7], [point.x + 7, point.y + 7]];
    const z = map.getZoom();
    for (const [layer, kind] of PICK_ORDER) {
      if (!map.getLayer(layer)) continue;
      if (layer !== 'land' && !S.layers[kind]) continue;
      if (layer === 'landmarks' && z >= THUMB_Z - 0.2) continue;  // de perto quem responde é a miniatura
      // estado não visitado só responde quando a divisa dele aparece (bordas de
      // estado ligadas e perto o bastante); senão, quem responde é o país
      if (layer === 'state-hit' && (!BORDERS.borders_state || z < 2.5)) continue;
      const q = layer === 'cities' || layer === 'airports' || layer === 'landmarks' ? box : point;
      const f = map.queryRenderedFeatures(q, { layers: [layer] })[0];
      if (!f) continue;
      if (kind !== 'state' && kind !== 'country') return { kind, id: f.properties.id, name: f.properties.name };
      const id = fid(f);
      return { kind, id, name: NAMES[kind][id] || f.properties.name };
    }
    return null;
  }

  const tooltip = $('#tooltip');
  map.on('mousemove', (e) => {
    if (S.view.type !== 'none' && !S.placing) return;  // gaveta aberta: mapa travado
    const hit = pick(e.point);
    map.getCanvas().style.cursor = hit ? 'pointer' : '';
    if (!hit) { tooltip.hidden = true; return; }
    tooltip.textContent = hit.name;
    tooltip.style.left = `${e.originalEvent.clientX + 12}px`;
    tooltip.style.top = `${e.originalEvent.clientY + 12}px`;
    tooltip.hidden = false;
  });
  map.on('mouseout', () => { tooltip.hidden = true; });

  map.on('click', (e) => {
    tooltip.hidden = true;
    if (e.originalEvent.target.closest?.('.lm-thumb')) return;
    if (S.placing) return S.placing.move(e.lngLat);  // formulário do landmark: toque posiciona
    const hit = pick(e.point);
    // não move o mapa: quem clicou já está olhando para o lugar
    if (hit) openPlace(hit.kind, hit.id, { point: e.lngLat, fly: false });
  });


  // ------------------------------------------------------------------ raspagem
  // Lugar que passa a ser visitado (cidade, estado, país) não ganha a cor de uma
  // vez: um retrato do mapa de antes, recortado no formato do lugar, vira a
  // película, raspada em zigue-zague como com uma moeda, soltando lascas.
  const SCRATCH_KINDS = ['country', 'state', 'city'];
  const SCRATCH_MS = 5000;   // duração da raspagem
  // sem animação: "Pular animações" no perfil (Configurações) ou "reduzir movimento" no sistema
  const reducedMotion = () => !!window.PREFS?.skip_animations || window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const scratchCv = el('<canvas class="scratch" aria-hidden="true"></canvas>');
  scratchCv.hidden = true;
  $('main').append(scratchCv);
  let scratchRun = 0;

  // Retrato do mapa como está: lido no próprio evento de render, antes de o
  // navegador descartar o buffer (sem preserveDrawingBuffer).
  function snapshotMap() {
    return new Promise((res) => {
      map.once('render', () => {
        const src = map.getCanvas();
        const c = document.createElement('canvas');
        c.width = src.width;
        c.height = src.height;
        c.getContext('2d').drawImage(src, 0, 0);
        res(c);
      });
      map.triggerRepaint();
    });
  }

  const keyOf = (kind, id) => `${kind}:${id}`;
  function newlyVisited(prev, visited) {
    const had = new Set(SCRATCH_KINDS.flatMap((k) => prev[k].map((p) => keyOf(k, p.id))));
    return SCRATCH_KINDS.filter((k) => S.layers[k])
      .flatMap((k) => visited[k].filter((p) => !had.has(keyOf(k, p.id))).map((p) => ({ kind: k, id: String(p.id), p })));
  }

  // Contorno do lugar na tela (px). Cidade: o contorno guardado; estado/país:
  // os pedaços dos tiles carregados (só o que está na tela importa).
  function screenShape(kind, id) {
    let geoms, rule = 'nonzero';
    if (kind === 'city') {
      const f = S.cityShapes.features.find((x) => x.properties.id === id);
      if (!f) return null;  // cidade sem contorno: fica só o pin
      geoms = [f.geometry];
      rule = 'evenodd';
    } else {
      geoms = map.querySourceFeatures('admin', { sourceLayer: kind === 'state' ? 'states' : 'countries', filter: ['==', FID, id] })
        .map((f) => f.geometry);
    }
    const path = new Path2D();
    let box = [Infinity, Infinity, -Infinity, -Infinity];
    for (const g of geoms) {
      const polys = g.type === 'MultiPolygon' ? g.coordinates : g.type === 'Polygon' ? [g.coordinates] : [];
      for (const ring of polys.flat()) {
        ring.forEach((c, i) => {
          const { x, y } = map.project(c);
          if (i) path.lineTo(x, y); else path.moveTo(x, y);
          box = [Math.min(box[0], x), Math.min(box[1], y), Math.max(box[2], x), Math.max(box[3], y)];
        });
        path.closePath();
      }
    }
    return box[0] < Infinity ? { path, rule, box } : null;
  }

  // Raspa os lugares (já pintados no mapa) com a película do retrato de antes.
  // Resolve quando termina, ou quando é interrompida (mapa mexeu, pulou).
  function scratchReveal(fresh, snap) {
    return new Promise((done) => scratchRun_(fresh, snap, done));
  }
  function scratchRun_(fresh, snap, done) {
    const shapes = fresh.map((x) => screenShape(x.kind, x.id)).filter(Boolean);
    if (!shapes.length) return done();
    const W = map.getCanvas().clientWidth, H = map.getCanvas().clientHeight;
    const dpr = snap.width / Math.max(1, W);
    // área a raspar: a união dos contornos, cortada pela tela
    const box = shapes.reduce((a, s) => [Math.min(a[0], s.box[0]), Math.min(a[1], s.box[1]), Math.max(a[2], s.box[2]), Math.max(a[3], s.box[3])],
      [Infinity, Infinity, -Infinity, -Infinity]);
    const [x0, y0, x1, y1] = [Math.max(0, box[0]), Math.max(0, box[1]), Math.min(W, box[2]), Math.min(H, box[3])];
    if (x1 - x0 < 2 || y1 - y0 < 2) return done();

    // película: o mapa de antes, só dentro dos contornos
    const film = document.createElement('canvas');
    film.width = scratchCv.width = Math.round(W * dpr);
    film.height = scratchCv.height = Math.round(H * dpr);
    const fx = film.getContext('2d', { willReadFrequently: true });
    fx.setTransform(dpr, 0, 0, dpr, 0, 0);
    for (const s of shapes) {
      fx.save();
      fx.clip(s.path, s.rule);
      fx.drawImage(snap, 0, 0, W, H);
      fx.restore();
    }

    // trajeto da "moeda": zigue-zague de cima para baixo cobrindo a área
    const bw = x1 - x0, bh = y1 - y0;
    const brush = Math.max(8, Math.min(34, Math.min(bw, bh) / 4));
    const step = brush * 0.8;
    const pts = [];
    for (let y = y0 - brush / 2, i = 0; y <= y1 + brush; y += step / 2, i++) {
      const jitter = (Math.random() - 0.5) * brush * 0.5;
      pts.push([i % 2 ? x1 + brush / 3 + jitter : x0 - brush / 3 + jitter, y + (Math.random() - 0.5) * step * 0.3]);
    }
    const segs = pts.slice(1).map((p, i) => ({ a: pts[i], b: p, len: Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]) }));
    const total = segs.reduce((a, s) => a + s.len, 0);
    const duration = SCRATCH_MS;

    const ctx = scratchCv.getContext('2d');
    const run = ++scratchRun;
    const flakes = [];
    let drawn = 0, t0 = null, last = pts[0];
    scratchCv.classList.remove('fade');
    scratchCv.hidden = false;
    const abort = () => { if (run === scratchRun) { scratchRun++; scratchCv.hidden = true; } done(); };
    map.once('movestart', abort);

    const pointAt = (d) => {
      for (const s of segs) {
        if (d <= s.len) { const k = d / s.len; return [s.a[0] + (s.b[0] - s.a[0]) * k, s.a[1] + (s.b[1] - s.a[1]) * k]; }
        d -= s.len;
      }
      return pts[pts.length - 1];
    };

    function frame(t) {
      if (run !== scratchRun) return done();
      t0 ??= t;
      const k = Math.min(1, (t - t0) / duration);
      const target = total * k;  // ritmo constante, como a mão raspando
      // raspa do ponto onde parou até o novo, em passos curtos (traço contínuo).
      // Um traço central e dois finos tremidos dos lados: a borda fica irregular,
      // como a de uma moeda raspando, e não reta.
      const head = pointAt(target);
      const trail = [last];
      for (let d = drawn + brush / 3; d < target; d += brush / 3) trail.push(pointAt(d));
      trail.push(head);
      fx.save();
      fx.globalCompositeOperation = 'destination-out';
      fx.lineCap = fx.lineJoin = 'round';
      for (const [off, w] of [[0, 0.75], [0.36, 0.3], [-0.36, 0.3]]) {
        fx.lineWidth = brush * w * (0.8 + Math.random() * 0.4);
        fx.beginPath();
        trail.forEach(([px, py], i) => {
          const j = off ? (Math.random() - 0.5) * brush * 0.25 : 0;
          const qx = px, qy = py + off * brush + j;
          if (i) fx.lineTo(qx, qy); else fx.moveTo(qx, qy);
        });
        fx.stroke();
      }
      fx.restore();
      // lascas: pedacinhos da película na cor de onde a moeda passou
      if (k < 1 && target > drawn) {
        const [hx, hy] = head;
        const px = fx.getImageData(Math.round(hx * dpr), Math.round(hy * dpr), 1, 1).data;
        const color = px[3] ? `rgb(${px[0]},${px[1]},${px[2]})` : null;
        for (let i = 0; i < 3 && color; i++) {
          flakes.push({ x: hx + (Math.random() - 0.5) * brush, y: hy + (Math.random() - 0.5) * brush, vx: (Math.random() - 0.5) * 2.4,
            vy: -Math.random() * 1.6, r: Math.random() * Math.PI, vr: (Math.random() - 0.5) * 0.3, s: 2 + Math.random() * 3.5, life: 1, color });
        }
      }
      drawn = target;
      last = head;  // (o trail começa daqui no próximo quadro)

      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, scratchCv.width, scratchCv.height);
      ctx.drawImage(film, 0, 0);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      for (const f of flakes) {
        f.x += f.vx; f.y += f.vy; f.vy += 0.18; f.r += f.vr; f.life -= 0.022;
        if (f.life <= 0) continue;
        ctx.save();
        ctx.globalAlpha = Math.min(1, f.life * 1.5);
        ctx.translate(f.x, f.y);
        ctx.rotate(f.r);
        ctx.fillStyle = f.color;
        ctx.fillRect(-f.s, -f.s / 2, f.s * 2, f.s);
        ctx.restore();
      }
      for (let i = flakes.length - 1; i >= 0; i--) if (flakes[i].life <= 0) flakes.splice(i, 1);

      if (k < 1 || flakes.length) return requestAnimationFrame(frame);
      // sobra de película nas beiradas (traço não passou): some num fade
      scratchCv.classList.add('fade');
      setTimeout(() => {
        map.off('movestart', abort);
        if (run === scratchRun) scratchCv.hidden = true;
        done();
      }, 350);
    }
    requestAnimationFrame(frame);
  }

  // ------------------------------------------------------------------ cena ao marcar
  // A marcação já foi gravada; a cena só mostra. Os lugares novos entram um a um,
  // do maior para o menor (país → estado → cidade): a gaveta sai, o mapa enquadra
  // o lugar e a película é raspada. No fim a gaveta volta, com a cidade enquadrada
  // acima dela. Tocar na tela pula o resto.
  const SCENE_ORDER = { country: 0, state: 1, city: 2 };
  const SCENE_MAX_ZOOM = { country: 6, state: 8, city: 11 };
  const skipLayer = $('#skip');
  const wait = (ms) => new Promise((res) => setTimeout(res, ms));

  async function placeBox(it, shapes) {
    if (it.kind === 'city') {
      const f = shapes.features.find((x) => x.properties.id === it.id);
      return f ? bboxOf(f.geometry) : [it.p.lon, it.p.lat, it.p.lon, it.p.lat];
    }
    const d = await api(`/api/place/${it.kind}/${encodeURIComponent(it.id)}`).catch(() => null);
    return d?.bbox || null;
  }

  async function frameOn(box, kind, bottom) {
    const pad = isMobile() ? 30 : 60;
    const moved = new Promise((res) => map.once('moveend', res));
    map.fitBounds(box, { padding: { top: pad, left: pad, right: pad, bottom: pad + bottom }, maxZoom: SCENE_MAX_ZOOM[kind], duration: 1200 });
    await Promise.race([moved, wait(2500)]);  // já enquadrado: pode não haver moveend
    // espera os tiles da nova área (com limite, para não travar)
    await Promise.race([new Promise((res) => map.once('idle', res)), wait(1500)]);
  }

  // Enquadramento de um grupo da cena em lote: as cidades novas (país e estado
  // inteiros puxariam o zoom para longe demais); sem cidades, todos.
  async function groupBox(group, shapes) {
    const cities = group.filter((x) => x.kind === 'city');
    const boxes = (await Promise.all((cities.length ? cities : group).map((it) => placeBox(it, shapes)))).filter(Boolean);
    if (!boxes.length) return null;
    return boxes.reduce((a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])]);
  }

  async function playScene(fresh, visited, shapes, { batch = false } = {}) {
    const steps = [...fresh].sort((a, b) => SCENE_ORDER[a.kind] - SCENE_ORDER[b.kind]);
    // um a um (país → estado → cidade) ou, em lote, tudo numa raspagem só
    const groups = batch ? [steps] : steps.map((it) => [it]);
    const pending = new Set(steps.map((x) => keyOf(x.kind, x.id)));
    // pinta só o que já entrou na cena
    const stage = () => {
      S.visited = Object.fromEntries(KINDS.map((k) => [k, visited[k].filter((p) => !pending.has(keyOf(k, String(p.id))))]));
      S.cityShapes = { ...shapes, features: shapes.features.filter((f) => !pending.has(keyOf('city', f.properties.id))) };
      paintVisited();
    };
    const hadSheet = sheet.classList.contains('open');
    const sheetH = hadSheet ? Math.min(sheet.offsetHeight, window.innerHeight * 0.6) : 0;
    sheet.classList.remove('open');
    scrim.classList.remove('on');
    let skipped = false;
    const skip = new Promise((res) => { skipLayer.onclick = () => { skipped = true; res(); }; });
    skipLayer.hidden = false;
    stage();
    try {
      for (const [i, group] of groups.entries()) {
        const box = await Promise.race([groupBox(group, shapes), skip]);
        if (skipped) break;
        // o último lugar fica acima de onde a gaveta vai voltar
        const kind = batch ? 'state' : group[0].kind;
        if (box) await Promise.race([frameOn(box, kind, i === groups.length - 1 ? sheetH : 0), skip]);
        if (skipped) break;
        const snap = await snapshotMap();
        for (const it of group) pending.delete(keyOf(it.kind, it.id));
        stage();
        await Promise.race([scratchReveal(group, snap), skip]);
        if (skipped) break;
      }
    } finally {
      if (skipped) {
        map.stop();
        scratchRun++;
        scratchCv.hidden = true;
      }
      skipLayer.hidden = true;
      skipLayer.onclick = null;
      S.visited = visited;
      S.cityShapes = shapes;
      paintVisited();
      if (hadSheet && S.view.type !== 'none') {
        setSize(S.view.size || 'peek', { instant: true });  // a altura foi limpa ao sair da tela
        openSheet();
      }
    }
  }

  // ------------------------------------------------------------------ dados
  // Contornos de cidade: guardados aqui; só os de cidades ainda não pedidas vão
  // ao servidor (desmarcar não baixa nada, marcar baixa um).
  const shapeCache = new Map();   // id → Feature
  const shapeAsked = new Set();   // ids já pedidos (cidade sem contorno não é pedida de novo)
  async function loadCityShapes(cityIds) {
    const missing = cityIds.filter((id) => !shapeAsked.has(id));
    if (missing.length) {
      // primeira carga: todas de uma vez, sem lista de ids
      const fc = await api(shapeAsked.size ? `/api/city-shapes?ids=${missing.join(',')}` : '/api/city-shapes');
      for (const f of fc.features) shapeCache.set(f.properties.id, f);
      // ainda calculando no servidor (lista de cidades): as sem contorno são pedidas de novo
      for (const id of missing) if (shapeCache.has(id) || !fc.pending) shapeAsked.add(id);
      if (fc.pending) pollShapes();
    }
    return { type: 'FeatureCollection', features: cityIds.map((id) => shapeCache.get(id)).filter(Boolean) };
  }

  // Enquanto o servidor calcula contornos (no modo leve, 1 por segundo), o mapa
  // vai buscando os prontos: a cidade sai do pin e ganha a cor.
  let shapePoll = null;
  function pollShapes() {
    if (shapePoll) return;
    shapePoll = setTimeout(async () => {
      shapePoll = null;
      if (!skipLayer.hidden) return pollShapes();  // cena em andamento: depois
      const before = shapeCache.size;
      const shapes = await loadCityShapes(S.visited.city.map((c) => String(c.id))).catch(() => null);
      if (shapes && shapeCache.size !== before) {
        S.cityShapes = shapes;
        paintVisited();
      }
    }, 4000);
  }

  // batch: muitas de uma vez (lista de cidades): uma cena só, com tudo junto
  async function loadVisited({ batch = false } = {}) {
    const prev = S.loaded ? S.visited : null;
    const visited = await api('/api/visited');
    const shapes = await loadCityShapes(visited.city.map((c) => String(c.id)));
    const fresh = prev && map.getLayer('land') && !reducedMotion() ? newlyVisited(prev, visited) : [];
    S.loaded = true;
    for (const k of KINDS) document.querySelector(`[data-count="${k}"]`).textContent = visited[k].length;
    if (fresh.length) return playScene(fresh, visited, shapes, { batch });
    [S.visited, S.cityShapes] = [visited, shapes];
    paintVisited();
  }

  async function toggleVisit(kind, id, on, hasPhotos = 0, hasDates = 0) {
    if (on) {
      await api('/api/visits', json('POST', { kind, id }));
    } else {
      if (hasPhotos && !confirm(t('Desmarcar também remove {n} foto(s) deste lugar. Continuar?', { n: hasPhotos }))) return false;
      if (!hasPhotos && hasDates && !confirm(t('Desmarcar também apaga as datas de visita deste lugar. Continuar?'))) return false;
      await api(`/api/visits/${kind}/${encodeURIComponent(id)}`, { method: 'DELETE' });
    }
    await loadVisited();
    return true;
  }

  // ------------------------------------------------------------------ gaveta
  // Uma gaveta só, que sobe de baixo por cima da barra de menu. Telas: add (as
  // opções do +), add-city / add-airport / add-photo (busca), place (o lugar) e landmark-form.
  // Aberta, ela trava o mapa (véu por cima) e tocar fora recolhe. A exceção é o
  // formulário do landmark: fica mais baixa e sem véu, porque usa o mapa.
  const sheet = $('#sheet');
  const body = $('#sheet-body');
  const scrim = $('#scrim');

  function openSheet() {
    const peek = S.view.type === 'landmark-form';
    sheet.classList.toggle('peek', peek);
    sheet.classList.add('open');
    scrim.classList.toggle('on', !peek);
    document.body.classList.add('sheet-open');
    tooltip.hidden = true;
  }
  function closeSheet() {
    stopPlacing();
    S.view = { type: 'none' };
    S.history = [];
    // desce com a altura que tem; ela é limpa quando sai da tela (transitionend)
    sheet.classList.remove('open');
    scrim.classList.remove('on');
    document.body.classList.remove('sheet-open');
    highlight(null);
  }
  scrim.addEventListener('click', closeSheet);

  // Quanto da parte de baixo do mapa a gaveta cobre (para enquadrar acima dela).
  // Em peek é a altura da foto (a gaveta pode estar no meio da transição).
  const sheetCover = () => {
    if (!sheet.classList.contains('open')) return 0;
    const h = sheet.dataset.size === 'peek' ? peekHeight() : sheet.offsetHeight;
    return Math.min(h, window.innerHeight * 0.6);
  };

  function go(view) {
    if (S.view.type !== 'none') S.history.push(S.view);
    S.view = view;
    render();
  }
  function back() {
    S.view = S.history.pop() || { type: 'none' };
    if (S.view.type === 'place') return openPlace(S.view.kind, S.view.id, { push: false, fly: false, point: S.view.point, size: S.view.size });
    highlight(null);
    render();
  }

  // Com foto no topo, a gaveta tem dois tamanhos: peek (só a foto) e full (tudo,
  // até 85% da tela). Abre em peek; arrastar para cima ou tocar na alça expande.
  const peekHeight = () => $('.hero', body)?.offsetHeight || 0;
  // instant: sem animar a altura (a gaveta está fechada e vai subir já no
  // tamanho certo; animar daria o efeito de abrir cheia e depois encolher).
  function setSize(size, { instant = false } = {}) {
    if (instant) sheet.classList.add('dragging');  // .dragging = sem transição
    if (!sheet.classList.contains('has-hero')) {
      sheet.style.height = '';
      delete sheet.dataset.size;
    } else {
      S.view.size = size;
      sheet.dataset.size = size;
      const to = size === 'peek' ? peekHeight() : Math.min(body.scrollHeight, window.innerHeight * 0.85);
      // altura fixa (de onde está para onde vai) para a transição funcionar
      if (!instant) {
        sheet.style.height = `${sheet.getBoundingClientRect().height}px`;
        void sheet.offsetHeight;
      }
      sheet.style.height = `${to}px`;
    }
    if (instant) {
      void sheet.offsetHeight;
      sheet.classList.remove('dragging');
    }
  }
  sheet.addEventListener('transitionend', (e) => {
    if (e.target !== sheet) return;
    // em full, terminada a transição, a altura volta a seguir o conteúdo (fotos carregando)
    if (e.propertyName === 'height' && sheet.dataset.size === 'full') sheet.style.height = '';
    // fechou (saiu da tela): limpa a altura para a próxima abertura
    if (e.propertyName === 'transform' && !sheet.classList.contains('open')) {
      sheet.style.height = '';
      delete sheet.dataset.size;
    }
  });

  function render() {
    const v = S.view;
    if (v.type !== 'landmark-form') stopPlacing();
    if (v.type === 'none') return closeSheet();
    body.innerHTML = '';
    sheet.classList.remove('has-hero');
    if (v.type === 'landmark-form') renderLandmarkForm(v);
    else if (v.type === 'place') renderPlace(v.data, v.point);
    else if (v.type === 'add') renderAdd();
    else if (v.type === 'add-list') renderCityList();
    else renderSearch(v);
    // abrindo do zero: tamanho certo antes de subir; já aberta: anima a troca
    setSize(v.size || 'peek', { instant: !sheet.classList.contains('open') });
    openSheet();
    body.scrollTop = 0;
  }

  // Cabeçalho da gaveta: "‹" volta (quando há para onde) e "×" fecha.
  function sheetHead(inner, { onClose = closeSheet, canBack = true, onPhoto = false } = {}) {
    const hasBack = canBack && S.history.length > 0;
    const head = el(`<div class="place-head${hasBack ? ' has-back' : ''}${onPhoto ? ' on-photo' : ''}">
      ${hasBack ? `<button class="back" title="${t('Voltar')}" aria-label="${t('Voltar')}">‹</button>` : ''}
      <button class="close" title="${t('Fechar (Esc)')}" aria-label="${t('Fechar')}">×</button>
      ${inner}
    </div>`);
    $('.close', head).addEventListener('click', onClose);
    $('.back', head)?.addEventListener('click', back);
    return head;
  }

  // ------------------------------------------------------------------ adicionar
  const LIST_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m3.5 6 1.5 1.5L8 4.5M3.5 12.5 5 14l3-3M3.5 19 5 20.5l3-3M11 6h10M11 12.5h10M11 19h10"/></svg>';
  const CAMERA_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M4 7.5h3.2L9 5h6l1.8 2.5H20a1 1 0 0 1 1 1V19a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8.5a1 1 0 0 1 1-1z"/><circle cx="12" cy="13.5" r="3.6"/></svg>';

  function renderAdd() {
    body.append(sheetHead(`<h2>${t('Adicionar')}</h2>`));
    const opt = (key, ico, title, sub) => `<li><button data-add="${key}">
      <span class="ico">${ico}</span><span><b>${title}</b><small>${sub}</small></span></button></li>`;
    const ul = el(`<ul class="add-list">
      ${opt('city', '<i class="dot city"></i>', t('Cidade'), t('Busque e finque a bandeira. Marca o estado e o país junto.'))}
      ${opt('list', LIST_SVG, t('Lista de cidades'), t('Várias de uma vez: escolha o país e toque nas que você conhece.'))}
      ${opt('airport', '<i class="dot airport"></i>', t('Aeroporto'), t('Busque pelo nome, pela cidade ou pelo código (GRU) e finque a bandeira.'))}
      ${opt('landmark', '<i class="dot landmark"></i>', t('Monumento'), t('A partir de uma foto; a posição vem do GPS dela.'))}
      ${opt('photo', CAMERA_SVG, t('Foto'), t('Escolha o lugar e depois as fotos.'))}
    </ul>`);
    const lmFile = el('<input type="file" accept="image/*,.heic,.heif" multiple hidden>');
    ul.append(lmFile);
    $('[data-add="city"]', ul).addEventListener('click', () => go({ type: 'add-city', q: '' }));
    $('[data-add="list"]', ul).addEventListener('click', () => go({ type: 'add-list' }));
    $('[data-add="airport"]', ul).addEventListener('click', () => go({ type: 'add-airport', q: '' }));
    $('[data-add="photo"]', ul).addEventListener('click', () => go({ type: 'add-photo', q: '' }));
    const lmBtn = $('[data-add="landmark"]', ul);
    lmBtn.addEventListener('click', () => lmFile.click());
    lmFile.addEventListener('change', () => {
      if (!lmFile.files.length) return;
      $('small', lmBtn).textContent = t('Enviando {n}…', { n: lmFile.files.length });
      lmBtn.disabled = true;
      newLandmark(lmFile.files);
    });
    body.append(ul);
  }

  // Lista de cidades (static/citypicker.js): marcadas, a gaveta fecha e as
  // novas são raspadas numa cena só.
  function renderCityList() {
    body.append(sheetHead(`<h2>${t('Lista de cidades')}</h2>`));
    const box = el('<div class="sheet-picker"></div>');
    body.append(box);
    window.SM.cityPicker(box, {
      onDone: async (n) => {
        closeSheet();
        await loadVisited({ batch: true });
        if (n) toast(t(n === 1 ? '{n} cidade marcada. Os contornos que faltam aparecem aos poucos.' : '{n} cidades marcadas. Os contornos que faltam aparecem aos poucos.', { n }));
      },
    });
  }

  // Busca dentro do "adicionar": cidade (com a bandeira para marcar) ou o lugar
  // que vai receber as fotos (tocar abre a escolha dos arquivos).
  const SEARCH = {
    'add-city': { title: t('Adicionar cidade'), kinds: ['city'], placeholder: t('Buscar cidade…') },
    'add-airport': { title: t('Adicionar aeroporto'), kinds: ['airport'], placeholder: t('Nome, cidade ou código (GRU)…') },
    'add-photo': {
      title: t('Adicionar foto'), kinds: KINDS, placeholder: t('Em qual lugar? País, estado, cidade, aeroporto…'),
      hint: t('Toque no lugar para escolher as fotos. Enviar foto para um lugar não visitado já marca o lugar.'),
    },
  };
  let searchTimer, searchSeq = 0;
  function renderSearch(v) {
    const cfg = SEARCH[v.type];
    body.append(sheetHead(`<h2>${cfg.title}</h2>`));
    const wrap = el(`<div class="search"><input type="search" placeholder="${cfg.placeholder}" autocomplete="off"></div>`);
    const input = $('input', wrap);
    const out = el('<div class="results"></div>');
    body.append(wrap, out);
    input.value = v.q;
    const run = async () => {
      v.q = input.value;
      const q = v.q.trim();
      const n = ++searchSeq;
      if (q.length < 2) { out.innerHTML = cfg.hint ? `<p class="hint">${cfg.hint}</p>` : ''; return; }
      const items = await api(`/api/search?kind=${cfg.kinds.join(',')}&q=${encodeURIComponent(q)}`);
      if (n !== searchSeq || !out.isConnected) return;
      out.innerHTML = '';
      if (!items.length) out.append(el(`<p class="empty">${t('Nada encontrado.')}</p>`));
      else out.append(v.type === 'add-photo' ? photoTargets(items) : resultList(items));
    };
    input.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(run, 200); });
    run();
    setTimeout(() => input.focus(), 60);
  }

  // Lista de resultados com a bandeira "estive aqui".
  function resultList(items) {
    const ul = el('<ul class="list"></ul>');
    for (const it of items) {
      const li = el(`<li>
        <i class="dot ${it.kind}"></i>
        <div class="name">${esc(it.name)}<small>${esc(it.sub || KIND_LABEL[it.kind])}</small></div>
        ${it.kind === 'landmark' ? '' : `<button class="flag-btn">${FLAG_SVG}</button>`}
      </li>`);
      li.addEventListener('click', () => openPlace(it.kind, it.id));
      const flag = $('.flag-btn', li);
      const paint = () => {
        flag.classList.toggle('on', !!it.visited);
        flag.title = it.visited ? t('Visitado — clique para desmarcar') : t('Estive aqui');
      };
      flag?.addEventListener('click', async (ev) => {
        ev.stopPropagation();
        if (flag.classList.contains('busy')) return;
        if (it.visited && !it.explicit) return toast(IMPLIED_MSG[it.kind]);
        flag.classList.add('busy');  // cidade nova calcula o contorno (~1-3 s)
        try {
          const ok = await toggleVisit(it.kind, it.id, !it.explicit);
          if (ok === false) return;
          it.explicit = !it.explicit;
          it.visited = isVisited(it.kind, it.id);
          if (it.visited && !it.explicit) toast(IMPLIED_MSG[it.kind]);
          paint();
        } finally {
          flag.classList.remove('busy');
        }
      });
      if (flag) paint();
      ul.append(li);
    }
    return ul;
  }

  function photoTargets(items) {
    const ul = el('<ul class="list"></ul>');
    for (const it of items) {
      const li = el(`<li>
        <i class="dot ${it.kind}"></i>
        <div class="name">${esc(it.name)}<small>${esc(it.sub || KIND_LABEL[it.kind])}</small></div>
        <span class="meta">📷</span>
        <input type="file" accept="image/*,.heic,.heif" multiple hidden>
      </li>`);
      const file = $('input', li);
      li.addEventListener('click', () => file.click());
      file.addEventListener('click', (e) => e.stopPropagation());
      file.addEventListener('change', async () => {
        if (!file.files.length) return;
        $('.meta', li).textContent = t('Enviando {n}…', { n: file.files.length });
        await uploadPhotos(it.kind, it.id, file.files);
        openPlace(it.kind, it.id);
      });
      ul.append(li);
    }
    return ul;
  }

  async function uploadPhotos(kind, id, files) {
    const fd = new FormData();
    for (const f of files) fd.append('photos', f);
    try {
      const r = await fetch(`/api/place/${kind}/${encodeURIComponent(id)}/photos`, { method: 'POST', body: fd });
      const res = await r.json();
      if (res.errors?.length) alert(`${t('Algumas fotos falharam:')}\n${res.errors.join('\n')}`);
    } catch (err) {
      alert(t('Falha no envio: {erro}', { erro: err.message }));
    }
    await loadVisited();
  }

  // ------------------------------------------------------------------ lugar
  async function openPlace(kind, id, { push = true, fly = true, point = null, size = 'peek' } = {}) {
    const data = await api(`/api/place/${kind}/${encodeURIComponent(id)}`);
    const view = { type: 'place', kind, id, data, point, size };
    if (push) go(view);
    else { S.view = view; render(); }
    highlight(kind, id);
    if (fly) focusPlace(data);
  }

  function renderPlace(p, point) {
    const crumbs = p.crumbs.map((c) => `<a data-kind="${c.kind}" data-id="${esc(c.id)}">${esc(c.name)}</a>`).join(' · ');
    const title = p.kind === 'airport' ? `${p.id} — ${p.name}` : p.name;
    const status = p.kind === 'landmark' ? '' : p.visited ? t('Visitado ✓') : t('Ainda não visitado');
    const all = [...p.photos, ...p.groups.flatMap((g) => g.photos)];

    // Com foto, a mais recente horizontal (vertical só se não houver; na cidade
    // entram as dos landmarks/aeroportos, no estado/país as das cidades) vira o
    // topo da gaveta, de ponta a ponta, com o nome sobre um desfoque embaixo.
    const head = sheetHead(`
      <div class="kind-label"><i class="dot ${p.kind}"></i>${KIND_LABEL[p.kind]}</div>
      <h2>${esc(title)}</h2>
      ${crumbs ? `<div class="crumbs">${crumbs}</div>` : ''}`, { onPhoto: all.length > 0 });
    if (all.length) {
      const cover = all.find((ph) => ph.width > ph.height) || all[0];
      const hero = el(`<div class="hero" data-drag><img src="${cover.url}" alt=""><div class="hero-fade"></div></div>`);
      hero.append(head);
      hero.onTap = (e) => { if (!e.target.closest('button, a')) lightbox.open(all, all.indexOf(cover), lbOpts); };
      body.append(hero);
    } else {
      body.append(head);
    }
    sheet.classList.toggle('has-hero', all.length > 0);
    if (status) body.append(el(`<div class="status">${status}</div>`));

    const visitBtn = p.kind === 'landmark' ? ''
      : p.visited ? `<button class="btn secondary" data-act="unmark">${t('Desmarcar')}</button>`
      : `<button class="btn flag" data-act="mark">${FLAG_SVG}${t('Estive aqui')}</button>`;
    const lmBtns = p.kind !== 'landmark' ? ''
      : `<button class="btn secondary" data-act="edit">${t('Editar')}</button><button class="btn secondary" data-act="delete">${t('Apagar')}</button>`;
    const actions = el(`<div class="actions">
      ${visitBtn}
      <button class="btn secondary" data-act="upload">📷 ${t('Adicionar fotos')}</button>
      ${lmBtns}
      <input type="file" accept="image/*,.heic,.heif" multiple hidden>
    </div>`);
    body.append(actions);
    if (p.visited || p.kind === 'landmark') body.append(visitDates(p, () => reopen()));

    // Clicou num ponto do mapa: oferece cidades/aeroportos ali perto para marcar.
    if (point && (p.kind === 'state' || p.kind === 'country')) {
      const slot = el('<div class="nearby"></div>');
      body.append(slot);
      loadNearby(slot, point);
    }

    // Fotos: as do lugar (na cidade, também as dos landmarks dela) e, no
    // estado/país, um grupo por cidade contida. As setas do lightbox passam por todas.
    const isOwn = (ph) => ph.kind === p.kind && String(ph.ref_id) === String(p.id);
    const lbOpts = {
      isOwn,
      openPlace: (ph) => openPlace(ph.kind, ph.ref_id),
      onChange: async (res) => {
        await loadVisited();
        if (res?.place_deleted && p.kind === 'landmark') return closeSheet();  // era a última foto
        reopen();
      },
    };
    // nome do lugar na margem só quando não é o do lugar aberto nem o do grupo
    const grid = (photos, owner = null) => {
      const g = el('<div class="prints"></div>');
      for (const ph of photos) {
        const mine = isOwn(ph) || (owner && ph.kind === owner.kind && String(ph.ref_id) === String(owner.id));
        g.append(print(ph, { withLabel: !mine, onClick: () => lightbox.open(all, all.indexOf(ph), lbOpts) }));
      }
      return g;
    };
    body.append(el(`<p class="group-title">${t('Fotos')}</p>`));
    if (p.photos.length) body.append(grid(p.photos));
    else body.append(el(`<p class="empty">${p.groups.length
      ? (p.kind === 'state' ? t('Nenhuma foto marcada direto neste estado.') : t('Nenhuma foto marcada direto neste país.'))
      : t('Nenhuma foto ainda. A data sai do próprio arquivo (EXIF) quando existir.')}</p>`));
    for (const g of p.groups) {
      const n = g.photos.length;
      const head = el(`<p class="photo-group"><a><i class="dot ${g.place.kind}"></i>${esc(g.title)}</a><small>${t(n === 1 ? '{n} foto' : '{n} fotos', { n })}</small></p>`);
      $('a', head).addEventListener('click', () => openPlace(g.place.kind, g.place.id));
      body.append(head, grid(g.photos, g.place));
    }

    body.querySelectorAll('.crumbs a').forEach((a) => a.addEventListener('click', () => openPlace(a.dataset.kind, a.dataset.id)));
    const reopen = () => openPlace(p.kind, p.id, { push: false, fly: false, point, size: S.view.size });
    actions.querySelector('[data-act="mark"]')?.addEventListener('click', async (ev) => {
      ev.currentTarget.disabled = true;
      await toggleVisit(p.kind, p.id, true);
      reopen();
    });
    actions.querySelector('[data-act="unmark"]')?.addEventListener('click', async () => {
      if (!p.explicit) return toast(IMPLIED_MSG[p.kind]);
      if (await toggleVisit(p.kind, p.id, false, p.photos.length, p.dates.length) === false) return;
      if (isVisited(p.kind, p.id)) toast(IMPLIED_MSG[p.kind]);  // ainda tem cidade marcada aqui
      reopen();
    });
    actions.querySelector('[data-act="edit"]')?.addEventListener('click', () => go({
      type: 'landmark-form', id: p.id, isNew: false, name: p.name, lat: p.lat, lon: p.lon, photos: p.photos,
    }));
    actions.querySelector('[data-act="delete"]')?.addEventListener('click', async () => {
      if (!confirm(t('Apagar o monumento "{nome}" e suas {n} foto(s)?', { nome: p.name, n: p.photos.length }))) return;
      await api(`/api/landmarks/${p.id}`, { method: 'DELETE' });
      await loadVisited();
      closeSheet();
    });
    const file = $('input[type=file]', actions);
    const upBtn = actions.querySelector('[data-act="upload"]');
    upBtn.addEventListener('click', () => file.click());
    file.addEventListener('change', async () => {
      if (!file.files.length) return;
      upBtn.disabled = true;
      upBtn.textContent = t('Enviando {n}…', { n: file.files.length });
      await uploadPhotos(p.kind, p.id, file.files);
      reopen();
    });
  }

  // Quando: as visitas do lugar (mês e ano; pode ter várias), as que ele herda
  // do que tem dentro (cidades de um estado etc.) e as sugeridas pelas fotos.
  function visitDates(p, reopen) {
    const box = el(`<div class="when"><p class="group-title">${t('Quando')}</p><div class="chips"></div></div>`);
    const chips = $('.chips', box);
    const url = `/api/place/${p.kind}/${encodeURIComponent(p.id)}/dates`;
    for (const m of p.dates) {
      const c = el(`<span class="chip">${fmtMonth(m)}<button aria-label="${esc(t('Remover'))}">×</button></span>`);
      $('button', c).addEventListener('click', async () => {
        await api(`${url}/${m}`, { method: 'DELETE' });
        reopen();
      });
      chips.append(c);
    }
    for (const m of p.suggested) {
      const c = el(`<button class="chip suggest" title="${esc(t('Pelas fotos'))}">+ ${fmtMonth(m)} <small>${t('pelas fotos')}</small></button>`);
      c.addEventListener('click', async () => { await api(url, json('POST', { month: m })); reopen(); });
      chips.append(c);
    }
    const add = el(`<button class="chip add">+ ${t('Adicionar data')}</button>`);
    chips.append(add);
    add.addEventListener('click', () => {
      const now = new Date();
      // mês opcional: lugar onde morou, ou viagem de que só lembra o ano
      const months = [`<option value="">${t('Mês')}</option>`, ...Array.from({ length: 12 }, (_, i) => `<option value="${String(i + 1).padStart(2, '0')}">${fmtMonth(`2000-${i + 1}`).split(' ')[0]}</option>`)];
      const years = Array.from({ length: now.getFullYear() - 1899 }, (_, i) => now.getFullYear() - i).map((y) => `<option>${y}</option>`);
      const form = el(`<form class="date-form">
        <select name="m" aria-label="${esc(t('Mês'))}">${months.join('')}</select>
        <select name="y" aria-label="${esc(t('Ano'))}">${years.join('')}</select>
        <button class="btn small">${t('Salvar')}</button></form>`);
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        await api(url, json('POST', { month: form.m.value ? `${form.y.value}-${form.m.value}` : form.y.value }));
        reopen();
      });
      add.hidden = true;  // não tirar do DOM: o toque fora da gaveta a recolhe (alvo solto conta como fora)
      add.after(form);
    });
    if (p.inherited.length) {
      const via = p.inherited.map((d) => `<span class="via"><b>${fmtMonth(d.month)}</b> ${d.places.map((x) => esc(x.name)).join(', ')}</span>`);
      box.append(el(`<p class="hint inherited">${p.kind === 'city' ? t('Pelos monumentos:') : t('Pelo que tem dentro:')} ${via.join(' · ')}</p>`));
    }
    if (!p.dates.length && !p.inherited.length && !p.suggested.length) {
      box.append(el(`<p class="hint">${t('Quando você esteve aqui? O ano basta (o mês é opcional); dá para pôr mais de uma visita.')}</p>`));
    }
    return box;
  }

  // ------------------------------------------------------------------ landmarks
  // Só nascem de uma foto: envia, o servidor lê GPS/data do EXIF e devolve um
  // rascunho; o formulário dá nome e posição (e, se quiser, marca a cidade etc.).
  async function newLandmark(files) {
    const fd = new FormData();
    for (const f of files) fd.append('photos', f);
    try {
      const r = await fetch('/api/landmarks', { method: 'POST', body: fd });
      const res = await r.json();
      if (res.errors?.length) alert(`${t('Algumas fotos falharam:')}\n${res.errors.join('\n')}`);
      if (!r.ok) return render();
      const place = await api(`/api/place/landmark/${res.id}`);
      S.history = [];
      S.view = { type: 'landmark-form', id: res.id, isNew: true, name: '', lat: place.lat, lon: place.lon, photos: place.photos, gps: !!res.gps };
      render();
    } catch (err) {
      alert(t('Falha no envio: {erro}', { erro: err.message }));
      render();
    }
  }

  function stopPlacing() {
    if (!S.placing) return;
    S.placing.marker.remove();
    S.placing = null;
  }

  function renderLandmarkForm(v) {
    const pos = v.lat != null;
    const cancel = async () => {
      stopPlacing();
      if (v.isNew) {
        await api(`/api/landmarks/${v.id}`, { method: 'DELETE' });
        closeSheet();
      } else back();
    };
    body.append(sheetHead(`<div class="kind-label"><i class="dot landmark"></i>${v.isNew ? t('Novo monumento') : t('Editar monumento')}</div>`,
      { onClose: cancel, canBack: false }));
    const strip = el('<div class="lm-strip"></div>');
    for (const ph of v.photos) strip.append(el(`<figure class="print"><img src="${ph.thumb}" alt=""><div class="date">${fmtDate(ph.taken_on)}</div></figure>`));
    body.append(strip);
    const form = el(`<form class="lm-form">
      <label>${t('Nome')}<input name="name" maxlength="200" required placeholder="${t('Ex.: Cristo Redentor')}" autocomplete="off"></label>
      <p class="hint suggest" hidden></p>
      <p class="hint where"></p>
      <div class="also" hidden><p class="group-title">${t('Também marcar como visitado')}</p><div class="checks"></div></div>
      <div class="actions">
        <button class="btn" type="submit">${t('Salvar')}</button>
        <button class="btn secondary" type="button" data-act="cancel">${t('Cancelar')}</button>
      </div>
    </form>`);
    body.append(form);
    const nameIn = form.elements.name, save = $('[type=submit]', form);
    nameIn.value = v.name || '';
    nameIn.addEventListener('input', () => { v.name = nameIn.value; check(); });
    const check = () => { save.disabled = !(nameIn.value.trim() && v.lat != null); };

    const where = $('.where', form);
    const showWhere = () => {
      where.textContent = v.lat == null
        ? `📍 ${t('A foto não tem localização. Toque no mapa onde ela foi tirada.')}`
        : `📍 ${v.gps ? t('Posição tirada do GPS da foto.') : t('Posição marcada.')} ${t('Arraste o marcador ou toque no mapa para ajustar.')}`;
    };

    // "Também marcar": cidade mais próxima, o estado e o país dela. Nada vem marcado.
    const also = $('.also', form), checks = $('.checks', form);
    let nearReq = 0;
    async function loadNear() {
      if (v.lat == null) return;
      const n = ++nearReq;
      const items = await api(`/api/landmarks/near?lat=${v.lat}&lon=${v.lon}`);
      if (n !== nearReq || !form.isConnected) return;
      checks.innerHTML = '';
      for (const it of items) {
        const label = it.kind === 'city' ? `${esc(it.name)} <small>(${it.km} km)</small>` : esc(it.name);
        checks.append(el(`<label class="check"><input type="checkbox" value="${it.kind}:${esc(it.id)}"
          ${it.visited ? 'checked disabled' : ''}><i class="dot ${it.kind}"></i>
          <span>${label}${it.visited ? ` <small>· ${t('já visitado')}</small>` : ''}</span></label>`));
      }
      also.hidden = !items.length;
    }

    // Sugestão de nome pelo OSM; preenche se o campo estiver vazio.
    const suggest = $('.suggest', form);
    async function loadSuggestion() {
      if (v.lat == null || !v.isNew) return;
      const { name } = await api(`/api/landmarks/suggest?lat=${v.lat}&lon=${v.lon}`).catch(() => ({}));
      if (!name || !form.isConnected) return;
      if (!nameIn.value.trim()) { nameIn.value = name; v.name = name; check(); }
      suggest.innerHTML = `${t('Sugestão do OpenStreetMap:')} <a>${esc(name)}</a>`;
      $('a', suggest).onclick = () => { nameIn.value = name; v.name = name; check(); };
      suggest.hidden = false;
    }

    // Marcador arrastável; tocar no mapa também move.
    stopPlacing();
    const marker = new maplibregl.Marker({ draggable: true, color: C.landmark });
    const moved = ({ lng, lat }) => {
      v.lat = +lat.toFixed(6);
      v.lon = +lng.toFixed(6);
      marker.setLngLat([v.lon, v.lat]).addTo(map);
      v.gps = false;
      showWhere(); check(); loadNear();
    };
    marker.on('dragend', () => moved(marker.getLngLat()));
    S.placing = { marker, move: moved };
    if (pos) {
      marker.setLngLat([v.lon, v.lat]).addTo(map);
      // a gaveta ainda não abriu aqui: desconta a altura que ela vai ter
      const cover = Math.min(window.innerHeight * 0.52, 420);
      map.flyTo({ center: [v.lon, v.lat], zoom: Math.max(map.getZoom(), THUMB_Z + 0.5), duration: 900, offset: [0, -cover / 2] });
    }
    showWhere(); check(); loadNear(); loadSuggestion();

    $('[data-act="cancel"]', form).addEventListener('click', cancel);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      save.disabled = true;
      save.textContent = t('Salvando…');
      try {
        await api(`/api/landmarks/${v.id}`, json('PATCH', { name: nameIn.value.trim(), lat: v.lat, lon: v.lon }));
        // cidade nova calcula o contorno (~1-3 s cada)
        for (const cb of checks.querySelectorAll('input:checked:not(:disabled)')) {
          const [kind, id] = cb.value.split(/:(.*)/);
          await api('/api/visits', json('POST', { kind, id }));
        }
        await loadVisited();
        stopPlacing();
        if (v.isNew) S.history = [];
        else S.history.pop();  // tira a tela antiga do landmark da pilha
        openPlace('landmark', v.id, { push: false });
      } catch (err) {
        alert(t('Falha ao salvar: {erro}', { erro: err.message }));
        save.textContent = t('Salvar');
        check();
      }
    });
  }

  async function loadNearby(slot, { lat, lng }) {
    const kinds = ['city', 'airport'].filter((k) => S.layers[k]);
    if (!kinds.length) return;
    const r = Math.max(0.15, 40 / 2 ** map.getZoom());
    const lists = await Promise.all(kinds.map((k) =>
      api(`/api/nearby?kind=${k}&lat=${lat}&lon=${lng}&r=${r}&limit=${k === 'city' ? 5 : 3}`)));
    const items = lists.flat();
    if (!items.length || !slot.isConnected) return;
    slot.append(el(`<p class="group-title">${t('Perto de onde você tocou')}</p>`));
    slot.append(resultList(items));
  }

  // Arrastar pela alça (ou pela foto do topo). Com foto: para cima expande,
  // para baixo volta ao tamanho da foto e, já nele, recolhe; tocar na alça
  // alterna. Sem foto: para baixo recolhe. O formulário do landmark não recolhe
  // assim (sai pelo Cancelar).
  (() => {
    let y0 = null, h0 = 0, dy = 0, moved = false, src = null;
    function down(e) {
      if (e.button > 0 || e.target.closest('button, a')) return;
      y0 = e.clientY; dy = 0; moved = false; src = e.currentTarget;
      h0 = sheet.getBoundingClientRect().height;
      src.setPointerCapture(e.pointerId);
    }
    function move(e) {
      if (y0 === null) return;
      dy = e.clientY - y0;
      if (!moved && Math.abs(dy) < 6) return;
      if (!moved) { moved = true; sheet.classList.add('dragging'); }
      if (sheet.dataset.size) sheet.style.height = `${Math.max(40, Math.min(window.innerHeight * 0.85, h0 - dy))}px`;
      else sheet.style.transform = `translateY(${Math.max(0, dy)}px)`;
    }
    function up(e) {
      if (y0 === null) return;
      y0 = null;
      sheet.classList.remove('dragging');
      sheet.style.transform = '';
      const size = sheet.dataset.size;
      if (!moved) {
        if (src.onTap) return src.onTap(e);
        if (size) setSize(size === 'peek' ? 'full' : 'peek');
        return;
      }
      if (!size) {
        if (dy > 70 && S.view.type !== 'landmark-form') closeSheet();
        return;
      }
      if (dy < 0) return setSize('full');
      if (sheet.getBoundingClientRect().height < peekHeight() * 0.75) return closeSheet();
      setSize('peek');
    }
    const bind = (node) => {
      node.addEventListener('pointerdown', down);
      node.addEventListener('pointermove', move);
      node.addEventListener('pointerup', up);
      node.addEventListener('pointercancel', up);
    };
    bind($('#grip'));
    // a foto do topo é recriada a cada render: liga quando ela aparece
    new MutationObserver(() => { const h = $('.hero[data-drag]', body); if (h && !h.dataset.bound) { h.dataset.bound = 1; bind(h); } })
      .observe(body, { childList: true });
  })();

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && S.view.type !== 'none' && S.view.type !== 'landmark-form') closeSheet();
  });

  // Botão + da barra de menu (nas outras telas ele é um link para /?add).
  $('#nav-add').addEventListener('click', (e) => {
    e.preventDefault();
    S.history = [];
    S.view = { type: 'add' };
    render();
  });

  // ------------------------------------------------------------------ toggles
  function syncToggles() {
    document.querySelectorAll('#toggles button').forEach((b) => b.setAttribute('aria-pressed', String(S.layers[b.dataset.kind])));
  }
  document.querySelectorAll('#toggles button').forEach((b) => b.addEventListener('click', () => {
    const k = b.dataset.kind;
    S.layers[k] = !S.layers[k];
    store.set('layers', S.layers);
    syncToggles();
    applyLayers();
  }));
  syncToggles();

  // ------------------------------------------------------------------ início
  Promise.all([setupMap(), loadVisited()]).then(() => {
    paintVisited();
    // vindo de outra tela: /?open=kind:id (abre o lugar) ou /?add (abre o +)
    const params = new URLSearchParams(location.search);
    const open = params.get('open');
    let first = true;  // primeira abertura nesta sessão (aba ou app)
    try {
      first = !sessionStorage.getItem('intro');
      sessionStorage.setItem('intro', '1');
    } catch { /* sem storage: anima sempre */ }
    if (!open) homeView({ intro: first && !params.has('scratch') && !reducedMotion() });
    if (params.has('open') || params.has('add') || params.has('scratch')) history.replaceState(null, '', '/');
    if (params.has('scratch')) {
      // vindo da lista de cidades do assistente: o mapa começa em branco e raspa tudo
      S.visited = Object.fromEntries(KINDS.map((k) => [k, []]));
      S.cityShapes = { type: 'FeatureCollection', features: [] };
      paintVisited();
      setTimeout(() => loadVisited({ batch: true }), 600);
    }
    if (open) {
      const [kind, id] = open.split(/:(.*)/);
      openPlace(kind, id);
    } else if (params.has('add')) {
      S.view = { type: 'add' };
      render();
    }
  }).catch((e) => {
    console.error(e);
    toast(t('Erro ao carregar: {erro}', { erro: e.message }));
  });
})();
