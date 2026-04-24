"""Tests for playlist_gen.py"""

import os
import tempfile
from pathlib import Path

import pytest

from playlist_gen import collect_show_files, interleave, build_playlist, natural_sort_key


# ---------------------------------------------------------------------------
# natural_sort_key
# ---------------------------------------------------------------------------

def test_natural_sort_numeric_order():
    names = [Path(n) for n in ["ep10.mkv", "ep2.mkv", "ep1.mkv"]]
    assert sorted(names, key=natural_sort_key) == [
        Path("ep1.mkv"), Path("ep2.mkv"), Path("ep10.mkv")
    ]


# ---------------------------------------------------------------------------
# interleave
# ---------------------------------------------------------------------------

def test_interleave_equal_length():
    a = [1, 2, 3]
    b = [4, 5, 6]
    assert interleave([a, b]) == [1, 4, 2, 5, 3, 6]


def test_interleave_unequal_length():
    a = [1, 2, 3, 4, 5]
    b = [6, 7]
    assert interleave([a, b]) == [1, 6, 2, 7, 3, 4, 5]


def test_interleave_three_shows():
    a = ["a1", "a2", "a3"]
    b = ["b1", "b2"]
    c = ["c1", "c2", "c3", "c4"]
    assert interleave([a, b, c]) == [
        "a1", "b1", "c1",
        "a2", "b2", "c2",
        "a3", "c3",
        "c4",
    ]


def test_interleave_single_show():
    assert interleave([["x1", "x2"]]) == ["x1", "x2"]


def test_interleave_empty():
    assert interleave([]) == []


# ---------------------------------------------------------------------------
# interleave -- repeat mode
# ---------------------------------------------------------------------------

def test_interleave_repeat_unequal_length():
    a = [1, 2, 3]
    b = [4, 5]
    # b cycles: slot 3 → 4 (b[0])
    assert interleave([a, b], repeat=True) == [1, 4, 2, 5, 3, 4]


def test_interleave_repeat_equal_length():
    # repeat should behave identically to non-repeat when lengths match
    a = [1, 2]
    b = [3, 4]
    assert interleave([a, b], repeat=True) == interleave([a, b])


def test_interleave_repeat_three_shows():
    a = ["a1", "a2", "a3"]
    b = ["b1", "b2"]
    c = ["c1", "c2", "c3", "c4"]
    # length governed by c (4); a cycles at pos 4 → a1, b cycles at pos 3 → b1 and pos 4 → b2
    assert interleave([a, b, c], repeat=True) == [
        "a1", "b1", "c1",
        "a2", "b2", "c2",
        "a3", "b1", "c3",
        "a1", "b2", "c4",
    ]


def test_interleave_repeat_single_show():
    assert interleave([["x1", "x2"]], repeat=True) == ["x1", "x2"]


# ---------------------------------------------------------------------------
# build_playlist (filesystem integration)
# ---------------------------------------------------------------------------

def _make_tree(base: Path, structure: dict[str, list[str]]):
    """Create subdirs with dummy video files."""
    for show, episodes in structure.items():
        show_dir = base / show
        show_dir.mkdir()
        for ep in episodes:
            (show_dir / ep).write_text("")


def _read_playlist_paths(m3u: Path) -> list[str]:
    lines = m3u.read_text().splitlines()
    return [l for l in lines if l and not l.startswith("#")]


def test_build_two_shows(tmp_path):
    _make_tree(tmp_path, {
        "ShowA": ["a01.mkv", "a02.mkv", "a03.mkv"],
        "ShowB": ["b01.mkv", "b02.mkv"],
    })
    out = tmp_path / "out.m3u"
    count = build_playlist(tmp_path, out, relative=True)

    assert count == 5
    paths = _read_playlist_paths(out)
    assert len(paths) == 5
    # First entry must be ShowA ep1, second ShowB ep1, etc.
    assert Path(paths[0]).name == "a01.mkv"
    assert Path(paths[1]).name == "b01.mkv"
    assert Path(paths[2]).name == "a02.mkv"
    assert Path(paths[3]).name == "b02.mkv"
    assert Path(paths[4]).name == "a03.mkv"


def test_build_ignores_non_video_files(tmp_path):
    show_dir = tmp_path / "Show"
    show_dir.mkdir()
    (show_dir / "ep1.mkv").write_text("")
    (show_dir / "ep2.mkv").write_text("")
    (show_dir / "cover.jpg").write_text("")
    (show_dir / "info.nfo").write_text("")

    out = tmp_path / "out.m3u"
    count = build_playlist(tmp_path, out, relative=False)
    assert count == 2


def test_build_skips_empty_show_dirs(tmp_path):
    _make_tree(tmp_path, {
        "ShowA": ["a01.mkv"],
    })
    (tmp_path / "Empty").mkdir()  # no video files

    out = tmp_path / "out.m3u"
    count = build_playlist(tmp_path, out, relative=False)
    assert count == 1


def test_build_relative_paths(tmp_path):
    _make_tree(tmp_path, {"ShowA": ["ep1.mkv"]})
    out = tmp_path / "out.m3u"
    build_playlist(tmp_path, out, relative=True)
    paths = _read_playlist_paths(out)
    assert not os.path.isabs(paths[0])


def test_build_absolute_paths(tmp_path):
    _make_tree(tmp_path, {"ShowA": ["ep1.mkv"]})
    out = tmp_path / "out.m3u"
    build_playlist(tmp_path, out, relative=False)
    paths = _read_playlist_paths(out)
    assert os.path.isabs(paths[0])


def test_build_returns_zero_for_empty_dir(tmp_path):
    out = tmp_path / "out.m3u"
    count = build_playlist(tmp_path, out, relative=False)
    assert count == 0


def test_build_repeat_cycles_shorter_show(tmp_path):
    _make_tree(tmp_path, {
        "ShowA": ["a01.mkv", "a02.mkv", "a03.mkv"],
        "ShowB": ["b01.mkv", "b02.mkv"],
    })
    out = tmp_path / "out.m3u"
    count = build_playlist(tmp_path, out, relative=True, repeat=True)

    assert count == 6  # 3 (longest) × 2 shows
    paths = _read_playlist_paths(out)
    names = [Path(p).name for p in paths]
    assert names == ["a01.mkv", "b01.mkv", "a02.mkv", "b02.mkv", "a03.mkv", "b01.mkv"]


def test_m3u_header(tmp_path):
    _make_tree(tmp_path, {"ShowA": ["ep1.mkv"]})
    out = tmp_path / "out.m3u"
    build_playlist(tmp_path, out, relative=False)
    content = out.read_text()
    assert content.startswith("#EXTM3U\n")
