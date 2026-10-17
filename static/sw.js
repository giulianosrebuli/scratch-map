/* scratch map — service worker. Tudo continua vindo do servidor de casa (nada
   é guardado para uso offline, para não mostrar dado velho); a única coisa
   guardada é a página "sem conexão", mostrada quando o servidor não responde
   (computador desligado, fora da rede ou do Tailscale). */
const CACHE = 'scratch-map-v1';
const OFFLINE = '/offline';

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll([OFFLINE, '/static/icons/icon-192.png'])));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  if (e.request.mode !== 'navigate') return;  // o resto vai direto para a rede
  e.respondWith(fetch(e.request).catch(() => caches.match(OFFLINE)));
});
