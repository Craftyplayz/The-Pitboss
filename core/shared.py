"""Constants and helpers shared by the bot and the website."""
import os
import time

WINDOW_DAYS = 30
WINDOW_MIN_MATCHES = 10
SITE_URL = os.environ.get("SITE_URL", "https://deadlock.craftyplayz.com").rstrip("/")


def window_start():
    """Unix time where the Leaderboard Window begins."""
    return int(time.time()) - WINDOW_DAYS * 86400


def site_links(account_id, match_id, hero_id):
    """Deep links into the website's dashboard (its views are picked by the URL hash)."""
    return {"home": f"{SITE_URL}/", "player": f"{SITE_URL}/#players/{account_id}",
            "match": f"{SITE_URL}/#matches/{match_id}/{account_id}", "hero": f"{SITE_URL}/#heroes/{hero_id}",
            "leaderboards": f"{SITE_URL}/#leaderboards"}


def item_icon(item):
    """An item asset's icon URL. Some upgrades (e.g. Stalker, Spellslinger) only have a shop_image."""
    return item.get("image") or item.get("shop_image") or ""


def won(match):
    """True if the Player won this match-history entry."""
    return match["match_result"] == match["player_team"]
