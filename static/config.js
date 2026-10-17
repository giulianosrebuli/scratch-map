/* scratch map — configurações. Por enquanto, aparência: tema e cores do mapa.
   Tudo é salvo no servidor (vale em todos os aparelhos) e aplicado na hora. */
(() => {
  const { $, api, json, t, LANG } = window.SM;
  const root = document.documentElement;
  const save = (body) => api('/api/settings', json('PATCH', body)).catch((e) => toast(t('Não deu para salvar: {erro}', { erro: e.message })));
  const locale = LANG === 'en' ? 'en' : 'pt-BR';

  let toastTimer;
  function toast(msg) {
    const box = $('#toast');
    box.textContent = msg;
    box.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { box.hidden = true; }, 3500);
  }

  // ------------------------------------------------------------------ idioma
  // os textos vêm do servidor já traduzidos: grava e recarrega
  $('#language').addEventListener('change', async (e) => {
    await save({ language: e.target.value });
    location.reload();
  });

  // ------------------------------------------------------------------ tema
  const themeBtns = document.querySelectorAll('#theme button');
  const paintTheme = () => themeBtns.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.theme === root.dataset.theme)));
  themeBtns.forEach((b) => b.addEventListener('click', () => {
    root.dataset.theme = b.dataset.theme;
    paintTheme();
    save({ theme: b.dataset.theme });
  }));
  paintTheme();

  // ------------------------------------------------------------------ cores do mapa
  // Cor igual ao padrão é gravada como null (volta a seguir o padrão do app).
  const inputs = [...document.querySelectorAll('#colors input[type=color]')];
  const timers = {};
  const apply = (inp) => {
    root.style.setProperty(`--${inp.dataset.key}`, inp.value);
    inp.closest('li').querySelector('code').textContent = inp.value;
  };
  for (const inp of inputs) {
    inp.addEventListener('input', () => {
      apply(inp);
      const key = `color_${inp.dataset.key}`;
      clearTimeout(timers[key]);
      timers[key] = setTimeout(() => save({ [key]: inp.value === inp.dataset.default ? null : inp.value }), 300);
    });
  }
  $('#reset-colors').addEventListener('click', () => {
    const body = {};
    for (const inp of inputs) {
      inp.value = inp.dataset.default;
      apply(inp);
      body[`color_${inp.dataset.key}`] = null;
    }
    save(body);
  });

  // ------------------------------------------------------------------ formato do mapa
  const projBtns = document.querySelectorAll('#projection button');
  let projection = document.body.dataset.projection;
  const paintProj = () => projBtns.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.projection === projection)));
  projBtns.forEach((b) => b.addEventListener('click', () => {
    projection = b.dataset.projection;
    paintProj();
    save({ projection });
  }));
  paintProj();

  // ------------------------------------------------------------------ bordas
  for (const sw of document.querySelectorAll('#borders .switch')) {
    sw.addEventListener('change', () => save({ [sw.dataset.key]: sw.checked }));
  }

  // ------------------------------------------------------------------ dados e privacidade
  const refetch = $('#refetch-flags');
  for (const sw of document.querySelectorAll('#external .switch')) {
    sw.addEventListener('change', () => {
      save({ [sw.dataset.key]: sw.checked });
      if (sw.dataset.key === 'ext_state_flags') refetch.disabled = !sw.checked;
    });
  }
  refetch.addEventListener('click', async () => {
    refetch.disabled = true;
    try {
      await api('/api/flags/refetch', { method: 'POST' });
      toast(t('Buscando em segundo plano. As bandeiras aparecem no Perfil conforme chegam.'));
    } catch (e) {
      toast(t('Não deu: {erro}', { erro: e.message }));
    } finally {
      refetch.disabled = false;
    }
  });

  // ------------------------------------------------------------------ backup
  const info = $('#backup-info');
  const mb = (n) => `${(n / 1024 / 1024).toLocaleString(locale, { maximumFractionDigits: n > 1e8 ? 0 : 1 })} MB`;
  const when = (iso) => new Date(iso).toLocaleString(locale, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  async function loadBackupInfo() {
    try {
      const d = await api('/api/backup/info');
      info.innerHTML = `${t('{n} lugares marcados', { n: d.visits })} · ${t('{n} monumentos', { n: d.landmarks })} · ${t('{n} fotos', { n: d.photos })} · ~${mb(d.bytes)}<br>`
        + (d.last_backup ? t('Último backup baixado: {quando}', { quando: when(d.last_backup) }) : `<b>${t('Nenhum backup baixado ainda.')}</b>`);
    } catch (e) {
      info.textContent = t('Não deu para ler: {erro}', { erro: e.message });
    }
  }
  loadBackupInfo();
  // o download é um link normal; só atualiza o "último backup" depois
  $('#backup-download').addEventListener('click', () => setTimeout(loadBackupInfo, 4000));

  const restoreBtn = $('#restore-btn');
  const restoreFile = $('#restore-file');
  restoreBtn.addEventListener('click', () => restoreFile.click());
  restoreFile.addEventListener('change', async () => {
    const f = restoreFile.files[0];
    restoreFile.value = '';
    if (!f) return;
    if (!confirm(t('Restaurar "{arquivo}"?\n\nTodas as visitas, monumentos, fotos e configurações atuais serão trocadas pelas do backup. Uma cópia do estado atual fica guardada no servidor antes.', { arquivo: f.name }))) return;
    restoreBtn.disabled = true;
    restoreBtn.textContent = t('Enviando {tamanho}…', { tamanho: mb(f.size) });
    const fd = new FormData();
    fd.append('backup', f);
    try {
      const r = await fetch('/api/restore', { method: 'POST', body: fd });
      const text = await r.text();
      if (!r.ok) throw new Error(text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 200));
      const res = JSON.parse(text);
      alert(t('Backup restaurado ({lugares} lugares, {fotos} fotos).\nO estado anterior foi guardado em {arquivo}.',
        { lugares: res.restored.visits, fotos: res.restored.photos, arquivo: `data/profiles/${window.PROFILE}/backups/${res.safety}` }));
      location.reload();
    } catch (e) {
      alert(t('Não deu para restaurar: {erro}', { erro: e.message }));
      restoreBtn.disabled = false;
      restoreBtn.textContent = t('Escolher arquivo…');
    }
  });

  // ------------------------------------------------------------------ perfil
  $('#delete-profile')?.addEventListener('click', async () => {
    if (!confirm(t('Apagar este perfil? As visitas, os monumentos, as fotos e as configurações dele saem do app.'))) return;
    try {
      await api('/api/profile', { method: 'DELETE' });
      location.href = '/perfis';
    } catch (e) {
      alert(t('Não deu para apagar: {erro}', { erro: e.message }));
    }
  });

  // ------------------------------------------------------------------ vista inicial
  const radios = [...document.querySelectorAll('#start-view input[name=start]')];
  const country = $('#home-country');
  const fixedBox = $('#fixed-map');
  const current = () => radios.find((r) => r.checked)?.value;
  function syncStart() {
    fixedBox.hidden = current() !== 'fixed';
    if (!fixedBox.hidden) setupFixedMap();
  }
  for (const r of radios) {
    r.addEventListener('change', () => {
      const body = { start_view: r.value };
      if (r.value === 'country' && country.value) body.home_country = country.value;
      save(body);
      syncStart();
    });
  }
  country.addEventListener('change', () => {
    radios.find((r) => r.value === 'country').checked = true;
    save({ start_view: 'country', home_country: country.value });
    syncStart();
  });
  if (!country.options.length) {
    // nenhum país visitado ainda: a opção não tem o que enquadrar
    country.closest('label').classList.add('disabled');
    radios.find((r) => r.value === 'country').disabled = true;
  }

  // Mapa pequeno, só com terra e fronteiras: o centro e o zoom viram a vista
  // fixa (salva ao parar de mexer). Sem vista salva, começa no Brasil.
  let fixedMap = null;
  function setupFixedMap() {
    if (fixedMap) return fixedMap.resize();
    const css = (v) => getComputedStyle(root).getPropertyValue(v).trim();
    const proto = new pmtiles.Protocol();
    maplibregl.addProtocol('pmtiles', proto.tile);
    const [lon, lat, zoom] = (fixedBox.dataset.view || '-52,-15,3').split(',').map(Number);
    fixedMap = new maplibregl.Map({
      container: fixedBox,
      style: {
        version: 8,
        sources: { admin: { type: 'vector', url: `pmtiles://${location.origin}/geo/world.pmtiles?v=${window.GEO_V}` } },
        layers: [
          { id: 'water', type: 'background', paint: { 'background-color': css('--water') } },
          { id: 'land', type: 'fill', source: 'admin', 'source-layer': 'countries', paint: { 'fill-color': css('--land') } },
          { id: 'lines', type: 'line', source: 'admin', 'source-layer': 'countries', paint: { 'line-color': css('--border') } },
        ],
      },
      center: [lon, lat], zoom, minZoom: 0.8, maxZoom: 14,
      attributionControl: false, dragRotate: false, pitchWithRotate: false,
    });
    fixedMap.touchZoomRotate.disableRotation();
    fixedMap.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-left');
    let timer;
    fixedMap.on('moveend', () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const c = fixedMap.getCenter();
        save({ start_fixed: `${c.lng.toFixed(4)},${c.lat.toFixed(4)},${fixedMap.getZoom().toFixed(2)}` });
      }, 400);
    });
    // primeira vez sem vista salva: grava a inicial, para "fixa" ter o que usar
    if (!fixedBox.dataset.view) fixedMap.once('load', () => fixedMap.fire('moveend'));
  }
  syncStart();
})();
