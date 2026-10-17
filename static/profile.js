/* scratch map — perfil: nome e foto, editáveis no topo da página (o álbum de
   bandeiras abaixo é o stats.js). */
(() => {
  const { $, api, json, t } = window.SM;
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
