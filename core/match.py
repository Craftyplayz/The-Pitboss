"""Pure functions over /v1/matches/{id}/metadata: no network, no Discord."""


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


def souls_sources(s):
    """[(label, souls)] by source, then the souls lost on death (negative)."""
    return [("Lane creeps", s["gold_lane_creep"]), ("Neutrals", s["gold_neutral_creep"]),
            ("Hero kills", s["gold_player"]), ("Objectives", s["gold_boss"]), ("Treasure", s["gold_treasure"]),
            ("Lost on death", -s["gold_death_loss"])]


def scoreboard(players, me, hero_names, won):
    """[(label, won, team souls, rows)] for your team then the enemy; rows are (hero, kda, souls, damage, is_me), richest first."""
    out = []
    for label, team, team_won in (("YOUR TEAM", me["team"], won), ("ENEMY TEAM", 1 - me["team"], not won)):
        ps = sorted((p for p in players if p["team"] == team), key=lambda p: -p["net_worth"])
        rows = [(hero_names.get(p["hero_id"], f"Hero {p['hero_id']}"), f"{p['kills']}/{p['deaths']}/{p['assists']}",
                 p["net_worth"], p["stats"][-1]["player_damage"], p is me) for p in ps]
        out.append((label, team_won, sum(p["net_worth"] for p in ps), rows))
    return out
