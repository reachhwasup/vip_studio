"""
Python translation of 1.go — Short drama video parsing endpoint
Handles: video_model API → fallback_api → download & CENC decrypt → serve local MP4

Reference: decrypt.py logic for CENC decryption and spade_a key derivation.
"""

import os
import re
import json
import sys
import time
import base64
import hashlib
import binascii
import subprocess
import threading
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlsplit, parse_qsl, quote

import requests
from Crypto.Cipher import AES

LIUSHEN_DIR = Path(__file__).resolve().parent / "liushen"
if str(LIUSHEN_DIR) not in sys.path:
    sys.path.insert(0, str(LIUSHEN_DIR))


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


load_dotenv_file(Path(__file__).resolve().parent / ".env")

from flurl.core import core_sixgod
from hongguo_device import credentials, DeviceConfigurationError, register as register_hongguo, make_identity, PARSER_DEVICE_PROFILE, CONFIG_LOCK

# ─── Constants ───────────────────────────────────────────────────────────────

USER_AGENT = (
    "com.phoenix.read/71332 (Linux; U; Android 16; zh_CN; 25053RT47C; "
    "Build/BP2A.250605.031.A3; Cronet/TTNetVersion:04657795 2026-01-23 "
    "QuicVersion:c67e9834 2025-09-08)"
)

VIDEO_MODEL_URL_TEMPLATE = (
    "https://api5-normal-sinfonlineb.fqnovel.com/novel/player/multi_video_model/v1/"
    "?iid={install_id}&device_id={device_id}&ac=wifi&channel=update_64&aid=8662"
    "&app_name=novelread&version_code=71332&version_name=7.1.3.32"
    "&device_platform=android&os=android&ssmix=a&device_type=25053RT47C"
    "&device_brand=Redmi&language=zh&os_api=36&os_version=16"
    "&manifest_version_code=71332&resolution=1280*2772&dpi=520"
    "&update_version_code=71332&host_abi=arm64-v8a&dragon_device_type=phone"
    "&pv_player=71332&compliance_status=0&need_personal_recommend=1"
    "&player_so_load=1&is_android_pad_screen=0"
)

# ─── Helpers (stubs — adapt to your BaseEndpoint equivalents) ─────────────────

def load_local_config() -> Dict[str, Any]:
    """Load optional local runtime config from config.json beside script/exe."""
    config_path = get_runtime_base_dir() / "config.json"
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"[config] failed_to_read_config={config_path} error={exc}")
        return {}


def get_download_dir() -> Path:
    configured = load_local_config().get("download_path", "")
    return Path(configured).expanduser().resolve() if configured else (get_runtime_base_dir() / "src").resolve()



class DownloadFolderUnavailable(RuntimeError):
    pass


def require_download_dir():
    folder = get_download_dir()
    configured = bool(load_local_config().get('download_path'))
    try:
        if configured and not folder.is_dir():
            raise DownloadFolderUnavailable('The download folder is missing or disconnected. Select your download folder again.')
        if not configured:
            folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=folder) as probe:
            probe.write(b'folder check')
            probe.flush()
    except OSError:
        raise DownloadFolderUnavailable('The download folder is unavailable or cannot be written to. Select your download folder again.') from None
    return folder


def download_root_key(directory: Path) -> str:
    return hashlib.sha256(str(directory.resolve()).encode("utf-8")).hexdigest()[:20]


def get_device_keys() -> Dict[str, str]:
    """Return device credentials from env vars or local config.json.

    ?????????? device_id / install_id??????????
    ?? EXE ??????????????????? config.json?
    """
    config = load_local_config()

    device_id = (
        os.getenv("DUANJU_DEVICE_ID")
        or str(config.get("device_id") or config.get("DUANJU_DEVICE_ID") or "")
    ).strip()
    install_id = (
        os.getenv("DUANJU_INSTALL_ID")
        or str(config.get("install_id") or config.get("DUANJU_INSTALL_ID") or "")
    ).strip()
    platform = (
        os.getenv("DUANJU_PLATFORM")
        or str(config.get("platform") or config.get("DUANJU_PLATFORM") or "android")
    ).strip() or "android"

    return credentials({"device_id": device_id, "install_id": install_id, "platform": platform})


def build_liushen_device(device_keys: Dict[str, str]) -> Dict[str, str]:
    """Build the minimum device payload required by liushen signing."""
    return {
        "device_id": device_keys.get("device_id", ""),
        "iid": device_keys.get("install_id", ""),
        "install_id": device_keys.get("install_id", ""),
        "device_brand": "Redmi",
        "device_model": "25053RT47C",
        "device_type": "25053RT47C",
        "device_manufacturer": "Xiaomi",
        "os_version": "16",
        "version_name": "7.1.3.32",
        "ua": USER_AGENT,
    }


def sign_json_request_with_liushen(
    url: str,
    body_obj: Dict[str, Any],
    device_keys: Dict[str, str],
) -> Tuple[str, Dict[str, str], bytes]:
    """JSON dump before signing, then reuse the same bytes for the POST body."""
    body_text = json.dumps(body_obj, ensure_ascii=False, separators=(",", ":"))
    body_data = json.loads(body_text)
    body_bytes = body_text.encode("utf-8")

    ts = str(int(time.time() * 1000))
    base_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json; charset=utf-8,application/x-protobuf",
        "Content-Type": "application/json; charset=UTF-8",
        "x-xs-from-web": "0",
        "x-ss-req-ticket": ts,
        "x-tt-request-tag": "t=0;n=0",
        "sdk-version": "2",
        "passport-sdk-version": "50561",
        "x-vc-bdturing-sdk-version": "3.7.2.cn",
    }

    url_parts = urlsplit(url)
    base_url = f"{url_parts.scheme}://{url_parts.netloc}{url_parts.path}"
    params = dict(parse_qsl(url_parts.query, keep_blank_values=True))
    sign_headers, sign_url = core_sixgod(
        surl=base_url,
        params=params,
        data=body_data,
        devices=build_liushen_device(device_keys),
        header=base_headers,
        log=False,
    )
    return sign_url, sign_headers, body_bytes


def replace_failed_device(device_id: str, platform: str) -> None:
    """Mark a device as failed so it isn't reused. Hook for your device pool."""
    pass


def get_current_domain(request=None) -> str:
    """Return the current server's base URL for serving local files."""
    if request is not None:
        try:
            return request.host_url.rstrip("/")
        except Exception:
            pass
    return f"http://127.0.0.1:{os.getenv('APP_PORT', '5000')}"


def get_runtime_base_dir() -> Path:
    """Return the directory of the running exe or script."""
    if os.getenv("VIP_STUDIO_DATA_DIR"):
        return Path(os.environ["VIP_STUDIO_DATA_DIR"]).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


DEFAULT_TIMEOUT = 30
VIDEO_WORKER_POOL = ThreadPoolExecutor(max_workers=4)
# Live progress of each download in flight, keyed by the id the caller asked for (served by /api/progress).
DOWNLOAD_PROGRESS: Dict[str, Dict[str, Any]] = {}
# The key of the request the current thread is serving; set by the web layer before it starts a download.
PROGRESS_LOCAL = threading.local()


def set_progress(key: str, stage: str, percent: Optional[float] = None, size: int = 0) -> None:
    if key:
        DOWNLOAD_PROGRESS[key] = {"stage": stage, "percent": percent, "bytes": size}
FFMPEG_BIN = "ffmpeg"


def get_ffmpeg_binary() -> str:
    """Resolve ffmpeg for source checkout and PyInstaller onedir runs."""
    runtime_dir = get_runtime_base_dir()
    candidates = [
        runtime_dir / "ffmpeg.exe",
        runtime_dir / "??" / "ffmpeg.exe",
        Path(getattr(sys, "_MEIPASS", runtime_dir)) / "ffmpeg.exe",
        Path(getattr(sys, "_MEIPASS", runtime_dir)) / "??" / "ffmpeg.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return os.getenv("FFMPEG_BIN", FFMPEG_BIN)


def safe_filename_part(text: Any) -> str:
    """Make text usable as a file or folder name on Windows, macOS and Linux."""
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", str(text or ""))
    return re.sub(r"\s+", " ", text).strip(" .")[:80]


def video_output_relpath(series_name: Any = "", episode: Any = None) -> str:
    """Path under src/ for a downloaded episode: '<series>/<series> - Episode 007.mp4'.

    Returns "" when the series name is unknown, so the caller keeps the timestamp name.
    """
    series = safe_filename_part(series_name)
    if not series:
        return ""
    try:
        number = int(episode)
    except (TypeError, ValueError):
        number = 0
    if number <= 0:
        return f"{series}/{series}.mp4"
    return f"{series}/{series} - Episode {number:03d}.mp4"


def requested_output_relpath(request) -> str:
    """Output path from the optional series/episode parameters of the request."""
    for source in (getattr(request, "args", None), getattr(request, "form", None)):
        if source and source.get("series"):
            return video_output_relpath(source.get("series"), source.get("episode"))
    return ""


def curl_request(
    url: str,
    headers: Dict[str, str],
    post_body: Optional[bytes] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> bytes:
    """Minimal HTTP request helper — mimics Go's curlRequest."""
    if post_body is not None:
        resp = requests.post(url, headers=headers, data=post_body, timeout=timeout)
    else:
        resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.content


# ─── Main endpoint (matching 1.go Handle / resolveVideoURL) ──────────────────

_SERIES_CACHE: Dict[str, Dict[str, Any]] = {}
SERIES_CACHE_SECONDS = 60


class SeriesDetailUnavailable(RuntimeError):
    """A connection/service failure is different from a missing drama."""


def _saved_series_detail(sid):
    try:
        path = get_runtime_base_dir() / 'drama_history.json'
        if path.stat().st_size > 20 * 1024 * 1024:
            return None
        history = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(history, list):
            return None
        entry = next((row for row in history if isinstance(row, dict) and row.get('series_id') == sid), {})
        vids = entry.get('vid_list')
        if not isinstance(vids, list) or not 1 <= len(vids) <= 5000 or not all(isinstance(vid, str) and re.fullmatch(r'[1-9][0-9]{0,29}', vid) for vid in vids):
            return None
        return {key: entry[key] for key in ('series_id', 'title', 'cover', 'intro', 'tags', 'cast', 'episode_text', 'first_visible_time', 'fetched_at', 'vid_list', 'total') if key in entry}
    except (OSError, ValueError, TypeError):
        return None



def _app_series_detail(sid):
    """Use the service's signed episode endpoint when its website is unavailable."""
    keys = get_device_keys()
    url = build_video_model_url(keys['device_id'], keys['install_id']).replace('/multi_video_model/v1/', '/video_detail/v1/')
    url, headers, body = sign_json_request_with_liushen(url, {'series_id': sid}, keys)
    response = json.loads(curl_request(url, headers, body, 12))
    detail = response.get('data', {}).get('video_data', {})
    if str(detail.get('series_id_str') or detail.get('series_id')) != sid:
        raise ValueError('The service did not return the requested drama')
    rows = detail.get('video_list')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
        raise ValueError('The service returned no episode list')
    rows = sorted(rows, key=lambda row: int(row['vid_index']))
    vids = []
    for index, row in enumerate(rows, 1):
        vid = str(row.get('vid', ''))
        if int(row['vid_index']) != index or not re.fullmatch(r'[1-9][0-9]{0,29}', vid) or (row.get('series_id') and str(row['series_id']) != sid):
            raise ValueError('The service returned invalid episodes')
        vids.append(vid)
    if len(set(vids)) != len(vids) or int(detail.get('episode_cnt') or len(vids)) > len(vids):
        raise ValueError('The service returned an incomplete episode list')
    return {'series_id': sid, 'title': detail.get('series_title') or detail.get('series_name') or f'Drama_{sid}',
            'cover': detail.get('series_cover', ''), 'intro': detail.get('series_intro', ''), 'tags': [], 'cast': [],
            'episode_text': detail.get('episode_right_text', ''), 'total': len(vids), 'vid_list': vids, 'fetched_at': time.time()}


def get_hongguo_series_detail(val: str) -> Optional[Dict[str, Any]]:
    """Read the latest episode list; retain saved lists across temporary outages."""
    val = (val or '').strip()
    match = re.search(r'series_id=([0-9]+)', val)
    sid = match.group(1) if match else val if val.isdigit() and len(val) >= 15 else None
    if not sid and 'hongguoduanju.com' in val:
        match = re.search(r'/([0-9]+)', val)
        sid = match.group(1) if match else None
    if not sid:
        return None
    cached = _SERIES_CACHE.get(sid) or _saved_series_detail(sid)
    try:
        fresh = cached and 0 <= time.time() - float(cached.get('fetched_at', 0)) < SERIES_CACHE_SECONDS
    except (ValueError, TypeError):
        fresh = False
    if fresh:
        return dict(cached)
    url = f'https://hongguoduanju.com/detail?series_id={sid}'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'}
    for attempt in range(2):
        try:
            request_url = url if attempt == 0 else url + '&source=history'
            response = requests.get(request_url, headers=headers, timeout=(4, 8))
            if response.status_code == 404:
                return None
            response.raise_for_status()
            marker = re.search(r'_ROUTER_DATA\s*=\s*', response.text)
            if not marker:
                raise ValueError('Episode data was not included in the page')
            data, _ = json.JSONDecoder().raw_decode(response.text[marker.end():])
            detail = data.get('loaderData', {}).get('detail_page', {}).get('seriesDetail', {})
            vids = detail.get('vid_list', [])
            if not vids:
                return None
            if not isinstance(vids, list) or not all(isinstance(vid, str) and re.fullmatch(r'[1-9][0-9]{0,29}', vid) for vid in vids):
                raise ValueError('Invalid episode list')
            result = {
                'series_id': sid, 'title': detail.get('series_name') or f'Drama_{sid}',
                'cover': detail.get('series_cover', ''), 'intro': detail.get('series_intro', ''),
                'tags': [tag for tag in detail.get('tags') or [] if isinstance(tag, str)],
                'cast': [{'name': actor.get('nickname', ''), 'role': actor.get('sub_title', '')}
                         for actor in detail.get('celebrities') or [] if isinstance(actor, dict) and actor.get('nickname')],
                'episode_text': detail.get('episode_right_text', ''), 'first_visible_time': detail.get('first_visible_time'),
                'total': len(vids), 'vid_list': vids, 'fetched_at': time.time(),
            }
            if len(_SERIES_CACHE) >= 100:
                _SERIES_CACHE.pop(next(iter(_SERIES_CACHE)))
            _SERIES_CACHE[sid] = result
            return dict(result)
        except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
            if cached:
                return dict(cached, stale=True)
            # Rate limits and denied requests should not be retried immediately.
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            if status not in (403, 429) and attempt == 1:
                try:
                    result = _app_series_detail(sid)
                    if len(_SERIES_CACHE) >= 100:
                        _SERIES_CACHE.pop(next(iter(_SERIES_CACHE)))
                    _SERIES_CACHE[sid] = result
                    return dict(result)
                except (requests.RequestException, ValueError, RuntimeError, TypeError, KeyError, AttributeError):
                    pass
            if status in (403, 429) or attempt == 1:
                raise SeriesDetailUnavailable('Could not reach Hongguo to load the episode list. Please retry shortly.') from None
            time.sleep(0.25)
    return None


def handle_video_request(
    video_id: str,
    request=None,
    max_retries: int = 3,
    output_series: str = "",
) -> Dict[str, Any]:
    """
    Top-level handler. Given a video_id (or series URL/series_id), returns the flattened response payload.
    """
    video_id = (video_id or "").strip()
    if not video_id:
        raise ValueError("Missing video_id parameter")

    # Determine requested episode if specified (defaults to 1)
    ep = 1
    if request:
        try:
            raw_ep = request.args.get("ep") if hasattr(request, "args") else None
            if not raw_ep and hasattr(request, "form"):
                raw_ep = request.form.get("ep")
            if raw_ep:
                ep = int(raw_ep)
        except Exception:
            ep = 1

    # If input is a URL or explicit series link
    if video_id.startswith("http") or "series_id=" in video_id:
        series_info = get_hongguo_series_detail(video_id)
        if series_info and series_info.get("vid_list"):
            idx = max(0, min(ep - 1, len(series_info["vid_list"]) - 1))
            actual_vid = series_info["vid_list"][idx]
            res = resolve_video_url(
                actual_vid, request, max_retries,
                output_relpath=video_output_relpath(output_series or series_info.get("title", ""), idx + 1),
            )
            res["pic"] = series_info.get("cover") or res.get("pic", "")
            res["series_name"] = series_info.get("title", "")
            res["episode"] = idx + 1
            res["total_episodes"] = series_info.get("total", len(series_info["vid_list"]))
            return res

    # Otherwise try direct video_id resolution
    try:
        return resolve_video_url(
            video_id, request, max_retries, output_relpath=(video_output_relpath(output_series, request.values.get("episode", ep)) if output_series else requested_output_relpath(request))
        )
    except (DeviceConfigurationError, DownloadFolderUnavailable):
        raise
    except Exception as exc:
        # If direct resolution failed, check whether video_id is a series_id
        if video_id.isdigit():
            series_info = get_hongguo_series_detail(video_id)
            if series_info and series_info.get("vid_list"):
                idx = max(0, min(ep - 1, len(series_info["vid_list"]) - 1))
                actual_vid = series_info["vid_list"][idx]
                res = resolve_video_url(
                    actual_vid, request, max_retries,
                    output_relpath=video_output_relpath(output_series or series_info.get("title", ""), idx + 1),
                )
                res["pic"] = series_info.get("cover") or res.get("pic", "")
                res["series_name"] = series_info.get("title", "")
                res["episode"] = idx + 1
                res["total_episodes"] = series_info.get("total", len(series_info["vid_list"]))
                return res
        raise exc


_CONNECTION_RECOVERY_LOCK = threading.Lock()
_CONNECTION_RECOVERY_ATTEMPTS = {}


def recover_video_connection(video_id, failed_keys, payload):
    """Validate a replacement registration before saving it; recover once/minute.

    Other download workers reuse the winner's credentials. Configured environment
    overrides are owned by the caller and must never be replaced automatically.
    """
    if os.getenv('DUANJU_DEVICE_ID') or os.getenv('DUANJU_INSTALL_ID'):
        return None
    path = get_runtime_base_dir() / 'config.json'
    with _CONNECTION_RECOVERY_LOCK:
        def probe(keys):
            url = build_video_model_url(keys['device_id'], keys['install_id'])
            url, headers, body = sign_json_request_with_liushen(url, payload, keys)
            data = json.loads(curl_request(url, headers, body, 30))
            fallback, model = extract_fallback_api(data, video_id)
            return fallback, model, keys
        try:
            with CONFIG_LOCK:
                current = get_device_keys()
            if current != failed_keys:
                return probe(current)
            now = time.monotonic()
            if now - _CONNECTION_RECOVERY_ATTEMPTS.get(str(path), -float('inf')) < 60:
                return None
            _CONNECTION_RECOVERY_ATTEMPTS[str(path)] = now
            identity = make_identity()
            candidate = register_hongguo(PARSER_DEVICE_PROFILE, identity)
            recovered = probe(candidate)
            with CONFIG_LOCK:
                if get_device_keys() != failed_keys:
                    return None  # Preserve a connection edited during recovery.
                config = load_local_config()
                config.update(candidate)
                config['hongguo_registration_identity'] = identity
                config['hongguo_connection_refreshed_at'] = time.time()
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
                    temporary = Path(handle.name)
                    json.dump(config, handle, ensure_ascii=False, indent=2)
                try:
                    temporary.chmod(0o600)
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
            return recovered
        except (requests.RequestException, ValueError, OSError):
            return None  # Keep the old configuration when validation fails.


class VideoServiceUnavailable(RuntimeError):
    """Hongguo answered the request but supplied no usable video metadata."""


def resolve_video_url(
    video_id: str,
    request=None,
    max_retries: int = 3,
    output_relpath: str = "",
) -> Dict[str, Any]:
    """
    Full flow (with retries):
      1. get device_keys
      2. POST multi_video_model
      3. extract fallback_api
      4. download + CENC-decrypt best-quality video
    Returns a flattened response dict.
    """
    last_err: Optional[Exception] = None

    for attempt in range(max_retries):
        if attempt:
            time.sleep(min(2 ** attempt, 8))
        device_keys = get_device_keys()
        target_url = build_video_model_url(
            device_keys["device_id"], device_keys["install_id"]
        )

        post_payload = {
            "biz_param": {
                "detail_page_version": 0,
                "device_level": 3,
                "disable_digg_stat": False,
                "need_all_video_definition": True,
                "need_mp4_align": False,
                "use_os_player": False,
                "use_server_dns": False,
                "video_platform": 1024,
            },
            "mixed_video_id_map": {
                "1004": [video_id],
            },
        }
        signed_url, headers, post_body = sign_json_request_with_liushen(
            target_url, post_payload, device_keys
        )

        try:
            resp = curl_request(signed_url, headers, post_body, 30)
        except Exception as exc:
            last_err = Exception(f"video_model request failed: {exc}")
            time.sleep(0.1)
            continue

        if not resp or not resp.strip():
            last_err = VideoServiceUnavailable("Hongguo video service temporarily unavailable: the server returned an empty response. Please retry later.")
            recovered = None
            if attempt == max_retries - 1:
                set_progress(video_id, 'Refreshing Hongguo connection')
                recovered = recover_video_connection(video_id, device_keys, post_payload)
            if recovered is None:
                continue
            fallback_api, video_model, device_keys = recovered
        else:
            try:
                data = json.loads(resp)
            except (ValueError, UnicodeError):
                last_err = VideoServiceUnavailable("Hongguo video service temporarily unavailable: the server returned an unreadable response. Please retry later.")
                continue
            try:
                fallback_api, video_model = extract_fallback_api(data, video_id)
            except Exception as exc:
                last_err = exc
                continue

        try:
            result = download_and_decrypt_video(
                request,
                fallback_api,
                video_model,
                device_keys,
                video_id,
                max_retries=3,
                output_relpath=output_relpath,
            )
            return result
        except DownloadFolderUnavailable:
            raise
        except Exception as exc:
            last_err = exc
            time.sleep(0.1)
            continue

    if isinstance(last_err, VideoServiceUnavailable):
        raise VideoServiceUnavailable(str(last_err))
    raise Exception(f"Video request failed, retried {max_retries} times: {last_err}")


def build_video_model_url(device_id: str, install_id: str) -> str:
    """Build the multi_video_model request URL (uses url-encoded params)."""
    from urllib.parse import quote

    return VIDEO_MODEL_URL_TEMPLATE.format(
        install_id=quote(install_id, safe=""),
        device_id=quote(device_id, safe=""),
    )


# ─── Extract fallback_api ────────────────────────────────────────────────────

def extract_fallback_api(
    data: Dict[str, Any], video_id: str
) -> Tuple[str, Dict[str, Any]]:
    """Extract fallback_api URL from video_model response."""
    if not isinstance(data, dict):
        raise ValueError("Hongguo returned an invalid video response. Please retry later.")
    base = data.get("BaseResp")
    base = base if isinstance(base, dict) else {}
    code = data.get("Code") or data.get("code") or base.get("StatusCode")
    if code not in (None, 0, "0"):
        safe_code = re.sub(r"[^a-zA-Z0-9_-]", "", str(code))[:32] or "unknown"
        raise ValueError(f"Hongguo could not provide video information (service error {safe_code}). Retry later; if it continues, check the Hongguo connection in Settings.")
    data_map = data.get("data")
    if not isinstance(data_map, dict):
        raise ValueError("Hongguo returned no video information. Retry later or check the Hongguo connection in Settings.")

    video_entry: Optional[Dict[str, Any]] = None

    # 1) direct lookup
    if video_id in data_map and isinstance(data_map[video_id], dict):
        video_entry = data_map[video_id]

    # 2) fallback scan
    if video_entry is None:
        for v in data_map.values():
            if isinstance(v, dict):
                video_entry = v
                break
            if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                video_entry = v[0]
                break

    if video_entry is None:
        keys = list(data_map.keys())
        raise ValueError(
            f"video entry not found (looked for {video_id}, available keys: {keys})"
        )

    video_model: Optional[Dict[str, Any]] = None
    vm = video_entry.get("video_model")
    if isinstance(vm, str):
        video_model = json.loads(vm)
    elif isinstance(vm, dict):
        video_model = vm
    else:
        raise ValueError("video_model is empty or unknown format")

    fallback_raw = video_model.get("fallback_api")
    fallback_str = parse_fallback_api(fallback_raw)
    if not fallback_str:
        raise ValueError(f"fallback_api cannot be parsed: {type(fallback_raw)} => {fallback_raw}")

    return fallback_str, video_model


def parse_fallback_api(raw: Any) -> str:
    """Parse fallback_api value in various formats."""
    if isinstance(raw, str):
        if raw.startswith("{"):
            try:
                decoded = json.loads(raw)
                if isinstance(decoded, dict) and "fallback_api" in decoded:
                    return str(decoded["fallback_api"])
            except (json.JSONDecodeError, TypeError):
                pass
        if len(raw) > 10:
            return raw
    elif isinstance(raw, list) and len(raw) > 0:
        if isinstance(raw[0], str):
            return raw[0]
    elif isinstance(raw, dict):
        if "fallback_api" in raw:
            return str(raw["fallback_api"])
    return ""


# ─── Download & Decrypt ──────────────────────────────────────────────────────

def download_and_decrypt_video(
    request,
    fallback_api: str,
    video_model: Dict[str, Any],
    device_keys: Dict[str, str],
    video_id: str,
    max_retries: int = 3,
    output_relpath: str = "",
) -> Dict[str, Any]:
    """
    Call fallback_api → parse video_info.data → pick best quality →
    download encrypted MP4 → CENC decrypt → serve locally.
    Returns a flattened response dict.
    """
    current_url = fallback_api
    current_device_keys = device_keys
    last_err: Optional[Exception] = None

    for attempt in range(max_retries):
        headers = {"User-Agent": USER_AGENT}

        try:
            resp = curl_request(current_url, headers, None, 30)
        except Exception as exc:
            last_err = Exception(f"fallback_api request failed: {exc}")
        else:
            try:
                data = json.loads(resp)
            except Exception as exc:
                last_err = Exception(f"fallback_api JSON parse failed: {exc}")
            else:
                video_info = data.get("video_info", {})
                if not isinstance(video_info, dict):
                    video_info = {}
                video_data = video_info.get("data", {})
                if not isinstance(video_data, dict):
                    video_data = {}

                if not video_data:
                    last_err = Exception("fallback_api response structure abnormal")
                else:
                    # decode key_seed for URL decryption
                    key_seed_b64 = video_data.get("key_seed", "")
                    key_seed_raw = b64_decode_padded(key_seed_b64)

                    # pick best quality
                    video_list = video_data.get("video_list", {})
                    if isinstance(video_list, dict):
                        best_key, best_item = select_best_quality(video_list)
                        if best_key and best_item:
                            spade_a = best_item.get("spade_a", "")
                            content_key = None
                            if spade_a:
                                try:
                                    content_key = derive_content_key(spade_a)
                                except Exception:
                                    pass

                            raw_main_url = best_item.get("main_url", "")
                            if raw_main_url:
                                real_main_url = raw_main_url
                                if key_seed_raw and len(raw_main_url) > 10:
                                    try:
                                        dec = decrypt_spade_url(raw_main_url, key_seed_raw)
                                        if dec:
                                            real_main_url = dec
                                    except Exception:
                                        pass

                                current_domain = get_current_domain(request)
                                try:
                                    future = VIDEO_WORKER_POOL.submit(
                                        download_decrypt_and_serve,
                                        current_domain,
                                        real_main_url,
                                        content_key,
                                        output_relpath,
                                        getattr(PROGRESS_LOCAL, "key", ""),
                                    )
                                    local_url = future.result()
                                    if local_url:
                                        best_item["main_url"] = local_url
                                except DownloadFolderUnavailable:
                                    raise
                                except Exception as exc:
                                    # Nothing was saved. Report that, rather than handing back the remote
                                    # address as though the download had finished.
                                    raise Exception(f"Could not save the video: {exc}")

                            # only keep best quality
                            video_data["video_list"] = {best_key: best_item}

                    video_info["data"] = video_data
                    data["video_info"] = video_info
                    return build_response_payload(video_id, video_model, video_data, best_item)

        # retry with new device
        if attempt < max_retries - 1 and video_id:
            if current_device_keys:
                replace_failed_device(
                    current_device_keys.get("device_id", ""),
                    current_device_keys.get("platform", ""),
                )
            try:
                new_url, new_keys = refresh_fallback_url(video_id)
                if new_url:
                    current_url = new_url
                    current_device_keys = new_keys
            except Exception:
                pass

    raise Exception(
        f"fallback_api request failed, retried {max_retries} times: {last_err}"
    )


def download_decrypt_and_serve(
    current_domain: str,
    video_url: str,
    content_key: Optional[bytes],
    output_relpath: str = "",
    progress_key: str = "",
) -> Optional[str]:
    """Use ffmpeg to stream-copy the main video into a local MP4 file."""
    pipeline_start = time.perf_counter()
    local_url = stream_copy_video_with_ffmpeg(
        current_domain, video_url, content_key, output_relpath, progress_key
    )
    pipeline_seconds = time.perf_counter() - pipeline_start
    print(f"[timing] video_pipeline_seconds={pipeline_seconds:.3f}")
    return local_url


def stream_copy_video_with_ffmpeg(
    current_domain: str,
    video_url: str,
    content_key: Optional[bytes],
    output_relpath: str = "",
    progress_key: str = "",
) -> str:
    """Let ffmpeg pull the remote MP4 directly and write a local playable file."""
    stream_start = time.perf_counter()
    src_dir = require_download_dir()

    filename = output_relpath or f"video_{time.time_ns()}.mp4"
    filepath = src_dir / filename
    try:
        if not src_dir.is_dir():
            raise OSError('Download folder disconnected')
        filepath.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise DownloadFolderUnavailable('The download folder is unavailable. Select your download folder again.') from None

    # Written under a hidden temporary name and renamed only when complete, so a download that is
    # cut short never looks like a finished episode (the app skips episodes already on disk).
    partial = filepath.with_name("." + filepath.name + ".partial")

    ffmpeg_bin = get_ffmpeg_binary()
    command = [ffmpeg_bin, "-y", "-nostats", "-progress", "pipe:1"]
    if content_key:
        command.extend(["-decryption_key", content_key.hex()])
    command.extend([
        "-i",
        video_url,
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(partial),
    ])

    # ffmpeg reports its position as key=value lines (-progress); its banner carries the total duration.
    set_progress(progress_key, "downloading", 0.0)
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace"
        )
    except OSError as exc:
        raise Exception(f"Failed to start ffmpeg: {exc}")
    duration = 0.0
    percent: Optional[float] = None
    size = 0
    for line in process.stdout:
        line = line.strip()
        if not duration:
            found = re.search(r"Duration: (\d+):(\d\d):(\d\d(?:\.\d+)?)", line)
            if found:
                duration = int(found.group(1)) * 3600 + int(found.group(2)) * 60 + float(found.group(3))
        if line.startswith("total_size=") and line[11:].isdigit():
            size = int(line[11:])
        elif line.startswith("out_time_us=") and line[12:].isdigit() and duration:
            percent = min(100.0, int(line[12:]) / 1_000_000 / duration * 100)
        elif line.startswith("progress="):
            set_progress(progress_key, "downloading", percent, size)
    if process.wait() != 0:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            raise DownloadFolderUnavailable('The download folder is unavailable. Select your download folder again.') from None
        if not src_dir.is_dir():
            raise DownloadFolderUnavailable('The download folder disconnected during transfer. Select your download folder again.')
        raise Exception(f"Failed to stream video with ffmpeg (exit code {process.returncode})")
    try:
        os.replace(partial, filepath)
    except OSError:
        raise DownloadFolderUnavailable('The video could not be saved to the download folder. Select your download folder again.') from None

    stream_seconds = time.perf_counter() - stream_start
    print(f"[timing] stream_copy_seconds={stream_seconds:.3f}")
    if not current_domain or not isinstance(current_domain, str):
        current_domain = f"http://127.0.0.1:{os.getenv('APP_PORT', '5000')}"
    return f"{current_domain}/downloads/{download_root_key(src_dir)}/{quote(filename)}"


def refresh_fallback_url(video_id: str) -> Tuple[str, Dict[str, str]]:
    """Re-fetch fallback_api URL with a new device."""
    device_keys = get_device_keys()
    target_url = build_video_model_url(
        device_keys["device_id"], device_keys["install_id"]
    )

    post_payload = {
        "biz_param": {
            "detail_page_version": 0,
            "device_level": 3,
            "disable_digg_stat": False,
            "need_all_video_definition": True,
            "need_mp4_align": False,
            "use_os_player": False,
            "use_server_dns": False,
            "video_platform": 1024,
        },
        "mixed_video_id_map": {"1004": [video_id]},
    }
    signed_url, headers, post_body = sign_json_request_with_liushen(
        target_url, post_payload, device_keys
    )

    resp = curl_request(signed_url, headers, post_body, 30)
    data = json.loads(resp)

    fallback_api, _ = extract_fallback_api(data, video_id)
    return fallback_api, device_keys


# ─── CENC decryption (reference: decrypt.py) ─────────────────────────────────

def derive_content_key(spade_b64: str) -> bytes:
    """
    Derive 16-byte content_key from spade_a (Base64 string).
    Fully matches Go's deriveContentKey / Python's derive_key.
    """
    s = spade_b64.strip()
    m = 4 - len(s) % 4
    if m != 4:
        s += "=" * m

    raw = base64.b64decode(s)

    if len(raw) < 3:
        raise ValueError(f"spade_a too short: {len(raw)} bytes")

    v6 = raw[0] ^ raw[1] ^ raw[2]
    v8 = len(raw) - v6 + 47

    if v8 <= 0 or v8 > len(raw) * 2:
        raise ValueError(f"spade_a: computed v8={v8} out of range")
    if 1 + v8 > len(raw):
        v8 = len(raw) - 1
    if v8 < 33:
        raise ValueError(f"spade_a: v8={v8} too small (need >=33)")

    v13 = bytearray(raw[1 : 1 + v8])

    vA, vB = 85, 246
    for i in range(v8):
        popcnt = bin(i).count("1")
        if i & 1:
            v24 = vA
            vA = v13[i]
        else:
            v24 = vB
            vB = v13[i]
        v25 = v24 ^ v13[i]
        v26 = -21 - popcnt
        v13[i] = (v26 + v25) & 0xFF

    hex_str = bytes(v13[1:33]).decode("ascii")
    key = binascii.unhexlify(hex_str)
    return key


# ─── MP4 box parsing helpers ─────────────────────────────────────────────────


def select_best_quality(video_list: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Pick the best quality video entry (max vheight; tie-break on bitrate)."""
    best_key = ""
    best_item: Dict[str, Any] = {}
    best_height = 0
    for k, item in video_list.items():
        if not isinstance(item, dict):
            continue
        h = int(item.get("vheight", 0))
        if h > best_height:
            best_height = h
            best_key = k
            best_item = item
        elif h == best_height and best_item:
            cur_br = int(item.get("bitrate", 0))
            best_br = int(best_item.get("bitrate", 0))
            if cur_br > best_br:
                best_key = k
                best_item = item
    return best_key, best_item


def build_response_payload(
    video_id: str,
    video_model: Dict[str, Any],
    video_data: Dict[str, Any],
    best_item: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the flattened response payload expected by the caller."""
    pic = first_non_empty(
        best_item.get("cover"),
        best_item.get("poster"),
        video_model.get("origin_cover"),
        video_model.get("cover_url"),
        video_model.get("dynamic_cover"),
        video_model.get("cover"),
        video_data.get("cover"),
        video_data.get("poster"),
    )
    url = first_non_empty(
        best_item.get("main_url"),
        best_item.get("play_addr"),
        best_item.get("backup_url_1"),
        best_item.get("url"),
    )
    height = stringify_int(first_non_empty(best_item.get("vheight"), best_item.get("height")))
    width = stringify_int(first_non_empty(best_item.get("vwidth"), best_item.get("width")))

    return {
        "vid": video_id,
        "pic": normalize_media_url(pic),
        "url": normalize_media_url(url),
        "quality": format_quality(best_item, height),
        "duration": format_duration(first_non_empty(video_model.get("duration"), video_data.get("duration"))),
        "size": format_size(first_non_empty(best_item.get("size"), best_item.get("data_size"), best_item.get("file_size"))),
        "height": height,
        "width": width,
        "create_time": format_create_time(
            first_non_empty(
                video_model.get("create_time"),
                video_model.get("publish_time"),
                video_data.get("create_time"),
                video_data.get("publish_time"),
            )
        ),
    }


def first_non_empty(*values: Any) -> str:
    for value in values:
        normalized = unwrap_media_value(value)
        if normalized:
            return normalized
    return ""


def unwrap_media_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        for item in value:
            normalized = unwrap_media_value(item)
            if normalized:
                return normalized
        return ""
    if isinstance(value, dict):
        for key in ("url", "uri", "src", "download_url"):
            normalized = unwrap_media_value(value.get(key))
            if normalized:
                return normalized
        for key in ("url_list", "urls"):
            normalized = unwrap_media_value(value.get(key))
            if normalized:
                return normalized
    return ""


def normalize_media_url(value: str) -> str:
    if value.startswith("//"):
        return f"https:{value}"
    return value


def stringify_int(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value)


def format_quality(best_item: Dict[str, Any], height: str) -> str:
    label = first_non_empty(
        best_item.get("quality"),
        best_item.get("definition"),
        best_item.get("gear_name"),
        best_item.get("quality_desc"),
    )
    if label:
        return label
    if height:
        return f"{height}p"
    return ""


def format_duration(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        total_seconds = int(float(value))
    except (TypeError, ValueError):
        return str(value)

    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    return f"{minutes}m {seconds}s"


def format_size(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        size_bytes = float(value)
    except (TypeError, ValueError):
        return str(value)

    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    while size_bytes >= 1024 and unit_index < len(units) - 1:
        size_bytes /= 1024
        unit_index += 1
    return f"{size_bytes:.2f}{units[unit_index]}"


def format_create_time(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(
                timezone(timedelta(hours=8))
            ).isoformat()
        try:
            numeric = float(text)
        except ValueError:
            return text
        value = numeric

    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 1e12:
            timestamp /= 1000
        dt = datetime.fromtimestamp(timestamp, tz=timezone(timedelta(hours=8)))
        return dt.isoformat()
    return str(value)


# ─── Utility ─────────────────────────────────────────────────────────────────

def decrypt_spade_url(b64_str: str, key_seed: bytes) -> str:
    """
    AES-128-CBC decrypt a spade-encoded URL (used by content_endpoint).
    Matches Go's decryptSpadeURL.
    """
    if not b64_str:
        return ""

    raw = b64_decode_padded(b64_str)
    if len(raw) < 5:
        raise ValueError("Ciphertext too short")
    if raw[0] != 0xA8 or raw[2] != 0x01 or raw[3] != 0x00:
        raise ValueError("Ciphertext header format error")

    cipher_data = raw[4:]
    cipher_len = (len(cipher_data) // 16) * 16
    cipher_data = cipher_data[:cipher_len]

    constants = bytes([
        0x4D, 0xD4, 0xC2, 0xE6, 0xB8, 0x31, 0x62, 0x09, 0x0E, 0x52, 0xB3, 0xC7, 0xA6, 0x73, 0x3B, 0xA4,
        0x1C, 0xB2, 0x46, 0x2B, 0x82, 0x9A, 0xB5, 0x8A, 0x19, 0x6B, 0x39, 0xDB, 0x57, 0x17, 0x75, 0x24,
        0xF4, 0x9B, 0xAF, 0x7F, 0x08, 0xE8, 0xD6, 0x8D, 0x26, 0xA7, 0x2E, 0x37, 0xC1, 0xA9, 0x5A, 0x2F,
        0x1F, 0x05, 0xA5, 0x18, 0x92, 0xAE, 0xF2, 0x94, 0x97, 0x32, 0xB6, 0x2A, 0x38, 0xAA, 0xDD, 0x58,
    ])

    h1 = hashlib.sha512(key_seed).digest()
    h2 = hashlib.sha512(h1 + constants).digest()
    aes_key = h2[:16]
    iv = h2[16:32]

    cipher = AES.new(aes_key, AES.MODE_CBC, iv=iv)
    plaintext = cipher.decrypt(cipher_data)

    # PKCS7 unpad
    if plaintext:
        pad = plaintext[-1]
        if 1 <= pad <= 16 and pad <= len(plaintext):
            plaintext = plaintext[:-pad]

    return plaintext.rstrip(b"\x00").decode("utf-8", errors="replace")


def b64_decode_padded(s: str) -> bytes:
    """Relaxed base64 decode with auto-padding."""
    s = s.strip()
    pad = len(s) % 4
    if pad:
        s += "=" * (4 - pad)
    try:
        return base64.b64decode(s)
    except Exception:
        return base64.urlsafe_b64decode(s)


# ─── CLI entry point (for testing) ───────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python 1.py <video_id>")
        sys.exit(1)

    vid = sys.argv[1]
    print(f"Resolving video_id={vid} ...")
    try:
        result = handle_video_request(vid)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
