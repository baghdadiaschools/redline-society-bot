CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 kind TEXT NOT NULL CHECK(kind IN ('role','item')),
 title TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 price INTEGER NOT NULL CHECK(price BETWEEN 1 AND 1000000000),
 role_id TEXT,
 purchase_mode TEXT NOT NULL CHECK(purchase_mode IN ('once','repeat','limited')),
 purchase_limit INTEGER,
 channel_id TEXT NOT NULL,
 message_id TEXT,
 active INTEGER NOT NULL DEFAULT 1,
 created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS product_files (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 product_id INTEGER NOT NULL REFERENCES products(id),
 stored_name TEXT NOT NULL,
 original_name TEXT NOT NULL,
 visibility TEXT NOT NULL CHECK(visibility IN ('preview','private'))
);
CREATE TABLE IF NOT EXISTS product_orders (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 product_id INTEGER NOT NULL REFERENCES products(id),
 buyer_id TEXT NOT NULL,
 price INTEGER NOT NULL,
 created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS product_orders_buyer ON product_orders(buyer_id,product_id);
