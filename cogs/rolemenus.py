"""Role menus: answers clicks on the role menu messages the control panel posts (core/rolemenus.py).
Buttons and dropdowns are DynamicItems, so they keep working after a restart; emoji menus use reactions."""
import discord
from discord.ext import commands

from core import db
from core.rolemenus import DANGEROUS, choose, click, emoji_key, parse_emoji

REASON = "Role menu"


def can_give(role):
    """Re-checked on every click: the panel's list was safe when saved, but roles can move or gain powers since."""
    me = role.guild.me
    return role < me.top_role and not role.managed and not role.is_default() and not role.permissions.value & DANGEROUS


async def apply(member, add, remove):
    """Change the member's roles. (added, removed, skipped) as lists of roles."""
    guild = member.guild
    add = [r for r in map(guild.get_role, add) if r]
    remove = [r for r in map(guild.get_role, remove) if r]
    skipped = [r for r in add + remove if not can_give(r)]
    add, remove = [r for r in add if r not in skipped], [r for r in remove if r not in skipped]
    if add:
        await member.add_roles(*add, reason=REASON)
    if remove:
        await member.remove_roles(*remove, reason=REASON)
    return add, remove, skipped


def reply(added, removed, skipped):
    parts = []
    if added:
        parts.append("Added " + ", ".join(r.mention for r in added))
    if removed:
        parts.append("Removed " + ", ".join(r.mention for r in removed))
    if skipped:
        parts.append("I can't change " + ", ".join(r.mention for r in skipped) + " (ask an admin to move my role above it)")
    return ". ".join(parts) + "." if parts else "Nothing changed."


async def handle(interaction, menu_id, change):
    """Shared by buttons and dropdowns. change(have, menu_roles, menu) returns (add, remove) or None for over the limit."""
    await interaction.response.defer(ephemeral=True, thinking=True)
    conn = interaction.client.db
    menu = db.get_menu(conn, menu_id)
    member = interaction.user
    if not menu or not isinstance(member, discord.Member):
        return await interaction.followup.send("This role menu no longer exists.", ephemeral=True)
    if menu["required_role_id"] and not member.get_role(menu["required_role_id"]):
        return await interaction.followup.send(f"You need <@&{menu['required_role_id']}> before you can use this menu.", ephemeral=True)
    menu_roles = {o["role_id"] for o in db.menu_options(conn, menu_id)}
    plan = change({r.id for r in member.roles}, menu_roles, menu)
    if plan is None:
        return await interaction.followup.send(f"You can pick at most {menu['max_picks']} here. Drop one first by clicking it again.", ephemeral=True)
    try:
        result = await apply(member, *plan)
    except discord.HTTPException as e:
        return await interaction.followup.send(f"Discord wouldn't change your roles ({e.text or e.status}).", ephemeral=True)
    await interaction.followup.send(reply(*result), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class RoleButton(discord.ui.DynamicItem[discord.ui.Button], template=r"rolemenu:(?P<menu>\d+):(?P<role>\d+)"):
    def __init__(self, menu_id, role_id):
        super().__init__(discord.ui.Button(custom_id=f"rolemenu:{menu_id}:{role_id}"))
        self.menu_id, self.role_id = menu_id, role_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["menu"]), int(match["role"]))

    async def callback(self, interaction):
        if self.role_id not in {o["role_id"] for o in db.menu_options(interaction.client.db, self.menu_id)}:
            return await interaction.response.send_message("That role was taken out of this menu.", ephemeral=True)
        await handle(interaction, self.menu_id, lambda have, roles, menu: click(have, roles, self.role_id, menu["max_picks"]))


class RoleSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"rolemenu:(?P<menu>\d+):select"):
    def __init__(self, menu_id):
        super().__init__(discord.ui.Select(custom_id=f"rolemenu:{menu_id}:select"))
        self.menu_id = menu_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["menu"]))

    async def callback(self, interaction):
        picked = {int(v) for v in interaction.data.get("values", []) if v.isdigit()}
        await handle(interaction, self.menu_id, lambda have, roles, menu: choose(have, roles, picked & roles))


class RoleMenus(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def reaction(self, payload, added):
        menu = db.menu_for_message(self.bot.db, payload.message_id)
        if not menu or menu["mode"] != "reactions" or payload.user_id == self.bot.user.id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        member = guild and (payload.member or guild.get_member(payload.user_id))
        options = db.menu_options(self.bot.db, menu["id"])
        role_id = next((o["role_id"] for o in options if emoji_key(parse_emoji(o["emoji"])) == emoji_key(payload.emoji)), None)
        if not member or member.bot or role_id is None:
            return
        channel = self.bot.get_channel(payload.channel_id)
        if added and menu["required_role_id"] and not member.get_role(menu["required_role_id"]):
            return await self.unreact(channel, payload.message_id, payload.emoji, member)
        have, menu_roles = {r.id for r in member.roles}, {o["role_id"] for o in options}
        if not added:
            plan = (set(), {role_id} & have)
        elif role_id in have:
            return
        else:
            plan = click(have, menu_roles, role_id, menu["max_picks"])
            if plan is None:  # over the limit: take the reaction back
                return await self.unreact(channel, payload.message_id, payload.emoji, member)
        try:
            await apply(member, *plan)
        except discord.HTTPException as e:
            print(f"rolemenus: changing roles for {member} failed: {e}")
            return
        if added and plan[1]:  # "pick one": clear their reaction on the role they lost
            for o in options:
                if o["role_id"] in plan[1]:
                    await self.unreact(channel, payload.message_id, parse_emoji(o["emoji"]), member)

    async def unreact(self, channel, message_id, emoji, member):
        if isinstance(emoji, dict):
            emoji = discord.PartialEmoji(name=emoji["name"], id=int(emoji["id"]) if emoji.get("id") else None,
                                         animated=emoji.get("animated", False))
        try:
            await channel.get_partial_message(message_id).remove_reaction(emoji, member)
        except (discord.HTTPException, AttributeError):
            pass  # needs Manage Messages; the role change itself already happened

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        await self.reaction(payload, True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        await self.reaction(payload, False)


async def setup(bot):
    bot.add_dynamic_items(RoleButton, RoleSelect)
    await bot.add_cog(RoleMenus(bot))
