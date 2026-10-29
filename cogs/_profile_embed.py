"""The Profile embed (layout P1) and its trend graph. Pure: callers fetch the data."""
import time

import discord

from core.insights import profile_insights
from core.shared import SITE_URL, WINDOW_DAYS, won

ROLL = 10  # Matches in the rolling win rate
TOP_HEROES = 5


def _date(ts):
    return time.strftime("%b %d", time.gmtime(ts)).replace(" 0", " ")


def kda(ms):
    return sum(m["player_kills"] + m["player_assists"] for m in ms) / max(sum(m["player_deaths"] for m in ms), 1)


def form(history, n=10):
    """Last n results oldest → newest as colored squares, plus the tally."""
    last = sorted(history, key=lambda m: m["start_time"])[-n:]
    wins = sum(map(won, last))
    return "".join("🟩" if won(m) else "🟥" for m in last) + f"  {wins}W {len(last) - wins}L"


def streaks(history):
    """(current streak length, current streak is wins, longest win streak)."""
    ms = sorted(history, key=lambda m: m["start_time"])
    if not ms:
        return 0, False, 0
    cur = 0
    for m in reversed(ms):
        if won(m) != won(ms[-1]):
            break
        cur += 1
    best = run = 0
    for m in ms:
        run = run + 1 if won(m) else 0
        best = max(best, run)
    return cur, won(ms[-1]), best


def records(history, hero_names):
    def hero(m):
        return hero_names.get(m["hero_id"], f"Hero {m['hero_id']}")
    k = max(history, key=lambda m: ((m["player_kills"] + m["player_assists"]) / max(m["player_deaths"], 1), m["start_time"]))
    kills = max(history, key=lambda m: m["player_kills"])
    souls = max(history, key=lambda m: m["net_worth"])
    long = max(history, key=lambda m: m["match_duration_s"])
    return "\n".join([
        f"Best KDA **{k['player_kills']}/{k['player_deaths']}/{k['player_assists']}** · {hero(k)} · {_date(k['start_time'])}",
        f"Most kills **{kills['player_kills']}** · {hero(kills)} · {_date(kills['start_time'])}",
        f"Most souls **{souls['net_worth']:,}** · {hero(souls)} · {_date(souls['start_time'])}",
        f"Longest Match **{long['match_duration_s'] // 60} min** · {hero(long)}",
    ])


def weighted(hero_stats, key):
    """Average of a per-hero rate, weighted by Matches played. None if no data."""
    rows = [h for h in hero_stats if h.get(key) is not None]
    n = sum(h["matches_played"] for h in rows)
    return sum(h[key] * h["matches_played"] for h in rows) / n if n else None


def hero_table(hero_stats, hero_names):
    rows = sorted(hero_stats, key=lambda h: -h["matches_played"])[:TOP_HEROES]
    lines = []
    for h in rows:
        m = h["matches_played"]
        name = hero_names.get(h["hero_id"], f"Hero {h['hero_id']}")
        acc = f" · {h['accuracy']:.0%} acc" if h.get("accuracy") is not None else ""
        lines.append(f"**{name}** · {m} Matches · {h['wins'] / m:.0%} · {(h['kills'] + h['assists']) / max(h['deaths'], 1):.2f} KDA"
                     f" · {h['networth_per_min']:,.0f} souls/min{acc}")
    return "\n".join(lines)


def mates_text(mates, names, linked):
    """Top teammates. linked: {account_id: member_id} for this server's Linked Members, shown as mentions."""
    lines = []
    for x in sorted(mates, key=lambda x: -x["matches_played"])[:3]:
        who = f"<@{linked[x['mate_id']]}>" if x["mate_id"] in linked else f"**{names.get(x['mate_id'], 'Unknown')}**"
        lines.append(f"{who} · {x['matches_played']} together · {x['wins'] / x['matches_played']:.0%}")
    return "\n".join(lines) or "No regular teammates yet"


def trend(history, ranked):
    """(points, title, line_graph kwargs) for the Profile graph, or None with too little data."""
    ms = sorted(history, key=lambda m: m["start_time"])
    if ranked:
        ms = [m for m in ms if m.get("ranked_delta") is not None]
        if len(ms) < 2:
            return None
        total, points = 0, []
        for i, m in enumerate(ms, 1):
            total += m["ranked_delta"]
            points.append((i, total))
        ticks = [(1, _date(ms[0]["start_time"])), (len(ms), _date(ms[-1]["start_time"]))]
        return points, f"Rank progress · {WINDOW_DAYS} days", dict(
            x_ticks=ticks, origin=(0, 0), midline=0, y_label=lambda v: f"{v:+,}" if v else "0")
    if len(ms) < ROLL:
        return None
    points = [(i, round(sum(map(won, ms[i - ROLL:i])) / ROLL * 100)) for i in range(ROLL, len(ms) + 1)]
    ticks = [(ROLL, _date(ms[ROLL - 1]["start_time"])), (len(ms), _date(ms[-1]["start_time"]))]
    return points, f"Win rate · rolling {ROLL} Matches", dict(
        x_ticks=ticks, y_range=(0, 100), midline=50, y_label=lambda v: f"{v}%")


def build_profile_embed(member, account_id, steam, rank_text, rank_icon, history, hero_stats, mates, mate_names, linked, heroes):
    """steam: /players/steam entry or None. history: match-history entries in the window. hero_stats: window rows."""
    hero_names = {i: h["name"] for i, h in heroes.items()}
    name = steam["personaname"] if steam else "Unknown player"
    embed = discord.Embed(color=discord.Color.gold())
    country = f" · {steam['countrycode']}" if steam and steam.get("countrycode") else ""
    embed.set_author(name=f"{name}{country}", icon_url=steam.get("avatarmedium") if steam else None,
                     url=f"{SITE_URL}/#players/{account_id}")

    lines = [f"Linked to {member.mention} · {rank_text}"]
    if not history:
        embed.description = lines[0] + f"\nNo Matches in the last {WINDOW_DAYS} days."
        if rank_icon:
            embed.set_thumbnail(url=rank_icon)
        return embed
    lines += profile_insights(history, hero_names)
    embed.description = "\n".join(lines)

    top = max(hero_stats, key=lambda h: h["matches_played"], default=None)
    thumb = rank_icon or (heroes.get(top["hero_id"], {}).get("images", {}).get("icon_image_small") if top else None)
    if thumb:
        embed.set_thumbnail(url=thumb)

    n, wins = len(history), sum(map(won, history))
    mins = max(sum(m["match_duration_s"] for m in history) / 60, 1)
    avg = lambda key: sum(m[key] for m in history) / n
    add = embed.add_field
    add(name=f"Record · {WINDOW_DAYS} days", value=f"{wins}W – {n - wins}L · {wins / n:.1%}")
    add(name="KDA", value=f"{kda(history):.2f} · {avg('player_kills'):.1f} / {avg('player_deaths'):.1f} / {avg('player_assists'):.1f}")
    add(name="Souls / min", value=f"{sum(m['net_worth'] for m in history) / mins:,.0f} · "
                                   f"{sum(m['last_hits'] for m in history) / mins:.1f} LH/min")
    dpm, obj = weighted(hero_stats, "damage_per_min"), weighted(hero_stats, "obj_damage_per_min")
    if dpm is not None:
        add(name="Hero damage / min", value=f"{dpm:,.0f}" + (f" · {obj:,.0f} objective" if obj is not None else ""))
    acc, crit = weighted(hero_stats, "accuracy"), weighted(hero_stats, "crit_shot_rate")
    if acc is not None:
        add(name="Accuracy", value=f"{acc:.1%}" + (f" · {crit:.1%} crits" if crit is not None else ""))
    add(name="Time played", value=f"{mins / 60:.1f} h · {mins / n:.1f} min avg")

    cur, cur_won, best = streaks(history)
    add(name="Last 10 Matches · oldest → newest", inline=False,
        value=form(history) + f"\n{cur}-game {'win' if cur_won else 'loss'} streak · best win streak {best}")
    if hero_stats:
        add(name="Top heroes", value=hero_table(hero_stats, hero_names), inline=False)
    add(name="Best teammates", value=mates_text(mates, mate_names, linked))
    add(name="Records", value=records(history, hero_names))
    embed.set_footer(text=f"Last {WINDOW_DAYS} days · {n} Matches")
    return embed
