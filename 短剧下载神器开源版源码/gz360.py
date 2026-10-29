"""Adapter for the public GZ360 web catalogue and its playable episode URLs."""
import json
import re
import threading
import time
from urllib.parse import urlparse

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

BASE = 'https://gz360.tv'
API = 'https://haiwaiapi.1fc8ab0.com/Pc/'
# Public wire-format constants from the site's web client, not account credentials.
KEY = b'181cc88340ae5b2b'
IV = b'4423d1e2773476ce'
_cache = {}
_lock = threading.Lock()


def identify(value):
    value = str(value or '').strip()
    match = re.fullmatch(r'gz360:(\d+)(?::(\d+))?', value)
    if match:
        return match.group(1), match.group(2)
    parsed = urlparse(value)
    if parsed.scheme in ('https', 'http') and parsed.hostname in ('gz360.tv', 'www.gz360.tv'):
        match = re.fullmatch(r'/videoDetail/(\d+)/?', parsed.path)
        if match:
            return match.group(1), None
    return None


def call(path, payload):
    encrypted = AES.new(KEY, AES.MODE_CBC, IV).encrypt(pad(json.dumps(payload).encode(), 16)).hex()
    try:
        response = requests.post(API + path, json={'params': encrypted},
                                 headers={'Referer': BASE + '/', 'Origin': BASE}, timeout=(5, 25))
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or result.get('code') != 200:
            raise ValueError('GZ360 could not serve this request. The title may be unavailable.')
        data = result.get('data')
        if isinstance(data, str):
            data = json.loads(unpad(AES.new(KEY, AES.MODE_CBC, IV).decrypt(bytes.fromhex(data)), 16))
        if not isinstance(data, dict):
            raise ValueError('Unexpected GZ360 catalogue format.')
        return data
    except requests.RequestException as exc:
        raise ValueError('Could not reach GZ360. Please retry later.') from exc
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError('GZ360 returned an unreadable catalogue response.') from exc


def search(keyword, page, category=''):
    types = {'movies': 1, 'movie': 1, '电影': 1, 'short dramas': 64, 'short drama': 64, '短剧': 64, 'drama': 2, '动漫': 4, 'anime': 4}
    tid = types.get(category.strip().lower(), 0)
    data = call('Search/GetConditionList', {'tid': tid, 'area': 0, 'year': 0, 'sort': 'd_addtime',
                'keywords': keyword, 'page': page, 'pageSize': 50})
    items = []
    for row in data.get('list', []):
        sid = str(row.get('vod_id', ''))
        if not sid.isdigit():
            continue
        title = str(row.get('vod_name') or '').strip()
        tags = ' / '.join(row.get('tags') or [])
        if category and not tid and category.lower() not in (title + ' ' + tags).lower():
            continue
        listed = row.get('vurlList')
        count = len(listed) if isinstance(listed, list) else None
        unavailable = count == 0
        episode_label = 'No episodes available' if unavailable else f'{count} episodes' if count is not None else 'Check episode availability'
        items.append({'drama_id': 'gz360:' + sid, 'title': title, 'author': 'GZ360',
                      'episodes': episode_label, 'duration': '-', 'online_time': row.get('vod_filmtime') or '-',
                      'category': tags, 'source': 'GZ360', 'source_url': BASE + '/videoDetail/' + sid,
                      'downloadable': not unavailable, 'availability': 'unavailable' if unavailable else 'available' if count is not None else 'unknown', 'cover': row.get('vod_pic') or '', 'desc': ''})
    return items


def detail(value):
    identity = identify(value)
    if not identity:
        raise ValueError('Use a GZ360 video detail link or a GZ360 catalogue result.')
    sid = identity[0]
    with _lock:
        cached = _cache.get(sid)
        if cached and time.monotonic() - cached[0] < 120:
            return cached[1]
    info = call('Resource/GetVodInfo', {'vod_id': sid}).get('vodInfo') or {}
    playlist = call('Resource/GetOnePlayList', {'vod_id': sid, 'pageSize': 0, 'page': 1})
    title = str(info.get('vod_name') or '').strip()
    if not title:
        raise ValueError('This GZ360 title was not found.')
    episodes, seen = [], set()
    for index, row in enumerate(playlist.get('urls') or [], 1):
        vid = str(row.get('vurl_id') or '')
        if not vid.isdigit() or vid in seen:
            continue
        seen.add(vid)
        # Preserve actual episode labels even when the source has a missing episode.
        name = str(row.get('name') or '')
        number = int(name) if name.isdigit() and int(name) > 0 else index
        episodes.append({'vid': f'gz360:{sid}:{vid}', 'ep': number,
                         'title': f'{title} Episode {number}', 'stream_url': row.get('url') or '',
                         'app_only': bool(row.get('isApp'))})
    result = {'series_id': 'gz360:' + sid, 'title': title, 'cover': info.get('pic') or '',
              'intro': str(info.get('vod_use_content') or ''), 'tags': info.get('videoTag') or [],
              'cast': [{'name': name, 'role': ''} for name in str(info.get('vod_actor') or '').split(',') if name],
              'release_date': info.get('vod_year') if info.get('vod_year') != '1970-01-01' else '',
              'source_url': BASE + '/videoDetail/' + sid, 'source': 'GZ360',
              'total': len(episodes), 'episodes': episodes,
              'episode_warning': '' if episodes else 'GZ360 lists this title but currently provides no episode playback links. Check the source page or try again later.'}
    with _lock:
        if len(_cache) >= 100:
            _cache.pop(next(iter(_cache)))
        _cache[sid] = (time.monotonic(), result)
    return result


def playable_url(episode):
    if episode.get('app_only'):
        raise ValueError('This GZ360 episode is available only in its own app.')
    url = episode.get('stream_url') or ''
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('GZ360 did not provide a playable HTTPS video for this episode.')
    if not parsed.path.lower().endswith(('.m3u8', '.mp4')):
        raise ValueError('This GZ360 playback format is not supported.')
    return url
