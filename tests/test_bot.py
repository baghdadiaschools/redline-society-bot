import asyncio
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from redline.bot import Bot
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
        self.assertEqual(len(commands), 12)
        self.assertEqual({c.name for c in commands}, {"balance", "daily", "leaderboard", "coins", "coins_all", "help",
                                                      "warn", "kick", "mute", "ban", "role", "history"})
        for command in commands:
            payload = command.to_dict(self.bot.tree)
            self.assertTrue(payload["name"])

    async def test_help_omits_old_market_commands(self):
        help_command = self.bot.tree.get_command("help", guild=self.bot.guild_scope)
        assert help_command is not None
        i = self.interaction()
        await help_command.callback(i)
        answer = i.followup.send.call_args.args[0]
        for old in ("/shop", "/market", "/buy", "/sell", "/inventory", "/download", "/remove", "/race"):
            self.assertNotIn(old, answer)
        for command in ("/warn", "/kick", "/mute", "/ban", "/role give", "/role delete", "/history"):
            self.assertIn(command, answer)

    async def test_moderation_rejects_unprivileged_user_before_acknowledging(self):
        import discord
        i = self.interaction()
        i.guild = MagicMock()
        i.user = MagicMock(spec=discord.Member)
        i.user.id = 2
        i.user.roles = []
        # Exact role gate prevents action even when a slash command is visible.
        with self.assertRaises(UserError):
            await self.bot.moderate(i, MagicMock(), "ban", "test")
        i.response.defer.assert_not_awaited()

    async def test_wrong_guild_and_non_owner_rejected(self):
        with self.assertRaises(UserError):
            await self.bot.begin(self.interaction(guild=101))
        with self.assertRaises(UserError):
            await self.bot.begin(self.interaction(), owner=True)

    async def test_rewards_ignore_bots_webhooks_and_other_guilds(self):
        message = MagicMock()
        message.guild.id = 100
        message.author.id = 2
        message.content = "ordinary message"
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



if __name__ == "__main__":
    unittest.main()
