/* scratch map — mural: todas as fotos, impressas e "jogadas sobre a mesa".
   Duas ordens, numa grade contínua (sem quebras de linha): os rótulos são
   etiquetas de papel no meio das fotos, ocupando uma vaga da grade.
   - time: linha do tempo, uma etiqueta por mês (a do primeiro mês de cada ano
     em destaque); mais novas ou mais antigas primeiro; sem data sempre no fim;
   - place: por localidade (cidade em ordem alfabética), uma etiqueta por lugar. */
(() => {
  const { $, esc, api, store, el, print, lightbox, t, LANG } = window.SM;
  const MONTHS = LANG === 'en'
    ? ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
    : ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
  const wall = $('#wall');
  let data = null;
  let order = store.get('mural-order', 'time');
  if (order === 'recent') order = 'time';  // nome antigo da ordem
  let dir = store.get('mural-dir', 'new');   // new (mais novas primeiro) | old

  // Pseudoaleatório fixo por item: a mesa fica igual a cada recarga.
  const rnd = (n, k) => {
    const x = Math.sin(n * 12.9898 + k * 78.233) * 43758.5453;
    return x - Math.floor(x);
  };
  const toss = (seed, node, spread = 1) => {
    node.style.setProperty('--rot', `${((rnd(seed, 1) * 7 - 3.5) * spread).toFixed(2)}deg`);
    node.style.setProperty('--dx', `${(rnd(seed, 2) * 14 - 7).toFixed(1)}px`);
    node.style.setProperty('--dy', `${(rnd(seed, 3) * 14 - 7).toFixed(1)}px`);
    return node;
  };
  const count = (n) => t(n === 1 ? '{n} foto' : '{n} fotos', { n });

  // Sequência da mesa: etiquetas e fotos, na ordem em que aparecem. O servidor
  // manda as mais novas primeiro, com as sem data no fim.
  function timeline(photos) {
    if (dir === 'old') {
      const dated = photos.filter((p) => p.taken_on);
      photos = [...dated.reverse(), ...photos.filter((p) => !p.taken_on)];
    }
    const out = [];
    let key = null, tag = null, lastYear = null;
    for (const ph of photos) {
      const k = ph.taken_on ? ph.taken_on.slice(0, 7) : 'none';
      if (k !== key) {
        key = k;
        const [y, m] = k.split('-');
        tag = k === 'none'
          ? { tag: true, title: t('sem data'), n: 0 }
          : { tag: true, title: MONTHS[+m - 1], sub: y, year: y !== lastYear, n: 0 };
        if (k !== 'none') lastYear = y;
        out.push(tag);
      }
      tag.n++;
      out.push({ ph });
    }
    return out;
  }
  function byPlace(groups) {
    return groups.flatMap((g) => [{ tag: true, title: g.title, place: g.place, n: g.photos.length },
      ...g.photos.map((ph) => ({ ph, group: g }))]);
  }

  function note(it, i) {
    const title = it.place
      ? `<a href="/?open=${it.place.kind}:${encodeURIComponent(it.place.id)}">${esc(it.title)}</a>`
      : esc(it.title);
    const node = el(`<div class="mural-note${it.year ? ' year' : ''}${it.place ? ' place' : ''}">
      <b>${title}</b>${it.sub ? `<span>${esc(it.sub)}</span>` : ''}<small>${count(it.n)}</small>
    </div>`);
    return toss(9000 + i, node, 0.8);
  }

  const dirBtn = $('#dir');
  function render() {
    document.querySelectorAll('#order button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.order === order)));
    dirBtn.hidden = order !== 'time';
    dirBtn.textContent = dir === 'new' ? t('↓ Mais novas') : t('↑ Mais antigas');
    dirBtn.title = dir === 'new' ? t('Mais novas primeiro (toque para inverter)') : t('Mais antigas primeiro (toque para inverter)');
    wall.innerHTML = '';
    if (!data.recent.length) {
      wall.append(el(`<p class="mural-empty">${t('Nenhuma foto ainda. Adicione fotos nos lugares, no mapa.')}</p>`));
      return;
    }
    const items = order === 'place' ? byPlace(data.groups) : timeline(data.recent);
    const all = items.filter((it) => it.ph).map((it) => it.ph);   // ordem das setas = ordem da mesa
    const opts = {
      openPlace: (ph) => { location.href = `/?open=${ph.kind}:${encodeURIComponent(ph.ref_id)}`; },
      onChange: load,
    };
    const grid = el('<div class="mural-grid"></div>');
    items.forEach((it, i) => {
      if (it.tag) return grid.append(note(it, i));
      const ph = it.ph;
      // no grupo do próprio lugar o nome dele na margem seria repetido
      const own = it.group && ph.kind === it.group.place.kind && String(ph.ref_id) === String(it.group.place.id);
      grid.append(toss(ph.id, print(ph, { withLabel: !own, onClick: () => lightbox.open(all, all.indexOf(ph), opts) })));
    });
    wall.append(grid);
  }

  async function load() {
    data = await api('/api/photos');
    $('#count').textContent = count(data.recent.length);
    render();
  }

  document.querySelectorAll('#order button').forEach((b) => b.addEventListener('click', () => {
    order = b.dataset.order;
    store.set('mural-order', order);
    render();
  }));

  dirBtn.addEventListener('click', () => {
    dir = dir === 'new' ? 'old' : 'new';
    store.set('mural-dir', dir);
    render();
  });

  load().catch((e) => wall.append(el(`<p class="mural-empty">${t('Erro ao carregar: {erro}', { erro: esc(e.message) })}</p>`)));
})();
