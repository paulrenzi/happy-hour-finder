/* Cache the shell and the zone bundles so "what's live right now" works with no
   signal -- it is pure client-side math over data already on the device. */
/* Bump on every deploy that changes the shell or the corpus. The name is the ONLY
   eviction trigger: activate deletes caches whose name differs, so a name that never
   changes means the precache below is never refreshed. data/index.json is precached,
   so a stale hhf-v4 kept serving an old zone list -- King of Prussia read 1 on
   devices while the server had said 3 for hours. */
const CACHE = "hhf-2026-08-31-169-2a408fcd";
const SHELL = [
  "./", "index.html", "app.js", "lib.js", "styles.css", "manifest.json",
  "data/index.json", "img/hero-taproom.jpg", "img/icon-192.png",
  // Self-hosted so the offline shell keeps its typography instead of falling
  // back to system serif the first time the page opens on no signal.
  "fonts/fraunces-latin-var.woff2", "fonts/manrope-latin-var.woff2",
];

self.addEventListener("install", (e) => {
  // reload: 'no-store' so the precache is filled from the network, never from an
  // HTTP-cached copy of the file this install exists to replace.
  e.waitUntil(
    caches
      .open(CACHE)
      .then((c) => c.addAll(SHELL.map((u) => new Request(u, { cache: "reload" }))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      // Without claim() the PAGE ALREADY OPEN keeps its old worker until every tab
      // for the site is closed -- on an installed PWA that can be days.
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  // Network first so a rebuilt bundle lands, cache as the offline floor.
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        // A 404 mid-deploy is not an offline floor worth keeping.
        if (res.ok && res.type === "basic") {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return res;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("index.html")))
  );
});
