"""Data for the website's dashboard page, in the compact shape pages/dashboard.html reads. No network here.

Every string that comes from Steam (names, avatar URLs) is HTML-escaped, because the page's script
writes these values straight into innerHTML.
"""
import html
import re
from collections import defaultdict

from core.match import final_build
from core.shared import item_icon, won
from core.trophies import FAMILIES, MASTERY, rarity

# order matches the page's souls-by-source legend: lane creeps, neutrals, heroes, bosses, treasure, denies
SOURCE_KEYS = ("gold_lane_creep", "gold_neutral_creep", "gold_player", "gold_boss", "gold_treasure", "gold_denied")


def esc(text):
    return html.escape(text or "", quote=True)


def _weighted(rows, key, weight="time_played"):
    total = sum(r[weight] for r in rows)
    return sum(r[key] * r[weight] for r in rows) / total if total else 0


def _acc(value):
    """hero-stats accuracy is a 0-1 fraction."""
    return round(value * 100) if value <= 1 else round(value)


def item_info(item):
    """[description, [[label, value], ...]] for the page's item popup; the API's text is HTML, so it is flattened and escaped."""
    desc = " ".join((item.get("description") or {}).values())
    desc = re.sub(r"\s+", " ", re.sub(r"<svg.*?</svg>", "", desc, flags=re.S))
    desc = re.sub(r"<[^>]+>", lambda m: "\n" if m.group().startswith("<br") else "", desc)
    props = item.get("properties") or {}
    names = [n for s in item.get("tooltip_sections") or [] for a in s.get("section_attributes") or []
             for k in ("properties", "elevated_properties", "important_properties") for n in a.get(k) or []]
    if item.get("is_active_item"):
        names.append("AbilityCooldown")
    stats = []
    for n in dict.fromkeys(names):
        p = props.get(n) or {}
        v = str(p.get("value", "")).removesuffix((p.get("postfix") or "").strip())
        if not p.get("label") or v in ("", "0"):
            continue
        sign = "+" if p.get("prefix") in ("+", "{s:sign}") and not v.startswith("-") else ""
        stats.append([esc(p["label"]), esc(f"{sign}{v}{p.get('postfix') or ''}")])
    return [esc(re.sub(r" *\n *", "\n", desc).strip()), stats]


PEOPLE_SHOWN = 6  # mates / rivals listed per Player


def top_people(rows, id_key, linked, limit=PEOPLE_SHOWN):
    """The mates or enemies the page shows: most games first, Linked Players left out."""
    return sorted((r for r in rows if r[id_key] not in linked), key=lambda r: -r["matches_played"])[:limit]


def _people(rows, id_key, linked, profiles, limit=PEOPLE_SHOWN):
    """Top mates or enemies by games, excluding Linked Players: [id, name, avatar, games, wins]."""
    rows = top_people(rows, id_key, linked, limit)
    out = []
    for r in rows:
        prof = profiles.get(r[id_key]) or {}
        out.append([r[id_key], esc(prof.get("personaname") or f"Player {str(r[id_key])[-4:]}"),
                    esc(prof.get("avatarmedium")), r["matches_played"], r["wins"]])
    return out


def player_entry(account_id, profile, badge, history, hero_stats, mates, enemies, linked, profiles):
    """One Linked Player's entry, or None if they have no matches in `history` (already windowed)."""
    games = sorted(history, key=lambda m: -m["start_time"])
    if not games:
        return None
    by_hero = defaultdict(lambda: [0, 0, 0, 0, 0])
    for m in games:
        h = by_hero[m["hero_id"]]
        h[0] += 1
        h[1] += won(m)
        h[2] += m["player_kills"]
        h[3] += m["player_deaths"]
        h[4] += m["player_assists"]
    minutes = sum(m["match_duration_s"] for m in games) / 60
    return {
        "id": account_id,
        "name": esc((profile or {}).get("personaname") or str(account_id)),
        "av": esc((profile or {}).get("avatarmedium")),
        "cc": esc((profile or {}).get("countrycode")) or None,
        "tier": badge // 10, "sub": badge % 10,
        "n": len(games), "w": sum(won(m) for m in games),
        "k": sum(m["player_kills"] for m in games), "d": sum(m["player_deaths"] for m in games),
        "a": sum(m["player_assists"] for m in games),
        "spm": round(sum(m["net_worth"] for m in games) / minutes) if minutes else 0,
        "hero": sorted(([h, *v] for h, v in by_hero.items()), key=lambda r: -r[1]),
        "form": [int(won(m)) for m in reversed(games[:20])],  # oldest -> newest
        "g": [[m["match_id"], m["hero_id"], m["start_time"], m["player_kills"], m["player_deaths"], m["player_assists"],
               m["net_worth"], m["match_duration_s"], int(won(m)), m["last_hits"]] for m in games],
        "mate": _people(mates, "mate_id", linked, profiles),
        "enem": _people(enemies, "enemy_id", linked, profiles),
        # all-time numbers from /v1/players/hero-stats
        "dpm": round(_weighted(hero_stats, "damage_per_min")),
        "lhpm": round(_weighted(hero_stats, "last_hits_per_min"), 1),
        "acc": _acc(_weighted(hero_stats, "accuracy", "matches_played")),
        "at": sum(r["matches_played"] for r in hero_stats),
        "hx": {r["hero_id"]: [r["matches_played"], round(r["damage_per_min"]), round(r["networth_per_min"]), _acc(r["accuracy"])]
               for r in hero_stats},
    }


def server_matches(players, histories, now, days=30):
    """(matches newest first, matches per day with index 0 = today). A match lists every Linked Player in it."""
    matches = {}
    for p in players:
        for m in histories[p["id"]]:
            e = matches.setdefault(m["match_id"], {"id": m["match_id"], "t": m["start_time"], "dur": m["match_duration_s"],
                                                   "win": None, "pl": []})
            e["pl"].append([p["id"], m["hero_id"], m["player_kills"], m["player_deaths"], m["player_assists"],
                            m["net_worth"], int(won(m))])
    per_day = [0] * days
    for m in matches.values():
        age = int((now - m["t"]) // 86400)
        if 0 <= age < days:
            per_day[age] += 1
    return sorted(matches.values(), key=lambda m: -m["t"]), per_day


def hero_analytics(rows):
    """{hero_id: [win %, pick %, kills, deaths, assists per game, avg souls, matches]} from /v1/analytics/hero-stats."""
    agg = defaultdict(lambda: defaultdict(int))
    for r in rows:
        for k in ("wins", "matches", "total_kills", "total_deaths", "total_assists", "total_net_worth"):
            agg[r["hero_id"]][k] += r[k]
    slots = sum(a["matches"] for a in agg.values()) or 1
    out = {}
    for hid, a in agg.items():
        m = a["matches"] or 1
        out[hid] = [round(100 * a["wins"] / m, 1), round(100 * a["matches"] / (slots / 12), 1),
                    round(a["total_kills"] / m, 1), round(a["total_deaths"] / m, 1), round(a["total_assists"] / m, 1),
                    round(a["total_net_worth"] / m), a["matches"]]
    return out


def dashboard(now, players, histories, heroes, items, ranks, hero_rows, names):
    """The page's `D` object. players: entries from player_entry (None already dropped). names: {account_id: name}."""
    sm, per_day = server_matches(players, histories, now)
    top = max(ranks) if ranks else 0
    rank_list = [[t, ranks[t]["name"], (ranks[t].get("images") or {}).get("large", "")] if t in ranks else [t, "", ""]
                 for t in range(top + 1)]
    return {
        "T": now, "P": players, "SM": sm, "days": per_day, "total": len(sm), "MM": [],
        "IT": {i: [it["name"], item_icon(it), it.get("item_slot_type") or "", it.get("cost") or 0, it.get("item_tier") or 0,
                   *item_info(it)]
               for i, it in items.items() if it.get("type") == "upgrade"},
        "H": {i: [h["name"], (h.get("images") or {}).get("icon_image_small", "")] for i, h in heroes.items()},
        "R": rank_list,
        "HA": hero_analytics(hero_rows),
        "TI": {},
        "N": {i: esc(n) for i, n in names.items()},
        # trophy families: key -> [category, label, unit, tier names, thresholds, lower is better]
        "TF": {k: [cat, label, unit, tiers, [len(heroes) if t is None else t for t in th], low]
               for k, (cat, label, unit, tiers, th, _, low) in FAMILIES.items()},
        "TM": MASTERY,
        "TR": rarity([p.get("tr", []) for p in players]),
    }


def match_detail(meta, items, names):
    """One match's full scoreboard for the page. names: {account_id: personaname}."""
    info = meta["match_info"]
    pl = []
    for p in info["players"]:
        s = p["stats"][-1] if p["stats"] else {}
        shots = s.get("shots_hit", 0) + s.get("shots_missed", 0)
        pl.append({
            "id": p["account_id"], "team": p["team"], "hero": p["hero_id"],
            "k": p["kills"], "d": p["deaths"], "a": p["assists"], "nw": p["net_worth"],
            "lh": p["last_hits"], "dn": p["denies"], "lvl": p["level"],
            "dmg": s.get("player_damage", 0), "heal": s.get("player_healing", 0),
            "acc": round(100 * s.get("shots_hit", 0) / shots) if shots else 0,
            "src": [s.get(k, 0) for k in SOURCE_KEYS], "loss": s.get("gold_death_loss", 0),
            "items": [i["id"] for i in final_build(p, items)],
            "nm": esc(names.get(p["account_id"]) or f"Player {str(p['account_id'])[-4:]}"),
            "cur": [x["net_worth"] for x in p["stats"]] or [0],
        })
    tc = []
    for team in (0, 1):
        curves = [x["cur"] for x in pl if x["team"] == team]
        n = min((len(c) for c in curves), default=0)
        tc.append([sum(c[i] for c in curves) for i in range(n)] or [0])
    return {"id": info["match_id"], "t": info["start_time"], "dur": info["duration_s"], "win": info["winning_team"],
            "pl": pl, "tc": tc}


def hero_items(rows, items, limit=8):
    """Most-bought upgrades for a hero: [[item_id, buys, win %]] from /v1/analytics/item-stats."""
    rows = [r for r in rows if items.get(r["item_id"], {}).get("type") == "upgrade" and r["matches"]]
    rows.sort(key=lambda r: -r["matches"])
    return [[r["item_id"], r["matches"], round(100 * r["wins"] / r["matches"], 1)] for r in rows[:limit]]
