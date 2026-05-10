"""Tests for playlist_gen.py"""

import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

from playlist_gen import (
    _natural_key,
    _scan_dirs,
    _collect_group_episodes,
    _collect_group_seasons,
    natural_sort_key,
    collect_show_files,
    collect_show_seasons,
    interleave,
    interleave_in_blocks,
    shuffle_in_blocks,
    interleave_by_season,
    build_playlist,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tree(base: Path, structure: dict[str, list[str]]):
    """Create show subdirs with dummy video files directly inside each."""
    for show, episodes in structure.items():
        show_dir = base / show
        show_dir.mkdir(exist_ok=True)
        for ep in episodes:
            (show_dir / ep).write_text("")


def _make_season_tree(show_dir: Path, seasons: dict[str, list[str]]):
    """Create season subdirs with dummy video files inside show_dir."""
    show_dir.mkdir(parents=True, exist_ok=True)
    for season, episodes in seasons.items():
        season_dir = show_dir / season
        season_dir.mkdir()
        for ep in episodes:
            (season_dir / ep).write_text("")


def _read_playlist_paths(m3u: Path) -> list[str]:
    lines = m3u.read_text().splitlines()
    return [l for l in lines if l and not l.startswith("#")]


# ---------------------------------------------------------------------------
# natural_sort_key
# ---------------------------------------------------------------------------

def test_natural_sort_numeric_order():
    names = [Path(n) for n in ["ep10.mkv", "ep2.mkv", "ep1.mkv"]]
    assert sorted(names, key=natural_sort_key) == [
        Path("ep1.mkv"), Path("ep2.mkv"), Path("ep10.mkv")
    ]


# ---------------------------------------------------------------------------
# collect_show_files — season subdirectory support
# ---------------------------------------------------------------------------

def test_collect_flat_show_unchanged(tmp_path):
    show = tmp_path / "Show"
    show.mkdir()
    for name in ["ep1.mkv", "ep2.mkv", "ep10.mkv"]:
        (show / name).write_text("")
    result = [f.name for f in collect_show_files(show)]
    assert result == ["ep1.mkv", "ep2.mkv", "ep10.mkv"]


def test_collect_single_season_dir(tmp_path):
    show = tmp_path / "Show"
    _make_season_tree(show, {"Season 1": ["s01e01.mkv", "s01e02.mkv", "s01e03.mkv"]})
    result = [f.name for f in collect_show_files(show)]
    assert result == ["s01e01.mkv", "s01e02.mkv", "s01e03.mkv"]


def test_collect_multiple_seasons_natural_order(tmp_path):
    show = tmp_path / "Show"
    _make_season_tree(show, {
        "Season 2":  ["s02e01.mkv", "s02e02.mkv"],
        "Season 10": ["s10e01.mkv"],
        "Season 1":  ["s01e01.mkv", "s01e02.mkv", "s01e03.mkv"],
    })
    result = [f.name for f in collect_show_files(show)]
    assert result == [
        "s01e01.mkv", "s01e02.mkv", "s01e03.mkv",
        "s02e01.mkv", "s02e02.mkv",
        "s10e01.mkv",
    ]


def test_collect_ignores_non_video_in_season(tmp_path):
    show = tmp_path / "Show"
    season = show / "Season 1"
    season.mkdir(parents=True)
    (season / "ep1.mkv").write_text("")
    (season / "poster.jpg").write_text("")
    (season / "metadata.nfo").write_text("")
    result = [f.name for f in collect_show_files(show)]
    assert result == ["ep1.mkv"]


def test_collect_episodes_within_season_natural_order(tmp_path):
    show = tmp_path / "Show"
    _make_season_tree(show, {
        "Season 1": ["ep9.mkv", "ep10.mkv", "ep2.mkv", "ep1.mkv"],
    })
    result = [f.name for f in collect_show_files(show)]
    assert result == ["ep1.mkv", "ep2.mkv", "ep9.mkv", "ep10.mkv"]


# ---------------------------------------------------------------------------
# collect_show_seasons
# ---------------------------------------------------------------------------

def test_seasons_flat_show(tmp_path):
    show = tmp_path / "Show"
    show.mkdir()
    for n in ["ep1.mkv", "ep2.mkv"]:
        (show / n).write_text("")
    result = collect_show_seasons(show)
    assert len(result) == 1
    assert [f.name for f in result[0]] == ["ep1.mkv", "ep2.mkv"]


def test_seasons_single_season_dir(tmp_path):
    show = tmp_path / "Show"
    _make_season_tree(show, {"Season 1": ["s01e01.mkv", "s01e02.mkv"]})
    result = collect_show_seasons(show)
    assert len(result) == 1
    assert [f.name for f in result[0]] == ["s01e01.mkv", "s01e02.mkv"]


def test_seasons_multiple_season_dirs(tmp_path):
    show = tmp_path / "Show"
    _make_season_tree(show, {
        "Season 1": ["s01e01.mkv", "s01e02.mkv"],
        "Season 2": ["s02e01.mkv"],
    })
    result = collect_show_seasons(show)
    assert len(result) == 2
    assert [f.name for f in result[0]] == ["s01e01.mkv", "s01e02.mkv"]
    assert [f.name for f in result[1]] == ["s02e01.mkv"]


def test_seasons_natural_ordering(tmp_path):
    show = tmp_path / "Show"
    _make_season_tree(show, {
        "Season 2":  ["s02e01.mkv"],
        "Season 10": ["s10e01.mkv"],
        "Season 1":  ["s01e01.mkv"],
    })
    result = collect_show_seasons(show)
    assert len(result) == 3
    assert result[0][0].name == "s01e01.mkv"
    assert result[1][0].name == "s02e01.mkv"
    assert result[2][0].name == "s10e01.mkv"


def test_seasons_mixed_root_files_and_season_dirs(tmp_path):
    show = tmp_path / "Show"
    _make_season_tree(show, {"Season 1": ["s01e01.mkv"]})
    (show / "special.mkv").write_text("")  # file directly in show root
    result = collect_show_seasons(show)
    # Root files come first, then season dirs
    assert len(result) == 2
    assert result[0][0].name == "special.mkv"
    assert result[1][0].name == "s01e01.mkv"


def test_seasons_empty_show(tmp_path):
    show = tmp_path / "Show"
    show.mkdir()
    assert collect_show_seasons(show) == []


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
    assert interleave([a, b], repeat=True) == [1, 4, 2, 5, 3, 4]


def test_interleave_repeat_equal_length():
    a = [1, 2]
    b = [3, 4]
    assert interleave([a, b], repeat=True) == interleave([a, b])


def test_interleave_repeat_three_shows():
    a = ["a1", "a2", "a3"]
    b = ["b1", "b2"]
    c = ["c1", "c2", "c3", "c4"]
    assert interleave([a, b, c], repeat=True) == [
        "a1", "b1", "c1",
        "a2", "b2", "c2",
        "a3", "b1", "c3",
        "a1", "b2", "c4",
    ]


def test_interleave_repeat_single_show():
    assert interleave([["x1", "x2"]], repeat=True) == ["x1", "x2"]


# ---------------------------------------------------------------------------
# shuffle_in_blocks
# ---------------------------------------------------------------------------

def test_shuffle_in_blocks_preserves_all_items():
    eps = [Path(f"ep{i:02d}.mkv") for i in range(9)]
    random.seed(0)
    result = shuffle_in_blocks(eps, 3)
    assert len(result) == 9
    assert set(result) == set(eps)


def test_shuffle_in_blocks_respects_boundaries():
    eps = [Path(f"ep{i:02d}.mkv") for i in range(6)]
    random.seed(0)
    result = shuffle_in_blocks(eps, 3)
    # Each half must still be contained within its block boundary
    assert set(result[:3]) == {Path("ep00.mkv"), Path("ep01.mkv"), Path("ep02.mkv")}
    assert set(result[3:]) == {Path("ep03.mkv"), Path("ep04.mkv"), Path("ep05.mkv")}


def test_shuffle_in_blocks_partial_last_block():
    eps = [Path(f"ep{i:02d}.mkv") for i in range(5)]
    random.seed(0)
    result = shuffle_in_blocks(eps, 3)
    assert len(result) == 5
    assert set(result) == set(eps)


def test_shuffle_in_blocks_size_one_is_noop():
    eps = [Path(f"ep{i:02d}.mkv") for i in range(4)]
    result = shuffle_in_blocks(eps, 1)
    assert result == eps


# ---------------------------------------------------------------------------
# interleave_in_blocks
# ---------------------------------------------------------------------------

def test_interleave_in_blocks_basic():
    a = [1, 2, 3, 4, 5]
    b = [6, 7, 8]
    assert interleave_in_blocks([a, b], block_size=2) == [1, 2, 6, 7, 3, 4, 8, 5]


def test_interleave_in_blocks_equal_length():
    a = [1, 2, 3, 4]
    b = [5, 6, 7, 8]
    assert interleave_in_blocks([a, b], block_size=2) == [1, 2, 5, 6, 3, 4, 7, 8]


def test_interleave_in_blocks_size_larger_than_list():
    a = [1, 2]
    b = [3, 4, 5, 6]
    assert interleave_in_blocks([a, b], block_size=5) == [1, 2, 3, 4, 5, 6]


def test_interleave_in_blocks_repeat():
    a = [1, 2, 3]
    b = [4, 5]
    # max_len=3, cycled b=[4,5,4]; block_size=2
    # round 0: a[0:2]=1,2 + b[0:2]=4,5; round 1: a[2:4]=3 + b[2:4]=4
    assert interleave_in_blocks([a, b], block_size=2, repeat=True) == [1, 2, 4, 5, 3, 4]


def test_interleave_in_blocks_empty():
    assert interleave_in_blocks([], block_size=3) == []


# ---------------------------------------------------------------------------
# interleave_by_season
# ---------------------------------------------------------------------------

def test_interleave_by_season_total_count():
    sa = [[Path("a01.mkv"), Path("a02.mkv")], [Path("a03.mkv")]]
    sb = [[Path("b01.mkv")], [Path("b02.mkv"), Path("b03.mkv")]]
    random.seed(0)
    result = interleave_by_season([sa, sb])
    assert len(result) == 6
    assert set(result) == {
        Path("a01.mkv"), Path("a02.mkv"), Path("a03.mkv"),
        Path("b01.mkv"), Path("b02.mkv"), Path("b03.mkv"),
    }


def test_interleave_by_season_shorter_show_skipped():
    sa = [[Path("a01.mkv")], [Path("a02.mkv")]]  # 2 seasons
    sb = [[Path("b01.mkv")]]                       # 1 season
    random.seed(0)
    result = interleave_by_season([sa, sb])
    # Season 1: a01 + b01; Season 2: a02 only
    assert len(result) == 3
    assert Path("a01.mkv") in result
    assert Path("b01.mkv") in result
    assert Path("a02.mkv") in result


def test_interleave_by_season_repeat():
    sa = [[Path("a01.mkv")], [Path("a02.mkv")]]  # 2 seasons
    sb = [[Path("b01.mkv")]]                       # 1 season — cycles
    random.seed(0)
    result = interleave_by_season([sa, sb], repeat=True)
    # Season 1: a01 + b01; Season 2: a02 + b01 (cycled)
    assert len(result) == 4
    assert result.count(Path("b01.mkv")) == 2


def test_interleave_by_season_empty():
    assert interleave_by_season([]) == []


# ---------------------------------------------------------------------------
# build_playlist (filesystem integration)
# ---------------------------------------------------------------------------

def test_build_two_shows(tmp_path):
    _make_tree(tmp_path, {
        "ShowA": ["a01.mkv", "a02.mkv", "a03.mkv"],
        "ShowB": ["b01.mkv", "b02.mkv"],
    })
    out = tmp_path / "out.m3u"
    count = build_playlist([tmp_path], out, relative=True)

    assert count == 5
    paths = _read_playlist_paths(out)
    assert [Path(p).name for p in paths] == [
        "a01.mkv", "b01.mkv", "a02.mkv", "b02.mkv", "a03.mkv",
    ]


def test_build_ignores_non_video_files(tmp_path):
    show_dir = tmp_path / "Show"
    show_dir.mkdir()
    (show_dir / "ep1.mkv").write_text("")
    (show_dir / "ep2.mkv").write_text("")
    (show_dir / "cover.jpg").write_text("")
    (show_dir / "info.nfo").write_text("")

    out = tmp_path / "out.m3u"
    count = build_playlist([tmp_path], out, relative=False)
    assert count == 2


def test_build_skips_empty_show_dirs(tmp_path):
    _make_tree(tmp_path, {"ShowA": ["a01.mkv"]})
    (tmp_path / "Empty").mkdir()

    out = tmp_path / "out.m3u"
    count = build_playlist([tmp_path], out, relative=False)
    assert count == 1


def test_build_relative_paths(tmp_path):
    _make_tree(tmp_path, {"ShowA": ["ep1.mkv"]})
    out = tmp_path / "out.m3u"
    build_playlist([tmp_path], out, relative=True)
    paths = _read_playlist_paths(out)
    assert not os.path.isabs(paths[0])


def test_build_absolute_paths(tmp_path):
    _make_tree(tmp_path, {"ShowA": ["ep1.mkv"]})
    out = tmp_path / "out.m3u"
    build_playlist([tmp_path], out, relative=False)
    paths = _read_playlist_paths(out)
    assert os.path.isabs(paths[0])


def test_build_returns_zero_for_empty_dir(tmp_path):
    out = tmp_path / "out.m3u"
    count = build_playlist([tmp_path], out, relative=False)
    assert count == 0


def test_build_repeat_cycles_shorter_show(tmp_path):
    _make_tree(tmp_path, {
        "ShowA": ["a01.mkv", "a02.mkv", "a03.mkv"],
        "ShowB": ["b01.mkv", "b02.mkv"],
    })
    out = tmp_path / "out.m3u"
    count = build_playlist([tmp_path], out, relative=True, repeat=True)

    assert count == 6
    names = [Path(p).name for p in _read_playlist_paths(out)]
    assert names == ["a01.mkv", "b01.mkv", "a02.mkv", "b02.mkv", "a03.mkv", "b01.mkv"]


def test_build_season_show_interleaved_with_flat_show(tmp_path):
    show_a = tmp_path / "ShowA"
    _make_season_tree(show_a, {
        "Season 1": ["s01e01.mkv", "s01e02.mkv"],
        "Season 2": ["s02e01.mkv"],
    })
    show_b = tmp_path / "ShowB"
    show_b.mkdir()
    for name in ["b01.mkv", "b02.mkv", "b03.mkv"]:
        (show_b / name).write_text("")

    out = tmp_path / "out.m3u"
    count = build_playlist([tmp_path], out, relative=True)

    assert count == 6
    names = [Path(p).name for p in _read_playlist_paths(out)]
    assert names == [
        "s01e01.mkv", "b01.mkv",
        "s01e02.mkv", "b02.mkv",
        "s02e01.mkv", "b03.mkv",
    ]


def test_build_multiple_dirs(tmp_path):
    dir1 = tmp_path / "dir1"
    dir2 = tmp_path / "dir2"
    dir1.mkdir()
    dir2.mkdir()
    _make_tree(dir1, {"ShowA": ["a01.mkv", "a02.mkv"]})
    _make_tree(dir2, {"ShowB": ["b01.mkv", "b02.mkv"]})

    out = tmp_path / "out.m3u"
    count = build_playlist([dir1, dir2], out, relative=False)

    assert count == 4
    names = [Path(p).name for p in _read_playlist_paths(out)]
    assert names == ["a01.mkv", "b01.mkv", "a02.mkv", "b02.mkv"]


def test_build_multiple_dirs_duplicate_show_names(tmp_path):
    dir1 = tmp_path / "dir1"
    dir2 = tmp_path / "dir2"
    dir1.mkdir()
    dir2.mkdir()
    _make_tree(dir1, {"ShowA": ["a01.mkv"]})
    _make_tree(dir2, {"ShowA": ["a02.mkv"]})  # same name in a different dir

    out = tmp_path / "out.m3u"
    count = build_playlist([dir1, dir2], out, relative=False)

    assert count == 2  # both episodes included, despite same show name


def test_build_shuffle_episodes_block_order(tmp_path):
    """episodes mode plays block_size consecutive episodes per show in order before switching."""
    _make_tree(tmp_path, {
        "ShowA": [f"a{i:02d}.mkv" for i in range(1, 6)],   # a01–a05
        "ShowB": [f"b{i:02d}.mkv" for i in range(1, 4)],   # b01–b03
    })
    out = tmp_path / "out.m3u"
    count = build_playlist([tmp_path], out, relative=False, shuffle_mode="episodes", shuffle_n=2)

    assert count == 8
    names = [Path(p).name for p in _read_playlist_paths(out)]
    # Block size 2: a01,a02, b01,b02, a03,a04, b03, a05
    assert names == ["a01.mkv", "a02.mkv", "b01.mkv", "b02.mkv",
                     "a03.mkv", "a04.mkv", "b03.mkv", "a05.mkv"]


def test_build_shuffle_seasons_preserves_count(tmp_path):
    show_a = tmp_path / "ShowA"
    show_b = tmp_path / "ShowB"
    _make_season_tree(show_a, {"Season 1": ["s01e01.mkv", "s01e02.mkv"], "Season 2": ["s02e01.mkv"]})
    _make_season_tree(show_b, {"Season 1": ["b01e01.mkv"], "Season 2": ["b02e01.mkv", "b02e02.mkv"]})

    out = tmp_path / "out.m3u"
    random.seed(42)
    count = build_playlist([tmp_path], out, relative=False, shuffle_mode="seasons")

    assert count == 6
    paths = _read_playlist_paths(out)
    assert len(set(paths)) == 6  # no duplicates


def test_build_include_excludes_shows(tmp_path):
    _make_tree(tmp_path, {
        "ShowA": ["a01.mkv", "a02.mkv"],
        "ShowB": ["b01.mkv", "b02.mkv"],
        "ShowC": ["c01.mkv"],
    })
    out = tmp_path / "out.m3u"
    count = build_playlist([tmp_path], out, relative=False, include={"ShowA", "ShowC"})

    assert count == 3
    names = {Path(p).name for p in _read_playlist_paths(out)}
    assert names == {"a01.mkv", "a02.mkv", "c01.mkv"}
    assert not any("b" in n for n in names)


def test_build_include_empty_set_produces_nothing(tmp_path):
    _make_tree(tmp_path, {"ShowA": ["a01.mkv"]})
    out = tmp_path / "out.m3u"
    count = build_playlist([tmp_path], out, relative=False, include=set())
    assert count == 0


def test_m3u_header(tmp_path):
    _make_tree(tmp_path, {"ShowA": ["ep1.mkv"]})
    out = tmp_path / "out.m3u"
    build_playlist([tmp_path], out, relative=False)
    assert out.read_text().startswith("#EXTM3U\n")


# ---------------------------------------------------------------------------
# Regression / edge case tests
# ---------------------------------------------------------------------------

def test_cli_shuffle_n_zero_produces_error(tmp_path):
    """--shuffle-n 0 must fail with a clear argparse error, not a crash."""
    _make_tree(tmp_path, {"ShowA": ["ep1.mkv"]})
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "playlist_gen.py"),
         str(tmp_path), "--shuffle", "episodes", "--shuffle-n", "0"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    assert "error" in combined or "invalid" in combined


def test_scan_dirs_deduplication_suffix(tmp_path):
    """Same show name in two source dirs gets a '(2)' suffix on the second."""
    dir1 = tmp_path / "dir1"
    dir2 = tmp_path / "dir2"
    dir1.mkdir()
    dir2.mkdir()
    (dir1 / "ShowA").mkdir()
    (dir2 / "ShowA").mkdir()

    result = _scan_dirs([dir1, dir2])
    labels = [label for label, _ in result]
    assert "ShowA" in labels
    assert "ShowA (2)" in labels


def test_collect_show_seasons_empty_season_dir_skipped(tmp_path):
    """An empty season subdirectory is silently skipped; others are still returned."""
    show = tmp_path / "Show"
    show.mkdir()
    (show / "Season 1").mkdir()          # empty — no video files
    season2 = show / "Season 2"
    season2.mkdir()
    (season2 / "s02e01.mkv").write_text("")

    result = collect_show_seasons(show)
    assert len(result) == 1
    assert result[0][0].name == "s02e01.mkv"


def test_build_playlist_missing_output_dir_returns_zero(tmp_path, capsys):
    """build_playlist returns 0 and prints an error when the output directory doesn't exist."""
    _make_tree(tmp_path, {"ShowA": ["ep1.mkv"]})
    out = tmp_path / "nonexistent_dir" / "out.m3u"
    count = build_playlist([tmp_path], out, relative=False)
    assert count == 0
    captured = capsys.readouterr()
    assert "error" in (captured.err + captured.out).lower()


# ---------------------------------------------------------------------------
# Show grouping
# ---------------------------------------------------------------------------

def test_collect_group_episodes_sequential(tmp_path):
    """Episodes from grouped shows are concatenated in order: all of ShowB then all of ShowC."""
    show_b = tmp_path / "ShowB"
    show_b.mkdir()
    (show_b / "b01.mkv").write_text("")
    (show_b / "b02.mkv").write_text("")

    show_c = tmp_path / "ShowC"
    show_c.mkdir()
    (show_c / "c01.mkv").write_text("")

    label_to_path = {"ShowB": show_b, "ShowC": show_c}
    result = _collect_group_episodes(["ShowB", "ShowC"], label_to_path)
    names = [f.name for f in result]
    assert names == ["b01.mkv", "b02.mkv", "c01.mkv"]


def test_collect_group_seasons_sequential(tmp_path):
    """Season groups from all shows in a group are concatenated in show order."""
    show_b = tmp_path / "ShowB"
    _make_season_tree(show_b, {"Season 1": ["b01.mkv", "b02.mkv"]})

    show_c = tmp_path / "ShowC"
    _make_season_tree(show_c, {
        "Season 1": ["c01.mkv"],
        "Season 2": ["c02.mkv"],
    })

    label_to_path = {"ShowB": show_b, "ShowC": show_c}
    result = _collect_group_seasons(["ShowB", "ShowC"], label_to_path)
    # ShowB: 1 season group, ShowC: 2 season groups → total 3
    assert len(result) == 3
    assert [f.name for f in result[0]] == ["b01.mkv", "b02.mkv"]
    assert [f.name for f in result[1]] == ["c01.mkv"]
    assert [f.name for f in result[2]] == ["c02.mkv"]


def test_build_playlist_group_acts_as_single_slot(tmp_path):
    """Grouped shows act as one round-robin slot: ShowA vs Group[ShowB, ShowC]."""
    _make_tree(tmp_path, {
        "ShowA": ["a01.mkv", "a02.mkv", "a03.mkv"],
        "ShowB": ["b01.mkv", "b02.mkv"],
        "ShowC": ["c01.mkv"],
    })
    out = tmp_path / "out.m3u"
    # Group ShowB + ShowC together → 2-way round-robin: ShowA vs [B1, B2, C1]
    count = build_playlist([tmp_path], out, relative=False, groups=[["ShowB", "ShowC"]])

    assert count == 6
    names = [Path(p).name for p in _read_playlist_paths(out)]
    # Expected: a01,b01, a02,b02, a03,c01
    assert names == ["a01.mkv", "b01.mkv", "a02.mkv", "b02.mkv", "a03.mkv", "c01.mkv"]
    # ShowB must fully precede ShowC in the group slot
    b_indices = [i for i, n in enumerate(names) if n.startswith("b")]
    c_indices = [i for i, n in enumerate(names) if n.startswith("c")]
    assert max(b_indices) < min(c_indices)


def test_build_playlist_group_seasons_mode(tmp_path):
    """In season mode, a group's seasons = all member shows' seasons concatenated."""
    show_a = tmp_path / "ShowA"
    _make_season_tree(show_a, {"Season 1": ["a01.mkv", "a02.mkv"], "Season 2": ["a03.mkv"]})

    show_b = tmp_path / "ShowB"
    _make_season_tree(show_b, {"Season 1": ["b01.mkv"]})

    show_c = tmp_path / "ShowC"
    _make_season_tree(show_c, {"Season 1": ["c01.mkv"], "Season 2": ["c02.mkv"]})

    out = tmp_path / "out.m3u"
    import random
    random.seed(42)
    # Group [ShowB, ShowC]: 3 season groups; ShowA: 2 seasons → interleave_by_season
    count = build_playlist(
        [tmp_path], out, relative=False,
        shuffle_mode="seasons",
        groups=[["ShowB", "ShowC"]],
    )
    assert count == 6
    names = set(Path(p).name for p in _read_playlist_paths(out))
    assert names == {"a01.mkv", "a02.mkv", "a03.mkv", "b01.mkv", "c01.mkv", "c02.mkv"}


def test_build_playlist_group_with_repeat(tmp_path):
    """repeat=True cycles the group slot like any other show slot."""
    _make_tree(tmp_path, {
        "ShowA": ["a01.mkv", "a02.mkv", "a03.mkv", "a04.mkv"],
        "ShowB": ["b01.mkv"],
        "ShowC": ["c01.mkv"],
    })
    out = tmp_path / "out.m3u"
    # Group [ShowB, ShowC] = 2 eps; ShowA = 4 eps; repeat cycles group
    count = build_playlist(
        [tmp_path], out, relative=False,
        repeat=True,
        groups=[["ShowB", "ShowC"]],
    )
    assert count == 8  # 4 × 2 slots
    names = [Path(p).name for p in _read_playlist_paths(out)]
    a_names = [n for n in names if n.startswith("a")]
    g_names = [n for n in names if not n.startswith("a")]
    assert a_names == ["a01.mkv", "a02.mkv", "a03.mkv", "a04.mkv"]
    assert len(g_names) == 4  # group slot repeated 4 times


# ---------------------------------------------------------------------------
# Show order randomization
# ---------------------------------------------------------------------------

def test_build_playlist_random_show_order_preserves_all_episodes(tmp_path):
    """show_order='random' still produces all episodes with no duplicates."""
    _make_tree(tmp_path, {
        "ShowA": ["a01.mkv", "a02.mkv"],
        "ShowB": ["b01.mkv", "b02.mkv"],
        "ShowC": ["c01.mkv"],
    })
    out = tmp_path / "out.m3u"
    random.seed(7)
    count = build_playlist([tmp_path], out, relative=False, show_order="random")
    assert count == 5
    names = {Path(p).name for p in _read_playlist_paths(out)}
    assert names == {"a01.mkv", "a02.mkv", "b01.mkv", "b02.mkv", "c01.mkv"}


def test_build_playlist_random_show_order_with_group(tmp_path):
    """show_order='random' with a group still produces all episodes with no duplicates."""
    _make_tree(tmp_path, {
        "ShowA": ["a01.mkv", "a02.mkv", "a03.mkv"],
        "ShowB": ["b01.mkv"],
        "ShowC": ["c01.mkv"],
    })
    out = tmp_path / "out.m3u"
    random.seed(3)
    count = build_playlist(
        [tmp_path], out, relative=False,
        show_order="random",
        groups=[["ShowB", "ShowC"]],
    )
    assert count == 5
    names = {Path(p).name for p in _read_playlist_paths(out)}
    assert names == {"a01.mkv", "a02.mkv", "a03.mkv", "b01.mkv", "c01.mkv"}
