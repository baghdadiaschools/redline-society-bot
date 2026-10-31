import datetime
import re
import time

import discord

from .store import Store, UserError

WARN_ROLE = 1565764096773849210
KICK_ROLE = 1565777948840173729
BAN_ROLE = 1565768824404443346
ROLE_ROLES = {BAN_ROLE, 1565778010546638949}


def has_role(member: discord.Member, allowed: set[int], owner_id: int) -> bool:
    return member.id == owner_id or any(role.id in allowed for role in member.roles)


def duration(text: str) -> datetime.timedelta:
    match = re.fullmatch(r"(\d+)(m|h|d)", text.lower())
    if not match:
        raise UserError("Use a length like 30m, 2h, or 7d (maximum 28d).")
    number = int(match.group(1))
    delta = datetime.timedelta(**{"m": {"minutes": number}, "h": {"hours": number},
                                  "d": {"days": number}}[match.group(2)])
    if not datetime.timedelta(0) < delta <= datetime.timedelta(days=28):
        raise UserError("Mute length must be between 1 minute and 28 days.")
    return delta


class Moderation:
    def __init__(self, store: Store, owner_id: int):
        self.store = store
        self.owner_id = owner_id

    def record(self, actor: discord.Member, target: discord.Member, action: str, reason: str) -> None:
        self.store.db.execute("INSERT INTO moderation_actions(target_id,actor_id,action,reason,created_at) VALUES (?,?,?,?,?)",
                              (str(target.id), str(actor.id), action, reason[:500], time.time()))

    async def run(self, message: discord.Message, command: str, args: list[str]) -> bool:
        if command not in {"warn", "kick", "mute", "ban", "role", "history"}:
            return False
        if not isinstance(message.author, discord.Member) or not message.guild:
            return True
        actor = message.author
        allowed = ROLE_ROLES if command == "role" else {BAN_ROLE if command == "ban" else KICK_ROLE if command == "kick" else WARN_ROLE}
        if not has_role(actor, allowed, self.owner_id):
            raise UserError("You do not have the required staff role.")
        if command == "role":
            if len(args) < 3 or args[0] not in {"give", "delete"}:
                raise UserError("Use ?role give @member @role or ?role delete @member @role reason")
            action = args.pop(0)
        else:
            action = command
        if not args or not message.mentions:
            raise UserError("Mention a member to target.")
        target = await message.guild.fetch_member(message.mentions[0].id)
        if target.id == actor.id or target.id == self.owner_id or target.bot:
            raise UserError("This target cannot be moderated with this command.")
        if command == "history":
            rows = self.store.db.execute("SELECT actor_id,action,reason,created_at FROM moderation_actions WHERE target_id=? ORDER BY id DESC LIMIT 20", (str(target.id),)).fetchall()
            lines = [f"{r['action']} by {r['actor_id']} • {r['reason']} • <t:{int(r['created_at'])}:f>" for r in rows]
            await message.reply("Recent bot moderation history for this member:\n" + ("\n".join(lines) or "No recorded actions."), mention_author=False)
            return True
        if target.top_role >= actor.top_role and actor.id != self.owner_id:
            raise UserError("You cannot moderate a member with an equal or higher role.")
        if command == "role":
            if not message.role_mentions:
                raise UserError("Mention a role.")
            role = message.role_mentions[0]
            bot_id = self.store.setting("bot_id")
            if not bot_id:
                raise UserError("Bot is still connecting. Try again.")
            bot_member = message.guild.me or await message.guild.fetch_member(int(bot_id))
            if role.managed or role >= bot_member.top_role or role >= actor.top_role and actor.id != self.owner_id:
                raise UserError("That role is above your role or the bot's role.")
            reason = " ".join(args[2:]).strip() or "No reason provided"
            if action == "give":
                await target.add_roles(role, reason=reason)
            else:
                await target.remove_roles(role, reason=reason)
            self.record(actor, target, f"role_{action}:{role.id}", reason)
        else:
            rest = message.content.split(maxsplit=2)
            remainder = rest[2] if len(rest) > 2 else ""
            if command == "mute":
                parts = remainder.split(maxsplit=1)
                if not parts:
                    raise UserError("Use ?mute @member 30m reason")
                length = duration(parts[0])
                reason = parts[1] if len(parts) > 1 else "No reason provided"
                await target.timeout(length, reason=reason)
            else:
                reason = remainder or "No reason provided"
                if command == "kick":
                    await target.kick(reason=reason)
                elif command == "ban":
                    await target.ban(reason=reason, delete_message_seconds=0)
            self.record(actor, target, command, reason)
        await message.reply(f"Recorded {action} for {target.mention}.", mention_author=False)
        return True
