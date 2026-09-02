/* Cache the shell and the zone bundles so "what's live right now" works with no
   signal -- it is pure client-side math over data already on the device. */
/* Bump on every deploy that changes the shell or the corpus. The name is the ONLY
   eviction trigger: activate deletes caches whose name differs, so a name that never
   changes means the precache below is never refreshed. data/index.json is precached,
   so a stale hhf-v4 kept serving an old zone list -- King of Prussia read 1 on
   devices while the server had said 3 for hours. */
const CACHE = "hhf-2026-09-02-309-2a359a00";
const SHELL = [
  "./", "index.html", "app.js", "lib.js", "styles.css", "manifest.json",
  "data/index.json", "img/hero-workhorse.jpg", "img/icon-192.png",
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
  //
  // 'no-cache' revalidates instead of trusting the HTTP cache: GitHub Pages
  // serves the shell with max-age=600, so a plain fetch() here can be answered
  // from Safari's own cache and "network first" quietly becomes "ten minutes
  // stale". That is not theoretical -- a deploy fixing the submit endpoint
  // read as still-broken on a phone because the phone re-ran the old app.js.
  // Revalidation costs a 304 when nothing changed, and is the difference
  // between a fix landing now and landing whenever the cache feels like it.
  const req = new URL(e.request.url).origin === self.location.origin
    ? new Request(e.request, { cache: "no-cache" })
    : e.request;
  e.respondWith(
    fetch(req)
      .then((res) => {
        // A 404 mid-deploy is not an offline floor worth keeping.
        if (res.ok && res.type === "basic") {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return res;
      })
      .catch(() =>
        // ignoreSearch because index.html asks for "app.js?v=2" while the
        // precache holds "app.js": without it the offline shell missed its own
        // script.
        caches.match(e.request, { ignoreSearch: true }).then((r) => {
          if (r) return r;
          // index.html as a last resort is right for a NAVIGATION and wrong for
          // everything else: it used to be handed back for an uncached
          // data/zone-*.json too, so r.json() got HTML, threw, and boot()'s
          // Promise.all rejected before it had drawn a single control. One
          // dropped request on a phone became a permanently dead board. Let a
          // failed asset fail, so the caller can see it and carry on.
          if (e.request.mode === "navigate") return caches.match("index.html");
          return Response.error();
        })
      )
  );
});
