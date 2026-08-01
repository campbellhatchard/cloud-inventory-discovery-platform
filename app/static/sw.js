const CACHE = 'ci-discovery-v0.5.0';
const SHELL = ['/', '/static/styles.css', '/static/app.js', '/static/cloud-inventory-logo-for-light-background-v0.4.1.png', '/static/cloud-inventory-logo-for-dark-background-v0.4.1.png', '/manifest.json'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET' || request.url.includes('/api/')) return;
  event.respondWith(fetch(request).then(response => {
    const clone = response.clone();
    caches.open(CACHE).then(cache => cache.put(request, clone));
    return response;
  }).catch(() => caches.match(request).then(found => found || caches.match('/'))));
});
