# TV Playlist Interleaver

Scans a directory of TV shows and produces a single M3U playlist with episodes interleaved round-robin across all shows.

```
ShowA/  a1 a2 a3 a4 a5 a6 a7 a8 a9
ShowB/  b1 b2 b3 b4 b5 b6 b7

→  a1 b1 a2 b2 a3 b3 a4 b4 a5 b5 a6 b6 a7 b7 a8 a9
```

## Requirements

- Python 3.11+
- No third-party dependencies

## Usage

Run with no arguments to launch the interactive menu:

```bash
python playlist_gen.py
```

Or pass arguments directly for a one-shot CLI run:

```bash
python playlist_gen.py <media_dir> [options]
```

### CLI Arguments

| Argument | Description |
|---|---|
| `media_dir` | One or more directories containing TV show subdirectories |
| `-o`, `--output` | Output file path (default: `<first media_dir>/interleaved.m3u`) |
| `--relative` | Write relative paths instead of absolute paths |
| `--repeat` | Cycle shorter shows back to episode 1 instead of leaving gaps |
| `--shuffle` | `episodes` or `seasons` (see Shuffle modes below) |
| `--shuffle-n N` | Block size for `--shuffle episodes` (default: 10) |

### CLI Examples

```bash
# Basic — writes interleaved.m3u into the media directory
python playlist_gen.py /media/tv

# Multiple source directories
python playlist_gen.py /media/tv1 /media/tv2 -o ~/combined.m3u

# Relative paths (useful when the playlist lives alongside the media)
python playlist_gen.py /media/tv --relative

# Repeat shorter shows so every slot is filled
python playlist_gen.py /media/tv --repeat

# Shuffle in blocks of 5 episodes
python playlist_gen.py /media/tv --shuffle episodes --shuffle-n 5

# Pool and shuffle within each season
python playlist_gen.py /media/tv --shuffle seasons
```

---

## Interactive Menu

Run with no arguments to enter the interactive menu. All features are available here, including show selection, groups, and show-order randomization.

```
======================================================
         TV Playlist Interleaver
======================================================

Source directories:
  [1] /media/tv

Settings:
  Shows       : 6 found, 6 selected
  Groups      : 1 defined
  Output      : (auto: interleaved.m3u in first source dir)
  Path style  : absolute
  Repeat      : off
  Show order  : alphabetical
  Shuffle     : none (ordered round-robin)

Commands:
  [a] Add source directory
  [x] Remove source directory
  [w] Select shows
  [G] Manage groups
  [o] Set output file
  [p] Toggle path style  (absolute / relative)
  [r] Toggle repeat shorter shows
  [n] Toggle show order  (alphabetical / random)
  [s] Configure shuffle
  [g] Generate playlist
  [q] Quit
```

### Main menu commands

| Key | Action |
|---|---|
| `a` | Add a source directory (scanned immediately) |
| `x` | Remove a source directory |
| `w` | Open the show selection screen |
| `G` | Open the group management screen |
| `o` | Set a custom output file path |
| `p` | Toggle between absolute and relative paths |
| `r` | Toggle repeat mode (cycle shorter shows) |
| `n` | Toggle show order (alphabetical / random) |
| `s` | Configure shuffle mode |
| `g` | Generate the playlist |
| `q` | Quit |

### Show selection (`w`)

Lists every show found across all source directories with its season and episode counts. Enter show numbers to toggle them in or out of the playlist. Multiple numbers can be entered at once separated by spaces or commas.

```
  [✓]  1. Breaking Bad        5 seasons  62 eps
  [ ]  2. Firefly             1 season   14 eps
  [✓]  3. Game of Thrones     8 seasons  73 eps
```

| Command | Action |
|---|---|
| `1 3 5` | Toggle shows 1, 3, and 5 |
| `a` | Select all shows |
| `n` | Deselect all shows |
| `b` | Back to main menu |

### Group management (`G`)

Groups bundle multiple shows into a single round-robin slot. The grouped shows play sequentially inside that slot (all of show B, then all of show C), so their combined episode count competes against longer shows without excessive repetition.

**Example:** Game of Thrones (73 eps) vs a group of [Firefly (14 eps) + Freaks and Geeks (18 eps)] = 32 combined episodes. Instead of repeating the short shows 5× each, they form one slot and play straight through.

```
  ●   1. Breaking Bad      5 seasons  62 eps
  G1  2. Firefly           1 season   14 eps
  G1  3. Freaks and Geeks  1 season   18 eps
  ●   4. Game of Thrones   8 seasons  73 eps
  G2  5. Mr. Robot         1 season   10 eps
```

| Command | Action |
|---|---|
| `g 2 3` | Create a new group from shows 2 and 3 |
| `g 2 3 5` | Create a new group from shows 2, 3, and 5 |
| `a 1 5` | Add show 5 to existing Group 1 |
| `r 2` | Remove show 2 from its group (back to solo) |
| `d 1` | Delete Group 1 entirely (all its shows return to solo) |
| `b` | Back to main menu |

Multiple groups are supported (Group 1, Group 2, …). A show can only belong to one group at a time.

### Show order (`n`)

Toggles between:

- **Alphabetical** (default) — shows and groups always appear in the same round-robin positions, determined by their names.
- **Random** — at each generate, the round-robin slot positions are reshuffled. When groups are defined, the playback order of shows within each group is also reshuffled.

---

## Directory structure

Both flat and season-based show layouts are supported and can be mixed freely.

**Flat** — episodes directly in the show folder:
```
/media/tv/
  Seinfeld/
    s01e01.mkv
    s01e02.mkv
  Frasier/
    s01e01.mkv
    s01e02.mkv
    s01e03.mkv
```

**Season subdirectories:**
```
/media/tv/
  Seinfeld/
    Season 1/
      s01e01.mkv
      s01e02.mkv
    Season 2/
      s02e01.mkv
  Frasier/
    s01e01.mkv
    s01e02.mkv
```

Episodes are sorted naturally within each season (`ep9` before `ep10`), and seasons are sorted naturally (`Season 2` before `Season 10`). Show directories with no video files are skipped with a warning.

---

## Interleave modes

### Default

When shows have different episode counts, the shorter show's slots are left empty and the longer show continues alone at the tail.

```
ShowA (4 eps):  a1 a2 a3 a4
ShowB (2 eps):  b1 b2

→  a1 b1  a2 b2  a3  a4
```

### `--repeat` / Repeat toggle

Shorter shows cycle back to episode 1, keeping every slot filled. Playlist length = longest show × number of shows.

```
ShowA (4 eps):  a1 a2 a3 a4
ShowB (2 eps):  b1 b2

→  a1 b1  a2 b2  a3 b1  a4 b2
```

---

## Shuffle modes

Configured via `--shuffle` (CLI) or `[s]` (interactive menu).

### None (default)

Episodes play in broadcast order, interleaved round-robin.

### Episodes (`--shuffle episodes`)

The interleaved playlist is shuffled in consecutive blocks of N episodes (default N = 10, set with `--shuffle-n`). Episodes within each block are randomised; blocks stay in order so you broadly progress through the shows.

### Seasons (`--shuffle seasons`)

Episodes from the same season across all shows are pooled and shuffled together before moving to the next season. Seasons are processed in order (Season 1 of all shows, then Season 2, etc.).

When `--repeat` is on and a show runs out of seasons, its earlier seasons are cycled back in.

---

## Supported formats

`.mkv` `.mp4` `.avi` `.mov` `.wmv` `.flv` `.m4v` `.mpg` `.mpeg` `.ts` `.m2ts` `.webm` `.ogv`

---

## Running tests

```bash
pip install pytest
python -m pytest test_playlist_gen.py -v
```
