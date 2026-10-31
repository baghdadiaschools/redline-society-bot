import asyncio
from contextlib import suppress
import logging
import random
import time
from typing import Literal

import discord
from discord import app_commands

from .backup import create_backup
from .config import Config
from .store import Store, UserError
from .market_v2 import Marketplace
from .moderation import Moderation

log = logging.getLogger("redline")


def safe_title(value: str) -> str:
    value = " ".join(value.split())[:60]
    return discord.utils.escape_markdown(discord.utils.escape_mentions(value))


class CommandTree(app_commands.CommandTree["Bot"]):
    async def on_error(self, interaction: discord.Interaction,
                       error: app_commands.AppCommandError) -> None:
        await self.client.command_error(interaction, error)


class Bot(discord.Client):
    def __init__(self, config: Config, store: Store):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        intents.dm_messages = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.config = config
        self.store = store
        self.tree = CommandTree(self)
        self.guild_scope = discord.Object(id=config.guild_id)
        self.background: list[asyncio.Task[None]] = []
        self.active: set[asyncio.Task[object]] = set()
        self.stopping = False
        self.marketplace = Marketplace(self, store, config.owner_id, config.data,
                                       config.max_upload, config.storage_limit)
        self.moderation = Moderation(store, config.owner_id)
        self.store.db.execute("INSERT INTO settings(key,value) VALUES ('guild_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                              (str(config.guild_id),))
        self.register_commands()

    async def setup_hook(self) -> None:
        self.marketplace.register()
        await self.tree.sync(guild=self.guild_scope)
        self.background = [asyncio.create_task(self.backup_loop()),
                           asyncio.create_task(self.health_loop())]
        log.info("Slash commands synced for configured server")

    async def on_ready(self) -> None:
        if self.user:
            self.store.db.execute("INSERT INTO settings(key,value) VALUES ('bot_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(self.user.id),))
        log.info("Redline Society bot connected")

    async def on_message(self, message: discord.Message) -> None:
        if self.stopping or message.author.bot or message.webhook_id:
            return
        if message.content.startswith("?"):
            if message.guild and message.guild.id != self.config.guild_id:
                return
            try:
                text = message.content[1:].strip()
                command, *args = text.split()
                if await self.moderation.run(message, command.lower(), args):
                    return
                if await self.marketplace.owner_command(message, text.lower() if text.startswith("marketrole ") or text.startswith("marketplace channel") or text.startswith("marketplace item remove") else text):
                    return
                if command.lower() == "orders":
                    if message.guild:
                        raise UserError("DM the bot ?orders to keep your purchases private.")
                    rows = self.store.db.execute("SELECT id,product_id FROM product_orders WHERE buyer_id=? ORDER BY id DESC LIMIT 20", (str(message.author.id),)).fetchall()
                    await message.reply("Your orders: " + (", ".join(f"#{r['id']} (product {r['product_id']})" for r in rows) or "none"), mention_author=False)
                elif command.lower() == "claim" and len(args) == 1:
                    if message.guild:
                        raise UserError("DM the bot ?claim ORDER_ID for private delivery.")
                    await self.marketplace.deliver(message.author, int(args[0]))
                    await message.reply("Order delivered to your DMs.", mention_author=False)
                elif command.lower() == "help":
                    await message.reply("Coins: /daily /balance /leaderboard; owner: /coins /coins_all. Staff: ?warn ?kick ?mute ?ban ?role give/delete ?history. Marketplace: ?marketplace channel #channel; ?marketrole add/remove; owner DM ?marketplace item add/remove; buyers use product buttons, ?orders and ?claim ORDER_ID. Games: ?roulette and ?blackjack are free practice with no stakes or rewards.", mention_author=False)
                elif command.lower() in {"roulette", "blackjack"}:
                    await message.reply("Free practice: " + (f"Roulette landed on {random.randrange(37)}." if command.lower() == "roulette" else f"Blackjack practice hand: {random.randint(12,21)}. No R-coins are spent or awarded."), mention_author=False)
            except (UserError, ValueError, IndexError) as exc:
                await message.reply(str(exc) if isinstance(exc, UserError) else "Check command format. Use ?help.", mention_author=False)
            except discord.HTTPException:
                log.warning("prefix_command_discord_error command=%s", message.content.split(maxsplit=1)[0])
                await message.reply("Discord could not complete that action. Check bot permissions and DMs.", mention_author=False)
            return
        if not message.guild or message.guild.id != self.config.guild_id or message.is_system():
            return
        try:
            self.store.reward(message.author.id)
        except Exception:
            log.error("message_reward_failed")

    async def command_error(self, interaction: discord.Interaction,
                            error: app_commands.AppCommandError) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, UserError):
            text = str(original)
        elif isinstance(original, app_commands.CommandOnCooldown):
            text = f"Try again in {original.retry_after:.0f} seconds."
        elif isinstance(original, discord.HTTPException):
            text = "Discord could not complete that action. Check bot permissions and DMs. For item delivery, DM ?orders and ?claim ORDER_ID."
            log.warning("discord_request_failed status=%s", original.status)
        else:
            # Do not log tokens, signed attachment URLs, file contents, or request payloads.
            text = "The action could not finish. For item delivery, DM ?orders and ?claim ORDER_ID."
            log.error("command_failed type=%s command=%s", type(original).__name__,
                      interaction.command.name if interaction.command else "unknown")
        await self.reply_error(interaction, text)

    async def reply_error(self, interaction: discord.Interaction, text: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)

    async def begin(self, i: discord.Interaction, owner: bool = False) -> None:
        if self.stopping:
            raise UserError("Bot is restarting. Please try again shortly.")
        if i.guild_id != self.config.guild_id:
            raise UserError("This bot only operates in its configured server.")
        if owner:
            self.store.owner(i.user.id)
        task = asyncio.current_task()
        if task:
            self.active.add(task)
            task.add_done_callback(self.active.discard)
        await i.response.defer(ephemeral=True, thinking=True)

    async def backup_loop(self) -> None:
        while not self.is_closed():
            try:
                path = await asyncio.to_thread(create_backup, self.config.data, self.config.backups,
                                               self.config.backup_keep)
                log.info("backup_completed archive=%s", path.name)
            except Exception as exc:
                log.error("backup_failed type=%s", type(exc).__name__)
            await asyncio.sleep(self.config.backup_hours * 3600)

    async def health_loop(self) -> None:
        last_ready = time.monotonic()
        while not self.is_closed():
            if self.is_ready():
                last_ready = time.monotonic()
                (self.config.data / "heartbeat").write_text(str(time.time()))
            elif time.monotonic() - last_ready > 600:
                log.error("gateway_unavailable_for_10_minutes restarting_worker")
                await self.close()
                return
            await asyncio.sleep(30)

    async def shutdown(self) -> None:
        self.stopping = True
        if self.active:
            _, pending = await asyncio.wait(self.active, timeout=100)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        for task in self.background:
            task.cancel()
        for task in self.background:
            with suppress(asyncio.CancelledError):
                await task
        await self.close()

    def register_commands(self) -> None:
        tree, guild = self.tree, self.guild_scope

        @tree.command(name="balance", description="Check R-coins", guild=guild)
        async def balance(i: discord.Interaction, member: discord.Member | None = None) -> None:
            await self.begin(i)
            user = member or i.user
            await i.followup.send(f"{safe_title(user.display_name)}: **{self.store.balance(user.id):,} R-coins**", ephemeral=True)

        @tree.command(name="daily", description="Claim 100 R-coins every 24 hours", guild=guild)
        async def daily(i: discord.Interaction) -> None:
            await self.begin(i)
            claimed = self.store.reward(i.user.id, daily=True)
            await i.followup.send("You received 100 R-coins!" if claimed else "Daily reward is on cooldown or your balance is full.", ephemeral=True)

        @tree.command(name="leaderboard", description="Top ten R-coin balances", guild=guild)
        async def leaderboard(i: discord.Interaction) -> None:
            await self.begin(i)
            rows = self.store.db.execute("SELECT user_id,balance FROM accounts ORDER BY balance DESC LIMIT 10").fetchall()
            await i.followup.send("**R-coin leaderboard**\n" + ("\n".join(f"{n}. <@{r[0]}> - {r[1]:,}" for n, r in enumerate(rows, 1)) or "No balances yet."), ephemeral=True)

        @tree.command(name="coins", description="Owner only: adjust one member's balance", guild=guild)
        async def coins(i: discord.Interaction, member: discord.Member,
                        mode: Literal["set", "add", "reset"], amount: int = 0) -> None:
            await self.begin(i, owner=True)
            self.store.adjust(i.user.id, member.id, mode, amount)
            await i.followup.send(f"Balance now: {self.store.balance(member.id):,} R-coins.", ephemeral=True)

        @tree.command(name="coins_all", description="Owner only: adjust all existing balances", guild=guild)
        async def coins_all(i: discord.Interaction, mode: Literal["set", "add", "reset"],
                            confirmation: str, amount: int = 0) -> None:
            await self.begin(i, owner=True)
            if confirmation != "CONFIRM ALL":
                raise UserError("Enter CONFIRM ALL exactly.")
            count = self.store.adjust(i.user.id, None, mode, amount)
            await i.followup.send(f"Updated {count} existing accounts.", ephemeral=True)

        @tree.command(name="help", description="Redline Society command guide", guild=guild)
        async def help_command(i: discord.Interaction) -> None:
            await self.begin(i)
            await i.followup.send("**Redline Society**\nEarn 1 R-coin per eligible message (30s cooldown). /daily gives 100 every 24h.\n/balance /leaderboard /coins /coins_all\nStaff: ?warn ?kick ?mute ?ban ?role give or delete ?history\nMarketplace: public Buy buttons, ?orders, ?claim ORDER_ID\nOwner: ?marketplace channel #channel; ?marketrole add or remove; DM ?marketplace item add or remove\n?roulette and ?blackjack are free practice without stakes or rewards.", ephemeral=True)
