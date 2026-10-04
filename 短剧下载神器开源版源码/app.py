"""
短剧下载工具 · 开源版

启动：python app.py
API：
  - GET/POST /api/search
  - GET/POST /hg?vid=VIDEO_ID
"""
import importlib
import json
import logging
import os
import re
import sys
import threading
import tempfile
import subprocess
import shutil
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, request, send_from_directory


APP_DIR = Path(__file__).resolve().parent
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
}
ITEMS_PER_PAGE = 50


SOURCE_ALIASES = {
    "红果短剧": "hongguo",
    "红果短剧官网": "hongguo",
    "红果漫剧": "hongguo_manju",
    "红果免费漫剧": "hongguo_manju",
}


def load_dotenv_file(path: Path) -> None:
    """Load simple KEY=VALUE pairs from .env without adding a dependency."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv_file(APP_DIR / ".env")

if getattr(sys, "frozen", False):
    EXE_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", EXE_DIR / "_internal"))
else:
    RESOURCE_DIR = APP_DIR

LIUSHEN_DIR = RESOURCE_DIR / "liushen"
STATIC_DIR = RESOURCE_DIR / "static"

for path in (RESOURCE_DIR, LIUSHEN_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")

parser_module = importlib.import_module("1")


class _SkipProgressPolls(logging.Filter):
    """The page polls /api/progress about twice a second; keep those lines out of the log."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/progress" not in record.getMessage()


logging.getLogger("werkzeug").addFilter(_SkipProgressPolls())
handle_video_request = parser_module.handle_video_request
from subtitle_formats import import_subtitles, normalize_segments, export_subtitles
from subtitles import create_subtitles, unavailable_reason as subtitles_unavailable_reason  # noqa: E402


# ───────────────────────── 配置 ─────────────────────────

def get_config_path() -> Path:
    return parser_module.get_runtime_base_dir() / "config.json"


CONFIG_LOCK = threading.Lock()


def write_local_config(cfg: dict) -> None:
    path = get_config_path()
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(cfg, handle, ensure_ascii=False, indent=2)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def mask_value(value: str) -> str:
    value = str(value or "")
    if len(value) <= 6:
        return "*" * len(value)
    return value[:3] + "*" * (len(value) - 6) + value[-3:]


def read_local_config() -> dict:
    path = get_config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@app.route("/api/config", methods=["GET"])
def get_config():
    cfg = read_local_config()
    device_id = os.getenv("DUANJU_DEVICE_ID") or str(cfg.get("device_id", ""))
    install_id = os.getenv("DUANJU_INSTALL_ID") or str(cfg.get("install_id", ""))
    platform = os.getenv("DUANJU_PLATFORM") or str(cfg.get("platform", "android"))
    return jsonify({
        "configured": bool(device_id and install_id),
        "device_id_masked": mask_value(device_id),
        "install_id_masked": mask_value(install_id),
        "platform": platform or "android",
        "config_path": str(get_config_path()),
    })


@app.route("/api/config", methods=["POST"])
def save_config():
    data = request.get_json(silent=True) or {}
    device_id = str(data.get("device_id", "")).strip()
    install_id = str(data.get("install_id", "")).strip()
    platform = str(data.get("platform", "android")).strip() or "android"

    if not device_id or not install_id:
        return jsonify({"error": "device_id and install_id are required"}), 400

    with CONFIG_LOCK:
        cfg = read_local_config()
        cfg.update(device_id=device_id, install_id=install_id, platform=platform)
        write_local_config(cfg)
    return jsonify({"ok": True, "config_path": str(get_config_path())})


@app.route("/api/download-path", methods=["GET", "POST"])
def download_path_setting():
    if request.method == "GET":
        return jsonify({"download_path": str(parser_module.get_download_dir())})
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("download_path"), str):
        return jsonify({"error": "Enter a download folder path"}), 400
    value = data["download_path"].strip()
    if not value:
        return jsonify({"error": "Enter a download folder path"}), 400
    try:
        folder = Path(value).expanduser()
        if not folder.is_absolute():
            return jsonify({"error": "Use an absolute folder path, such as ~/Downloads/Dramas"}), 400
        folder = folder.resolve()
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=folder) as probe:
            probe.write(b"download folder check")
            probe.flush()
        with CONFIG_LOCK:
            cfg = read_local_config()
            roots = cfg.setdefault("download_roots", {})
            previous = parser_module.get_download_dir()
            roots[parser_module.download_root_key(previous)] = str(previous)
            roots[parser_module.download_root_key(folder)] = str(folder)
            cfg["download_path"] = str(folder)
            write_local_config(cfg)
    except (OSError, ValueError) as exc:
        return jsonify({"error": f"Cannot use this folder: {exc}"}), 400
    return jsonify({"ok": True, "download_path": str(folder)})



FOLDER_PICKER_LOCK = threading.Lock()


def choose_download_folder():
    """Open a native dialog in a separate process, never on a Flask worker's UI thread."""
    if sys.platform == "darwin":
        command = ["osascript", "-e", 'try\nreturn POSIX path of (choose folder with prompt "Choose a download folder")\non error number -128\nreturn ""\nend try']
    elif sys.platform == "win32":
        command = ["powershell", "-NoProfile", "-STA", "-Command",
                   'Add-Type -AssemblyName System.Windows.Forms; $dialog = New-Object System.Windows.Forms.FolderBrowserDialog; $dialog.Description = "Choose a download folder"; if ($dialog.ShowDialog() -eq "OK") { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; [Console]::Write($dialog.SelectedPath) }; $dialog.Dispose()']
    elif shutil.which("zenity"):
        command = ["zenity", "--file-selection", "--directory", "--title=Choose a download folder"]
    else:
        raise RuntimeError("A folder picker is not available on this computer. Enter the folder path manually.")
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=120)
    if result.returncode != 0:
        if sys.platform not in {"darwin", "win32"} and result.returncode == 1:
            return ""
        raise RuntimeError("Could not open the folder picker. Enter the folder path manually.")
    return result.stdout.strip()


@app.route("/api/download-path/browse", methods=["POST"])
def browse_download_path():
    # A native dialog belongs to the local computer, not to a remote browser.
    origin = request.headers.get("Origin")
    if request.remote_addr not in {"127.0.0.1", "::1"} or (origin and urlparse(origin).netloc != request.host):
        return jsonify({"error": "Open the app on this computer to browse folders."}), 403
    if not FOLDER_PICKER_LOCK.acquire(blocking=False):
        return jsonify({"error": "A folder picker is already open. Select a folder or cancel it first."}), 409
    try:
        folder = choose_download_folder()
        return jsonify({"cancelled": not bool(folder), "download_path": folder})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Folder selection timed out. Try Browse again or enter a path."}), 408
    except (OSError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400
    finally:
        FOLDER_PICKER_LOCK.release()


# ───────────────────────── 搜索源 ─────────────────────────

def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def estimate_duration_from_episodes(episode_text: str) -> str:
    """Return a conservative series duration estimate when official duration is absent."""
    m = re.search(r"(\d+)", episode_text or "")
    if not m:
        return ""
    episodes = int(m.group(1))
    # Most short-drama episodes are about 1-2 minutes; use a neutral range.
    return f"About {episodes}-{episodes * 2} min (estimated at 1-2 min per episode)"


def public_unknown_time() -> str:
    return "Not published"


def fetch_text(url: str, timeout: int = 20) -> str:
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=timeout)
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def dedupe_items(items: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for item in items:
        key = item.get("drama_id") or item.get("source_url") or item.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def matches_keywords(item: dict, keyword: str, category_filter: str) -> bool:
    keys = []
    if keyword:
        keys.extend([x.strip() for x in re.split(r"[,，\s]+", keyword) if x.strip()])
    if category_filter:
        keys.extend([x.strip() for x in re.split(r"[,，]+", category_filter) if x.strip()])
    if not keys:
        return True
    haystack = " ".join(str(item.get(k, "")) for k in ("title", "category", "author", "desc", "source"))
    return any(k in haystack for k in keys)


def apply_page(items: list[dict], page: int) -> list[dict]:
    page = max(int(page or 1), 1)
    start = (page - 1) * ITEMS_PER_PAGE
    return items[start:start + ITEMS_PER_PAGE]


def hongguo_cover(url: str) -> str:
    """Poster URL at card size; the image host resizes on request."""
    return re.sub(r"tplv-shrink:\d+:\d+", "tplv-shrink:360:0", url or "")


def parse_hongguo_cards(html_text: str, base_url: str = "https://hongguoduanju.com") -> list[dict]:
    soup = BeautifulSoup(html_text, "html.parser")
    items = []
    for a in soup.select('a[href*="/detail?series_id="]'):
        href = a.get("href") or ""
        parsed = urlparse(urljoin(base_url, href))
        series_id = (parse_qs(parsed.query).get("series_id") or [""])[0]
        if not series_id:
            continue

        texts = [clean_text(x) for x in a.stripped_strings if clean_text(x)]
        text_join = " ".join(texts)
        episode = next((x for x in texts if re.search(r"全\d+集", x)), "")

        title = ""
        title_node = a.select_one('[class*="title"]')
        if title_node:
            title = clean_text(title_node.get_text(" "))
        if not title:
            # fallback: 去掉“全xx集”和标签后，取第一段不像标签的文本
            candidates = [x for x in texts if not re.fullmatch(r"全\d+集", x)]
            title = candidates[0] if candidates else text_join[:40]

        tag_texts = []
        for node in a.select('[class*="tag-text"], [class*="tag"] span'):
            t = clean_text(node.get_text(" "))
            if t and t not in tag_texts and len(t) <= 12:
                tag_texts.append(t)
        if not tag_texts:
            # fallback: anchor 文本中除标题/集数外的短词作为标签
            tag_texts = [x for x in texts if x not in {title, episode} and 1 <= len(x) <= 12][:5]

        items.append({
            "author": "Hongguo Short Drama",
            "title": title,
            "drama_id": series_id,
            "episodes": episode,
            "duration": estimate_duration_from_episodes(episode),
            "online_time": public_unknown_time(),
            "category": " / ".join(tag_texts),
            "source": "Hongguo Short Drama (official site)",
            "source_url": urljoin(base_url, href),
            "downloadable": True,
            "desc": text_join,
            "cover": hongguo_cover((a.find("img") or {}).get("src", "")),
            "duration_source": "estimated_from_episode_count" if episode else "not_public",
            "online_time_source": "not_public",
        })
    return dedupe_items(items)


HONGGUO_BASE = "https://hongguoduanju.com"
HONGGUO_HOT_PATH = "/category?sort_type=1"
HONGGUO_CONTENT_TYPES = {"真人剧": "real-drama", "漫剧": "comic-drama", "AI剧": "ai-drama"}
HONGGUO_ALL_TYPES = tuple(HONGGUO_CONTENT_TYPES.values())
HONGGUO_MANJU_TYPES = ("comic-drama", "ai-drama")
HONGGUO_LISTING_PAGES_PER_PAGE = 2  # site listing pages (24 items each) fetched per UI page
HONGGUO_LISTING_MAX_PAGES = 34  # the site serves at most 800 items (24 per page) per listing
HONGGUO_LISTING_TTL = 1800
HONGGUO_CATEGORY_TTL = 6 * 3600
_hongguo_listing_cache: dict[str, tuple[float, list[dict]]] = {}
_hongguo_category_cache: tuple[float, dict[str, dict[str, str]]] = (0.0, {})


def hongguo_categories() -> dict[str, dict[str, str]]:
    """Per content type: category name -> listing path, read from the site's own category navigation."""
    global _hongguo_category_cache
    cached_at, cached = _hongguo_category_cache
    if cached and time.time() - cached_at < HONGGUO_CATEGORY_TTL:
        return cached

    def nav_links(slug: str) -> dict[str, str]:
        try:
            soup = BeautifulSoup(fetch_text(f"{HONGGUO_BASE}/category/{slug}"), "html.parser")
        except Exception as exc:
            print(f"[search][hongguo] category nav failed type={slug} error={exc}")
            return {}
        links: dict[str, str] = {}
        for a in soup.select(f'a[href^="/category/{slug}/"]'):
            name = clean_text(a.get_text(" "))
            if name:
                links.setdefault(name, a["href"].split("?")[0])
        return links

    with ThreadPoolExecutor(max_workers=3) as pool:
        categories = dict(zip(HONGGUO_ALL_TYPES, pool.map(nav_links, HONGGUO_ALL_TYPES)))
    if any(categories.values()):
        _hongguo_category_cache = (time.time(), categories)
    return categories


def hongguo_listing_path(keyword: str, category_filter: str, slugs: tuple, default_path: str) -> tuple[str, bool]:
    """Listing path for the first term naming a content type or site category, and whether the keyword itself is one."""
    categories = hongguo_categories()
    names: dict[str, str] = {}
    for slug in reversed(slugs):  # earlier content types win when a category name repeats
        names.update(categories.get(slug, {}))
    names.update({label: f"/category/{slug}" for label, slug in HONGGUO_CONTENT_TYPES.items() if slug in slugs})
    keyword_is_category = keyword.strip() in names
    for term in re.split(r"[,，\s]+", f"{category_filter},{keyword}"):
        if term in names:
            return names[term], keyword_is_category
    return default_path, keyword_is_category


def fetch_hongguo_listing(path: str, site_page: int) -> list[dict]:
    url = f"{HONGGUO_BASE}{path}"
    if site_page > 1:
        url += f"{'&' if '?' in path else '?'}page={site_page}"
    cached = _hongguo_listing_cache.get(url)
    if cached and time.time() - cached[0] < HONGGUO_LISTING_TTL:
        return cached[1]
    try:
        items = parse_hongguo_cards(fetch_text(url), HONGGUO_BASE)
    except Exception as exc:
        print(f"[search][hongguo] failed url={url} error={exc}")
        return []
    if items:
        _hongguo_listing_cache[url] = (time.time(), items)
    return items


def fetch_hongguo_listings(path: str, site_pages: list[int]) -> list[dict]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        pages = list(pool.map(lambda p: fetch_hongguo_listing(path, p), site_pages))
    return [item for page_items in pages for item in page_items]


def search_hongguo_site(keyword: str) -> list[dict]:
    """Results from the site's own search page. The site serves one page (about 10) per keyword."""
    url = f"{HONGGUO_BASE}/search/{quote(keyword, safe='')}"
    html_text = ""
    for _ in range(2):  # the search page intermittently answers 500
        try:
            html_text = fetch_text(url)
            break
        except Exception as exc:
            print(f"[search][hongguo] failed url={url} error={exc}")
    marker = '"searchList":['
    pos = html_text.find(marker)
    if pos < 0:
        return []
    try:
        docs = json.JSONDecoder().raw_decode(html_text[pos + len(marker) - 1:])[0]
    except ValueError as exc:
        print(f"[search][hongguo] search data parse failed error={exc}")
        return []

    items = []
    for doc in docs:
        video = doc.get("video_data") or {}
        series_id = str(video.get("series_id") or "")
        if not series_id:
            continue
        title = clean_text(video.get("series_title") or doc.get("name") or "")
        episode = video.get("episode_right_text") or ""
        if not episode and video.get("episode_cnt"):
            episode = f"全{video['episode_cnt']}集"
        tags = []
        for cat in video.get("category_list") or []:
            name = cat.get("name") if isinstance(cat, dict) else cat
            if isinstance(name, str) and name and name not in tags:
                tags.append(name)
        online_time, time_source = public_unknown_time(), "not_public"
        try:
            online_time = time.strftime("%Y-%m-%d", time.localtime(int(video["create_time"])))
            time_source = "official"
        except (KeyError, TypeError, ValueError):
            pass
        items.append({
            "author": "Hongguo Short Drama",
            "title": title,
            "drama_id": series_id,
            "episodes": episode,
            "duration": estimate_duration_from_episodes(episode),
            "online_time": online_time,
            "category": " / ".join(tags[:5]),
            "source": "Hongguo Short Drama (official site)",
            "source_url": f"{HONGGUO_BASE}/detail?series_id={series_id}",
            "downloadable": True,
            "desc": clean_text(video.get("series_intro") or "")[:180],
            "cover": hongguo_cover(video.get("series_cover") or ""),
            "duration_source": "estimated_from_episode_count" if episode else "not_public",
            "online_time_source": time_source,
        })
    return items


def search_hongguo(
    keyword: str,
    page: int,
    category_filter: str,
    slugs: tuple = HONGGUO_ALL_TYPES,
    default_path: str = HONGGUO_HOT_PATH,
    site_search: bool = True,
) -> list[dict]:
    page = max(int(page or 1), 1)
    path, keyword_is_category = hongguo_listing_path(keyword, category_filter, slugs, default_path)

    if not keyword or keyword_is_category:
        # Browsing the default list or a site category: page through that listing on the site itself.
        per = HONGGUO_LISTING_PAGES_PER_PAGE
        return dedupe_items(fetch_hongguo_listings(path, list(range((page - 1) * per + 1, page * per + 1))))

    # Free-text keyword: title and tag matches from the full listings - every content type in
    # scope unless the filter names a category - after the site's own search (it serves about 10
    # and mixes content types, so it is skipped when the scope is narrower than the whole site).
    paths = [path] if path != default_path else [f"/category/{slug}" for slug in slugs]
    site_pages = list(range(1, HONGGUO_LISTING_MAX_PAGES + 1))
    listing = [x for p in paths for x in fetch_hongguo_listings(p, site_pages)]
    terms = keyword.split()
    matches = [x for x in listing if matches_keywords(x, keyword, "")]
    matches.sort(key=lambda x: not any(term in x["title"] for term in terms))  # title matches first
    site_items = search_hongguo_site(keyword) if site_search else []
    return apply_page(dedupe_items(site_items + matches), page)


def search_short_drama(keyword: str, page: int, source: str, category_filter: str) -> list[dict]:
    if SOURCE_ALIASES.get(source, source) == "hongguo_manju":
        return search_hongguo(
            keyword, page, category_filter, HONGGUO_MANJU_TYPES, "/category/comic-drama", site_search=False
        )
    return search_hongguo(keyword, page, category_filter)


@app.route("/api/search", methods=["GET", "POST"])
def api_search():
    payload = request.get_json(silent=True) if request.method == "POST" else request.args
    if not isinstance(payload, dict):
        return jsonify({"items": [], "message": "Search parameters must be a JSON object."}), 400
    raw_page = payload.get("page", 1)
    try:
        if isinstance(raw_page, bool) or not str(raw_page).isdigit():
            raise ValueError
        page = int(raw_page)
        if page < 1:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"items": [], "message": "Page must be a positive integer."}), 400
    keyword = str(payload.get("keyword", "")).strip()
    source = str(payload.get("source", "红果短剧")).strip()
    category_filter = str(payload.get("category_filter", "")).strip()

    try:
        items = search_short_drama(keyword, page, source, category_filter)
        if items:
            message = f"Search complete: page {page}, {len(items)} results."
        elif page > 1:
            message = f"No more results on page {page}."
        else:
            message = "No results. Try another keyword (Chinese keywords work best)."
        return jsonify({"items": items, "page": page, "source": source, "message": message})
    except Exception as exc:
        return jsonify({"items": [], "page": page, "source": source, "message": f"Search failed: {exc}"}), 500


# ───────────────────────── 页面和下载 ─────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.route("/src/<path:filename>")
def generated_video(filename):
    src_dir = parser_module.get_runtime_base_dir() / "src"
    return send_from_directory(str(src_dir), legacy_cover_alias(src_dir, filename))


def download_root(root_key: str):
    current = parser_module.get_download_dir()
    default = (parser_module.get_runtime_base_dir() / "src").resolve()
    roots = read_local_config().get("download_roots", {})
    roots = dict(roots)
    for folder in (current, default):
        roots[parser_module.download_root_key(folder)] = str(folder)
    return Path(roots[root_key]).resolve() if root_key in roots else None


@app.route("/downloads/<root_key>/<path:filename>")
def saved_download(root_key, filename):
    root = download_root(root_key)
    if root is None or Path(filename).suffix.lower() not in {".mp4", ".srt", ".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return jsonify({"error": "Download not found"}), 404
    target = (root / filename).resolve()
    if root not in target.parents:
        return jsonify({"error": "Download not found"}), 404
    return send_from_directory(str(root), legacy_cover_alias(root, filename))


TRENDING_URL = "https://hongguoduanju.com/rank/hot-real-drama"
_trending_cache = (0, [])


def parse_trending(html):
    soup = BeautifulSoup(html, 'html.parser')
    items, seen = [], set()
    for article in soup.select('article'):
        link = article.select_one('a[href*="/detail?series_id="]')
        title = article.select_one('h2')
        image = article.select_one('img')
        rank = article.select_one('[class*="badge-number"]')
        if not link or not title or not rank:
            continue
        sid = (parse_qs(urlparse(link['href']).query).get('series_id') or [''])[0]
        if not sid or sid in seen or not rank.get_text(strip=True).isdigit():
            continue
        seen.add(sid)
        items.append({'drama_id': sid, 'title': title.get_text(strip=True),
                      'rank': int(rank.get_text(strip=True)),
                      'cover': hongguo_cover(image.get('src', '')) if image else '',
                      'category': ' / '.join(n.get_text(strip=True) for n in article.select('[class*="categories"] span')),
                      'source_url': urljoin(TRENDING_URL, link['href']), 'source': 'Hongguo'})
    return sorted(items, key=lambda item: item['rank'])


@app.get('/api/trending')
def api_trending():
    global _trending_cache
    updated, items = _trending_cache
    if not items or time.time() - updated > 900 or request.args.get('refresh') == '1':
        try:
            items = parse_trending(fetch_text(TRENDING_URL))
            if not items:
                raise ValueError('No ranked dramas found')
            updated = time.time()
            _trending_cache = (updated, items)
        except Exception:
            app.logger.exception('Could not fetch Hongguo rankings')
            return jsonify({'error': 'Trending dramas are unavailable right now. Please try again.'}), 502
    return jsonify({'items': items, 'updated_at': updated, 'source_url': TRENDING_URL})


def library_roots():
    roots = [parser_module.get_download_dir(), parser_module.get_runtime_base_dir() / "src"]
    roots.extend(Path(value) for value in read_local_config().get("download_roots", {}).values())
    return list(dict.fromkeys(root.resolve() for root in roots))


@app.get("/api/library")
def api_library():
    dramas, seen = [], set()
    try:
        for root in library_roots():
            if not root.is_dir():
                continue
            root_key = parser_module.download_root_key(root)
            for directory, folders, filenames in os.walk(root, followlinks=False):
                folders[:] = [name for name in folders if not name.startswith('.')]
                folder = Path(directory)
                episodes = []
                def file_url(path):
                    return f"/downloads/{root_key}/{quote(path.relative_to(root).as_posix())}"
                for name in sorted(filenames, key=lambda name: [int(p) if p.isdigit() else p.lower() for p in re.split(r'(\d+)', name)]):
                    path = folder / name
                    if name.startswith('.') or path.suffix.lower() != '.mp4' or path.is_symlink():
                        continue
                    resolved = path.resolve()
                    if resolved in seen or root not in resolved.parents:
                        continue
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    if not stat.st_size:
                        continue
                    seen.add(resolved)
                    episodes.append({"title": path.stem, "url": file_url(path), "subtitle_url": file_url(path.with_suffix(".srt")) if path.with_suffix(".srt").is_file() and not path.with_suffix(".srt").is_symlink() else "", "size": stat.st_size, "modified": stat.st_mtime})
                if not episodes:
                    continue
                poster = next((folder / name for name in filenames if Path(name).stem.lower() == 'poster' and Path(name).suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp'} and not (folder / name).is_symlink()), None)
                dramas.append({"root": root_key, "folder": folder.relative_to(root).as_posix(), "title": folder.name if folder != root else "Other saved episodes", "poster": file_url(poster) if poster else '', "episodes": episodes, "modified": max(ep['modified'] for ep in episodes)})
        dramas.sort(key=lambda item: item['modified'], reverse=True)
        return jsonify({"items": dramas})
    except Exception:
        app.logger.exception('Could not read episode library')
        return jsonify({"error": "Could not read the download folders. Check your folder settings."}), 500


@app.post("/api/library/open-folder")
def api_library_open_folder():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get('folder'), str):
        return jsonify({"error": "Choose a library folder."}), 400
    root = download_root(str(payload.get('root', '')))
    if root is None:
        return jsonify({"error": "Folder not found."}), 404
    folder = (root / payload['folder']).resolve()
    if (folder != root and root not in folder.parents) or not folder.is_dir():
        return jsonify({"error": "Folder not found."}), 404
    try:
        if sys.platform == 'darwin':
            subprocess.Popen(['open', str(folder)])
        elif os.name == 'nt':
            os.startfile(str(folder))
        else:
            subprocess.Popen(['xdg-open', str(folder)])
        return jsonify({"ok": True})
    except OSError:
        return jsonify({"error": "Could not open the folder on this computer."}), 500


HISTORY_LOCK = threading.Lock()


def read_drama_history():
    path = parser_module.get_runtime_base_dir() / "drama_history.json"
    if not path.exists():
        return []
    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError("Invalid drama history file")
    return items


def remember_drama(detail=None, series_id="", episode=None):
    """History survives queue clearing and browser storage changes."""
    detail = detail or {}
    series_id = str(detail.get("series_id") or series_id or "").strip()
    if not series_id:
        return
    with HISTORY_LOCK:
        items = read_drama_history()
        old = next((item for item in items if item.get("series_id") == series_id), {})
        if not detail and not old:
            return
        entry = dict(old, series_id=series_id, updated_at=time.time())
        for key in ("title", "cover", "total"):
            if detail.get(key):
                entry[key] = detail[key]
        if episode is not None:
            try:
                number = int(episode)
                if number > 0:
                    entry["last_episode"] = number
                    entry["downloaded_episodes"] = sorted(set(entry.get("downloaded_episodes", [])) | {number})
            except (TypeError, ValueError):
                pass
        items = [entry] + [item for item in items if item.get("series_id") != series_id]
        path = parser_module.get_runtime_base_dir() / "drama_history.json"
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(items[:100], handle, ensure_ascii=False, indent=2)
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


@app.route("/api/drama-history", methods=["GET"])
def drama_history():
    try:
        with HISTORY_LOCK:
            items = read_drama_history()
        return jsonify({"items": items})
    except (OSError, ValueError):
        return jsonify({"error": "Could not read saved drama history."}), 500


@app.route("/api/episodes", methods=["GET", "POST"])
def api_episodes():
    val = ""
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        val = payload.get("id") or payload.get("url") or payload.get("series_id") or ""
    else:
        val = request.args.get("id") or request.args.get("url") or request.args.get("series_id") or ""
    val = str(val).strip()
    if not val:
        return jsonify({"error": "Missing id/url parameter"}), 400

    detail = parser_module.get_hongguo_series_detail(val)
    if not detail or not detail.get("vid_list"):
        return jsonify({"error": "Drama not found, or it has no episode list yet", "episodes": []}), 404

    episodes = []
    title = detail.get("title", "")
    for i, vid in enumerate(detail["vid_list"], 1):
        episodes.append({
            "vid": vid,
            "ep": i,
            "title": f"{title} Episode {i}" if title else f"Episode {i}",
        })

    release_date = ""
    try:
        release_date = time.strftime("%Y-%m-%d", time.localtime(int(detail["first_visible_time"])))
    except (KeyError, TypeError, ValueError):
        pass

    history_error = ""
    try:
        remember_drama(dict(detail, total=len(episodes)))
    except (OSError, ValueError) as exc:
        history_error = "Could not save this drama to history."
        app.logger.warning("Could not save drama history: %s", exc)
    return jsonify({
        "history_error": history_error,
        "series_id": detail["series_id"],
        "title": title,
        "cover": detail.get("cover", ""),
        "intro": clean_text(detail.get("intro", "")),
        "tags": detail.get("tags", []),
        "cast": detail.get("cast", []),
        "episode_text": detail.get("episode_text", ""),
        "release_date": release_date,
        "total": len(episodes),
        "episodes": episodes,
    })


def download_file_state(url) -> str:
    """"present" or "missing" for a saved file's link; "unknown" when it can't be checked.

    A download folder that isn't there right now (an unplugged drive, a renamed folder) says
    nothing about the files in it, so it counts as unknown rather than missing.
    """
    path = urlparse(str(url or "")).path
    if path.startswith("/downloads/"):
        parts = path.split("/", 3)
        if len(parts) != 4:
            return "unknown"
        root, relative = download_root(parts[2]), unquote(parts[3])
    elif path.startswith("/src/"):
        root, relative = (parser_module.get_runtime_base_dir() / "src").resolve(), unquote(path[len("/src/"):])
    else:
        return "unknown"
    if root is None or not root.is_dir():
        return "unknown"
    target = (root / relative).resolve()
    if root not in target.parents:
        return "unknown"
    if target.is_file():
        return "present"
    alias = legacy_cover_alias(root, relative)  # older poster links are served from the drama's shared poster
    return "present" if alias != relative and (root / alias).is_file() else "missing"


@app.route("/api/downloads/check", methods=["POST"])
def api_downloads_check():
    urls = (request.get_json(silent=True) or {}).get("urls") or []
    return jsonify({"states": {str(url): download_file_state(url) for url in urls[:5000] if url}})


def local_video_path(url):
    path = urlparse(str(url or "")).path
    if path.startswith("/downloads/"):
        parts = path.split("/", 3)
        root = download_root(parts[2]) if len(parts) == 4 else None
        relative = unquote(parts[3]) if len(parts) == 4 else ""
    elif path.startswith("/src/"):
        root = (parser_module.get_runtime_base_dir() / "src").resolve()
        relative = unquote(path[len("/src/"):])
    else:
        return None
    if root is None:
        return None
    target = (root / relative).resolve()
    return target if root in target.parents and target.suffix.lower() == ".mp4" and target.is_file() else None


from studio_features import register_studio_features
register_studio_features(app, lambda url: local_video_path(url))

SUBTITLE_JOBS = {}
SUBTITLE_JOBS_LOCK = threading.Lock()
SUBTITLE_REPAIR_POOL = ThreadPoolExecutor(max_workers=1)


def run_subtitle_repair(job_id, video_path):
    with SUBTITLE_JOBS_LOCK:
        SUBTITLE_JOBS[job_id]['status'] = 'running'
    try:
        srt, method = create_subtitles(video_path, parser_module.get_ffmpeg_binary())
        count = len(import_subtitles(srt.read_bytes(), srt.name)['segments'])
        result = {'status': 'done', 'captions': count, 'method': method, 'updated_at': time.time()}
    except Exception as exc:
        app.logger.exception('Subtitle regeneration failed')
        result = {'status': 'error', 'error': str(exc)}
    with SUBTITLE_JOBS_LOCK:
        SUBTITLE_JOBS[job_id].update(result)


@app.route('/api/subtitles/regenerate', methods=['GET', 'POST'])
def subtitle_regenerate():
    if request.method == 'GET':
        with SUBTITLE_JOBS_LOCK:
            job = SUBTITLE_JOBS.get(request.args.get('id', ''))
            return jsonify(dict(job)) if job else (jsonify({'error': 'Subtitle job not found. Please try again.'}), 404)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get('url'), str):
        return jsonify({'error': 'Choose a saved episode.'}), 400
    video = local_video_path(payload['url'])
    if video is None:
        return jsonify({'error': 'Saved episode not found.'}), 404
    url = urlparse(payload['url']).path
    key = str(video)
    with SUBTITLE_JOBS_LOCK:
        for existing in SUBTITLE_JOBS.values():
            if existing['key'] == key and existing['status'] in ('queued', 'running'):
                return jsonify(dict(existing)), 202
        if sum(job['status'] in ('queued', 'running') for job in SUBTITLE_JOBS.values()) >= 10:
            return jsonify({'error': 'The subtitle queue is full. Wait for an episode to finish.'}), 429
        if len(SUBTITLE_JOBS) >= 100:
            for old_id in list(SUBTITLE_JOBS):
                if SUBTITLE_JOBS[old_id]['status'] in ('done', 'error'):
                    del SUBTITLE_JOBS[old_id]
                    break
        job_id = os.urandom(16).hex()
        job = {'id': job_id, 'key': key, 'title': video.stem, 'status': 'queued', 'subtitle_url': url.rsplit('.', 1)[0] + '.srt'}
        SUBTITLE_JOBS[job_id] = job
        response = dict(job)
        SUBTITLE_REPAIR_POOL.submit(run_subtitle_repair, job_id, video)
    return jsonify(response), 202


def fetch_cover_image(url):
    """Fetch bounded image data only from the catalogue's public image CDNs."""
    for _ in range(5):
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or parsed.port not in (None, 443) or parsed.username or parsed.password or not any(host == domain or host.endswith("." + domain) for domain in ("byteimg.com", "fqnovelstatic.com", "bytegecko.com")):
            raise ValueError("The poster address is not a supported catalogue image URL.")
        with requests.get(url, timeout=(5, 15), stream=True, allow_redirects=False) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 10 * 1024 * 1024:
                    raise ValueError("Poster image exceeds 10 MB.")
                chunks.append(chunk)
            image = b"".join(chunks)
        if image.startswith(b"\xff\xd8\xff"):
            extension = ".jpg"
        elif image.startswith(b"\x89PNG\r\n\x1a\n"):
            extension = ".png"
        elif image.startswith(b"RIFF") and image[8:12] == b"WEBP":
            extension = ".webp"
        elif image.startswith((b"GIF87a", b"GIF89a")):
            extension = ".gif"
        else:
            raise ValueError("The poster response was not a supported image.")
        return image, extension
    raise ValueError("Too many poster redirects.")


COVER_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
COVER_LOCKS = [threading.Lock() for _ in range(32)]


def add_download_cover(result, preferred_cover=""):
    """Keep one poster per drama directory; reuse it before making any network request."""
    video = local_video_path(result.get("url"))
    if video is None:
        result["cover_error"] = "The video was not saved locally."
        return
    url_path = urlparse(result["url"]).path
    relative = url_path.split("/", 3)[-1] if url_path.startswith("/downloads/") else url_path[len("/src/"):]
    # Raw video IDs with no series metadata share the root, not a drama folder.
    grouped = len(Path(unquote(relative)).parts) > 1
    stem = "poster" if grouped else video.stem + ".poster"
    def finish(path):
        result["cover_url"] = url_path.rsplit("/", 1)[0] + "/" + quote(path.name)
        result.pop("cover_error", None)
    with COVER_LOCKS[hash(str(video.parent / stem)) % len(COVER_LOCKS)]:
        for extension in COVER_EXTENSIONS:
            existing = video.parent / (stem + extension)
            if existing.is_file() and not existing.is_symlink() and existing.stat().st_size:
                finish(existing)
                return
        # Upgrade old per-episode covers without downloading another image.
        legacy = sorted(video.parent.iterdir()) if grouped else [video.with_suffix(ext) for ext in COVER_EXTENSIONS]
        legacy = [path for path in legacy if path.suffix.lower() in COVER_EXTENSIONS and path.is_file() and not path.is_symlink() and path.stat().st_size and path.with_suffix(".mp4").is_file()]
        if legacy:
            poster = video.parent / (stem + legacy[0].suffix.lower())
            legacy[0].replace(poster)
            content = poster.read_bytes()
            for duplicate in legacy[1:]:
                if duplicate.read_bytes() == content:
                    duplicate.unlink()
            finish(poster)
            return
        sources = list(dict.fromkeys(str(x) for x in (preferred_cover, result.get("pic")) if x))
        error = "No poster is available for this drama."
        for source in sources:
            try:
                image, extension = fetch_cover_image(source)
                poster = video.parent / (stem + extension)
                with tempfile.NamedTemporaryFile(dir=video.parent, delete=False) as handle:
                    temp = Path(handle.name)
                    handle.write(image)
                try:
                    temp.replace(poster)
                finally:
                    temp.unlink(missing_ok=True)
                finish(poster)
                return
            except (OSError, ValueError, requests.RequestException) as exc:
                error = str(exc)
        result["cover_error"] = error


def legacy_cover_alias(root, filename):
    """Keep saved task links to migrated episode covers working."""
    root = Path(root).resolve()
    old = (root / filename).resolve()
    if root not in old.parents or old.exists() or old.suffix.lower() not in COVER_EXTENSIONS or not old.with_suffix(".mp4").is_file():
        return filename
    stem = "poster" if old.parent != root else old.stem + ".poster"
    for extension in COVER_EXTENSIONS:
        poster = old.parent / (stem + extension)
        if poster.is_file() and not poster.is_symlink():
            return str(poster.relative_to(root))
    return filename


@app.route("/api/download-cover", methods=["POST"])
def save_existing_cover():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("url"), str):
        return jsonify({"error": "Provide the downloaded video's URL."}), 400
    result = {"url": data["url"]}
    add_download_cover(result, data.get("cover", ""))
    if result.get("cover_error"):
        return jsonify({"error": result["cover_error"]}), 400
    return jsonify(result)


def add_subtitles(result: dict) -> None:
    """Write a .srt beside the downloaded video; record its URL, or why it could not be made."""
    url = str(result.get("url") or "")
    url_path = urlparse(url).path
    if url_path.startswith("/downloads/"):
        parts = url_path.split("/", 3)
        src_dir = download_root(parts[2]) if len(parts) == 4 else None
        relative = unquote(parts[3]) if len(parts) == 4 else ""
    else:
        src_dir = (parser_module.get_runtime_base_dir() / "src").resolve()
        relative = unquote(url_path[len("/src/"):]) if url_path.startswith("/src/") else ""
    if src_dir is None or not relative.endswith(".mp4"):
        result["subtitle_error"] = "the video was not saved locally, so there is nothing to transcribe"
        return
    video_path = (src_dir / relative).resolve()
    if src_dir not in video_path.parents or not video_path.is_file():
        result["subtitle_error"] = "the downloaded video file was not found"
        return
    try:
        srt_path, method = create_subtitles(video_path, parser_module.get_ffmpeg_binary())
    except Exception as exc:
        print(f"[subtitles] failed file={video_path.name} error={exc}")
        result["subtitle_error"] = str(exc)
        return
    result["subtitle_url"] = url[: -len(".mp4")] + ".srt"
    result["subtitle_source"] = method  # "picture": read from the frames; "audio": speech recognition


@app.route("/api/subtitles/import", methods=["POST"])
def subtitle_import():
    upload = request.files.get("file")
    if upload is None:
        return jsonify({"error": "Choose a subtitle file to import."}), 400
    data = upload.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        return jsonify({"error": "Subtitle files must be 5 MB or smaller."}), 413
    try:
        return jsonify(import_subtitles(data, upload.filename or ""))
    except (ValueError, UnicodeError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/subtitles/export", methods=["POST"])
def subtitle_export():
    if request.content_length and request.content_length > 10 * 1024 * 1024:
        return jsonify({"error": "Subtitle export is too large."}), 413
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("segments"), list):
        return jsonify({"error": "Provide a segments array."}), 400
    format_name = payload.get("format", "json")
    if not isinstance(format_name, str) or format_name not in {"srt", "vtt", "ass", "ssa", "json"}:
        return jsonify({"error": "Unsupported export format."}), 400
    segments = normalize_segments(payload["segments"])
    if not segments:
        return jsonify({"error": "There are no usable timed captions to export."}), 400
    content = export_subtitles(segments, format_name)
    return Response(content, content_type="text/plain; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="subtitles.{format_name}"',
    })


@app.route("/api/subtitles", methods=["GET"])
def api_subtitles():
    reason = subtitles_unavailable_reason()
    return jsonify({"available": not reason, "reason": reason})


def existing_download(series: str, episode: str):
    """The saved file for this series and episode number, if it is already in the download folder."""
    try:
        number = int(episode)
    except (TypeError, ValueError):
        return None
    relpath = parser_module.video_output_relpath(series, number)
    if not relpath or number <= 0:
        return None
    folder = parser_module.get_download_dir()
    path = folder / relpath
    if not path.is_file() or path.stat().st_size == 0:
        return None
    domain = parser_module.get_current_domain(request)
    return {
        "url": f"{domain}/downloads/{parser_module.download_root_key(folder)}/{quote(relpath)}",
        "size": parser_module.format_size(path.stat().st_size),
        "already_on_disk": True,
    }


@app.route("/hg", methods=["GET", "POST"])
def hg():
    video_id = request.args.get("vid") or (request.form.get("vid") if request.method == "POST" else None)
    if not video_id:
        return jsonify({"error": "Missing vid parameter"}), 400

    key = video_id.strip()
    parser_module.PROGRESS_LOCAL.key = key
    parser_module.set_progress(key, "resolving")
    try:
        result = None
        if request.values.get("skip_existing") == "1":
            result = existing_download(request.values.get("series", ""), request.values.get("episode", ""))
        if result is None:
            result = handle_video_request(key, request, max_retries=3)
        add_download_cover(result, request.values.get("cover", ""))
        if local_video_path(result.get("url")):
            try:
                remember_drama(series_id=request.values.get("series_id", ""), episode=request.values.get("episode") or result.get("episode"))
            except (OSError, ValueError) as exc:
                app.logger.warning("Could not update drama history: %s", exc)
        if request.values.get("subtitles") == "1":
            srt = local_video_path(result.get("url"))
            if result.get("already_on_disk") and srt is not None and srt.with_suffix(".srt").is_file():
                result["subtitle_url"] = result["url"][: -len(".mp4")] + ".srt"
            else:
                parser_module.set_progress(key, "subtitles")
                add_subtitles(result)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        parser_module.PROGRESS_LOCAL.key = ""
        parser_module.DOWNLOAD_PROGRESS.pop(key, None)


@app.route("/api/progress", methods=["GET"])
def api_progress():
    """Stage and percentage of the download in flight for this id; empty when there is none."""
    return jsonify(parser_module.DOWNLOAD_PROGRESS.get(request.args.get("vid", "").strip(), {}))


def _should_open_browser() -> bool:
    return os.getenv("OPEN_BROWSER", "1").strip().lower() not in {"0", "false", "no", "off"}


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.getenv("APP_PORT", "5000"))
    url = f"http://127.0.0.1:{port}"

    if _should_open_browser():
        def open_browser():
            import time
            time.sleep(1)
            webbrowser.open(url)

        threading.Thread(target=open_browser, daemon=True).start()

    print(f"Short Drama Downloader (open source edition): {url}")
    app.run(host="127.0.0.1", port=port, debug=os.getenv("FLASK_DEBUG", "0") == "1")
