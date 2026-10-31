from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator

MAX_BALANCE = 1_000_000_000_000


class UserError(Exception):
    """An expected error safe to show to the member."""


class Store:
    def __init__(self, path: Path, owner_id: int):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.owner_id = str(owner_id)
        self.db = sqlite3.connect(path, isolation_level=None, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY)")
        for migration in sorted(files("redline").joinpath("migrations").iterdir(),
                                key=lambda p: p.name):
            if not migration.name.endswith(".sql"):
                continue
            if not self.db.execute("SELECT 1 FROM migrations WHERE name=?",
                                   (migration.name,)).fetchone():
                # Each migration is SQL only; record version in the same transaction.
                name = migration.name.replace("'", "''")
                try:
                    self.db.executescript("BEGIN IMMEDIATE;\n" + migration.read_text()
                                          + f"\nINSERT INTO migrations VALUES ('{name}'); COMMIT;")
                except Exception:
                    if self.db.in_transaction:
                        self.db.rollback()
                    raise

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def owner(self, actor: int) -> None:
        if str(actor) != self.owner_id:
            raise UserError("Only the configured owner can do that.")

    def ensure(self, user: int | str) -> None:
        self.db.execute("INSERT OR IGNORE INTO accounts(user_id) VALUES (?)", (str(user),))

    def balance(self, user: int | str) -> int:
        row = self.db.execute("SELECT balance FROM accounts WHERE user_id=?", (str(user),)).fetchone()
        return int(row[0]) if row else 0

    def change(self, user: int | str, delta: int, reason: str, actor: int | None = None) -> None:
        self.ensure(user)
        new = self.balance(user) + delta
        if not 0 <= new <= MAX_BALANCE:
            raise UserError("Insufficient R-coins or balance limit reached.")
        self.db.execute("UPDATE accounts SET balance=? WHERE user_id=?", (new, str(user)))
        self.db.execute("INSERT INTO ledger(user_id,delta,reason,actor_id,created_at) VALUES (?,?,?,?,?)",
                        (str(user), delta, reason, str(actor) if actor else None, time.time()))

    def reward(self, user: int, daily: bool = False, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        column, cooldown, amount = ("last_daily", 86400, 100) if daily else ("last_message", 30, 1)
        with self.transaction():
            self.ensure(user)
            last = self.db.execute(f"SELECT {column} FROM accounts WHERE user_id=?",
                                   (str(user),)).fetchone()[0]
            if last and now - last < cooldown:
                return False
            if self.balance(user) + amount > MAX_BALANCE:
                return False
            self.change(user, amount, "daily" if daily else "message")
            self.db.execute(f"UPDATE accounts SET {column}=? WHERE user_id=?", (now, str(user)))
        return True

    def adjust(self, actor: int, target: int | None, mode: str, amount: int) -> int:
        self.owner(actor)
        if mode not in {"set", "add", "reset"}:
            raise UserError("Invalid adjustment mode.")
        if not -MAX_BALANCE <= amount <= MAX_BALANCE:
            raise UserError("Amount out of range.")
        with self.transaction():
            if target is not None:
                self.ensure(target)
            users = [str(target)] if target is not None else [r[0] for r in self.db.execute(
                "SELECT user_id FROM accounts").fetchall()]
            for user in users:
                delta = amount if mode == "add" else (amount if mode == "set" else 0) - self.balance(user)
                self.change(user, delta, f"owner:{mode}", actor)
        return len(users)

    def setting(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else None

    def configure(self, actor: int, channel: int) -> None:
        self.owner(actor)
        self.db.execute("INSERT INTO settings VALUES ('market_channel',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(channel),))

    def add_listing(self, actor: int, title: str, price: int, kind: str,
                    role_id: int | None = None, file_name: str | None = None,
                    original_name: str | None = None, description: str = "") -> int:
        if kind in {"role", "pack"}:
            self.owner(actor)
        if kind not in {"role", "pack", "market"} or not 1 <= price <= 1_000_000_000:
            raise UserError("Invalid listing type or price.")
        if not 1 <= len(title.strip()) <= 80:
            raise UserError("Title must be 1–80 characters.")
        if len(description) > 500:
            raise UserError("Description must be 500 characters or fewer.")
        if (kind == "role" and not role_id) or (kind != "role" and not file_name):
            raise UserError("Listing requires a role or an uploaded file.")
        cursor = self.db.execute("INSERT INTO listings(seller_id,title,price,kind,role_id,file_name,original_name,created_at,description) VALUES (?,?,?,?,?,?,?,?,?)",
                                 (str(actor), title.strip(), price, kind, str(role_id) if role_id else None,
                                  file_name, original_name, time.time(), description.strip()))
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def listing(self, listing_id: int) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
        if not row:
            raise UserError("Listing not found.")
        return dict(row)

    def catalog(self, market: bool, page: int) -> list[dict[str, Any]]:
        op = "=" if market else "!="
        return [dict(r) for r in self.db.execute(
            f"SELECT * FROM listings WHERE active=1 AND kind {op} 'market' ORDER BY id LIMIT 10 OFFSET ?",
            ((page - 1) * 10,)).fetchall()]

    def owns(self, user: int, listing_id: int) -> bool:
        return bool(self.db.execute("SELECT 1 FROM purchases WHERE user_id=? AND listing_id=?",
                                    (str(user), listing_id)).fetchone())

    def buy(self, user: int, listing_id: int) -> bool:
        with self.transaction():
            item = self.listing(listing_id)
            if self.owns(user, listing_id):
                return False
            if not item["active"]:
                raise UserError("This listing is no longer for sale.")
            if item["seller_id"] == str(user):
                raise UserError("You cannot buy your own listing.")
            self.change(user, -item["price"], f"purchase:{listing_id}")
            if item["kind"] == "market":
                self.change(item["seller_id"], item["price"], f"sale:{listing_id}")
            self.db.execute("INSERT INTO purchases(user_id,listing_id,price,created_at) VALUES (?,?,?,?)",
                            (str(user), listing_id, item["price"], time.time()))
        return True

    def retire(self, actor: int, listing_id: int) -> None:
        item = self.listing(listing_id)
        if str(actor) != self.owner_id and not (item["kind"] == "market" and item["seller_id"] == str(actor)):
            raise UserError("Only the owner or this marketplace seller can remove it.")
        self.db.execute("UPDATE listings SET active=0 WHERE id=?", (listing_id,))

    def set_post(self, listing_id: int, channel_id: int, message_id: int) -> None:
        self.db.execute("UPDATE listings SET post_channel_id=?, post_message_id=? WHERE id=?",
                        (str(channel_id), str(message_id), listing_id))

    def posted_active(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM listings WHERE active=1 AND post_message_id IS NOT NULL").fetchall()]

    def edit_listing(self, actor: int, listing_id: int, price: int | None,
                     description: str | None) -> None:
        self.owner(actor)
        item = self.listing(listing_id)
        if not item["active"]:
            raise UserError("This listing is withdrawn.")
        if price is None and description is None:
            raise UserError("Provide a price or description to change.")
        if price is not None and not 1 <= price <= 1_000_000_000:
            raise UserError("Price must be between 1 and 1,000,000,000.")
        if description is not None and len(description) > 500:
            raise UserError("Description must be 500 characters or fewer.")
        self.db.execute("UPDATE listings SET price=?, description=? WHERE id=?",
                        (price if price is not None else item["price"],
                         description.strip() if description is not None else item["description"], listing_id))

    def inventory(self, user: int, page: int) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT l.* FROM listings l JOIN purchases p ON l.id=p.listing_id WHERE p.user_id=? ORDER BY p.id DESC LIMIT 10 OFFSET ?",
                                               (str(user), (page - 1) * 10)).fetchall()]

    def product(self, product_id: int) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not row:
            raise UserError("Product not found.")
        return dict(row)

    def product_files(self, product_id: int, visibility: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM product_files WHERE product_id=? AND visibility=? ORDER BY id",
            (product_id, visibility)).fetchall()]

    def products_posted(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM products WHERE active=1 AND message_id IS NOT NULL").fetchall()]

    def add_product(self, actor: int, kind: str, title: str, description: str, price: int,
                    mode: str, limit: int | None, channel_id: int, role_id: int | None = None,
                    files: list[tuple[str, str, str]] | None = None) -> int:
        self.owner(actor)
        if kind not in {"role", "item"} or mode not in {"once", "repeat", "limited"}:
            raise UserError("Invalid product type or purchase mode.")
        if not 1 <= len(title) <= 80 or len(description) > 1000 or not 1 <= price <= 1_000_000_000:
            raise UserError("Check title (1-80), description (up to 1000), and price.")
        if mode == "limited" and (limit is None or not 1 <= limit <= 1000):
            raise UserError("Limited products need a purchase limit of 1-1000.")
        if kind == "role" and not role_id or kind == "item" and not any(f[2] == "private" for f in files or []):
            raise UserError("A role or at least one private delivery file is required.")
        with self.transaction():
            cursor = self.db.execute("INSERT INTO products(kind,title,description,price,role_id,purchase_mode,purchase_limit,channel_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                                     (kind, title, description, price, str(role_id) if role_id else None,
                                      mode, limit if mode == "limited" else None, str(channel_id), time.time()))
            assert cursor.lastrowid is not None
            product_id = cursor.lastrowid
            for stored, original, visibility in files or []:
                self.db.execute("INSERT INTO product_files(product_id,stored_name,original_name,visibility) VALUES (?,?,?,?)",
                                (product_id, stored, original, visibility))
        return product_id

    def set_product_message(self, product_id: int, message_id: int) -> None:
        self.db.execute("UPDATE products SET message_id=? WHERE id=?", (str(message_id), product_id))

    def remove_product(self, actor: int, product_id: int) -> None:
        self.owner(actor)
        self.product(product_id)
        self.db.execute("UPDATE products SET active=0 WHERE id=?", (product_id,))

    def purchase_product(self, buyer: int, product_id: int) -> int:
        with self.transaction():
            item = self.product(product_id)
            if not item["active"]:
                raise UserError("This product is no longer for sale.")
            count = self.db.execute("SELECT COUNT(*) FROM product_orders WHERE buyer_id=? AND product_id=?",
                                    (str(buyer), product_id)).fetchone()[0]
            if item["purchase_mode"] == "once" and count:
                raise UserError("You already purchased this. Use ?orders to see your purchases.")
            if item["purchase_mode"] == "limited" and count >= item["purchase_limit"]:
                raise UserError("You reached this product's purchase limit.")
            self.change(buyer, -item["price"], f"product:{product_id}")
            cursor = self.db.execute("INSERT INTO product_orders(product_id,buyer_id,price,created_at) VALUES (?,?,?,?)",
                                     (product_id, str(buyer), item["price"], time.time()))
            assert cursor.lastrowid is not None
            return cursor.lastrowid

    def close(self) -> None:
        self.db.close()
