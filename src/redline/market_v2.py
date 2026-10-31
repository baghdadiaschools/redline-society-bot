import asyncio
from contextlib import closing
from pathlib import Path
import re
import uuid

import discord

from .store import Store, UserError


class BuyView(discord.ui.View):
    def __init__(self, market: "Marketplace", product_id: int):
        super().__init__(timeout=None)
        self.market = market
        self.add_item(BuyProduct(self, product_id))


class BuyProduct(discord.ui.Button[BuyView]):
    def __init__(self, view: BuyView, product_id: int):
        super().__init__(label="Purchase with R-coins", style=discord.ButtonStyle.green,
                         custom_id=f"redline:v2:buy:{product_id}")
        self.market = view
        self.product_id = product_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.market.market.buy(interaction, self.product_id)


class Marketplace:
    def __init__(self, bot: discord.Client, store: Store, owner_id: int, data: Path,
                 max_upload: int, storage_limit: int):
        self.bot = bot
        self.store = store
        self.owner_id = owner_id
        self.materials = data / "materials"
        self.materials.mkdir(parents=True, exist_ok=True)
        self.max_upload = max_upload
        self.storage_limit = storage_limit

    def register(self) -> None:
        for product in self.store.products_posted():
            self.bot.add_view(BuyView(self, product["id"]), message_id=int(product["message_id"]))

    def card(self, item: dict[str, object], removed: bool = False) -> discord.Embed:
        title = discord.utils.escape_markdown(discord.utils.escape_mentions(str(item["title"])))
        description = discord.utils.escape_markdown(discord.utils.escape_mentions(str(item["description"])))
        embed = discord.Embed(title=("Removed • " if removed else "") + title,
                              description=description or "No description", color=0xD52338 if not removed else 0x555555)
        embed.add_field(name="Price", value=f"{int(str(item['price'])):,} R-coins")
        mode = str(item["purchase_mode"])
        embed.add_field(name="Purchases per member", value="Once" if mode == "once" else
                        "Multiple" if mode == "repeat" else f"Up to {item['purchase_limit']}")
        embed.set_footer(text=f"Product #{item['id']} • {'Role' if item['kind'] == 'role' else 'Item'} • Private delivery")
        return embed

    async def save_files(self, attachments: list[discord.Attachment], visibility: str) -> list[tuple[str, str, str]]:
        result: list[tuple[str, str, str]] = []
        for attachment in attachments:
            if attachment.size <= 0 or attachment.size > self.max_upload:
                raise UserError(f"Each file must be 1 byte to {self.max_upload // 1024**2} MB.")
            if sum(p.stat().st_size for p in self.materials.iterdir() if p.is_file()) + attachment.size > self.storage_limit:
                raise UserError("File storage is full.")
            stored = uuid.uuid4().hex
            try:
                await attachment.save(self.materials / stored)
            except BaseException:
                (self.materials / stored).unlink(missing_ok=True)
                raise
            original = re.sub(r"[^A-Za-z0-9._-]", "_", attachment.filename)[:100].strip(".") or "file.bin"
            result.append((stored, original, visibility))
        return result

    async def post(self, product_id: int, previews: list[tuple[str, str, str]]) -> None:
        item = self.store.product(product_id)
        channel = await self.bot.fetch_channel(int(item["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            raise UserError("Configured marketplace channel is unavailable.")
        files = [discord.File(self.materials / name, filename=original) for name, original, _ in previews]
        try:
            post = await channel.send(embed=self.card(item), view=BuyView(self, product_id), files=files,
                                      allowed_mentions=discord.AllowedMentions.none())
        finally:
            for file in files:
                file.close()
        self.store.set_product_message(product_id, post.id)

    async def remove(self, actor: int, product_id: int) -> None:
        self.store.remove_product(actor, product_id)
        item = self.store.product(product_id)
        if item["message_id"]:
            try:
                channel = await self.bot.fetch_channel(int(item["channel_id"]))
                if isinstance(channel, discord.TextChannel):
                    post = await channel.fetch_message(int(item["message_id"]))
                    await post.edit(embed=self.card(item, removed=True), view=None)
            except discord.HTTPException:
                pass

    async def deliver(self, user: discord.User | discord.Member, order_id: int) -> None:
        row = self.store.db.execute("SELECT product_id FROM product_orders WHERE id=? AND buyer_id=?",
                                    (order_id, str(user.id))).fetchone()
        if not row:
            raise UserError("Order not found for your account.")
        item = self.store.product(row[0])
        if item["kind"] == "role":
            guild = self.bot.get_guild(int(self.store.setting("guild_id") or 0))
            if guild is None:
                raise UserError("Server unavailable. Try again later.")
            member = await guild.fetch_member(user.id)
            role = guild.get_role(int(item["role_id"]))
            if role is None:
                raise UserError("Role unavailable. Contact the owner.")
            await member.add_roles(role, reason=f"Redline order #{order_id}")
            await user.send(f"Your role purchase #{order_id} was delivered: {role.name}.")
        else:
            files = [discord.File(self.materials / file["stored_name"], filename=file["original_name"])
                     for file in self.store.product_files(row[0], "private")]
            try:
                if not files or any(not (self.materials / f["stored_name"]).is_file() for f in self.store.product_files(row[0], "private")):
                    raise UserError("Private files are unavailable. Contact the owner.")
                await user.send(f"Your private files for **{item['title']}** (order #{order_id}):", files=files)
            finally:
                for file in files:
                    file.close()

    async def buy(self, interaction: discord.Interaction, product_id: int) -> None:
        if interaction.guild_id != int(self.store.setting("guild_id") or 0):
            await interaction.response.send_message("Wrong server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            item = self.store.product(product_id)
            if item["kind"] == "role":
                guild = interaction.guild
                if guild is None or (role := guild.get_role(int(item["role_id"]))) is None or guild.me is None or role >= guild.me.top_role:
                    raise UserError("Role unavailable or above the bot's role. No coins charged.")
            else:
                if any(not (self.materials / f["stored_name"]).is_file() for f in self.store.product_files(product_id, "private")):
                    raise UserError("Private files unavailable. No coins charged.")
            user = interaction.user
            await user.create_dm()
            order = self.store.purchase_product(user.id, product_id)
            try:
                await self.deliver(user, order)
                outcome = f"Purchased! Check your DMs. Order #{order}."
            except (discord.HTTPException, UserError):
                outcome = f"Purchased, but delivery could not finish. Order #{order}. Enable DMs and send ?claim {order} to the bot."
            try:
                owner = await self.bot.fetch_user(self.owner_id)
                await owner.send(f"Product #{product_id} purchased by member ID {user.id}; order #{order}.")
            except discord.HTTPException:
                pass
            await interaction.followup.send(outcome, ephemeral=True)
        except UserError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except discord.HTTPException:
            await interaction.followup.send("Discord could not finish this action. Check your orders and DMs.", ephemeral=True)

    async def owner_command(self, message: discord.Message, text: str) -> bool:
        if not (text.startswith("marketrole ") or text.startswith("marketplace ")):
            return False
        if message.author.id != self.owner_id:
            raise UserError("Only the configured owner can manage products.")
        parts = text.split()
        if parts[:2] == ["marketplace", "channel"] and message.guild and message.channel_mentions:
            self.store.db.execute("INSERT INTO settings(key,value) VALUES ('product_channel',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                  (str(message.channel_mentions[0].id),))
            await message.reply(f"Marketplace channel set to {message.channel_mentions[0].mention}.", mention_author=False)
            return True
        if len(parts) >= 3 and parts[1] == "remove" or len(parts) >= 4 and parts[1:3] == ["item", "remove"]:
            product_id = int(parts[-1])
            await self.remove(message.author.id, product_id)
            await message.reply(f"Product #{product_id} removed from sale.", mention_author=False)
            return True
        channel_id = self.store.setting("product_channel")
        if not channel_id:
            raise UserError("Set ?marketplace channel #channel first.")
        if parts[:2] == ["marketrole", "add"] and message.guild:
            if not message.role_mentions or len(parts) < 4:
                raise UserError("Use ?marketrole add @role PRICE")
            role, price = message.role_mentions[0], int(parts[-1])
            if message.guild.me is None or role >= message.guild.me.top_role or role.managed or any(
                getattr(role.permissions, flag) for flag in ("administrator", "manage_roles", "ban_members", "kick_members", "manage_guild")):
                raise UserError("Only cosmetic roles below the bot's role may be sold.")
            product = self.store.add_product(self.owner_id, "role", role.name, "Cosmetic server role", price,
                                             "once", None, int(channel_id), role.id)
            await self.post(product, [])
            await message.reply(f"Role product #{product} posted.", mention_author=False)
            return True
        if parts[:3] == ["marketplace", "item", "add"] and isinstance(message.channel, discord.DMChannel):
            fields = [x.strip() for x in text[len("marketplace item add "):].split("|")]
            if len(fields) != 4:
                raise UserError("DM me: ?marketplace item add TITLE | DESCRIPTION | PRICE | once/repeat/limit:N")
            title, description, price_text, mode_text = fields
            price = int(price_text)
            mode, limit = ("limited", int(mode_text[6:])) if mode_text.startswith("limit:") else (mode_text, None)
            if not 1 <= price <= 1_000_000_000 or mode not in {"once", "repeat", "limited"}:
                raise UserError("Invalid price or purchase mode.")
            await message.reply("Send the public preview attachment(s) in your next DM. Send `skip` for none.")
            def check(m: discord.Message) -> bool:
                return m.author.id == self.owner_id and m.channel.id == message.channel.id
            try:
                previews_msg = await self.bot.wait_for("message", check=check, timeout=180)
                await message.channel.send("Now send the PRIVATE delivery file(s) in your next DM. These are never posted publicly.")
                private_msg = await self.bot.wait_for("message", check=check, timeout=180)
            except asyncio.TimeoutError:
                raise UserError("Upload timed out. Start again.") from None
            if not private_msg.attachments:
                raise UserError("At least one private file is required. Start again.")
            previews = await self.save_files(previews_msg.attachments[:5], "preview")
            private = await self.save_files(private_msg.attachments[:5], "private")
            product = self.store.add_product(self.owner_id, "item", title, description, price,
                                             mode, limit, int(channel_id), files=previews + private)
            await self.post(product, previews)
            await message.channel.send(f"Item #{product} posted. Private files stay in bot storage; buyers receive them by DM.")
            return True
        raise UserError("Use ?marketplace channel #channel, ?marketrole add @role PRICE, ?marketrole remove ID, or DM me ?marketplace item add TITLE | DESCRIPTION | PRICE | once/repeat/limit:N. To remove: ?marketplace item remove ID")
