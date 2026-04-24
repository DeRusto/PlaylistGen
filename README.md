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

```
python playlist_gen.py <media_dir> [options]
```

### Arguments

| Argument | Description |
|---|---|
| `media_dir` | Directory containing TV show subdirectories |
| `-o`, `--output` | Output file path (default: `<media_dir>/interleaved.m3u`) |
| `--relative` | Write relative paths instead of absolute paths |
| `--repeat` | Cycle shorter shows back to episode 1 instead of leaving gaps |

### Examples

```bash
# Basic — writes interleaved.m3u into the media directory
python playlist_gen.py /media/tv

# Custom output path
python playlist_gen.py /media/tv -o ~/watchlist.m3u

# Relative paths (useful when the playlist lives alongside the media)
python playlist_gen.py /media/tv --relative

# Repeat shorter shows so every slot is filled
python playlist_gen.py /media/tv --repeat
```

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

## Interleave modes

### Default

When shows have different episode counts, the shorter show's slots are left empty and the longer show continues alone at the tail.

```
ShowA (4 eps):  a1 a2 a3 a4
ShowB (2 eps):  b1 b2

→  a1 b1  a2 b2  a3  a4
```

### `--repeat`

Shorter shows cycle back to episode 1, keeping every slot filled. Playlist length = longest show × number of shows.

```
ShowA (4 eps):  a1 a2 a3 a4
ShowB (2 eps):  b1 b2

→  a1 b1  a2 b2  a3 b1  a4 b2
```

## Supported formats

`.mkv` `.mp4` `.avi` `.mov` `.wmv` `.flv` `.m4v` `.mpg` `.mpeg` `.ts` `.m2ts` `.webm` `.ogv`

## Running tests

```bash
pip install pytest
python -m pytest test_playlist_gen.py -v
```
