"""Insights: rule-based comparisons over match-history entries (newest first). Pure functions."""
MIN_HISTORY = 10  # matches needed before any Insight shows
MIN_HERO = 5  # matches on one hero before it can be "best" or "worst"
MIN_STREAK = 3
WR_GAP = 0.10  # hero win rate must differ from own average by this much
STAT_GAP = 0.25  # match stat must differ from own average by this fraction


def _won(m):
    return m["match_result"] == m["player_team"]


def _kda(ms):
    return (sum(m["player_kills"] + m["player_assists"] for m in ms)
            / max(sum(m["player_deaths"] for m in ms), 1))


def _spm(ms):
    mins = sum(m["match_duration_s"] for m in ms) / 60
    return sum(m["net_worth"] for m in ms) / mins if mins else 0


def _streak(history):
    n = 0
    for m in history:
        if _won(m) != _won(history[0]):
            break
        n += 1
    return n


def profile_insights(history, hero_names):
    if len(history) < MIN_HISTORY:
        return []
    avg = sum(map(_won, history)) / len(history)
    heroes = {}
    for m in history:
        heroes.setdefault(m["hero_id"], []).append(_won(m))
    rates = {h: (sum(w) / len(w), len(w)) for h, w in heroes.items() if len(w) >= MIN_HERO}
    out = []
    if rates:
        best = max(rates, key=lambda h: rates[h][0])
        worst = min(rates, key=lambda h: rates[h][0])
        for h, word, sign in ((best, "Best", 1), (worst, "Worst", -1)):
            wr, n = rates[h]
            if sign * (wr - avg) >= WR_GAP:
                name = hero_names.get(h, f"Hero {h}")
                out.append(f"{word} hero: {name} at {wr:.0%} win rate over {n} matches (average {avg:.0%}).")
    s = _streak(history)
    if s >= MIN_STREAK:
        out.append(f"On a {s}-match {'win' if _won(history[0]) else 'loss'} streak.")
    return out[:3]


def match_insights(match, history, hero_names):
    others = [m for m in history if m["match_id"] != match["match_id"]]
    if len(others) < MIN_HISTORY:
        return []
    out = []
    kda = (match["player_kills"] + match["player_assists"]) / max(match["player_deaths"], 1)
    avg_kda = _kda(others)
    if avg_kda and abs(kda - avg_kda) / avg_kda >= STAT_GAP:
        out.append(f"KDA {kda:.1f} this match, {'above' if kda > avg_kda else 'below'} your average of {avg_kda:.1f}.")
    spm, avg_spm = _spm([match]), _spm(others)
    if avg_spm and abs(spm - avg_spm) / avg_spm >= STAT_GAP:
        out.append(f"{spm:.0f} souls/min, {'above' if spm > avg_spm else 'below'} your average of {avg_spm:.0f}.")
    same = [m for m in others if m["hero_id"] == match["hero_id"]]
    if len(same) >= MIN_HERO:
        wr = sum(map(_won, same)) / len(same)
        name = hero_names.get(match["hero_id"], f"Hero {match['hero_id']}")
        out.append(f"{name} win rate before this match: {wr:.0%} over {len(same)} matches.")
    s = _streak([match] + others)
    if s >= MIN_STREAK:
        out.append(f"That makes a {s}-match {'win' if _won(match) else 'loss'} streak.")
    return out[:3]
