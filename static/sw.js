// Caches only the static app shell. Never caches /api, /socket.io, or chat/game data.
const V='ourplay-v1',SHELL=['/static/manifest.webmanifest','/static/icon.svg'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(V).then(c=>c.addAll(SHELL)));self.skipWaiting()});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==V).map(x=>caches.delete(x)))));self.clients.claim()});
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);
 if(e.request.method!=='GET'||u.origin!==location.origin||u.pathname.startsWith('/api')||u.pathname.startsWith('/socket.io'))return;
 e.respondWith(fetch(e.request).catch(()=>caches.match(e.request).then(r=>r||new Response('<body style="background:#070b1f;color:#fff;font-family:sans-serif;text-align:center;padding-top:20vh"><h2>OurPlay ♡</h2><p>You are offline. Reconnect to play.</p>',{headers:{'Content-Type':'text/html'}}))))});
