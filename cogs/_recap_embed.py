"""The full Match Recap embed (layout A2), built from /v1/matches/{id}/metadata. No network calls here."""
from datetime import datetime, timezone

import discord

from cogs._insights import match_insights

SLOTS = [("weapon", "Weapon"), ("vitality", "Vitality"), ("spirit", "Spirit")]
FIELD_MAX = 1024


def find_player(meta, account_id):
    return next((p for p in meta["match_info"]["players"] if p["account_id"] == account_id), None)


def place(players, me, key):
    """1-based position of `me` among all players by a final-stats key, highest first."""
    return 1 + sum(1 for p in players if p["stats"][-1][key] > me["stats"][-1][key])


def final_build(player, items):
    """Item assets still owned at the end, in purchase order."""
    seen, out = set(), []
    for it in player["items"]:
        item = items.get(it["item_id"])
        if it["sold_time_s"] == 0 and item and item.get("type") == "upgrade" and it["item_id"] not in seen:
            seen.add(it["item_id"])
            out.append(item)
    return out


def souls_timeline(player):
    return [(s["time_stamp_s"], s["net_worth"]) for s in player["stats"]]


def _mmss(s):
    return f"{s // 60}:{s % 60:02d}"


def _bar(value, top, width=14):
    eighths = round(value / top * width * 8) if top else 0
    full, part = divmod(eighths, 8)
    return "█" * full + ("", "▏", "▎", "▍", "▌", "▋", "▊", "▉")[part]


def souls_block(s):
    rows = [("Lane creeps", s["gold_lane_creep"]), ("Neutrals", s["gold_neutral_creep"]),
            ("Hero kills", s["gold_player"]), ("Objectives", s["gold_boss"]), ("Treasure", s["gold_treasure"])]
    top = max(v for _, v in rows)
    lines = [f"{n:<13} {v:>6,}  {_bar(v, top)}" for n, v in rows]
    lines.append(f"{'Lost on death':<13} {-s['gold_death_loss']:>6,}")
    return "```\n" + "\n".join(lines) + "\n```"


def build_field(build, emojis):
    def text(with_names):
        rows = []
        for slot, label in SLOTS:
            parts = [f"{emojis.get(i['id'], '')} {i['name']}".strip() if with_names else emojis.get(i["id"]) or i["name"]
                     for i in build if i.get("item_slot_type") == slot]
            if parts:
                rows.append(f"**{label}** " + (" · " if with_names else " ").join(parts))
        return "\n".join(rows) or "No items"
    full = text(True)
    return full if len(full) <= FIELD_MAX else text(False)[:FIELD_MAX]


def scoreboard(players, me, hero_names, won):
    def row(p):
        name = ("▶ " if p is me else "  ") + hero_names.get(p["hero_id"], f"Hero {p['hero_id']}")
        kda = f"{p['kills']}/{p['deaths']}/{p['assists']}"
        return f"{name[:15]:<15}{kda:>8}{p['net_worth']:>8,}{p['stats'][-1]['player_damage']:>8,}"

    out = []
    for label, team, team_won in (("YOUR TEAM", me["team"], won), ("ENEMY TEAM", 1 - me["team"], not won)):
        ps = sorted((p for p in players if p["team"] == team), key=lambda p: -p["net_worth"])
        out.append(f"{label} · {'WIN' if team_won else 'LOSS'}   souls {sum(p['net_worth'] for p in ps):,}")
        out.append(f"{'  Hero':<15}{'K/D/A':>8}{'Souls':>8}{'Dmg':>8}")
        out += [row(p) for p in ps]
        out.append("")
    return "```\n" + "\n".join(out).rstrip() + "\n```"


def rank_footer(rank_data, ranks):
    """(text, icon url) for the Player's rank going into the Match."""
    badge = (rank_data or {}).get("initial_display_rank") or 0
    tier, sub = divmod(badge, 10)
    rank = ranks.get(tier)
    if not badge or not rank:
        return None, None
    return f"{rank['name']} {sub}", (rank.get("images") or {}).get(f"small_subrank{sub}")


def rank_lines(rank_data):
    """Rank progress actually gained or lost, and whether rank loss protection kicked in."""
    rd = rank_data or {}
    if rd.get("initial_flat_progress") is None or rd.get("final_flat_progress") is None:
        return []
    # desired_progress_change is the change before protection; the real change is final - initial
    change = rd["final_flat_progress"] - rd["initial_flat_progress"]
    if rd.get("consumed_demotion_protection"):
        left = max((rd.get("initial_demotion_protection_games") or 1) - 1, 0)
        return [f"**Rank loss protection saved you:** lost {abs(change)} instead of "
                f"{abs(rd.get('desired_progress_change') or 0)}. {left} protected loss{'' if left == 1 else 'es'} left."]
    if change:
        return [f"{'Gained' if change > 0 else 'Lost'} {abs(change)} rank progress."]
    return []


def build_full_embed(match, meta, account_id, earlier, heroes, items, ranks, emojis, member):
    """match: the match-history entry. earlier: match-history entries before it. Returns None if the Player isn't in meta."""
    info = meta["match_info"]
    players = info["players"]
    me = find_player(meta, account_id)
    if me is None:
        return None
    s = me["stats"][-1]
    hero_names = {i: h["name"] for i, h in heroes.items()}
    hero = heroes.get(me["hero_id"], {})
    won = info["winning_team"] == me["team"]
    duration = info["duration_s"]
    minutes = max(duration / 60, 1)

    dmg_place, heal_place, souls_place = (place(players, me, k) for k in ("player_damage", "player_healing", "net_worth"))
    lines = []
    if dmg_place == 1:
        lines.append(f"**Most hero damage in the Match** ({s['player_damage']:,}, #1 of {len(players)}).")
    if heal_place == 1:
        lines.append(f"**Most healing in the Match** ({s['player_healing']:,}).")
    if souls_place == 1:
        lines.append(f"**Most souls in the Match** ({me['net_worth']:,}).")
    lines += match_insights(match, earlier, hero_names)
    lines += rank_lines(me.get("player_rank_data"))

    embed = discord.Embed(
        title=f"{hero.get('name', 'Hero')} · {'Win' if won else 'Loss'} · {_mmss(duration)}",
        description="\n".join(lines[:5]) or None,
        color=discord.Color.green() if won else discord.Color.red(),
        timestamp=datetime.fromtimestamp(info["start_time"] + duration, timezone.utc),
    )
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    if icon := (hero.get("images") or {}).get("icon_image_small"):
        embed.set_thumbnail(url=icon)

    kda = (me["kills"] + me["assists"]) / max(me["deaths"], 1)
    shots = s["shots_hit"] + s["shots_missed"]
    add = embed.add_field
    add(name="K / D / A", value=f"{me['kills']} / {me['deaths']} / {me['assists']} · KDA {kda:.1f}")
    add(name="Souls", value=f"{me['net_worth']:,} · {me['net_worth'] / minutes:,.0f}/min")
    add(name="Level", value=f"{me['level']} · {me['ability_points']} ability pts")
    add(name="Hero damage", value=f"{s['player_damage']:,} · #{dmg_place} in match")
    add(name="Healing", value=f"{s['player_healing']:,} · #{heal_place} in match")
    add(name="Damage taken", value=f"{s['player_damage_taken']:,} · {s['damage_absorbed']:,} absorbed")
    add(name="Accuracy", value=f"{s['shots_hit'] / shots:.1%} · {s['shots_hit']:,} / {shots:,} shots" if shots else "No shots")
    add(name="Crits", value=f"{s['hero_bullets_hit_crit'] / s['hero_bullets_hit']:.1%} · {s['hero_bullets_hit_crit']} of {s['hero_bullets_hit']} hero hits"
        if s["hero_bullets_hit"] else "No hero hits")
    creeps = f" · {s['creep_kills'] / s['possible_creeps']:.0%} lane creeps" if s["possible_creeps"] else ""
    add(name="Farm", value=f"{me['last_hits']} LH · {me['denies']} DN{creeps}")
    add(name="Souls by source", value=souls_block(s), inline=False)
    build = final_build(me, items)
    add(name=f"Final build · {len(build)} items · {sum(i.get('cost') or 0 for i in build):,} souls",
        value=build_field(build, emojis), inline=False)
    add(name="Scoreboard", value=scoreboard(players, me, hero_names, won), inline=False)

    text, rank_icon = rank_footer(me.get("player_rank_data"), ranks)
    embed.set_footer(text=" · ".join(filter(None, [text, f"Match {info['match_id']}"])), icon_url=rank_icon)
    return embed
