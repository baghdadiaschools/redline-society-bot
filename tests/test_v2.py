from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from redline.moderation import duration
from redline.store import Store, UserError


class NewMarketplaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "bot.db", 1)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_purchase_modes_and_atomic_coin_debit(self):
        with self.assertRaises(UserError):
            self.store.add_product(2, "item", "Pack", "Description", 5, "once", None, 100,
                                   files=[("hidden", "private.zip", "private")])
        item = self.store.add_product(1, "item", "Pack", "Description", 5, "limited", 2, 100,
                                      files=[("preview", "image.png", "preview"),
                                             ("hidden", "private.zip", "private")])
        self.store.adjust(1, 2, "set", 10)
        self.store.purchase_product(2, item)
        self.store.purchase_product(2, item)
        self.assertEqual(self.store.balance(2), 0)
        with self.assertRaises(UserError):
            self.store.purchase_product(2, item)
        self.assertEqual(len(self.store.product_files(item, "private")), 1)
        self.store.remove_product(1, item)
        with self.assertRaises(UserError):
            self.store.purchase_product(3, item)

    def test_once_and_insufficient_funds(self):
        item = self.store.add_product(1, "role", "Cosmetic", "", 100, "once", None, 100, role_id=456)
        with self.assertRaises(UserError):
            self.store.purchase_product(2, item)
        self.store.adjust(1, 2, "set", 100)
        self.store.purchase_product(2, item)
        with self.assertRaises(UserError):
            self.store.purchase_product(2, item)
        self.assertEqual(self.store.balance(2), 0)

    def test_duration_bounds(self):
        self.assertEqual(duration("2h"), timedelta(hours=2))
        for text in ("0m", "29d", "1w", "abc"):
            with self.assertRaises(UserError):
                duration(text)
