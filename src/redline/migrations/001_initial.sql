CREATE TABLE IF NOT EXISTS accounts (
 user_id TEXT PRIMARY KEY,
 balance INTEGER NOT NULL DEFAULT 0 CHECK(balance BETWEEN 0 AND 1000000000000),
 last_message REAL NOT NULL DEFAULT 0,
 last_daily REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS listings (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 seller_id TEXT NOT NULL,
 title TEXT NOT NULL,
 price INTEGER NOT NULL CHECK(price BETWEEN 1 AND 1000000000),
 kind TEXT NOT NULL CHECK(kind IN ('role','pack','market')),
 role_id TEXT,
 file_name TEXT,
 original_name TEXT,
 active INTEGER NOT NULL DEFAULT 1,
 created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS purchases (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id TEXT NOT NULL REFERENCES accounts(user_id),
 listing_id INTEGER NOT NULL REFERENCES listings(id),
 price INTEGER NOT NULL,
 created_at REAL NOT NULL,
 UNIQUE(user_id,listing_id)
);
CREATE TABLE IF NOT EXISTS ledger (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id TEXT NOT NULL,
 delta INTEGER NOT NULL,
 reason TEXT NOT NULL,
 actor_id TEXT,
 created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS purchases_user ON purchases(user_id);
CREATE INDEX IF NOT EXISTS ledger_user ON ledger(user_id);

