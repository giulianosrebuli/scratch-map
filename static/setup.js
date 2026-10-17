/* scratch map — assistente de primeira execução (/setup, installer.py).
   Um passo por vez: boas-vindas (idioma; começar ou restaurar um backup) →
   perfil → vista inicial → dados do mapa → montagem (progresso) → lista de
   cidades. Cada escolha é gravada na hora; "Montar o mapa" começa a montagem
   no servidor. Perfil novo (com o mapa já montado): sem os dados e a montagem,
   da vista inicial direto para a lista de cidades. */
(() => {
  const { $, api, json, t, LANG } = window.SM;
  const { state, newProfile } = window.SETUP;
  const save = (body) => api('/api/settings', json('PATCH', body)).catch((e) => toast(t('Não deu para salvar: {erro}', { erro: e.message })));
  const params = new URLSearchParams(location.search);

  let toastTimer;
  function toast(msg) {
    const box = $('#toast');
    box.textContent = msg;
    box.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { box.hidden = true; }, 3500);
  }

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ------------------------------------------------------------------ mapa ao fundo
  // static/backdrop.js; voltando da troca de idioma, sem a entrada de novo
  window.SM.backdrop({ instant: params.has('lang') });
  if (params.has('lang')) history.replaceState(null, '', '/setup');

  // ------------------------------------------------------------------ passos
  // Troca suave: o passo atual sai deslizando, o cartão acompanha a altura do
  // próximo e ele entra pelo outro lado (de trás para frente no "Voltar").
  const card = $('#card');
  const steps = [...document.querySelectorAll('.setup-step')];
  const ALL = steps.map((s) => s.dataset.step);
  const dots = [...document.querySelectorAll('#dots li')];
  const ORDER = dots.map((d) => d.dataset.for);
  let current = null;
  let swap = 0;
  function paintDots(name) {
    const at = ORDER.indexOf(name);
    $('#dots').hidden = at < 0;
    dots.forEach((d, i) => { d.className = i < at ? 'past' : i === at ? 'now' : ''; });
  }
  function go(name) {
    const next = steps[ALL.indexOf(name)];
    const prev = current && steps[ALL.indexOf(current)];
    const dir = current && ALL.indexOf(name) < ALL.indexOf(current) ? -1 : 1;
    current = name;
    const id = ++swap;
    if (name === 'build') poll();
    if (name === 'cities' && !$('#picker').childElementCount) {
      // depois de marcar, o mapa abre e raspa as cidades novas numa cena só
      window.SM.cityPicker($('#picker'), { onDone: () => { location.href = '/?scratch'; } });
    }
    if (!prev || prev === next || reduceMotion) {
      for (const s of steps) s.hidden = s !== next;
      paintDots(name);
      return;
    }
    const h0 = card.offsetHeight;
    card.style.height = `${h0}px`;
    prev.style.setProperty('--dir', dir);
    prev.classList.add('leave');
    setTimeout(() => {
      if (id !== swap) return;
      for (const s of steps) {  // inclusive um passo deixado no meio por cliques rápidos
        if (s !== next) { s.hidden = true; s.classList.remove('leave', 'enter'); }
      }
      paintDots(name);
      next.style.setProperty('--dir', dir);
      next.classList.add('enter');
      next.hidden = false;
      card.style.height = '';
      const h1 = card.offsetHeight;
      card.style.height = `${h0}px`;
      void card.offsetHeight;  // fixa a altura antiga antes de animar
      card.style.height = `${h1}px`;
      $('.setup').scrollTo({ top: 0, behavior: 'smooth' });
      requestAnimationFrame(() => requestAnimationFrame(() => next.classList.remove('enter')));
      setTimeout(() => { if (id === swap) card.style.height = ''; }, 420);
    }, 220);
  }
  document.querySelectorAll('[data-go]').forEach((b) => b.addEventListener('click', () => go(b.dataset.go)));

  // ------------------------------------------------------------------ restaurar
  const mb = (n) => `${(n / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 0 })} MB`;
  const restoreBtn = $('#restore-btn');
  const restoreFile = $('#restore-file');
  restoreBtn.addEventListener('click', () => restoreFile.click());
  restoreFile.addEventListener('change', async () => {
    const f = restoreFile.files[0];
    restoreFile.value = '';
    if (!f) return;
    const label = restoreBtn.textContent;
    restoreBtn.disabled = true;
    restoreBtn.textContent = t('Enviando {tamanho}…', { tamanho: mb(f.size) });
    try {
      const fd = new FormData();
      fd.append('backup', f);
      const r = await fetch('/api/restore', { method: 'POST', body: fd });
      if (!r.ok) throw new Error((await r.text()).replace(/<[^>]+>/g, ' ').trim());
      const res = await r.json();
      // a página volta com o nome, a foto e as preferências do backup
      location.href = `/setup?restored=${res.restored.visits || 0},${res.restored.photos || 0}`;
    } catch (e) {
      toast(t('Não deu para restaurar: {erro}', { erro: e.message }));
      restoreBtn.disabled = false;
      restoreBtn.textContent = label;
    }
  });

  // ------------------------------------------------------------------ idioma, perfil, vista
  // os textos vêm do servidor já traduzidos: grava e recarrega (sem a entrada)
  $('#language').addEventListener('change', async (e) => {
    await save({ language: e.target.value });
    location.href = '/setup?lang';
  });
  // sem tocar no idioma, fica o que apareceu (o do navegador)
  $('[data-step=welcome] [data-go=profile]').addEventListener('click', () => save({ language: LANG }));

  const name = $('#profile-name');
  let savedName = name.value;
  const saveName = () => {
    const v = name.value.trim();
    if (v !== savedName) { savedName = v; save({ profile_name: v || null }); }
  };
  name.addEventListener('change', saveName);
  name.addEventListener('keydown', (e) => { if (e.key === 'Enter') name.blur(); });
  $('[data-step=profile] [data-go=view]').addEventListener('click', saveName);

  const avatar = $('#avatar');
  const file = $('#avatar-file');
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
      toast(t('Não deu para usar essa imagem'));
    } finally {
      avatar.classList.remove('busy');
      file.value = '';
    }
  });

  document.querySelectorAll('input[name=start]').forEach((r) => r.addEventListener('change', () => save({ start_view: r.value })));

  // ------------------------------------------------------------------ dados do mapa
  const DISK = { leve: '~13 GB', completo: '~22 GB' };
  const modeInput = () => $('input[name=mode]:checked');
  document.querySelectorAll('input[name=mode]').forEach((r) => r.addEventListener('change', () => {
    $('#disk-need').textContent = DISK[r.value];
  }));
  async function start(mode) {
    try {
      // a vista inicial padrão do assistente também vale se ninguém mexeu nela
      await save({ start_view: $('input[name=start]:checked').value });
      await api('/api/setup/start', json('POST', { mode }));
      go('build');
    } catch (e) {
      toast(t('Não deu para começar: {erro}', { erro: e.message }));
    }
  }
  $('#start').addEventListener('click', () => start(modeInput().value));
  $('#retry').addEventListener('click', () => start(state.mode || 'leve'));

  // ------------------------------------------------------------------ montagem
  let pollTimer;
  const ago = (ts) => {
    const min = Math.round((Date.now() / 1000 - ts) / 60);
    return min < 1 ? t('agora há pouco') : min < 60 ? t('há {n} min', { n: min })
      : t('há {h}h{m}', { h: Math.floor(min / 60), m: String(min % 60).padStart(2, '0') });
  };
  function paint(s) {
    const b = s.build || {};
    const done = new Set(b.done || []);
    const list = b.steps || ['download', 'clip', 'tiles', 'db', 'cleanup'];
    for (const li of document.querySelectorAll('#build-steps li')) {
      const id = li.dataset.step;
      li.hidden = !list.includes(id);
      li.className = done.has(id) ? 'done' : b.step === id ? (b.state === 'error' ? 'failed' : 'running') : '';
    }
    const err = b.state === 'error';
    const ok = s.installed || s.ready;
    $('#build-error').hidden = !err;
    if (err) $('#build-error-text').textContent = b.error || '';
    $('#build-done').hidden = !ok;
    $('#build-title').textContent = ok ? t('Pronto!') : err ? t('Montagem interrompida') : t('Montando o mapa');
    $('#build-lead').hidden = ok || err;
    // a mensagem da etapa vem do build (técnica, sem tradução)
    $('#build-msg').textContent = ok
      ? (b.started_at && b.finished_at ? t('Montado em {n} min.', { n: Math.max(1, Math.round((b.finished_at - b.started_at) / 60)) }) : '')
      : b.msg ? `${b.msg}${b.started_at ? ` · ${t('começou {quando}', { quando: ago(b.started_at) })}` : ''}` : t('Começando…');
    return ok || err;
  }
  async function poll() {
    clearTimeout(pollTimer);
    let s;
    try {
      s = await api('/api/setup');
      state.mode = s.mode;
    } catch {
      pollTimer = setTimeout(poll, 5000);  // servidor reiniciando: tenta de novo
      return;
    }
    if (!paint(s) || (s.ready && !s.installed)) pollTimer = setTimeout(poll, 2000);
  }

  // ------------------------------------------------------------------ início
  const restored = params.get('restored');
  if (newProfile) {
    go('welcome');  // perfil novo (restaurar um backup leva direto ao mapa)
  } else if (state.done) {
    go('build');
  } else if (restored) {
    const [v, p] = restored.split(',');
    history.replaceState(null, '', '/setup');
    toast(t('Backup restaurado: {lugares} lugares, {fotos} fotos.', { lugares: v, fotos: p }));
    go('profile');
  } else {
    go('welcome');
  }
})();
