#!/usr/bin/env python3
"""
TV Playlist Interleaver
Scans media directories for TV show subdirectories and produces an interleaved M3U playlist.
Run with no arguments to enter the interactive menu.
"""

import argparse
import os
import random
import re
import sys
from itertools import cycle, islice, zip_longest
from pathlib import Path

VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".m4v",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".webm", ".ogv",
}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _natural_key(s: str) -> list:
    parts = re.split(r"(\d+)", s.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def natural_sort_key(path: Path) -> list:
    """Sort key that handles embedded numbers correctly (ep2 before ep10)."""
    return _natural_key(path.name)


def _path_sort_key(f: Path, base: Path) -> list:
    key: list = []
    for part in f.relative_to(base).parts:
        key.extend(_natural_key(part))
    return key


# ---------------------------------------------------------------------------
# Episode collection
# ---------------------------------------------------------------------------

def collect_show_files(show_dir: Path) -> list[Path]:
    """Return sorted video files under show_dir, descending into season subdirectories.

    Files are ordered by each path component naturally, so Season 2 comes
    before Season 10, and episodes within a season stay in broadcast order.
    """
    files = [
        f for f in show_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    ]
    return sorted(files, key=lambda f: _path_sort_key(f, show_dir))


def collect_show_seasons(show_dir: Path) -> list[list[Path]]:
    """Group episodes by immediate season subdirectory.

    Returns a list of episode groups (each group is one season).
    Any video files directly in show_dir form the first group.
    For flat shows (no subdirectories), returns a single group of all episodes.
    """
    direct = sorted(
        [f for f in show_dir.iterdir()
         if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS],
        key=natural_sort_key,
    )
    subdirs = sorted(
        [d for d in show_dir.iterdir() if d.is_dir()],
        key=natural_sort_key,
    )

    seasons: list[list[Path]] = []
    if direct:
        seasons.append(direct)
    for subdir in subdirs:
        eps = sorted(
            [f for f in subdir.rglob("*")
             if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS],
            key=lambda f, b=subdir: _path_sort_key(f, b),
        )
        if eps:
            seasons.append(eps)
    return seasons


# ---------------------------------------------------------------------------
# Interleaving and shuffling
# ---------------------------------------------------------------------------

def interleave(lists: list[list], repeat: bool = False) -> list:
    """
    Round-robin interleave across all lists.

    repeat=False: exhausted lists are skipped; longer lists fill the tail.
      [a1,a2,a3], [b1,b2] → [a1,b1, a2,b2, a3]

    repeat=True: shorter lists cycle back to their first episode.
      [a1,a2,a3], [b1,b2] → [a1,b1, a2,b2, a3,b1]
    """
    if not lists:
        return []
    if repeat:
        max_len = max(len(lst) for lst in lists)
        cycled = [list(islice(cycle(lst), max_len)) for lst in lists]
        return [item for group in zip(*cycled) for item in group]
    result = []
    for group in zip_longest(*lists):
        for item in group:
            if item is not None:
                result.append(item)
    return result


def shuffle_in_blocks(playlist: list[Path], block_size: int) -> list[Path]:
    """Shuffle the playlist in consecutive blocks of block_size episodes."""
    result: list[Path] = []
    for i in range(0, len(playlist), block_size):
        block = list(playlist[i:i + block_size])
        random.shuffle(block)
        result.extend(block)
    return result


def interleave_by_season(
    show_seasons: list[list[list[Path]]], repeat: bool = False
) -> list[Path]:
    """Interleave shows season-by-season.

    All episodes from season N across every show are pooled and shuffled
    together before moving on to season N+1.

    show_seasons: list of shows; each show is a list of season-episode lists.
    """
    if not show_seasons:
        return []
    max_seasons = max(len(s) for s in show_seasons)
    result: list[Path] = []
    for idx in range(max_seasons):
        pool: list[Path] = []
        for seasons in show_seasons:
            if repeat:
                pool.extend(seasons[idx % len(seasons)])
            elif idx < len(seasons):
                pool.extend(seasons[idx])
        random.shuffle(pool)
        result.extend(pool)
    return result


# ---------------------------------------------------------------------------
# Directory scanning
# ---------------------------------------------------------------------------

def _scan_dirs(dirs: list[Path]) -> list[tuple[str, Path]]:
    """Scan each media dir for show subdirectories, returning (label, path) pairs.

    Shows are sorted alphabetically within each source dir. If the same show
    name appears in more than one source dir the second gets a "(2)" suffix, etc.
    """
    raw: list[tuple[str, Path]] = []
    name_counts: dict[str, int] = {}
    for media_dir in dirs:
        for d in sorted(
            [x for x in media_dir.iterdir() if x.is_dir()],
            key=lambda x: x.name.lower(),
        ):
            name_counts[d.name] = name_counts.get(d.name, 0) + 1
            raw.append((d.name, d))

    seen: dict[str, int] = {}
    result: list[tuple[str, Path]] = []
    for name, d in raw:
        if name_counts[name] > 1:
            seen[name] = seen.get(name, 0) + 1
            label = name if seen[name] == 1 else f"{name} ({seen[name]})"
        else:
            label = name
        result.append((label, d))
    return result


# ---------------------------------------------------------------------------
# Playlist builder
# ---------------------------------------------------------------------------

def build_playlist(
    dirs: list[Path],
    output: Path,
    relative: bool,
    repeat: bool = False,
    shuffle_mode: str = "none",
    shuffle_n: int = 10,
) -> int:
    """Scan dirs for shows, interleave/shuffle episodes, write M3U. Returns episode count.

    shuffle_mode: "none" | "episodes" | "seasons"
    shuffle_n:   block size used when shuffle_mode == "episodes"
    """
    if not dirs:
        print("No directories specified.", file=sys.stderr)
        return 0

    show_entries = _scan_dirs(dirs)
    if not show_entries:
        print("No show subdirectories found.", file=sys.stderr)
        return 0

    if shuffle_mode == "seasons":
        named: list[tuple[str, list[list[Path]]]] = []
        for label, d in show_entries:
            seasons = collect_show_seasons(d)
            if seasons:
                named.append((label, seasons))
            else:
                print(f"  Skipping '{label}' — no video files found", file=sys.stderr)

        if not named:
            print("No video files found.", file=sys.stderr)
            return 0

        print(f"Found {len(named)} show(s):")
        for name, seasons in named:
            total = sum(len(s) for s in seasons)
            print(f"  {name}: {total} episode(s) in {len(seasons)} season group(s)")

        playlist = interleave_by_season([s for _, s in named], repeat=repeat)

    else:
        shows: list[tuple[str, list[Path]]] = []
        for label, d in show_entries:
            files = collect_show_files(d)
            if files:
                shows.append((label, files))
            else:
                print(f"  Skipping '{label}' — no video files found", file=sys.stderr)

        if not shows:
            print("No video files found.", file=sys.stderr)
            return 0

        print(f"Found {len(shows)} show(s):")
        for name, files in shows:
            print(f"  {name}: {len(files)} episode(s)")

        playlist = interleave([files for _, files in shows], repeat=repeat)
        if shuffle_mode == "episodes":
            playlist = shuffle_in_blocks(playlist, shuffle_n)

    with output.open("w", encoding="utf-8") as fh:
        fh.write("#EXTM3U\n")
        for ep in playlist:
            fh.write(f"#EXTINF:-1,{ep.stem}\n")
            if relative:
                path_str = os.path.normpath(os.path.relpath(ep, output.parent))
            else:
                path_str = os.path.normpath(ep)
            fh.write(path_str + "\n")

    return len(playlist)


# ---------------------------------------------------------------------------
# Interactive menu
# ---------------------------------------------------------------------------

_SHUFFLE_LABELS = {
    "none":     "none (ordered round-robin)",
    "episodes": "per {n} episodes",
    "seasons":  "per season",
}


def _clear() -> None:
    os.system("clear" if os.name == "posix" else "cls")


def _print_menu(
    dirs: list[Path],
    output: Path | None,
    relative: bool,
    repeat: bool,
    shuffle_mode: str,
    shuffle_n: int,
) -> None:
    _clear()
    print("=" * 54)
    print("         TV Playlist Interleaver")
    print("=" * 54)
    print()
    print("Source directories:")
    if dirs:
        for i, d in enumerate(dirs, 1):
            print(f"  [{i}] {d}")
    else:
        print("  (none — add at least one with [a])")
    print()
    out_str = str(output) if output else "(auto: interleaved.m3u in first source dir)"
    shuffle_str = _SHUFFLE_LABELS[shuffle_mode].format(n=shuffle_n)
    print("Settings:")
    print(f"  Output      : {out_str}")
    print(f"  Path style  : {'relative' if relative else 'absolute'}")
    print(f"  Repeat      : {'on' if repeat else 'off'}")
    print(f"  Shuffle     : {shuffle_str}")
    print()
    print("Commands:")
    print("  [a] Add source directory")
    if dirs:
        print("  [x] Remove source directory")
    print("  [o] Set output file")
    print("  [p] Toggle path style  (absolute / relative)")
    print("  [r] Toggle repeat shorter shows")
    print("  [s] Configure shuffle")
    if dirs:
        print("  [g] Generate playlist")
    print("  [q] Quit")
    print()


def _shuffle_submenu(current_mode: str, current_n: int) -> tuple[str, int]:
    _clear()
    print("─" * 54)
    print("  Shuffle mode")
    print("─" * 54)
    print("  [1] None           ordered round-robin, no randomness")
    print("  [2] Per X episodes shuffle in blocks of X across all shows")
    print("  [3] Per season     pool + shuffle episodes within each season")
    print("  [b] Back           keep current setting")
    print()
    choice = input("Choice: ").strip().lower()
    if choice == "1":
        return "none", current_n
    if choice == "2":
        raw = input(f"Block size (episodes per block) [{current_n}]: ").strip()
        n = int(raw) if raw.isdigit() and int(raw) > 0 else current_n
        return "episodes", n
    if choice == "3":
        return "seasons", current_n
    return current_mode, current_n


def interactive_mode() -> None:
    dirs: list[Path] = []
    output: Path | None = None
    relative = False
    repeat = False
    shuffle_mode = "none"
    shuffle_n = 10

    while True:
        _print_menu(dirs, output, relative, repeat, shuffle_mode, shuffle_n)
        choice = input("Choice: ").strip().lower()

        if choice == "a":
            raw = input("Directory path: ").strip()
            if raw:
                p = Path(raw).expanduser().resolve()
                if p.is_dir():
                    dirs.append(p)
                else:
                    input(f"'{p}' is not a valid directory. Press Enter...")

        elif choice == "x" and dirs:
            if len(dirs) == 1:
                dirs.clear()
            else:
                _clear()
                print("Remove which directory?\n")
                for i, d in enumerate(dirs, 1):
                    print(f"  [{i}] {d}")
                raw = input("\nNumber (Enter to cancel): ").strip()
                if raw.isdigit():
                    idx = int(raw) - 1
                    if 0 <= idx < len(dirs):
                        dirs.pop(idx)

        elif choice == "o":
            raw = input("Output file path (Enter for auto): ").strip()
            output = Path(raw).expanduser().resolve() if raw else None

        elif choice == "p":
            relative = not relative

        elif choice == "r":
            repeat = not repeat

        elif choice == "s":
            shuffle_mode, shuffle_n = _shuffle_submenu(shuffle_mode, shuffle_n)

        elif choice == "g" and dirs:
            out = output or (dirs[0] / "interleaved.m3u")
            print()
            count = build_playlist(dirs, out, relative, repeat, shuffle_mode, shuffle_n)
            if count:
                input(f"\nPlaylist written: {out}  ({count} entries)\nPress Enter...")
            else:
                input("\nNo playlist generated. Press Enter...")

        elif choice == "q":
            sys.exit(0)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) == 1:
        interactive_mode()
        return

    parser = argparse.ArgumentParser(
        description="Interleave TV show episodes from subdirectories into one M3U playlist.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  playlist_gen.py /media/tv
  playlist_gen.py /media/tv1 /media/tv2 -o ~/combined.m3u
  playlist_gen.py /media/tv --shuffle episodes --shuffle-n 5
  playlist_gen.py /media/tv --shuffle seasons
  playlist_gen.py /media/tv --relative --repeat
""",
    )
    parser.add_argument(
        "media_dirs",
        type=Path,
        nargs="+",
        metavar="media_dir",
        help="One or more directories containing TV show subdirectories",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output playlist file (default: <first media_dir>/interleaved.m3u)",
    )
    parser.add_argument(
        "--relative",
        action="store_true",
        help="Write relative paths in the playlist instead of absolute paths",
    )
    parser.add_argument(
        "--repeat",
        action="store_true",
        help=(
            "Cycle shorter shows back to episode 1 instead of leaving gaps. "
            "Playlist length = longest show × number of shows."
        ),
    )
    parser.add_argument(
        "--shuffle",
        choices=["none", "episodes", "seasons"],
        default="none",
        dest="shuffle_mode",
        help=(
            "'episodes': shuffle in blocks of --shuffle-n; "
            "'seasons': pool and shuffle within each season phase."
        ),
    )
    parser.add_argument(
        "--shuffle-n",
        type=int,
        default=10,
        metavar="N",
        help="Block size for --shuffle episodes (default: 10)",
    )

    args = parser.parse_args()

    dirs = [d.resolve() for d in args.media_dirs]
    for d in dirs:
        if not d.is_dir():
            print(f"Error: '{d}' is not a directory.", file=sys.stderr)
            sys.exit(1)

    output = args.output.resolve() if args.output else dirs[0] / "interleaved.m3u"

    count = build_playlist(
        dirs, output, args.relative, args.repeat, args.shuffle_mode, args.shuffle_n
    )
    if count:
        print(f"\nPlaylist written to: {output}  ({count} entries)")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
