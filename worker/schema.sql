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
