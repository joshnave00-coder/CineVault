# CineVault — Changelog

All notable changes to the app are documented here.
Version format: `MAJOR.MINOR.PATCH`
- **MAJOR** — Architectural overhaul or breaking change
- **MINOR** — New feature or significant UI change
- **PATCH** — Bug fix or small refinement

---

## [3.12.0] — 2026-04-12

### Changed
- **🕹️ Frogger extracted to standalone app** — All game code moved to a new `frogger.py` file in the same directory. CineVault imports the HTML from `frogger.py` and serves it at `/frogger`, which the Konami-code trigger embeds in a fullscreen `<iframe>`. The game looks and plays identically inside CineVault. Exiting (ESC or the Exit button) sends a `postMessage` to CineVault, which tears down the iframe. `triggerFrogger()` in CineVault shrank from ~700 lines to 15.
- **Frogger as a standalone game** — Run `python frogger.py` from the Media Database folder to launch Frogger independently at `http://localhost:5001/`. Works without CineVault running. The Exit button closes the tab when possible; if the browser blocks `window.close()` (direct navigation), it shows a "Close this tab to exit" hint.

---

## [3.11.0] — 2026-04-12

### Added
- **👁 Watched / Unwatched tracking** — Every title can be tagged as watched or unwatched. Three ways to do it:
  1. **Card button** — A ✓ button (top-right of the card) appears on hover. Click it to instantly flip the status without opening the title. Watched cards keep the green ✓ visible at all times as a badge so you can see at a glance what you've already seen.
  2. **Movie detail modal** — A **Watched** toggle (like the Kid Friendly toggle) sits in the action row of every movie/episode popup.
  3. **Filter bar** — Two new buttons in the top bar — **✓ Watched** (green when active) and **○ Unwatched** (blue when active). Clicking once filters to that group; clicking again returns to All. Both are reset by Clear All Filters.
- **`/api/set_watched` route** — POST endpoint persisting `watched: bool` per path in `media_metadata.json`.

---

## [3.10.0] — 2026-04-12

### Added
- **🏆 Frogger leaderboard** — After game over, a 2.5-second countdown transitions automatically to initials entry (if the score qualifies for the top 5) or straight to the leaderboard. Enter up to 3 initials using ↑↓ arrows to cycle letters, ← → / Enter to move between slots, or just type letters directly; Backspace corrects the previous slot. Final entry triggers a fanfare. The leaderboard screen shows rank, name, score, level reached, and difficulty tier — new entries are highlighted in green. Scores persist across sessions via `localStorage`. Press Enter/Space from the leaderboard to return to the difficulty picker.
- **📊 Export Library CSV** (Settings page) — New "Export Library" card with a Download CSV button. Exports every title in the library along with all available metadata (display title, category, series, rating, year, genre, genres list, runtime, director, cast, description, kid-friendly flag, file size, extension, cover art status, and file path) as a UTF-8 CSV with BOM for Excel compatibility. Served via the new `/api/export_library_csv` route.

### Changed
- **✏️ Edit Metadata — moved to movie detail modal** — The pencil icon on each card has been removed. An **Edit Metadata** button now appears in the actions row of the movie detail popup (hidden in Kids Mode), making it discoverable only after selecting a title — a cleaner flow that keeps the card grid uncluttered.

### Fixed
- **Edit Metadata button did nothing on click** — `openEditModal()` was calling `decPath()`, a function that was never defined. Rewrote the function to use `activeVideo` (already set by the movie detail modal) instead of re-resolving the path, eliminating the silent failure entirely.

---

## [3.9.0] — 2026-04-12

### Added
- **✏️ Edit metadata button on cards** — A pencil icon button fades in on card hover (bottom-right corner). Hidden completely in Kids Mode. Clicking it opens the Edit Metadata sheet without navigating away from the library.
- **Edit Metadata sheet** — Full-featured metadata editor: Display Title, Year, Rating (full dropdown: G / PG / PG-13 / R / NC-17 / NR / TV-G / TV-Y / TV-Y7 / TV-PG / TV-14 / TV-MA), Runtime (minutes), Genre, Director, Cast (comma-separated), and Description. Pre-populated with existing metadata. Adapts to dark and light themes. ESC to dismiss.
- **`/api/update_metadata` route** — POST endpoint writing display_title, year, rating, runtime_min, genre, director, cast, and description to `media_metadata.json`. After a successful save the library refreshes in the background so cards update instantly.

---

## [3.8.1] — 2026-04-10

### Changed
- **Frogger difficulty selection** — Game now opens on a canvas-rendered difficulty picker (← → arrow keys or click to choose, Enter/click to start). Three tiers: **🟢 Easy** (50% speed, wider logs, fewer vehicles, 5 lives), **🟡 Medium** (75% speed, standard layout, 3 lives), **🔴 Hard** (full original speed and density, 3 lives). Level-up speed scaling is also gentler on easier tiers (+12%/+17%/+22% per level). Active difficulty shown as a badge in the game header. On game over, pressing R returns to the difficulty picker rather than restarting instantly. ESC from the select screen exits the arcade; ESC during play returns to the picker.

---

## [3.8.0] — 2026-04-10

### Added
- **🕹️ Hidden Frogger game** — Type the Konami code (↑ ↑ ↓ ↓ ← → ← →) anywhere on the main library page to unlock a fully playable, self-contained Frogger arcade game. Features: 13×13 grid with 5 road lanes and 5 river lanes; animated vehicles (cars and trucks) and logs riding river currents; frog drifts with log flow and dies if swept off-screen or falls in open water; 5 lily-pad homes to fill per level; 3-lives system with death flash animation; score tracking (+10 per row advanced, +100 per home, +500 level-clear bonus) with persistent high score; level progression increases all speeds by 22% per level; 8 distinct Web Audio API sound effects (hop, splash, squash, home fanfare, level-up arpeggio, game-over descending tones) with no external dependencies. Canvas rendered at 572×628 with pixel-perfect scaling to fit any screen. Retro-arcade styled with neon green UI, lane markings, animated water ripples, wood-grain log ends, directional headlights/tail lights, and an expressive directional frog sprite. Close with the Exit button or ESC; press R to restart after game over. The secret arcade banner reads `↑ ↑ ↓ ↓ ← → ← →` at all times as a knowing wink to those who found it.

---

## [3.7.0] — 2026-04-10

### Added
- **👑 Leia easter egg** — Type `leia` into the search bar to trigger a full-screen space surprise for Princess Leia. A dark starfield fills the screen with 220 twinkling stars and randomized shooting stars. Center card features a slowly spinning crown, shimmer-animated golden "Princess Leia!" gradient text, a "May the Force be with you ✨" tagline, and glowing blue lightsaber accent bars along the top and bottom edge. Auto-dismisses after 9 seconds or tap anywhere to close.
- **🐾 Lily easter egg** — Type `lily` into the search bar for a personalized animal-themed surprise for future vet Dr. Lily. 55 animal emojis (🐶🐱🐰🦊🐨🐸🐧🐾🦋🐼🦄 and more) float upward from the bottom at staggered speeds and delays over a soft pink overlay. Center card features a bouncing stethoscope, pink-to-purple gradient "Hi, Lily! 🌸" text, "Future Vet in Training! 🐾" tagline, and paw print decorations in each corner with a heartbeat pulse animation. Auto-dismisses after 9 seconds or tap anywhere to close.
- Both easter eggs clear the search field and restore the movie grid before triggering (same pattern as the popcorn easter egg). Cannot be double-triggered while already running.

---

## [3.6.3] — 2026-04-10

### Added
- **🍿 Popcorn easter egg** — Type `popcorn` into the search bar and 75 popcorn (and occasional 🌽 corn) emojis rain down the full screen. Each piece has randomized size (18–38px), staggered start height, fall speed, horizontal drift, wobble, and spin. They accelerate slightly as they fall (gravity), fade out over the bottom quarter of the screen, and clean themselves up automatically. A `🍿 Popcorn time!` toast fires at launch. Cannot be double-triggered while already running.

---

## [3.6.2] — 2026-04-10

### Changed
- **CineVault logo — single click resets library** — Clicking the logo once on the main page now clears all active filters (category, rating, genre, search, sort) and smooth-scrolls back to the top, returning to the default launch state. Clicks 1–4 all do this; click 5 within 2 seconds still triggers the credits easter egg.
- **CineVault logo on Settings — goes home** — Single click on the logo from the settings page navigates back to the main library. 5 rapid clicks still goes to credits (with a 350ms debounce so rapid clicks can accumulate before navigating).
- **About section `ⓘ` icon — links to credits** — The info icon in the Settings → About card is now clickable and navigates to `/credits`. Subtly scales and highlights on hover as a hint that it's interactive.

---

## [3.6.1] — 2026-04-10

### Added
- **Light bulb icon for light mode toggle** — Replaced `fa-sun` with `fa-lightbulb` on the theme toggle button. Moon stays for dark mode.
- **Easter egg — hidden credits page** (`/credits`) — Click the CineVault logo 5 times within 2 seconds from anywhere in the app to unlock a secret cinematic credits page. Features a live starfield background, slow auto-scroll (pauses on hover), and full credits listing Josh Nave across approximately every job title imaginable, Claude as co-developer, and Claude Code as the development environment. Also documents the Josh Brolin incident, WALL-E's incorrect birth year, and other historical events.

---

## [3.6.0] — 2026-04-10

### Changed
- **Light mode theme overhaul** — Fixed all the contrast and consistency problems in light mode:
  - **Nav & filter bars** — All three bars (`#nav`, `#fbar`, `#fbar2`), the series panel header, and the settings nav now use a `--nav-bg` CSS variable instead of a hardcoded dark `rgba(10,10,18,.97)`. In light mode this switches to a warm off-white frosted glass (`rgba(240,240,236,.97)`), eliminating the stark dark-vs-light contrast.
  - **Card borders** — `--border` darkened from `#ccccc4` → `#b0b0a6` in light mode so card outlines are visible against the white surface.
  - **Muted text** — `--muted` darkened from `#68687e` → `#58586e` for better readability.
  - **"All" category button** — Was `background:#fff` (invisible on a white nav). Now uses `var(--text)` / `var(--bg)` so it's a dark pill in light mode, matching the dark-mode white-pill look.
  - **Badge text colors** — All colored badges (ratings, categories, genres) had text colors that were too pale for a white background (e.g. `#86efac` green on white). Added `[data-theme="light"]` overrides for every badge class with proper dark, saturated colors.
  - **Genre chip text** — Same fix applied to all genre chips in modals and the series sidebar.
  - **Modal description & cast** — `#mdesc` was hardcoded `#c4c4e0` (invisible in light mode). `#mcast b` was hardcoded `#d4b4fe`. Both now use CSS variables.
  - **Settings page** — Applied the same `--nav-bg` and updated `--border`/`--muted`/`--bg` variables to the settings page theme block for consistency.
- **Removed Fitness genre** — Removed from the genre filter bar, the GENRES constant, and the modal add-genre dropdown. Existing videos already tagged with Fitness are unaffected (tag still displays correctly if assigned).

---

## [3.5.1] — 2026-04-10

### Added
- **Scroll-to-top button** — A floating `^` button appears in the bottom-right corner after scrolling down 400px. Fades in/out smoothly, scrolls back to the top with a smooth animation on click. Sits just above the toast notification so they don't overlap.

---

## [3.5.0] — 2026-04-10

### Added
- **Broken File Paths report** (Settings page) — New card that scans every entry in `media_cache.json` and checks whether the file still exists on disk. Shows a count badge ("12 of 825 broken"), filterable list (All / Movies / TV Shows), and per-row **Remove** button that cleans the entry out of the cache, metadata, and genre data. A **Remove All** button bulk-purges all broken entries at once (with confirmation). A **Rescan** button re-runs the check at any time.
- **Drive-offline warning** — If 5+ broken paths share the same drive letter, a yellow warning banner appears explaining the drive may be disconnected, advising not to remove entries until the drive is reconnected.
- **Play failure feedback** — Clicking Play on a missing file now shows a clear toast: `"⚠ File not found — drive may be disconnected or file was moved"` instead of silently opening WMP to nothing.
- **`/api/broken_paths`** route — Returns broken items, total checked, count, and detected offline drives.
- **`/api/remove_from_cache`** route — Accepts single `path` or array of `paths`, removes them from cache, metadata, and extra-cats files atomically.

### Changed
- **Connectivity pill** — Simplified to just `● Online` / `● Offline` (removed latency ms from display). Latency is still shown on hover via tooltip. Text is slightly smaller.

---

## [3.4.0] — 2026-04-10

### Added
- **Internet connectivity check** — New `/api/connectivity` route probes three hosts in sequence (Google DNS → Cloudflare DNS → TMDB) via socket and returns `{online, latency_ms, host}`. Designed to catch connection problems before any API call is attempted.
- **Connectivity pill** — Both the main library nav and the settings nav show a live color-coded pill: green `● 42ms` when online, red `● Offline` when not. Updates on page load and polls every 60 seconds automatically.
- **Offline banners** — Settings page shows warning banners inside the TMDB Token and Missing Cover Art cards when offline, explaining which features are unavailable.
- **TMDB button guards** — Save Token, Test Token, and all Fetch (cover preview) buttons are disabled and titled `"No internet connection"` when offline. `fetchCoverPreview`, `saveTmdbToken`, and `testTmdbToken` also check `_isOnline` before making any network call.

---

## [3.3.1] — 2026-04-10

### Fixed
- **Scroll lock after closing TV series panel** — `closeSeries()` was calling `document.getElementById('sp-genre-bar')` on an element that no longer exists (removed in a prior layout refactor). The resulting `TypeError` crashed the function before `document.body.style.overflow = ''` could run, permanently locking page scroll for the rest of the session. Removed the dead reference.
- **WMP not coming to foreground / fullscreen not working** — Replaced the PowerShell + `WScript.Shell.AppActivate` + `SendKeys` approach entirely. Windows silently blocks background processes from calling `SetForegroundWindow`, so the fullscreen command was never reaching WMP. Replaced with a Python daemon thread using `ctypes` Win32 calls: finds WMP by window class name `WMPlayerApp` (works even when WMP reuses an existing instance), uses the `AttachThreadInput` trick to unlock foreground-window permission, force-maximizes via `ShowWindow`, then sends `Alt+Enter` via `keybd_event` (more reliable than `SendKeys` from a hidden process).

---

## [3.3.0] — 2026-04-09

### Added
- **Missing Cover Art report** (Settings page) — New card showing how many movies and TV series are missing poster art, with filter buttons (All / Movies / TV Shows). Each row has a **Fetch** button that queries TMDB for the best match and shows a preview modal (190×285 poster, TMDB title + year). User can **Apply Cover** (downloads and saves the image, shows green ✓) or **Skip**. Count badge updates live as covers are applied.
- **TMDB Token Manager** (Settings page) — Paste and save a TMDB Read Access Token (`eyJ…`), view/reveal the stored token, and test it against the TMDB API with a one-click connection check.
- New Python API routes: `/api/missing_covers`, `/api/fetch_cover_preview`, `/api/apply_cover_from_tmdb`, `/api/get_tmdb_token`, `/api/save_tmdb_token`, `/api/test_tmdb_token`.

---

## [3.2.0] — 2026-04-08

### Added
- **Settings page** (`/settings`) — Separate full-page route with: Library stats (total, movies, episodes, series, covered, missing), Quick/Full scan buttons, Kid Mode PIN management, Appearance (dark/light toggle).
- **TV Series two-column layout** — Series panel redesigned to match a streaming-service style: fixed left sidebar (poster, cast, description, genre chips, Favorites / Change Cover actions) and scrollable right column (season tabs + episode list).
- **Settings button hidden in Kid Mode** — Settings is inaccessible while Kid Mode is active, matching the restriction on other edit features.

### Fixed
- **How It's Made season parsing** — `parseEpisode()` extended with `NNxEE` (e.g. `11x01`) and compact `NMM` (e.g. `101`) patterns, plus a raw `v.title` fallback for episodes where `display_title` was stripped of episode numbers. Seasons 7–10 now show correctly.

---

## [3.1.0] — 2026-04-07

### Added
- **Multi-select category filter** — Top bar buttons (All, Movies, TV Shows, Favorites) now act as a multi-select toggle. Empty selection = "All". Internally changed from `filter.cat` (string) to `filter.cats` (Set).
- **Multi-select rating filter** — Rating buttons (G, PG, PG-13, etc.) can be combined to show multiple ratings simultaneously. Changed from single-value to `filter.ratings` Set with `toggleRating()`.
- **Genre badges on video modal** — Active genres displayed as removable badge chips inside the card. A dropdown lets you add genres not yet assigned. Replaces the old inline checkbox list.
- **Sort by Video Length** — Added "Video Length" sort option. Removed "Most Recently Added" and "Genre" sort options.
- **Kid Friendly toggle disabled in Kid Mode** — The toggle is grayed out and non-interactive when browsing in Kid Mode so children cannot self-edit the tag.
- **`encPath()` helper** — Prevents apostrophes in file paths from breaking `onclick` handlers (e.g. "A Bug's Life").

### Changed
- **App renamed to CineVault** — All UI references updated from "Josh's Media Library" to "CineVault".
- **Genre list reorganized** — Removed Crime, Horror, Mystery, Thriller from the filter bar. Added Faith and Fitness in alphabetical order. Removed Family from the top category bar (it remains a genre tag). Removed Kids and Favorites from the genre filter bar (Favorites stays in the category bar).

### Fixed
- **"A Bug's Life" card wouldn't open** — Apostrophes in file paths broke `onclick='openModal('...')'`. Fixed with `encPath()` which encodes `'` as `%27`.
- **Genre badges not showing** — `#mcat-editor` has `display:none` in CSS; JS was setting `style.display = ''` which reverted to CSS hidden. Fixed by explicitly setting `style.display = 'block'`.

---

## [3.0.0] — Initial Release

### Features at launch
- Flask-based local media browser with Netflix-style card grid
- Auto-scan of `E:\Movies` and `E:\Shows`; metadata stored in `media_cache.json`
- Cover art upload and storage in `covers/` directory
- Cast, rating, year, description sourced from `media_metadata.json`
- TV Series grouping with season/episode parsing
- Kid Mode (PIN-protected exit, filters to kid-friendly content)
- Dark/light theme toggle (persisted in `localStorage`)
- Video playback via Windows Media Player (`/open` route)
- Streamable badge for browser-playable formats (`.mp4`, `.m4v`, `.webm`, `.mov`)
- Favorites system via genre tag
- `media_extra_cats.json` for per-video genre overrides
