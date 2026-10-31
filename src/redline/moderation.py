"""Role-gated moderation actions used by guild slash commands."""
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

    def authorize(self, actor: discord.Member, action: str) -> None:
        allowed = ROLE_ROLES if action in {"role_give", "role_delete"} else {
            BAN_ROLE if action == "ban" else KICK_ROLE if action == "kick" else WARN_ROLE
        }
        if not has_role(actor, allowed, self.owner_id):
            raise UserError("You do not have the required staff role.")

    def record(self, actor: discord.Member, target: discord.Member, action: str, reason: str) -> None:
        self.store.db.execute("INSERT INTO moderation_actions(target_id,actor_id,action,reason,created_at) VALUES (?,?,?,?,?)",
                              (str(target.id), str(actor.id), action, reason[:500], time.time()))

    def check_target(self, actor: discord.Member, target: discord.Member, action: str) -> None:
        self.authorize(actor, action)
        if action == "history":
            return
        if target.id == actor.id or target.id == self.owner_id or target.bot:
            raise UserError("This target cannot be moderated with this command.")
        if target.top_role >= actor.top_role and actor.id != self.owner_id:
            raise UserError("You cannot moderate a member with an equal or higher role.")

    async def action(self, guild: discord.Guild, actor: discord.Member, target: discord.Member,
                     action: str, reason: str = "No reason provided", length: str = "",
                     role: discord.Role | None = None) -> str:
        self.check_target(actor, target, action)
        if action == "history":
            rows = self.store.db.execute(
                "SELECT actor_id,action,reason,created_at FROM moderation_actions WHERE target_id=? ORDER BY id DESC LIMIT 20",
                (str(target.id),)).fetchall()
            lines = [f"{r['action']} by {r['actor_id']} | {r['reason']} | <t:{int(r['created_at'])}:f>" for r in rows]
            report = "Recent bot moderation history for this member:\n" + ("\n".join(lines) or "No recorded actions.")
            return report if len(report) <= 1900 else report[:1860] + "\n… Older entries were omitted."

        reason = (reason.strip() or "No reason provided")[:500]
        if action in {"role_give", "role_delete"}:
            if role is None:
                raise UserError("Choose a role.")
            bot_id = self.store.setting("bot_id")
            if not bot_id:
                raise UserError("Bot is still connecting. Try again.")
            bot_member = guild.me or await guild.fetch_member(int(bot_id))
            if role.managed or role >= bot_member.top_role or (role >= actor.top_role and actor.id != self.owner_id):
                raise UserError("That role is above your role or the bot's role.")
            if action == "role_give":
                await target.add_roles(role, reason=reason)
            else:
                await target.remove_roles(role, reason=reason)
            recorded = f"{action}:{role.id}"
        elif action == "warn":
            recorded = action
        elif action == "mute":
            await target.timeout(duration(length), reason=reason)
            recorded = action
        elif action == "kick":
            await target.kick(reason=reason)
            recorded = action
        elif action == "ban":
            await target.ban(reason=reason, delete_message_seconds=0)
            recorded = action
        else:
            raise UserError("Unknown moderation action.")
        self.record(actor, target, recorded, reason)
        return f"Recorded {action.replace('_', ' ')} for {target.mention}."
