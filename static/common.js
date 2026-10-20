/* scratch map — peças comuns ao mapa (app.js) e ao mural (mural.js):
   helpers, a cópia "impressa" de uma foto e o lightbox. Expõe window.SM. */
(() => {
  // Tradução (i18n.py): o português é a chave; window.I18N tem a tabela do
  // idioma escolhido (vazia em português). Variáveis: t('Olá, {nome}', { nome }).
  const I18N = window.I18N || {};
  const LANG = window.LANG || 'pt-BR';
  const t = (s, vars) => {
    const r = I18N[s] ?? s;
    return vars ? r.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m)) : r;
  };
  const MONTHS = LANG === 'en'
    ? ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
    : ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ'];

  const $ = (sel, el = document) => el.querySelector(sel);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const api = async (url, opts = {}) => {
    const r = await fetch(url, opts);
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r.json();
  };
  const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const fmtDate = (iso) => {
    if (!iso) return t('SEM DATA');
    const [y, m, d] = iso.split('-');
    return `${d} ${MONTHS[+m - 1]} ${y}`;
  };
  const fmtMonth = (ym) => {  // AAAA-MM ou só AAAA (data de visita)
    const [y, m] = ym.split('-');
    return m ? `${MONTHS[+m - 1]} ${y}` : y;
  };
  const store = {
    // por perfil (o aparelho pode ser de mais de uma pessoa); o perfil 1 ainda
    // lê as chaves de antes dos perfis
    key: (k) => `p${window.PROFILE}:${k}`,
    get(k, d) {
      try {
        const v = localStorage.getItem(this.key(k)) ?? (window.PROFILE === '1' ? localStorage.getItem(k) : null);
        return JSON.parse(v) ?? d;
      } catch { return d; }
    },
    set(k, v) { try { localStorage.setItem(this.key(k), JSON.stringify(v)); } catch { /* sem storage, tudo bem */ } },
  };
  function el(html) {
    const t = document.createElement('template');
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  }

  // Margem da foto: nome do lugar (quando pedido) à esquerda, data à direita.
  const margin = (ph, withLabel) => `<div class="date">${withLabel && ph.label
    ? `<span class="from"><i class="dot ${ph.kind}"></i><span>${esc(ph.label)}</span></span>` : ''}<span class="when">${fmtDate(ph.taken_on)}</span></div>`;

  function print(ph, { withLabel = false, onClick } = {}) {
    const fig = el(`<figure class="print"><img loading="lazy" src="${ph.thumb}" alt=""
      ${ph.width ? `width="${ph.width}" height="${ph.height}"` : ''}>${margin(ph, withLabel)}</figure>`);
    if (onClick) fig.addEventListener('click', onClick);
    return fig;
  }

  // ------------------------------------------------------------------ lightbox
  // photos: lista por onde as setas navegam. opts:
  //   isOwn(ph)        → a foto é do lugar aberto (aí não mostra o nome dele)
  //   openPlace(ph)    → botão "Abrir <lugar>" (só se a foto for de outro lugar)
  //   onChange()       → depois de mudar a data ou apagar
  let lb, st = null;

  function open(photos, index, opts = {}) {
    lb = lb || $('#lightbox');
    st = { photos, index, opts };
    draw();
    lb.hidden = false;
  }
  function close() { lb.hidden = true; lb.innerHTML = ''; st = null; }

  function draw() {
    const { photos, index, opts } = st;
    const ph = photos[index];
    const many = photos.length > 1;
    const other = !opts.isOwn?.(ph);
    lb.innerHTML = `
      <button class="close-x" aria-label="${t('Fechar')}">×</button>
      ${many ? `<button class="nav-arrow prev" aria-label="${t('Anterior')}">‹</button><button class="nav-arrow next" aria-label="${t('Próxima')}">›</button>` : ''}
      <figure class="big-print">
        <img src="${ph.url}" alt="">
        ${margin(ph, other)}
      </figure>
      <div class="lb-tools">
        ${other && opts.openPlace ? `<button data-act="place">${t('Abrir {lugar}', { lugar: esc(ph.label) })}</button>` : ''}
        <a href="${ph.url}" download>${t('Baixar')}</a><button data-act="del">${t('Apagar')}</button>
      </div>`;
    $('.close-x', lb).onclick = close;
    if (many) {
      $('.prev', lb).onclick = (e) => { e.stopPropagation(); step(-1); };
      $('.next', lb).onclick = (e) => { e.stopPropagation(); step(1); };
    }
    $('.big-print', lb).onclick = (e) => e.stopPropagation();
    $('.lb-tools', lb).onclick = (e) => e.stopPropagation();
    const when = $('.big-print .when', lb);
    when.title = t('Clique para editar a data');
    when.classList.add('stamp');
    when.onclick = () => {
      when.outerHTML = `<input type="date" value="${ph.taken_on || ''}">`;
      const inp = $('.big-print input', lb);
      inp.focus();
      const save = async () => {
        await api(`/api/photos/${ph.id}`, json('PATCH', { taken_on: inp.value || null }));
        ph.taken_on = inp.value || null;
        draw();
        st.opts.onChange?.();
      };
      inp.addEventListener('change', save);
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') save(); });
    };
    $('[data-act="place"]', lb)?.addEventListener('click', () => { close(); opts.openPlace(ph); });
    $('[data-act="del"]', lb).onclick = async () => {
      const msg = ph.kind === 'landmark' && other ? t('Apagar esta foto do monumento "{nome}"?', { nome: ph.label }) : t('Apagar esta foto?');
      if (!confirm(msg)) return;
      const res = await api(`/api/photos/${ph.id}`, { method: 'DELETE' });
      const cb = opts.onChange;
      close();
      cb?.(res);
    };
  }
  function step(d) {
    const n = st.photos.length;
    st.index = (st.index + d + n) % n;
    draw();
  }
  document.addEventListener('click', (e) => { if (lb && e.target === lb) close(); });
  document.addEventListener('keydown', (e) => {
    if (!st) return;
    if (e.key === 'Escape') { close(); e.stopImmediatePropagation(); }  // não desseleciona o lugar junto
    if (e.key === 'ArrowLeft') step(-1);
    if (e.key === 'ArrowRight') step(1);
  });

  window.SM = {
    $, esc, api, json, fmtDate, fmtMonth, store, el, print, t, LANG,
    lightbox: { open, close, isOpen: () => !!st },
  };
})();
