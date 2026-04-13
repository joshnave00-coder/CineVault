#!/usr/bin/env python3
"""
CineVault  v3
Self-contained local media browser with Netflix-style UI.
Run via 'Start Media Library.bat'  or:  python media_library.py
Then open http://localhost:5000
"""

import os, json, re, webbrowser, threading, time, subprocess
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request, Response, send_from_directory
from frogger import FROGGER_HTML

app = Flask(__name__)

APP_VERSION = '3.12.0'

# ── Config ────────────────────────────────────────────────────────────────────
QUICK_SCAN_PATHS = [r'E:\Movies', r'E:\Shows']
FULL_SCAN_PATHS  = [r'E:\Movies', r'E:\Shows',
                    r'E:\Personal bckup 1\My Videos',
                    r'E:\Personal bckup 1\My Pictures']

VIDEO_EXTS      = {'.mp4','.m4v','.avi','.mov','.mpg','.mpeg','.wmv','.mkv','.flv','.webm','.3gp'}
STREAMABLE_EXTS = {'.mp4','.m4v','.webm','.mov'}

DATA_DIR            = Path(__file__).parent
CACHE_FILE          = DATA_DIR / 'media_cache.json'
TAGS_FILE           = DATA_DIR / 'media_tags.json'
METADATA_FILE       = DATA_DIR / 'media_metadata.json'
SERIES_POSTERS_FILE = DATA_DIR / 'series_posters.json'
EXTRA_CATS_FILE     = DATA_DIR / 'media_extra_cats.json'
SETTINGS_FILE       = DATA_DIR / 'cinevault_settings.json'
COVERS_DIR          = DATA_DIR / 'covers'

# Primary structural categories (what type of media)
PRIMARY_CATS = ['Movies', 'TV Shows', 'Music', 'Personal']

# Genre / tag list (what kind of content — editable per video)
GENRES = [
    'Action', 'Adventure', 'Animation', 'Comedy',
    'Documentary', 'Drama', 'Faith', 'Family', 'Fantasy',
    'Holiday', 'Musical', 'Romance', 'Sci-Fi',
    'Kids', 'Favorites',
]

AVAILABLE_CATS = PRIMARY_CATS + GENRES  # full list for API

# ── JSON helpers ──────────────────────────────────────────────────────────────
def load_json(path, default=None):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except: pass
    return default if default is not None else {}

def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

# ── Title cleaning ─────────────────────────────────────────────────────────────
QUALITY_RE = re.compile(
    r'\b(WS|FS|LQ|HQ|TQ|HD|SD|4K|UHD|BRRip|BluRay|Blu-Ray|DVDRip|DVDScr|'
    r'WEBRip|WEB-DL|HDTV|XviD|x264|x265|H264|H265|HEVC|'
    r'AAC|AC3|DTS|MP3|DiVERSiTY|sparks|YIFY|YTS|PROPER|REPACK|'
    r'720p|1080p|480p|2160p)\b', re.I)
BRACKET_RE  = re.compile(r'\[[^\]]*\]')
SCENE_RE    = re.compile(r'\b(cedar|ct-?|ef-?|ys-?|ws-hd|ws-tq|fs-lq|fs-hd)\b.*$', re.I)
LOWER_WORDS = {'a','an','the','and','but','or','for','nor','on','at','to','by','in','of','up','as','vs','via'}

def title_case(s):
    words = s.split()
    out = []
    for i, w in enumerate(words):
        out.append(w.capitalize() if (i == 0 or w.lower() not in LOWER_WORDS) else w.lower())
    return ' '.join(out)

def clean_title(filename):
    name = Path(filename).stem
    name = QUALITY_RE.sub('', name)
    name = BRACKET_RE.sub('', name)
    name = SCENE_RE.sub('', name)
    name = re.sub(r'^(\d{3})\s+', '', name)   # strip leading 3-digit index (e.g. Bugs Bunny shorts)
    name = re.sub(r'[._]', ' ', name)
    name = re.sub(r'\s*-\s*$', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return title_case(name)

def clean_folder_name(raw):
    name = re.sub(r'[._]', ' ', raw)
    name = re.sub(r'\(\d{4}\)', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return title_case(name)

# ── Categorization ────────────────────────────────────────────────────────────
CARTOON_SHOWS = ['pinky and the brain', 'animaniacs', 'bugs bunny',
                 'veggie tales', 'veggietales', 'ducktales']

def categorize(filepath, filename):
    """Returns (category, series_name, kid_auto, unwatched)."""
    p  = filepath.lower().replace('\\', '/')
    fn = filename.lower()

    unwatched = 'have not watched' in p

    # Cartoon / episodic kids shows inside Kids Movies
    for show in CARTOON_SHOWS:
        if show.replace(' ', '') in p.replace(' ','').replace('_',''):
            parts  = re.split(r'[/\\]', filepath)
            folder = clean_folder_name(parts[-2]) if len(parts) >= 2 else 'Cartoons'
            # If parent folder is a bare season dir, use the show title instead
            if re.match(r'^season\s*\d+$', folder, re.I):
                folder = show.title()
            return ('TV Shows', folder, True, unwatched)

    # Music concerts
    if re.search(r'/movies/music/', p):
        return ('Music', 'Concerts', False, unwatched)

    # Kids Movies folder — keep kid_friendly flag, classify as Movies or TV Shows
    if '/kids movies/' in p or '/kids/' in p:
        if re.search(r's\d{1,2}e\d{1,2}', fn) or re.search(r'\.ep\d{2}\.', fn) or re.search(r'\d+of\d+', fn):
            parts  = re.split(r'[/\\]', filepath)
            series = clean_folder_name(parts[-2]) if len(parts) >= 2 else 'TV Shows'
            return ('TV Shows', series, True, unwatched)
        return ('Movies', None, True, unwatched)

    # Planet Earth series
    if 'planet earth' in p:
        return ('TV Shows', 'Planet Earth', False, unwatched)

    # The Bible miniseries — match folder path OR filename containing "the.bible" / "the bible"
    if ('/the.bible/' in p or '/the bible' in p or
            ('the.bible' in fn and re.search(r'of\d+|miniseries', fn))):
        return ('TV Shows', 'The Bible', False, unwatched)

    # Shows folder
    if '/shows/' in p:
        # Pitch Perfect was accidentally placed in Shows — it's a movie
        if 'pitch.perfect' in p or 'pitch perfect' in p:
            return ('Movies', None, False, unwatched)
        try:
            parts     = re.split(r'[/\\]', filepath)
            shows_idx = [x.lower() for x in parts].index('shows')
            series    = clean_folder_name(parts[shows_idx + 1]) if shows_idx + 1 < len(parts) else 'TV Shows'
        except:
            series = 'TV Shows'
        return ('TV Shows', series, False, unwatched)

    # Movies folder — check for hidden episode patterns
    if '/movies/' in p:
        if re.search(r's\d{1,2}e\d{1,2}', fn):           # S01E01
            parts  = re.split(r'[/\\]', filepath)
            series = clean_folder_name(parts[-2]) if len(parts) >= 2 else 'TV Shows'
            return ('TV Shows', series, False, unwatched)
        if re.search(r'\.ep\d{2}\.', fn):                  # .EP01.
            parts  = re.split(r'[/\\]', filepath)
            series = clean_folder_name(parts[-2]) if len(parts) >= 2 else 'TV Shows'
            return ('TV Shows', series, False, unwatched)
        if re.search(r'\d+of\d+', fn):                     # 05of10
            parts  = re.split(r'[/\\]', filepath)
            series = clean_folder_name(parts[-2]) if len(parts) >= 2 else 'TV Shows'
            return ('TV Shows', series, False, unwatched)
        return ('Movies', None, False, unwatched)

    return ('Personal', None, False, unwatched)

# ── Episode title builder ──────────────────────────────────────────────────────
def build_episode_title(filename):
    name = Path(filename).stem

    # S01E01 – Episode Name
    m = re.search(r'[Ss](\d{1,2})[Ee](\d{1,2})(?:[Ee]\d{1,2})*\s*[-.\s]*(.*)', name)
    if m:
        s, e, rest = m.group(1), m.group(2), m.group(3).strip()
        rest = QUALITY_RE.sub('', rest)
        rest = re.sub(r'[._]', ' ', rest).strip('-. ')
        label = f"S{int(s):02d}E{int(e):02d}"
        return f"{label} – {title_case(rest)}" if rest else label

    # .EP01.Title
    m = re.search(r'\.ep(\d{2})\.(.+)', name, re.I)
    if m:
        return f"Ep {int(m.group(1)):02d} – {title_case(re.sub(r'[._]',' ', m.group(2)).strip())}"

    # 05of10.Title
    m = re.search(r'(\d+)of(\d+)[.\s]+(.+)', name, re.I)
    if m:
        ep_title = title_case(re.sub(r'[._]', ' ', m.group(3)).strip())
        return f"Part {m.group(1)} of {m.group(2)} – {ep_title}"

    # DISC.05.Title  (P90X style)
    m = re.search(r'disc[.\s]+(\d+)[.\s]+(.+)', name, re.I)
    if m:
        ep_title = title_case(re.sub(r'[._]', ' ', m.group(2)).strip())
        ep_title = QUALITY_RE.sub('', ep_title).strip()
        return f"Disc {int(m.group(1)):02d} – {ep_title}"

    # 01-Title or 01 Title  (numbered episodes)
    m = re.match(r'^(\d{1,3})[-.\s]+(.+)', name)
    if m:
        ep_title = QUALITY_RE.sub('', re.sub(r'[._]', ' ', m.group(2))).strip()
        return f"{int(m.group(1)):02d} – {title_case(ep_title)}"

    return clean_title(filename)

# ── Duration via ffprobe ──────────────────────────────────────────────────────
_ffprobe_ok = None

def has_ffprobe():
    global _ffprobe_ok
    if _ffprobe_ok is None:
        try:
            r = subprocess.run(['ffprobe', '-version'], capture_output=True, timeout=5)
            _ffprobe_ok = (r.returncode == 0)
        except:
            _ffprobe_ok = False
    return _ffprobe_ok

def get_duration(filepath):
    if not has_ffprobe():
        return None
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
             '-of', 'csv=p=0', filepath],
            capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            secs = float(r.stdout.strip())
            h = int(secs // 3600)
            m = int((secs % 3600) // 60)
            s = int(secs % 60)
            return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    except:
        pass
    return None

# ── Scan ──────────────────────────────────────────────────────────────────────
def scan_videos(paths, add_duration=False):
    tags  = load_json(TAGS_FILE)
    seen  = set()
    videos = []

    for scan_path in paths:
        if not os.path.exists(scan_path):
            continue
        for root, dirs, files in os.walk(scan_path):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for fname in files:
                ext = Path(fname).suffix.lower()
                if ext not in VIDEO_EXTS:
                    continue
                fpath = os.path.join(root, fname)
                if fpath in seen:
                    continue
                seen.add(fpath)

                try:    size_mb = round(os.path.getsize(fpath) / 1_048_576, 1)
                except: size_mb = 0

                cat, series, kid_auto, unwatched = categorize(fpath, fname)
                tag_data     = tags.get(fpath, {})
                kid_friendly = tag_data.get('kid_friendly', kid_auto)

                # Build display title
                if series:
                    display_title = build_episode_title(fname)
                else:
                    display_title = clean_title(fname)
                    # Handle split cd1/cd2 movies
                    m = re.search(r'\.cd(\d)$', Path(fname).stem, re.I)
                    if m:
                        base = re.sub(r'\.cd\d$', '', Path(fname).stem, flags=re.I)
                        display_title = clean_title(base + '.avi') + f' (Part {m.group(1)})'

                duration = get_duration(fpath) if add_duration else None

                videos.append({
                    'path':         fpath,
                    'title':        display_title,
                    'filename':     fname,
                    'category':     cat,
                    'series':       series or '',
                    'size_mb':      size_mb,
                    'kid_friendly': kid_friendly,
                    'kid_auto':     kid_auto,
                    'unwatched':    unwatched,
                    'streamable':   ext in STREAMABLE_EXTS,
                    'ext':          ext,
                    'duration':     duration,
                })

    videos.sort(key=lambda v: (v['category'], v['series'].lower(), v['title'].lower()))
    return videos

# ── Reprocess (fix titles/categories without re-scanning drive) ───────────────
def reprocess_cache():
    raw  = load_json(CACHE_FILE, default=[])
    tags = load_json(TAGS_FILE)
    if not isinstance(raw, list):
        return []
    updated = []
    for v in raw:
        fpath, fname = v['path'], v['filename']
        cat, series, kid_auto, unwatched = categorize(fpath, fname)
        ext        = Path(fname).suffix.lower()
        tag_data   = tags.get(fpath, {})

        if series:
            display_title = build_episode_title(fname)
        else:
            display_title = clean_title(fname)
            m = re.search(r'\.cd(\d)$', Path(fname).stem, re.I)
            if m:
                base = re.sub(r'\.cd\d$', '', Path(fname).stem, flags=re.I)
                display_title = clean_title(base + '.avi') + f' (Part {m.group(1)})'

        updated.append({
            'path':         fpath,
            'title':        display_title,
            'filename':     fname,
            'category':     cat,
            'series':       series or '',
            'size_mb':      v.get('size_mb', 0),
            'kid_friendly': tag_data.get('kid_friendly', kid_auto),
            'kid_auto':     kid_auto,
            'unwatched':    unwatched,
            'streamable':   ext in STREAMABLE_EXTS,
            'ext':          ext,
            'duration':     v.get('duration'),
        })

    updated.sort(key=lambda v: (v['category'], v['series'].lower(), v['title'].lower()))
    save_json(CACHE_FILE, updated)
    return updated

# ── Shared metadata merge ─────────────────────────────────────────────────────
def auto_genres(v, m):
    """Auto-assign genre tags from TMDB genre text, series/title keywords, and flags."""
    g      = (m.get('genre') or '').lower()   # TMDB genre string e.g. "Action / Comedy"
    series = (v.get('series') or '').lower()
    title  = (m.get('display_title') or v.get('title') or '').lower()
    is_kid = v.get('kid_friendly') or m.get('kid_friendly')

    tags = []

    # Audience/mood tags first
    if is_kid:
        tags.append('Kids')

    # Content genres mapped from TMDB genre text
    if 'action'      in g:                            tags.append('Action')
    if 'adventure'   in g:                            tags.append('Adventure')
    if 'animat'      in g:                            tags.append('Animation')
    if 'comedy'      in g:                            tags.append('Comedy')
    if 'crime'       in g:                            tags.append('Crime')
    if ('documentary' in g or 'nature' in g or
            any(s in series for s in ['planet earth', "how it's made",
                                      'americas test kitchen'])):
        tags.append('Documentary')
    if 'drama'       in g:                            tags.append('Drama')
    if 'fantasy'     in g:                            tags.append('Fantasy')
    if ('christmas'  in g or 'holiday' in g or
            'christmas' in title or 'holiday' in title):
        tags.append('Holiday')
    if 'horror'      in g:                            tags.append('Horror')
    if 'music'       in g or 'musical' in g:         tags.append('Musical')
    if 'mystery'     in g:                            tags.append('Mystery')
    if 'romance'     in g:                            tags.append('Romance')
    if ('sci-fi'     in g or 'science fiction' in g or
            'sci fi' in g):                           tags.append('Sci-Fi')
    if 'thriller'    in g:                            tags.append('Thriller')

    # Special keyword overrides
    if (any(w in g      for w in ['christian', 'religious', 'faith']) or
            any(w in series for w in ['bible', 'dave ramsey', 'fpu', 'financial peace']) or
            'passion of the christ' in title or 'bible' in title):
        tags.append('Faith')
    if (any(w in g      for w in ['fitness', 'workout']) or
            any(w in series for w in ['p90x', 'workout', 'fitness'])):
        tags.append('Fitness')

    return list(dict.fromkeys(tags))   # deduplicate, preserve order


def apply_metadata(videos):
    """Merge media_metadata.json enrichments on top of raw cache entries."""
    tags           = load_json(TAGS_FILE)
    meta           = load_json(METADATA_FILE, default={})
    series_posters = load_json(SERIES_POSTERS_FILE, default={})
    extra_cats_db  = load_json(EXTRA_CATS_FILE, default={})
    for v in videos:
        v['kid_friendly'] = tags.get(v['path'], {}).get('kid_friendly', v.get('kid_auto', False))
        m = meta.get(v['path'], {})
        v['rating']        = m.get('rating', '')
        v['genre']         = m.get('genre', '')
        v['runtime_min']   = m.get('runtime_min', None)
        v['description']   = m.get('description', '')
        v['director']      = m.get('director', '')
        v['cast']          = m.get('cast', [])
        v['meta_year']     = m.get('year', None)
        v['watched']       = bool(m.get('watched', False))
        v['display_title'] = m.get('display_title') or v.get('title', '')
        v['poster_local']  = m.get('poster_local', '') or series_posters.get(v.get('series', ''), '')
        # File modification time for "Most Recently Added" sort
        try:    v['mtime'] = os.path.getmtime(v['path'])
        except: v['mtime'] = 0
        # Genre tags: stored manual overrides take priority, else auto-detect
        if v['path'] in extra_cats_db:
            genres = extra_cats_db[v['path']]
        else:
            genres = auto_genres(v, m)
        primary = v['category']
        v['genres']      = genres
        v['extra_cats']  = genres          # keep legacy key for API compat
        v['categories']  = [primary] + [g for g in genres if g != primary]
        # Pull series from metadata when the cache scan missed it
        if m.get('series') and not v.get('series'):
            v['series'] = m['series']
            if v.get('category') == 'Movies':
                v['category'] = 'TV Shows'
        if m.get('kid_friendly') is not None and not tags.get(v['path']):
            v['kid_friendly'] = m['kid_friendly']
    return videos

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/api/library')
def library():
    raw = load_json(CACHE_FILE, default=[])
    if not isinstance(raw, list):
        return jsonify([])
    return jsonify(apply_metadata(raw))

@app.route('/api/scan')
def api_scan():
    full     = request.args.get('full', 'false') == 'true'
    with_dur = request.args.get('duration', 'false') == 'true'
    videos   = scan_videos(FULL_SCAN_PATHS if full else QUICK_SCAN_PATHS, add_duration=with_dur)
    save_json(CACHE_FILE, videos)
    return jsonify(apply_metadata(videos))

@app.route('/api/reprocess')
def api_reprocess():
    videos = reprocess_cache()
    return jsonify(apply_metadata(videos))

@app.route('/api/tag', methods=['POST'])
def api_tag():
    data = request.get_json()
    path, kf = data.get('path'), data.get('kid_friendly', False)
    tags = load_json(TAGS_FILE)
    tags.setdefault(path, {})['kid_friendly'] = kf
    save_json(TAGS_FILE, tags)
    return jsonify({'ok': True})

@app.route('/api/duration')
def api_duration():
    path = request.args.get('path', '')
    if not path or not os.path.exists(path):
        return jsonify({'duration': None})
    return jsonify({'duration': get_duration(path)})

@app.route('/stream')
def stream():
    path = request.args.get('path', '')
    if not path or not os.path.exists(path):
        return 'File not found', 404
    size = os.path.getsize(path)
    ext  = Path(path).suffix.lower()
    mime_map = {
        '.mp4':'video/mp4', '.m4v':'video/mp4', '.webm':'video/webm',
        '.mov':'video/quicktime', '.avi':'video/x-msvideo',
        '.mpg':'video/mpeg', '.mpeg':'video/mpeg', '.wmv':'video/x-ms-wmv',
        '.mkv':'video/x-matroska', '.3gp':'video/3gpp', '.flv':'video/x-flv',
    }
    mime = mime_map.get(ext, 'video/mp4')
    rng  = request.headers.get('Range', '')

    def gen(start, end):
        with open(path, 'rb') as f:
            f.seek(start)
            rem = end - start + 1
            while rem > 0:
                chunk = f.read(min(65536, rem))
                if not chunk: break
                rem -= len(chunk)
                yield chunk

    if rng:
        m     = re.search(r'bytes=(\d+)-(\d*)', rng)
        start = int(m.group(1)) if m else 0
        end   = int(m.group(2)) if m and m.group(2) else size - 1
        end   = min(end, size - 1)
        resp  = Response(gen(start, end), 206, mimetype=mime, direct_passthrough=True)
        resp.headers['Content-Range']  = f'bytes {start}-{end}/{size}'
        resp.headers['Accept-Ranges']  = 'bytes'
        resp.headers['Content-Length'] = str(end - start + 1)
        return resp

    resp = Response(gen(0, size - 1), 200, mimetype=mime, direct_passthrough=True)
    resp.headers['Accept-Ranges']  = 'bytes'
    resp.headers['Content-Length'] = str(size)
    return resp

def _wmp_fullscreen():
    """Run in a daemon thread: find WMP by window class, maximize it,
    force it to the foreground (AttachThreadInput trick), then send
    Alt+Enter to enter WMP's true borderless fullscreen mode."""
    import ctypes, ctypes.wintypes, time

    user32   = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    SW_MAXIMIZE      = 3
    VK_MENU          = 0x12   # Alt
    VK_RETURN        = 0x0D   # Enter
    KEYEVENTF_KEYUP  = 0x0002

    # ── 1. Poll until the WMP main window appears (up to ~15 s) ──────────────
    # FindWindowW by class name works whether WMP is new or reused-instance.
    hwnd = None
    for _ in range(50):
        h = user32.FindWindowW("WMPlayerApp", None)
        if h:
            hwnd = h
            break
        time.sleep(0.3)
    if not hwnd:
        return

    # ── 2. Let WMP finish restoring its saved window position ─────────────────
    time.sleep(2.0)

    # ── 3. Force-maximize so the next step always toggles to fullscreen ───────
    user32.ShowWindow(hwnd, SW_MAXIMIZE)
    time.sleep(0.5)

    # ── 4. AttachThreadInput trick — lets a background thread call
    #       SetForegroundWindow successfully (Windows normally blocks this). ───
    fg_hwnd = user32.GetForegroundWindow()
    fg_tid  = user32.GetWindowThreadProcessId(fg_hwnd, None)
    my_tid  = kernel32.GetCurrentThreadId()
    if fg_tid and fg_tid != my_tid:
        user32.AttachThreadInput(my_tid, fg_tid, True)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    if fg_tid and fg_tid != my_tid:
        user32.AttachThreadInput(my_tid, fg_tid, False)
    time.sleep(0.4)

    # ── 5. Send Alt+1 — WMP's "Switch to Now Playing" shortcut.
    #       Without this WMP stays in Library mode and Alt+Enter does nothing. ─
    VK_1 = 0x31
    user32.keybd_event(VK_MENU, 0, 0,               0)
    user32.keybd_event(VK_1,    0, 0,               0)
    user32.keybd_event(VK_1,    0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.7)   # let Now Playing mode fully render

    # ── 6. Send Alt+Enter to enter WMP's true borderless fullscreen mode. ─────
    user32.keybd_event(VK_MENU,   0, 0,               0)
    user32.keybd_event(VK_RETURN, 0, 0,               0)
    user32.keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_MENU,   0, KEYEVENTF_KEYUP, 0)


@app.route('/open')
def open_file():
    path = request.args.get('path', '')
    if not path or not os.path.exists(path):
        return jsonify({'ok': False}), 404
    wmp = r'C:\Program Files\Windows Media Player\wmplayer.exe'
    if os.path.exists(wmp):
        si = subprocess.STARTUPINFO()
        si.dwFlags     = subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 3  # SW_SHOWMAXIMIZED — reasonable starting size
        subprocess.Popen([wmp, path], startupinfo=si)
        # Fullscreen logic runs in a daemon thread so the route returns instantly
        threading.Thread(target=_wmp_fullscreen, daemon=True).start()
    else:
        os.startfile(path)
    return jsonify({'ok': True})

@app.route('/covers/<path:filename>')
def serve_cover(filename):
    return send_from_directory(COVERS_DIR, filename)

@app.route('/api/available_cats')
def api_available_cats():
    return jsonify(AVAILABLE_CATS)

@app.route('/api/set_cats', methods=['POST'])
def api_set_cats():
    data  = request.get_json()
    path  = data.get('path', '')
    extra = data.get('extra_cats', [])
    db    = load_json(EXTRA_CATS_FILE, default={})
    if extra:
        db[path] = extra
    else:
        db.pop(path, None)
    save_json(EXTRA_CATS_FILE, db)
    return jsonify({'ok': True})

@app.route('/api/remove_cover', methods=['POST'])
def api_remove_cover():
    data   = request.get_json()
    path   = data.get('path', '')
    series = data.get('series', '')

    meta           = load_json(METADATA_FILE, default={})
    series_posters = load_json(SERIES_POSTERS_FILE, default={})

    removed = None

    if series and series in series_posters:
        removed = series_posters.pop(series)
        save_json(SERIES_POSTERS_FILE, series_posters)

    if path and path in meta and meta[path].get('poster_local'):
        removed = removed or meta[path]['poster_local']
        del meta[path]['poster_local']
        save_json(METADATA_FILE, meta)

    # Delete the image file if nothing else references it
    if removed:
        img_path = DATA_DIR / removed
        still_referenced = (
            any(v.get('poster_local') == removed for v in meta.values()) or
            any(v == removed for v in series_posters.values())
        )
        if not still_referenced and img_path.exists():
            img_path.unlink()

    return jsonify({'ok': True, 'removed': removed})

@app.route('/api/set_cover', methods=['POST'])
def api_set_cover():
    """Upload a new cover image for a series or individual movie."""
    series   = request.form.get('series', '')
    path     = request.form.get('path', '')
    img_file = request.files.get('image')
    if not img_file or (not series and not path):
        return jsonify({'ok': False, 'error': 'missing params'}), 400

    COVERS_DIR.mkdir(exist_ok=True)
    ext      = Path(img_file.filename).suffix.lower() if img_file.filename else '.jpg'
    if ext not in {'.jpg', '.jpeg', '.png', '.webp'}:
        ext = '.jpg'

    # Derive a safe filename from series name or movie path
    base     = series if series else Path(path).stem
    safe     = re.sub(r'[^\w-]', '_', base).strip('_') + ext
    out_path = COVERS_DIR / safe
    img_file.save(str(out_path))
    local_ref = f'covers/{safe}'

    if series:
        sp = load_json(SERIES_POSTERS_FILE, default={})
        sp[series] = local_ref
        save_json(SERIES_POSTERS_FILE, sp)
    if path:
        meta = load_json(METADATA_FILE, default={})
        meta.setdefault(path, {})['poster_local'] = local_ref
        save_json(METADATA_FILE, meta)

    return jsonify({'ok': True, 'poster_local': local_ref})

@app.route('/api/set_series_genres', methods=['POST'])
def api_set_series_genres():
    """Set the same genre list on every episode of a series."""
    data   = request.get_json()
    series = data.get('series', '')
    genres = data.get('genres', [])
    if not series:
        return jsonify({'ok': False, 'error': 'missing series'}), 400

    cache  = load_json(CACHE_FILE, default=[])
    db     = load_json(EXTRA_CATS_FILE, default={})
    updated = 0
    for v in cache:
        if v.get('series') == series:
            db[v['path']] = genres
            updated += 1
    save_json(EXTRA_CATS_FILE, db)
    return jsonify({'ok': True, 'updated': updated})

@app.route('/api/stats')
def api_stats():
    cache   = load_json(CACHE_FILE, default=[])
    meta    = load_json(METADATA_FILE, default={})
    movies  = [v for v in cache if v.get('category') == 'Movies']
    shows   = [v for v in cache if v.get('category') == 'TV Shows']
    series  = set(v.get('series','') for v in shows if v.get('series'))
    covered = sum(1 for v in cache if meta.get(v['path'], {}).get('poster_local'))
    return jsonify({
        'total':   len(cache),
        'movies':  len(movies),
        'episodes': len(shows),
        'series':  len(series),
        'covered': covered,
        'missing': len(cache) - covered,
    })

@app.route('/api/get_settings')
def api_get_settings():
    s = load_json(SETTINGS_FILE, default={'pin': '0000'})
    return jsonify(s)

@app.route('/api/save_settings', methods=['POST'])
def api_save_settings():
    data = request.get_json()
    s = load_json(SETTINGS_FILE, default={'pin': '0000'})
    if 'pin' in data:
        s['pin'] = str(data['pin'])
    save_json(SETTINGS_FILE, s)
    return jsonify({'ok': True})

@app.route('/api/get_tmdb_token')
def api_get_tmdb_token():
    cfg = load_json(DATA_DIR / 'config.json', default={})
    token = cfg.get('tmdb_bearer_token', '')
    # Mask all but first/last 6 chars for display — full token returned so JS can fill the field
    return jsonify({'token': token})

@app.route('/api/save_tmdb_token', methods=['POST'])
def api_save_tmdb_token():
    data  = request.get_json()
    token = (data.get('token') or '').strip()
    if not token:
        return jsonify({'ok': False, 'error': 'empty token'}), 400
    cfg = load_json(DATA_DIR / 'config.json', default={})
    cfg['tmdb_bearer_token'] = token
    save_json(DATA_DIR / 'config.json', cfg)
    return jsonify({'ok': True})

@app.route('/api/test_tmdb_token')
def api_test_tmdb_token():
    import urllib.request as ur
    cfg   = load_json(DATA_DIR / 'config.json', default={})
    token = cfg.get('tmdb_bearer_token', '')
    if not token:
        return jsonify({'ok': False, 'error': 'no token'})
    try:
        req = ur.Request(
            'https://api.themoviedb.org/3/account',
            headers={'Authorization': f'Bearer {token}', 'accept': 'application/json'}
        )
        with ur.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read())
        username = body.get('username') or body.get('name') or 'unknown'
        return jsonify({'ok': True, 'username': username})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/missing_covers')
def api_missing_covers():
    """Return list of movies/series that have no cover art."""
    cache          = load_json(CACHE_FILE, default=[])
    meta           = load_json(METADATA_FILE, default={})
    series_posters = load_json(SERIES_POSTERS_FILE, default={})

    items = []

    # ── Movies without a poster_local ──────────────────────────────────────────
    for v in cache:
        if v.get('category') != 'Movies':
            continue
        m = meta.get(v['path'], {})
        if m.get('poster_local'):
            continue
        title = m.get('display_title') or m.get('title') or v.get('title') or Path(v['path']).stem
        year  = m.get('year') or ''
        items.append({'type': 'Movies', 'path': v['path'], 'key': v['path'],
                      'title': title, 'year': year})

    # ── TV series without a poster ─────────────────────────────────────────────
    seen_series = set()
    for v in cache:
        if v.get('category') != 'TV Shows':
            continue
        sname = v.get('series', '')
        if not sname or sname in seen_series:
            continue
        seen_series.add(sname)
        if series_posters.get(sname):
            continue
        # Try to get year from any episode metadata
        year = ''
        for ep in cache:
            if ep.get('series') == sname:
                y = meta.get(ep['path'], {}).get('year')
                if y:
                    year = y
                    break
        items.append({'type': 'TV Shows', 'path': '', 'key': sname,
                      'title': sname, 'year': year})

    # Sort: TV series first by title, then movies by title
    items.sort(key=lambda x: (0 if x['type'] == 'TV Shows' else 1, (x['title'] or '').lower()))
    return jsonify({'items': items, 'count': len(items)})


@app.route('/api/fetch_cover_preview', methods=['POST'])
def api_fetch_cover_preview():
    """Search TMDB for a poster and return the preview URL (does NOT save yet)."""
    import urllib.request as ur, urllib.parse
    data  = request.get_json()
    title = (data.get('title') or '').strip()
    year  = str(data.get('year') or '').strip()
    typ   = data.get('type', 'Movies')  # 'Movies' or 'TV Shows'

    cfg   = load_json(DATA_DIR / 'config.json', default={})
    token = cfg.get('tmdb_bearer_token', '')
    if not token:
        return jsonify({'ok': False, 'error': 'no TMDB token'})
    if not title:
        return jsonify({'ok': False, 'error': 'no title'})

    headers = {'Authorization': f'Bearer {token}', 'accept': 'application/json'}

    def tmdb_get(url):
        req = ur.Request(url, headers=headers)
        with ur.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    try:
        if typ == 'Movies':
            q   = urllib.parse.quote(title)
            url = f'https://api.themoviedb.org/3/search/movie?query={q}&language=en-US&page=1'
            if year:
                url += f'&year={year}'
            results = tmdb_get(url).get('results', [])
            if not results and year:
                url2    = f'https://api.themoviedb.org/3/search/movie?query={q}&language=en-US&page=1'
                results = tmdb_get(url2).get('results', [])
            if not results:
                return jsonify({'ok': False, 'error': 'not found'})
            hit         = results[0]
            poster_path = hit.get('poster_path', '')
            tmdb_title  = hit.get('title', title)
            tmdb_year   = (hit.get('release_date') or '')[:4]
        else:
            q   = urllib.parse.quote(title)
            url = f'https://api.themoviedb.org/3/search/tv?query={q}&language=en-US&page=1'
            results = tmdb_get(url).get('results', [])
            if not results:
                return jsonify({'ok': False, 'error': 'not found'})
            hit         = results[0]
            poster_path = hit.get('poster_path', '')
            tmdb_title  = hit.get('name', title)
            tmdb_year   = (hit.get('first_air_date') or '')[:4]

        if not poster_path:
            return jsonify({'ok': False, 'error': 'no poster'})

        img_url = f'https://image.tmdb.org/t/p/w500{poster_path}'
        return jsonify({'ok': True, 'img_url': img_url, 'poster_path': poster_path,
                        'tmdb_title': tmdb_title, 'tmdb_year': tmdb_year})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/api/apply_cover_from_tmdb', methods=['POST'])
def api_apply_cover_from_tmdb():
    """Download a TMDB poster and save it; update metadata/series_posters."""
    import urllib.request as ur
    data        = request.get_json()
    path        = data.get('path', '')       # video file path (movies)
    key         = data.get('key', '')        # series name (TV) or same as path (movies)
    typ         = data.get('type', 'Movies')
    poster_path = data.get('poster_path', '')

    if not poster_path:
        return jsonify({'ok': False, 'error': 'no poster_path'})

    img_url = f'https://image.tmdb.org/t/p/w500{poster_path}'

    try:
        COVERS_DIR.mkdir(exist_ok=True)
        # Build a safe filename
        if typ == 'TV Shows' and key:
            base = key
        elif path:
            base = Path(path).stem
        else:
            base = key or 'cover'
        safe     = re.sub(r'[^\w-]', '_', base).strip('_') + '.jpg'
        out_path = COVERS_DIR / safe
        local_ref = f'covers/{safe}'

        # Download
        with ur.urlopen(img_url, timeout=15) as resp:
            out_path.write_bytes(resp.read())

        # Persist reference
        if typ == 'TV Shows' and key:
            sp      = load_json(SERIES_POSTERS_FILE, default={})
            sp[key] = local_ref
            save_json(SERIES_POSTERS_FILE, sp)
        if path:
            meta = load_json(METADATA_FILE, default={})
            meta.setdefault(path, {})['poster_local'] = local_ref
            save_json(METADATA_FILE, meta)

        return jsonify({'ok': True, 'poster_local': local_ref})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/api/connectivity')
def api_connectivity():
    """Quick internet check — tries a sequence of reliable hosts via socket."""
    import socket, time as _time
    hosts = [
        ('8.8.8.8',              53),   # Google DNS  (UDP-like TCP probe)
        ('1.1.1.1',              53),   # Cloudflare DNS
        ('api.themoviedb.org',  443),   # TMDB directly
    ]
    for host, port in hosts:
        try:
            t0 = _time.time()
            with socket.create_connection((host, port), timeout=3):
                pass
            ms = int((_time.time() - t0) * 1000)
            return jsonify({'online': True, 'latency_ms': ms, 'host': host})
        except OSError:
            continue
    return jsonify({'online': False, 'latency_ms': None, 'host': None})


@app.route('/api/broken_paths')
def api_broken_paths():
    """Scan every cached path and return those that no longer exist on disk."""
    cache = load_json(CACHE_FILE, default=[])
    meta  = load_json(METADATA_FILE, default={})

    broken = []
    for v in cache:
        path = v.get('path', '')
        if not path:
            continue
        if not os.path.exists(path):
            m     = meta.get(path, {})
            title = m.get('display_title') or m.get('title') or v.get('title') or Path(path).stem
            broken.append({
                'path':   path,
                'title':  title,
                'type':   v.get('category', 'Unknown'),
                'series': v.get('series', ''),
                'year':   str(m.get('year', '')),
            })

    broken.sort(key=lambda x: (x['type'], (x['title'] or '').lower()))
    # Detect if a whole drive seems offline (>5 missing from same root)
    from collections import Counter
    drive_counts = Counter(Path(b['path']).drive for b in broken)
    offline_drives = [d for d, n in drive_counts.items() if n >= 5]
    return jsonify({
        'items':          broken,
        'count':          len(broken),
        'total_checked':  len(cache),
        'offline_drives': offline_drives,
    })


@app.route('/api/remove_from_cache', methods=['POST'])
def api_remove_from_cache():
    """Remove one or more paths from the cache and clean up associated data."""
    data  = request.get_json()
    paths = data.get('paths') or ([data['path']] if data.get('path') else [])
    if not paths:
        return jsonify({'ok': False, 'error': 'no paths provided'}), 400

    path_set = set(paths)

    cache = load_json(CACHE_FILE, default=[])
    before = len(cache)
    cache  = [v for v in cache if v.get('path') not in path_set]
    save_json(CACHE_FILE, cache)

    meta = load_json(METADATA_FILE, default={})
    for p in path_set:
        meta.pop(p, None)
    save_json(METADATA_FILE, meta)

    extra = load_json(EXTRA_CATS_FILE, default={})
    for p in path_set:
        extra.pop(p, None)
    save_json(EXTRA_CATS_FILE, extra)

    return jsonify({'ok': True, 'removed': before - len(cache)})


@app.route('/api/update_metadata', methods=['POST'])
def api_update_metadata():
    """Update editable metadata fields for a single file."""
    data = request.get_json()
    path = data.get('path')
    if not path:
        return jsonify({'ok': False, 'error': 'no path'}), 400
    meta = load_json(METADATA_FILE, default={})
    entry = meta.get(path, {})
    # Apply each editable field if present in the payload
    for field in ['display_title', 'rating', 'genre', 'description', 'director']:
        if field in data:
            entry[field] = data[field]
    if 'year' in data:
        entry['year'] = data['year']          # stored as 'year', surfaced as meta_year
    if 'runtime_min' in data:
        entry['runtime_min'] = data['runtime_min']
    if 'cast' in data:
        entry['cast'] = data['cast']          # list of strings
    meta[path] = entry
    save_json(METADATA_FILE, meta)
    return jsonify({'ok': True})


@app.route('/api/set_watched', methods=['POST'])
def api_set_watched():
    """Mark a single file as watched or unwatched."""
    data = request.get_json()
    path    = data.get('path')
    watched = bool(data.get('watched', False))
    if not path:
        return jsonify({'ok': False, 'error': 'no path'}), 400
    meta = load_json(METADATA_FILE, default={})
    meta.setdefault(path, {})['watched'] = watched
    save_json(METADATA_FILE, meta)
    return jsonify({'ok': True, 'watched': watched})


@app.route('/api/export_library_csv')
def api_export_library_csv():
    """Export the full library (cache + metadata) as a downloadable CSV."""
    import csv, io
    cache = load_json(CACHE_FILE, default=[])
    meta  = load_json(METADATA_FILE, default={})
    extra = load_json(EXTRA_CATS_FILE, default={})

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow([
        'Title', 'Display Title', 'Category', 'Series', 'Rating',
        'Year', 'Genre', 'Genres', 'Runtime (min)', 'Director', 'Cast',
        'Description', 'Kid Friendly', 'File Size (MB)', 'Extension',
        'Has Cover', 'File Path',
    ])
    for item in cache:
        path = item.get('path', '')
        m    = meta.get(path, {})
        genres_list = extra.get(path, item.get('genres', []))
        writer.writerow([
            item.get('title', ''),
            m.get('display_title', item.get('display_title', item.get('title', ''))),
            item.get('category', ''),
            item.get('series', ''),
            m.get('rating', item.get('rating', '')),
            m.get('year', item.get('meta_year', '')),
            m.get('genre', item.get('genre', '')),
            ', '.join(genres_list) if isinstance(genres_list, list) else genres_list,
            m.get('runtime_min', item.get('runtime_min', '')),
            m.get('director', item.get('director', '')),
            ', '.join(m['cast']) if isinstance(m.get('cast'), list) else m.get('cast', ''),
            m.get('description', item.get('description', '')),
            'Yes' if item.get('kid_friendly') else 'No',
            item.get('size_mb', ''),
            item.get('ext', ''),
            'Yes' if item.get('poster_local') else 'No',
            path,
        ])
    csv_bytes = output.getvalue().encode('utf-8-sig')  # BOM for Excel compatibility
    return Response(
        csv_bytes,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename="cinevault_library.csv"'},
    )


@app.route('/credits')
def credits_page():
    return Response(CREDITS_HTML.replace('__APP_VERSION__', APP_VERSION), mimetype='text/html')

@app.route('/frogger')
def frogger_page():
    """Serves the standalone Frogger game (also embedded as an iframe in CineVault)."""
    return Response(FROGGER_HTML, mimetype='text/html')

@app.route('/settings')
def settings_page():
    html = SETTINGS_HTML.replace('__APP_VERSION__', APP_VERSION)
    return Response(html, mimetype='text/html')

# ── HTML / CSS / JS ───────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>CineVault</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<script>try{if(localStorage.getItem('mlTheme')==='light')document.documentElement.setAttribute('data-theme','light')}catch(e){}</script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0a0a12;--surface:#13132a;--surface2:#1e1e3a;--border:#2a2a4a;
  --accent:#7c3aed;--accent2:#a855f7;
  --movies:#7c3aed;--tv:#2563eb;--kids:#16a34a;--music:#db2777;--personal:#ea580c;
  --text:#f0f0ff;--muted:#7070a0;
  --nav-bg:rgba(10,10,18,.97);--fbar2-bg:rgba(10,10,18,.93);
}
[data-theme="light"]{
  --bg:#f0f0ec;--surface:#ffffff;--surface2:#e2e2dc;--border:#b0b0a6;
  --text:#1a1a2e;--muted:#58586e;
  --nav-bg:rgba(240,240,236,.97);--fbar2-bg:rgba(240,240,236,.94);
}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh;overflow-x:hidden}

/* NAV */
#nav{position:fixed;top:0;left:0;right:0;z-index:100;background:var(--nav-bg);padding:11px 26px;display:flex;align-items:center;gap:11px;border-bottom:1px solid var(--border);backdrop-filter:blur(10px)}
#logo{font-size:1.25rem;font-weight:800;background:linear-gradient(135deg,var(--accent2),#60a5fa);-webkit-background-clip:text;-webkit-text-fill-color:transparent;white-space:nowrap}
#search-wrap{flex:1;max-width:300px;position:relative}
#search{width:100%;padding:7px 13px 7px 32px;background:var(--surface2);border:1px solid var(--border);border-radius:20px;color:var(--text);font-size:.86rem;outline:none;transition:border-color .2s}
#search:focus{border-color:var(--accent)}
#si{position:absolute;left:10px;top:50%;transform:translateY(-50%);color:var(--muted);font-size:.78rem;pointer-events:none}
#nav-right{display:flex;gap:7px;margin-left:auto;align-items:center;flex-wrap:wrap}
.nbtn{padding:5px 12px;border-radius:16px;font-size:.78rem;font-weight:600;border:1px solid var(--border);background:var(--surface2);color:var(--text);cursor:pointer;transition:all .2s;white-space:nowrap;text-decoration:none;display:inline-flex;align-items:center;gap:5px}
.nbtn:hover{border-color:var(--accent)}
.nbtn.active{background:var(--accent);border-color:var(--accent)}
#conn-pill{display:inline-flex;align-items:center;gap:3px;font-size:.65rem;font-weight:600;padding:2px 8px;border-radius:12px;border:1px solid var(--border);background:var(--surface2);white-space:nowrap;cursor:default}
#conn-dot{font-size:.45rem;line-height:1}
#conn-pill.online{border-color:rgba(74,222,128,.35);background:rgba(74,222,128,.08);color:#4ade80}
#conn-pill.offline{border-color:rgba(248,113,113,.35);background:rgba(248,113,113,.08);color:#f87171}
#kids-btn{border-color:var(--kids);color:var(--kids)}
#kids-btn.active{background:var(--kids);border-color:var(--kids);color:#fff}
#stat{font-size:.73rem;color:var(--muted)}

/* FILTER BAR 1 — category + ratings */
#fbar{position:fixed;top:55px;left:0;right:0;z-index:99;background:var(--nav-bg);padding:6px 22px;display:flex;gap:5px;align-items:center;border-bottom:1px solid var(--border);backdrop-filter:blur(8px);overflow-x:auto}
.cbtn{padding:4px 12px;border-radius:13px;font-size:.75rem;font-weight:600;border:1px solid var(--border);background:transparent;color:var(--muted);cursor:pointer;transition:all .2s;white-space:nowrap}
.cbtn:hover{color:var(--text);border-color:var(--muted)}
.cbtn.active[data-cat="all"]      {background:var(--text);border-color:var(--text);color:var(--bg)}
.cbtn.active[data-cat="Movies"]   {background:var(--movies);border-color:var(--movies);color:#fff}
.cbtn.active[data-cat="TV Shows"] {background:var(--tv);border-color:var(--tv);color:#fff}
.cbtn.active[data-cat="Family"]   {background:#16a34a;border-color:#16a34a;color:#fff}
.cbtn.active[data-cat="Favorites"]{background:#ca8a04;border-color:#ca8a04;color:#fff}
.cbtn.active[data-rating]         {background:var(--accent);border-color:var(--accent);color:#fff}
/* Category chips in modal */
#mcat-editor{margin-bottom:10px;display:none}
#mcat-editor label{font-size:.68rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;display:block;margin-bottom:5px}
#mcat-editor-row{display:flex;flex-wrap:wrap;align-items:center;gap:5px}
.cat-chips{display:flex;flex-wrap:wrap;gap:5px}
.cat-chip{padding:3px 11px;border-radius:11px;font-size:.7rem;font-weight:700;cursor:pointer;border:1px solid;transition:all .15s;user-select:none}
.cat-chip.primary{cursor:default;opacity:.55}
.cat-chip.on{opacity:1}
.cat-chip.off{opacity:.25;filter:grayscale(.5)}
/* Genre badge (assigned genres in modal) */
.genre-badge{display:inline-flex;align-items:center;gap:0;padding:3px 8px 3px 10px;border-radius:11px;font-size:.7rem;font-weight:700;border:1px solid;user-select:none;white-space:nowrap}
.genre-badge .gbx{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;margin-left:4px;border-radius:50%;font-size:.6rem;font-weight:900;cursor:pointer;opacity:0;transition:opacity .15s,background .15s;color:inherit;background:rgba(255,255,255,.08)}
.genre-badge:hover .gbx{opacity:1}
.genre-badge .gbx:hover{background:rgba(255,80,80,.35);color:#ff8080}
/* Add genre dropdown */
#mgenre-add{padding:3px 8px;border-radius:10px;font-size:.7rem;font-weight:600;border:1px solid var(--border);background:var(--surface2);color:var(--muted);cursor:pointer;outline:none;max-width:130px}
#mgenre-add:hover{border-color:var(--accent);color:var(--text)}
#mgenre-add option{background:var(--surface2)}
/* Primary category chips (read-only in modal) */
.cat-chip[data-cat="Movies"]      {background:rgba(124,58,237,.2); color:#c084fc;border-color:rgba(124,58,237,.45)}
.cat-chip[data-cat="TV Shows"]    {background:rgba(37,99,235,.2);  color:#93c5fd;border-color:rgba(37,99,235,.45)}
.cat-chip[data-cat="Music"]       {background:rgba(219,39,119,.2); color:#f9a8d4;border-color:rgba(219,39,119,.45)}
.cat-chip[data-cat="Personal"]    {background:rgba(234,88,12,.2);  color:#fb923c;border-color:rgba(234,88,12,.45)}
/* Genre chips */
.cat-chip[data-cat="Action"]      {background:rgba(220,38,38,.2);  color:#fca5a5;border-color:rgba(220,38,38,.45)}
.cat-chip[data-cat="Adventure"]   {background:rgba(5,150,105,.2);  color:#6ee7b7;border-color:rgba(5,150,105,.45)}
.cat-chip[data-cat="Animation"]   {background:rgba(124,58,237,.2); color:#c084fc;border-color:rgba(124,58,237,.45)}
.cat-chip[data-cat="Comedy"]      {background:rgba(234,179,8,.2);  color:#fde68a;border-color:rgba(234,179,8,.45)}
.cat-chip[data-cat="Crime"]       {background:rgba(107,114,128,.2);color:#d1d5db;border-color:rgba(107,114,128,.45)}
.cat-chip[data-cat="Documentary"] {background:rgba(3,105,161,.2);  color:#7dd3fc;border-color:rgba(3,105,161,.45)}
.cat-chip[data-cat="Drama"]       {background:rgba(79,70,229,.2);  color:#a5b4fc;border-color:rgba(79,70,229,.45)}
.cat-chip[data-cat="Family"]      {background:rgba(22,163,74,.2);  color:#86efac;border-color:rgba(22,163,74,.45)}
.cat-chip[data-cat="Fantasy"]     {background:rgba(168,85,247,.2); color:#d8b4fe;border-color:rgba(168,85,247,.45)}
.cat-chip[data-cat="Holiday"]     {background:rgba(220,38,38,.2);  color:#fca5a5;border-color:rgba(220,38,38,.45)}
.cat-chip[data-cat="Horror"]      {background:rgba(55,65,81,.2);   color:#9ca3af;border-color:rgba(55,65,81,.45)}
.cat-chip[data-cat="Kids"]        {background:rgba(22,163,74,.2);  color:#86efac;border-color:rgba(22,163,74,.45)}
.cat-chip[data-cat="Musical"]     {background:rgba(219,39,119,.2); color:#f9a8d4;border-color:rgba(219,39,119,.45)}
.cat-chip[data-cat="Mystery"]     {background:rgba(55,65,81,.2);   color:#9ca3af;border-color:rgba(55,65,81,.45)}
.cat-chip[data-cat="Romance"]     {background:rgba(236,72,153,.2); color:#fbcfe8;border-color:rgba(236,72,153,.45)}
.cat-chip[data-cat="Sci-Fi"]      {background:rgba(6,182,212,.2);  color:#67e8f9;border-color:rgba(6,182,212,.45)}
.cat-chip[data-cat="Thriller"]    {background:rgba(234,88,12,.2);  color:#fdba74;border-color:rgba(234,88,12,.45)}
.cat-chip[data-cat="Faith"]       {background:rgba(146,64,14,.2);  color:#fcd34d;border-color:rgba(146,64,14,.45)}
.cat-chip[data-cat="Fitness"]     {background:rgba(234,88,12,.2);  color:#fdba74;border-color:rgba(234,88,12,.45)}
.cat-chip[data-cat="Favorites"]   {background:rgba(202,138,4,.2);  color:#fde68a;border-color:rgba(202,138,4,.45)}
/* Favorites star button on cards */
.fav-btn{position:absolute;top:6px;left:6px;z-index:3;background:rgba(0,0,0,.55);border:none;border-radius:50%;width:26px;height:26px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:rgba(255,255,255,.45);font-size:.75rem;transition:all .18s;padding:0}
.fav-btn:hover{background:rgba(0,0,0,.75);color:#fbbf24}
.fav-btn.active{color:#fbbf24;background:rgba(0,0,0,.65)}
/* Watched check button on cards */
.watch-btn{position:absolute;top:6px;right:6px;z-index:3;background:rgba(0,0,0,.55);border:none;border-radius:50%;width:26px;height:26px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:rgba(255,255,255,.35);font-size:.72rem;transition:all .18s;padding:0;opacity:0}
.card:hover .watch-btn{opacity:1}
.watch-btn:hover{background:rgba(0,0,0,.75);color:#4ade80}
.watch-btn.watched{color:#4ade80;background:rgba(0,0,0,.65);opacity:1}
/* Watched ribbon in corner of poster */
.watched-ribbon{position:absolute;top:6px;right:6px;z-index:2;width:22px;height:22px;background:#16a34a;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:.65rem;color:#fff;box-shadow:0 1px 4px rgba(0,0,0,.5);pointer-events:none}
.card:hover .watched-ribbon{opacity:0}
/* Watch filter buttons active state */
.cbtn.active[data-watched="watched"]  {background:#16a34a;border-color:#16a34a;color:#fff}
.cbtn.active[data-watched="unwatched"]{background:#2563eb;border-color:#2563eb;color:#fff}
.edit-card-btn{position:absolute;bottom:7px;right:7px;z-index:3;background:rgba(0,0,0,.52);border:1px solid rgba(255,255,255,.1);border-radius:6px;width:26px;height:26px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:rgba(255,255,255,.4);font-size:.62rem;padding:0;opacity:0;transition:opacity .18s,color .18s,background .18s,border-color .18s}
.card:hover .edit-card-btn{opacity:1}
.edit-card-btn:hover{color:#fff;background:var(--accent);border-color:transparent}
[data-theme="light"] .edit-card-btn{background:rgba(0,0,0,.32);border-color:rgba(0,0,0,.15)}
/* ── Edit metadata modal ──────────────────────────────────────────────────── */
#edit-modal{display:none;position:fixed;inset:0;z-index:800;background:rgba(0,0,0,.7);backdrop-filter:blur(6px);align-items:center;justify-content:center;padding:16px}
#edit-modal.open{display:flex}
#edit-sheet{background:var(--surface);border:1px solid var(--border);border-radius:16px;width:min(620px,100%);max-height:calc(100vh - 32px);overflow-y:auto;box-shadow:0 24px 80px rgba(0,0,0,.55);display:flex;flex-direction:column}
.ef-header{padding:16px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px;flex-shrink:0}
.ef-header-icon{width:34px;height:34px;border-radius:8px;background:var(--accent);display:flex;align-items:center;justify-content:center;color:#fff;font-size:.85rem;flex-shrink:0}
.ef-title{font-weight:700;font-size:.95rem;color:var(--text);line-height:1.2}
.ef-subtitle{font-size:.72rem;color:var(--muted);margin-top:2px;word-break:break-all;display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden}
.ef-body{padding:18px 20px;display:grid;grid-template-columns:100px 1fr;gap:18px;flex:1}
.ef-poster{width:100px;flex-shrink:0}
.ef-poster img{width:100px;border-radius:8px;display:block}
.ef-poster-ph{width:100px;height:142px;background:var(--surface2);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:2.2rem;border:1px solid var(--border)}
.ef-fields{display:flex;flex-direction:column;gap:11px}
.ef-row{display:grid;gap:10px}
.ef-row-3{grid-template-columns:1fr 1fr 1fr}
.ef-row-2{grid-template-columns:1fr 1fr}
.ef-group label{display:block;font-size:.68rem;color:var(--muted);letter-spacing:.06em;text-transform:uppercase;margin-bottom:4px;font-weight:600}
.ef-group input,.ef-group select,.ef-group textarea{width:100%;box-sizing:border-box;background:var(--surface2);border:1px solid var(--border);border-radius:7px;padding:7px 10px;color:var(--text);font-size:.875rem;font-family:inherit;transition:border-color .15s,box-shadow .15s;outline:none}
.ef-group input:focus,.ef-group select:focus,.ef-group textarea:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(124,58,237,.18)}
.ef-group textarea{resize:vertical;min-height:72px;line-height:1.5}
.ef-group select option{background:var(--surface)}
.ef-footer{padding:14px 20px;border-top:1px solid var(--border);display:flex;align-items:center;justify-content:flex-end;gap:10px;flex-shrink:0}
.ef-btn-cancel{background:transparent;border:1px solid var(--border);color:var(--muted);padding:8px 18px;border-radius:8px;cursor:pointer;font-size:.85rem;transition:border-color .15s,color .15s}
.ef-btn-cancel:hover{border-color:var(--text);color:var(--text)}
.ef-btn-save{background:var(--accent);border:none;color:#fff;padding:8px 24px;border-radius:8px;cursor:pointer;font-size:.85rem;font-weight:700;transition:opacity .15s}
.ef-btn-save:hover{opacity:.88}
.ef-btn-save:disabled{opacity:.5;cursor:default}
#fbar-right{display:flex;align-items:center;gap:7px;margin-left:auto;flex-shrink:0}
#fcount{font-size:.73rem;color:var(--muted);white-space:nowrap}
#sort-sel{padding:4px 8px;border-radius:10px;font-size:.74rem;font-weight:600;border:1px solid var(--border);background:var(--surface2);color:var(--text);cursor:pointer;outline:none}
#sort-sel:hover{border-color:var(--accent)}

/* ── SERIES PANEL — two-column layout ───────────────────────────────────────── */
/* left sidebar */
#sp-left{width:272px;flex-shrink:0;overflow-y:auto;border-right:1px solid var(--border);background:var(--surface);padding:20px 18px 40px;display:flex;flex-direction:column;gap:14px}
#sp-poster{width:100%;aspect-ratio:2/3;border-radius:10px;overflow:hidden;background:var(--surface2);border:1px solid var(--border);display:flex;align-items:center;justify-content:center;font-size:3rem;flex-shrink:0}
#sp-poster img{width:100%;height:100%;object-fit:cover;display:block}
#sp-left-title{font-size:1.15rem;font-weight:800;line-height:1.3;color:var(--text)}
#sp-left-badges{display:flex;flex-wrap:wrap;gap:5px;align-items:center}
#sp-left-desc{font-size:.78rem;color:var(--muted);line-height:1.6;display:none}
#sp-left-cast{font-size:.75rem;color:var(--muted);line-height:1.6;display:none}
#sp-left-cast b{color:var(--text)}
#sp-left-genres{display:none}
#sp-left-genres label{font-size:.65rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;display:block;margin-bottom:5px}
#sp-genre-chips{display:flex;flex-wrap:wrap;gap:4px}
#sp-left-actions{display:flex;flex-direction:column;gap:7px;margin-top:2px}
.sp-action-btn{padding:7px 12px;border-radius:9px;font-size:.76rem;font-weight:600;border:1px solid var(--border);background:var(--surface2);color:var(--text);cursor:pointer;transition:all .18s;display:flex;align-items:center;gap:6px;width:100%}
.sp-action-btn:hover{border-color:var(--accent);color:var(--accent)}
.sp-fav-btn{border-color:rgba(202,138,4,.4);color:#ca8a04}
.sp-fav-btn:hover{background:rgba(202,138,4,.1);border-color:#ca8a04;color:#ca8a04}
.sp-fav-btn.active{background:rgba(202,138,4,.15);border-color:#ca8a04;color:#ca8a04}
/* right column */
#sp-right{flex:1;min-width:0;display:flex;flex-direction:column;overflow:hidden}
#sp-seasons{padding:9px 18px 0;display:flex;gap:6px;overflow-x:auto;flex-wrap:nowrap;border-bottom:1px solid var(--border);background:var(--bg);flex-shrink:0}
#sp-episodes{flex:1;overflow-y:auto;padding:14px 18px 60px}
#sp-episodes-inner{max-width:820px}

/* FILTER BAR 2 — genre */
#fbar2{position:fixed;top:97px;left:0;right:0;z-index:98;background:var(--fbar2-bg);padding:5px 22px;display:flex;gap:5px;align-items:center;border-bottom:1px solid var(--border);backdrop-filter:blur(6px);overflow-x:auto}
.gbtn{padding:3px 11px;border-radius:11px;font-size:.71rem;font-weight:600;border:1px solid var(--border);background:transparent;color:var(--muted);cursor:pointer;transition:all .2s;white-space:nowrap}
.gbtn:hover{color:var(--text);border-color:var(--muted)}
.gbtn.active{background:linear-gradient(135deg,#6d28d9,#7c3aed);border-color:#7c3aed;color:#fff}

/* MAIN */
#main{padding:158px 26px 60px}
.section{margin-bottom:40px}
.sec-head{display:flex;align-items:center;gap:9px;margin-bottom:13px}
.sec-title{font-size:1.1rem;font-weight:700}
.sec-count{font-size:.73rem;color:var(--muted);background:var(--surface2);padding:2px 8px;border-radius:9px;border:1px solid var(--border)}
.sec-line{flex:1;height:1px;background:var(--border)}

/* SERIES SUB-GROUP */
.series-group{margin-bottom:24px}
.series-label{font-size:.82rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;border-left:3px solid var(--tv);padding-left:8px;margin-bottom:9px}

/* GRID */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:13px}

/* CARD */
.card{background:var(--surface);border-radius:10px;overflow:hidden;cursor:pointer;border:1px solid var(--border);transition:transform .2s,box-shadow .2s,border-color .2s;position:relative}
.card:hover{transform:translateY(-4px) scale(1.02);box-shadow:0 12px 32px rgba(124,58,237,.25);border-color:var(--accent)}
.poster{height:200px;display:flex;align-items:center;justify-content:center;font-size:2.6rem;position:relative;overflow:hidden}
.poster::after{content:'';position:absolute;inset:0;background:linear-gradient(to bottom,transparent 40%,rgba(0,0,0,.55))}
.poster img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:0}
.poster img~*{z-index:1}
.card[data-cat="Movies"]  .poster{background:linear-gradient(135deg,#3b1f6e,#7c3aed)}
.card[data-cat="TV Shows"].poster{background:linear-gradient(135deg,#1e3a7c,#2563eb)}
.card[data-cat="Kids"]    .poster{background:linear-gradient(135deg,#14532d,#16a34a)}
.card[data-cat="Music"]   .poster{background:linear-gradient(135deg,#831843,#db2777)}
.card[data-cat="Personal"].poster{background:linear-gradient(135deg,#7c3a1e,#ea580c)}
.play-ov{position:absolute;inset:0;z-index:2;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.5);opacity:0;transition:opacity .2s}
.card:hover .play-ov{opacity:1}
.play-circle{width:46px;height:46px;border-radius:50%;background:rgba(255,255,255,.9);display:flex;align-items:center;justify-content:center;font-size:1rem;color:#111}
.kid-pin{position:absolute;top:6px;right:6px;z-index:3;background:var(--kids);color:#fff;font-size:.56rem;font-weight:800;padding:2px 5px;border-radius:5px;text-transform:uppercase}
.cbody{padding:8px 10px 10px}
.ctitle{font-size:.8rem;font-weight:600;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;margin-bottom:6px}
.cmeta{display:flex;align-items:center;gap:4px;flex-wrap:wrap}
.badge{font-size:.6rem;font-weight:700;padding:1px 6px;border-radius:5px;text-transform:uppercase;letter-spacing:.3px}
.b-movies  {background:rgba(124,58,237,.2);color:#c084fc;border:1px solid rgba(124,58,237,.35)}
.b-tv      {background:rgba(37,99,235,.2); color:#93c5fd;border:1px solid rgba(37,99,235,.35)}
.b-kids    {background:rgba(22,163,74,.2); color:#86efac;border:1px solid rgba(22,163,74,.35)}
.b-music   {background:rgba(219,39,119,.2);color:#f9a8d4;border:1px solid rgba(219,39,119,.35)}
.b-personal{background:rgba(234,88,12,.2); color:#fb923c;border:1px solid rgba(234,88,12,.35)}
.b-size,.b-dur{color:var(--muted);font-size:.68rem}
.b-ext{background:rgba(255,255,255,.06);color:var(--muted);border:1px solid var(--border);font-size:.6rem;padding:1px 5px;border-radius:4px}
.b-genre{color:#a78bfa;font-size:.65rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100px}
.b-rating{font-size:.6rem;font-weight:800;padding:1px 5px;border-radius:4px;text-transform:uppercase;letter-spacing:.3px}
.b-G{background:rgba(22,163,74,.2);color:#86efac;border:1px solid rgba(22,163,74,.4)}
.b-PG{background:rgba(59,130,246,.2);color:#93c5fd;border:1px solid rgba(59,130,246,.4)}
.b-PG13{background:rgba(234,179,8,.2);color:#fde68a;border:1px solid rgba(234,179,8,.4)}
.b-R{background:rgba(239,68,68,.2);color:#fca5a5;border:1px solid rgba(239,68,68,.4)}
.b-NR,.b-nr{background:rgba(107,114,128,.15);color:var(--muted);border:1px solid var(--border)}
#mdesc{font-size:.82rem;color:var(--muted);line-height:1.55;margin:4px 0 8px;font-style:italic}
#mcast{font-size:.75rem;color:var(--muted);margin-bottom:8px}
#mcast b{color:var(--accent2)}

/* LOADING */
#loading-screen{position:fixed;inset:0;z-index:200;background:var(--bg);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px}
.spinner{width:42px;height:42px;border-radius:50%;border:4px solid var(--border);border-top-color:var(--accent);animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes popIn{0%{opacity:0;transform:scale(.4) translateY(20px)}60%{transform:scale(1.15) translateY(-4px)}100%{opacity:1;transform:scale(1) translateY(0)}}
@keyframes spinSlow{to{transform:rotate(360deg)}}
@keyframes floatUp{0%{opacity:0;transform:translateY(0) scale(.7)}15%{opacity:1}85%{opacity:.9}100%{opacity:0;transform:translateY(-110vh) scale(1.1)}}
@keyframes shimmerGold{0%,100%{text-shadow:0 0 18px #ffd700,0 0 40px #ff8c00}50%{text-shadow:0 0 30px #ffe566,0 0 60px #ffd700,0 0 90px #ff8c00}}
@keyframes glowSaber{0%,100%{box-shadow:0 0 12px #00bfff,0 0 28px #00bfff}50%{box-shadow:0 0 22px #7df9ff,0 0 50px #00bfff}}
@keyframes heartbeat{0%,100%{transform:scale(1)}14%{transform:scale(1.15)}28%{transform:scale(1)}}
@keyframes pawBounce{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
#load-msg{color:var(--muted);font-size:.86rem;text-align:center;max-width:320px}
#load-logo{font-size:1.7rem;font-weight:800;background:linear-gradient(135deg,var(--accent2),#60a5fa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}

/* EMPTY */
#empty{display:none;flex-direction:column;align-items:center;gap:12px;padding:80px 20px;text-align:center}
#empty i{font-size:3.2rem;color:var(--muted)}
.sbtn{padding:8px 20px;border-radius:20px;background:var(--accent);border:none;color:#fff;font-size:.86rem;font-weight:700;cursor:pointer;transition:background .2s}
.sbtn:hover{background:var(--accent2)}
.sbtn.sec{background:var(--surface2);border:1px solid var(--border);color:var(--text)}
.sbtn.sec:hover{background:var(--surface)}

/* CONFIRM DIALOG */
#confirm-overlay,#pin-overlay{display:none;position:fixed;inset:0;z-index:500;background:rgba(0,0,0,.87);backdrop-filter:blur(6px);align-items:center;justify-content:center;padding:20px}
#confirm-overlay.open,#pin-overlay.open{display:flex}
.dialog-box{background:var(--surface);border:1px solid var(--border);border-radius:13px;padding:28px 28px 22px;width:100%;max-width:360px;box-shadow:0 24px 80px rgba(0,0,0,.7);text-align:center}
.dialog-icon{font-size:2rem;margin-bottom:12px}
.dialog-title{font-size:1rem;font-weight:700;margin-bottom:8px}
.dialog-msg{font-size:.82rem;color:var(--muted);line-height:1.5;margin-bottom:20px}
.dialog-actions{display:flex;gap:9px;justify-content:center}
.dbtn-cancel{padding:8px 22px;border-radius:20px;background:var(--surface2);border:1px solid var(--border);color:var(--text);font-size:.86rem;font-weight:600;cursor:pointer}
.dbtn-cancel:hover{background:var(--border)}
.dbtn-confirm{padding:8px 22px;border-radius:20px;background:#dc2626;border:none;color:#fff;font-size:.86rem;font-weight:700;cursor:pointer}
.dbtn-confirm:hover{background:#ef4444}
/* PIN DIALOG */
.pin-dots{display:flex;justify-content:center;gap:12px;margin:16px 0 8px}
.pin-dot{width:14px;height:14px;border-radius:50%;background:var(--border);transition:background .15s}
.pin-dot.filled{background:var(--accent)}
.pin-dot.error{background:#dc2626}
.pin-pad{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:16px}
.pin-key{padding:14px;border-radius:10px;background:var(--surface2);border:1px solid var(--border);color:var(--text);font-size:1.1rem;font-weight:700;cursor:pointer;transition:background .15s}
.pin-key:hover{background:var(--border)}
.pin-key:active{background:var(--accent);color:#fff}
.pin-error{font-size:.78rem;color:#f87171;min-height:1.1em;margin-top:4px}

/* MODAL */
#moverlay{display:none;position:fixed;inset:0;z-index:300;background:rgba(0,0,0,.87);backdrop-filter:blur(6px);align-items:center;justify-content:center;padding:20px}
#moverlay.open{display:flex}
#modal{background:var(--surface);border:1px solid var(--border);border-radius:13px;overflow:hidden;width:100%;max-width:560px;box-shadow:0 24px 80px rgba(0,0,0,.7);max-height:90vh;display:flex;flex-direction:column}
#mplayer{position:relative;height:260px;display:flex;align-items:center;justify-content:center;overflow:hidden;cursor:pointer;background:#000}
#mplayer:hover #mplay-btn{transform:scale(1.08)}
#mposter-bg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:brightness(.45)}
#mposter-gradient{position:absolute;inset:0;background:linear-gradient(to bottom,rgba(0,0,0,.1),rgba(0,0,0,.6))}
#mplay-btn{position:relative;z-index:2;display:flex;flex-direction:column;align-items:center;gap:10px;transition:transform .2s}
#mplay-circle{width:80px;height:80px;border-radius:50%;background:rgba(255,255,255,.95);display:flex;align-items:center;justify-content:center;box-shadow:0 8px 32px rgba(0,0,0,.5)}
#mplay-circle i{font-size:2rem;color:#111;margin-left:6px}
#mplay-label{color:#fff;font-size:.85rem;font-weight:700;letter-spacing:.5px;text-shadow:0 1px 4px rgba(0,0,0,.8)}
#mclose{position:absolute;top:9px;right:11px;z-index:10;background:rgba(0,0,0,.6);border:1px solid rgba(255,255,255,.15);color:#fff;width:28px;height:28px;border-radius:50%;font-size:.85rem;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .2s}
#mclose:hover{background:rgba(255,255,255,.15)}
#mbody{padding:16px 20px;overflow-y:auto}
#mtitle{font-size:1.15rem;font-weight:700;margin-bottom:4px}
#mseries{font-size:.8rem;color:var(--muted);margin-bottom:7px}
#mmeta{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:9px}
#mpath{font-size:.68rem;color:var(--muted);word-break:break-all;margin-bottom:13px;font-family:monospace}
#mactions{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
#kid-wrap{display:flex;align-items:center;gap:7px;margin-left:auto}
#kid-wrap label{font-size:.8rem;cursor:pointer;user-select:none}
.toggle{position:relative;width:36px;height:19px;cursor:pointer}
.toggle input{opacity:0;width:0;height:0}
.tsl{position:absolute;inset:0;background:var(--border);border-radius:19px;transition:background .2s}
.tsl::before{content:'';position:absolute;width:13px;height:13px;border-radius:50%;background:#fff;top:3px;left:3px;transition:transform .2s}
.toggle input:checked+.tsl{background:var(--kids)}
.toggle input:checked+.tsl::before{transform:translateX(17px)}

/* TOAST */
#toast{position:fixed;bottom:20px;right:20px;z-index:500;background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:10px 15px;font-size:.81rem;box-shadow:0 8px 24px rgba(0,0,0,.4);opacity:0;transform:translateY(6px);pointer-events:none;transition:opacity .3s,transform .3s}
#scroll-top-btn{position:fixed;bottom:72px;right:22px;z-index:499;width:38px;height:38px;border-radius:50%;background:var(--surface2);border:1px solid var(--border);color:var(--muted);font-size:.85rem;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 14px rgba(0,0,0,.35);opacity:0;transform:translateY(10px);pointer-events:none;transition:opacity .25s,transform .25s,border-color .2s,color .2s}
#scroll-top-btn.visible{opacity:1;transform:translateY(0);pointer-events:auto}
#scroll-top-btn:hover{border-color:var(--accent);color:var(--accent)}
#toast.show{opacity:1;transform:translateY(0)}
::-webkit-scrollbar{width:5px}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}

/* ── LIGHT MODE OVERRIDES ───────────────────────────────────────────────────── */
/* Badge text colors that were too pale for a light background */
[data-theme="light"] .b-movies  {background:rgba(124,58,237,.12);color:#6d28d9;border-color:rgba(124,58,237,.35)}
[data-theme="light"] .b-tv      {background:rgba(37,99,235,.12); color:#1d4ed8;border-color:rgba(37,99,235,.35)}
[data-theme="light"] .b-kids    {background:rgba(22,163,74,.12); color:#15803d;border-color:rgba(22,163,74,.35)}
[data-theme="light"] .b-music   {background:rgba(219,39,119,.12);color:#be185d;border-color:rgba(219,39,119,.35)}
[data-theme="light"] .b-personal{background:rgba(234,88,12,.12); color:#c2410c;border-color:rgba(234,88,12,.35)}
[data-theme="light"] .b-G       {background:rgba(22,163,74,.1);  color:#15803d;border-color:rgba(22,163,74,.4)}
[data-theme="light"] .b-PG      {background:rgba(59,130,246,.1); color:#1d4ed8;border-color:rgba(59,130,246,.4)}
[data-theme="light"] .b-PG13    {background:rgba(234,179,8,.1);  color:#a16207;border-color:rgba(234,179,8,.4)}
[data-theme="light"] .b-R       {background:rgba(239,68,68,.1);  color:#b91c1c;border-color:rgba(239,68,68,.4)}
[data-theme="light"] .b-NR,[data-theme="light"] .b-nr{color:var(--muted)}
[data-theme="light"] .b-genre   {color:#6d28d9}
[data-theme="light"] .b-dur,[data-theme="light"] .b-size{color:var(--muted)}
/* Genre chips — darken text so it's readable on light surfaces */
[data-theme="light"] .cat-chip[data-cat="Movies"]     {background:rgba(124,58,237,.1); color:#6d28d9;border-color:rgba(124,58,237,.35)}
[data-theme="light"] .cat-chip[data-cat="TV Shows"]   {background:rgba(37,99,235,.1);  color:#1d4ed8;border-color:rgba(37,99,235,.35)}
[data-theme="light"] .cat-chip[data-cat="Action"]     {background:rgba(220,38,38,.1);  color:#b91c1c;border-color:rgba(220,38,38,.35)}
[data-theme="light"] .cat-chip[data-cat="Adventure"]  {background:rgba(5,150,105,.1);  color:#065f46;border-color:rgba(5,150,105,.35)}
[data-theme="light"] .cat-chip[data-cat="Animation"]  {background:rgba(124,58,237,.1); color:#6d28d9;border-color:rgba(124,58,237,.35)}
[data-theme="light"] .cat-chip[data-cat="Comedy"]     {background:rgba(234,179,8,.1);  color:#a16207;border-color:rgba(234,179,8,.35)}
[data-theme="light"] .cat-chip[data-cat="Documentary"]{background:rgba(3,105,161,.1);  color:#0c4a6e;border-color:rgba(3,105,161,.35)}
[data-theme="light"] .cat-chip[data-cat="Drama"]      {background:rgba(79,70,229,.1);  color:#4338ca;border-color:rgba(79,70,229,.35)}
[data-theme="light"] .cat-chip[data-cat="Faith"]      {background:rgba(146,64,14,.1);  color:#92400e;border-color:rgba(146,64,14,.35)}
[data-theme="light"] .cat-chip[data-cat="Family"]     {background:rgba(22,163,74,.1);  color:#15803d;border-color:rgba(22,163,74,.35)}
[data-theme="light"] .cat-chip[data-cat="Fantasy"]    {background:rgba(168,85,247,.1); color:#7e22ce;border-color:rgba(168,85,247,.35)}
[data-theme="light"] .cat-chip[data-cat="Holiday"]    {background:rgba(220,38,38,.1);  color:#b91c1c;border-color:rgba(220,38,38,.35)}
[data-theme="light"] .cat-chip[data-cat="Kids"]       {background:rgba(22,163,74,.1);  color:#15803d;border-color:rgba(22,163,74,.35)}
[data-theme="light"] .cat-chip[data-cat="Musical"]    {background:rgba(219,39,119,.1); color:#be185d;border-color:rgba(219,39,119,.35)}
[data-theme="light"] .cat-chip[data-cat="Romance"]    {background:rgba(236,72,153,.1); color:#9d174d;border-color:rgba(236,72,153,.35)}
[data-theme="light"] .cat-chip[data-cat="Sci-Fi"]     {background:rgba(6,182,212,.1);  color:#0e7490;border-color:rgba(6,182,212,.35)}
[data-theme="light"] .cat-chip[data-cat="Favorites"]  {background:rgba(202,138,4,.1);  color:#a16207;border-color:rgba(202,138,4,.35)}
/* Card hover shadow lighter in light mode */
[data-theme="light"] .card:hover{box-shadow:0 8px 24px rgba(124,58,237,.15)}
/* Season tab active in light mode */
[data-theme="light"] .season-tab.active{background:var(--accent);color:#fff}

/* ── SERIES PANEL ───────────────────────────────────────────────────────────── */
#series-panel{display:none;position:fixed;inset:0;z-index:150;background:var(--bg);flex-direction:column}
#series-panel.open{display:flex}
#sp-header{background:var(--nav-bg);border-bottom:1px solid var(--border);padding:10px 18px;display:flex;align-items:center;gap:11px;z-index:10;backdrop-filter:blur(10px);flex-shrink:0}
#sp-back{background:transparent;border:1px solid var(--border);color:var(--muted);padding:5px 13px;border-radius:16px;cursor:pointer;font-size:.79rem;font-weight:600;transition:all .2s;flex-shrink:0;white-space:nowrap}
#sp-back:hover{color:var(--text);border-color:var(--muted)}
#sp-title{font-size:1rem;font-weight:800;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted)}
#sp-body{display:flex;flex:1;overflow:hidden}
#sp-epcount{font-size:.72rem;color:var(--muted);background:var(--surface2);padding:2px 8px;border-radius:9px;border:1px solid var(--border);white-space:nowrap;flex-shrink:0}
.season-tab{padding:6px 15px;border-radius:16px 16px 0 0;border:1px solid var(--border);border-bottom:none;background:transparent;color:var(--muted);cursor:pointer;font-size:.79rem;font-weight:600;white-space:nowrap;transition:all .2s;margin-bottom:-1px}
.season-tab:hover{color:var(--text);border-color:var(--muted)}
.season-tab.active{background:var(--tv);border-color:var(--tv);color:#fff}
.ep-row{display:flex;align-items:center;gap:13px;padding:10px 12px;border-radius:9px;border:1px solid transparent;cursor:pointer;transition:background .15s,border-color .15s;margin-bottom:4px}
.ep-row:hover{background:var(--surface);border-color:var(--border)}
.ep-thumb{width:70px;height:44px;border-radius:6px;background:linear-gradient(135deg,var(--surface2),var(--surface));display:flex;align-items:center;justify-content:center;font-size:1.25rem;flex-shrink:0;border:1px solid var(--border)}
.ep-info{flex:1;min-width:0}
.ep-title-row{display:flex;align-items:center;gap:6px;margin-bottom:3px;overflow:hidden}
.ep-num{font-size:.68rem;font-weight:800;color:var(--tv);font-variant-numeric:tabular-nums;white-space:nowrap;flex-shrink:0}
.ep-title{font-size:.86rem;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ep-meta-row{display:flex;align-items:center;gap:10px;font-size:.7rem;color:var(--muted)}
.ep-play{width:32px;height:32px;border-radius:50%;background:var(--surface2);border:1px solid var(--border);display:flex;align-items:center;justify-content:center;color:var(--muted);flex-shrink:0;transition:all .2s}
.ep-row:hover .ep-play{background:var(--accent);border-color:var(--accent);color:#fff}
/* Series card overlays */
.series-ep-badge{position:absolute;bottom:6px;right:6px;z-index:3;background:rgba(0,0,0,.72);color:#fff;font-size:.62rem;font-weight:700;padding:2px 7px;border-radius:6px;pointer-events:none}
.series-chevron{position:absolute;inset:0;z-index:2;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.45);opacity:0;transition:opacity .2s}
.card.series-card:hover .series-chevron{opacity:1}
.series-chevron-circle{width:40px;height:40px;border-radius:50%;background:rgba(255,255,255,.9);display:flex;align-items:center;justify-content:center;font-size:1rem;color:#111}
</style>
</head>
<body>

<div id="loading-screen">
  <div id="load-logo">🎬 CineVault</div>
  <div class="spinner"></div>
  <div id="load-msg">Loading your media library…</div>
</div>

<nav id="nav">
  <div id="logo" onclick="logoClick()" style="cursor:pointer;user-select:none">🎬 CineVault</div>
  <div id="search-wrap">
    <i class="fas fa-search" id="si"></i>
    <input id="search" type="text" placeholder="Search titles, series…" autocomplete="off">
  </div>
  <div id="nav-right">
    <span id="stat"></span>
    <button class="nbtn" id="kids-btn" onclick="toggleKids()"><i class="fas fa-child"></i> Kid Mode</button>

    <button class="nbtn" id="theme-btn" onclick="toggleTheme()" title="Toggle light / dark mode"><i class="fas fa-moon"></i></button>
    <a class="nbtn" id="settings-btn" href="/settings" title="Settings"><i class="fas fa-cog"></i></a>
    <span id="conn-pill" title="Checking internet…" style="display:none">
      <span id="conn-dot">●</span><span id="conn-lbl"></span>
    </span>
  </div>
</nav>

<div id="fbar">
  <button class="cbtn active" data-cat="all"       onclick="setCat('all')">All</button>
  <button class="cbtn"        data-cat="Movies"    onclick="setCat('Movies')">🎬 Movies</button>
  <button class="cbtn"        data-cat="TV Shows"  onclick="setCat('TV Shows')">📺 TV Shows</button>
  <button class="cbtn"        data-cat="Favorites" onclick="setCat('Favorites')">⭐ Favorites</button>
  <div style="width:1px;height:20px;background:var(--border);margin:0 3px;flex-shrink:0"></div>
  <button class="cbtn" data-watched="watched"   onclick="setWatchedFilter('watched')"  title="Show only watched titles">✓ Watched</button>
  <button class="cbtn" data-watched="unwatched" onclick="setWatchedFilter('unwatched')" title="Show only unwatched titles">○ Unwatched</button>
  <div style="width:1px;height:20px;background:var(--border);margin:0 3px;flex-shrink:0"></div>
  <button class="cbtn" data-rating="G"     onclick="toggleRating('G')"     title="Rated G">G</button>
  <button class="cbtn" data-rating="PG"    onclick="toggleRating('PG')"    title="Rated PG">PG</button>
  <button class="cbtn" data-rating="PG-13" onclick="toggleRating('PG-13')" title="Rated PG-13">PG-13</button>
  <button class="cbtn" data-rating="R"     onclick="toggleRating('R')"     title="Rated R">R</button>
  <button class="cbtn" data-rating="NR"    onclick="toggleRating('NR')"    title="Not Rated">NR</button>
  <div id="fbar-right">
    <select id="sort-sel" onchange="setSort(this.value)" title="Sort order">
      <option value="az">A → Z</option>
      <option value="za">Z → A</option>
      <option value="newest">Year: Newest</option>
      <option value="oldest">Year: Oldest</option>
      <option value="size">Largest File</option>
      <option value="length">Video Length</option>
      <option value="rating">Rating: High → Low</option>
    </select>
    <span id="fcount"></span>
  </div>
</div>

<div id="fbar2">
  <button class="gbtn active" data-genre="all"          onclick="setGenre('all')">All Genres</button>
  <button class="gbtn" data-genre="Action"              onclick="setGenre('Action')">⚔️ Action</button>
  <button class="gbtn" data-genre="Adventure"           onclick="setGenre('Adventure')">🗺️ Adventure</button>
  <button class="gbtn" data-genre="Animation"           onclick="setGenre('Animation')">✏️ Animation</button>
  <button class="gbtn" data-genre="Comedy"              onclick="setGenre('Comedy')">😂 Comedy</button>
  <button class="gbtn" data-genre="Documentary"         onclick="setGenre('Documentary')">🔬 Documentary</button>
  <button class="gbtn" data-genre="Drama"               onclick="setGenre('Drama')">🎭 Drama</button>
  <button class="gbtn" data-genre="Faith"               onclick="setGenre('Faith')">✝️ Faith</button>
  <button class="gbtn" data-genre="Family"              onclick="setGenre('Family')">👨‍👩‍👧 Family</button>
  <button class="gbtn" data-genre="Fantasy"             onclick="setGenre('Fantasy')">🧙 Fantasy</button>
  <button class="gbtn" data-genre="Holiday"             onclick="setGenre('Holiday')">🎄 Holiday</button>
  <button class="gbtn" data-genre="Musical"             onclick="setGenre('Musical')">🎵 Musical</button>
  <button class="gbtn" data-genre="Romance"             onclick="setGenre('Romance')">💕 Romance</button>
  <button class="gbtn" data-genre="Sci-Fi"              onclick="setGenre('Sci-Fi')">🚀 Sci-Fi</button>
</div>

<main id="main">
  <div id="empty">
    <i class="fas fa-film"></i>
    <h2 style="color:var(--muted);font-weight:500;font-size:1.1rem">No videos loaded yet</h2>
  </div>
  <div id="content"></div>
</main>

<!-- Modal -->
<div id="moverlay" onclick="closeModal(event)">
  <div id="modal">
    <div id="mplayer" onclick="openInPlayer()">
      <button id="mclose" onclick="event.stopPropagation();closeModal()"><i class="fas fa-times"></i></button>
      <img id="mposter-bg" src="" alt="" onerror="this.style.display='none'">
      <div id="mposter-gradient"></div>
      <div id="mplay-btn">
        <div id="mplay-circle"><i class="fas fa-play"></i></div>
        <span id="mplay-label">Play in Windows Media Player</span>
      </div>
    </div>
    <div id="mbody">
      <div id="mtitle"></div>
      <div id="mseries"></div>
      <div id="mmeta"></div>
      <div id="mcat-editor">
        <label>Genres</label>
        <div id="mcat-editor-row">
          <div id="mcat-chips"></div>
          <select id="mgenre-add" onchange="addGenreFromDropdown(this)" title="Add a genre">
            <option value="">+ Add genre…</option>
          </select>
        </div>
      </div>
      <div id="mdesc"></div>
      <div id="mcast"></div>
      <div id="mpath"></div>
      <div id="mactions">
        <button class="sbtn sec" id="wrong-cover-btn" onclick="removeCover()" style="display:none"><i class="fas fa-times-circle"></i> Wrong Cover</button>
        <button class="sbtn sec" id="change-cover-btn" onclick="triggerMovieCover()" style="display:none"><i class="fas fa-image"></i> Change Cover</button>
        <button class="sbtn sec" id="edit-meta-btn" onclick="openEditModal()" title="Edit metadata fields"><i class="fas fa-pen"></i> Edit Metadata</button>
        <div id="watched-wrap">
          <label for="watched-chk"><i class="fas fa-eye" style="color:#4ade80"></i> Watched</label>
          <label class="toggle">
            <input type="checkbox" id="watched-chk" onchange="setWatched(this.checked)">
            <span class="tsl"></span>
          </label>
        </div>
        <div id="kid-wrap">
          <label for="kid-chk"><i class="fas fa-child" style="color:var(--kids)"></i> Kid Friendly</label>
          <label class="toggle">
            <input type="checkbox" id="kid-chk" onchange="setKidFriendly(this.checked)">
            <span class="tsl"></span>
          </label>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- Confirm Dialog -->
<div id="confirm-overlay">
  <div class="dialog-box">
    <div class="dialog-icon">🗑️</div>
    <div class="dialog-title">Remove This Cover?</div>
    <div class="dialog-msg" id="confirm-msg"></div>
    <div class="dialog-actions">
      <button class="dbtn-cancel" onclick="confirmClose()">Cancel</button>
      <button class="dbtn-confirm" onclick="confirmProceed()">Yes, Remove It</button>
    </div>
  </div>
</div>

<!-- PIN Dialog -->
<div id="pin-overlay">
  <div class="dialog-box">
    <div class="dialog-icon">🔒</div>
    <div class="dialog-title">Enter PIN to Unlock</div>
    <div class="dialog-msg">Kids Mode is active. Enter your PIN to view all content.</div>
    <div class="pin-dots">
      <div class="pin-dot" id="pd0"></div>
      <div class="pin-dot" id="pd1"></div>
      <div class="pin-dot" id="pd2"></div>
      <div class="pin-dot" id="pd3"></div>
    </div>
    <div class="pin-error" id="pin-error"></div>
    <div class="pin-pad">
      <button class="pin-key" onclick="pinKey('1')">1</button>
      <button class="pin-key" onclick="pinKey('2')">2</button>
      <button class="pin-key" onclick="pinKey('3')">3</button>
      <button class="pin-key" onclick="pinKey('4')">4</button>
      <button class="pin-key" onclick="pinKey('5')">5</button>
      <button class="pin-key" onclick="pinKey('6')">6</button>
      <button class="pin-key" onclick="pinKey('7')">7</button>
      <button class="pin-key" onclick="pinKey('8')">8</button>
      <button class="pin-key" onclick="pinKey('9')">9</button>
      <button class="pin-key dbtn-cancel" onclick="pinCancel()" style="font-size:.78rem;font-weight:600">Cancel</button>
      <button class="pin-key" onclick="pinKey('0')">0</button>
      <button class="pin-key" onclick="pinBackspace()" title="Delete">⌫</button>
    </div>
  </div>
</div>

<!-- Series Panel -->
<div id="series-panel">
  <!-- Slim top bar: back + series name breadcrumb -->
  <div id="sp-header">
    <button id="sp-back" onclick="closeSeries()"><i class="fas fa-arrow-left"></i> Browse</button>
    <div id="sp-title"></div>
    <div id="sp-epcount"></div>
  </div>

  <div id="sp-body">
    <!-- Left sidebar: poster + metadata + controls -->
    <div id="sp-left">
      <div id="sp-poster"><span>📺</span></div>
      <div id="sp-left-title"></div>
      <div id="sp-left-badges"></div>
      <div id="sp-left-desc"></div>
      <div id="sp-left-cast"></div>
      <div id="sp-left-genres">
        <label><i class="fas fa-tags" style="margin-right:4px;opacity:.6"></i>Genres</label>
        <div id="sp-genre-chips"></div>
      </div>
      <div id="sp-left-actions">
        <button id="sp-fav-btn" class="sp-action-btn sp-fav-btn" onclick="toggleSeriesFavFromPanel()">
          <i class="fas fa-star"></i> <span id="sp-fav-label">Add to Favorites</span>
        </button>
        <button id="sp-cover-btn" class="sp-action-btn" onclick="triggerSeriesCover()" style="display:none">
          <i class="fas fa-image"></i> Change Cover
        </button>
      </div>
    </div>

    <!-- Right column: season tabs + episode list -->
    <div id="sp-right">
      <div id="sp-seasons"></div>
      <div id="sp-episodes">
        <div id="sp-episodes-inner"></div>
      </div>
    </div>
  </div>
</div>

<!-- Hidden file inputs for cover upload -->
<input type="file" id="series-cover-input" accept="image/*" style="display:none" onchange="uploadSeriesCover(this)">
<input type="file" id="movie-cover-input"  accept="image/*" style="display:none" onchange="uploadMovieCover(this)">

<!-- ── Edit Metadata Modal ───────────────────────────────────────────────── -->
<div id="edit-modal" onclick="if(event.target===this)closeEditModal()">
  <div id="edit-sheet">
    <div class="ef-header">
      <div class="ef-header-icon"><i class="fas fa-pen"></i></div>
      <div style="flex:1;min-width:0">
        <div class="ef-title" id="ef-modal-title">Edit Metadata</div>
        <div class="ef-subtitle" id="ef-modal-path"></div>
      </div>
      <button onclick="closeEditModal()" style="background:none;border:none;color:var(--muted);font-size:1.1rem;cursor:pointer;padding:4px 6px;border-radius:6px;line-height:1;transition:color .15s" onmouseover="this.style.color='var(--text)'" onmouseout="this.style.color='var(--muted)'"><i class="fas fa-times"></i></button>
    </div>
    <div class="ef-body">
      <div class="ef-poster">
        <img id="ef-poster-img" src="" alt="">
        <div id="ef-poster-ph" class="ef-poster-ph">🎞️</div>
      </div>
      <div class="ef-fields">
        <div class="ef-group">
          <label>Display Title</label>
          <input id="ef-title" type="text" placeholder="Title shown in CineVault">
        </div>
        <div class="ef-row ef-row-3">
          <div class="ef-group">
            <label>Year</label>
            <input id="ef-year" type="number" min="1888" max="2099" placeholder="2024">
          </div>
          <div class="ef-group">
            <label>Rating</label>
            <select id="ef-rating">
              <option value="">-- None --</option>
              <option>G</option><option>PG</option><option>PG-13</option>
              <option>R</option><option>NC-17</option><option>NR</option>
              <option>TV-G</option><option>TV-Y</option><option>TV-Y7</option>
              <option>TV-PG</option><option>TV-14</option><option>TV-MA</option>
            </select>
          </div>
          <div class="ef-group">
            <label>Runtime (min)</label>
            <input id="ef-runtime" type="number" min="1" max="999" placeholder="120">
          </div>
        </div>
        <div class="ef-group">
          <label>Genre <span style="text-transform:none;font-weight:400;opacity:.6">(e.g. Action / Comedy)</span></label>
          <input id="ef-genre" type="text" placeholder="Action / Adventure">
        </div>
        <div class="ef-row ef-row-2">
          <div class="ef-group">
            <label>Director</label>
            <input id="ef-director" type="text" placeholder="Director name">
          </div>
          <div class="ef-group">
            <label>Cast <span style="text-transform:none;font-weight:400;opacity:.6">(comma-separated)</span></label>
            <input id="ef-cast" type="text" placeholder="Actor 1, Actor 2">
          </div>
        </div>
        <div class="ef-group">
          <label>Description</label>
          <textarea id="ef-description" placeholder="Plot summary or notes…"></textarea>
        </div>
      </div>
    </div>
    <div class="ef-footer">
      <div id="ef-status" style="flex:1;font-size:.78rem;color:var(--muted)"></div>
      <button class="ef-btn-cancel" onclick="closeEditModal()">Cancel</button>
      <button class="ef-btn-save" id="ef-save-btn" onclick="saveEditModal()"><i class="fas fa-check" style="margin-right:6px"></i>Save Changes</button>
    </div>
  </div>
</div>

<button id="scroll-top-btn" onclick="window.scrollTo({top:0,behavior:'smooth'})" title="Back to top">
  <i class="fas fa-chevron-up"></i>
</button>

<div id="toast"></div>

<script>
let allVideos = [], activeVideo = null;
let activeSeriesName = null, activeSeriesSeason = null;
let activeSeriesGenres = [];
let filter = { cats:new Set(), kidsOnly:false, search:'', ratings:new Set(), genres:new Set(['all']), sort:'az', watched:'all' };

const EMO   = { Movies:'🎬','TV Shows':'📺',Music:'🎵',Personal:'🎞️' };
const BCLS  = { Movies:'b-movies','TV Shows':'b-tv',Music:'b-music',Personal:'b-personal' };
const ORDER = ['Movies','TV Shows','Music','Personal'];
// Genre tags (must match Python GENRES list)
const AVAILABLE_GENRES = [
  'Action','Adventure','Animation','Comedy',
  'Documentary','Drama','Faith','Family','Fantasy',
  'Holiday','Musical','Romance','Sci-Fi',
  'Kids','Favorites'
];
// Rating severity order for sort
const RATING_ORDER = {'G':1,'PG':2,'PG-13':3,'R':4,'NR':5,'':6};

// ── Init ──────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  // Load PIN from server settings
  try { const s = await fetch('/api/get_settings').then(r=>r.json()); KIDS_PIN = s.pin || '0000'; } catch(e) {}
  try {
    const data = await fetch('/api/library').then(r=>r.json());
    if (data.length > 0) { allVideos = data; render(); }
    else { document.getElementById('empty').style.display = 'flex'; }
  } catch(e) { document.getElementById('empty').style.display = 'flex'; }
  document.getElementById('loading-screen').style.display = 'none';
  document.getElementById('search').addEventListener('input', e => {
    filter.search = e.target.value.trim();
    const term = filter.search.toLowerCase();
    if (term === 'popcorn') {
      // Clear the search so movie cards fill the background, then rain popcorn over them
      filter.search = '';
      e.target.value = '';
      render();
      triggerPopcorn();
    } else if (term === 'leia') {
      filter.search = '';
      e.target.value = '';
      render();
      triggerLeiaEasterEgg();
    } else if (term === 'lily') {
      filter.search = '';
      e.target.value = '';
      render();
      triggerLilyEasterEgg();
    } else {
      render();
    }
  });
});

// ── Scan / Reprocess ──────────────────────────────────────────────────────────
async function doScan(full) {
  setLoading(full ? 'Full scan in progress… this may take a few minutes.' : 'Scanning Movies & Shows…');
  try {
    const data = await fetch('/api/scan?full=' + full).then(r=>r.json());
    allVideos = data; render();
    document.getElementById('empty').style.display = data.length===0 ? 'flex' : 'none';
    toast('Found ' + data.length + ' videos');
  } catch(e) { toast('Scan failed — is the E: drive connected?'); }
  document.getElementById('loading-screen').style.display = 'none';
}


function setLoading(msg) {
  document.getElementById('load-msg').textContent = msg;
  document.getElementById('loading-screen').style.display = 'flex';
}

// ── Filters ───────────────────────────────────────────────────────────────────
function setCat(cat) {
  if (cat === 'all') {
    filter.cats = new Set();
  } else if (filter.cats.has(cat)) {
    filter.cats.delete(cat);  // deselect — if empty, falls back to All
  } else {
    filter.cats.add(cat);
  }
  const isAll = filter.cats.size === 0;
  document.querySelectorAll('.cbtn[data-cat]').forEach(b => {
    if (b.dataset.cat === 'all') b.classList.toggle('active', isAll);
    else b.classList.toggle('active', filter.cats.has(b.dataset.cat));
  });
  render();
}

function toggleRating(r) {
  if (filter.ratings.has(r)) filter.ratings.delete(r);
  else filter.ratings.add(r);
  document.querySelectorAll('.cbtn[data-rating]').forEach(b =>
    b.classList.toggle('active', filter.ratings.has(b.dataset.rating)));
  render();
}

function setGenre(g) {
  if (g === 'all') {
    filter.genres = new Set(['all']);
  } else if (filter.genres.has(g)) {
    filter.genres.delete(g);
    if (filter.genres.size === 0) filter.genres.add('all');
  } else {
    filter.genres.delete('all');
    filter.genres.add(g);
  }
  document.querySelectorAll('.gbtn[data-genre]').forEach(b =>
    b.classList.toggle('active', filter.genres.has(b.dataset.genre)));
  render();
}

function setWatchedFilter(state) {
  // Clicking the active button toggles it back to 'all'
  filter.watched = (filter.watched === state) ? 'all' : state;
  document.querySelectorAll('.cbtn[data-watched]').forEach(b =>
    b.classList.toggle('active', b.dataset.watched === filter.watched));
  render();
}

function setSort(s) {
  filter.sort = s;
  render();
}

// ── Kids PIN lock ─────────────────────────────────────────────────────────────
let KIDS_PIN = '0000'; // overwritten on load from /api/get_settings
let _pinBuffer = '';

function toggleKids() {
  if (filter.kidsOnly) {
    // Trying to turn OFF kids mode — require PIN
    _pinBuffer = '';
    pinRender();
    document.getElementById('pin-error').textContent = '';
    document.getElementById('pin-overlay').classList.add('open');
  } else {
    // Turning ON kids mode — no PIN needed
    filter.kidsOnly = true;
    document.getElementById('kids-btn').classList.add('active');
    document.getElementById('settings-btn').style.display = 'none';
    render();
  }
}

function pinKey(digit) {
  if (_pinBuffer.length >= 4) return;
  _pinBuffer += digit;
  pinRender();
  if (_pinBuffer.length === 4) {
    setTimeout(pinCheck, 120); // brief pause so last dot fills visually
  }
}

function pinBackspace() {
  _pinBuffer = _pinBuffer.slice(0, -1);
  pinRender();
  document.getElementById('pin-error').textContent = '';
}

function pinRender() {
  for (let i = 0; i < 4; i++) {
    const dot = document.getElementById('pd' + i);
    dot.classList.toggle('filled', i < _pinBuffer.length);
    dot.classList.remove('error');
  }
}

function pinCheck() {
  if (_pinBuffer === KIDS_PIN) {
    document.getElementById('pin-overlay').classList.remove('open');
    filter.kidsOnly = false;
    document.getElementById('kids-btn').classList.remove('active');
    document.getElementById('settings-btn').style.display = '';
    _pinBuffer = '';
    render();
  } else {
    // Flash red dots, clear, let user try again
    for (let i = 0; i < 4; i++) document.getElementById('pd' + i).classList.add('error');
    document.getElementById('pin-error').textContent = 'Incorrect PIN. Try again.';
    setTimeout(() => { _pinBuffer = ''; pinRender(); }, 800);
  }
}

function pinCancel() {
  document.getElementById('pin-overlay').classList.remove('open');
  _pinBuffer = '';
}


function getFiltered() {
  let list = allVideos.filter(v => {
    if (filter.kidsOnly && !v.kid_friendly) return false;

    // Top-row category filter (multi-select)
    if (filter.cats.size > 0) {
      const pass = [...filter.cats].some(cat => {
        if (cat === 'Favorites') return (v.genres || []).includes('Favorites');
        return v.category === cat;
      });
      if (!pass) return false;
    }

    if (filter.ratings.size > 0 && !filter.ratings.has(v.rating || '')) return false;

    // Watched filter
    if (filter.watched === 'watched'   && !v.watched) return false;
    if (filter.watched === 'unwatched' &&  v.watched) return false;

    // Genre-row filter — check v.genres tags directly
    if (!filter.genres.has('all') && !(v.genres || []).some(g => filter.genres.has(g))) return false;

    if (filter.search) {
      const q = filter.search.toLowerCase();
      return (v.display_title || v.title).toLowerCase().includes(q) ||
             v.filename.toLowerCase().includes(q) ||
             (v.series      || '').toLowerCase().includes(q) ||
             (v.genre       || '').toLowerCase().includes(q) ||
             (v.description || '').toLowerCase().includes(q) ||
             (v.director    || '').toLowerCase().includes(q) ||
             (v.cast || []).some(c => c.toLowerCase().includes(q));
    }
    return true;
  });

  // Sort
  const sortKey = v => (v.display_title || v.title || '').toLowerCase();
  if      (filter.sort === 'az')     list.sort((a,b) => sortKey(a).localeCompare(sortKey(b)));
  else if (filter.sort === 'za')     list.sort((a,b) => sortKey(b).localeCompare(sortKey(a)));
  else if (filter.sort === 'newest') list.sort((a,b) => (b.meta_year||0) - (a.meta_year||0));
  else if (filter.sort === 'oldest') list.sort((a,b) => (a.meta_year||9999) - (b.meta_year||9999));
  else if (filter.sort === 'size')   list.sort((a,b) => b.size_mb - a.size_mb);
  else if (filter.sort === 'rating') list.sort((a,b) =>
    (RATING_ORDER[a.rating||'']||6) - (RATING_ORDER[b.rating||'']||6));
  else if (filter.sort === 'length') list.sort((a,b) =>
    (b.runtime_min||0) - (a.runtime_min||0) || sortKey(a).localeCompare(sortKey(b)));

  return list;
}

// ── Render ────────────────────────────────────────────────────────────────────
function render() {
  const vids = getFiltered();
  const isSearching = !!filter.search;

  // Count displayed "items" (series collapsed → 1 card per series)
  let displayCount = vids.length;
  if (!isSearching) {
    const seen = new Set();
    displayCount = 0;
    vids.forEach(v => {
      if (v.series) { if (!seen.has(v.series)) { seen.add(v.series); displayCount++; } }
      else displayCount++;
    });
  }

  document.getElementById('fcount').textContent = displayCount + ' title' + (displayCount !== 1 ? 's' : '');
  document.getElementById('stat').textContent   = allVideos.length + ' videos';
  const content = document.getElementById('content');
  content.innerHTML = '';

  if (!vids.length) {
    content.innerHTML = `<div style="text-align:center;padding:70px 20px;color:var(--muted)">
      <i class="fas fa-search" style="font-size:3rem;display:block;margin-bottom:12px"></i>
      No videos match your filters.
      <div style="margin-top:14px"><button class="sbtn sec" onclick="clearFilters()">Clear All Filters</button></div>
    </div>`;
    return;
  }

  const grouped = {};
  vids.forEach(v => (grouped[v.category] = grouped[v.category] || []).push(v));
  // Always group by primary category; supplemental filters just narrow which videos appear
  const cats = ORDER.filter(c => grouped[c])
    .concat(Object.keys(grouped).filter(c => !ORDER.includes(c)));

  const COL = { Movies:'var(--movies)','TV Shows':'var(--tv)',Music:'var(--music)',Personal:'var(--personal)' };
  const ICN = { Movies:'fa-film','TV Shows':'fa-tv',Music:'fa-music',Personal:'fa-photo-video' };

  cats.forEach(cat => {
    const items = grouped[cat] || [];
    const sec   = document.createElement('div');
    sec.className = 'section';
    const color = COL[cat] || 'var(--accent)';
    const icon  = ICN[cat] || 'fa-folder';

    if (!isSearching) {
      // Collapse items with a series into one series card per series
      const bySeries = {};
      const standalone = [];
      items.forEach(v => {
        if (v.series) (bySeries[v.series] = bySeries[v.series] || []).push(v);
        else standalone.push(v);
      });

      // Sort series alphabetically; sort standalone by current sort key
      const sortedSeries = Object.entries(bySeries).sort(([a],[b]) => {
        if (filter.sort === 'za')     return b.localeCompare(a);
        if (filter.sort === 'newest') return (Math.max(...bySeries[b].map(e=>e.meta_year||0))) - (Math.max(...bySeries[a].map(e=>e.meta_year||0)));
        if (filter.sort === 'oldest') return (Math.min(...bySeries[a].map(e=>e.meta_year||9999))) - (Math.min(...bySeries[b].map(e=>e.meta_year||9999)));
        if (filter.sort === 'size')   return bySeries[b].reduce((s,e)=>s+e.size_mb,0) - bySeries[a].reduce((s,e)=>s+e.size_mb,0);
        return a.localeCompare(b);
      });

      const allCards = [
        ...sortedSeries.map(([name, eps]) => seriesCardHTML(name, eps, cat)),
        ...standalone.map(cardHTML)
      ];
      const totalShown = sortedSeries.length + standalone.length;
      sec.innerHTML = `<div class="sec-head">
        <i class="fas ${icon}" style="color:${color}"></i>
        <span class="sec-title">${cat}</span>
        <span class="sec-count">${totalShown}</span>
        <div class="sec-line"></div>
      </div><div class="grid">${allCards.join('')}</div>`;
    } else {
      // Searching — show flat individual episode cards
      sec.innerHTML = `<div class="sec-head">
        <i class="fas ${icon}" style="color:${color}"></i>
        <span class="sec-title">${cat}</span>
        <span class="sec-count">${items.length}</span>
        <div class="sec-line"></div>
      </div><div class="grid">${items.map(cardHTML).join('')}</div>`;
    }
    content.appendChild(sec);
  });
}

function clearFilters() {
  filter.cats = new Set(); filter.ratings = new Set(); filter.genres = new Set(['all']);
  filter.kidsOnly = false; filter.search = ''; filter.sort = 'az'; filter.watched = 'all';
  document.getElementById('search').value = '';
  document.getElementById('sort-sel').value = 'az';
  document.getElementById('kids-btn').classList.remove('active');
  document.getElementById('settings-btn').style.display = '';
  document.querySelectorAll('.cbtn[data-cat]').forEach(b =>
    b.classList.toggle('active', b.dataset.cat === 'all'));
  document.querySelectorAll('.cbtn[data-rating]').forEach(b => b.classList.toggle('active', filter.ratings.has(b.dataset.rating)));
  document.querySelectorAll('.cbtn[data-watched]').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.gbtn[data-genre]').forEach(b =>
    b.classList.toggle('active', b.dataset.genre === 'all'));
  render();
}

// ── Series Card (collapsed view) ──────────────────────────────────────────────
function seriesCardHTML(seriesName, episodes, cat) {
  const emo   = EMO[cat] || '📺';
  const bc    = BCLS[cat] || 'b-tv';
  const enc   = encPath(seriesName);
  const ep0   = episodes[0] || {};
  const rtg   = ep0.rating ? `<span class="b-rating ${ratingClass(ep0.rating)}">${ep0.rating}</span>` : '';
  const genre = ep0.genre  ? `<span class="b-genre">${esc(ep0.genre.split('/')[0])}</span>` : '';
  const posterImg = ep0.poster_local
    ? `<img src="/${ep0.poster_local}" alt="" loading="lazy" onerror="this.style.display='none'">`
    : '';
  const anyFav = episodes.some(e => (e.genres || []).includes('Favorites'));
  const favBtn = filter.kidsOnly ? '' :
    `<button class="fav-btn${anyFav?' active':''}" onclick="event.stopPropagation();toggleSeriesFav('${enc}')" title="${anyFav?'Remove series from Favorites':'Add series to Favorites'}">
      <i class="fas fa-star"></i></button>`;
  return `<div class="card series-card" data-cat="${cat}" onclick="openSeries('${enc}')">
    ${favBtn}
    <div class="poster">${posterImg}${posterImg ? '' : emo}
      <div class="series-ep-badge">${episodes.length} ep</div>
      <div class="series-chevron"><div class="series-chevron-circle"><i class="fas fa-chevron-right"></i></div></div>
    </div>
    <div class="cbody">
      <div class="ctitle">${esc(seriesName)}</div>
      <div class="cmeta"><span class="badge ${bc}">${cat}</span>${rtg}${genre}</div>
    </div>
  </div>`;
}

// ── Parse episode info from display_title ─────────────────────────────────────
function parseEpisode(v) {
  const dt  = v.display_title || v.title || '';
  const raw = v.title || dt;   // raw filename-based title; may contain episode codes stripped from display_title

  // S01E02 – Title
  let m = dt.match(/^S(\d{2})E(\d{2})\s*[\u2013\-]\s*(.*)/i);
  if (m) return { season:parseInt(m[1]), ep:parseInt(m[2]), label:`S${m[1]}E${m[2]}`, title:m[3].trim() };

  // S01E02  (no title after)
  m = dt.match(/^S(\d{2})E(\d{2})/i);
  if (m) return { season:parseInt(m[1]), ep:parseInt(m[2]), label:`S${m[1]}E${m[2]}`, title:'' };

  // 01 – Title  (Baby Einstein style)
  m = dt.match(/^(\d{2})\s*[\u2013\-]\s*(.*)/);
  if (m) return { season:0, ep:parseInt(m[1]), label:`Ep ${m[1]}`, title:m[2].trim() };

  // Disc 01 – Title  (P90X)
  m = dt.match(/^Disc\s+(\d+)\s*[\u2013\-]\s*(.*)/i);
  if (m) return { season:0, ep:parseInt(m[1]), label:`Disc ${m[1]}`, title:m[2].trim() };

  // Part X of Y – Title
  m = dt.match(/^Part\s+(\d+)\s+of\s+\d+\s*[\u2013\-]\s*(.*)/i);
  if (m) return { season:0, ep:parseInt(m[1]), label:`Part ${m[1]}`, title:m[2].trim() };

  // NNxEE — e.g. "How Its Made 11x01 Binoculars…"  (seasons 11+)
  m = dt.match(/\b(\d{1,2})x(\d{2})\b(.*)/i);
  if (m) {
    const s = String(parseInt(m[1])).padStart(2,'0');
    const e = m[2];
    const title = m[3].replace(/^\s*[-\u2013\s]+/, '').trim();
    return { season:parseInt(m[1]), ep:parseInt(m[2]), label:`S${s}E${e}`, title };
  }

  // NMM — compact 3-digit season+episode in display_title e.g. "101 Aluminum Foil…"
  m = dt.match(/\b([1-9])(\d{2})\b(.*)/);
  if (m) {
    const s = '0' + m[1]; const e = m[2];
    const title = m[3].replace(/^\s*[-\u2013\s]+/, '').trim();
    return { season:parseInt(m[1]), ep:parseInt(m[2]), label:`S${s}E${e}`, title };
  }

  // ── Fallback: try to extract season/ep from the raw filename title,
  //    then use display_title as the episode name.
  //    Handles cases where display_title had the number stripped out
  //    e.g. raw="707 – Crayons…"  display_title="Crayons…"

  // NNxEE in raw
  m = raw.match(/\b(\d{1,2})x(\d{2})\b/i);
  if (m) {
    const s = String(parseInt(m[1])).padStart(2,'0'); const e = m[2];
    return { season:parseInt(m[1]), ep:parseInt(m[2]), label:`S${s}E${e}`, title:dt };
  }

  // NMM in raw
  m = raw.match(/\b([1-9])(\d{2})\b/);
  if (m) {
    const s = '0' + m[1]; const e = m[2];
    return { season:parseInt(m[1]), ep:parseInt(m[2]), label:`S${s}E${e}`, title:dt };
  }

  return { season:0, ep:0, label:'', title:dt };
}

// ── Episode row (inside series panel) ─────────────────────────────────────────
function epCardHTML(v) {
  const enc  = encPath(v.path);
  const info = parseEpisode(v);
  const title = info.title || v.display_title || v.title;
  const dur  = v.duration || (v.runtime_min ? v.runtime_min + ' min' : '');
  const size = v.size_mb > 1024 ? (v.size_mb/1024).toFixed(1)+' GB' : v.size_mb+' MB';
  const emo  = EMO[v.category] || '🎞️';
  return `<div class="ep-row" onclick="openModal('${enc}')">
    <div class="ep-thumb">${emo}</div>
    <div class="ep-info">
      <div class="ep-title-row">
        ${info.label ? `<span class="ep-num">${esc(info.label)}</span>` : ''}
        <span class="ep-title">${esc(title)}</span>
      </div>
      <div class="ep-meta-row">
        ${dur ? `<span><i class="fas fa-clock" style="opacity:.55;font-size:.65rem"></i> ${dur}</span>` : ''}
        <span>${size}</span>
        ${v.streamable ? `<span style="color:var(--kids)"><i class="fas fa-check-circle"></i> Streamable</span>` : ''}
      </div>
    </div>
    <div class="ep-play"><i class="fas fa-play" style="font-size:.7rem;margin-left:2px"></i></div>
  </div>`;
}

// ── Open / Close series panel ─────────────────────────────────────────────────
function openSeries(enc) {
  const seriesName = decodeURIComponent(enc);
  activeSeriesName = seriesName;

  const episodes = allVideos.filter(v => v.series === seriesName);
  const parsed   = episodes.map(v => ({ ...v, _ep: parseEpisode(v) }));

  // Determine unique seasons
  const seasonNums = [...new Set(parsed.map(p => p._ep.season))].sort((a,b)=>a-b);
  const hasSeasons = seasonNums.length > 1 || (seasonNums.length === 1 && seasonNums[0] !== 0);
  activeSeriesSeason = hasSeasons ? seasonNums[0] : null;

  const ep0 = episodes[0] || {};

  // ── Slim header ──
  document.getElementById('sp-title').textContent   = seriesName;
  document.getElementById('sp-epcount').textContent = episodes.length + ' episode' + (episodes.length !== 1 ? 's' : '');

  // ── Left sidebar ──
  // Poster
  const posterEl = document.getElementById('sp-poster');
  if (ep0.poster_local) {
    posterEl.innerHTML = `<img src="/${ep0.poster_local}" alt="" onerror="this.parentElement.innerHTML='📺'">`;
  } else {
    posterEl.innerHTML = '<span>📺</span>';
  }

  // Title
  document.getElementById('sp-left-title').textContent = seriesName;

  // Badges (rating + ep count)
  let badges = '';
  if (ep0.rating) badges += `<span class="b-rating ${ratingClass(ep0.rating)}">${ep0.rating}</span>`;
  if (ep0.meta_year) badges += `<span class="b-dur">${ep0.meta_year}</span>`;
  badges += `<span class="b-dur">${episodes.length} ep</span>`;
  document.getElementById('sp-left-badges').innerHTML = badges;

  // Description
  const descEl = document.getElementById('sp-left-desc');
  if (ep0.description) {
    descEl.textContent   = ep0.description;
    descEl.style.display = '';
  } else {
    descEl.style.display = 'none';
  }

  // Cast
  const castEl = document.getElementById('sp-left-cast');
  if (ep0.cast && ep0.cast.length) {
    castEl.innerHTML     = `<b>Cast:</b> ${ep0.cast.map(esc).join(', ')}`;
    castEl.style.display = '';
  } else if (ep0.director) {
    castEl.innerHTML     = `<b>Director:</b> ${esc(ep0.director)}`;
    castEl.style.display = '';
  } else {
    castEl.style.display = 'none';
  }

  // Genres
  activeSeriesGenres = [...(ep0.genres || ep0.extra_cats || [])];
  const genresEl = document.getElementById('sp-left-genres');
  if (filter.kidsOnly) {
    genresEl.style.display = 'none';
  } else {
    genresEl.style.display = '';
    renderSeriesGenreChips();
  }

  // Favorites button
  const anyFav = episodes.some(v => (v.genres || []).includes('Favorites'));
  const favBtn = document.getElementById('sp-fav-btn');
  favBtn.classList.toggle('active', anyFav);
  document.getElementById('sp-fav-label').textContent = anyFav ? 'Remove from Favorites' : 'Add to Favorites';
  favBtn.style.display = filter.kidsOnly ? 'none' : '';

  // Change Cover button
  document.getElementById('sp-cover-btn').style.display = filter.kidsOnly ? 'none' : '';

  // ── Season tabs ──
  const seasonsEl = document.getElementById('sp-seasons');
  if (hasSeasons) {
    seasonsEl.style.display = '';
    seasonsEl.innerHTML = seasonNums.map(s =>
      `<button class="season-tab ${s===activeSeriesSeason?'active':''}" data-season="${s}" onclick="setSeriesSeason(${s})">Season ${s}</button>`
    ).join('');
  } else {
    seasonsEl.style.display = 'none';
  }

  renderSeriesEpisodes(parsed, hasSeasons);
  document.getElementById('series-panel').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function toggleSeriesFavFromPanel() {
  if (!activeSeriesName) return;
  const episodes = allVideos.filter(v => v.series === activeSeriesName);
  const anyFav   = episodes.some(v => (v.genres || []).includes('Favorites'));
  // Reuse the existing card-level toggleSeriesFav by faking the enc arg
  toggleSeriesFav(encPath(activeSeriesName));
  // Update the sidebar button immediately
  const favBtn = document.getElementById('sp-fav-btn');
  favBtn.classList.toggle('active', !anyFav);
  document.getElementById('sp-fav-label').textContent = !anyFav ? 'Remove from Favorites' : 'Add to Favorites';
}

function setSeriesSeason(s) {
  activeSeriesSeason = s;
  document.querySelectorAll('.season-tab').forEach(b =>
    b.classList.toggle('active', parseInt(b.dataset.season) === s));
  const parsed = allVideos
    .filter(v => v.series === activeSeriesName)
    .map(v => ({ ...v, _ep: parseEpisode(v) }));
  renderSeriesEpisodes(parsed, true);
}

function renderSeriesEpisodes(parsed, hasSeasons) {
  let list = hasSeasons && activeSeriesSeason !== null
    ? parsed.filter(p => p._ep.season === activeSeriesSeason)
    : parsed;
  list = list.slice().sort((a,b) => {
    if (a._ep.season !== b._ep.season) return a._ep.season - b._ep.season;
    return a._ep.ep - b._ep.ep;
  });
  document.getElementById('sp-episodes-inner').innerHTML = list.map(epCardHTML).join('');
}

function closeSeries() {
  activeSeriesName = null;
  document.getElementById('series-panel').classList.remove('open');
  document.body.style.overflow = '';
}

// ── Series genre editor ───────────────────────────────────────────────────────
function renderSeriesGenreChips() {
  document.getElementById('sp-genre-chips').innerHTML = AVAILABLE_GENRES.map(genre => {
    const isOn  = activeSeriesGenres.includes(genre);
    const cls   = 'cat-chip ' + (isOn ? 'on' : 'off');
    const title = isOn ? 'Click to remove' : 'Click to add';
    return `<span class="${cls}" data-cat="${genre}" title="${title}"
              onclick="toggleSeriesGenre('${genre}')">${genre}</span>`;
  }).join('');
}

async function toggleSeriesGenre(genre) {
  if (!activeSeriesName) return;
  if (activeSeriesGenres.includes(genre)) {
    activeSeriesGenres = activeSeriesGenres.filter(g => g !== genre);
  } else {
    activeSeriesGenres = [...activeSeriesGenres, genre];
  }
  renderSeriesGenreChips();

  // Update in-memory for every episode of the series
  allVideos.filter(v => v.series === activeSeriesName).forEach(v => {
    v.genres = v.extra_cats = [...activeSeriesGenres];
    v.categories = [v.category, ...activeSeriesGenres.filter(g => g !== v.category)];
  });
  render();

  try {
    await fetch('/api/set_series_genres', {
      method:  'POST',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify({ series: activeSeriesName, genres: activeSeriesGenres })
    });
  } catch(e) { toast('Failed to save genres'); }
}

// ── Card ──────────────────────────────────────────────────────────────────────
// encodeURIComponent doesn't encode apostrophes, which breaks onclick='...' handlers
// for titles like "A Bug's Life". This helper ensures ' → %27 as well.
function encPath(s) { return encodeURIComponent(s).replace(/'/g, '%27'); }

function ratingClass(r) {
  if (r === 'G')     return 'b-G';
  if (r === 'PG')    return 'b-PG';
  if (r === 'PG-13') return 'b-PG13';
  if (r === 'R')     return 'b-R';
  return 'b-NR';
}

function cardHTML(v) {
  const enc      = encPath(v.path);
  const emo      = EMO[v.category] || '🎞️';
  const bc       = BCLS[v.category] || 'b-personal';
  const label    = v.display_title || v.title;
  const size     = v.size_mb > 1024 ? (v.size_mb / 1024).toFixed(1) + ' GB' : v.size_mb + ' MB';
  const durTxt   = v.duration || (v.runtime_min ? v.runtime_min + ' min' : '');
  const dur      = durTxt ? `<span class="b-dur"><i class="fas fa-clock" style="opacity:.5;font-size:.58rem;margin-right:2px"></i>${durTxt}</span>` : '';
  const kid      = v.kid_friendly ? '<div class="kid-pin">👶 Kids</div>' : '';
  const rtg      = v.rating    ? `<span class="b-rating ${ratingClass(v.rating)}">${v.rating}</span>` : '';
  const yr       = v.meta_year ? `<span class="b-dur">${v.meta_year}</span>` : '';
  const genreLbl = v.genre     ? `<span class="b-genre" title="${esc(v.genre)}">${esc(v.genre.split('/')[0])}</span>` : '';
  const posterImg = v.poster_local
    ? `<img src="/${v.poster_local}" alt="" loading="lazy" onerror="this.style.display='none'">`
    : '';
  const isFav = (v.genres || []).includes('Favorites');
  const favBtn = filter.kidsOnly ? '' :
    `<button class="fav-btn${isFav?' active':''}" onclick="event.stopPropagation();toggleFav('${enc}')" title="${isFav?'Remove from Favorites':'Add to Favorites'}">
      <i class="fas fa-star"></i></button>`;
  const watchBtn = filter.kidsOnly ? '' :
    `<button class="watch-btn${v.watched?' watched':''}" onclick="event.stopPropagation();toggleWatchedCard('${enc}',this)" title="${v.watched?'Mark as unwatched':'Mark as watched'}">
      <i class="fas fa-check"></i></button>`;
  const watchedBadge = v.watched ? `<div class="watched-ribbon" title="Watched"><i class="fas fa-check"></i></div>` : '';
  return `<div class="card" data-cat="${v.category}" onclick="openModal('${enc}')">
    ${favBtn}${kid}${watchBtn}
    <div class="poster">${posterImg}${posterImg ? '' : emo}
      ${watchedBadge}
      <div class="play-ov"><div class="play-circle"><i class="fas fa-play" style="margin-left:3px"></i></div></div>
    </div>
    <div class="cbody">
      <div class="ctitle">${esc(label)}</div>
      <div class="cmeta">
        ${rtg}${genreLbl}${yr}${dur}
        <span class="b-ext">${v.ext.toUpperCase().slice(1)}</span>
      </div>
    </div>
  </div>`;
}

// ── Modal ─────────────────────────────────────────────────────────────────────
function openModal(enc) {
  const path  = decodeURIComponent(enc);
  const video = allVideos.find(v => v.path === path);
  if (!video) return;
  activeVideo = video;

  const bc     = BCLS[video.category] || 'b-personal';
  const label  = video.display_title || video.title;
  const size   = video.size_mb > 1024 ? (video.size_mb / 1024).toFixed(1) + ' GB' : video.size_mb + ' MB';
  const durTxt = video.duration || (video.runtime_min ? video.runtime_min + ' min' : '');

  // Poster background in the play area
  const posterEl = document.getElementById('mposter-bg');
  if (video.poster_local) {
    posterEl.src = '/' + video.poster_local;
    posterEl.style.display = '';
  } else {
    posterEl.src = '';
    posterEl.style.display = 'none';
  }

  document.getElementById('mtitle').textContent  = label;
  document.getElementById('mseries').textContent = video.series ? '📺 ' + video.series : '';
  document.getElementById('mpath').textContent   = video.path;
  const watchedChk = document.getElementById('watched-chk');
  watchedChk.checked = !!video.watched;

  const kidChk = document.getElementById('kid-chk');
  kidChk.checked  = video.kid_friendly;
  kidChk.disabled = filter.kidsOnly;
  document.getElementById('kid-wrap').style.opacity      = filter.kidsOnly ? '0.4' : '';
  document.getElementById('kid-wrap').style.pointerEvents = filter.kidsOnly ? 'none' : '';
  document.getElementById('wrong-cover-btn').style.display =
    (video.poster_local && !filter.kidsOnly) ? '' : 'none';
  document.getElementById('change-cover-btn').style.display =
    filter.kidsOnly ? 'none' : '';
  document.getElementById('edit-meta-btn').style.display =
    filter.kidsOnly ? 'none' : '';

  // Category editor — hidden in Kid Mode
  const catEditor = document.getElementById('mcat-editor');
  catEditor.style.display = filter.kidsOnly ? 'none' : 'block';
  if (!filter.kidsOnly) renderCatChips(video);

  // Description
  const descEl = document.getElementById('mdesc');
  descEl.textContent   = video.description || '';
  descEl.style.display = video.description ? '' : 'none';

  // Director / Cast
  const castEl   = document.getElementById('mcast');
  const castBits = [];
  if (video.director)                castBits.push('<b>Director:</b> ' + esc(video.director));
  if (video.cast && video.cast.length) castBits.push('<b>Cast:</b> ' + video.cast.map(esc).join(', '));
  castEl.innerHTML     = castBits.join(' &nbsp;·&nbsp; ');
  castEl.style.display = castBits.length ? '' : 'none';

  // Meta row
  let meta = `<span class="badge ${bc}">${video.category}</span>`;
  if (video.rating)    meta += `<span class="b-rating ${ratingClass(video.rating)}">${video.rating}</span>`;
  if (video.genre)     meta += `<span style="font-size:.72rem;color:#a78bfa">${esc(video.genre)}</span>`;
  if (video.meta_year) meta += `<span class="b-dur">${video.meta_year}</span>`;
  if (durTxt)          meta += `<span class="b-dur"><i class="fas fa-clock"></i> ${durTxt}</span>`;
  meta += `<span class="b-size">${size}</span><span class="b-ext">${video.ext.toUpperCase().slice(1)}</span>`;
  document.getElementById('mmeta').innerHTML = meta;

  document.getElementById('moverlay').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeModal(e) {
  if (e && e.target !== document.getElementById('moverlay')) return;
  document.getElementById('moverlay').classList.remove('open');
  document.body.style.overflow = '';
  activeVideo = null;
}

async function openInPlayer() {
  if (!activeVideo) return;
  try {
    const r    = await fetch('/open?path=' + encodeURIComponent(activeVideo.path));
    const data = await r.json();
    if (data.ok) {
      toast('Opening in Windows Media Player…');
    } else {
      toast('⚠ File not found — drive may be disconnected or file was moved');
    }
  } catch(e) {
    toast('⚠ Could not open file');
  }
}

async function setKidFriendly(val) {
  if (!activeVideo) return;
  activeVideo.kid_friendly = val;
  const v = allVideos.find(x => x.path === activeVideo.path);
  if (v) v.kid_friendly = val;
  await fetch('/api/tag', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ path: activeVideo.path, kid_friendly: val })
  });
  toast(val ? '👶 Marked as Kid Friendly' : 'Kid Friendly tag removed');
  render();
}

// ── Watched toggle ────────────────────────────────────────────────────────────
async function setWatched(val) {
  if (!activeVideo) return;
  activeVideo.watched = val;
  const v = allVideos.find(x => x.path === activeVideo.path);
  if (v) v.watched = val;
  await fetch('/api/set_watched', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ path: activeVideo.path, watched: val })
  });
  toast(val ? '✓ Marked as watched' : 'Marked as unwatched');
  render();
}

async function toggleWatchedCard(enc, btn) {
  const path  = decodeURIComponent(enc);
  const video = allVideos.find(v => v.path === path);
  if (!video) return;
  const newVal = !video.watched;
  video.watched = newVal;
  btn.classList.toggle('watched', newVal);
  btn.title = newVal ? 'Mark as unwatched' : 'Mark as watched';
  await fetch('/api/set_watched', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ path, watched: newVal })
  });
  toast(newVal ? '✓ Marked as watched' : 'Marked as unwatched');
  render();
}

// ── Favorites toggle ─────────────────────────────────────────────────────────
async function toggleFav(enc) {
  const path  = decodeURIComponent(enc);
  const video = allVideos.find(v => v.path === path);
  if (!video) return;
  const genres  = video.genres || [];
  const hasFav  = genres.includes('Favorites');
  const newG    = hasFav ? genres.filter(g => g !== 'Favorites') : [...genres, 'Favorites'];
  video.genres = video.extra_cats = newG;
  video.categories = [video.category, ...newG.filter(g => g !== video.category)];
  try {
    await fetch('/api/set_cats', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ path, extra_cats: newG })
    });
    render();
    toast(hasFav ? 'Removed from Favorites' : '⭐ Added to Favorites');
  } catch(e) { toast('Failed to save'); }
}

async function toggleSeriesFav(enc) {
  const seriesName = decodeURIComponent(enc);
  const episodes   = allVideos.filter(v => v.series === seriesName);
  if (!episodes.length) return;
  const anyFav = episodes.some(v => (v.genres || []).includes('Favorites'));
  const saves  = episodes.map(v => {
    const genres = v.genres || [];
    const newG   = anyFav ? genres.filter(g => g !== 'Favorites')
                           : genres.includes('Favorites') ? genres : [...genres, 'Favorites'];
    v.genres = v.extra_cats = newG;
    v.categories = [v.category, ...newG.filter(g => g !== v.category)];
    return fetch('/api/set_cats', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ path: v.path, extra_cats: newG })
    });
  });
  try {
    await Promise.all(saves);
    render();
    toast(anyFav ? 'Removed series from Favorites' : '⭐ Added series to Favorites');
  } catch(e) { toast('Failed to save'); }
}

// ── Genre editor (in modal) ───────────────────────────────────────────────────
function renderCatChips(video) {
  const active = video.genres || video.extra_cats || [];

  // Render assigned genres as badges with hover-X
  document.getElementById('mcat-chips').innerHTML = active.length
    ? active.map(genre => {
        return `<span class="genre-badge cat-chip" data-cat="${genre}">${esc(genre)}<span class="gbx" onclick="toggleCatChip('${genre}')" title="Remove ${genre}">✕</span></span>`;
      }).join('')
    : `<span style="color:var(--muted);font-size:.7rem;font-style:italic">No genres — use dropdown to add</span>`;

  // Populate add-genre dropdown with only unassigned genres
  const sel = document.getElementById('mgenre-add');
  const unassigned = AVAILABLE_GENRES.filter(g => !active.includes(g));
  sel.innerHTML = '<option value="">+ Add genre\u2026</option>' +
    unassigned.map(g => `<option value="${g}">${g}</option>`).join('');
  sel.style.display = unassigned.length ? '' : 'none';
}

async function toggleCatChip(genre) {
  if (!activeVideo) return;
  let genres = [...(activeVideo.genres || activeVideo.extra_cats || [])];
  genres = genres.includes(genre) ? genres.filter(g => g !== genre) : [...genres, genre];

  activeVideo.genres = activeVideo.extra_cats = genres;
  activeVideo.categories = [activeVideo.category, ...genres.filter(g => g !== activeVideo.category)];
  const v = allVideos.find(x => x.path === activeVideo.path);
  if (v) { v.genres = v.extra_cats = genres; v.categories = activeVideo.categories; }

  renderCatChips(activeVideo);
  render();
  try {
    await fetch('/api/set_cats', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ path: activeVideo.path, extra_cats: genres })
    });
  } catch(e) { toast('Failed to save genre'); }
}

async function addGenreFromDropdown(sel) {
  const genre = sel.value;
  if (!genre || !activeVideo) return;
  await toggleCatChip(genre);
  // toggleCatChip already re-renders chips and resets dropdown
}

// ── Cover upload ──────────────────────────────────────────────────────────────
function triggerSeriesCover() {
  document.getElementById('series-cover-input').click();
}

function triggerMovieCover() {
  document.getElementById('movie-cover-input').click();
}

async function uploadSeriesCover(input) {
  if (!input.files || !input.files[0] || !activeSeriesName) return;
  const btn = document.getElementById('sp-cover-btn');
  const orig = btn.innerHTML;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Uploading…';
  btn.disabled  = true;

  const fd = new FormData();
  fd.append('series', activeSeriesName);
  fd.append('image', input.files[0]);

  try {
    const resp = await fetch('/api/set_cover', { method: 'POST', body: fd });
    const data = await resp.json();
    if (data.ok) {
      const local = data.poster_local;
      // Update every episode of this series in memory
      allVideos.filter(v => v.series === activeSeriesName)
               .forEach(v => { v.poster_local = local; });
      toast('Cover art updated! ✓');
      render();
    } else {
      toast('Upload failed: ' + (data.error || 'unknown'));
    }
  } catch(e) { toast('Upload failed'); }
  finally {
    btn.innerHTML = orig;
    btn.disabled  = false;
    input.value   = '';
  }
}

async function uploadMovieCover(input) {
  if (!input.files || !input.files[0] || !activeVideo) return;
  const btn = document.getElementById('change-cover-btn');
  const orig = btn.innerHTML;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Uploading…';
  btn.disabled  = true;

  const fd = new FormData();
  fd.append('path', activeVideo.path);
  if (activeVideo.series) fd.append('series', activeVideo.series);
  fd.append('image', input.files[0]);

  try {
    const resp = await fetch('/api/set_cover', { method: 'POST', body: fd });
    const data = await resp.json();
    if (data.ok) {
      const local = data.poster_local;
      activeVideo.poster_local = local;
      // Update all episodes with same series poster
      if (activeVideo.series) {
        allVideos.filter(v => v.series === activeVideo.series)
                 .forEach(v => { v.poster_local = local; });
      } else {
        const v = allVideos.find(x => x.path === activeVideo.path);
        if (v) v.poster_local = local;
      }
      // Refresh poster in the modal player area
      const posterEl = document.getElementById('mposter-bg');
      posterEl.src = '/' + local;
      posterEl.style.display = '';
      document.getElementById('wrong-cover-btn').style.display = '';
      toast('Cover art updated! ✓');
      render();
    } else {
      toast('Upload failed: ' + (data.error || 'unknown'));
    }
  } catch(e) { toast('Upload failed'); }
  finally {
    btn.innerHTML = orig;
    btn.disabled  = false;
    input.value   = '';
  }
}

// ── Cover removal with confirmation ──────────────────────────────────────────
let _confirmResolve = null;

function removeCover() {
  if (!activeVideo || !activeVideo.poster_local) return;
  const label = activeVideo.display_title || activeVideo.title || 'this item';
  document.getElementById('confirm-msg').textContent =
    `The cover art for "${label}" will be permanently deleted from your covers folder.`;
  document.getElementById('confirm-overlay').classList.add('open');
}

function confirmClose() {
  document.getElementById('confirm-overlay').classList.remove('open');
}

async function confirmProceed() {
  confirmClose();
  if (!activeVideo) return;

  const btn = document.getElementById('wrong-cover-btn');
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Removing…';

  try {
    await fetch('/api/remove_cover', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ path: activeVideo.path, series: activeVideo.series || '' })
    });

    const removed = activeVideo.poster_local;
    allVideos.forEach(v => { if (v.poster_local === removed) v.poster_local = ''; });
    activeVideo.poster_local = '';
    btn.style.display = 'none';
    toast('Cover removed');
    render();
  } catch(e) {
    toast('Failed to remove cover');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-image"></i> Wrong Cover';
  }
}

// ── Theme toggle ─────────────────────────────────────────────────────────────
function toggleTheme() {
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  document.documentElement.setAttribute('data-theme', isLight ? 'dark' : 'light');
  document.getElementById('theme-btn').innerHTML =
    isLight ? '<i class="fas fa-moon"></i>' : '<i class="fas fa-lightbulb"></i>';
  try { localStorage.setItem('mlTheme', isLight ? 'dark' : 'light'); } catch(e) {}
}

// Apply correct button icon on load
window.addEventListener('DOMContentLoaded', () => {
  if (document.documentElement.getAttribute('data-theme') === 'light') {
    document.getElementById('theme-btn').innerHTML = '<i class="fas fa-lightbulb"></i>';
  }
});

// ── Utilities ─────────────────────────────────────────────────────────────────
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

let _tt;
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg; el.classList.add('show');
  clearTimeout(_tt); _tt = setTimeout(() => el.classList.remove('show'), 3000);
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    // Close dialogs first before closing the main modal
    if (document.getElementById('confirm-overlay').classList.contains('open')) {
      confirmClose(); return;
    }
    if (document.getElementById('pin-overlay').classList.contains('open')) {
      pinCancel(); return;
    }
    if (document.getElementById('edit-modal').classList.contains('open')) {
      closeEditModal(); return;
    }
    document.getElementById('moverlay').classList.remove('open');
    document.body.style.overflow = '';
    activeVideo = null;
  }
  // Allow PIN entry via keyboard number keys
  if (document.getElementById('pin-overlay').classList.contains('open')) {
    if (e.key >= '0' && e.key <= '9') pinKey(e.key);
    if (e.key === 'Backspace') pinBackspace();
  }
});

// ── Logo click — home + easter egg ───────────────────────────────────────────
let _logoClicks = 0, _logoTimer = null;
function logoClick() {
  _logoClicks++;
  clearTimeout(_logoTimer);
  if (_logoClicks >= 5) {
    // 5 rapid clicks → secret credits page
    _logoClicks = 0;
    window.location.href = '/credits';
    return;
  }
  _logoTimer = setTimeout(() => { _logoClicks = 0; }, 2000);
  // Single click: reset everything and snap back to the top
  clearFilters();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── Connectivity ──────────────────────────────────────────────────────────────
let _isOnline = true;

async function checkConnectivity() {
  try {
    const data = await fetch('/api/connectivity').then(r => r.json());
    _isOnline = data.online;
    const pill = document.getElementById('conn-pill');
    const dot  = document.getElementById('conn-dot');
    const lbl  = document.getElementById('conn-lbl');
    pill.style.display = '';
    pill.className   = data.online ? 'online' : 'offline';
    dot.textContent  = '●';
    lbl.textContent  = data.online ? ' Online' : ' Offline';
    pill.title       = data.online
      ? `Internet connected (${data.latency_ms}ms via ${data.host})`
      : 'No internet connection — TMDB features unavailable';
  } catch(e) {
    _isOnline = false;
  }
}

// Check on load, then every 60 s
checkConnectivity();
setInterval(checkConnectivity, 60000);

// ── Scroll-to-top button ──────────────────────────────────────────────────────
window.addEventListener('scroll', () => {
  document.getElementById('scroll-top-btn')
    .classList.toggle('visible', window.scrollY > 400);
}, { passive: true });

// ── Edit Metadata Modal ───────────────────────────────────────────────────────
let _editPath = null;

function openEditModal() {
  const v = activeVideo;
  if (!v) return;
  _editPath = v.path;

  // Header
  document.getElementById('ef-modal-title').textContent = v.display_title || v.title || 'Edit Metadata';
  document.getElementById('ef-modal-path').textContent = v.path;

  // Poster
  const img = document.getElementById('ef-poster-img');
  const ph  = document.getElementById('ef-poster-ph');
  if (v.poster_local) {
    img.src = '/' + v.poster_local;
    img.style.display = 'block';
    ph.style.display  = 'none';
  } else {
    img.style.display = 'none';
    ph.style.display  = 'flex';
    ph.textContent = (EMO[v.category] || '🎞️');
  }

  // Populate fields
  document.getElementById('ef-title').value       = v.display_title || v.title || '';
  document.getElementById('ef-year').value        = v.meta_year  || '';
  document.getElementById('ef-rating').value      = v.rating     || '';
  document.getElementById('ef-runtime').value     = v.runtime_min|| '';
  document.getElementById('ef-genre').value       = v.genre      || '';
  document.getElementById('ef-director').value    = v.director   || '';
  document.getElementById('ef-cast').value        = (v.cast||[]).join(', ');
  document.getElementById('ef-description').value = v.description|| '';
  document.getElementById('ef-status').textContent = '';

  const modal = document.getElementById('edit-modal');
  modal.classList.add('open');
  document.body.style.overflow = 'hidden';
  setTimeout(() => document.getElementById('ef-title').select(), 60);
}

function closeEditModal() {
  document.getElementById('edit-modal').classList.remove('open');
  // Don't reset overflow — the movie detail modal is still open underneath
  _editPath = null;
}

async function saveEditModal() {
  if (!_editPath) return;
  const btn = document.getElementById('ef-save-btn');
  const status = document.getElementById('ef-status');
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin" style="margin-right:6px"></i>Saving…';
  status.textContent = '';

  const castRaw = document.getElementById('ef-cast').value;
  const castArr = castRaw.split(',').map(s => s.trim()).filter(Boolean);

  const yearVal    = parseInt(document.getElementById('ef-year').value)    || null;
  const runtimeVal = parseInt(document.getElementById('ef-runtime').value) || null;

  const payload = {
    path:          _editPath,
    display_title: document.getElementById('ef-title').value.trim(),
    year:          yearVal,
    rating:        document.getElementById('ef-rating').value,
    runtime_min:   runtimeVal,
    genre:         document.getElementById('ef-genre').value.trim(),
    director:      document.getElementById('ef-director').value.trim(),
    cast:          castArr,
    description:   document.getElementById('ef-description').value.trim(),
  };

  try {
    const res  = await fetch('/api/update_metadata', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.ok) {
      toast('✅ Metadata saved');
      closeEditModal();
      // Refresh library data in the background so cards update
      const fresh = await fetch('/api/library').then(r => r.json());
      allVideos = fresh;
      render();
    } else {
      status.textContent = '❌ ' + (data.error || 'Save failed');
    }
  } catch (err) {
    status.textContent = '❌ Network error';
  }

  btn.disabled = false;
  btn.innerHTML = '<i class="fas fa-check" style="margin-right:6px"></i>Save Changes';
}

// Close edit modal on Escape (handled alongside other modal close logic)

// ── 🍿 Popcorn easter egg ─────────────────────────────────────────────────────
let _popcornActive = false;
function triggerPopcorn() {
  if (_popcornActive) return;
  _popcornActive = true;

  // Container — sits above everything, ignores pointer events
  const wrap = document.createElement('div');
  wrap.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:9998;overflow:hidden';
  document.body.appendChild(wrap);

  const EMOJIS   = ['🍿','🍿','🍿','🍿','🌽'];   // mostly popcorn, occasional kernel
  const COUNT    = 75;
  const W        = window.innerWidth;
  const H        = window.innerHeight;
  const pieces   = [];

  for (let i = 0; i < COUNT; i++) {
    const el = document.createElement('span');
    const sz = Math.random() * 20 + 18;             // 18–38px
    el.textContent = EMOJIS[Math.floor(Math.random() * EMOJIS.length)];
    el.style.cssText = `position:absolute;top:0;left:0;font-size:${sz}px;line-height:1;user-select:none;will-change:transform;opacity:0`;
    wrap.appendChild(el);
    pieces.push({
      el,
      x:    Math.random() * (W + 80) - 40,          // spread across full width
      y:    -sz - Math.random() * H * 0.6,           // stagger start heights
      vy:   Math.random() * 4 + 3,                   // 3–7 px/frame fall speed
      vx:   (Math.random() - 0.5) * 2.5,             // gentle horizontal drift
      rot:  Math.random() * 360,
      vrot: (Math.random() - 0.5) * 12,              // spin rate
      wobT: Math.random() * Math.PI * 2,             // wobble phase offset
      wobA: (Math.random() - 0.5) * 1.5,             // wobble amplitude
      done: false,
    });
  }

  toast('🍿 Popcorn time!');

  let frame = 0;
  function tick() {
    frame++;
    let alive = 0;
    pieces.forEach(p => {
      if (p.done) return;
      p.y   += p.vy + frame * 0.012;                 // gentle gravity acceleration
      p.x   += p.vx + Math.sin(p.wobT + frame * 0.06) * p.wobA;
      p.rot += p.vrot;
      // Fade out over the bottom 25% of screen
      const fadeStart = H * 0.75;
      const opacity   = p.y < fadeStart ? 1 : Math.max(0, 1 - (p.y - fadeStart) / (H * 0.3));
      if (p.y > H + 60) { p.done = true; p.el.style.opacity = 0; return; }
      p.el.style.opacity   = opacity;
      p.el.style.transform = `translate(${p.x}px,${p.y}px) rotate(${p.rot}deg)`;
      alive++;
    });
    if (alive > 0) {
      requestAnimationFrame(tick);
    } else {
      wrap.remove();
      _popcornActive = false;
    }
  }
  requestAnimationFrame(tick);
}

// ── 👑 Leia easter egg — Princess of the Galaxy ───────────────────────────────
let _leiaActive = false;
function triggerLeiaEasterEgg() {
  if (_leiaActive) return;
  _leiaActive = true;

  // ── Dark space overlay
  const overlay = document.createElement('div');
  overlay.style.cssText = `
    position:fixed;inset:0;z-index:9999;
    background:radial-gradient(ellipse at 50% 60%, #0a0030 0%, #000010 100%);
    display:flex;flex-direction:column;align-items:center;justify-content:center;
    cursor:pointer;overflow:hidden
  `;
  document.body.appendChild(overlay);

  // ── Canvas starfield
  const canvas = document.createElement('canvas');
  canvas.width  = window.innerWidth;
  canvas.height = window.innerHeight;
  canvas.style.cssText = 'position:absolute;inset:0;pointer-events:none';
  overlay.appendChild(canvas);
  const ctx = canvas.getContext('2d');
  const STARS = Array.from({length:220}, () => ({
    x: Math.random()*canvas.width, y: Math.random()*canvas.height,
    r: Math.random()*1.6+.3, twinkle: Math.random()*Math.PI*2, speed: Math.random()*.04+.01
  }));
  const SHOOTS = [];
  function spawnShoot() {
    SHOOTS.push({x:Math.random()*canvas.width*.7, y:Math.random()*canvas.height*.4,
                 vx:Math.random()*9+6, vy:Math.random()*4+2, life:1, tail:Math.random()*60+40});
  }
  spawnShoot();
  let animId;
  function drawStars() {
    ctx.clearRect(0,0,canvas.width,canvas.height);
    STARS.forEach(s => {
      s.twinkle += s.speed;
      const a = .55 + .45*Math.sin(s.twinkle);
      ctx.beginPath();ctx.arc(s.x,s.y,s.r,0,Math.PI*2);
      ctx.fillStyle=`rgba(255,255,255,${a})`;ctx.fill();
    });
    // shooting stars
    for (let i=SHOOTS.length-1;i>=0;i--) {
      const sh=SHOOTS[i];
      const grad=ctx.createLinearGradient(sh.x-sh.vx*sh.tail/10,sh.y-sh.vy*sh.tail/10,sh.x,sh.y);
      grad.addColorStop(0,'rgba(255,255,220,0)');
      grad.addColorStop(1,`rgba(255,255,200,${sh.life*.9})`);
      ctx.beginPath();ctx.moveTo(sh.x-sh.vx*sh.tail/10,sh.y-sh.vy*sh.tail/10);
      ctx.lineTo(sh.x,sh.y);ctx.strokeStyle=grad;ctx.lineWidth=2;ctx.stroke();
      sh.x+=sh.vx;sh.y+=sh.vy;sh.life-=.022;
      if(sh.life<=0||sh.x>canvas.width||sh.y>canvas.height) SHOOTS.splice(i,1);
    }
    if(Math.random()<.025) spawnShoot();
    animId=requestAnimationFrame(drawStars);
  }
  drawStars();

  // ── Lightsaber accent bars
  const saberTop=document.createElement('div');
  saberTop.style.cssText='position:absolute;top:0;left:0;right:0;height:4px;background:linear-gradient(90deg,transparent,#00bfff,#7df9ff,#00bfff,transparent);animation:glowSaber 2s ease-in-out infinite';
  overlay.appendChild(saberTop);
  const saberBot=document.createElement('div');
  saberBot.style.cssText='position:absolute;bottom:0;left:0;right:0;height:4px;background:linear-gradient(90deg,transparent,#00bfff,#7df9ff,#00bfff,transparent);animation:glowSaber 2s ease-in-out infinite';
  overlay.appendChild(saberBot);

  // ── Center message card
  const card=document.createElement('div');
  card.style.cssText=`
    position:relative;z-index:2;text-align:center;padding:40px 52px;
    background:rgba(0,20,60,.55);backdrop-filter:blur(10px);
    border:1px solid rgba(0,191,255,.35);border-radius:20px;
    box-shadow:0 0 60px rgba(0,191,255,.25);
    animation:popIn .7s cubic-bezier(.34,1.56,.64,1) both
  `;
  overlay.appendChild(card);

  // Crown
  const crown=document.createElement('div');
  crown.textContent='👑';
  crown.style.cssText='font-size:72px;display:block;margin-bottom:8px;animation:spinSlow 6s linear infinite;transform-origin:center';
  card.appendChild(crown);

  // Name
  const name=document.createElement('div');
  name.textContent='Princess Leia!';
  name.style.cssText=`
    font-size:clamp(2.4rem,8vw,4rem);font-weight:900;letter-spacing:.02em;
    background:linear-gradient(135deg,#ffd700 0%,#fff8a0 40%,#ffa500 70%,#ffd700 100%);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
    animation:shimmerGold 2.5s ease-in-out infinite;margin-bottom:14px
  `;
  card.appendChild(name);

  // Tagline
  const tag=document.createElement('div');
  tag.innerHTML='✨ May the Force be with you ✨';
  tag.style.cssText='color:#b0d8ff;font-size:1.25rem;font-weight:600;letter-spacing:.06em;margin-bottom:18px';
  card.appendChild(tag);

  // Sub-line
  const sub=document.createElement('div');
  sub.textContent='A long time ago in a galaxy far, far away… you were born awesome. 🌟';
  sub.style.cssText='color:rgba(176,216,255,.7);font-size:.95rem;max-width:360px;line-height:1.5;margin:0 auto 20px';
  card.appendChild(sub);

  // Dismiss hint
  const hint=document.createElement('div');
  hint.textContent='[ tap anywhere to close ]';
  hint.style.cssText='color:rgba(100,180,255,.45);font-size:.75rem;letter-spacing:.1em;margin-top:4px';
  card.appendChild(hint);

  // Auto-dismiss after 9s or on click
  const dismiss = () => {
    cancelAnimationFrame(animId);
    overlay.style.transition='opacity .6s';
    overlay.style.opacity='0';
    setTimeout(() => { overlay.remove(); _leiaActive=false; }, 650);
  };
  overlay.addEventListener('click', dismiss);
  setTimeout(dismiss, 9000);
}

// ── 🐾 Lily easter egg — Future Vet ──────────────────────────────────────────
let _lilyActive = false;
function triggerLilyEasterEgg() {
  if (_lilyActive) return;
  _lilyActive = true;

  // ── Soft overlay (cards show through)
  const overlay = document.createElement('div');
  overlay.style.cssText = `
    position:fixed;inset:0;z-index:9999;
    background:rgba(255,220,240,.82);
    display:flex;flex-direction:column;align-items:center;justify-content:center;
    cursor:pointer;overflow:hidden;backdrop-filter:blur(3px)
  `;
  document.body.appendChild(overlay);

  // ── Floating animal emojis rising from bottom
  const ANIMALS = ['🐶','🐱','🐰','🐹','🦊','🐨','🐸','🐧','🐾','🦋','🐼','🦄','🐙','🐢','🦜'];
  const COUNT = 55;
  const W = window.innerWidth, H = window.innerHeight;
  for (let i=0; i<COUNT; i++) {
    const el=document.createElement('span');
    const em=ANIMALS[Math.floor(Math.random()*ANIMALS.length)];
    const sz=Math.random()*28+22;
    const startX=Math.random()*W;
    const delay=Math.random()*5;
    const dur=Math.random()*4+5;
    const drift=(Math.random()-.5)*120;
    el.textContent=em;
    el.style.cssText=`
      position:absolute;bottom:-60px;left:${startX}px;font-size:${sz}px;line-height:1;
      user-select:none;pointer-events:none;
      animation:floatUp ${dur}s ${delay}s ease-in-out forwards;
      transform:translateX(${drift}px)
    `;
    overlay.appendChild(el);
  }

  // ── Heartbeat paw prints decorating corners
  ['top:18px;left:24px','top:18px;right:24px','bottom:18px;left:24px','bottom:18px;right:24px'].forEach(pos=>{
    const p=document.createElement('span');
    p.textContent='🐾';
    p.style.cssText=`position:absolute;${pos};font-size:32px;animation:heartbeat 1.4s ease-in-out infinite;opacity:.65`;
    overlay.appendChild(p);
  });

  // ── Center card
  const card=document.createElement('div');
  card.style.cssText=`
    position:relative;z-index:2;text-align:center;padding:38px 50px;
    background:rgba(255,255,255,.78);backdrop-filter:blur(8px);
    border:2px solid rgba(255,150,200,.5);border-radius:24px;
    box-shadow:0 8px 48px rgba(255,100,180,.25);
    animation:popIn .7s cubic-bezier(.34,1.56,.64,1) both
  `;
  overlay.appendChild(card);

  // Stethoscope + paw
  const icon=document.createElement('div');
  icon.textContent='🩺';
  icon.style.cssText='font-size:68px;display:block;margin-bottom:6px;animation:pawBounce 1.2s ease-in-out infinite';
  card.appendChild(icon);

  // Name
  const name=document.createElement('div');
  name.textContent='Hi, Lily! 🌸';
  name.style.cssText=`
    font-size:clamp(2.4rem,8vw,3.8rem);font-weight:900;letter-spacing:.02em;margin-bottom:12px;
    background:linear-gradient(135deg,#ff6eb4 0%,#c45aff 50%,#ff6eb4 100%);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent
  `;
  card.appendChild(name);

  // Tagline
  const tag=document.createElement('div');
  tag.textContent='🐾 Future Vet in Training! 🐾';
  tag.style.cssText='color:#c026d3;font-size:1.2rem;font-weight:700;letter-spacing:.04em;margin-bottom:14px';
  card.appendChild(tag);

  // Sub-line
  const sub=document.createElement('div');
  sub.textContent='Every animal in the whole world is SO lucky to have you! 🐶🐱🐰❤️';
  sub.style.cssText='color:#9d174d;font-size:.95rem;max-width:360px;line-height:1.6;margin:0 auto 20px';
  card.appendChild(sub);

  // Dismiss hint
  const hint=document.createElement('div');
  hint.textContent='[ tap anywhere to close ]';
  hint.style.cssText='color:rgba(180,80,140,.45);font-size:.75rem;letter-spacing:.1em;margin-top:2px';
  card.appendChild(hint);

  // Auto-dismiss after 9s or on click
  const dismiss = () => {
    overlay.style.transition='opacity .6s';
    overlay.style.opacity='0';
    setTimeout(() => { overlay.remove(); _lilyActive=false; }, 650);
  };
  overlay.addEventListener('click', dismiss);
  setTimeout(dismiss, 9000);
}

// ── 🕹️ Frogger — Konami Code easter egg ──────────────────────────────────────
(function(){
  const SEQ=['ArrowUp','ArrowUp','ArrowDown','ArrowDown','ArrowLeft','ArrowRight','ArrowLeft','ArrowRight'];
  let idx=0;
  document.addEventListener('keydown',function(e){
    if(_froggerActive)return;
    const tag=document.activeElement&&document.activeElement.tagName;
    if(tag==='INPUT'||tag==='TEXTAREA'){idx=0;return;}
    if(e.key===SEQ[idx]){idx++;if(idx===SEQ.length){idx=0;triggerFrogger();}}
    else{idx=e.key===SEQ[0]?1:0;}
  });
})();

let _froggerActive=false;
function triggerFrogger(){
  if(_froggerActive)return;
  _froggerActive=true;
  toast('\u{1F579}\uFE0F CHEAT CODE ACCEPTED!');

  // Mount the game in a fullscreen iframe served by CineVault at /frogger.
  // The game calls window.parent.postMessage('frogger:exit','*') to close.
  const overlay=document.createElement('div');
  overlay.style.cssText='position:fixed;inset:0;z-index:10000;background:#040410;';
  const iframe=document.createElement('iframe');
  iframe.src='/frogger';
  iframe.style.cssText='width:100%;height:100%;border:none;display:block;';
  iframe.allow='autoplay';
  overlay.appendChild(iframe);
  document.body.appendChild(overlay);
  document.body.style.overflow='hidden';

  function _msgHandler(e){
    if(e.data==='frogger:exit'){
      overlay.remove();
      document.body.style.overflow='';
      _froggerActive=false;
      window.removeEventListener('message',_msgHandler);
    }
  }
  window.addEventListener('message',_msgHandler);
}
</script>
</body>
</html>"""

CREDITS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>CineVault — Credits</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;background:#000;color:#e8e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;overflow:hidden}

/* starfield */
#stars{position:fixed;inset:0;z-index:0;pointer-events:none}

/* scroll container */
#reel{position:fixed;inset:0;z-index:1;overflow-y:auto;display:flex;flex-direction:column;align-items:center;padding:100vh 20px 80vh}

/* back button */
#back{position:fixed;top:20px;left:24px;z-index:10;padding:6px 16px;border-radius:16px;font-size:.8rem;font-weight:600;border:1px solid rgba(255,255,255,.2);background:rgba(255,255,255,.07);color:#fff;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:7px;transition:all .2s;backdrop-filter:blur(6px)}
#back:hover{background:rgba(255,255,255,.15);border-color:rgba(255,255,255,.4)}

/* secret badge */
#secret{position:fixed;top:20px;right:24px;z-index:10;font-size:.65rem;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:rgba(255,255,255,.2);border:1px solid rgba(255,255,255,.1);padding:3px 10px;border-radius:10px}

/* credits typography */
.cr-intro{text-align:center;margin-bottom:60px;max-width:540px}
.cr-intro h1{font-size:2.8rem;font-weight:900;letter-spacing:-1px;background:linear-gradient(135deg,#a855f7,#60a5fa);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px}
.cr-intro .tagline{font-size:.9rem;color:rgba(255,255,255,.4);letter-spacing:.3px}
.cr-intro .version{font-size:.72rem;color:rgba(255,255,255,.2);margin-top:6px;font-family:monospace}

.cr-block{width:100%;max-width:540px;margin-bottom:52px;text-align:center}
.cr-label{font-size:.62rem;font-weight:700;letter-spacing:1.4px;text-transform:uppercase;color:rgba(168,85,247,.7);margin-bottom:16px}
.cr-name{font-size:1.45rem;font-weight:800;color:#fff;margin-bottom:6px;letter-spacing:-.3px}
.cr-name.golden{background:linear-gradient(135deg,#fbbf24,#f59e0b);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.cr-name.purple{background:linear-gradient(135deg,#a855f7,#818cf8);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.cr-name.blue{background:linear-gradient(135deg,#60a5fa,#34d399);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.cr-roles{display:flex;flex-direction:column;gap:3px;margin-top:2px}
.cr-role{font-size:.78rem;color:rgba(255,255,255,.45);letter-spacing:.1px}
.cr-role.funny{color:rgba(255,255,255,.28);font-style:italic;font-size:.72rem}

.cr-divider{width:1px;height:40px;background:linear-gradient(to bottom,transparent,rgba(255,255,255,.12),transparent);margin:0 auto 52px}

.cr-quote{width:100%;max-width:480px;margin:0 auto 52px;text-align:center;font-size:.82rem;color:rgba(255,255,255,.3);line-height:1.7;font-style:italic;border-left:2px solid rgba(168,85,247,.3);padding-left:16px;text-align:left}

.cr-tech{width:100%;max-width:540px;margin-bottom:52px}
.cr-tech-label{font-size:.62rem;font-weight:700;letter-spacing:1.4px;text-transform:uppercase;color:rgba(96,165,250,.6);margin-bottom:14px;text-align:center}
.cr-tech-grid{display:flex;flex-wrap:wrap;justify-content:center;gap:8px}
.cr-tech-pill{font-size:.72rem;font-weight:600;padding:4px 12px;border-radius:12px;border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.05);color:rgba(255,255,255,.5);letter-spacing:.2px}

.cr-fin{text-align:center;max-width:480px;margin-bottom:60px}
.cr-fin p{font-size:.8rem;color:rgba(255,255,255,.25);line-height:1.8}
.cr-fin .heart{color:#f43f5e;font-size:.9rem}

.cr-stamp{text-align:center;font-size:.65rem;color:rgba(255,255,255,.1);letter-spacing:.5px;font-family:monospace;margin-bottom:20px}
</style>
</head>
<body>

<canvas id="stars"></canvas>

<a id="back" href="/"><i class="fas fa-arrow-left"></i> Back to Library</a>
<div id="secret">🔒 CLASSIFIED</div>

<div id="reel">

  <div class="cr-intro">
    <h1>🎬 CineVault</h1>
    <div class="tagline">A local media browser no one asked for, but everyone needed.</div>
    <div class="version">Version __APP_VERSION__ &nbsp;·&nbsp; Internal Use Only</div>
  </div>

  <div class="cr-block">
    <div class="cr-label">Presented By</div>
    <div class="cr-name golden">Josh Nave</div>
    <div class="cr-roles">
      <div class="cr-role">Founder &amp; CEO</div>
      <div class="cr-role">Lead Developer</div>
      <div class="cr-role">Head of Design</div>
      <div class="cr-role">UX Researcher &amp; UX Ignorer</div>
      <div class="cr-role">QA Engineer (self-certified)</div>
      <div class="cr-role">Product Manager</div>
      <div class="cr-role">Director of Vibes</div>
      <div class="cr-role">Chief Coffee Officer</div>
      <div class="cr-role">IT Department (entire)</div>
      <div class="cr-role">Network Administrator</div>
      <div class="cr-role">Database Architect</div>
      <div class="cr-role">DevOps &amp; Infrastructure</div>
      <div class="cr-role">Marketing Department (budget: $0)</div>
      <div class="cr-role">Social Media Manager (account: nonexistent)</div>
      <div class="cr-role">Legal Team (unlicensed)</div>
      <div class="cr-role">HR Department (solo division)</div>
      <div class="cr-role">Chief Snack Officer</div>
      <div class="cr-role funny">Facilities &amp; Maintenance · Janitor · Night Crew · Also the Intern</div>
    </div>
  </div>

  <div class="cr-divider"></div>

  <div class="cr-block">
    <div class="cr-label">Co-Developer &amp; Architect</div>
    <div class="cr-name purple">Claude (Anthropic)</div>
    <div class="cr-roles">
      <div class="cr-role">Lead Backend Engineer</div>
      <div class="cr-role">Frontend Developer &amp; CSS Therapist</div>
      <div class="cr-role">Database Whisperer</div>
      <div class="cr-role">Bug Introducer (unintentional)</div>
      <div class="cr-role">Bug Resolver (also unintentional)</div>
      <div class="cr-role">Documentation Author (you're reading it)</div>
      <div class="cr-role">PowerShell Wrangler</div>
      <div class="cr-role">Win32 API Consultant</div>
      <div class="cr-role">Chief Explainer of Things That Broke</div>
      <div class="cr-role funny">Wrote approximately 97.3% of the code · Do not tell Josh</div>
    </div>
  </div>

  <div class="cr-divider"></div>

  <div class="cr-block">
    <div class="cr-label">Built With</div>
    <div class="cr-name blue">Claude Code</div>
    <div class="cr-roles">
      <div class="cr-role">Agentic Development Environment</div>
      <div class="cr-role">Keeper of the Changelog</div>
      <div class="cr-role">Primary Reason Anything Works</div>
      <div class="cr-role funny">Runs on pure vibes and compute credits</div>
    </div>
  </div>

  <div class="cr-divider"></div>

  <div class="cr-quote">
    "I just wanted to watch movies without opening File Explorer."<br><br>
    — Josh Nave, Founder, CEO, and Janitor of CineVault
  </div>

  <div class="cr-tech">
    <div class="cr-tech-label">Technologies &amp; Ingredients</div>
    <div class="cr-tech-grid">
      <span class="cr-tech-pill">Python 3</span>
      <span class="cr-tech-pill">Flask</span>
      <span class="cr-tech-pill">HTML / CSS / JS</span>
      <span class="cr-tech-pill">TMDB API</span>
      <span class="cr-tech-pill">Windows Media Player (Legacy)</span>
      <span class="cr-tech-pill">Win32 ctypes</span>
      <span class="cr-tech-pill">PowerShell (retired)</span>
      <span class="cr-tech-pill">JSON files (many)</span>
      <span class="cr-tech-pill">Font Awesome</span>
      <span class="cr-tech-pill">Caffeine</span>
      <span class="cr-tech-pill">Clipboard Paste</span>
      <span class="cr-tech-pill">Stack Overflow (spiritually)</span>
      <span class="cr-tech-pill">Vibes</span>
    </div>
  </div>

  <div class="cr-fin">
    <p>
      No files were harmed in the making of this software.<br>
      Several metadata JSONs were deeply confused.<br>
      Josh Brolin was incorrectly credited in four movies and has since been removed.<br>
      WALL-E was born in the wrong year and has been corrected.<br><br>
      This application is provided <em>as-is</em> to one (1) household.<br>
      All 825 videos have been lovingly catalogued.<br><br>
      <span class="heart">♥</span> Made with love, frustration, and an unreasonable number of AI tokens. <span class="heart">♥</span>
    </p>
  </div>

  <div class="cr-stamp">CINEVAULT · __APP_VERSION__ · FOR INTERNAL USE ONLY · THIS MESSAGE WILL NOT SELF-DESTRUCT</div>

</div>

<script>
// ── Starfield ─────────────────────────────────────────────────────────────────
(function() {
  const c = document.getElementById('stars');
  const ctx = c.getContext('2d');
  let stars = [];
  function resize() {
    c.width  = window.innerWidth;
    c.height = window.innerHeight;
  }
  function makeStars(n) {
    stars = [];
    for (let i = 0; i < n; i++) {
      stars.push({
        x: Math.random() * c.width,
        y: Math.random() * c.height,
        r: Math.random() * 1.2 + 0.2,
        a: Math.random(),
        da: (Math.random() - 0.5) * 0.004
      });
    }
  }
  function draw() {
    ctx.clearRect(0, 0, c.width, c.height);
    stars.forEach(s => {
      s.a = Math.max(0.05, Math.min(1, s.a + s.da));
      if (s.a <= 0.05 || s.a >= 1) s.da *= -1;
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255,255,255,${s.a})`;
      ctx.fill();
    });
    requestAnimationFrame(draw);
  }
  resize();
  makeStars(180);
  draw();
  window.addEventListener('resize', () => { resize(); makeStars(180); });
})();

// ── Auto-scroll ───────────────────────────────────────────────────────────────
(function() {
  const reel = document.getElementById('reel');
  let speed = 0.6;
  let paused = false;
  reel.addEventListener('mouseenter', () => paused = true);
  reel.addEventListener('mouseleave', () => paused = false);
  function tick() {
    if (!paused) reel.scrollTop += speed;
    requestAnimationFrame(tick);
  }
  tick();
})();
</script>
</body>
</html>"""

SETTINGS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>CineVault — Settings</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<style>
:root{--bg:#0a0a12;--surface:#13131f;--surface2:#1c1c2e;--border:#2a2a3d;--text:#e8e8f0;--muted:#6b6b8a;--accent:#7c3aed;--kids:#16a34a;--nav-bg:rgba(10,10,18,.97)}
[data-theme=light]{--bg:#f0f0ec;--surface:#ffffff;--surface2:#e2e2dc;--border:#b0b0a6;--text:#1a1a2e;--muted:#58586e;--accent:#7c3aed;--nav-bg:rgba(240,240,236,.97)}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh}

/* NAV */
#snav{position:sticky;top:0;z-index:10;background:var(--nav-bg,rgba(10,10,18,.97));border-bottom:1px solid var(--border);display:flex;align-items:center;gap:14px;padding:0 24px;height:56px;backdrop-filter:blur(8px)}
#slogo{font-size:1.1rem;font-weight:800;letter-spacing:-.3px;color:var(--text)}
#slogo span{color:var(--accent)}
#snav-right{margin-left:auto;display:flex;gap:8px;align-items:center}
.snbtn{padding:5px 14px;border-radius:16px;font-size:.8rem;font-weight:600;border:1px solid var(--border);background:var(--surface2);color:var(--text);cursor:pointer;text-decoration:none;transition:all .2s;display:inline-flex;align-items:center;gap:6px}
.snbtn:hover{border-color:var(--accent);color:var(--accent)}
.snbtn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.snbtn.primary:hover{opacity:.85;color:#fff}

/* PAGE LAYOUT */
#spage{max-width:760px;margin:0 auto;padding:32px 20px 60px}
h1{font-size:1.5rem;font-weight:800;margin-bottom:6px}
.page-sub{color:var(--muted);font-size:.88rem;margin-bottom:32px}

/* CARDS */
.scard{background:var(--surface);border:1px solid var(--border);border-radius:14px;margin-bottom:20px;overflow:hidden}
.scard-head{padding:16px 20px 12px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px}
.scard-icon{width:32px;height:32px;border-radius:8px;background:var(--surface2);display:flex;align-items:center;justify-content:center;font-size:.85rem;color:var(--accent);flex-shrink:0}
.scard-title{font-size:.82rem;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--muted)}
.scard-body{padding:18px 20px}

/* STATS GRID */
.stat-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
@media(max-width:480px){.stat-grid{grid-template-columns:repeat(2,1fr)}}
.stat-tile{background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.stat-num{font-size:1.6rem;font-weight:800;color:var(--text);line-height:1}
.stat-lbl{font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin-top:4px}

/* SCAN BUTTONS */
.scan-row{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap}
.scan-btn{padding:8px 18px;border-radius:10px;font-size:.82rem;font-weight:600;border:1px solid var(--border);background:var(--surface2);color:var(--text);cursor:pointer;transition:all .2s;display:inline-flex;align-items:center;gap:7px}
.scan-btn:hover{border-color:var(--accent);color:var(--accent)}
.scan-btn:disabled{opacity:.4;cursor:not-allowed}
#scan-status{margin-top:10px;font-size:.8rem;color:var(--muted);min-height:1.2em}

/* FORM ROWS */
.form-group{margin-bottom:14px}
.form-group:last-child{margin-bottom:0}
.form-label{font-size:.78rem;font-weight:600;color:var(--muted);margin-bottom:5px;display:block}
.form-input{width:100%;padding:9px 13px;border-radius:9px;font-size:.88rem;border:1px solid var(--border);background:var(--surface2);color:var(--text);outline:none;transition:border-color .15s}
.form-input:focus{border-color:var(--accent)}
.form-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.form-submit{padding:8px 18px;border-radius:10px;font-size:.82rem;font-weight:600;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer;transition:opacity .18s}
.form-submit:hover{opacity:.85}
#pin-msg{font-size:.78rem;min-height:1.2em;margin-top:8px}

/* APPEARANCE ROW */
.appear-row{display:flex;align-items:center;justify-content:space-between;padding:4px 0}
.appear-label{font-size:.88rem;color:var(--text)}
.appear-sub{font-size:.75rem;color:var(--muted);margin-top:1px}
.toggle-pill{width:44px;height:24px;border-radius:12px;background:var(--border);border:none;cursor:pointer;position:relative;transition:background .2s;flex-shrink:0}
.toggle-pill.on{background:var(--accent)}
.toggle-pill::after{content:'';position:absolute;width:18px;height:18px;border-radius:50%;background:#fff;top:3px;left:3px;transition:transform .2s}
.toggle-pill.on::after{transform:translateX(20px)}

/* ABOUT */
.about-row{display:flex;align-items:center;gap:12px;padding:4px 0}
.about-icon{font-size:1.6rem}
.about-name{font-size:1rem;font-weight:700}
.about-ver{font-size:.78rem;color:var(--muted)}

/* MISSING COVERS */
.missing-badge{margin-left:auto;font-size:.72rem;color:var(--muted);background:var(--surface2);padding:2px 9px;border-radius:9px;border:1px solid var(--border)}
.missing-filters{display:flex;gap:6px;margin-bottom:12px}
.mf-btn{padding:4px 13px;border-radius:14px;font-size:.75rem;font-weight:600;border:1px solid var(--border);background:var(--surface2);color:var(--muted);cursor:pointer;transition:all .2s}
.mf-btn.active{background:var(--accent);border-color:var(--accent);color:#fff}
.missing-list{max-height:380px;overflow-y:auto;border:1px solid var(--border);border-radius:10px}
.missing-row{display:flex;align-items:center;gap:9px;padding:9px 13px;border-bottom:1px solid var(--border);transition:background .12s}
.missing-row:last-child{border-bottom:none}
.missing-row:hover{background:var(--surface2)}
.missing-type{font-size:.63rem;font-weight:700;padding:2px 6px;border-radius:5px;flex-shrink:0;letter-spacing:.2px}
.mt-movie{background:rgba(124,58,237,.15);color:#c084fc;border:1px solid rgba(124,58,237,.3)}
.mt-series{background:rgba(37,99,235,.15);color:#93c5fd;border:1px solid rgba(37,99,235,.3)}
.missing-title{flex:1;font-size:.81rem;color:var(--text);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.missing-year{font-size:.71rem;color:var(--muted);flex-shrink:0}
.fetch-btn{padding:3px 10px;border-radius:7px;font-size:.71rem;font-weight:600;border:1px solid var(--border);background:var(--surface);color:var(--text);cursor:pointer;flex-shrink:0;transition:all .18s;white-space:nowrap}
.fetch-btn:hover{border-color:var(--accent);color:var(--accent)}
.fetch-btn:disabled{opacity:.35;cursor:not-allowed}
.row-status{font-size:.8rem;flex-shrink:0;width:18px;text-align:center}

/* COVER PREVIEW MODAL */
#cprev-overlay{position:fixed;inset:0;z-index:600;background:rgba(0,0,0,.72);display:none;align-items:center;justify-content:center;backdrop-filter:blur(5px)}
#cprev-overlay.open{display:flex}
#cprev-box{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:24px 22px;max-width:320px;width:92%;display:flex;flex-direction:column;align-items:center;gap:14px;box-shadow:0 20px 60px rgba(0,0,0,.6)}
#cprev-img{width:190px;height:285px;object-fit:cover;border-radius:10px;border:1px solid var(--border);background:var(--surface2)}
#cprev-tmdb-title{font-size:.95rem;font-weight:700;color:var(--text);text-align:center}
#cprev-tmdb-year{font-size:.76rem;color:var(--muted);margin-top:2px;text-align:center}
#cprev-actions{display:flex;gap:8px;width:100%}
#cprev-actions button{flex:1;padding:8px;border-radius:9px;font-size:.8rem;font-weight:600;cursor:pointer;border:1px solid;transition:all .18s}
#cprev-apply{background:var(--accent);border-color:var(--accent);color:#fff}
#cprev-apply:hover{opacity:.85}
#cprev-skip{background:var(--surface2);border-color:var(--border);color:var(--text)}
#cprev-skip:hover{border-color:#f87171;color:#f87171}

/* BROKEN PATHS */
.bp-drive-warn{display:flex;align-items:center;gap:9px;background:rgba(251,191,36,.07);border:1px solid rgba(251,191,36,.3);border-radius:9px;padding:9px 13px;margin-bottom:12px;font-size:.8rem;color:#fbbf24}
.bp-drive-warn i{flex-shrink:0}
.broken-row{display:flex;align-items:center;gap:9px;padding:9px 13px;border-bottom:1px solid var(--border);transition:background .12s}
.broken-row:last-child{border-bottom:none}
.broken-row:hover{background:var(--surface2)}
.broken-path{flex:1;min-width:0;display:flex;flex-direction:column;gap:1px}
.broken-title{font-size:.81rem;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.broken-filepath{font-size:.67rem;color:var(--muted);font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.remove-btn{padding:3px 10px;border-radius:7px;font-size:.71rem;font-weight:600;border:1px solid rgba(248,113,113,.4);background:rgba(248,113,113,.08);color:#f87171;cursor:pointer;flex-shrink:0;transition:all .18s;white-space:nowrap}
.remove-btn:hover{background:rgba(248,113,113,.2)}
.remove-btn:disabled{opacity:.35;cursor:not-allowed}
.bp-toolbar{display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap}
.bp-purge{padding:4px 13px;border-radius:14px;font-size:.75rem;font-weight:600;border:1px solid rgba(248,113,113,.4);background:rgba(248,113,113,.08);color:#f87171;cursor:pointer;margin-left:auto;transition:all .18s}
.bp-purge:hover{background:rgba(248,113,113,.2)}
.bp-purge:disabled{opacity:.35;cursor:not-allowed}
.bp-rescan{padding:4px 13px;border-radius:14px;font-size:.75rem;font-weight:600;border:1px solid var(--border);background:var(--surface2);color:var(--muted);cursor:pointer;transition:all .18s;display:inline-flex;align-items:center;gap:5px}
.bp-rescan:hover{border-color:var(--accent);color:var(--accent)}

/* CONNECTIVITY PILL (settings nav) */
#sconn-pill{display:inline-flex;align-items:center;gap:3px;font-size:.65rem;font-weight:600;padding:2px 8px;border-radius:12px;border:1px solid var(--border);background:var(--surface2);white-space:nowrap;cursor:default}
#sconn-dot{font-size:.45rem;line-height:1}
#sconn-pill.online{border-color:rgba(74,222,128,.35);background:rgba(74,222,128,.08);color:#4ade80}
#sconn-pill.offline{border-color:rgba(248,113,113,.35);background:rgba(248,113,113,.08);color:#f87171}

/* OFFLINE WARNING BANNER */
.offline-banner{display:none;align-items:center;gap:9px;background:rgba(248,113,113,.08);border:1px solid rgba(248,113,113,.3);border-radius:9px;padding:9px 13px;margin-bottom:14px;font-size:.8rem;color:#f87171}
.offline-banner.show{display:flex}
.offline-banner i{flex-shrink:0}

/* TOAST */
#stoast{position:fixed;bottom:28px;left:50%;transform:translateX(-50%) translateY(20px);background:#1e1e30;border:1px solid var(--border);color:var(--text);padding:9px 20px;border-radius:20px;font-size:.84rem;opacity:0;transition:all .3s;pointer-events:none;white-space:nowrap;z-index:999}
#stoast.show{opacity:1;transform:translateX(-50%) translateY(0)}
</style>
</head>
<body>

<nav id="snav">
  <div id="slogo" onclick="logoClick()" style="cursor:pointer;user-select:none">🎬 <span>Cine</span>Vault</div>
  <div id="snav-right">
    <span id="sconn-pill" title="Checking internet…" style="display:none">
      <span id="sconn-dot">●</span><span id="sconn-lbl"></span>
    </span>
    <button class="snbtn" onclick="toggleTheme()"><i class="fas fa-moon" id="stheme-icon"></i> <span id="stheme-label">Dark</span></button>
    <a class="snbtn primary" href="/"><i class="fas fa-arrow-left"></i> Back to Library</a>
  </div>
</nav>

<div id="spage">
  <h1><i class="fas fa-cog" style="color:var(--accent);margin-right:10px"></i>Settings</h1>
  <div class="page-sub">Manage your CineVault library, appearance, and security settings.</div>

  <!-- Library Stats -->
  <div class="scard">
    <div class="scard-head">
      <div class="scard-icon"><i class="fas fa-film"></i></div>
      <div class="scard-title">Library</div>
    </div>
    <div class="scard-body">
      <div class="stat-grid" id="stat-grid">
        <div class="stat-tile"><div class="stat-num">—</div><div class="stat-lbl">Loading…</div></div>
      </div>
      <div class="scan-row">
        <button class="scan-btn" id="quick-scan-btn" onclick="doScan(false)">
          <i class="fas fa-sync-alt"></i> Quick Scan
        </button>
        <button class="scan-btn" id="full-scan-btn" onclick="doScan(true)">
          <i class="fas fa-hdd"></i> Full Scan
        </button>
      </div>
      <div id="scan-status"></div>
    </div>
  </div>

  <!-- Kid Mode PIN -->
  <div class="scard">
    <div class="scard-head">
      <div class="scard-icon"><i class="fas fa-child" style="color:var(--kids)"></i></div>
      <div class="scard-title">Kid Mode PIN</div>
    </div>
    <div class="scard-body">
      <p style="font-size:.82rem;color:var(--muted);margin-bottom:16px">Change the 4-digit PIN required to exit Kid Mode. Default is <code style="background:var(--surface2);padding:1px 5px;border-radius:4px">0000</code>.</p>
      <div class="form-group">
        <label class="form-label">Current PIN</label>
        <input class="form-input" id="pin-cur" type="password" maxlength="4" placeholder="••••" inputmode="numeric" style="max-width:180px">
      </div>
      <div class="form-group">
        <label class="form-label">New PIN</label>
        <input class="form-input" id="pin-new" type="password" maxlength="4" placeholder="4 digits" inputmode="numeric" style="max-width:180px">
      </div>
      <div class="form-group">
        <label class="form-label">Confirm New PIN</label>
        <input class="form-input" id="pin-conf" type="password" maxlength="4" placeholder="4 digits" inputmode="numeric" style="max-width:180px">
      </div>
      <button class="form-submit" onclick="changePin()"><i class="fas fa-key"></i> Update PIN</button>
      <div id="pin-msg"></div>
    </div>
  </div>

  <!-- Appearance -->
  <div class="scard">
    <div class="scard-head">
      <div class="scard-icon"><i class="fas fa-palette"></i></div>
      <div class="scard-title">Appearance</div>
    </div>
    <div class="scard-body">
      <div class="appear-row">
        <div>
          <div class="appear-label">Dark Mode</div>
          <div class="appear-sub">Toggle between dark and light themes</div>
        </div>
        <button class="toggle-pill" id="theme-pill" onclick="toggleTheme()"></button>
      </div>
    </div>
  </div>

  <!-- TMDB Token -->
  <div class="scard">
    <div class="scard-head">
      <div class="scard-icon"><i class="fas fa-key"></i></div>
      <div class="scard-title">TMDB API Token</div>
    </div>
    <div class="scard-body">
      <div class="offline-banner" id="tmdb-offline-banner">
        <i class="fas fa-wifi-slash"></i>
        No internet connection — TMDB features are unavailable until connectivity is restored.
      </div>
      <p style="font-size:.82rem;color:var(--muted);margin-bottom:16px;line-height:1.6">
        Used to fetch cover art and metadata from
        <a href="https://www.themoviedb.org" target="_blank" style="color:var(--accent);text-decoration:none">themoviedb.org</a>.
        Get a free token at
        <a href="https://www.themoviedb.org/settings/api" target="_blank" style="color:var(--accent);text-decoration:none">TMDB → Settings → API</a>
        and paste the <b>Read Access Token</b> (the long one starting with <code style="background:var(--surface2);padding:1px 5px;border-radius:4px">eyJ…</code>) below.
      </p>
      <div class="form-group">
        <label class="form-label">Current token</label>
        <div style="display:flex;gap:8px;align-items:center">
          <input class="form-input" id="tmdb-display" type="password" readonly placeholder="No token saved"
                 style="font-family:monospace;font-size:.75rem;flex:1;cursor:default">
          <button class="form-submit" style="white-space:nowrap;background:var(--surface2);border-color:var(--border);color:var(--text)" onclick="toggleTokenVisibility()">
            <i class="fas fa-eye" id="tmdb-eye-icon"></i>
          </button>
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">Paste new token</label>
        <textarea class="form-input" id="tmdb-new" rows="3"
                  placeholder="eyJhbGciOiJIUzI1NiJ9…"
                  style="font-family:monospace;font-size:.72rem;resize:vertical"></textarea>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <button class="form-submit net-btn" onclick="saveTmdbToken()"><i class="fas fa-save"></i> Save Token</button>
        <button class="form-submit net-btn" style="background:var(--surface2);border-color:var(--border);color:var(--text)" onclick="testTmdbToken()"><i class="fas fa-flask"></i> Test Token</button>
      </div>
      <div id="tmdb-msg" style="font-size:.78rem;min-height:1.2em;margin-top:8px"></div>
    </div>
  </div>

  <!-- Missing Cover Art -->
  <div class="scard">
    <div class="scard-head">
      <div class="scard-icon"><i class="fas fa-image"></i></div>
      <div class="scard-title">Missing Cover Art</div>
      <span class="missing-badge" id="missing-badge">Loading…</span>
    </div>
    <div class="scard-body">
      <div class="offline-banner" id="covers-offline-banner">
        <i class="fas fa-wifi-slash"></i>
        No internet connection — Fetch buttons require internet to reach TMDB.
      </div>
      <div class="missing-filters">
        <button class="mf-btn active" data-mf="all"      onclick="setMissingFilter('all')">All</button>
        <button class="mf-btn"        data-mf="Movies"   onclick="setMissingFilter('Movies')">Movies</button>
        <button class="mf-btn"        data-mf="TV Shows" onclick="setMissingFilter('TV Shows')">TV Shows</button>
      </div>
      <div class="missing-list" id="missing-list">
        <div class="missing-row" style="justify-content:center;color:var(--muted);font-size:.8rem;padding:22px">Loading…</div>
      </div>
    </div>
  </div>

  <!-- Broken File Paths -->
  <div class="scard">
    <div class="scard-head">
      <div class="scard-icon"><i class="fas fa-unlink" style="color:#f87171"></i></div>
      <div class="scard-title">Broken File Paths</div>
      <span class="missing-badge" id="bp-badge">—</span>
    </div>
    <div class="scard-body">
      <div class="bp-toolbar">
        <button class="mf-btn active" data-bpf="all"      onclick="setBpFilter('all')">All</button>
        <button class="mf-btn"        data-bpf="Movies"   onclick="setBpFilter('Movies')">Movies</button>
        <button class="mf-btn"        data-bpf="TV Shows" onclick="setBpFilter('TV Shows')">TV Shows</button>
        <button class="bp-rescan" onclick="loadBrokenPaths()"><i class="fas fa-sync-alt"></i> Rescan</button>
        <button class="bp-purge" id="bp-purge-btn" onclick="purgeAllBroken()" style="display:none">
          <i class="fas fa-trash-alt"></i> Remove All
        </button>
      </div>
      <div id="bp-drive-warn" class="bp-drive-warn" style="display:none">
        <i class="fas fa-exclamation-triangle"></i>
        <span id="bp-drive-warn-text"></span>
      </div>
      <div class="missing-list" id="bp-list">
        <div class="broken-row" style="justify-content:center;color:var(--muted);font-size:.8rem;padding:22px">Loading…</div>
      </div>
    </div>
  </div>

  <!-- Export Library -->
  <div class="scard">
    <div class="scard-head">
      <div class="scard-icon"><i class="fas fa-file-csv"></i></div>
      <div class="scard-title">Export Library</div>
    </div>
    <div class="scard-body">
      <p style="font-size:.82rem;color:var(--muted);margin-bottom:16px;line-height:1.6">
        Download your entire library — every title, its metadata (rating, year, genre, director, cast, description), file size, and path — as a CSV file you can open in Excel or any spreadsheet app.
      </p>
      <button class="form-submit" id="csv-export-btn" onclick="exportLibraryCSV(this)">
        <i class="fas fa-download"></i> Download CSV
      </button>
      <div id="csv-msg" style="font-size:.78rem;min-height:1.2em;margin-top:8px;color:var(--muted)"></div>
    </div>
  </div>

  <!-- About -->
  <div class="scard">
    <div class="scard-head">
      <div class="scard-icon" onclick="window.location.href='/credits'" title="View credits" style="cursor:pointer;transition:transform .2s,color .2s" onmouseenter="this.style.transform='scale(1.18)';this.style.color='var(--accent)'" onmouseleave="this.style.transform='';this.style.color=''"><i class="fas fa-info-circle"></i></div>
      <div class="scard-title">About</div>
    </div>
    <div class="scard-body">
      <div class="about-row">
        <div class="about-icon">🎬</div>
        <div>
          <div class="about-name">CineVault</div>
          <div class="about-ver">Version __APP_VERSION__ &nbsp;·&nbsp; Local media browser &nbsp;·&nbsp; Powered by Flask &amp; TMDB</div>
        </div>
      </div>
    </div>
  </div>

</div>

<!-- Cover Preview Modal -->
<div id="cprev-overlay">
  <div id="cprev-box">
    <img id="cprev-img" src="" alt="Cover preview">
    <div id="cprev-tmdb-title"></div>
    <div id="cprev-tmdb-year"></div>
    <div id="cprev-actions">
      <button id="cprev-apply" onclick="applySelectedCover()"><i class="fas fa-check"></i> Apply Cover</button>
      <button id="cprev-skip"  onclick="declineCover()"><i class="fas fa-times"></i> Skip</button>
    </div>
  </div>
</div>

<div id="stoast"></div>

<script>
// ── Theme ─────────────────────────────────────────────────────────────────────
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const isLight = theme === 'light';
  document.getElementById('stheme-icon').className  = isLight ? 'fas fa-lightbulb' : 'fas fa-moon';
  document.getElementById('stheme-label').textContent = isLight ? 'Light' : 'Dark';
  const pill = document.getElementById('theme-pill');
  if (pill) pill.classList.toggle('on', !isLight);
}
function toggleTheme() {
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  const next = isLight ? 'dark' : 'light';
  applyTheme(next);
  try { localStorage.setItem('mlTheme', next); } catch(e) {}
}
(function() {
  try { applyTheme(localStorage.getItem('mlTheme') || 'dark'); } catch(e) { applyTheme('dark'); }
})();

// ── Stats ─────────────────────────────────────────────────────────────────────
async function loadStats() {
  try {
    const s = await fetch('/api/stats').then(r=>r.json());
    document.getElementById('stat-grid').innerHTML =
      statTile(s.total,    'Total Videos')  +
      statTile(s.movies,   'Movies')        +
      statTile(s.episodes, 'TV Episodes')   +
      statTile(s.series,   'TV Series')     +
      statTile(s.covered,  'With Cover Art')+
      statTile(s.missing,  'Missing Covers');
  } catch(e) {
    document.getElementById('stat-grid').innerHTML = '<p style="color:var(--muted);font-size:.82rem">Could not load stats — is the server running?</p>';
  }
}
function statTile(n, lbl) {
  return `<div class="stat-tile"><div class="stat-num">${n}</div><div class="stat-lbl">${lbl}</div></div>`;
}

// ── Scan ──────────────────────────────────────────────────────────────────────
async function doScan(full) {
  const qb = document.getElementById('quick-scan-btn');
  const fb = document.getElementById('full-scan-btn');
  const st = document.getElementById('scan-status');
  qb.disabled = fb.disabled = true;
  st.style.color = 'var(--muted)';
  st.textContent = full ? 'Full scan in progress… this may take a few minutes.' : 'Scanning Movies & Shows…';
  try {
    const data = await fetch('/api/scan?full=' + full).then(r=>r.json());
    st.style.color = '#4ade80';
    st.textContent = '✓ Scan complete — ' + data.length + ' videos found.';
    loadStats();
  } catch(e) {
    st.style.color = '#f87171';
    st.textContent = '✗ Scan failed — is the E: drive connected?';
  }
  qb.disabled = fb.disabled = false;
}

// ── PIN ───────────────────────────────────────────────────────────────────────
let CURRENT_PIN = '0000';
async function loadPin() {
  try { const s = await fetch('/api/get_settings').then(r=>r.json()); CURRENT_PIN = s.pin || '0000'; } catch(e) {}
}
async function changePin() {
  const cur  = document.getElementById('pin-cur').value.trim();
  const nw   = document.getElementById('pin-new').value.trim();
  const conf = document.getElementById('pin-conf').value.trim();
  const msg  = document.getElementById('pin-msg');
  if (cur !== CURRENT_PIN)      { showMsg(msg, 'error', 'Current PIN is incorrect.'); return; }
  if (!/^\d{4}$/.test(nw))     { showMsg(msg, 'error', 'New PIN must be exactly 4 digits.'); return; }
  if (nw !== conf)              { showMsg(msg, 'error', 'New PINs do not match.'); return; }
  try {
    await fetch('/api/save_settings', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({pin: nw}) });
    CURRENT_PIN = nw;
    document.getElementById('pin-cur').value = '';
    document.getElementById('pin-new').value = '';
    document.getElementById('pin-conf').value = '';
    showMsg(msg, 'ok', '✓ PIN updated successfully.');
    toast('PIN updated');
  } catch(e) { showMsg(msg, 'error', 'Failed to save — try again.'); }
}
function showMsg(el, type, txt) {
  el.style.color = type === 'ok' ? '#4ade80' : '#f87171';
  el.textContent = txt;
}

// ── Toast ─────────────────────────────────────────────────────────────────────
let _tt;
function toast(msg) {
  const el = document.getElementById('stoast');
  el.textContent = msg; el.classList.add('show');
  clearTimeout(_tt); _tt = setTimeout(() => el.classList.remove('show'), 3000);
}

// ── TMDB Token ────────────────────────────────────────────────────────────────
let _tokenVisible = false;

async function loadTmdbToken() {
  try {
    const data = await fetch('/api/get_tmdb_token').then(r=>r.json());
    const field = document.getElementById('tmdb-display');
    field.value = data.token || '';
    field.type  = 'password';
    _tokenVisible = false;
    document.getElementById('tmdb-eye-icon').className = 'fas fa-eye';
  } catch(e) {}
}

function toggleTokenVisibility() {
  const field = document.getElementById('tmdb-display');
  _tokenVisible = !_tokenVisible;
  field.type = _tokenVisible ? 'text' : 'password';
  document.getElementById('tmdb-eye-icon').className = _tokenVisible ? 'fas fa-eye-slash' : 'fas fa-eye';
}

async function saveTmdbToken() {
  const token = document.getElementById('tmdb-new').value.trim();
  const msg   = document.getElementById('tmdb-msg');
  if (!_isOnline) { showMsg(msg, 'error', 'No internet connection.'); return; }
  if (!token) { showMsg(msg, 'error', 'Please paste a token first.'); return; }
  if (!token.startsWith('eyJ')) { showMsg(msg, 'error', 'That doesn\'t look like a valid TMDB Read Access Token (should start with eyJ…).'); return; }
  try {
    const r = await fetch('/api/save_tmdb_token', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ token })
    });
    const data = await r.json();
    if (data.ok) {
      document.getElementById('tmdb-display').value = token;
      document.getElementById('tmdb-new').value = '';
      showMsg(msg, 'ok', '✓ Token saved to config.json.');
      toast('TMDB token saved');
    } else {
      showMsg(msg, 'error', 'Server error saving token.');
    }
  } catch(e) { showMsg(msg, 'error', 'Failed to save — try again.'); }
}

async function testTmdbToken() {
  const msg = document.getElementById('tmdb-msg');
  if (!_isOnline) { showMsg(msg, 'error', 'No internet connection.'); return; }
  showMsg(msg, 'ok', 'Testing token…');
  try {
    const data = await fetch('/api/test_tmdb_token').then(r=>r.json());
    if (data.ok) {
      showMsg(msg, 'ok', `✓ Token works! Connected as "${data.username}" on TMDB.`);
    } else {
      showMsg(msg, 'error', '✗ Token rejected by TMDB — double-check you copied the full Read Access Token.');
    }
  } catch(e) { showMsg(msg, 'error', '✗ Could not reach TMDB — check your internet connection.'); }
}

// ── Missing Covers ────────────────────────────────────────────────────────────
let _missingAll    = [];
let _missingFilter = 'all';
let _cprevData     = null;

function esc2(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function loadMissingCovers() {
  try {
    const data = await fetch('/api/missing_covers').then(r=>r.json());
    _missingAll = data.items || [];
    document.getElementById('missing-badge').textContent =
      _missingAll.length ? `${_missingAll.length} missing` : 'All covered ✓';
    renderMissingList();
  } catch(e) {
    document.getElementById('missing-badge').textContent = 'Error';
  }
}

function setMissingFilter(f) {
  _missingFilter = f;
  document.querySelectorAll('.mf-btn').forEach(b => b.classList.toggle('active', b.dataset.mf === f));
  renderMissingList();
}

function _filteredMissing() {
  return _missingFilter === 'all'
    ? _missingAll
    : _missingAll.filter(i => i.type === _missingFilter);
}

function renderMissingList() {
  const items = _filteredMissing();
  const el    = document.getElementById('missing-list');
  if (!items.length) {
    el.innerHTML = `<div class="missing-row" style="justify-content:center;color:var(--muted);font-size:.8rem;padding:22px">
      ${_missingFilter === 'all' ? 'All items have cover art! ✓' : 'No items in this category missing covers.'}
    </div>`;
    return;
  }
  el.innerHTML = items.map((item, idx) => {
    const tc = item.type === 'Movies' ? 'mt-movie' : 'mt-series';
    const tl = item.type === 'Movies' ? 'Movie' : 'Series';
    return `<div class="missing-row" id="mrow-${idx}">
      <span class="missing-type ${tc}">${tl}</span>
      <span class="missing-title" title="${esc2(item.title)}">${esc2(item.title)}</span>
      <span class="missing-year">${esc2(item.year)}</span>
      <button class="fetch-btn" id="fbtn-${idx}" onclick="fetchCoverPreview(${idx})">
        <i class="fas fa-cloud-download-alt"></i> Fetch
      </button>
      <span class="row-status" id="rstatus-${idx}"></span>
    </div>`;
  }).join('');
}

async function fetchCoverPreview(idx) {
  if (!_isOnline) { toast('No internet connection — cannot reach TMDB'); return; }
  const items = _filteredMissing();
  const item  = items[idx];
  const btn   = document.getElementById(`fbtn-${idx}`);
  const stat  = document.getElementById(`rstatus-${idx}`);

  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
  stat.textContent = '';

  try {
    const r = await fetch('/api/fetch_cover_preview', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ path: item.path, type: item.type, title: item.title, year: item.year, key: item.key })
    });
    const data = await r.json();

    if (data.ok && data.img_url) {
      _cprevData = { idx, item, ...data };
      document.getElementById('cprev-img').src              = data.img_url;
      document.getElementById('cprev-tmdb-title').textContent = data.tmdb_title || item.title;
      document.getElementById('cprev-tmdb-year').textContent  = data.tmdb_year  || item.year || '';
      document.getElementById('cprev-overlay').classList.add('open');
    } else {
      stat.textContent = '✗';
      stat.style.color = '#f87171';
      btn.disabled = false;
      btn.innerHTML = '<i class="fas fa-cloud-download-alt"></i> Fetch';
      toast('No cover found on TMDB');
    }
  } catch(e) {
    stat.textContent = '✗';
    stat.style.color = '#f87171';
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-cloud-download-alt"></i> Fetch';
  }
}

async function applySelectedCover() {
  if (!_cprevData) return;
  document.getElementById('cprev-overlay').classList.remove('open');
  const { idx, item } = _cprevData;
  const stat = document.getElementById(`rstatus-${idx}`);
  const btn  = document.getElementById(`fbtn-${idx}`);

  stat.textContent = '⏳';
  stat.style.color = 'var(--muted)';

  try {
    const r = await fetch('/api/apply_cover_from_tmdb', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        path: item.path, type: item.type, key: item.key,
        poster_path: _cprevData.poster_path
      })
    });
    const data = await r.json();
    if (data.ok) {
      stat.textContent = '✓';
      stat.style.color = '#4ade80';
      btn.style.display = 'none';
      // Remove from _missingAll so count updates
      const globalIdx = _missingAll.indexOf(item);
      if (globalIdx !== -1) _missingAll.splice(globalIdx, 1);
      document.getElementById('missing-badge').textContent =
        _missingAll.length ? `${_missingAll.length} missing` : 'All covered ✓';
      toast(`Cover saved for "${item.title}"`);
    } else {
      stat.textContent = '✗';
      stat.style.color = '#f87171';
      btn.disabled = false;
      btn.innerHTML = '<i class="fas fa-cloud-download-alt"></i> Fetch';
      toast('Failed to save cover');
    }
  } catch(e) {
    stat.textContent = '✗';
    stat.style.color = '#f87171';
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-cloud-download-alt"></i> Fetch';
  }
  _cprevData = null;
}

function declineCover() {
  if (!_cprevData) return;
  const { idx } = _cprevData;
  const btn = document.getElementById(`fbtn-${idx}`);
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-cloud-download-alt"></i> Fetch';
  }
  document.getElementById('cprev-overlay').classList.remove('open');
  _cprevData = null;
}

// ── Logo click — home + easter egg (settings page) ───────────────────────────
let _logoClicks = 0, _logoTimer = null;
function logoClick() {
  _logoClicks++;
  clearTimeout(_logoTimer);
  if (_logoClicks >= 5) {
    // 5 rapid clicks → secret credits page
    _logoClicks = 0;
    window.location.href = '/credits';
    return;
  }
  // Single click on settings → go back to library
  _logoTimer = setTimeout(() => {
    if (_logoClicks > 0 && _logoClicks < 5) {
      _logoClicks = 0;
      window.location.href = '/';
    }
  }, 350);
}

// ── Connectivity ──────────────────────────────────────────────────────────────
let _isOnline = true;

async function checkConnectivity() {
  try {
    const data = await fetch('/api/connectivity').then(r => r.json());
    _isOnline = data.online;

    // Nav pill
    const pill = document.getElementById('sconn-pill');
    const dot  = document.getElementById('sconn-dot');
    const lbl  = document.getElementById('sconn-lbl');
    pill.style.display = '';
    pill.className   = data.online ? 'online' : 'offline';
    dot.textContent  = '●';
    lbl.textContent  = data.online ? ' Online' : ' Offline';
    pill.title       = data.online
      ? `Internet connected (${data.latency_ms}ms via ${data.host})`
      : 'No internet — TMDB features unavailable';

    // Offline banners
    document.getElementById('tmdb-offline-banner').classList.toggle('show', !data.online);
    document.getElementById('covers-offline-banner').classList.toggle('show', !data.online);

    // Disable/enable internet-dependent buttons
    const netBtns = document.querySelectorAll('.net-btn');
    netBtns.forEach(b => {
      b.disabled = !data.online;
      b.title    = data.online ? '' : 'No internet connection';
    });

    // Fetch buttons in missing covers list
    document.querySelectorAll('.fetch-btn:not([style*="display: none"])').forEach(b => {
      if (!b.closest('#mrow-') || !b.querySelector('.fa-check')) {  // skip already-done rows
        b.disabled = !data.online;
        if (!data.online) b.title = 'No internet connection';
      }
    });
  } catch(e) {
    _isOnline = false;
  }
}

// ── Broken File Paths ─────────────────────────────────────────────────────────
let _brokenAll    = [];
let _bpFilter     = 'all';

function _filteredBroken() {
  return _bpFilter === 'all' ? _brokenAll
    : _brokenAll.filter(b => b.type === _bpFilter);
}

async function loadBrokenPaths() {
  document.getElementById('bp-badge').textContent = '…';
  document.getElementById('bp-list').innerHTML =
    '<div class="broken-row" style="justify-content:center;color:var(--muted);font-size:.8rem;padding:22px"><i class="fas fa-spinner fa-spin" style="margin-right:6px"></i>Scanning…</div>';
  try {
    const data = await fetch('/api/broken_paths').then(r => r.json());
    _brokenAll = data.items || [];

    // Badge
    const badge = document.getElementById('bp-badge');
    badge.textContent = _brokenAll.length
      ? `${_brokenAll.length} of ${data.total_checked} broken`
      : `All ${data.total_checked} OK ✓`;
    badge.style.color = _brokenAll.length ? '#f87171' : '#4ade80';

    // Drive offline warning
    const warnBox  = document.getElementById('bp-drive-warn');
    const warnText = document.getElementById('bp-drive-warn-text');
    if (data.offline_drives && data.offline_drives.length) {
      warnText.textContent =
        `⚠ Drive(s) ${data.offline_drives.join(', ')} may be offline or disconnected — ` +
        `all files on those drives appear broken. Reconnect the drive before removing entries.`;
      warnBox.style.display = 'flex';
    } else {
      warnBox.style.display = 'none';
    }

    // Purge button
    document.getElementById('bp-purge-btn').style.display =
      _brokenAll.length ? '' : 'none';

    renderBrokenList();
  } catch(e) {
    document.getElementById('bp-badge').textContent = 'Error';
    document.getElementById('bp-list').innerHTML =
      '<div class="broken-row" style="justify-content:center;color:#f87171;font-size:.8rem;padding:22px">Failed to scan — is the server running?</div>';
  }
}

function setBpFilter(f) {
  _bpFilter = f;
  document.querySelectorAll('.mf-btn[data-bpf]').forEach(b =>
    b.classList.toggle('active', b.dataset.bpf === f));
  renderBrokenList();
}

function renderBrokenList() {
  const items = _filteredBroken();
  const el    = document.getElementById('bp-list');
  if (!items.length) {
    el.innerHTML = `<div class="broken-row" style="justify-content:center;color:var(--muted);font-size:.8rem;padding:22px">
      ${_bpFilter === 'all' ? 'No broken paths found ✓' : 'No broken paths in this category.'}
    </div>`;
    return;
  }
  el.innerHTML = items.map((item, idx) => {
    const tc = item.type === 'Movies' ? 'mt-movie' : 'mt-series';
    const tl = item.type === 'Movies' ? 'Movie' : 'Series';
    const fname = item.path.split('\\').pop() || item.path;
    return `<div class="broken-row" id="brow-${idx}">
      <span class="missing-type ${tc}">${tl}</span>
      <span class="broken-path" title="${esc2(item.path)}">
        <span class="broken-title">${esc2(item.title)}</span>
        <span class="broken-filepath">${esc2(item.path)}</span>
      </span>
      <button class="remove-btn" id="rbtn-${idx}" onclick="removeBrokenEntry(${idx})">
        <i class="fas fa-trash-alt"></i> Remove
      </button>
      <span class="row-status" id="bstatus-${idx}"></span>
    </div>`;
  }).join('');
}

async function removeBrokenEntry(idx) {
  const items = _filteredBroken();
  const item  = items[idx];
  const btn   = document.getElementById(`rbtn-${idx}`);
  const stat  = document.getElementById(`bstatus-${idx}`);

  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

  try {
    const r = await fetch('/api/remove_from_cache', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ path: item.path })
    });
    const data = await r.json();
    if (data.ok) {
      stat.textContent = '✓';
      stat.style.color = '#4ade80';
      btn.style.display = 'none';
      // Remove from master list
      const gi = _brokenAll.indexOf(item);
      if (gi !== -1) _brokenAll.splice(gi, 1);
      const badge = document.getElementById('bp-badge');
      badge.textContent = _brokenAll.length
        ? `${_brokenAll.length} broken` : 'All OK ✓';
      badge.style.color = _brokenAll.length ? '#f87171' : '#4ade80';
      document.getElementById('bp-purge-btn').style.display =
        _brokenAll.length ? '' : 'none';
      toast(`Removed "${item.title}" from library`);
    } else {
      stat.textContent = '✗';
      stat.style.color = '#f87171';
      btn.disabled = false;
      btn.innerHTML = '<i class="fas fa-trash-alt"></i> Remove';
    }
  } catch(e) {
    stat.textContent = '✗';
    stat.style.color = '#f87171';
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-trash-alt"></i> Remove';
  }
}

async function purgeAllBroken() {
  if (!_brokenAll.length) return;
  const msg = `Remove all ${_brokenAll.length} broken entries from the library?\n\nThis cannot be undone — run a scan to re-add them if the drive comes back online.`;
  if (!confirm(msg)) return;

  const btn = document.getElementById('bp-purge-btn');
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Removing…';

  try {
    const r = await fetch('/api/remove_from_cache', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ paths: _brokenAll.map(b => b.path) })
    });
    const data = await r.json();
    if (data.ok) {
      toast(`Removed ${data.removed} entries from library`);
      _brokenAll = [];
      document.getElementById('bp-badge').textContent = 'All OK ✓';
      document.getElementById('bp-badge').style.color = '#4ade80';
      btn.style.display = 'none';
      renderBrokenList();
    } else {
      btn.disabled = false;
      btn.innerHTML = '<i class="fas fa-trash-alt"></i> Remove All';
      toast('Failed to remove entries');
    }
  } catch(e) {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-trash-alt"></i> Remove All';
  }
}

// ── Export Library CSV ────────────────────────────────────────────────────────
async function exportLibraryCSV(btn) {
  const msg = document.getElementById('csv-msg');
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Preparing…';
  msg.textContent = '';
  try {
    const res = await fetch('/api/export_library_csv');
    if (!res.ok) throw new Error('Server error ' + res.status);
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = 'cinevault_library.csv';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    msg.style.color = '#4ade80';
    msg.textContent = '✓ Download started';
    toast('✅ CSV export downloaded');
  } catch(e) {
    msg.style.color = '#f87171';
    msg.textContent = '❌ Export failed — ' + e.message;
  }
  btn.disabled = false;
  btn.innerHTML = '<i class="fas fa-download"></i> Download CSV';
}

// ── Init ──────────────────────────────────────────────────────────────────────
loadStats();
loadPin();
loadTmdbToken();
loadMissingCovers();
loadBrokenPaths();
checkConnectivity();
setInterval(checkConnectivity, 60000);
</script>
</body>
</html>"""

# ── Launch ────────────────────────────────────────────────────────────────────
def _kill_stale_server():
    """Kill any existing pythonw process listening on port 5000."""
    try:
        result = subprocess.run(
            ['netstat', '-ano'],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if ':5000' in line and 'LISTENING' in line:
                pid = line.strip().split()[-1]
                subprocess.run(['taskkill', '/F', '/PID', pid],
                               capture_output=True, timeout=5)
                time.sleep(0.5)
                break
    except Exception:
        pass

if __name__ == '__main__':
    _kill_stale_server()
    def open_browser():
        time.sleep(1.5)
        webbrowser.open('http://localhost:5000')
    threading.Thread(target=open_browser, daemon=True).start()
    # pythonw.exe sets sys.stdout to None — guard all prints
    try:
        print('\n' + '='*52)
        print("  CineVault  v3")
        print('='*52)
        print('  Open:  http://localhost:5000')
        print('  Stop:  Ctrl+C')
        print('='*52 + '\n')
    except (AttributeError, OSError):
        pass
    import logging, sys
    if sys.stdout is None:   # running under pythonw.exe — silence Flask logs
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
    app.run(host='localhost', port=5000, debug=False, threaded=True)
