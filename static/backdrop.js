/* scratch map — fundo do assistente e da escolha de perfil: um mundo leve
   (Natural Earth, static/vendor/world-lite.geojson; os dados do mapa podem
   ainda não existir) girando para leste, como a Terra: o chão anda para a
   direita na tela. Na entrada, desfoca e o cartão aparece (CSS: body.revealed).
   window.SM.backdrop({ instant }) — instant: já revelado, sem a entrada. */
(() => {
  const DEG_PER_S = 2.5;

  function backdrop({ instant = false } = {}) {
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
    const map = new maplibregl.Map({
      container: 'setup-map',
      style: {
        version: 8,
        sources: { world: { type: 'geojson', data: '/static/vendor/world-lite.geojson' } },
        layers: [
          { id: 'water', type: 'background', paint: { 'background-color': css('--water') } },
          { id: 'land', type: 'fill', source: 'world', paint: { 'fill-color': css('--land') } },
          { id: 'borders', type: 'line', source: 'world', paint: { 'line-color': css('--border'), 'line-width': 0.6 } },
        ],
      },
      center: [-20, 18], zoom: window.innerWidth < 600 ? 1.4 : 2, interactive: false, attributionControl: false,
    });
    let shown = false;
    const reveal = () => {
      if (shown) return;
      shown = true;
      document.body.classList.add('revealed');
    };
    if (instant) {
      document.body.classList.add('no-intro');
      reveal();
      requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.remove('no-intro')));
    }
    map.once('load', () => setTimeout(reveal, 250));
    setTimeout(reveal, 1500);  // mapa lento ou sem WebGL: o cartão aparece mesmo assim
    if (!reduceMotion) {
      let last = performance.now();
      const spin = (now) => {
        const c = map.getCenter();
        const lon = c.lng - DEG_PER_S * Math.min(now - last, 100) / 1000;
        map.jumpTo({ center: [lon < -180 ? lon + 360 : lon, c.lat] });
        last = now;
        requestAnimationFrame(spin);
      };
      requestAnimationFrame(spin);
    }
    return map;
  }

  window.SM.backdrop = backdrop;
})();
