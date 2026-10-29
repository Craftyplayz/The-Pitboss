"""Pure Leaderboard math. Aggregates are dicts: matches, wins, kills, deaths, assists, seconds, souls, delta."""
from core.shared import WINDOW_MIN_MATCHES, won

ZERO = dict(matches=0, wins=0, kills=0, deaths=0, assists=0, seconds=0, souls=0.0, delta=0)

METRICS = {
    "Win rate": lambda a: a["wins"] / a["matches"],
    "KDA": lambda a: (a["kills"] + a["assists"]) / max(a["deaths"], 1),
    "Matches played": lambda a: a["matches"],
    "Souls per minute": lambda a: a["souls"] / (a["seconds"] / 60) if a["seconds"] else 0.0,
    # Sum of per-match ranked_delta from match-history: it is exactly what Valve awarded per match,
    # while mmr-history's player_score is on a different scale and has gaps for unranked matches.
    "Rank Climb": lambda a: a["delta"],
}


def from_hero_stats(rows, hero_id=None):
    """Sum /v1/players/hero-stats rows (one per hero) for one Player, optionally one hero."""
    agg = dict(ZERO)
    for r in rows:
        if hero_id is not None and r["hero_id"] != hero_id:
            continue
        agg["matches"] += r["matches_played"]
        agg["wins"] += r["wins"]
        agg["kills"] += r["kills"]
        agg["deaths"] += r["deaths"]
        agg["assists"] += r["assists"]
        agg["seconds"] += r["time_played"]
        agg["souls"] += r["networth_per_min"] * r["time_played"] / 60
    return agg


def from_history(entries, since, hero_id=None):
    """Aggregate match-history entries inside the window, optionally one hero."""
    agg = dict(ZERO)
    for m in entries:
        if m["start_time"] < since or (hero_id is not None and m["hero_id"] != hero_id):
            continue
        agg["matches"] += 1
        agg["wins"] += won(m)
        agg["kills"] += m["player_kills"]
        agg["deaths"] += m["player_deaths"]
        agg["assists"] += m["player_assists"]
        agg["seconds"] += m["match_duration_s"]
        agg["souls"] += m["net_worth"]
        agg["delta"] += m.get("ranked_delta") or 0
    return agg


def rank_board(aggs, metric, minimum=WINDOW_MIN_MATCHES):
    """aggs: {key: agg}. Returns [(key, value)] best first; under-minimum players dropped.
    Ties go to more matches, then key, so the order is stable."""
    scored = [(k, METRICS[metric](a), a["matches"]) for k, a in aggs.items() if a["matches"] >= minimum]
    scored.sort(key=lambda t: (-t[1], -t[2], t[0]))
    return [(k, v) for k, v, _ in scored]


def rank_by_badge(ranks):
    """ranks: {key: badge}. Badge is tier*10+subrank, so higher is better. Unranked (0/None) dropped."""
    items = [(k, b) for k, b in ranks.items() if b]
    items.sort(key=lambda t: (-t[1], t[0]))
    return items
