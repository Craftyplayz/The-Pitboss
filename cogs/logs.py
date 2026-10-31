"""Server Log: records every Discord event the bot can see into the events table, for the control panel's Logs tab.

Discord doesn't give bots member bios, and banners only by request, so those can't be logged."""
import json
import os
import re
import time
from pathlib import Path

import discord
from discord.ext import commands

from core import db
from core.events import KINDS, describe, diff, show

# saved next to the database so the control panel (same volume) can show them after Discord's links expire
FILES = Path(os.environ.get("DB_PATH", "data/pitboss.db")).parent / "logfiles"
# shortcut: files over this size are listed but not saved, and nothing is ever pruned; add a cleanup job if the volume fills up
FILE_MAX = 25 * 1024 * 1024
SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")

CHANNEL_ATTRS = ["name", "topic", "category", "position", "nsfw", "slowmode_delay", "bitrate", "user_limit",
                 "rtc_region", "video_quality_mode", "default_auto_archive_duration", "type"]
THREAD_ATTRS = ["name", "archived", "locked", "slowmode_delay", "auto_archive_duration", "applied_tags", "pinned"]
ROLE_ATTRS = ["name", "colour", "hoist", "mentionable", "position", "permissions", "icon", "unicode_emoji"]
GUILD_ATTRS = ["name", "description", "icon", "banner", "splash", "owner", "afk_channel", "afk_timeout",
               "system_channel", "rules_channel", "public_updates_channel", "verification_level",
               "explicit_content_filter", "default_notifications", "mfa_level", "vanity_url_code", "preferred_locale",
               "premium_tier", "premium_subscription_count", "features"]
EVENT_ATTRS = ["name", "description", "start_time", "end_time", "status", "location", "channel"]


def who(user):
    """'Display (@username)', or just '@username' when they're the same."""
    if user is None:
        return None
    name = getattr(user, "name", str(user))
    display = getattr(user, "display_name", name)
    return f"{display} (@{name})" if display != name else f"@{name}"


def activity_text(a):
    if isinstance(a, discord.CustomActivity):
        return f"custom status: {(str(a.emoji) + ' ') if a.emoji else ''}{a.name or ''}".strip()
    if isinstance(a, discord.Spotify):
        return f"listening to {a.title} by {a.artist} on Spotify"
    if isinstance(a, discord.Streaming):
        return f"streaming {a.name} ({a.url})"
    verb = {discord.ActivityType.playing: "playing", discord.ActivityType.listening: "listening to",
            discord.ActivityType.watching: "watching", discord.ActivityType.competing: "competing in"}
    details = " · ".join(x for x in (getattr(a, "details", None), getattr(a, "state", None)) if x)
    return f"{verb.get(a.type, 'doing')} {a.name}" + (f" ({details})" if details else "")


class Logs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        FILES.mkdir(parents=True, exist_ok=True)

    def ours(self, guild_or_id):
        gid = getattr(guild_or_id, "id", guild_or_id)
        return gid is not None and gid == int(os.environ.get("GUILD_ID", 0))

    def log(self, kind, summary, user=None, channel=None, message_id=None, user_id=None, channel_id=None, **data):
        db.add_event(self.bot.db, int(time.time()), kind, KINDS[kind], summary[:1000],
                     user_id=getattr(user, "id", user_id), user_name=who(user),
                     channel_id=getattr(channel, "id", channel_id), channel_name=getattr(channel, "name", None),
                     message_id=message_id, data={k: v for k, v in data.items() if v not in (None, "", [], {})})

    async def save(self, asset_or_attachment, name):
        """Download to logfiles/, returning the file name, or None if too big or it failed."""
        size = getattr(asset_or_attachment, "size", 0)
        if size > FILE_MAX:
            return None
        path = FILES / SAFE_RE.sub("_", name)[:150]
        try:
            if not path.exists():
                await asset_or_attachment.save(path)
            return path.name
        except (discord.HTTPException, OSError) as e:
            print(f"logs: saving {name} failed: {e}")
            return None

    async def save_avatar(self, asset, user_id):
        if asset is None:
            return None
        return await self.save(asset, f"avatar_{user_id}_{asset.key}.{'gif' if asset.is_animated() else 'png'}")

    def channel_of(self, channel_id):
        return self.bot.get_channel(channel_id)

    # ---- messages ----

    @commands.Cog.listener()
    async def on_message(self, message):
        if not self.ours(message.guild):
            return
        files = [{"name": a.filename, "size": a.size, "type": a.content_type, "url": a.url,
                  "file": await self.save(a, f"{message.id}_{i}_{a.filename}")} for i, a in enumerate(message.attachments)]
        reply = message.reference.message_id if message.reference else None
        self.log("message_sent", f"{who(message.author)} in #{message.channel.name}: {message.content or '(no text)'}",
                 message.author, message.channel, message.id, content=message.content, files=files, reply_to=reply,
                 stickers=[s.name for s in message.stickers], embeds=len(message.embeds) or None,
                 bot=message.author.bot or None, jump=message.jump_url)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        if not self.ours(payload.guild_id) or "content" not in payload.data:
            return
        new = payload.data["content"]
        old = payload.cached_message.content if payload.cached_message else self.original(payload.message_id, None)[2]
        if old == new:
            return  # Discord also sends edits for link previews loading
        author = payload.message.author if payload.message else None
        channel = self.channel_of(payload.channel_id)
        self.log("message_edited", f"{who(author) or 'Someone'} edited a message in #{getattr(channel, 'name', '?')}: "
                 f"{old if old is not None else '(not seen before)'} → {new}",
                 author, channel, payload.message_id, channel_id=payload.channel_id,
                 before=old, content=new, jump=payload.message.jump_url if payload.message else None)

    def original(self, message_id, cached):
        """(author, author id, content, files) of a message, from the cache or our own log. Files come from the log
        when we can: those are the copies we saved, which outlive Discord's links."""
        history = db.message_history(self.bot.db, message_id)
        sent = json.loads(history[0]["data"] or "{}") if history and history[0]["kind"] == "message_sent" else {}
        files = sent.get("files", [])
        if cached:
            return cached.author, cached.author.id, cached.content, files or [{"name": a.filename, "url": a.url} for a in cached.attachments]
        if not history:
            return None, None, None, []
        return None, history[-1]["user_id"], json.loads(history[-1]["data"] or "{}").get("content"), files

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        if not self.ours(payload.guild_id):
            return
        author, author_id, content, files = self.original(payload.message_id, payload.cached_message)
        channel = self.channel_of(payload.channel_id)
        name = who(author) or (who(self.bot.get_user(author_id)) if author_id else None) or "unknown author"
        self.log("message_deleted", f"Message by {name} deleted in #{getattr(channel, 'name', '?')}: "
                 f"{content if content is not None else '(sent before logging started)'}",
                 author, channel, payload.message_id, user_id=author_id, channel_id=payload.channel_id,
                 content=content, files=files)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        if not self.ours(payload.guild_id):
            return
        channel = self.channel_of(payload.channel_id)
        messages = []
        for mid in sorted(payload.message_ids):
            author, author_id, content, files = self.original(mid, next((m for m in payload.cached_messages if m.id == mid), None))
            messages.append({"id": mid, "author": who(author) or author_id, "content": content, "files": files})
        self.log("messages_bulk_deleted", f"{len(payload.message_ids)} messages bulk deleted in #{getattr(channel, 'name', '?')}",
                 None, channel, channel_id=payload.channel_id, messages=messages)

    @commands.Cog.listener()
    async def on_guild_channel_pins_update(self, channel, last_pin):
        if self.ours(channel.guild):
            self.log("pins_changed", f"Pins changed in #{channel.name}", None, channel, last_pin=show(last_pin))

    # ---- reactions and polls ----

    async def reaction(self, payload, kind, verb):
        if not self.ours(payload.guild_id):
            return
        user = payload.member or self.bot.get_user(payload.user_id)
        channel = self.channel_of(payload.channel_id)
        self.log(kind, f"{who(user) or payload.user_id} {verb} {payload.emoji} on a message in #{getattr(channel, 'name', '?')}",
                 user, channel, payload.message_id, user_id=payload.user_id, channel_id=payload.channel_id,
                 emoji=str(payload.emoji), super_reaction=payload.burst or None)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        await self.reaction(payload, "reaction_added", "reacted")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        await self.reaction(payload, "reaction_removed", "removed reaction")

    @commands.Cog.listener()
    async def on_raw_reaction_clear(self, payload):
        if self.ours(payload.guild_id):
            channel = self.channel_of(payload.channel_id)
            self.log("reactions_cleared", f"All reactions cleared on a message in #{getattr(channel, 'name', '?')}",
                     None, channel, payload.message_id, channel_id=payload.channel_id)

    @commands.Cog.listener()
    async def on_raw_reaction_clear_emoji(self, payload):
        if self.ours(payload.guild_id):
            channel = self.channel_of(payload.channel_id)
            self.log("reactions_cleared", f"{payload.emoji} reactions cleared on a message in #{getattr(channel, 'name', '?')}",
                     None, channel, payload.message_id, channel_id=payload.channel_id, emoji=str(payload.emoji))

    async def poll_vote(self, payload, kind, verb):
        if not self.ours(payload.guild_id):
            return
        user, channel = self.bot.get_user(payload.user_id), self.channel_of(payload.channel_id)
        self.log(kind, f"{who(user) or payload.user_id} {verb} answer {payload.answer_id} in a poll in #{getattr(channel, 'name', '?')}",
                 user, channel, payload.message_id, user_id=payload.user_id, channel_id=payload.channel_id, answer=payload.answer_id)

    @commands.Cog.listener()
    async def on_raw_poll_vote_add(self, payload):
        await self.poll_vote(payload, "poll_vote_added", "voted for")

    @commands.Cog.listener()
    async def on_raw_poll_vote_remove(self, payload):
        await self.poll_vote(payload, "poll_vote_removed", "removed their vote for")

    # ---- members and profiles ----

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if not self.ours(member.guild):
            return
        age = (discord.utils.utcnow() - member.created_at).days
        self.log("member_joined", f"{who(member)} joined (account {age} days old)", member,
                 account_created=member.created_at.isoformat(), bot=member.bot or None,
                 avatar=await self.save_avatar(member.avatar, member.id), member_count=member.guild.member_count)

    @commands.Cog.listener()
    async def on_raw_member_remove(self, payload):
        if not self.ours(payload.guild_id):
            return
        user = payload.user
        roles = [r.name for r in getattr(user, "roles", [])[1:]]
        joined = getattr(user, "joined_at", None)
        self.log("member_left", f"{who(user)} left the server", user, roles=roles,
                 joined_at=joined.isoformat() if joined else None)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        if self.ours(guild):
            self.log("member_banned", f"{who(user)} was banned", user)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        if self.ours(guild):
            self.log("member_unbanned", f"{who(user)} was unbanned", user)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if not self.ours(after.guild):
            return
        changes = diff(before, after, ["nick", "timed_out_until", "premium_since", "pending", "guild_avatar"])
        added = [r.name for r in after.roles if r not in before.roles]
        removed = [r.name for r in before.roles if r not in after.roles]
        if added:
            changes["roles added"] = ["", ", ".join(added)]
        if removed:
            changes["roles removed"] = [", ".join(removed), ""]
        if not changes:
            return
        files = {}
        if "guild_avatar" in changes:
            files = {"before_file": await self.save_avatar(before.guild_avatar, after.id),
                     "after_file": await self.save_avatar(after.guild_avatar, after.id)}
            changes["server avatar"] = ["old picture", "new picture"]
            del changes["guild_avatar"]
        parts = []
        if added:
            parts.append(f"got {', '.join(added)}")
        if removed:
            parts.append(f"lost {', '.join(removed)}")
        rest = {k: v for k, v in changes.items() if not k.startswith("roles")}
        if rest:
            parts.append(describe(rest))
        self.log("member_updated", f"{who(after)}: {'; '.join(parts)}", after, changes=changes, **files)

    @commands.Cog.listener()
    async def on_user_update(self, before, after):
        guild = self.bot.get_guild(int(os.environ.get("GUILD_ID", 0)))
        if not guild or not guild.get_member(after.id):
            return
        changes = diff(before, after, ["name", "global_name", "avatar", "avatar_decoration"])
        if not changes:
            return
        files = {}
        if "avatar" in changes:
            files = {"before_file": await self.save_avatar(before.avatar, after.id),
                     "after_file": await self.save_avatar(after.avatar, after.id)}
            changes["avatar"] = ["old picture", "new picture"]  # the hashes mean nothing to a reader
        self.log("user_updated", f"{who(after)} changed their profile: {describe(changes)}", after, changes=changes, **files)

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if not self.ours(after.guild):
            return
        changes = {}
        if before.status != after.status:
            changes["status"] = [str(before.status), str(after.status)]
        devices = {d: (str(getattr(before, f"{d}_status")), str(getattr(after, f"{d}_status"))) for d in ("desktop", "mobile", "web")}
        for d, (old, new) in devices.items():
            if old != new:
                changes[f"{d} status"] = [old, new]
        old_acts, new_acts = {activity_text(a) for a in before.activities}, {activity_text(a) for a in after.activities}
        if old_acts != new_acts:
            changes["activity"] = [show(old_acts - new_acts), show(new_acts - old_acts)]
        if changes:
            self.log("presence_updated", f"{who(after)}: {describe(changes)}", after, changes=changes,
                     activities=sorted(new_acts))

    # ---- voice ----

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not self.ours(member.guild):
            return
        if before.channel != after.channel:
            if not before.channel:
                what = f"joined 🔊{after.channel.name}"
            elif not after.channel:
                what = f"left 🔊{before.channel.name}"
            else:
                what = f"moved from 🔊{before.channel.name} to 🔊{after.channel.name}"
            changes = {"channel": [show(before.channel), show(after.channel)]}
        else:
            changes = diff(before, after, ["self_mute", "self_deaf", "mute", "deaf", "self_stream", "self_video",
                                           "suppress", "requested_to_speak_at"])
            if not changes:
                return
            what = describe(changes)
        self.log("voice_updated", f"{who(member)} {what}", member, after.channel or before.channel, changes=changes)

    # ---- channels, threads and roles ----

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        if self.ours(channel.guild):
            self.log("channel_created", f"Channel #{channel.name} created ({show(channel.type)})", None, channel)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if self.ours(channel.guild):
            self.log("channel_deleted", f"Channel #{channel.name} deleted ({show(channel.type)})", None, channel)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if not self.ours(after.guild):
            return
        changes = diff(before, after, CHANNEL_ATTRS)
        if before.overwrites != after.overwrites:
            def perms(ch):
                return {show(t): {k: v for k, v in o if v is not None} for t, o in ch.overwrites.items()}
            old, new = perms(before), perms(after)
            for target in sorted(set(old) | set(new)):
                if old.get(target) != new.get(target):
                    changes[f"permissions for {target}"] = [show(sorted(f"{k}={v}" for k, v in old.get(target, {}).items())),
                                                            show(sorted(f"{k}={v}" for k, v in new.get(target, {}).items()))]
        if changes:
            self.log("channel_updated", f"#{after.name} changed: {describe(changes)}", None, after, changes=changes)

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        if self.ours(thread.guild):
            self.log("thread_created", f"Thread {thread.name} created in #{show(thread.parent)} by {who(thread.owner) or thread.owner_id}",
                     thread.owner, thread, user_id=thread.owner_id)

    @commands.Cog.listener()
    async def on_raw_thread_delete(self, payload):
        if self.ours(payload.guild_id):
            name = payload.thread.name if payload.thread else payload.thread_id
            self.log("thread_deleted", f"Thread {name} deleted", None, payload.thread, channel_id=payload.thread_id)

    @commands.Cog.listener()
    async def on_thread_update(self, before, after):
        if self.ours(after.guild) and (changes := diff(before, after, THREAD_ATTRS)):
            self.log("thread_updated", f"Thread {after.name} changed: {describe(changes)}", None, after, changes=changes)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        if self.ours(role.guild):
            self.log("role_created", f"Role {role.name} created", permissions=show(role.permissions.value))

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        if self.ours(role.guild):
            self.log("role_deleted", f"Role {role.name} deleted", members=len(role.members))

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        if not self.ours(after.guild):
            return
        changes = diff(before, after, [a for a in ROLE_ATTRS if a != "permissions"])
        if before.permissions != after.permissions:
            old, new = dict(before.permissions), dict(after.permissions)
            changes["permissions"] = [show([k for k, v in old.items() if v and not new[k]]) + " removed",
                                      show([k for k, v in new.items() if v and not old[k]]) + " added"]
        if changes:
            self.log("role_updated", f"Role {after.name} changed: {describe(changes)}", changes=changes)

    # ---- server ----

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        if self.ours(after) and (changes := diff(before, after, GUILD_ATTRS)):
            self.log("server_updated", f"Server settings changed: {describe(changes)}", changes=changes)

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        if self.ours(guild):
            old, new = {e.id: e.name for e in before}, {e.id: e.name for e in after}
            changes = {"added": ["", show([n for i, n in new.items() if i not in old])],
                       "removed": [show([n for i, n in old.items() if i not in new]), ""],
                       "renamed": ["", show([f"{old[i]} → {n}" for i, n in new.items() if i in old and old[i] != n])]}
            changes = {k: v for k, v in changes.items() if "none" not in (v[0] or v[1]) and (v[0] or v[1])}
            self.log("emojis_updated", f"Emojis changed: {describe(changes) or 'details unknown'}", changes=changes)

    @commands.Cog.listener()
    async def on_guild_stickers_update(self, guild, before, after):
        if self.ours(guild):
            self.log("stickers_updated", f"Stickers changed: {show([s.name for s in before])} → {show([s.name for s in after])}")

    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        if self.ours(invite.guild):
            self.log("invite_created", f"{who(invite.inviter) or 'Someone'} made invite {invite.code} for #{show(invite.channel)} "
                     f"(max uses {invite.max_uses or 'unlimited'}, expires {'never' if not invite.max_age else f'in {invite.max_age // 3600}h'})",
                     invite.inviter, invite.channel, code=invite.code, temporary=invite.temporary or None)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        if self.ours(invite.guild):
            self.log("invite_deleted", f"Invite {invite.code} deleted", None, invite.channel, code=invite.code)

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel):
        if self.ours(channel.guild):
            self.log("webhooks_updated", f"Webhooks changed in #{channel.name}", None, channel)

    @commands.Cog.listener()
    async def on_scheduled_event_create(self, event):
        if self.ours(event.guild):
            self.log("scheduled_event", f"Event {event.name} created for {event.start_time:%Y-%m-%d %H:%M} UTC",
                     event.creator, description=event.description, location=event.location)

    @commands.Cog.listener()
    async def on_scheduled_event_delete(self, event):
        if self.ours(event.guild):
            self.log("scheduled_event", f"Event {event.name} deleted")

    @commands.Cog.listener()
    async def on_scheduled_event_update(self, before, after):
        if self.ours(after.guild) and (changes := diff(before, after, EVENT_ATTRS)):
            self.log("scheduled_event", f"Event {after.name} changed: {describe(changes)}", changes=changes)

    @commands.Cog.listener()
    async def on_scheduled_event_user_add(self, event, user):
        if self.ours(event.guild):
            self.log("scheduled_event", f"{who(user)} is interested in event {event.name}", user)

    @commands.Cog.listener()
    async def on_scheduled_event_user_remove(self, event, user):
        if self.ours(event.guild):
            self.log("scheduled_event", f"{who(user)} is no longer interested in event {event.name}", user)

    @commands.Cog.listener()
    async def on_automod_action(self, execution):
        if self.ours(execution.guild_id):
            self.log("automod_action", f"AutoMod {show(execution.action.type)} on {who(execution.member) or execution.user_id}: "
                     f"{execution.content or ''} (matched {execution.matched_keyword or execution.matched_content or '?'})",
                     execution.member, execution.channel, execution.message_id, user_id=execution.user_id,
                     channel_id=execution.channel_id, content=execution.content, rule_id=execution.rule_id)

    @commands.Cog.listener()
    async def on_automod_rule_create(self, rule):
        if self.ours(rule.guild):
            self.log("automod_rule", f"AutoMod rule {rule.name} created")

    @commands.Cog.listener()
    async def on_automod_rule_update(self, rule):
        if self.ours(rule.guild):
            self.log("automod_rule", f"AutoMod rule {rule.name} changed", enabled=str(rule.enabled))

    @commands.Cog.listener()
    async def on_automod_rule_delete(self, rule):
        if self.ours(rule.guild):
            self.log("automod_rule", f"AutoMod rule {rule.name} deleted")

    @commands.Cog.listener()
    async def on_stage_instance_create(self, stage):
        if self.ours(stage.guild):
            self.log("stage", f"Stage started in {show(stage.channel)}: {stage.topic}", None, stage.channel)

    @commands.Cog.listener()
    async def on_stage_instance_delete(self, stage):
        if self.ours(stage.guild):
            self.log("stage", f"Stage ended in {show(stage.channel)}", None, stage.channel)

    @commands.Cog.listener()
    async def on_soundboard_sound_create(self, sound):
        if self.ours(getattr(sound, "guild", None)):
            self.log("soundboard", f"Soundboard sound {sound.name} added")

    @commands.Cog.listener()
    async def on_soundboard_sound_delete(self, sound):
        if self.ours(getattr(sound, "guild", None)):
            self.log("soundboard", f"Soundboard sound {sound.name} removed")

    # ---- audit log: who did it, for kicks, bans, role and channel changes, deleted messages and more ----

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry):
        if not self.ours(entry.guild):
            return
        changes = {}
        for attr, old in entry.changes.before:
            changes[attr] = [show(old), show(getattr(entry.changes.after, attr, None))]
        for attr, new in entry.changes.after:
            changes.setdefault(attr, [show(None), show(new)])
        action = entry.action.name.replace("_", " ")
        target = who(entry.target) if isinstance(entry.target, (discord.User, discord.Member)) else show(entry.target)
        extra = entry.extra
        where = getattr(extra, "channel", None)
        text = f"{who(entry.user) or entry.user_id} → {action}: {target}"
        if getattr(extra, "count", None):
            text += f" ({extra.count}x)"
        if entry.reason:
            text += f" — reason: {entry.reason}"
        if changes:
            text += f" — {describe(changes)}"
        self.log("audit_entry", text, entry.user, where if isinstance(where, discord.abc.GuildChannel) else None,
                 user_id=entry.user_id, action=entry.action.name, target=target, reason=entry.reason, changes=changes)


async def setup(bot):
    await bot.add_cog(Logs(bot))
