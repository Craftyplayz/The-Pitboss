import discord
from cogs._meta_heroes_embed import heroes_embed

HEROES = {i: {"name": f"Hero{i}"} for i in range(1, 45)}
ROWS = [{"hero_id": i, "wins": (400 + i * 7) * (1000 + (i * 37) % 500) // 1000, "matches": 1000 + (i * 37) % 500} for i in range(1, 45)]
EMOJI = {i: f"<:h{i}_aaaaaaaaaa:123456789012345678>" for i in HEROES}


def lines(e):
    return "\n".join(f.value for f in e.fields).split("\n")


def test_win_sort_and_numbering():
    e = heroes_embed(ROWS, HEROES, EMOJI, "win", "Oracle+", 7)
    ls = lines(e)
    assert len(ls) == 44 and ls[0].startswith("`1.`") and ls[-1].startswith("`44.`")
    assert "**Hero44**" in ls[0] and "**Hero1**" in ls[-1]
    assert e.title == "Heroes by win rate" and e.author.name == "Hero meta · last 7 days · Oracle+"


def test_pick_sort():
    e = heroes_embed(ROWS, HEROES, EMOJI, "pick", None, 7)
    top = max(ROWS, key=lambda r: r["matches"])["hero_id"]
    assert f"**Hero{top}**" in lines(e)[0]
    assert e.title == "Heroes by pick rate" and e.author.name == "Hero meta · last 7 days"


def test_sizes():
    e = heroes_embed(ROWS, HEROES, EMOJI, "win", "Oracle+", 7)
    assert all(len(f.value) <= 1024 for f in e.fields) and len(e) <= 6000
    assert len(e.fields) >= 3


def test_missing_emoji():
    e = heroes_embed(ROWS, HEROES, {}, "win", None, 7)
    assert "`1.` **Hero44**" in lines(e)[0]
