"""Constants and helpers shared by the bot and the website."""
import time

WINDOW_DAYS = 30
WINDOW_MIN_MATCHES = 10


def window_start():
    """Unix time where the Leaderboard Window begins."""
    return int(time.time()) - WINDOW_DAYS * 86400


def won(match):
    """True if the Player won this match-history entry."""
    return match["match_result"] == match["player_team"]
