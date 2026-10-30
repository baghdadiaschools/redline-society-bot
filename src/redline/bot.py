import asyncio
from contextlib import closing, suppress
import logging
from pathlib import Path
import random
import re
import time
from typing import Literal
import uuid

import discord
from discord import app_commands

from .backup import create_backup
from .config import Config
from .store import Store, UserError

log = logging.getLogger("redline")


def safe_title(value: str) -> str:
    value = " ".join(value.split())[:60]
    return discord.utils.escape_markdown(discord.utils.escape_mentions(value))


class PurchaseButton(discord.ui.Button["BuyButton"]):
    def __init__(self, view: "BuyButton", listing_id: int):
        super().__init__(label="Buy with R-coins", style=discord.ButtonStyle.green,
                         custom_id=f"redline:buy:{listing_id}")
        self.owner_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.owner_view.buy(interaction)


class BuyButton(discord.ui.View):
    def __init__(self, bot: "Bot", listing_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.listing_id = listing_id
        self.add_item(PurchaseButton(self, listing_id))

    async def buy(self, interaction: discord.Interaction) -> None:
        try:
            await self.bot.begin(interaction)
            await self.bot.purchase(interaction, self.listing_id)
        except app_commands.AppCommandError as exc:
            await self.bot.command_error(interaction, exc)
        except UserError as exc:
            await self.bot.reply_error(interaction, str(exc))
        except discord.HTTPException as exc:
            log.warning("discord_request_failed status=%s", exc.status)
            await self.bot.reply_error(interaction, "Delivery failed. If charged, use /download at no cost.")
        except Exception as exc:
            log.error("button_purchase_failed type=%s", type(exc).__name__)
            await self.bot.reply_error(interaction, "Purchase could not finish. Check /inventory and retry /download.")


class CommandTree(app_commands.CommandTree["Bot"]):
    async def on_error(self, interaction: discord.Interaction,
                       error: app_commands.AppCommandError) -> None:
        await self.client.command_error(interaction, error)


class Bot(discord.Client):
    def __init__(self, config: Config, store: Store):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.config = config
        self.store = store
        self.tree = CommandTree(self)
        self.guild_scope = discord.Object(id=config.guild_id)
        self.upload_lock = asyncio.Lock()
        self.background: list[asyncio.Task[None]] = []
        self.active: set[asyncio.Task[object]] = set()
        self.stopping = False
        self.materials = config.data / "materials"
        self.materials.mkdir(parents=True, exist_ok=True)
        self.register_commands()

    async def setup_hook(self) -> None:
        for item in self.store.posted_active():
            self.add_view(BuyButton(self, int(item["id"])), message_id=int(item["post_message_id"]))
        await self.tree.sync(guild=self.guild_scope)
        self.background = [asyncio.create_task(self.backup_loop()),
                           asyncio.create_task(self.health_loop())]
        log.info("Slash commands synced for configured server")

    async def on_ready(self) -> None:
        log.info("Redline Society bot connected")

    async def on_message(self, message: discord.Message) -> None:
        if self.stopping or not message.guild or message.guild.id != self.config.guild_id:
            return
        if message.author.bot or message.webhook_id or message.is_system():
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
            text = "Discord could not complete delivery. If charged, use /download to retry at no cost. Check bot permissions and file limits."
            log.warning("discord_request_failed status=%s", original.status)
        else:
            # Do not log tokens, signed attachment URLs, file contents, or request payloads.
            text = "The action could not finish. If you purchased an item, check /inventory and retry /download."
            log.error("command_failed type=%s command=%s", type(original).__name__,
                      interaction.command.name if interaction.command else "unknown")
        await self.reply_error(interaction, text)

    async def reply_error(self, interaction: discord.Interaction, text: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)

    def listing_embed(self, item: dict[str, object]) -> discord.Embed:
        kind = str(item["kind"])
        embed = discord.Embed(title=f"#{item['id']} • {safe_title(str(item['title']))}",
                              description=safe_title(str(item["description"])) or "No description provided.",
                              color=discord.Color.red())
        embed.add_field(name="Price", value=f"{int(str(item['price'])):,} R-coins")
        embed.add_field(name="Type", value={"market": "Member package", "pack": "Official package",
                                           "role": "Official role"}[kind])
        if kind == "market":
            embed.add_field(name="Seller", value=f"<@{item['seller_id']}>")
        embed.set_footer(text="Press Buy for private delivery. Purchases are permanent while storage survives.")
        return embed

    async def publish_listing(self, i: discord.Interaction, listing_id: int) -> bool:
        channel_id = self.store.setting("market_channel")
        if not channel_id or not i.guild:
            return False
        item = self.store.listing(listing_id)
        if item["post_message_id"]:
            raise UserError("This listing already has a public card.")
        channel = i.guild.get_channel(int(channel_id)) or await i.guild.fetch_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            raise UserError("Marketplace channel is unavailable. Set /market_channel again.")
        try:
            post = await channel.send(embed=self.listing_embed(item), view=BuyButton(self, listing_id),
                                      allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            log.warning("listing_card_post_failed id=%s status=%s", listing_id, exc.status)
            raise UserError(f"Listing #{listing_id} was saved but its public card could not be posted. Check Send Messages and Embed Links permissions, then use /listing_post.") from exc
        self.store.set_post(listing_id, channel.id, post.id)
        return True

    async def refresh_listing(self, item: dict[str, object], withdrawn: bool = False) -> None:
        if not item["post_message_id"] or not item["post_channel_id"]:
            return
        try:
            channel = self.get_channel(int(str(item["post_channel_id"]))) or await self.fetch_channel(int(str(item["post_channel_id"])))
            if not isinstance(channel, discord.TextChannel):
                return
            post = await channel.fetch_message(int(str(item["post_message_id"])))
            embed = self.listing_embed(item)
            if withdrawn:
                embed.title = f"WITHDRAWN • {embed.title}"
                embed.color = discord.Color.dark_grey()
                embed.set_footer(text="No longer for sale. Previous buyers may use /download.")
            await post.edit(embed=embed, view=None if withdrawn else BuyButton(self, int(str(item["id"]))))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
            log.warning("listing_card_refresh_failed id=%s type=%s", item["id"], type(exc).__name__)

    async def purchase(self, i: discord.Interaction, listing_id: int) -> None:
        item = self.store.listing(listing_id)
        if item["kind"] == "market":
            self.require_market(i)
        if item["kind"] == "role":
            await self.role_for(i, int(item["role_id"]))
        elif not (self.materials / item["file_name"]).is_file():
            raise UserError("File unavailable. You have not been charged.")
        self.store.buy(i.user.id, listing_id)
        await self.deliver(i, listing_id)

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

    def require_market(self, i: discord.Interaction) -> None:
        channel = self.store.setting("market_channel")
        if not channel or str(i.channel_id) != channel:
            raise UserError("Use the marketplace channel selected by the owner.")

    async def upload(self, attachment: discord.Attachment) -> tuple[str, str]:
        if attachment.size <= 0 or attachment.size > self.config.max_upload:
            raise UserError(f"Upload must be between 1 byte and {self.config.max_upload // 1024**2} MB.")
        used = sum(p.stat().st_size for p in self.materials.iterdir() if p.is_file())
        if used + attachment.size > self.config.storage_limit:
            raise UserError("Material storage is full. Ask the owner to increase capacity.")
        original = re.sub(r"[^A-Za-z0-9._-]", "_", Path(attachment.filename).name)[:100]
        original = original.strip(".") or "package.bin"
        name = uuid.uuid4().hex
        path = self.materials / name
        try:
            await asyncio.wait_for(attachment.save(path), timeout=90)
            if path.stat().st_size > self.config.max_upload:
                raise UserError("File exceeds upload limit.")
            return name, original
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    async def role_for(self, i: discord.Interaction, role_id: int) -> discord.Role:
        assert i.guild is not None
        roles = await i.guild.fetch_roles()
        role = discord.utils.get(roles, id=role_id)
        me = i.guild.me
        if not role or not me or role.managed or role.is_default() or role >= me.top_role:
            raise UserError("Role is missing, managed, or above the bot. Ask the owner to fix its position.")
        if not me.guild_permissions.manage_roles:
            raise UserError("Bot needs Manage Roles permission.")
        dangerous = ("administrator", "manage_guild", "manage_roles", "manage_channels", "kick_members",
                     "ban_members", "moderate_members", "manage_messages", "manage_webhooks")
        if any(getattr(role.permissions, flag) for flag in dangerous):
            raise UserError("Only non-moderation roles can be sold.")
        return role

    async def deliver(self, i: discord.Interaction, listing_id: int) -> None:
        if not self.store.owns(i.user.id, listing_id):
            raise UserError("Purchase this item first with /buy.")
        item = self.store.listing(listing_id)
        if item["kind"] == "role":
            role = await self.role_for(i, int(item["role_id"]))
            assert i.guild is not None
            member = await i.guild.fetch_member(i.user.id)
            await member.add_roles(role, reason=f"Redline purchase {listing_id}")
            await i.followup.send(f"Role delivered: {safe_title(role.name)}.", ephemeral=True)
        else:
            path = self.materials / item["file_name"]
            if not path.is_file():
                raise UserError("Your purchase is recorded, but its file is missing. Ask the owner to restore a backup.")
            with closing(discord.File(path, filename=item["original_name"])) as file:
                await i.followup.send(f"Your purchase: {safe_title(item['title'])}", file=file, ephemeral=True)

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

        @tree.command(name="daily", description="Claim 100 R-coins once every 24 hours", guild=guild)
        async def daily(i: discord.Interaction) -> None:
            await self.begin(i)
            claimed = self.store.reward(i.user.id, daily=True)
            await i.followup.send("You received **100 R-coins**!" if claimed else "Daily reward is on cooldown (24 hours from your last claim), or your balance is full.", ephemeral=True)

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
                raise UserError("Enter CONFIRM ALL in confirmation to change every existing account.")
            count = self.store.adjust(i.user.id, None, mode, amount)
            await i.followup.send(f"Updated {count} existing accounts. Purchase ownership and cooldowns are preserved.", ephemeral=True)

        @tree.command(name="market_channel", description="Owner only: choose marketplace channel", guild=guild)
        async def market_channel(i: discord.Interaction, channel: discord.TextChannel) -> None:
            await self.begin(i, owner=True)
            self.store.configure(i.user.id, channel.id)
            await i.followup.send(f"Marketplace channel set to {channel.mention}.", ephemeral=True)

        @tree.command(name="role_add", description="Owner only: add a role to the shop", guild=guild)
        async def role_add(i: discord.Interaction, role: discord.Role,
                           price: app_commands.Range[int, 1, 1000000000],
                           description: app_commands.Range[str, 1, 500] = "") -> None:
            await self.begin(i, owner=True)
            await self.role_for(i, role.id)
            listing_id = self.store.add_listing(i.user.id, role.name, price, "role", role_id=role.id, description=description)
            posted = await self.publish_listing(i, listing_id)
            await i.followup.send(f"Role listed as #{listing_id} for {price:,} R-coins." +
                                  (" Public Buy card posted." if posted else " Set /market_channel, then use /listing_post to publish its Buy card."), ephemeral=True)

        @tree.command(name="pack_add", description="Owner only: upload an official shop package", guild=guild)
        async def pack_add(i: discord.Interaction, title: app_commands.Range[str, 1, 80],
                           price: app_commands.Range[int, 1, 1000000000], file: discord.Attachment,
                           description: app_commands.Range[str, 1, 500] = "") -> None:
            await self.begin(i, owner=True)
            async with self.upload_lock:
                name, original = await self.upload(file)
                try:
                    listing_id = self.store.add_listing(i.user.id, title, price, "pack", file_name=name, original_name=original, description=description)
                except BaseException:
                    (self.materials / name).unlink(missing_ok=True)
                    raise
            posted = await self.publish_listing(i, listing_id)
            await i.followup.send(f"Official package #{listing_id} added. Use /shop to view." +
                                  (" Public Buy card posted." if posted else " Set /market_channel, then use /listing_post to publish its Buy card."), ephemeral=True)

        @tree.command(name="sell", description="Upload your package in the configured marketplace", guild=guild)
        @app_commands.checks.cooldown(1, 60, key=lambda i: i.user.id)
        async def sell(i: discord.Interaction, title: app_commands.Range[str, 1, 80],
                       price: app_commands.Range[int, 1, 1000000000], file: discord.Attachment,
                       description: app_commands.Range[str, 1, 500] = "") -> None:
            await self.begin(i)
            self.require_market(i)
            async with self.upload_lock:
                count = self.store.db.execute("SELECT COUNT(*) FROM listings WHERE seller_id=? AND kind='market' AND active=1", (str(i.user.id),)).fetchone()[0]
                if count >= self.config.max_listings:
                    raise UserError("You reached the active listing limit. Remove an old listing first.")
                name, original = await self.upload(file)
                try:
                    listing_id = self.store.add_listing(i.user.id, title, price, "market", file_name=name, original_name=original, description=description)
                except BaseException:
                    (self.materials / name).unlink(missing_ok=True)
                    raise
            await self.publish_listing(i, listing_id)
            await i.followup.send(f"Marketplace listing #{listing_id} posted with a Buy button. You earn {price:,} R-coins per purchase.", ephemeral=True)

        async def show(i: discord.Interaction, market: bool, page: int) -> None:
            await self.begin(i)
            if market:
                self.require_market(i)
            rows = self.store.catalog(market, page)
            lines = [f"**#{r['id']} · {safe_title(r['title'])}** — {r['price']:,} R-coins ({r['kind']})" for r in rows]
            await i.followup.send(f"**{'Marketplace' if market else 'Official shop'} · Page {page}**\n" + ("\n".join(lines) or "No listings on this page.") + "\nUse /buy with an item ID. Increase page to browse more.", ephemeral=True)

        @tree.command(name="shop", description="Browse official roles and packages", guild=guild)
        async def shop(i: discord.Interaction, page: app_commands.Range[int, 1, 100000] = 1) -> None:
            await show(i, False, page)

        @tree.command(name="market", description="Browse member packages in the marketplace", guild=guild)
        async def market(i: discord.Interaction, page: app_commands.Range[int, 1, 100000] = 1) -> None:
            await show(i, True, page)

        @tree.command(name="buy", description="Purchase a role or package with R-coins", guild=guild)
        async def buy(i: discord.Interaction, item_id: int) -> None:
            await self.begin(i)
            await self.purchase(i, item_id)

        @tree.command(name="download", description="Redeliver a purchased file or role at no cost", guild=guild)
        @app_commands.checks.cooldown(1, 10, key=lambda i: i.user.id)
        async def download(i: discord.Interaction, item_id: int) -> None:
            await self.begin(i)
            await self.deliver(i, item_id)

        @tree.command(name="inventory", description="See your permanent purchases", guild=guild)
        async def inventory(i: discord.Interaction, page: app_commands.Range[int, 1, 100000] = 1) -> None:
            await self.begin(i)
            rows = self.store.inventory(i.user.id, page)
            text = "\n".join(f"#{r['id']} · {safe_title(r['title'])}" for r in rows)
            await i.followup.send(f"**Purchases · Page {page}**\n" + (text or "No purchases on this page.") + "\nUse /download with the item ID.", ephemeral=True)

        @tree.command(name="remove", description="Remove a listing; existing buyers keep access", guild=guild)
        async def remove(i: discord.Interaction, item_id: int) -> None:
            await self.begin(i)
            self.store.retire(i.user.id, item_id)
            await self.refresh_listing(self.store.listing(item_id), withdrawn=True)
            await i.followup.send("Listing removed from sale. Existing purchases and files are preserved.", ephemeral=True)

        @tree.command(name="listing_edit", description="Owner only: edit any listing's price or description", guild=guild)
        async def listing_edit(i: discord.Interaction, item_id: int,
                               price: app_commands.Range[int, 1, 1000000000] | None = None,
                               description: app_commands.Range[str, 1, 500] | None = None) -> None:
            await self.begin(i, owner=True)
            self.store.edit_listing(i.user.id, item_id, price, description)
            await self.refresh_listing(self.store.listing(item_id))
            await i.followup.send(f"Listing #{item_id} updated. Existing buyers retain access.", ephemeral=True)

        @tree.command(name="listing_post", description="Owner only: publish an existing listing's Buy card", guild=guild)
        async def listing_post(i: discord.Interaction, item_id: int) -> None:
            await self.begin(i, owner=True)
            item = self.store.listing(item_id)
            if not item["active"]:
                raise UserError("This listing is withdrawn.")
            if not await self.publish_listing(i, item_id):
                raise UserError("Set /market_channel first.")
            await i.followup.send(f"Listing #{item_id} posted with a Buy button.", ephemeral=True)

        @tree.command(name="leaderboard", description="Top 10 R-coin balances", guild=guild)
        async def leaderboard(i: discord.Interaction) -> None:
            await self.begin(i)
            rows = self.store.db.execute("SELECT user_id,balance FROM accounts ORDER BY balance DESC LIMIT 10").fetchall()
            await i.followup.send("**R-coin leaderboard**\n" + ("\n".join(f"{n}. <@{r[0]}> — {r[1]:,}" for n, r in enumerate(rows, 1)) or "No balances yet."), ephemeral=True)

        @tree.command(name="race", description="Free practice race — no stakes, prizes or coin changes", guild=guild)
        async def race(i: discord.Interaction) -> None:
            await self.begin(i)
            await i.followup.send(f"🏁 Practice lap: **{random.uniform(55, 95):.3f} seconds**. No coins spent or awarded.", ephemeral=True)

        @tree.command(name="help", description="Redline Society command guide", guild=guild)
        async def help_command(i: discord.Interaction) -> None:
            await self.begin(i)
            await i.followup.send("**Redline Society bot**\nEarn 1 R-coin per message, at most once every 30 seconds. Bots and webhooks excluded.\n/daily — 100 coins every 24 hours\n/balance · /leaderboard\n/shop · /market · /buy\n/sell — upload your own package in the market channel\n/inventory · /download — purchases are retained across restarts\n/remove — withdraw your listing\n/race — free practice game\nOwner: /coins · /coins_all · /market_channel · /role_add · /pack_add\nR-coins are virtual points, with no real-money purchase or cash-out. Only upload materials you have rights to distribute.", ephemeral=True)
