/* scratch map — perfil: nome e foto, editáveis no topo da página, e a lista
   de voos (o álbum de bandeiras é o stats.js). */
(() => {
  const { $, esc, api, json, el, fmtDate, t } = window.SM;
  const name = $('#profile-name');
  const hint = $('#profile-hint');
  const avatar = $('#avatar');
  const file = $('#avatar-file');
  const HINT = hint.textContent;
  let saved = name.value;
  let hintTimer;
  const flash = (msg) => {
    hint.textContent = msg;
    clearTimeout(hintTimer);
    hintTimer = setTimeout(() => { hint.textContent = HINT; }, 2500);
  };

  name.addEventListener('change', async () => {
    const v = name.value.trim();
    if (v === saved) return;
    try {
      await api('/api/settings', json('PATCH', { profile_name: v || null }));
      saved = v;
      flash(t('Nome salvo'));
    } catch (e) {
      flash(t('Não deu para salvar: {erro}', { erro: e.message }));
    }
  });
  name.addEventListener('keydown', (e) => { if (e.key === 'Enter') name.blur(); });

  // exportar é um link; apagar pede confirmação (só aparece com mais de um perfil)
  $('#delete-profile')?.addEventListener('click', async () => {
    if (!confirm(t('Apagar este perfil? As visitas, os monumentos, as fotos e as configurações dele saem do app.'))) return;
    try {
      await api('/api/profile', { method: 'DELETE' });
      location.href = '/profiles';
    } catch (e) {
      alert(t('Não deu para apagar: {erro}', { erro: e.message }));
    }
  });

  // voos: o mais recente primeiro; apagar não desmarca os aeroportos
  const flightList = $('#flight-list');
  async function loadFlights() {
    const items = await api('/api/flights');
    flightList.innerHTML = '';
    $('#flights-empty').hidden = items.length > 0;
    for (const f of items) {
      const hours = f.departs || f.arrives ? ` · ${f.departs || '?'} → ${f.arrives || '?'}` : '';
      const li = el(`<li>
        <span class="code">${esc(f.code)}</span>
        <div class="name"><span class="route">${esc(f.origin.id)} → ${esc(f.destination.id)}</span>
          <small>${fmtDate(f.date)}${hours} · ${esc(f.origin.city || f.origin.name)} → ${esc(f.destination.city || f.destination.name)}</small></div>
        <button class="del" title="${esc(t('Apagar voo'))}" aria-label="${esc(t('Apagar voo'))}">×</button>
      </li>`);
      $('.del', li).addEventListener('click', async () => {
        if (!confirm(t('Apagar o voo {code} de {data}? Os aeroportos continuam marcados.', { code: f.code, data: fmtDate(f.date) }))) return;
        await api(`/api/flights/${f.id}`, { method: 'DELETE' });
        loadFlights();
      });
      flightList.append(li);
    }
  }
  loadFlights();

  avatar.addEventListener('click', () => file.click());
  file.addEventListener('change', async () => {
    if (!file.files.length) return;
    const fd = new FormData();
    fd.append('photo', file.files[0]);
    avatar.classList.add('busy');
    try {
      const r = await fetch('/api/profile/photo', { method: 'POST', body: fd });
      if (!r.ok) throw new Error(await r.text());
      const p = await r.json();
      avatar.innerHTML = `<img src="/profile.jpg?v=${p.photo}" alt="">`;
    } catch {
      flash(t('Não deu para usar essa imagem'));
    } finally {
      avatar.classList.remove('busy');
      file.value = '';
    }
  });
})();
