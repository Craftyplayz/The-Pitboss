"""Trophies: tiers a Player earns from their full match history (docs/trophies-plan.md). Pure functions.

Only the families match history can answer live here; the ones that need match metadata
(damage, healing, items, kill style, MVP, multi-kills, accuracy) come later via Match Recaps.
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


def player_trophies(history, hero_count):
    """(earned [[key, tier, unix time]], progress {key: current value}, hero ids won with).
    Hero mastery keys are "h<hero_id>" and use MASTERY."""
    ms = sorted(history, key=lambda m: m["start_time"])
    runs = [(k, f[4], f[5], f[6]) for k, f in FAMILIES.items()]
    runs += [(f"h{h}", MASTERY[1], _total(lambda m, h=h: m["hero_id"] == h), False)
             for h in sorted({m["hero_id"] for m in ms})]
    got, progress = [], {}
    for key, thresholds, run, low in runs:
        values = list(run(ms))
        for tier, t in enumerate(thresholds):
            t = hero_count if t is None else t
            i = next((i for i, v in enumerate(values) if v is not None and (v <= t if low else v >= t)), None)
            if i is None:
                break
            got.append([key, tier, ms[i]["start_time"]])
        last = values[-1] if values else None
        progress[key] = round(last, 1) if isinstance(last, float) else last
    return got, progress, sorted({m["hero_id"] for m in ms if won(m)})


def rarity(earned_by_player):
    """{"key:tier": % of players holding it} from each player's earned list."""
    counts = Counter(f"{k}:{t}" for got in earned_by_player for k, t, _ in got)
    n = len(earned_by_player) or 1
    return {k: round(100 * c / n) for k, c in counts.items()}
