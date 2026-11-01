import pytest

from dtranscript.core import render_markdown, slugify
from dtranscript.youtube import Segment, Transcript, fmt_ts, parse_video_id

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
    VID,
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtube.com/watch?feature=share&v={VID}&t=10s",
    f"https://m.youtube.com/watch?v={VID}",
    f"https://youtu.be/{VID}?si=abc",
    f"https://www.youtube.com/shorts/{VID}",
    f"youtube.com/shorts/{VID}?feature=share",
    f"https://www.youtube.com/embed/{VID}",
    f"https://www.youtube.com/live/{VID}",
])
def test_parse_video_id(url):
    assert parse_video_id(url) == VID


@pytest.mark.parametrize("url", ["", "https://example.com/watch?v=" + VID, "https://youtube.com/@channel"])
def test_parse_video_id_rejects(url):
    with pytest.raises(ValueError):
        parse_video_id(url)


def test_fmt_ts():
    assert fmt_ts(5) == "00:05"
    assert fmt_ts(65.9) == "01:05"
    assert fmt_ts(3725) == "1:02:05"


def test_slugify():
    assert slugify('Eleições 2026: "O que muda?"') == "eleicoes-2026-o-que-muda"


def test_render_raw():
    t = Transcript(VID, "https://www.youtube.com/watch?v=" + VID,
                   [Segment(0, "olá"), Segment(61, "mundo")], "captions:pt", "pt", {"title": 'A "quoted" title'})
    md = render_markdown(t, "raw")
    assert md.startswith("---\n")
    assert 'title: "A \\"quoted\\" title"' in md
    assert "**[01:01]** mundo" in md
    assert "ai_generated: false" in md
