# TV Playlist Interleaver

Scans a directory of TV shows and produces a single M3U playlist with episodes interleaved round-robin across all shows.

```
ShowA/  a1 a2 a3 a4 a5 a6 a7 a8 a9
ShowB/  b1 b2 b3 b4 b5 b6 b7

→  a1 b1 a2 b2 a3 b3 a4 b4 a5 b5 a6 b6 a7 b7 a8 a9
```

## Requirements

- Python 3.11+
- No third-party dependencies (built entirely using Python's standard library, including Tkinter)

## Launch Modes

The application automatically dispatches to the correct interface based on your command-line arguments:

1. **GUI Application (Default)**: Run with no arguments to launch the brand-new desktop interface:
   ```bash
   python playlist_gen.py
   ```
2. **One-Shot CLI**: Pass source directories to run directly from the command line:
   ```bash
   python playlist_gen.py <media_dir> [options]
   ```
3. **Interactive Text Menu**: Pass the `--text` flag to run the console-based menu:
   ```bash
   python playlist_gen.py --text
   ```

---

## Desktop GUI Application

The Tkinter-based desktop interface provides an intuitive and robust toolset to configure and generate playlists:

- **Source Directory Manager**: Add or remove multiple source directories via an integrated folder browser. Added folders are scanned immediately.
- **Show Treeview**: Lists all discovered shows with their checkbox select status, names, active groups, season count, and episode count. Double-click or press space to toggle a show's inclusion.
- **Interactive Group Management**: Bundles multiple shows into custom round-robin slots with actions to create, add to, remove from, or dissolve groups.
- **Settings Panel**: Live controls for Path style (absolute vs. relative), Repeating shorter shows, Show order (alphabetical vs. random), Interleave Mode, Block Size, and Output Playlist file path.
- **Asynchronous Generation**: The playlist is built in a background worker thread so the GUI remains highly responsive. Progress and final statistics are shown via status logs and popups.

### Layout State & Persistence

Your configuration is preserved between sessions automatically in `playlist_layouts.json` (saved inside your user config directory, resolving to `$XDG_CONFIG_HOME/playlist_gen/` or `~/.config/playlist_gen/`).

Use the **File Menu** to manage named layouts:
- **New Layout**: Resets the current configuration.
- **Save Layout**: Overwrites the active named layout.
- **Save Layout As...**: Creates a new custom layout name (with duplicate-name overwrite warnings).
- **Load Layout...**: Switches between your saved layouts.
- **Delete Layout...**: Permanently removes a layout definition.

---

## Interactive Text Menu

Run with `python playlist_gen.py --text` to enter the interactive console menu:

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
  Mode        : 1 episode per show

Commands:
  [a] Add source directory
  [x] Remove source directory
  [w] Select shows
  [G] Manage groups
  [o] Set output file
  [p] Toggle path style  (absolute / relative)
  [r] Toggle repeat shorter shows
  [n] Toggle show order  (alphabetical / random)
  [s] Set interleave mode
  [g] Generate playlist
  [q] Quit
```

---

## CLI Arguments

| Argument | Description |
|---|---|
| `--text` | Launch the interactive text menu instead of the GUI |
| `media_dirs` | One or more directories containing TV show subdirectories |
| `-o`, `--output` | Output file path (default: `<first media_dir>/interleaved.m3u`) |
| `--relative` | Write relative paths instead of absolute paths |
| `--repeat` | Cycle shorter shows back to episode 1 instead of leaving gaps |
| `--interleave` | `episodes` or `seasons` (see Interleave modes below) |
| `--block-size N` | Episodes per show per round for `--interleave episodes` (default: 10) |

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

# Watch 5 episodes of each show before switching
python playlist_gen.py /media/tv --interleave episodes --block-size 5

# Watch one full season of each show before switching
python playlist_gen.py /media/tv --interleave seasons
```

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

## Interleave modes

The interleave mode controls how many episodes of each show play before the next show takes its turn. Configured via `--interleave` (CLI), `[s]` (interactive menu), or the Interleave combobox (GUI).

### Default — 1 episode per show

One episode from each show per round, strict round-robin. This is the default and requires no flag.

```
ShowA:  a1 a2 a3 a4 a5
ShowB:  b1 b2 b3

→  a1 b1  a2 b2  a3 b3  a4  a5
```

### Episodes (`--interleave episodes`)

N consecutive episodes of each show (in broadcast order) before switching to the next. The cycle repeats with the next block of N episodes from each show.

```
ShowA:  a1 a2 a3 a4 a5
ShowB:  b1 b2 b3
N = 2 → a1 a2  b1 b2  a3 a4  b3  a5
```

Set N with `--block-size N` (default 10). Episodes always play in broadcast order.

### Seasons (`--interleave seasons`)

One complete season of each show (in broadcast order) before switching to the next show. After all shows have played their current season, the cycle moves to the next season.

```
ShowA: S1=[a01 a02]  S2=[a03]
ShowB: S1=[b01]      S2=[b02 b03]

→  a01 a02 b01  (Season 1 of all shows)
   a03 b02 b03  (Season 2 of all shows)
```

When `--repeat` is on and a show runs out of seasons, its earlier seasons are cycled back in.

---

## Supported formats

`.mkv` `.mp4` `.avi` `.mov` `.wmv` `.flv` `.m4v` `.mpg` `.mpeg` `.ts` `.m2ts` `.webm` `.ogv`

---

## Running tests

To run the unit tests (including persistent layout states and GUI deserialization tests):

```bash
pip install pytest
```

If you are running in a headless Linux environment, use `xvfb-run` to emulate a virtual display for Tkinter:

```bash
xvfb-run python3 -m pytest test_playlist_gen.py -v
```
