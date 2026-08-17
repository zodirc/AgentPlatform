/* Cache flow diagrams so wiki page switches do not re-download ~1.5MB PNGs. */
const CACHE = "ap-docs-png-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (!url.pathname.toLowerCase().endsWith(".png")) return;
  event.respondWith(
    caches.open(CACHE).then((cache) =>
      cache.match(event.request).then((cached) => {
        const network = fetch(event.request)
          .then((resp) => {
            if (resp && resp.ok) cache.put(event.request, resp.clone());
            return resp;
          })
          .catch(() => cached);
        return cached || network;
      })
    )
  );
});
