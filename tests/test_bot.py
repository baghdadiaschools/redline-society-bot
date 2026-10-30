import asyncio
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from redline.bot import Bot, BuyButton
from redline.config import Config
from redline.store import Store, UserError


class BotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        config = Config("TEST-NOT-A-TOKEN", 100, 1, root / "data", root / "backups", 24, 7, 8*1024**2, 64*1024**2, 25)
        self.store = Store(config.data / "bot.db", 1)
        self.bot = Bot(config, self.store)

    async def asyncTearDown(self):
        await self.bot.close()
        self.store.close()
        self.temp.cleanup()

    def interaction(self, user=2, guild=100, channel=200):
        i = MagicMock()
        i.guild_id = guild
        i.channel_id = channel
        i.user.id = user
        i.response.defer = AsyncMock()
        i.followup.send = AsyncMock()
        return i

    async def test_all_commands_serialize_without_token(self):
        commands = self.bot.tree.get_commands(guild=self.bot.guild_scope)
        self.assertEqual(len(commands), 19)
        for command in commands:
            payload = command.to_dict(self.bot.tree)
            self.assertTrue(payload["name"])

    async def test_wrong_guild_and_non_owner_rejected(self):
        with self.assertRaises(UserError):
            await self.bot.begin(self.interaction(guild=101))
        with self.assertRaises(UserError):
            await self.bot.begin(self.interaction(), owner=True)

    async def test_rewards_ignore_bots_webhooks_and_other_guilds(self):
        message = MagicMock()
        message.guild.id = 100
        message.author.id = 2
        message.author.bot = True
        message.webhook_id = None
        message.is_system.return_value = False
        await self.bot.on_message(message)
        self.assertEqual(self.store.balance(2), 0)
        message.author.bot = False
        message.webhook_id = 999
        await self.bot.on_message(message)
        self.assertEqual(self.store.balance(2), 0)
        message.webhook_id = None
        message.guild.id = 101
        await self.bot.on_message(message)
        self.assertEqual(self.store.balance(2), 0)
        message.guild.id = 100
        await self.bot.on_message(message)
        await self.bot.on_message(message)
        self.assertEqual(self.store.balance(2), 1)

    async def test_unpurchased_file_not_delivered(self):
        item = self.store.add_listing(1, "Pack", 50, "pack", file_name="abc")
        with self.assertRaises(UserError):
            await self.bot.deliver(self.interaction(), item)

    async def test_market_channel_enforced(self):
        with self.assertRaises(UserError):
            self.bot.require_market(self.interaction())
        self.store.configure(1, 200)
        self.bot.require_market(self.interaction())
        with self.assertRaises(UserError):
            self.bot.require_market(self.interaction(channel=201))

    async def test_oversized_upload_rejected_before_download(self):
        attachment = MagicMock()
        attachment.size = 100*1024**2
        attachment.save = AsyncMock()
        with self.assertRaises(UserError):
            await self.bot.upload(attachment)
        attachment.save.assert_not_called()

    async def test_delivery_failure_keeps_retryable_entitlement(self):
        item = self.store.add_listing(1, "Pack", 50, "pack", file_name="abc", original_name="pack.zip")
        (self.bot.materials / "abc").write_bytes(b"package")
        self.store.adjust(1, 2, "set", 100)
        self.store.buy(2, item)
        i = self.interaction()
        i.followup.send.side_effect = RuntimeError("simulated transport failure")
        with self.assertRaises(RuntimeError):
            await self.bot.deliver(i, item)
        self.assertTrue(self.store.owns(2, item))
        self.assertFalse(self.store.buy(2, item))
        i.followup.send.side_effect = None
        await self.bot.deliver(i, item)
        self.assertEqual(self.store.balance(2), 50)

    async def test_public_card_button_uses_atomic_purchase_and_private_delivery(self):
        item = self.store.add_listing(1, "Package", 50, "pack", file_name="abc",
                                      original_name="pack.zip", description="A safe test file")
        (self.bot.materials / "abc").write_bytes(b"package")
        self.store.adjust(1, 2, "set", 100)
        view = BuyButton(self.bot, item)
        self.assertEqual(view.children[0].custom_id, f"redline:buy:{item}")
        i = self.interaction()
        await view.buy(i)
        self.assertTrue(self.store.owns(2, item))
        self.assertEqual(self.store.balance(2), 50)
        self.assertTrue(i.response.defer.call_args.kwargs["ephemeral"])
        await view.buy(self.interaction())
        self.assertEqual(self.store.balance(2), 50)
        self.assertIn("A safe test file", self.bot.listing_embed(self.store.listing(item)).description)


if __name__ == "__main__":
    unittest.main()
