/* scratch map — lista de cidades: marcar várias de uma vez, sem buscar uma por
   uma. Usada no fim do assistente (setup.js) e no + do mapa ("Lista de
   cidades", app.js). País → (estado) → cidades das maiores para as menores,
   com filtro por nome; tocar escolhe. A escolha vale entre países: dá para
   escolher no Brasil, trocar para Portugal e continuar.
   window.SM.cityPicker(container, { onDone(n) }) */
(() => {
  const { $, esc, api, json, el, t } = window.SM;

  function cityPicker(root, { onDone } = {}) {
    const picked = new Map();  // id → nome
    root.innerHTML = `
      <div class="picker">
        <div class="picker-filters">
          <select class="picker-country" aria-label="${t('País')}"></select>
          <select class="picker-state" aria-label="${t('Estado')}"><option value="">${t('Todos os estados')}</option></select>
          <input type="search" class="picker-q" placeholder="${t('Filtrar por nome…')}" autocomplete="off" enterkeyhint="search">
        </div>
        <ul class="picker-list" aria-label="${t('Cidades')}"></ul>
        <div class="picker-foot">
          <span class="picker-count">${t('Toque nas cidades que você conhece.')}</span>
          <button class="btn picker-go" disabled>${t('Marcar')}</button>
        </div>
      </div>`;
    const country = $('.picker-country', root);
    const state = $('.picker-state', root);
    const q = $('.picker-q', root);
    const list = $('.picker-list', root);
    const count = $('.picker-count', root);
    const go = $('.picker-go', root);

    function paintFoot() {
      const names = [...picked.values()];
      const n = names.length;
      go.disabled = !n;
      go.textContent = n ? t(n === 1 ? 'Marcar {n} cidade' : 'Marcar {n} cidades', { n }) : t('Marcar');
      count.textContent = !n ? t('Toque nas cidades que você conhece.')
        : n <= 3 ? names.join(', ') : t('{nomes} e mais {n}', { nomes: names.slice(0, 2).join(', '), n: n - 2 });
    }

    function row(c) {
      const on = c.visited || picked.has(c.id);
      const li = el(`<li><button class="pick-row${c.visited ? ' visited' : ''}" aria-pressed="${on}" ${c.visited ? 'disabled' : ''}>
        <span class="box" aria-hidden="true"></span>
        <span class="nm"><b>${esc(c.name)}</b><small>${c.visited ? t('já marcada') : esc(c.state)}</small></span>
      </button></li>`);
      const b = $('button', li);
      b.addEventListener('click', () => {
        if (picked.has(c.id)) picked.delete(c.id);
        else picked.set(c.id, c.name);
        b.setAttribute('aria-pressed', String(picked.has(c.id)));
        paintFoot();
      });
      return li;
    }

    let seq = 0;
    let offset = 0;
    async function load({ append = false } = {}) {
      const n = ++seq;
      if (!append) offset = 0;
      const params = new URLSearchParams({ country: country.value, offset });
      if (state.value) params.set('state', state.value);
      if (q.value.trim()) params.set('q', q.value.trim());
      if (!append) list.classList.add('loading');
      const r = await api(`/api/cities?${params}`);
      if (n !== seq) return;
      list.classList.remove('loading');
      if (r.states) {
        const keep = state.value;
        state.innerHTML = `<option value="">${t('Todos os estados')}</option>`
          + r.states.map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('');
        state.value = keep;
        state.hidden = !r.states.length;
      }
      $('.more', list)?.remove();
      if (!append) { list.innerHTML = ''; list.scrollTop = 0; }
      if (!append && !r.cities.length) list.append(el(`<li class="empty">${t('Nenhuma cidade com esse nome.')}</li>`));
      for (const c of r.cities) list.append(row(c));
      offset += r.cities.length;
      if (r.more) {
        const more = el(`<li class="more"><button class="btn secondary small">${t('Mostrar mais')}</button></li>`);
        $('button', more).addEventListener('click', () => load({ append: true }));
        list.append(more);
      }
    }

    country.addEventListener('change', () => { state.value = ''; q.value = ''; load(); });
    state.addEventListener('change', () => load());
    let qTimer;
    q.addEventListener('input', () => { clearTimeout(qTimer); qTimer = setTimeout(load, 250); });

    go.addEventListener('click', async () => {
      go.disabled = true;
      go.textContent = t('Marcando…');
      try {
        const r = await api('/api/visits/batch', json('POST', { ids: [...picked.keys()] }));
        picked.clear();
        onDone?.(r.added);
      } catch (e) {
        alert(t('Não deu para marcar: {erro}', { erro: e.message }));
        paintFoot();
      }
    });

    // país inicial: o mais visitado; sem visitas, o do idioma do navegador (pt-BR → BR)
    (async () => {
      const r = await api('/api/countries');
      country.innerHTML = r.countries.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');
      const region = (navigator.language || '').split('-')[1]?.toUpperCase();
      const ids = new Set(r.countries.map((c) => c.id));
      country.value = r.home || (ids.has(region) ? region : r.countries[0]?.id);
      load();
    })();
  }

  window.SM.cityPicker = cityPicker;
})();
