from PIL import Image

from cogs._souls_graph import souls_graph

SAMPLE = [(180, 2324), (360, 4614), (540, 7851), (720, 10868), (900, 14106), (1200, 20460), (1500, 26274), (1753, 27938)]


def test_png_and_size():
    buf = souls_graph(SAMPLE)
    assert buf.tell() == 0
    assert buf.getvalue().startswith(b"\x89PNG")
    assert Image.open(buf).size == (800, 300)


def test_empty_single_and_zero():
    for tl in ([], [(60, 500)], [(0, 0)], [(60, 0), (120, 0)]):
        assert Image.open(souls_graph(tl)).size == (800, 300)
