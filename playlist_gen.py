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
        except PermissionError as e:
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
# Interactive menu
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
                    # Re-parse g_idx after cleanup is complex; just append to the group
                    # identified before cleanup if it still exists
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
# CLI
# ---------------------------------------------------------------------------

def _positive_int(value: str) -> int:
    """argparse type that rejects non-positive integers."""
    n = int(value)
    if n <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {n}")
    return n


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
