from PIL import Image

from core.graphs import souls_graph

SAMPLE = [(180, 2324), (360, 4614), (540, 7851), (720, 10868), (900, 14106), (1200, 20460), (1500, 26274), (1753, 27938)]


def test_png_and_size():
    buf = souls_graph(SAMPLE)
    assert buf.tell() == 0
    assert buf.getvalue().startswith(b"\x89PNG")
    assert Image.open(buf).size == (800, 300)


def test_empty_single_and_zero():
    for tl in ([], [(60, 500)], [(0, 0)], [(60, 0), (120, 0)]):
        assert Image.open(souls_graph(tl)).size == (800, 300)


def test_souls_image_and_scoreboard():
    from core.recap_images import scoreboard_image, souls_image
    sources = [("Lane creeps", 7970), ("Neutrals", 1869), ("Hero kills", 0), ("Lost on death", -1021)]
    assert Image.open(souls_image(SAMPLE, sources)).width == 800
    rows = [("Lady Geist", "3/12/15", 27627, 15230, False), ("Wraith", "2/9/11", 29731, 24009, True)]
    assert Image.open(scoreboard_image([("YOUR TEAM", False, 1, rows), ("ENEMY TEAM", True, 2, rows[:1])])).width == 800
