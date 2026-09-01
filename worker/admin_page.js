/* The admin page, served by the Worker at /admin.

   The HTML itself is not secret -- it contains no submissions -- so it is served
   without a token and asks for one, which it keeps in localStorage and sends as
   X-Admin-Token on every call. The photo is fetched the same way and turned into
   a blob URL, so a menu photo never becomes a URL that works without the token.

   Deliberately one file with no build step and no dependencies, like the rest of
   this project. */

export const ADMIN_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow">
<title>Happy Hour — review</title>
<style>
  :root {
    --bg: #f7f3eb; --surface: #fff; --fg: #0f2a34; --muted: #3d5a65;
    --dim: #5a7888; --line: rgba(15,42,52,.12); --accent: #0a8a9e;
    --ok: #2e8b57; --bad: #b14a3b; --warn: #a15c00;
    --r: 16px; --tap: 44px;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  header {
    position: sticky; top: 0; z-index: 5; background: rgba(247,243,235,.94);
    backdrop-filter: blur(8px); border-bottom: 1px solid var(--line);
    padding: 12px 16px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
  }
  h1 { font-size: 1.05rem; margin: 0; letter-spacing: -.01em; }
  main { max-width: 900px; margin: 0 auto; padding: 16px; }
  .tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-left: auto; }
  .tab {
    border: 1px solid var(--line); background: var(--surface); color: var(--muted);
    border-radius: 999px; padding: 7px 14px; font-size: .86rem; cursor: pointer;
    min-height: 36px;
  }
  .tab[aria-selected="true"] { background: var(--accent); border-color: var(--accent); color: #fff; }
  .card {
    background: var(--surface); border: 1px solid var(--line); border-radius: var(--r);
    padding: 16px; margin-bottom: 16px;
  }
  .card h2 { margin: 0 0 2px; font-size: 1.05rem; }
  .sub { color: var(--dim); font-size: .85rem; margin: 0 0 12px; }
  .row { display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-start; }
  .shot {
    flex: 0 0 240px; max-width: 240px; border-radius: 12px; border: 1px solid var(--line);
    background: #eee; cursor: zoom-in; display: block;
  }
  .shot.big { position: fixed; inset: 4vh 4vw; max-width: none; width: auto; height: 92vh;
              object-fit: contain; background: rgba(10,28,38,.94); z-index: 20; cursor: zoom-out;
              padding: 12px; }
  .detail { flex: 1 1 300px; min-width: 260px; }
  .win { font-variant-numeric: tabular-nums; }
  ul { margin: 6px 0; padding-left: 20px; }
  li { margin: 2px 0; }
  .flag { color: var(--warn); font-size: .88rem; margin: 8px 0 0; }
  .bad { color: var(--bad); }
  .ok { color: var(--ok); }
  .board {
    border-left: 3px solid var(--line); padding: 2px 0 2px 12px; margin: 12px 0;
    color: var(--muted); font-size: .9rem;
  }
  details { margin-top: 10px; font-size: .88rem; color: var(--muted); }
  summary { cursor: pointer; min-height: 28px; }
  pre { white-space: pre-wrap; word-break: break-word; font-size: .82rem; }
  .acts { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
  .merge { margin-top: 14px; padding: 10px 12px; border: 1px solid #d8cfc2; border-radius: 10px; }
  .merge > p { margin: 0 0 8px; font-weight: 700; }
  .merge label { display: block; margin: 6px 0; cursor: pointer; }
  .merge label span { color: #6b6357; font-weight: 400; }
  button.go, button.no, button.ghost {
    min-height: var(--tap); padding: 0 18px; border-radius: 999px; font-size: .92rem;
    font-weight: 600; cursor: pointer; border: 1px solid transparent;
  }
  button.go { background: var(--accent); color: #fff; }
  button.no { background: var(--surface); color: var(--bad); border-color: var(--line); }
  button.ghost { background: var(--surface); color: var(--muted); border-color: var(--line); }
  button[disabled] { opacity: .5; cursor: default; }
  input, select, textarea {
    font: inherit; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--line);
    background: var(--surface); color: var(--fg); width: 100%; min-height: var(--tap);
  }
  label { display: block; font-size: .85rem; color: var(--muted); margin: 10px 0 4px; }
  .empty { color: var(--dim); padding: 40px 0; text-align: center; }
  .pill {
    display: inline-block; font-size: .74rem; text-transform: uppercase;
    letter-spacing: .06em; padding: 3px 9px; border-radius: 999px;
    border: 1px solid var(--line); color: var(--muted); margin-left: 6px;
  }
  .pill.auto { color: var(--ok); border-color: var(--ok); }
  #err { color: var(--bad); font-size: .9rem; }
</style>
</head>
<body>
<header>
  <h1>Happy Hour — review</h1>
  <div class="tabs" id="tabs"></div>
</header>
<main>
  <div id="gate" class="card" hidden>
    <h2>Admin token</h2>
    <p class="sub">Stored in this browser only, sent as a header. Never in a URL.</p>
    <input id="tok" type="password" autocomplete="off" placeholder="ADMIN_TOKEN">
    <div class="acts"><button class="go" id="tokGo">Unlock</button></div>
    <p id="err"></p>
  </div>

  <div id="add" class="card" hidden>
    <h2>Add a menu yourself</h2>
    <p class="sub">Same queue and same checks as a photo from the site.</p>
    <label for="aLid">Venue (PLCB licence ID)</label>
    <input id="aLid" inputmode="numeric" placeholder="130467">
    <label for="aName">Venue name (optional, helps you recognise it here)</label>
    <input id="aName" placeholder="Dave &amp; Buster's King of Prussia">
    <label for="aFile">Photo</label>
    <input id="aFile" type="file" accept="image/*">
    <div class="acts">
      <button class="go" id="aGo">Send it</button>
      <span id="aMsg" class="sub" style="margin:0;align-self:center"></span>
    </div>
  </div>

  <div id="list"></div>
</main>
<script>
const $ = (s) => document.querySelector(s);
const STATUSES = ["pending", "extracted", "approved", "rejected"];
const DOW = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
let token = localStorage.getItem("hhf_admin") || "";
let status = "extracted";
let board = null;

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { ...(opts.headers || {}), "X-Admin-Token": token },
  });
  if (res.status === 401) throw new Error("unauthorized");
  if (!res.ok) throw new Error((await res.text()).slice(0, 200));
  return res;
}

function fmtWindows(ws) {
  const clock = (t) => {
    if (t === "24:00") return "midnight";
    let [h, m] = t.split(":").map(Number);
    const ap = h >= 12 && h < 24 ? "pm" : "am";
    h = h % 12 || 12;
    return m ? h + ":" + String(m).padStart(2, "0") + ap : h + ap;
  };
  return (ws || []).map((w) => DOW[w.dow] + " " + clock(w.start) + "–" + clock(w.end)).join(" · ");
}

function dealBlock(d) {
  const box = el("div");
  box.append(el("p", "win", fmtWindows(d.windows) || "no times printed"));
  if ((d.items || []).length) {
    const ul = el("ul");
    for (const i of d.items) {
      const price = i.price_usd != null
        ? "$" + i.price_usd + (i.price_max != null ? "\u2013" + i.price_max : "")
        : i.discount_pct != null ? i.discount_pct + "% off"
        : i.amount_off_usd != null ? "$" + i.amount_off_usd + " off" : "—";
      ul.append(el("li", null, price + "  " + (i.label || "")));
    }
    box.append(ul);
  }
  if (d.fine_print) {
    const det = el("details");
    det.append(el("summary", null, "Fine print"));
    det.append(el("pre", null, d.fine_print));
    box.append(det);
  }
  return box;
}

/* What the site is showing for this venue right now -- the question the reviewer
   is actually answering, since approving REPLACES it. */
function boardFor(lid) {
  const wrap = el("div", "board");
  const venue = board && board[lid];
  if (!venue) {
    wrap.append(el("p", null, "Nothing published for this venue yet — approving adds the first hours."));
    return wrap;
  }
  wrap.append(el("p", null, "On the board now:"));
  for (const d of venue.deals) {
    wrap.append(el("p", "win", fmtWindows(d.windows) + "  · " + (d.source && d.source.kind || "?")));
  }
  return wrap;
}

async function showPhoto(img, id) {
  try {
    const res = await api("/admin/photo/" + id);
    img.src = URL.createObjectURL(await res.blob());
  } catch {
    img.alt = "photo unavailable";
  }
}

/* Ask only when the answer can change anything.

   If the venue has nothing published, approving adds the first hours either
   way and a question with one real answer is just a thing to click past. When
   there IS something on the board, the clock cannot tell "another page of this
   menu" from "the menu changed" -- so the person looking at the photo says,
   and "the menu changed" is where the radio starts, because that is the answer
   that leaves a card honest if it is wrong. */
function mergeChooser(lid) {
  const venue = board && board[lid];
  if (!venue || !(venue.deals || []).length) return null;
  const wrap = el("div", "merge");
  wrap.append(el("p", null, "This venue already has hours published. This photo is:"));
  for (const [value, label, hint] of [
    ["replace", "A menu that changed", "the hours above come off the board"],
    ["add", "Another page of the same menu", "these hours are published alongside"],
  ]) {
    const l = el("label");
    const r = el("input");
    r.type = "radio";
    r.name = "merge-" + lid;
    r.value = value;
    if (value === "replace") r.checked = true;
    l.append(r, document.createTextNode(" " + label + " "), el("span", null, "— " + hint));
    wrap.append(l);
  }
  return wrap;
}

function card(sub) {
  const c = el("div", "card");
  const h = el("h2", null, sub.venue_name || "LID " + sub.lid);
  if ((sub.review_note || "").startsWith("auto-approved")) {
    h.append(el("span", "pill auto", "auto"));
  }
  c.append(h);
  c.append(el("p", "sub",
    "LID " + sub.lid + " · " + new Date(sub.submitted_at).toLocaleString() +
    " · " + Math.round(sub.bytes / 1024) + " KB"));

  const row = el("div", "row");
  const img = el("img", "shot");
  img.alt = "submitted menu photo";
  img.addEventListener("click", () => img.classList.toggle("big"));
  showPhoto(img, sub.id);
  row.append(img);

  const detail = el("div", "detail");
  let ex = null;
  try { ex = sub.extracted ? JSON.parse(sub.extracted) : null; } catch { ex = null; }

  if (sub.extract_error) {
    detail.append(el("p", "bad", "Could not read it: " + sub.extract_error));
  } else if (!ex) {
    detail.append(el("p", "sub", "Not read yet."));
  } else if (!ex.is_menu) {
    detail.append(el("p", "bad", "Not a menu — " + (ex.reason || "")));
  } else {
    if (!ex.deals.length) detail.append(el("p", "bad", "Nothing publishable was read."));
    for (const d of ex.deals) detail.append(dealBlock(d));
    if (ex.legible === false) {
      detail.append(el("p", "flag", "The model said the photo is not clearly legible."));
    }
    for (const con of ex.concerns || []) detail.append(el("p", "flag", "⚑ " + con));
    for (const r of ex.rejected || []) detail.append(el("p", "flag", "dropped: " + r));
    if (ex.transcript) {
      const det = el("details");
      det.append(el("summary", null, "Transcript the prices were read from"));
      det.append(el("pre", null, ex.transcript));
      detail.append(det);
    }
  }

  detail.append(boardFor(sub.lid));
  if (sub.note) detail.append(el("p", "sub", "Submitter note: " + sub.note));
  if (sub.review_note) detail.append(el("p", "sub", sub.review_note));

  if (status === "pending" || status === "extracted") {
    const chooser = mergeChooser(sub.lid);
    if (chooser) detail.append(chooser);
    const merge = () => {
      const picked = chooser && chooser.querySelector("input:checked");
      return picked ? picked.value : "replace";
    };
    const acts = el("div", "acts");
    const ok = el("button", "go", "Approve — publish it");
    const no = el("button", "no", "Reject");
    const publishable = ex && ex.is_menu && ex.deals && ex.deals.length;
    if (!publishable) ok.disabled = true;
    ok.addEventListener("click", () => review(sub.id, "approved", acts, merge()));
    no.addEventListener("click", () => review(sub.id, "rejected", acts));
    acts.append(ok, no);
    if (sub.extract_error || !ex) {
      const again = el("button", "ghost", "Read it again");
      again.addEventListener("click", async () => {
        again.disabled = true;
        again.textContent = "Reading…";
        try { await api("/admin/read/" + sub.id, { method: "POST" }); } catch (e) {
          again.textContent = String(e.message).slice(0, 60);
          return;
        }
        load();
      });
      acts.append(again);
    }
    detail.append(acts);
  }

  row.append(detail);
  c.append(row);
  return c;
}

async function review(id, decision, acts, merge) {
  for (const b of acts.querySelectorAll("button")) b.disabled = true;
  try {
    await api("/admin/review/" + id, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: decision,
        note: "reviewed on the admin page",
        merge: merge || "replace",
      }),
    });
  } catch (e) {
    acts.append(el("span", "bad", " " + e.message));
    return;
  }
  load();
}

function tabs() {
  const box = $("#tabs");
  box.textContent = "";
  for (const s of STATUSES) {
    const b = el("button", "tab", s);
    b.setAttribute("aria-selected", String(s === status));
    b.addEventListener("click", () => { status = s; load(); });
    box.append(b);
  }
}

async function load() {
  tabs();
  const list = $("#list");
  list.textContent = "";
  list.append(el("p", "empty", "Loading…"));
  let subs;
  try {
    const res = await api("/admin/queue?status=" + status);
    subs = (await res.json()).submissions;
  } catch (e) {
    if (e.message === "unauthorized") return gate("That token was not accepted.");
    list.textContent = "";
    list.append(el("p", "empty", e.message));
    return;
  }
  $("#gate").hidden = true;
  $("#add").hidden = false;
  try {
    if (!board) board = await (await api("/admin/board")).json();
  } catch { board = {}; }
  list.textContent = "";
  if (!subs.length) {
    list.append(el("p", "empty", "Nothing " + status + "."));
    return;
  }
  // Newest first: a reviewer wants the thing that just came in.
  subs.reverse();
  for (const s of subs) list.append(card(s));
}

function gate(msg) {
  $("#gate").hidden = false;
  $("#add").hidden = true;
  $("#list").textContent = "";
  $("#err").textContent = msg || "";
  $("#tok").focus();
}

$("#tokGo").addEventListener("click", () => {
  token = $("#tok").value.trim();
  localStorage.setItem("hhf_admin", token);
  load();
});
$("#tok").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#tokGo").click(); });

$("#aGo").addEventListener("click", async () => {
  const file = $("#aFile").files[0];
  const lid = $("#aLid").value.trim();
  const msg = $("#aMsg");
  if (!file || !lid) { msg.textContent = "Need a licence ID and a photo."; return; }
  msg.textContent = "Sending…";
  const fd = new FormData();
  fd.append("photo", file);
  fd.append("lid", lid);
  fd.append("venue_name", $("#aName").value.trim());
  const res = await fetch("/submit", { method: "POST", body: fd });
  if (!res.ok) { msg.textContent = (await res.json()).error || "failed"; return; }
  msg.textContent = "In the queue — reading it now.";
  $("#aFile").value = "";
  setTimeout(load, 1500);
});

if (token) load(); else gate();
</script>
</body>
</html>`;
