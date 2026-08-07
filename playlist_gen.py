#!/usr/bin/env python3
"""
TV Playlist Interleaver
Scans media directories for TV show subdirectories and produces an interleaved M3U playlist.
Includes:
- Standard CLI mode
- Interactive Text Menu (using `--text`)
- Tkinter GUI with robust file management and layout/state persistence (default mode with no arguments)
"""

import argparse
import json
import os
import random
import re
import sys
from itertools import cycle, islice, zip_longest
from pathlib import Path

from __future__ import annotations

# Tkinter imports for GUI
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    tk = None  # type: ignore
    filedialog = messagebox = ttk = None  # type: ignore

VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".m4v",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".webm", ".ogv",
}

LAYOUT_FILE = Path(__file__).parent / "playlist_layouts.json"

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
    try:
        files = [
            f for f in show_dir.rglob("*")
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        ]
    except PermissionError as e:
        print(f"Warning: cannot read '{show_dir}': {e}", file=sys.stderr)
        return []
    return sorted(files, key=lambda f: _path_sort_key(f, show_dir))


def collect_show_seasons(show_dir: Path) -> list[list[Path]]:
    """Group episodes by immediate season subdirectory.

    Returns a list of episode groups (each group is one season).
    Any video files directly in show_dir form the first group.
    For flat shows (no subdirectories), returns a single group of all episodes.
    """
    try:
        direct = sorted(
            [f for f in show_dir.iterdir()
             if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS],
            key=natural_sort_key,
        )
        subdirs = sorted(
            [d for d in show_dir.iterdir() if d.is_dir()],
            key=natural_sort_key,
        )
    except PermissionError as e:
        print(f"Warning: cannot read '{show_dir}': {e}", file=sys.stderr)
        return []

    seasons: list[list[Path]] = []
    if direct:
        seasons.append(direct)
    for subdir in subdirs:
        try:
            eps = sorted(
                [f for f in subdir.rglob("*")
                 if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS],
                key=lambda f, b=subdir: _path_sort_key(f, b),
            )
        except PermissionError as e:
            print(f"Warning: cannot read '{subdir}': {e}", file=sys.stderr)
            continue
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


def interleave_in_blocks(lists: list[list], block_size: int, repeat: bool = False) -> list:
    """Interleave shows in consecutive blocks of block_size episodes, keeping episode order.

    Each round gives block_size consecutive episodes from each show in turn.
    Episodes always play in their natural order — no randomisation.

      [a1,a2,a3,a4,a5], [b1,b2,b3], block_size=2
      → a1 a2  b1 b2  a3 a4  b3  a5
    """
    if not lists:
        return []
    if repeat:
        max_len = max(len(lst) for lst in lists)
        cycled = [list(islice(cycle(lst), max_len)) for lst in lists]
        result = []
        for i in range(0, max_len, block_size):
            for lst in cycled:
                result.extend(lst[i:i + block_size])
        return result
    max_len = max(len(lst) for lst in lists)
    result = []
    for i in range(0, max_len, block_size):
        for lst in lists:
            block = lst[i:i + block_size]
            if block:
                result.extend(block)
    return result


def interleave_by_season(
    show_seasons: list[list[list[Path]]], repeat: bool = False
) -> list[Path]:
    """Interleave shows season-by-season in broadcast order.

    For each season round, all episodes of each show's current season are appended
    in show order (no pooling, no randomisation), then the next season round begins.

    show_seasons: list of shows; each show is a list of season-episode lists.
    """
    if not show_seasons:
        return []
    max_seasons = max(len(s) for s in show_seasons)
    result: list[Path] = []
    for idx in range(max_seasons):
        for seasons in show_seasons:
            if repeat:
                result.extend(seasons[idx % len(seasons)])
            elif idx < len(seasons):
                result.extend(seasons[idx])
    return result


# ---------------------------------------------------------------------------
# Directory scanning
# ---------------------------------------------------------------------------

# (label, show_path, num_seasons, num_episodes)
ShowInfo = tuple[str, Path, int, int]


def _scan_dirs(dirs: list[Path]) -> list[tuple[str, Path]]:
    """Scan each media dir for show subdirectories, returning (label, path) pairs.

    Shows are sorted alphabetically within each source dir. If the same show
    name appears in more than one source dir the second gets a "(2)" suffix, etc.
    """
    raw: list[tuple[str, Path]] = []
    name_counts: dict[str, int] = {}
    for media_dir in dirs:
        try:
            entries = sorted(
                [x for x in media_dir.iterdir() if x.is_dir()],
                key=lambda x: x.name.lower(),
            )
        except OSError as e:
            print(f"Warning: cannot read '{media_dir}': {e}", file=sys.stderr)
            continue
        for d in entries:
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


def _refresh_shows(dirs: list[Path]) -> list[ShowInfo]:
    """Scan dirs and return (label, path, n_seasons, n_episodes) for every show that has video files."""
    result: list[ShowInfo] = []
    for label, d in _scan_dirs(dirs):
        seasons = collect_show_seasons(d)
        n_eps = sum(len(s) for s in seasons)
        if n_eps > 0:
            result.append((label, d, len(seasons), n_eps))
    return result


# ---------------------------------------------------------------------------
# Playlist builder
# ---------------------------------------------------------------------------

def _collect_group_episodes(group_labels: list[str], label_to_path: dict[str, Path]) -> list[Path]:
    """Concatenate episodes from grouped shows sequentially."""
    result: list[Path] = []
    for label in group_labels:
        if label in label_to_path:
            result.extend(collect_show_files(label_to_path[label]))
    return result


def _collect_group_seasons(group_labels: list[str], label_to_path: dict[str, Path]) -> list[list[Path]]:
    """Concatenate all season groups from grouped shows sequentially."""
    result: list[list[Path]] = []
    for label in group_labels:
        if label in label_to_path:
            result.extend(collect_show_seasons(label_to_path[label]))
    return result


def build_playlist(
    dirs: list[Path],
    output: Path,
    relative: bool,
    repeat: bool = False,
    interleave_mode: str = "none",
    block_size: int = 10,
    include: set[str] | None = None,
    groups: list[list[str]] | None = None,
    show_order: str = "alpha",
) -> int:
    """Scan dirs for shows, interleave episodes, write M3U. Returns episode count.

    interleave_mode: "none" (1 ep/show) | "episodes" (N eps/show) | "seasons" (1 season/show)
    block_size:      episodes per show per round when interleave_mode == "episodes"
    include:         when set, only shows whose label is in this set are used
    groups:          each element is an ordered list of show labels to treat as one round-robin slot
    show_order:      "alpha" (default) | "random" — controls slot order and within-group order
    """
    if not dirs:
        print("No directories specified.", file=sys.stderr)
        return 0

    show_entries = _scan_dirs(dirs)
    if include is not None:
        show_entries = [(label, d) for label, d in show_entries if label in include]

    if not show_entries:
        print("No show subdirectories found.", file=sys.stderr)
        return 0

    if show_order == "random":
        show_entries = list(show_entries)
        random.shuffle(show_entries)

    effective_groups = groups or []
    label_to_path = {label: d for label, d in show_entries}

    # Map each label → index of its group (first occurrence wins)
    label_to_group: dict[str, int] = {}
    for g_idx, g in enumerate(effective_groups):
        for lbl in g:
            if lbl in label_to_path and lbl not in label_to_group:
                label_to_group[lbl] = g_idx

    # Walk show_entries in scan order; insert each group at its first member's position
    placed_groups: set[int] = set()
    flat_slots: list[tuple[str, list[Path]]] = []
    season_slots: list[tuple[str, list[list[Path]]]] = []

    for label, d in show_entries:
        if label in label_to_group:
            g_idx = label_to_group[label]
            if g_idx not in placed_groups:
                placed_groups.add(g_idx)
                g_labels = effective_groups[g_idx]
                if show_order == "random":
                    g_labels = list(g_labels)
                    random.shuffle(g_labels)
                g_name = f"Group {g_idx + 1} ({', '.join(effective_groups[g_idx])})"
                if interleave_mode == "seasons":
                    g_seasons = _collect_group_seasons(g_labels, label_to_path)
                    if g_seasons:
                        season_slots.append((g_name, g_seasons))
                    else:
                        print(f"  Skipping '{g_name}' — no video files found", file=sys.stderr)
                else:
                    g_eps = _collect_group_episodes(g_labels, label_to_path)
                    if g_eps:
                        flat_slots.append((g_name, g_eps))
                    else:
                        print(f"  Skipping '{g_name}' — no video files found", file=sys.stderr)
        else:
            if interleave_mode == "seasons":
                seasons = collect_show_seasons(d)
                if seasons:
                    season_slots.append((label, seasons))
                else:
                    print(f"  Skipping '{label}' — no video files found", file=sys.stderr)
            else:
                eps = collect_show_files(d)
                if eps:
                    flat_slots.append((label, eps))
                else:
                    print(f"  Skipping '{label}' — no video files found", file=sys.stderr)

    if interleave_mode == "seasons":
        if not season_slots:
            print("No video files found.", file=sys.stderr)
            return 0
        print(f"Found {len(season_slots)} slot(s):")
        for name, seasons in season_slots:
            total = sum(len(s) for s in seasons)
            print(f"  {name}: {total} episode(s) in {len(seasons)} season group(s)")
        playlist = interleave_by_season([s for _, s in season_slots], repeat=repeat)
    else:
        if not flat_slots:
            print("No video files found.", file=sys.stderr)
            return 0
        print(f"Found {len(flat_slots)} slot(s):")
        for name, files in flat_slots:
            print(f"  {name}: {len(files)} episode(s)")
        if interleave_mode == "episodes":
            playlist = interleave_in_blocks([files for _, files in flat_slots], block_size, repeat=repeat)
        else:
            playlist = interleave([files for _, files in flat_slots], repeat=repeat)

    try:
        with output.open("w", encoding="utf-8") as fh:
            fh.write("#EXTM3U\n")
            for ep in playlist:
                fh.write(f"#EXTINF:-1,{ep.stem}\n")
                if relative:
                    path_str = os.path.normpath(os.path.relpath(ep, output.parent))
                else:
                    path_str = os.path.normpath(ep)
                fh.write(path_str + "\n")
    except OSError as e:
        print(f"Error writing playlist: {e}", file=sys.stderr)
        return 0

    return len(playlist)


# ---------------------------------------------------------------------------
# Interactive text menu
# ---------------------------------------------------------------------------

_MODE_LABELS = {
    "none":     "1 episode per show",
    "episodes": "{n} episodes per show",
    "seasons":  "1 season per show",
}


def _clear() -> None:
    os.system("clear" if os.name == "posix" else "cls")


def _print_menu(
    dirs: list[Path],
    output: Path | None,
    relative: bool,
    repeat: bool,
    interleave_mode: str,
    block_size: int,
    show_info: list[ShowInfo],
    selected: set[str],
    groups: list[list[str]],
    show_order: str,
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
    mode_str = _MODE_LABELS[interleave_mode].format(n=block_size)
    n_total = len(show_info)
    n_sel = sum(1 for label, *_ in show_info if label in selected)
    if n_total:
        shows_str = f"{n_total} found, {n_sel} selected"
    elif dirs:
        shows_str = "scanning..."
    else:
        shows_str = "none"
    n_groups = len(groups)
    groups_str = f"{n_groups} defined" if n_groups else "none"

    order_str = "alphabetical" if show_order == "alpha" else "random"

    print("Settings:")
    print(f"  Shows       : {shows_str}")
    print(f"  Groups      : {groups_str}")
    print(f"  Output      : {out_str}")
    print(f"  Path style  : {'relative' if relative else 'absolute'}")
    print(f"  Repeat      : {'on' if repeat else 'off'}")
    print(f"  Show order  : {order_str}")
    print(f"  Mode        : {mode_str}")
    print()
    print("Commands:")
    print("  [a] Add source directory")
    if dirs:
        print("  [x] Remove source directory")
    if show_info:
        print("  [w] Select shows")
        print("  [G] Manage groups")
    print("  [o] Set output file")
    print("  [p] Toggle path style  (absolute / relative)")
    print("  [r] Toggle repeat shorter shows")
    print("  [n] Toggle show order  (alphabetical / random)")
    print("  [s] Set interleave mode")
    if dirs and selected:
        print("  [g] Generate playlist")
    print("  [q] Quit")
    print()


def _mode_submenu(current_mode: str, current_n: int) -> tuple[str, int]:
    _clear()
    print("─" * 54)
    print("  Interleave mode")
    print("─" * 54)
    print("  [1] Default (1 ep)  1 episode per show, round-robin")
    print("  [2] Block (N eps)   N consecutive episodes per show before switching")
    print("  [3] Season          1 full season per show before switching")
    print("  [b] Back            keep current setting")
    print()
    choice = input("Choice: ").strip().lower()
    if choice == "1":
        return "none", current_n
    if choice == "2":
        raw = input(f"Episodes per show per round [{current_n}]: ").strip()
        n = int(raw) if raw.isdigit() and int(raw) > 0 else current_n
        return "episodes", n
    if choice == "3":
        return "seasons", current_n
    return current_mode, current_n


def _selection_screen(
    show_info: list[ShowInfo],
    selected: set[str],
) -> set[str]:
    selected = set(selected)
    max_name = max((len(label) for label, *_ in show_info), default=10)

    while True:
        _clear()
        n_total = len(show_info)
        n_sel = sum(1 for label, *_ in show_info if label in selected)
        print("─" * 54)
        print(f"  Show Selection  ({n_sel}/{n_total} selected)")
        print("─" * 54)
        print()
        for i, (label, _, n_seasons, n_eps) in enumerate(show_info, 1):
            mark = "✓" if label in selected else " "
            s_str = f"{n_seasons} season{'s' if n_seasons != 1 else ' '}"
            e_str = f"{n_eps} ep{'s' if n_eps != 1 else ' '}"
            print(f"  [{mark}] {i:>2}. {label:<{max_name}}  {s_str:>10}  {e_str:>7}")
        print()
        print("  Enter number(s) to toggle (e.g. 3  or  1 4 7),")
        print("  [a] select all,  [n] select none,  [b] back")
        print()
        raw = input("  > ").strip().lower()

        if raw == "b":
            return selected
        elif raw == "a":
            selected = {label for label, *_ in show_info}
        elif raw == "n":
            selected = set()
        else:
            for token in raw.replace(",", " ").split():
                if token.isdigit():
                    idx = int(token) - 1
                    if 0 <= idx < len(show_info):
                        label = show_info[idx][0]
                        if label in selected:
                            selected.discard(label)
                        else:
                            selected.add(label)


def _groups_screen(
    show_info: list[ShowInfo],
    selected: set[str],
    groups: list[list[str]],
) -> list[list[str]]:
    """Full-screen group management. Returns updated groups list.

    Only selected shows are listed. Commands:
      g <n> [n]...  create new group from listed show numbers
      a <g#> <n>    append show n to existing group g#
      r <n>         remove show n from its group
      d <g#>        delete group g#
      b             back
    """
    groups = [list(g) for g in groups]  # shallow copy so caller's list isn't mutated live

    while True:
        visible = [(label, path, ns, ne) for label, path, ns, ne in show_info if label in selected]
        if not visible:
            input("No shows selected. Press Enter...")
            return groups

        # Build label → group index map for display
        label_to_g: dict[str, int] = {}
        for g_idx, g in enumerate(groups):
            for lbl in g:
                if lbl not in label_to_g:
                    label_to_g[lbl] = g_idx

        max_name = max((len(label) for label, *_ in visible), default=10)
        n_groups = len(groups)

        _clear()
        print("─" * 54)
        g_word = f"{n_groups} group{'s' if n_groups != 1 else ''}" if n_groups else "no groups"
        print(f"  Show Groups  ({g_word})")
        print("─" * 54)
        print()
        for i, (label, _, n_seasons, n_eps) in enumerate(visible, 1):
            if label in label_to_g:
                tag = f"G{label_to_g[label] + 1}"
            else:
                tag = "●"
            s_str = f"{n_seasons} season{'s' if n_seasons != 1 else ' '}"
            e_str = f"{n_eps} ep{'s' if n_eps != 1 else ' '}"
            print(f"  {tag:<3} {i:>2}. {label:<{max_name}}  {s_str:>10}  {e_str:>7}")
        print()
        print("  g <num> [num]...  create new group from listed shows")
        print("  a <group#> <num>  add show to existing group")
        print("  r <num>           remove show from its group")
        print("  d <group#>        delete entire group")
        print("  [b]               back")
        print()
        raw = input("  > ").strip()
        tokens = raw.split()
        if not tokens:
            continue

        cmd = tokens[0].lower()

        if cmd == "b":
            return groups

        elif cmd == "g" and len(tokens) >= 2:
            new_group: list[str] = []
            for tok in tokens[1:]:
                if tok.isdigit():
                    idx = int(tok) - 1
                    if 0 <= idx < len(visible):
                        label = visible[idx][0]
                        if label not in new_group:
                            new_group.append(label)
            if new_group:
                # Remove these labels from any existing group first
                groups = [
                    [lbl for lbl in g if lbl not in new_group]
                    for g in groups
                ]
                groups = [g for g in groups if g]
                groups.append(new_group)

        elif cmd == "a" and len(tokens) == 3:
            g_tok, n_tok = tokens[1], tokens[2]
            if g_tok.isdigit() and n_tok.isdigit():
                g_idx = int(g_tok) - 1
                show_idx = int(n_tok) - 1
                if 0 <= g_idx < len(groups) and 0 <= show_idx < len(visible):
                    label = visible[show_idx][0]
                    # Remove from any current group
                    groups = [
                        [lbl for lbl in g if lbl != label]
                        for g in groups
                    ]
                    groups = [g for g in groups if g]
                    # Re-find target group index (list may have shifted after cleanup)
                    if g_idx < len(groups):
                        groups[g_idx].append(label)
                    else:
                        groups.append([label])

        elif cmd == "r" and len(tokens) == 2:
            if tokens[1].isdigit():
                show_idx = int(tokens[1]) - 1
                if 0 <= show_idx < len(visible):
                    label = visible[show_idx][0]
                    groups = [
                        [lbl for lbl in g if lbl != label]
                        for g in groups
                    ]
                    groups = [g for g in groups if g]

        elif cmd == "d" and len(tokens) == 2:
            if tokens[1].isdigit():
                g_idx = int(tokens[1]) - 1
                if 0 <= g_idx < len(groups):
                    groups.pop(g_idx)


def interactive_mode() -> None:
    dirs: list[Path] = []
    output: Path | None = None
    relative = False
    repeat = False
    interleave_mode = "none"
    block_size = 10
    show_order = "alpha"
    show_info: list[ShowInfo] = []
    selected: set[str] = set()
    groups: list[list[str]] = []

    def rescan() -> None:
        nonlocal show_info, selected, groups
        old_labels = {label for label, *_ in show_info}
        show_info = _refresh_shows(dirs)
        new_labels = {label for label, *_ in show_info}
        # Preserve existing selections; auto-select shows that are newly discovered
        selected = (selected & new_labels) | (new_labels - old_labels)
        # Remove stale labels from groups; drop empty groups
        groups = [
            [lbl for lbl in g if lbl in new_labels]
            for g in groups
        ]
        groups = [g for g in groups if g]

    while True:
        _print_menu(dirs, output, relative, repeat, interleave_mode, block_size, show_info, selected, groups, show_order)
        raw_choice = input("Choice: ").strip()
        choice = raw_choice.lower()

        if choice == "a":
            raw = input("Directory path: ").strip()
            if raw:
                p = Path(raw).expanduser().resolve()
                if p.is_dir():
                    dirs.append(p)
                    print("Scanning...", end="\r", flush=True)
                    rescan()
                else:
                    input(f"'{p}' is not a valid directory. Press Enter...")

        elif choice == "x" and dirs:
            if len(dirs) == 1:
                dirs.clear()
                show_info = []
                selected = set()
                groups = []
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
                        print("Scanning...", end="\r", flush=True)
                        rescan()

        elif choice == "w" and show_info:
            selected = _selection_screen(show_info, selected)

        elif raw_choice == "G" and show_info:
            groups = _groups_screen(show_info, selected, groups)

        elif choice == "o":
            raw = input("Output file path (Enter for auto): ").strip()
            output = Path(raw).expanduser().resolve() if raw else None

        elif choice == "p":
            relative = not relative

        elif choice == "r":
            repeat = not repeat

        elif choice == "n":
            show_order = "random" if show_order == "alpha" else "alpha"

        elif choice == "s":
            interleave_mode, block_size = _mode_submenu(interleave_mode, block_size)

        elif choice == "g" and dirs and selected:
            out = output or (dirs[0] / "interleaved.m3u")
            include = {label for label, *_ in show_info if label in selected}
            print()
            try:
                count = build_playlist(
                    dirs, out, relative, repeat, interleave_mode, block_size,
                    include=include, groups=groups, show_order=show_order,
                )
            except Exception as e:
                input(f"\nError generating playlist: {e}\nPress Enter...")
                continue
            if count:
                input(f"\nPlaylist written: {out}  ({count} entries)\nPress Enter...")
            else:
                input("\nNo playlist generated. Press Enter...")

        elif choice == "q":
            sys.exit(0)


# ---------------------------------------------------------------------------
# State Management & Persistence (JSON Store)
# ---------------------------------------------------------------------------

class LayoutStore:
    def __init__(self, filename: Path = LAYOUT_FILE):
        self.filename = filename
        self.layouts: dict[str, dict] = {}
        self.active_layout_name: str | None = None
        self.load_all()

    def load_all(self):
        if self.filename.exists():
            try:
                with self.filename.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.layouts = data.get("layouts", {})
                    self.active_layout_name = data.get("active_layout_name", None)
            except Exception as e:
                print(f"Warning: Failed to load layouts from {self.filename}: {e}", file=sys.stderr)
                self.layouts = {}
                self.active_layout_name = None
        else:
            self.layouts = {}
            self.active_layout_name = None

    def save_all(self):
        try:
            with self.filename.open("w", encoding="utf-8") as f:
                json.dump({
                    "layouts": self.layouts,
                    "active_layout_name": self.active_layout_name
                }, f, indent=2)
        except Exception as e:
            print(f"Error: Failed to save layouts to {self.filename}: {e}", file=sys.stderr)

    def get_layout(self, name: str) -> dict | None:
        return self.layouts.get(name, None)

    def save_layout(self, name: str, state: dict):
        self.layouts[name] = state
        self.active_layout_name = name
        self.save_all()

    def delete_layout(self, name: str):
        if name in self.layouts:
            del self.layouts[name]
            if self.active_layout_name == name:
                self.active_layout_name = list(self.layouts.keys())[0] if self.layouts else None
            self.save_all()

    def get_active_state(self) -> dict | None:
        if self.active_layout_name and self.active_layout_name in self.layouts:
            return self.layouts[self.active_layout_name]
        return None


# ---------------------------------------------------------------------------
# Tkinter GUI Application
# ---------------------------------------------------------------------------

class InterleaverGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("TV Playlist Interleaver")
        self.root.geometry("950x700")
        self.root.minsize(850, 600)

        # Initialize layout state variables
        self.dirs: list[Path] = []
        self.show_info: list[ShowInfo] = []
        self.selected: set[str] = set()
        self.groups: list[list[str]] = []

        # Settings
        self.output_path_var = tk.StringVar(value="")
        self.relative_var = tk.BooleanVar(value=False)
        self.repeat_var = tk.BooleanVar(value=False)
        self.show_order_var = tk.StringVar(value="alpha")
        self.interleave_mode_var = tk.StringVar(value="none")
        self.block_size_var = tk.StringVar(value="10")

        self.store = LayoutStore()

        # UI setup
        self._create_menu()
        self._create_widgets()

        # Load previously active layout
        self.load_active_layout_state()

    def get_current_state_dict(self) -> dict:
        return {
            "dirs": [str(d) for d in self.dirs],
            "selected": list(self.selected),
            "groups": self.groups,
            "output_path": self.output_path_var.get(),
            "relative": self.relative_var.get(),
            "repeat": self.repeat_var.get(),
            "show_order": self.show_order_var.get(),
            "interleave_mode": self.interleave_mode_var.get(),
            "block_size": self.block_size_var.get(),
        }

    def apply_state_dict(self, state: dict):
        self.dirs = [Path(d) for d in state.get("dirs", [])]
        self._refresh_dirs_listbox()

        # Scan shows based on directories
        self.rescan_shows()

        # Restore selections & groups
        all_show_labels = {lbl for lbl, *_ in self.show_info}
        self.selected = {lbl for lbl in state.get("selected", []) if lbl in all_show_labels}

        raw_groups = state.get("groups", [])
        self.groups = []
        for g in raw_groups:
            filtered_g = [lbl for lbl in g if lbl in all_show_labels]
            if filtered_g:
                self.groups.append(filtered_g)

        self.output_path_var.set(state.get("output_path", ""))
        self.relative_var.set(state.get("relative", False))
        self.repeat_var.set(state.get("repeat", False))
        self.show_order_var.set(state.get("show_order", "alpha"))
        self.interleave_mode_var.set(state.get("interleave_mode", "none"))
        self.block_size_var.set(state.get("block_size", "10"))

        self._update_block_size_entry_state()
        self._refresh_shows_treeview()

    def load_active_layout_state(self):
        state = self.store.get_active_state()
        if state:
            self.apply_state_dict(state)
            self._update_window_title()
        else:
            self._update_window_title()

    def _update_window_title(self):
        layout_name = self.store.active_layout_name or "Unsaved Layout"
        self.root.title(f"TV Playlist Interleaver — [{layout_name}]")

    def _create_menu(self):
        menubar = tk.Menu(self.root)

        # File Menu
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="New Layout", command=self.new_layout)
        filemenu.add_command(label="Save Layout", command=self.save_layout)
        filemenu.add_command(label="Save Layout As...", command=self.save_layout_as)
        filemenu.add_command(label="Load Layout...", command=self.load_layout)
        filemenu.add_command(label="Delete Layout...", command=self.delete_layout)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=filemenu)

        self.root.config(menu=menubar)

    def _create_widgets(self):
        # Create Main paned window or grid layout
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Left Column: Directories & Settings
        left_col = ttk.Frame(main_frame, width=320)
        left_col.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        # Right Column: Shows & Group Management
        right_col = ttk.Frame(main_frame)
        right_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # --- LEFT COLUMN COMPONENTS ---

        # 1. Directory Manager
        dir_frame = ttk.LabelFrame(left_col, text="Media Source Directories", padding=5)
        dir_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.dir_listbox = tk.Listbox(dir_frame, height=5, selectmode=tk.SINGLE)
        self.dir_listbox.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        dir_btn_frame = ttk.Frame(dir_frame)
        dir_btn_frame.pack(fill=tk.X)

        add_dir_btn = ttk.Button(dir_btn_frame, text="Add Directory...", command=self.add_directory)
        add_dir_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        rem_dir_btn = ttk.Button(dir_btn_frame, text="Remove", command=self.remove_directory)
        rem_dir_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        # 2. Settings Panel
        settings_frame = ttk.LabelFrame(left_col, text="Playlist Settings", padding=10)
        settings_frame.pack(fill=tk.X, pady=(0, 10))

        # Interleave Mode
        ttk.Label(settings_frame, text="Interleave Mode:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.mode_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.interleave_mode_var,
            values=["none", "episodes", "seasons"],
            state="readonly"
        )
        self.mode_combo.grid(row=0, column=1, sticky=tk.EW, pady=5)
        self.mode_combo.bind("<<ComboboxSelected>>", lambda e: self._update_block_size_entry_state())

        # Block Size (only enabled if mode is episodes)
        ttk.Label(settings_frame, text="Block Size (N):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.block_size_entry = ttk.Entry(settings_frame, textvariable=self.block_size_var, width=10)
        self.block_size_entry.grid(row=1, column=1, sticky=tk.W, pady=5)

        # Show Order
        ttk.Label(settings_frame, text="Show Order:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.order_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.show_order_var,
            values=["alpha", "random"],
            state="readonly"
        )
        self.order_combo.grid(row=2, column=1, sticky=tk.EW, pady=5)

        # Path Style Checkbox
        rel_chk = ttk.Checkbutton(settings_frame, text="Write Relative Paths", variable=self.relative_var)
        rel_chk.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=5)

        # Repeat Checkbox
        rep_chk = ttk.Checkbutton(settings_frame, text="Repeat Shorter Shows", variable=self.repeat_var)
        rep_chk.grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=5)

        # Output File Path
        ttk.Label(settings_frame, text="Output Playlist:").grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=(10, 2))

        out_path_frame = ttk.Frame(settings_frame)
        out_path_frame.grid(row=6, column=0, columnspan=2, sticky=tk.EW)

        out_entry = ttk.Entry(out_path_frame, textvariable=self.output_path_var)
        out_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        browse_out_btn = ttk.Button(out_path_frame, text="...", width=3, command=self.browse_output_path)
        browse_out_btn.pack(side=tk.RIGHT)

        # --- RIGHT COLUMN COMPONENTS ---

        # 1. Shows treeview
        shows_frame = ttk.LabelFrame(right_col, text="TV Shows Discovered", padding=5)
        shows_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Scrollbar + Treeview
        tree_scroll = ttk.Scrollbar(shows_frame)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.shows_tree = ttk.Treeview(
            shows_frame,
            columns=("selected", "name", "group", "seasons", "episodes"),
            show="headings",
            yscrollcommand=tree_scroll.set,
            selectmode="extended"
        )
        self.shows_tree.pack(fill=tk.BOTH, expand=True)
        tree_scroll.config(command=self.shows_tree.yview)

        self.shows_tree.heading("selected", text="Use?", anchor=tk.CENTER)
        self.shows_tree.heading("name", text="Show Name", anchor=tk.W)
        self.shows_tree.heading("group", text="Group", anchor=tk.CENTER)
        self.shows_tree.heading("seasons", text="Seasons", anchor=tk.CENTER)
        self.shows_tree.heading("episodes", text="Episodes", anchor=tk.CENTER)

        self.shows_tree.column("selected", width=50, stretch=False, anchor=tk.CENTER)
        self.shows_tree.column("name", width=250, minwidth=150, stretch=True, anchor=tk.W)
        self.shows_tree.column("group", width=120, stretch=True, anchor=tk.CENTER)
        self.shows_tree.column("seasons", width=70, stretch=False, anchor=tk.CENTER)
        self.shows_tree.column("episodes", width=70, stretch=False, anchor=tk.CENTER)

        # Bind spacebar / double click to toggle use/selected status of a show
        self.shows_tree.bind("<space>", lambda e: self.toggle_show_selected())
        self.shows_tree.bind("<Double-1>", lambda e: self.toggle_show_selected())

        # 2. Group Management Toolbar
        grp_frame = ttk.LabelFrame(right_col, text="Group Management", padding=5)
        grp_frame.pack(fill=tk.X, pady=(0, 10))

        grp_btn_frame = ttk.Frame(grp_frame)
        grp_btn_frame.pack(fill=tk.X, expand=True)

        create_grp_btn = ttk.Button(grp_btn_frame, text="Create Group from Selected", command=self.create_group_from_selected)
        create_grp_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        add_grp_btn = ttk.Button(grp_btn_frame, text="Add Selected to Group...", command=self.add_selected_to_group)
        add_grp_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        rem_grp_btn = ttk.Button(grp_btn_frame, text="Remove Selected from Group", command=self.remove_selected_from_group)
        rem_grp_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        dissolve_grp_btn = ttk.Button(grp_btn_frame, text="Dissolve Group...", command=self.dissolve_group)
        dissolve_grp_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        # Footer Actions
        footer_frame = ttk.Frame(main_frame)
        footer_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=5)

        self.status_label = ttk.Label(footer_frame, text="Ready", font=("TkDefaultFont", 10, "italic"))
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        generate_btn = ttk.Button(footer_frame, text="Generate Playlist", style="Accent.TButton", command=self.generate_playlist)
        generate_btn.pack(side=tk.RIGHT, padx=5, ipady=5)

    def _update_block_size_entry_state(self):
        if self.interleave_mode_var.get() == "episodes":
            self.block_size_entry.config(state="normal")
        else:
            self.block_size_entry.config(state="disabled")

    def _refresh_dirs_listbox(self):
        self.dir_listbox.delete(0, tk.END)
        for d in self.dirs:
            self.dir_listbox.insert(tk.END, str(d))

    def _refresh_shows_treeview(self):
        # Save active focus/selection names if possible
        selected_items = self.shows_tree.selection()
        selected_names = [
            vals[1]
            for item in selected_items
            if (vals := self.shows_tree.item(item, "values")) and len(vals) > 1
        ]

        # Clear
        for item in self.shows_tree.get_children():
            self.shows_tree.delete(item)

        label_to_group: dict[str, int] = {}
        for g_idx, g in enumerate(self.groups):
            for lbl in g:
                label_to_group[lbl] = g_idx

        # Populating treeview
        for label, path, n_seasons, n_eps in self.show_info:
            is_sel = "[✓]" if label in self.selected else "[ ]"
            group_text = ""
            if label in label_to_group:
                group_text = f"Group {label_to_group[label] + 1}"

            node_id = self.shows_tree.insert(
                "",
                tk.END,
                values=(is_sel, label, group_text, str(n_seasons), str(n_eps))
            )
            if label in selected_names:
                self.shows_tree.selection_add(node_id)

    # --- Directory Operations ---

    def add_directory(self):
        chosen = filedialog.askdirectory(title="Select Media Source Directory")
        if chosen:
            p = Path(chosen).resolve()
            if p not in self.dirs:
                self.dirs.append(p)
                self._refresh_dirs_listbox()
                self.rescan_shows()
                self.set_status(f"Added directory: {p}")
            else:
                messagebox.showinfo("Directory exists", f"Directory is already added:\n{p}")

    def remove_directory(self):
        sel = self.dir_listbox.curselection()
        if sel:
            idx = sel[0]
            removed = self.dirs.pop(idx)
            self._refresh_dirs_listbox()
            self.rescan_shows()
            self.set_status(f"Removed directory: {removed}")
        else:
            messagebox.showwarning("Selection Required", "Please select a directory to remove.")

    def rescan_shows(self):
        old_labels = {lbl for lbl, *_ in self.show_info}
        self.show_info = _refresh_shows(self.dirs)
        new_labels = {lbl for lbl, *_ in self.show_info}

        # Preserve selection only for currently discovered shows, auto-select newly discovered shows
        self.selected = (self.selected & new_labels) | (new_labels - old_labels)

        # Strip deleted shows from groups
        cleaned_groups = []
        for g in self.groups:
            filtered = [lbl for lbl in g if lbl in new_labels]
            if filtered:
                cleaned_groups.append(filtered)
        self.groups = cleaned_groups

        self._refresh_shows_treeview()

    # --- Show Treeview Actions ---

    def toggle_show_selected(self):
        for item in self.shows_tree.selection():
            vals = self.shows_tree.item(item, "values")
            if not vals:
                continue
            label = vals[1]
            if label in self.selected:
                self.selected.discard(label)
            else:
                self.selected.add(label)
        self._refresh_shows_treeview()

    # --- Group Operations ---

    def get_selected_show_labels(self) -> list[str]:
        labels = []
        for item in self.shows_tree.selection():
            vals = self.shows_tree.item(item, "values")
            if vals:
                labels.append(vals[1])
        return labels

    def create_group_from_selected(self):
        labels = self.get_selected_show_labels()
        # Verify selected shows are part of 'selected' for playlist use
        for lbl in labels:
            if lbl not in self.selected:
                messagebox.showwarning(
                    "Show not in Use",
                    f"Show '{lbl}' must be checked ('Use?') before grouping."
                )
                return

        if len(labels) < 2:
            messagebox.showwarning("Selection Required", "Please select 2 or more shows to create a group.")
            return

        # Remove from any existing group
        self.groups = [[lbl for lbl in g if lbl not in labels] for g in self.groups]
        self.groups = [g for g in self.groups if g]

        self.groups.append(labels)
        self._refresh_shows_treeview()
        self.set_status(f"Created group with {len(labels)} shows.")

    def add_selected_to_group(self):
        labels = self.get_selected_show_labels()
        if not labels:
            messagebox.showwarning("Selection Required", "Please select one or more shows to add to a group.")
            return

        for lbl in labels:
            if lbl not in self.selected:
                messagebox.showwarning(
                    "Show not in Use",
                    f"Show '{lbl}' must be checked ('Use?') before grouping."
                )
                return

        if not self.groups:
            messagebox.showinfo("No Groups", "There are no existing groups. Please use 'Create Group' first.")
            return

        # Let user select from a dialog list of groups
        group_sel_win = tk.Toplevel(self.root)
        group_sel_win.title("Select Target Group")
        group_sel_win.geometry("300x200")
        group_sel_win.transient(self.root)
        group_sel_win.grab_set()

        ttk.Label(group_sel_win, text="Select existing group:").pack(pady=5)

        group_choices = [f"Group {i+1} ({', '.join(g[:3])}...)" for i, g in enumerate(self.groups)]
        combo = ttk.Combobox(group_sel_win, values=group_choices, state="readonly")
        combo.pack(pady=10, fill=tk.X, padx=10)
        combo.current(0)

        def confirm():
            g_idx = combo.current()
            if g_idx >= 0:
                # Remove from previous groups
                self.groups = [[lbl for lbl in g if lbl not in labels] for g in self.groups]
                self.groups = [g for g in self.groups if g]

                # Append
                if g_idx < len(self.groups):
                    for lbl in labels:
                        if lbl not in self.groups[g_idx]:
                            self.groups[g_idx].append(lbl)
                else:
                    self.groups.append(labels)

                self._refresh_shows_treeview()
                self.set_status(f"Added {len(labels)} shows to Group {g_idx + 1}.")
            group_sel_win.destroy()

        ttk.Button(group_sel_win, text="Add to Group", command=confirm).pack(pady=10)

    def remove_selected_from_group(self):
        labels = self.get_selected_show_labels()
        if not labels:
            messagebox.showwarning("Selection Required", "Please select one or more shows to remove from their groups.")
            return

        self.groups = [[lbl for lbl in g if lbl not in labels] for g in self.groups]
        self.groups = [g for g in self.groups if g]
        self._refresh_shows_treeview()
        self.set_status("Removed selected shows from their groups.")

    def dissolve_group(self):
        if not self.groups:
            messagebox.showinfo("No Groups", "No groups are currently defined.")
            return

        group_sel_win = tk.Toplevel(self.root)
        group_sel_win.title("Dissolve Group")
        group_sel_win.geometry("300x200")
        group_sel_win.transient(self.root)
        group_sel_win.grab_set()

        ttk.Label(group_sel_win, text="Select group to dissolve:").pack(pady=5)

        group_choices = [f"Group {i+1} ({', '.join(g[:3])}...)" for i, g in enumerate(self.groups)]
        combo = ttk.Combobox(group_sel_win, values=group_choices, state="readonly")
        combo.pack(pady=10, fill=tk.X, padx=10)
        combo.current(0)

        def confirm():
            g_idx = combo.current()
            if g_idx >= 0 and g_idx < len(self.groups):
                self.groups.pop(g_idx)
                self._refresh_shows_treeview()
                self.set_status(f"Dissolved Group {g_idx + 1}.")
            group_sel_win.destroy()

        ttk.Button(group_sel_win, text="Dissolve", command=confirm).pack(pady=10)

    # --- Output Path Picker ---

    def browse_output_path(self):
        chosen = filedialog.asksaveasfilename(
            title="Save M3U Playlist As",
            defaultextension=".m3u",
            filetypes=[("M3U Playlist", "*.m3u"), ("All Files", "*.*")]
        )
        if chosen:
            self.output_path_var.set(chosen)

    # --- Playlist Generation ---

    def generate_playlist(self):
        if not self.dirs:
            messagebox.showerror("Error", "Please add at least one media directory first.")
            return

        if not self.selected:
            messagebox.showerror("Error", "Please select/check ('Use?') at least one show.")
            return

        out_str = self.output_path_var.get().strip()
        if out_str:
            output = Path(out_str).expanduser().resolve()
        else:
            output = self.dirs[0] / "interleaved.m3u"

        # Validate block size if in episodes mode
        block_size = 10
        if self.interleave_mode_var.get() == "episodes":
            raw_bs = self.block_size_var.get().strip()
            if not raw_bs.isdigit() or int(raw_bs) <= 0:
                messagebox.showerror("Error", "Block Size must be a positive integer.")
                return
            block_size = int(raw_bs)

        include = {lbl for lbl, *_ in self.show_info if lbl in self.selected}

        try:
            self.set_status("Generating playlist...")
            self.root.update_idletasks()
            count = build_playlist(
                dirs=self.dirs,
                output=output,
                relative=self.relative_var.get(),
                repeat=self.repeat_var.get(),
                interleave_mode=self.interleave_mode_var.get(),
                block_size=block_size,
                include=include,
                groups=self.groups,
                show_order=self.show_order_var.get(),
            )
        except Exception as e:
            messagebox.showerror("Generation Error", f"An error occurred during playlist generation:\n{e}")
            self.set_status("Generation failed.")
            return

        if count > 0:
            messagebox.showinfo("Success", f"Playlist generated successfully!\nPath: {output}\nEntries: {count}")
            self.set_status(f"Generated {count} entries into: {output.name}")
        else:
            messagebox.showwarning("No Playlist Generated", "No video files were found matching your parameters.")
            self.set_status("No playlist generated.")

    # --- Layout State Operations ---

    def new_layout(self):
        # Reset everything
        self.dirs = []
        self.show_info = []
        self.selected = set()
        self.groups = []
        self.output_path_var.set("")
        self.relative_var.set(False)
        self.repeat_var.set(False)
        self.show_order_var.set("alpha")
        self.interleave_mode_var.set("none")
        self.block_size_var.set("10")

        self.store.active_layout_name = None
        self._refresh_dirs_listbox()
        self._refresh_shows_treeview()
        self._update_block_size_entry_state()
        self._update_window_title()
        self.set_status("Created new layout.")

    def save_layout(self):
        name = self.store.active_layout_name
        if name:
            self.store.save_layout(name, self.get_current_state_dict())
            self.set_status(f"Saved layout: {name}")
        else:
            self.save_layout_as()

    def save_layout_as(self):
        # Prompt for name
        save_win = tk.Toplevel(self.root)
        save_win.title("Save Layout As")
        save_win.geometry("300x120")
        save_win.transient(self.root)
        save_win.grab_set()

        ttk.Label(save_win, text="Enter Layout Name:").pack(pady=5)
        name_entry = ttk.Entry(save_win)
        name_entry.pack(fill=tk.X, padx=10, pady=5)
        name_entry.focus_set()

        # Prefill current name if it exists
        if self.store.active_layout_name:
            name_entry.insert(0, self.store.active_layout_name)

        def confirm():
            name = name_entry.get().strip()
            if name:
                self.store.save_layout(name, self.get_current_state_dict())
                self._update_window_title()
                self.set_status(f"Saved layout: {name}")
                save_win.destroy()
            else:
                messagebox.showwarning("Name Required", "Please enter a valid layout name.")

        ttk.Button(save_win, text="Save", command=confirm).pack(pady=5)

    def load_layout(self):
        if not self.store.layouts:
            messagebox.showinfo("No Saved Layouts", "There are no saved layouts to load.")
            return

        load_win = tk.Toplevel(self.root)
        load_win.title("Load Layout")
        load_win.geometry("300x200")
        load_win.transient(self.root)
        load_win.grab_set()

        ttk.Label(load_win, text="Select Layout:").pack(pady=5)
        choices = list(self.store.layouts.keys())
        combo = ttk.Combobox(load_win, values=choices, state="readonly")
        combo.pack(fill=tk.X, padx=10, pady=10)

        # Select active in combo if applicable
        if self.store.active_layout_name in choices:
            combo.current(choices.index(self.store.active_layout_name))
        else:
            combo.current(0)

        def confirm():
            name = combo.get()
            state = self.store.get_layout(name)
            if state:
                self.store.active_layout_name = name
                self.store.save_all()
                self.apply_state_dict(state)
                self._update_window_title()
                self.set_status(f"Loaded layout: {name}")
            load_win.destroy()

        ttk.Button(load_win, text="Load", command=confirm).pack(pady=10)

    def delete_layout(self):
        if not self.store.layouts:
            messagebox.showinfo("No Saved Layouts", "There are no layouts to delete.")
            return

        del_win = tk.Toplevel(self.root)
        del_win.title("Delete Layout")
        del_win.geometry("300x200")
        del_win.transient(self.root)
        del_win.grab_set()

        ttk.Label(del_win, text="Select Layout to Delete:").pack(pady=5)
        choices = list(self.store.layouts.keys())
        combo = ttk.Combobox(del_win, values=choices, state="readonly")
        combo.pack(fill=tk.X, padx=10, pady=10)
        combo.current(0)

        def confirm():
            name = combo.get()
            if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete layout: '{name}'?"):
                self.store.delete_layout(name)
                self.set_status(f"Deleted layout: {name}")
                if self.store.active_layout_name:
                    active_state = self.store.get_active_state()
                    if active_state:
                        self.apply_state_dict(active_state)
                    else:
                        self.new_layout()
                else:
                    self.new_layout()
            del_win.destroy()

        ttk.Button(del_win, text="Delete", command=confirm).pack(pady=10)

    # --- Help Status bar helper ---

    def set_status(self, text: str):
        self.status_label.config(text=text)


def launch_gui():
    if not tk:
        print("Error: Tkinter is not installed or available on this system. Cannot launch GUI.", file=sys.stderr)
        sys.exit(1)

    root = tk.Tk()
    app = InterleaverGUI(root)
    root.mainloop()


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def _positive_int(value: str) -> int:
    """argparse type that rejects non-positive integers."""
    n = int(value)
    if n <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {n}")
    return n


def main() -> None:
    # 1. Check for command line arguments
    # No arguments -> GUI
    # If '--text' is present -> launch Text Menu
    # If media directories are given -> CLI Mode as before

    if len(sys.argv) == 1:
        launch_gui()
        return

    # Check for '--text' parameter specifically
    if "--text" in sys.argv:
        # Run text interactive mode
        interactive_mode()
        return

    parser = argparse.ArgumentParser(
        description="Interleave TV show episodes from subdirectories into one M3U playlist.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  playlist_gen.py /media/tv
  playlist_gen.py /media/tv1 /media/tv2 -o ~/combined.m3u
  playlist_gen.py /media/tv --interleave episodes --block-size 5
  playlist_gen.py /media/tv --interleave seasons
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
        "--interleave",
        choices=["none", "episodes", "seasons"],
        default="none",
        dest="interleave_mode",
        help=(
            "'episodes': N consecutive episodes per show (set N with --block-size); "
            "'seasons': one full season per show before switching."
        ),
    )
    parser.add_argument(
        "--block-size",
        type=_positive_int,
        default=None,
        metavar="N",
        help="Episodes per show per round for --interleave episodes (default: 10)",
    )

    args = parser.parse_args()

    dirs = [d.resolve() for d in args.media_dirs]
    for d in dirs:
        if not d.is_dir():
            print(f"Error: '{d}' is not a directory.", file=sys.stderr)
            sys.exit(1)

    if args.block_size is not None and args.interleave_mode != "episodes":
        print(
            f"Warning: --block-size has no effect when --interleave is '{args.interleave_mode}'.",
            file=sys.stderr,
        )
    block_size = args.block_size if args.block_size is not None else 10

    output = args.output.resolve() if args.output else dirs[0] / "interleaved.m3u"

    count = build_playlist(
        dirs, output, args.relative, args.repeat, args.interleave_mode, block_size
    )
    if count:
        print(f"\nPlaylist written to: {output}  ({count} entries)")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
