"""Translate public Chinese drama titles and retain stable download names locally."""
import html
import json
import os
import re
import tempfile
import threading
from pathlib import Path
import requests

_lock = threading.Lock()


def translate_title(title, cache_path):
    title = str(title or '').strip()
    if not title or len(title.encode('utf-8')) > 500:
        raise ValueError('English titles need a drama title of up to 500 bytes.')
    if not re.search(r'[\u3400-\u9fff]', title):
        return title
    cache_path = Path(cache_path)
    with _lock:
        try:
            cache = json.loads(cache_path.read_text(encoding='utf-8'))
            if not isinstance(cache, dict):
                raise ValueError('Invalid title cache')
        except FileNotFoundError:
            cache = {}
        if isinstance(cache.get(title), str) and cache[title]:
            return cache[title]
        try:
            response = requests.get('https://api.mymemory.translated.net/get',
                                    params={'q': title, 'langpair': 'zh-CN|en'}, timeout=20)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or str(data.get('responseStatus')) != '200' or data.get('quotaFinished'):
                raise ValueError('Translation service is unavailable or its daily limit has been reached. Retry later or turn off English titles.')
            translated = data.get('responseData', {}).get('translatedText')
            if not isinstance(translated, str):
                raise ValueError('The translation service did not return a title.')
            translated = html.unescape(translated).strip()
            if not translated or len(translated) > 500 or re.search(r'[\u3400-\u9fff]', translated) or not re.search(r'[A-Za-z]', translated):
                raise ValueError('An English title could not be generated. Retry later or turn off English titles.')
        except (requests.RequestException, json.JSONDecodeError) as exc:
            raise ValueError('Title translation could not connect. Retry later or turn off English titles.') from exc
        cache[title] = translated
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, staged = tempfile.mkstemp(prefix='.title-cache-', dir=cache_path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(cache, handle, ensure_ascii=False)
            os.replace(staged, cache_path)
        finally:
            Path(staged).unlink(missing_ok=True)
        return translated
