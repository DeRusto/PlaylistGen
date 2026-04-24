#!/usr/bin/env python3
"""
TV Playlist Interleaver
Scans a media directory for TV show subdirectories and produces an interleaved M3U playlist.
"""

import argparse
import os
import re
import sys
from itertools import cycle, islice, zip_longest
from pathlib import Path

VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".m4v",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".webm", ".ogv",
}


def natural_sort_key(path: Path) -> list:
    """Sort key that handles embedded numbers correctly (ep2 before ep10)."""
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def collect_show_files(show_dir: Path) -> list[Path]:
    """Return sorted list of video files directly inside show_dir."""
    files = [
        f for f in show_dir.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    ]
    return sorted(files, key=natural_sort_key)


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


def build_playlist(media_dir: Path, output: Path, relative: bool, repeat: bool = False) -> int:
    """Scan media_dir, interleave episodes, write M3U. Returns episode count."""
    show_dirs = sorted(
        [d for d in media_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name.lower(),
    )

    if not show_dirs:
        print(f"No subdirectories found in {media_dir}", file=sys.stderr)
        return 0

    shows: list[tuple[str, list[Path]]] = []
    for d in show_dirs:
        files = collect_show_files(d)
        if files:
            shows.append((d.name, files))
        else:
            print(f"  Skipping '{d.name}' — no video files found", file=sys.stderr)

    if not shows:
        print("No video files found in any subdirectory.", file=sys.stderr)
        return 0

    print(f"Found {len(shows)} show(s):")
    for name, files in shows:
        print(f"  {name}: {len(files)} episode(s)")

    playlist = interleave([files for _, files in shows], repeat=repeat)

    with output.open("w", encoding="utf-8") as fh:
        fh.write("#EXTM3U\n")
        for ep in playlist:
            fh.write(f"#EXTINF:-1,{ep.stem}\n")
            path_str = (
                os.path.relpath(ep, output.parent) if relative else str(ep.resolve())
            )
            fh.write(path_str + "\n")

    return len(playlist)


def main():
    parser = argparse.ArgumentParser(
        description="Interleave TV show episodes from subdirectories into one M3U playlist.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  playlist_gen.py /media/tv
  playlist_gen.py /media/tv -o ~/interleaved.m3u
  playlist_gen.py /media/tv --relative
  playlist_gen.py /media/tv --repeat
""",
    )
    parser.add_argument(
        "media_dir",
        type=Path,
        help="Directory containing TV show subdirectories",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output playlist file (default: <media_dir>/interleaved.m3u)",
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
            "The playlist length equals (number of shows) × (longest show's episode count)."
        ),
    )

    args = parser.parse_args()

    media_dir: Path = args.media_dir.resolve()
    if not media_dir.is_dir():
        print(f"Error: '{media_dir}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    output: Path = args.output.resolve() if args.output else media_dir / "interleaved.m3u"

    count = build_playlist(media_dir, output, args.relative, args.repeat)
    if count:
        print(f"\nPlaylist written to: {output}  ({count} entries)")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
