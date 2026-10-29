"""Trophies: tiers a Player earns (docs/trophies-plan.md). Pure functions.

FAMILIES count the Player's full match history. META_FAMILIES need match metadata, so they count the
match_stats rows the recaps cog saves: every Match in the history, filled in a few per loop run.
"""
from collections import Counter
from itertools import accumulate

from core.shared import won

MASTERY = (["Tryout", "Regular", "Specialist", "Expert", "Master", "Grandmaster", "Legend"],
           [3, 10, 50, 100, 250, 500, 1000])


def _total(f):
    return lambda ms: accumulate(f(m) for m in ms)


def _best(f):
    return lambda ms: accumulate((f(m) for m in ms), max)


def _streak(want):
    def run(ms):
        cur = best = 0
        for m in ms:
            cur = cur + 1 if won(m) == want else 0
            best = max(best, cur)
            yield best
    return run


def _days_in_a_row(ms):
    best = cur = 0
    last = None
    for m in ms:
        day = m["start_time"] // 86400  # shortcut: UTC days; switch once a server timezone is picked
        if day != last:
            cur = cur + 1 if last is not None and day == last + 1 else 1
            last = day
        best = max(best, cur)
        yield best


def _heroes_won(ms):
    seen = set()
    for m in ms:
        if won(m):
            seen.add(m["hero_id"])
        yield len(seen)


def _one_trick(ms):
    """Best share (%) of any 100 matches in a row on one hero; 0 until 100 matches."""
    best = 0
    for i in range(len(ms)):
        if i >= 99:
            best = max(best, Counter(m["hero_id"] for m in ms[i - 99:i + 1]).most_common(1)[0][1])
        yield best


def _fastest_win(ms):
    best = None
    for m in ms:
        if won(m):
            mins = m["match_duration_s"] / 60
            best = mins if best is None else min(best, mins)
        yield best


def _spm(m):
    return round(m["net_worth"] / (m["match_duration_s"] / 60)) if m["match_duration_s"] >= 900 else 0


# key: (category, label, unit, tier names, thresholds, running value over matches oldest -> newest, lower is better)
# Jack of All Trades' last threshold (None) is filled with the current hero count.
FAMILIES = {
    "kills": ("Combat", "Kills", "", ["First Blood", "Headhunter", "Slayer", "Executioner", "Reaper", "Death Incarnate", "Extinction Event"],
              [15, 50, 250, 500, 1250, 2500, 5000], _total(lambda m: m["player_kills"]), False),
    "deaths": ("Combat", "Deaths", "", ["Respawn", "Frequent Flyer", "Corpse Run", "Graveyard Regular", "Revenant", "Undying", "Eternal Return"],
               [15, 50, 250, 500, 1250, 2500, 5000], _total(lambda m: m["player_deaths"]), False),
    "assists": ("Combat", "Assists", "", ["Wingman", "Support Act", "Team Player", "Playmaker", "Puppetmaster", "The Enabler", "The Architect"],
                [30, 125, 600, 1250, 3000, 6000, 12500], _total(lambda m: m["player_assists"]), False),
    "souls": ("Economy", "Souls earned", "", ["Pocket Change", "Soul Collector", "Soul Hoarder", "Soul Baron", "Soul Tycoon", "Soul Mogul", "Soul Emperor"],
              [100_000, 350_000, 1_750_000, 3_500_000, 9_000_000, 17_500_000, 35_000_000], _total(lambda m: m["net_worth"]), False),
    "matches": ("Results", "Matches played", "", ["Rookie", "Regular", "Veteran", "Lifer", "Die-Hard", "Institution", "The Pitboss"],
                [3, 10, 50, 100, 250, 500, 1000], _total(lambda m: 1), False),
    "hours": ("Results", "Time played", "h", ["Warm-Up", "Dedicated", "Grinder", "Committed", "No-Lifer", "Living in the Pit", "One with the Pit"],
              [1.5, 5, 25, 50, 150, 300, 600], _total(lambda m: m["match_duration_s"] / 3600), False),
    "wins": ("Results", "Total wins", "", ["First Win", "Contender", "Victor", "Champion", "Conqueror", "Warlord", "Legend"],
             [1, 5, 25, 50, 125, 250, 500], _total(lambda m: int(won(m))), False),
    "losses": ("Results", "Total losses", "", ["Learning Experience", "Hard Knocks", "Glutton for Punishment", "Still Here", "Iron Will", "Never Gives Up", "Eternal Optimist"],
               [1, 5, 25, 50, 125, 250, 500], _total(lambda m: int(not won(m))), False),
    "winstreak": ("Results", "Win streak", "", ["On a Roll", "Hot Streak", "Unstoppable", "Dominating", "Godlike"],
                  [3, 5, 7, 10, 12], _streak(True), False),
    "losestreak": ("Results", "Lose streak", "", ["Rough Patch", "Tilted", "Cursed", "Rock Bottom", "Uninstall?"],
                   [3, 5, 7, 10, 12], _streak(False), False),
    "grind": ("Results", "Daily Grind", " days", ["Back for More", "Hooked", "Week-Long Grind", "Can't Stop", "Two-Week Grind", "Month in the Pit"],
              [2, 4, 7, 10, 14, 30], _days_in_a_row, False),
    "jack": ("Heroes", "Jack of All Trades", " heroes", ["Dabbler", "Flexible", "Versatile", "Jack of All Trades", "Master of All"],
             [3, 8, 15, 25, None], _heroes_won, False),
    "onetrick": ("Heroes", "One-Trick", "%", ["Favourite", "Main", "One-Trick"], [40, 60, 80], _one_trick, False),
    "spm": ("Single match", "Souls per minute", "", ["Farmer", "Harvester", "Soul Engine", "Soul Storm", "Soul Singularity"],
            [1200, 1400, 1600, 1800, 2000], _best(_spm), False),
    "length": ("Single match", "Match length", " min", ["Long Haul", "Endurance", "Marathon", "Ultramarathon", "Forever War"],
               [45, 55, 65, 75, 90], _best(lambda m: m["match_duration_s"] / 60), False),
    "untouchable": ("Single match", "Untouchable (K+A in a win with 0 deaths)", "", ["Clean Sheet", "Untouchable", "Flawless", "Perfection"],
                    [0, 10, 20, 25], _best(lambda m: m["player_kills"] + m["player_assists"] if won(m) and not m["player_deaths"] else -1), False),
    "feeder": ("Single match", "Feeder (deaths)", "", ["Feeder", "Soul Donor", "Open Buffet", "All-You-Can-Eat"],
               [12, 15, 18, 22], _best(lambda m: m["player_deaths"]), False),
    "stomp": ("Single match", "Stomp (fastest win)", " min", ["Quick Win", "Stomp", "Steamroll", "Blowout", "Speedrun"],
              [25, 22, 20, 17, 15], _fastest_win, True),
}


def _items_owned(rows):
    seen = set()
    for r in rows:
        seen.update(r["items"])
        yield len(seen)


# Same shape as FAMILIES, but run over match_stats rows: only Matches whose metadata has been saved so far.
# Collector's last threshold (None) is filled with the number of shop items.
META_FAMILIES = {
    "dmg": ("Combat", "Damage dealt", "", ["Scrapper", "Bruiser", "Heavy Hitter", "Wrecking Ball", "Demolisher", "Annihilator", "Cataclysm"],
            [75_000, 250_000, 1_250_000, 2_500_000, 6_000_000, 12_500_000, 25_000_000], _total(lambda r: r["dmg"]), False),
    "taken": ("Combat", "Damage taken", "", ["Punching Bag", "Tough Skin", "Thick Hide", "Iron Wall", "Juggernaut", "Unbreakable", "Immovable Object"],
              [75_000, 275_000, 1_250_000, 2_750_000, 7_000_000, 12_500_000, 30_000_000], _total(lambda r: r["taken"]), False),
    "heal": ("Combat", "Healing", "", ["Band-Aid", "Medic", "Field Surgeon", "Lifeline", "Miracle Worker", "Saint", "Fountain of Life"],
             [20_000, 60_000, 300_000, 600_000, 1_500_000, 3_000_000, 6_500_000], _total(lambda r: r["heal"]), False),
    "head": ("Kill style", "Headshot kills", "", ["Lucky Shot", "Crack Shot", "Marksman", "Deadeye", "Skull Splitter", "Sniper Elite", "One Tap"],
             [1, 4, 20, 40, 100, 200, 400], _total(lambda r: r["head"]), False),
    "melee": ("Kill style", "Melee kills", "", ["Scuffle", "Brawler", "Knuckle Sandwich", "Pugilist", "Heavyweight", "Fist of Fury", "Knockout King"],
              [2, 8, 40, 80, 200, 400, 800], _total(lambda r: r["melee"]), False),
    "abil": ("Kill style", "Ability kills", "", ["Cantrip", "Spellslinger", "Hexer", "Evoker", "Warlock", "Grand Warlock", "Arcane Executioner"],
             [10, 35, 175, 350, 850, 1750, 3500], _total(lambda r: r["abil"]), False),
    "mvp": ("Results", "MVP", "", ["Standout", "Star Player", "MVP", "Clutch", "Franchise Player", "Hall of Famer", "GOAT"],
            [1, 3, 5, 10, 20, 40, 80], _total(lambda r: r["mvp"]), False),
    "weapon": ("Items", "Weapon items bought", "", ["Armed", "Gunslinger", "Sharpshooter", "Arms Dealer", "Arsenal", "Walking Armory", "God of War"],
               [15, 50, 250, 500, 1250, 2500, 5000], _total(lambda r: r["weapon"]), False),
    "vitality": ("Items", "Vitality items bought", "", ["Healthy", "Hardy", "Sturdy", "Fortified", "Bulwark", "Immortal", "Living Fortress"],
                 [15, 50, 250, 500, 1250, 2500, 5000], _total(lambda r: r["vitality"]), False),
    "spirit": ("Items", "Spirit items bought", "", ["Spark", "Mystic", "Sorcerer", "Arcanist", "Archmage", "Spirit Lord", "Ascended"],
               [15, 50, 250, 500, 1250, 2500, 5000], _total(lambda r: r["spirit"]), False),
    "collector": ("Items", "Collector (different items)", "", ["Window Shopper", "Bargain Hunter", "Collector", "Hoarder", "The Whole Shop"],
                  [10, 30, 60, 90, None], _items_owned, False),
    "multi": ("Single match", "Multi-kill (≤10s apart)", "", ["Triple Kill", "Quad Kill", "Penta Kill", "Wipeout"],
              [3, 4, 5, 6], _best(lambda r: r["multi"]), False),
    "acc": ("Single match", "Accuracy (200+ shots)", "%", ["Steady Hand", "Precise", "Laser", "Aimbot?"],
            [60, 65, 70, 75], _best(lambda r: round(100 * r["hit"] / r["shots"]) if r["shots"] >= 200 else 0), False),
}

MULTI_GAP = 10  # seconds allowed between kills in one multi-kill


def match_stats(meta, account_id, items):
    """The numbers META_FAMILIES need from one Match's metadata, or None if the Player isn't in it."""
    players = meta["match_info"]["players"]
    me = next((p for p in players if p["account_id"] == account_id), None)
    if me is None:
        return None
    s = me["stats"][-1] if me["stats"] else {}
    bought = [i["item_id"] for i in me["items"] if items.get(i["item_id"], {}).get("type") == "upgrade"]
    slots = Counter(items[i].get("item_slot_type") for i in bought)
    kills = sorted(d["game_time_s"] for p in players if p["team"] != me["team"]
                   for d in p.get("death_details") or [] if d.get("killer_player_slot") == me["player_slot"])
    multi = run = 0
    for i, t in enumerate(kills):
        run = run + 1 if i and t - kills[i - 1] <= MULTI_GAP else 1
        multi = max(multi, run)
    return {"dmg": s.get("player_damage", 0), "taken": s.get("player_damage_taken", 0), "heal": s.get("player_healing", 0),
            "head": s.get("headshot_kills", 0), "melee": s.get("melee_kills", 0), "abil": s.get("ability_kills", 0),
            "mvp": int(me.get("mvp_rank") == 1), "multi": multi,
            "hit": s.get("shots_hit", 0), "shots": s.get("shots_hit", 0) + s.get("shots_missed", 0),
            "weapon": slots["weapon"], "vitality": slots["vitality"], "spirit": slots["spirit"], "items": sorted(set(bought))}


def player_trophies(history, stats, hero_count, item_count):
    """(earned [[key, tier, unix time]], progress {key: current value}, hero ids won with, item ids bought).
    history: match-history entries; stats: match_stats dicts plus "start_time". Hero mastery keys are
    "h<hero_id>" and use MASTERY."""
    ms = sorted(history, key=lambda m: m["start_time"])
    rows = sorted(stats, key=lambda r: r["start_time"])
    runs = [(k, f[4], f[5], f[6], ms, hero_count) for k, f in FAMILIES.items()]
    runs += [(k, f[4], f[5], f[6], rows, item_count) for k, f in META_FAMILIES.items()]
    runs += [(f"h{h}", MASTERY[1], _total(lambda m, h=h: int(m["hero_id"] == h)), False, ms, None)
             for h in sorted({m["hero_id"] for m in ms})]
    got, progress = [], {}
    for key, thresholds, run, low, src, everything in runs:
        values = list(run(src))
        for tier, t in enumerate(thresholds):
            t = everything if t is None else t
            i = next((i for i, v in enumerate(values) if v is not None and (v <= t if low else v >= t)), None)
            if i is None:
                break
            got.append([key, tier, src[i]["start_time"]])
        last = values[-1] if values else None
        progress[key] = round(last, 1) if isinstance(last, float) else last
    return got, progress, sorted({m["hero_id"] for m in ms if won(m)}), sorted({i for r in rows for i in r["items"]})


def rarity(earned_by_player):
    """{"key:tier": % of players holding it} from each player's earned list."""
    counts = Counter(f"{k}:{t}" for got in earned_by_player for k, t, _ in got)
    n = len(earned_by_player) or 1
    return {k: round(100 * c / n) for k, c in counts.items()}
