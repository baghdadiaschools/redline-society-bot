from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from redline.store import Store, UserError, MAX_BALANCE
from redline.backup import create_backup, restore
from redline.runtime import FileLock


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.store = Store(self.data / "bot.db", 1)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def pack(self, price=50, seller=3):
        return self.store.add_listing(seller, "Test pack", price, "market", file_name="abc", original_name="test.zip")

    def test_message_and_daily_cooldowns_survive_restart(self):
        self.assertTrue(self.store.reward(2, now=100000))
        self.assertFalse(self.store.reward(2, now=100029))
        self.assertTrue(self.store.reward(2, now=100030))
        self.assertTrue(self.store.reward(2, daily=True, now=100000))
        self.store.close()
        self.store = Store(self.data / "bot.db", 1)
        self.assertFalse(self.store.reward(2, daily=True, now=186399))
        self.assertTrue(self.store.reward(2, daily=True, now=186400))
        self.assertEqual(self.store.balance(2), 202)

    def test_owner_only_controls_including_admin_impersonation(self):
        for call in [lambda: self.store.adjust(2, 2, "set", 100),
                     lambda: self.store.configure(2, 123),
                     lambda: self.store.add_listing(2, "VIP", 1, "role", role_id=10),
                     lambda: self.store.add_listing(2, "Official", 1, "pack", file_name="abc")]:
            with self.assertRaises(UserError):
                call()

    def test_duplicate_buy_is_idempotent_and_seller_paid_once(self):
        item = self.pack()
        self.store.adjust(1, 2, "set", 100)
        self.assertTrue(self.store.buy(2, item))
        self.assertFalse(self.store.buy(2, item))
        self.assertEqual(self.store.balance(2), 50)
        self.assertEqual(self.store.balance(3), 50)
        self.assertTrue(self.store.owns(2, item))

    def test_insufficient_funds_no_partial_credit_or_purchase(self):
        item = self.pack()
        with self.assertRaises(UserError):
            self.store.buy(2, item)
        self.assertEqual(self.store.balance(3), 0)
        self.assertFalse(self.store.owns(2, item))

    def test_seller_overflow_rolls_back_buyer_debit(self):
        item = self.pack()
        self.store.adjust(1, 2, "set", 100)
        self.store.adjust(1, 3, "set", MAX_BALANCE)
        with self.assertRaises(UserError):
            self.store.buy(2, item)
        self.assertEqual(self.store.balance(2), 100)

    def test_retired_items_keep_purchase_access(self):
        item = self.pack()
        self.store.adjust(1, 2, "set", 100)
        self.store.buy(2, item)
        with self.assertRaises(UserError):
            self.store.retire(4, item)
        self.store.retire(3, item)
        self.assertTrue(self.store.owns(2, item))
        self.assertEqual(self.store.inventory(2, 1)[0]["id"], item)
        with self.assertRaises(UserError):
            self.store.buy(4, item)

    def test_reset_all_preserves_inventory_and_cooldown(self):
        item = self.pack()
        self.store.reward(2, daily=True, now=100000)
        self.store.buy(2, item)
        self.store.adjust(1, None, "reset", 0)
        self.assertEqual(self.store.balance(2), 0)
        self.assertEqual(self.store.balance(3), 0)
        self.assertTrue(self.store.owns(2, item))
        self.assertFalse(self.store.reward(2, daily=True, now=100001))

    def test_all_adjustment_is_atomic(self):
        self.store.adjust(1, 2, "set", 10)
        self.store.adjust(1, 3, "set", 0)
        with self.assertRaises(UserError):
            self.store.adjust(1, None, "add", -5)
        self.assertEqual(self.store.balance(2), 10)

    def test_concurrent_buy_does_not_double_spend(self):
        item = self.pack()
        self.store.adjust(1, 2, "set", 50)
        def buy(_):
            store = Store(self.data / "bot.db", 1)
            try:
                return store.buy(2, item)
            finally:
                store.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(buy, range(8)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.store.balance(2), 0)
        self.assertEqual(self.store.balance(3), 50)

    def test_migration_is_not_reapplied(self):
        self.store.adjust(1, 2, "set", 123)
        self.store.close()
        self.store = Store(self.data / "bot.db", 1)
        self.assertEqual(self.store.balance(2), 123)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM migrations").fetchone()[0], 2)

    def test_owner_edits_any_listing_and_post_metadata_survives_reopen(self):
        item = self.store.add_listing(3, "Member pack", 20, "market", file_name="abc",
                                      description="First description")
        self.store.set_post(item, 100, 200)
        with self.assertRaises(UserError):
            self.store.edit_listing(3, item, 30, "Changed")
        self.store.edit_listing(1, item, 30, "Changed")
        self.store.close()
        self.store = Store(self.data / "bot.db", 1)
        self.assertEqual(self.store.listing(item)["description"], "Changed")
        self.assertEqual(self.store.listing(item)["price"], 30)
        self.assertEqual(self.store.posted_active()[0]["post_message_id"], "200")
        self.store.retire(1, item)
        self.assertEqual(self.store.posted_active(), [])

    def test_backup_restore_includes_retired_material_and_balances(self):
        material = self.data / "materials"
        material.mkdir()
        (material / "abc").write_bytes(b"private sample content")
        item = self.pack()
        self.store.adjust(1, 2, "set", 75)
        self.store.buy(2, item)
        self.store.retire(3, item)
        archive = create_backup(self.data, self.root / "backups")
        target = self.root / "restored"
        restore(archive, target)
        restored = Store(target / "bot.db", 1)
        try:
            self.assertEqual(restored.balance(2), 25)
            self.assertTrue(restored.owns(2, item))
            self.assertEqual((target / "materials" / "abc").read_bytes(), b"private sample content")
        finally:
            restored.close()
        with self.assertRaises(ValueError):
            restore(archive, self.data)

    def test_backup_retention_and_missing_file_fails(self):
        dest = self.root / "backups"
        for _ in range(3):
            create_backup(self.data, dest, keep=2)
        self.assertEqual(len(list(dest.glob("*.zip"))), 2)
        self.pack()
        with self.assertRaises(FileNotFoundError):
            create_backup(self.data, dest)
        self.assertEqual(len(list(dest.glob("*.zip"))), 2)
        self.assertEqual(len(list(dest.glob("*.partial"))), 0)

    def test_second_worker_is_blocked(self):
        with FileLock(str(self.root / "worker.lock")):
            with self.assertRaises(TimeoutError):
                with FileLock(str(self.root / "worker.lock")):
                    pass

    def test_invalid_price_and_self_purchase(self):
        with self.assertRaises(UserError):
            self.pack(price=-1)
        item = self.pack()
        with self.assertRaises(UserError):
            self.store.buy(3, item)


if __name__ == "__main__":
    unittest.main()
