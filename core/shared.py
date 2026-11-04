"""Constants and helpers shared by the bot and the website."""
import os
import time

WINDOW_DAYS = 30
WINDOW_MIN_MATCHES = 10
SITE_URL = os.environ.get("SITE_URL", "https://pitboss.craftyplayz.com").rstrip("/")
# The Pitstop, the control panel; the live voice transcript links to its call page
DASH_URL = os.environ.get("DASH_URL", "https://pitstop.craftyplayz.com").rstrip("/")


def window_start():
    """Unix time where the Leaderboard Window begins."""
    return int(time.time()) - WINDOW_DAYS * 86400


def site_links(account_id, match_id, hero_id):
    """Deep links into the website's dashboard (its views are picked by the URL hash)."""
    return {"home": f"{SITE_URL}/", "player": f"{SITE_URL}/#players/{account_id}",
            "match": f"{SITE_URL}/#matches/{match_id}/{account_id}", "hero": f"{SITE_URL}/#heroes/{hero_id}",
            "leaderboards": f"{SITE_URL}/#leaderboards"}


def item_icon(item):
    """An item asset's icon URL. Some upgrades (e.g. Stalker, Spellslinger) only have a shop_image.
    An SVG image (Rebuttal, Counterspell: a generic parry icon) loses to the shop_image, since Discord emojis can't be SVG."""
    image = item.get("image") or ""
    if image.endswith(".svg") and item.get("shop_image"):
        return item["shop_image"]
    return image or item.get("shop_image") or ""


STREET_BRAWL = 4  # match-history game_mode (deadlock-api's ECitadelGameMode enum: 1 = Normal, 4 = Street Brawl)


def brawl(match):
    """1 if this match-history entry is Street Brawl, which win rates leave out."""
    return int(match.get("game_mode") == STREET_BRAWL)


def won(match):
    """True if the Player won this match-history entry."""
    return match["match_result"] == match["player_team"]
