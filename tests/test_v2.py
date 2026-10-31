from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from redline.moderation import duration, has_role, Moderation, WARN_ROLE, BAN_ROLE, ROLE_ROLES
from redline.store import Store, UserError
from redline.backup import create_backup
import zipfile


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

    def test_exact_moderator_roles(self):
        from unittest.mock import MagicMock
        member = MagicMock()
        member.id = 2
        member.roles = [MagicMock(id=WARN_ROLE)]
        self.assertTrue(has_role(member, {WARN_ROLE}, 1))
        self.assertFalse(has_role(member, {BAN_ROLE}, 1))
        self.assertFalse(has_role(member, ROLE_ROLES, 1))

    def test_owner_removes_only_warning_case_and_keeps_audit(self):
        from unittest.mock import MagicMock
        moderation = Moderation(self.store, 1)
        actor, target = MagicMock(), MagicMock()
        actor.id, target.id = 1, 2
        case = moderation.record(actor, target, "warn", "spam")
        other = moderation.record(actor, target, "mute", "timeout")
        with self.assertRaises(UserError):
            moderation.remove_warning(3, case, "unauthorized")
        with self.assertRaises(UserError):
            moderation.remove_warning(1, other, "wrong type")
        self.assertIn(f"#{case}", moderation.remove_warning(1, case, "appeal accepted"))
        self.assertIsNone(self.store.db.execute("SELECT 1 FROM moderation_actions WHERE id=?", (case,)).fetchone())
        self.assertIsNotNone(self.store.db.execute("SELECT 1 FROM moderation_actions WHERE id=?", (other,)).fetchone())
        audit = self.store.db.execute("SELECT action,reason FROM moderation_actions WHERE target_id='2' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(audit["action"], "unwarn")
        self.assertIn(f"case #{case}", audit["reason"])
        with self.assertRaises(UserError):
            moderation.remove_warning(1, case, "again")

    def test_private_product_file_is_in_backup(self):
        data = Path(self.temp.name)
        (data / "materials").mkdir()
        (data / "materials" / "secret").write_bytes(b"private pack")
        self.store.add_product(1, "item", "Pack", "", 10, "once", None, 100,
                               files=[("secret", "pack.zip", "private")])
        archive = create_backup(data, data / "backups")
        with zipfile.ZipFile(archive) as saved:
            self.assertEqual(saved.read("materials/secret"), b"private pack")
