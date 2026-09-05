-- D1 schema for the photo lane (SPEC section 9).
--   wrangler d1 execute hhf --remote --file worker/schema.sql

-- One row per menu photo somebody sent in.
--
-- status is the whole moderation story, and it only ever moves forward:
--
--   pending    uploaded, nothing has looked at it yet
--   extracted  the vision pass proposed deals; waiting on a human
--   approved   Paul said yes; the deals are in data/deals_photo.json
--   rejected   Paul said no (reason in review_note); the photo stays for audit
--
-- Nothing here is published by the Worker. A row becomes a deal on the site
-- only by passing through ingest/review_photos.py and a rebuild, which is what
-- keeps an arbitrary photo from a stranger off the board.
CREATE TABLE IF NOT EXISTS submissions (
  id            TEXT PRIMARY KEY,
  -- The venue this is a menu FOR. lid is the PLCB licence number, the stable
  -- key the board is built on; venue_name is carried alongside it purely so a
  -- reviewer can read the queue without joining anything.
  lid           TEXT,
  venue_name    TEXT,
  r2_key        TEXT NOT NULL,
  bytes         INTEGER NOT NULL,
  content_type  TEXT NOT NULL,
  note          TEXT,
  submitted_at  TEXT NOT NULL,
  -- Salted hash, never the address itself. Enough to rate-limit one submitter,
  -- not enough to locate them, and the salt is rotatable.
  ip_hash       TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'pending',
  -- The vision pass's proposal, as JSON. Kept verbatim even when a human then
  -- rejects it: what the model claimed is the record of why a photo was
  -- refused, and it is the only way to tell a bad photo from a bad read.
  extracted     TEXT,
  extract_error TEXT,
  extracted_at  TEXT,
  reviewed_at   TEXT,
  review_note   TEXT
);

CREATE INDEX IF NOT EXISTS submissions_status ON submissions (status, submitted_at);
CREATE INDEX IF NOT EXISTS submissions_lid ON submissions (lid);

-- Per-submitter daily counter. A photo endpoint with no ceiling is an open
-- image host; this is the ceiling. Old days are pruned on write.
CREATE TABLE IF NOT EXISTS rate (
  ip_hash TEXT NOT NULL,
  day     TEXT NOT NULL,
  n       INTEGER NOT NULL,
  PRIMARY KEY (ip_hash, day)
);

-- One row per person saying "yes, this happy hour is still on".
--
-- deal_key is produced by dealKey() in web/lib.js and stored verbatim: it is a
-- fingerprint of the deal's WINDOWS, so when the hours change the key changes
-- and the old confirmations stop counting toward the new ones. That is the
-- whole safety property -- nothing here can make hours look confirmed that
-- nobody confirmed.
--
-- ip_hash is in the primary key, so one person confirming the same deal five
-- times is one confirmation. It is the same salted hash used for submissions:
-- enough to deduplicate, not enough to locate anybody.
CREATE TABLE IF NOT EXISTS confirmations (
  lid          TEXT NOT NULL,
  deal_key     TEXT NOT NULL,
  ip_hash      TEXT NOT NULL,
  confirmed_at TEXT NOT NULL,
  PRIMARY KEY (lid, deal_key, ip_hash)
);

CREATE INDEX IF NOT EXISTS confirmations_recent ON confirmations (confirmed_at);

-- ============================================================
-- The night-out layer (PLAYBOOK-NIGHT-OUT.md). Added 2026-09-04.
-- Re-runnable: everything here is IF NOT EXISTS.
--   wrangler d1 execute hhf --remote --file worker/schema.sql
-- ============================================================

-- One row per address that asked for the list. Double opt-in: a row is
-- `pending` until the person clicks the link we mailed them, and only
-- `confirmed` rows are ever mailed again. The address is the only personal
-- thing this database holds anywhere, so it is stored once, lower-cased, and
-- deleted outright on unsubscribe -- not flagged.
CREATE TABLE IF NOT EXISTS subscribers (
  email         TEXT PRIMARY KEY,
  zone_id       TEXT,
  status        TEXT NOT NULL DEFAULT 'pending',   -- pending | confirmed
  token         TEXT NOT NULL,                     -- confirm/unsubscribe link
  created_at    TEXT NOT NULL,
  confirmed_at  TEXT,
  ip_hash       TEXT NOT NULL,
  mailed_at     TEXT                               -- when the confirm mail went
);
CREATE INDEX IF NOT EXISTS subscribers_status ON subscribers (status, created_at);

-- One row per thing happening at a venue on a date: a band, trivia, a seating.
-- The four fields nobody else carries are start, set_minutes, cover_usd and
-- kitchen_open. Everything else is what any calendar has.
--
-- source_kind says where the row came from, and decides who reviewed it:
--   image       read off a calendar picture on the venue's site (agent lane)
--   page        read off a page or Facebook embed on the venue's site
--   venue_form  the venue typed it through its own magic link  -> publishes
--   band_claim  the act typed it through its claim link         -> pending
--   ticketing   Ticketmaster / dead-shows feed
-- status: pending | approved | rejected. Only approved rows reach the overlay,
-- and a venue_form row is approved on write because the venue is the author.
CREATE TABLE IF NOT EXISTS events (
  id            TEXT PRIMARY KEY,
  lid           TEXT NOT NULL,
  zone_id       TEXT,
  date          TEXT NOT NULL,        -- YYYY-MM-DD, local
  start         TEXT,                 -- HH:MM, 24h, or NULL when unpublished
  end           TEXT,
  set_minutes   INTEGER,
  act           TEXT NOT NULL,
  kind          TEXT NOT NULL,        -- live_music | trivia | dj | comedy | other
  cover_usd     REAL,
  kitchen_open  INTEGER,              -- 1 yes, 0 no, NULL unknown
  source_kind   TEXT NOT NULL,
  source_url    TEXT,
  quote         TEXT,                 -- the exact words the row was read from
  recurs        TEXT,                 -- NULL = a one-off on `date`; 'weekly' = every
                                      -- week on `date`'s weekday, expanded at read time
  until         TEXT,                 -- YYYY-MM-DD, last day a recurring rule is trusted
  status        TEXT NOT NULL DEFAULT 'pending',
  created_at    TEXT NOT NULL,
  reviewed_at   TEXT,
  review_note   TEXT
);
CREATE INDEX IF NOT EXISTS events_live ON events (status, date);
CREATE INDEX IF NOT EXISTS events_lid ON events (lid, date);

-- A venue's magic link. Minted by an admin, mailed by a person, presented by
-- the venue on POST /venue/events. One live token per venue; minting again
-- replaces it.
CREATE TABLE IF NOT EXISTS venue_tokens (
  lid           TEXT PRIMARY KEY,
  token         TEXT NOT NULL UNIQUE,
  contact       TEXT,                 -- who it was sent to, for the record
  created_at    TEXT NOT NULL,
  last_used_at  TEXT
);

-- RESERVED, not yet served by any route. Model 2 in the playbook: "the band
-- plays Tuesday if 25 people put $10 on a tab". Schema settled now so the
-- events table above is built with it in mind; no money moves until the
-- PLCB read and the three-band test in PLAYBOOK-NIGHT-OUT.md section 9a.
CREATE TABLE IF NOT EXISTS campaigns (
  id            TEXT PRIMARY KEY,
  event_id      TEXT NOT NULL,
  lid           TEXT NOT NULL,
  threshold     INTEGER NOT NULL,     -- pledges needed to tip
  price_usd     REAL NOT NULL,        -- per pledge, credited to the tab
  deadline      TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'open',   -- open | tipped | failed | cancelled
  created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pledges (
  id            TEXT PRIMARY KEY,
  campaign_id   TEXT NOT NULL,
  email         TEXT NOT NULL,
  heads         INTEGER NOT NULL DEFAULT 1,
  payment_ref   TEXT,                 -- Stripe PaymentIntent, authorised not captured
  status        TEXT NOT NULL DEFAULT 'held',   -- held | captured | released | redeemed
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS pledges_campaign ON pledges (campaign_id);
