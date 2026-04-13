# CineVault — File Reference

This folder contains all files for a local media library web app built to catalog and browse the video collection stored on the **FreeAgent GoFlex Drive (E:)**.

---

## How the Project Came Together

1. **Scanned E: drive for duplicates** → produced the two CSV reports
2. **Verified which Seagate Backup files were safe to delete** → produced the Seagate CSV pair
3. **Built a local web app** (Flask + HTML) to browse and play videos → `media_library.py` + launcher `.bat`
4. **Scanned the drive** to build the video catalog → `media_cache.json`
5. **Exported movies to a spreadsheet** → `movies.csv`
6. **Enriched all videos with real metadata** (ratings, genres, descriptions, cast) → `media_metadata.json`
7. **Added TMDB cover art** for movies and TV series → `covers/` folder + `fetch_covers.py`
8. **Added multi-genre tagging** for every video → `media_extra_cats.json`
9. **Made various content corrections** (removed bad files, fixed mislabeled series, consolidated Pinky and the Brain seasons, merged VeggieTales Songs, moved DuckTales to Movies, fixed The Bible episodes)

---

## To Run the App

1. Make sure the **FreeAgent GoFlex Drive (E:)** is connected
2. Double-click **`Start Media Library.bat`**
3. The browser opens automatically to `http://localhost:5000`

*Python 3 must be installed with "Add Python to PATH" checked.*

> **Note:** The app kills any stale server process on port 5000 automatically at launch, so you don't need to manually stop it before restarting.

---

## File-by-File Reference

---

### `media_library.py`
**Type:** Python script (Flask web application)  
**Size:** ~100 KB / ~1,700 lines  
**Purpose:** The main program. Run this (via the .bat file) to launch the media library browser.

Serves a local website at `http://localhost:5000` with a dark-themed Netflix-style interface. Full feature list:

**Browsing & Filtering**
- **Top filter bar** — All · Movies · TV Shows · Family · Favorites · G · PG · PG-13 · R · NR
- **Genre filter bar** — 20 genres: Action, Adventure, Animation, Comedy, Crime, Documentary, Drama, Family, Fantasy, Holiday, Horror, Musical, Mystery, Romance, Sci-Fi, Thriller, Faith, Fitness, Kids, Favorites
- **Search** — covers title, series, genre, description, director, and cast
- **Sort options** — A→Z, Z→A, Year (Newest/Oldest), Largest File, Rating (High→Low), Most Recently Added, Genre
- Movies display as individual cards; TV shows collapse into one card per series

**Playback**
- Click any card to open the detail modal
- Big play button launches the file in **Windows Media Player** at full screen (guaranteed via a PowerShell post-launch hook that sends Alt+Enter after WMP finishes restoring its saved window state)

**Cover Art**
- Poster images display on cards and as a blurred backdrop in the detail modal
- **Wrong Cover** button (in movie modal) — removes an incorrect poster with a confirmation dialog
- **Change Cover** button (in movie modal and TV series panel) — opens a file picker to upload any image as the new cover; saved locally to `covers/`
- Run `fetch_covers.py` from the command line to auto-fetch missing covers from TMDB

**Genres**
- Every video has one or more genre tags (705 of 825 videos have 2+)
- **Genre editor in movie modal** — click any genre chip to add or remove it; saved instantly
- **Genre editor in TV series panel** — same chip editor applies genres to all episodes of the series at once

**Kid Mode**
- **Kid Mode button** (top-right nav) — turns on a parental filter showing only kid-friendly content; tap again to exit (requires PIN **0000**)
- When Kid Mode is active: Wrong Cover, Change Cover, and genre editor are hidden; the filter bar and genre row are locked
- **Family filter** (top bar) — shows kid-friendly content without the PIN lock or content restriction of full Kid Mode

**Favorites**
- ⭐ star button on every card — tap to add/remove from Favorites without opening the modal
- On series cards, the star marks/unmarks all episodes at once
- Favorites filter in the top bar shows only starred content

**Data Management**
- Automatically kills any stale server on port 5000 before binding
- All genre/favorites overrides persist in `media_extra_cats.json`
- All poster references persist in `media_metadata.json` (movies) or `series_posters.json` (TV series)

**Depends on:** `media_cache.json` (required), `media_metadata.json` (enriched metadata), `media_extra_cats.json` (genre/favorites tags), `series_posters.json` (series poster paths), `covers/` (poster images), `media_tags.json` (kid-friendly overrides)

---

### `Start Media Library.bat`
**Type:** Windows batch file (launcher)  
**Purpose:** Double-click this to start the media library — no terminal required.

Runs `pythonw.exe media_library.py` (no console window), then opens the browser automatically. **This is the file you double-click every time.**

---

### `Start Media Library-old.bat`
**Type:** Windows batch file (older version)  
**Purpose:** Earlier version kept for reference. The current `.bat` supersedes it.

---

### `fetch_covers.py`
**Type:** Python script (standalone utility)  
**Purpose:** Fetches movie and TV series poster images from The Movie Database (TMDB) and saves them locally to the `covers/` folder. Updates `media_metadata.json` with the local file path.

**Usage (run from the command line):**
```
python fetch_covers.py 50              # fetch up to 50 missing movie covers
python fetch_covers.py 50 --no-kids   # skip kids content
python fetch_covers.py 50 --kids-only # only kids content
python fetch_covers.py --series       # fetch one poster per TV series
```

**Requires:** `config.json` with a TMDB API read access token.

---

### `config.json`
**Type:** JSON configuration file  
**Purpose:** Stores the TMDB API bearer token used by `fetch_covers.py` to authenticate with The Movie Database API.

```json
{ "tmdb_bearer_token": "eyJ..." }
```

> ⚠️ **Keep this file private.** It is listed in `.gitignore` and should never be committed to version control or shared.

---

### `media_cache.json`
**Type:** JSON data file  
**Purpose:** The master video catalog — a snapshot of every video file found on the E: drive.

Contains **825 video entries**, each with:
- `path` — full Windows file path (e.g., `E:\Movies\Batman Begins (2005).avi`)
- `title` — cleaned, human-readable display title
- `filename` — original filename
- `category` — Movies / TV Shows / Music
- `series` — series name for episodic content (TV shows, workout programs, etc.)
- `size_mb` — file size
- `kid_friendly` — true/false flag (auto-detected from folder, overridable per video)
- `streamable` — whether the format can be streamed in a browser
- `ext` — file extension

**Current breakdown:**
- Movies (standalone): 371
- TV Show episodes: 448
- Music: 6

**Distinct TV series:** 11 (Bugs Bunny, Pinky and the Brain, Veggietales, Planet Earth, How It's Made, Americas Test Kitchen, The Bible, Baby Einstein, P90X, Storage Wars, Dave Ramsey FPU)

**Important:** File paths inside all start with `E:\`. If the drive letter changes, a re-scan will update this file. Do this by hitting the app's API at `http://localhost:5000/api/scan` or running `python media_library.py` with a scan flag.

---

### `media_metadata.json`
**Type:** JSON data file (~408 KB)  
**Purpose:** Enriched metadata for all 825 videos — ratings, genres, descriptions, director, cast, year, runtime, and local poster image paths.

Each entry is **keyed by the exact file path** and contains:
- `rating` — MPAA rating (G, PG, PG-13, R, NR)
- `genre` — TMDB genre string (e.g., `"Animation / Comedy / Family"`)
- `runtime_min` — runtime in minutes
- `year` — release year
- `director` — director name(s)
- `description` — plot summary
- `cast` — list of notable cast members
- `display_title` — human-readable title override (used when the filename title is wrong)
- `poster_local` — relative path to the local cover image (e.g., `covers/Batman_Begins.jpg`)
- `series` / `episode_title` — for TV show episodes

**343 of 825 videos** have a `poster_local` cover image.

> **Note:** File paths used as keys must match `media_cache.json` exactly. Both reflect E: drive paths.

---

### `media_extra_cats.json`
**Type:** JSON data file (~99 KB)  
**Purpose:** Stores genre tags for every video in the library. This is the source of truth for the genre chips shown in the app.

Keyed by file path, each value is a list of genre tags from the 20-genre system:
```json
"E:\\Movies\\Batman Begins (2005).avi": ["Action", "Crime", "Drama", "Thriller"]
```

**All 825 videos** have at least one genre. **705 videos** have two or more.

When you add or remove a genre chip in the app's movie modal or TV series genre editor, the change is written immediately to this file. Genres auto-assigned by `auto_genres()` during the bulk assignment session are stored here as the baseline, and any manual edits through the UI override them.

---

### `series_posters.json`
**Type:** JSON data file  
**Purpose:** Maps TV series names to their local cover image path. Used so all episodes of a series share one poster without storing a path on every individual episode entry.

```json
{
  "Veggietales": "covers/Veggietales.jpg",
  "Planet Earth": "covers/Planet_Earth.jpg",
  ...
}
```

**8 series** currently have posters: Americas Test Kitchen, Animaniac Appearences, Bugs Bunny, How It's Made, Planet Earth, The Bible, Veggietales, Storage Wars.

When you use the **Change Cover** button in the TV series panel, this file is updated.

---

### `covers/`
**Type:** Folder of JPEG images  
**Purpose:** Local copies of poster/cover art for movies and TV series. Referenced by paths stored in `media_metadata.json` and `series_posters.json`.

**345 images** currently in the folder. Served by the Flask app at `/covers/<filename>` so the browser can display them. Images are fetched from TMDB via `fetch_covers.py` or uploaded manually through the **Change Cover** button in the app.

> Listed in `.gitignore` — not committed to version control (too large, regenerable).

---

### `media_tags.json`
**Type:** JSON data file  
**Purpose:** Stores per-video `kid_friendly` overrides set manually through the toggle in the video detail modal. Only videos where you've manually overridden the auto-detected kid-friendly flag appear here.

---

### `.gitignore`
**Type:** Git configuration  
**Purpose:** Tells Git which files not to track. Currently excludes:
- `config.json` (TMDB token — keep private)
- `covers/` (large regenerable images)
- `media_cache.json`, `media_tags.json`, `series_posters.json` (runtime data)
- `__pycache__/`, `*.pyc` (Python bytecode)

---

### `bugs_bunny_episodes.csv`
**Type:** CSV spreadsheet  
**Purpose:** Detailed per-episode reference for all **80 Bugs Bunny cartoon shorts** from the Cedar DVD collection. Each row contains collection number, title, year, series, director, rating, genre, runtime, guest characters, description, notable facts, and file path.

**Filename tag key:** `[Ef]` = Elmer Fudd · `[Ys]` = Yosemite Sam · `[Dd]` = Daffy Duck · `[Mm]` = Marvin the Martian · `[Td]` = Tasmanian Devil · `[Wc]` = Wile E. Coyote · `[r&m]` = Rocky & Mugsy · `[Wh]` = Witch Hazel · `[Ct]` = Cecil Turtle

---

### `movies.csv`
**Type:** CSV spreadsheet  
**Purpose:** A plain-text export of the movie portion of the library — useful for viewing in Excel without running the app.

> **Note:** This was exported from an older version of the scan. Some entries that now correctly show as TV Shows may still appear here as Movies. Use the app for current categorization.

---

### `EDrive_Duplicates_Report.csv`
**Type:** CSV report (~6.4 MB)  
**Purpose:** Full duplicate file report for the entire E: drive. ~25,400 rows identifying groups of files sharing the same name and size. Columns: GroupKey, CopyNumber, TotalCopies, WastedSpaceMB, FileName, Extension, SizeMB, FullPath, Directory, LastModified.

**How to use:** Filter `TotalCopies > 1`, sort by `WastedSpaceGB` descending.

---

### `SeagateBackup_SAFE_TO_DELETE.csv`
**Type:** CSV report (~3.7 MB)  
**Purpose:** ~11,400 files inside `E:\Personal bckup 1\Seagate Backup\` that already have a copy elsewhere on the drive. Theoretically safe to delete. The `CopyExistsAt` column shows where the duplicate lives.

**Total size of safe-to-delete files: ~20.77 GB**

---

### `SeagateBackup_UNIQUE_FILES.csv`
**Type:** CSV report (~3.6 MB)  
**Purpose:** ~13,700 files inside `E:\Personal bckup 1\Seagate Backup\` with **no copy anywhere else** on the drive. Do **not** delete these without intentionally discarding them.

**Total size of unique files: ~47.94 GB**

> ⚠️ **Review this file carefully before any Seagate Backup cleanup.**

---

## Quick Summary Table

| File / Folder | Type | Size / Entries | Keep? | Notes |
|---|---|---|---|---|
| `media_library.py` | Python app | ~100 KB / ~1,700 lines | ✅ Core | Run this to use the library |
| `Start Media Library.bat` | Launcher | — | ✅ Core | Double-click to start |
| `Start Media Library-old.bat` | Launcher (old) | — | 🗑️ Optional | Superseded |
| `fetch_covers.py` | Python utility | ~9 KB | ✅ Core | Fetches TMDB cover art |
| `config.json` | Config | — | ✅ Private | TMDB API token — do not share |
| `media_cache.json` | JSON catalog | 825 videos | ✅ Core | Regenerated by scanning |
| `media_metadata.json` | JSON metadata | 825 entries | ✅ Core | Ratings, descriptions, cast, poster paths |
| `media_extra_cats.json` | JSON genres | 825 entries | ✅ Core | Genre tags, Favorites — edited via UI |
| `series_posters.json` | JSON poster map | 8 series | ✅ Core | TV series poster references |
| `covers/` | Image folder | 345 JPEGs | ✅ Core | Local cover art (regenerable from TMDB) |
| `media_tags.json` | JSON overrides | Small | ✅ Core | Manual kid-friendly overrides |
| `.gitignore` | Git config | — | ✅ Core | Excludes secrets and large files |
| `bugs_bunny_episodes.csv` | CSV reference | 80 episodes | ✅ Optional | Detailed Bugs Bunny data |
| `movies.csv` | CSV export | 586 rows | 🗑️ Optional | Older export; use the app instead |
| `EDrive_Duplicates_Report.csv` | CSV report | ~25,400 rows | 🗑️ Reference | Duplicate analysis |
| `SeagateBackup_SAFE_TO_DELETE.csv` | CSV report | ~11,400 rows | ⚠️ Keep until done | Review before deleting |
| `SeagateBackup_UNIQUE_FILES.csv` | CSV report | ~13,700 rows | ⚠️ Keep until done | Do NOT delete these |

---

## The 20-Genre System

Every video is tagged with one or more genres from this list. Tags are stored in `media_extra_cats.json` and editable through the app UI.

| Content Genres | | Audience / Lifestyle Tags |
|---|---|---|
| Action | Mystery | Kids |
| Adventure | Romance | Family |
| Animation | Sci-Fi | Faith |
| Comedy | Thriller | Fitness |
| Crime | | Favorites |
| Documentary | | |
| Drama | | |
| Fantasy | | |
| Holiday | | |
| Horror | | |
| Musical | | |

**Top filter bar** filters by primary type (Movies, TV Shows, Family, Favorites) and rating.  
**Genre filter bar** filters by any of the 20 genre tags above — multiple genres can be active at once.

---

## Content Notes

- **2 files removed** (`sparks-pp2012-xvid cd1/cd2`) — corrupt/unusable scene rips
- **DuckTales the Movie** moved from TV Shows → Movies (standalone animated film)
- **The Bible episodes** (Mission, Betrayal — History Channel miniseries) correctly placed under TV Shows → The Bible series
- **Pinky and the Brain** seasons 1–4 (previously showing as four separate "Season 1/2/3/4" series) consolidated into one series
- **VeggieTales Songs** merged into the main VeggieTales series
