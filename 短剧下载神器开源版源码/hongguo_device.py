"""Hongguo registration and credential validation, independent of the UI/runtime.

Registration is a best-effort adapter for the existing provider, not an official
authentication API. Never substitute ANDROID_ID or random numbers for credentials.
"""
import gzip
import threading
import json
import re
import time
import uuid

import requests

class DeviceConfigurationError(ValueError):
    pass


CONFIG_LOCK = threading.RLock()


REGISTRATION_URL = 'https://log.snssdk.com/service/2/device_register/'


def credentials(data):
    if not isinstance(data, dict):
        raise DeviceConfigurationError('Provide numeric Hongguo device_id and install_id values in Settings → Device configuration.')
    result = {}
    for key in ('device_id', 'install_id'):
        value = str(data.get(key) or '').strip()
        if not re.fullmatch(r'[1-9][0-9]{0,29}', value):
            raise DeviceConfigurationError('Hongguo device_id and install_id must contain digits only and cannot be zero. Open Settings → Device configuration and use automatic setup. Mac serial numbers and hardware IDs do not work.')
        result[key] = value
    result['platform'] = str(data.get('platform') or 'android')
    return result


def make_identity():
    return {'openudid': uuid.uuid4().hex[:16], 'clientudid': str(uuid.uuid4()), 'cdid': str(uuid.uuid4())}


def register(device, identity, post=requests.post):
    from flurl.ttEncryptorUtil import ttEncrypt
    # Match the app profile already used by the parser; do not call the legacy
    # Douyin registration script, which runs network requests at import time.
    header = {
        'aid': 8662, 'app_name': 'novelread', 'package': 'com.phoenix.read',
        'display_name': '红果免费短剧', 'channel': 'update_64',
        'app_version': '7.1.3.32', 'version_code': 71332,
        'manifest_version_code': 71332, 'update_version_code': 71332,
        'sdk_version': '3.7.3', 'sdk_target_version': device['os_api'],
        'os': 'Android', 'os_version': device['os_version'], 'os_api': device['os_api'],
        'device_model': device['model'], 'device_brand': device['brand'],
        'device_manufacturer': device['manufacturer'], 'device_category': 'phone',
        'resolution': device['resolution'], 'density_dpi': device['dpi'],
        'cpu_abi': device['abi'], 'language': 'zh', 'access': 'wifi',
        **identity,
    }
    payload = {'magic_tag': 'ss_app_log', 'header': header, '_gen_time': int(time.time() * 1000)}
    params = {
        'aid': '8662', 'app_name': 'novelread', 'device_platform': 'android',
        'version_code': '71332', 'version_name': '7.1.3.32', 'channel': 'update_64',
        'manifest_version_code': '71332', 'update_version_code': '71332',
        'package': 'com.phoenix.read', 'resolution': device['resolution'].replace('x', '*'),
        'dpi': device['dpi'], 'host_abi': device['abi'],
        'device_type': device['model'], 'device_brand': device['brand'],
        'os_version': device['os_version'], 'os_api': device['os_api'],
        'tt_data': 'a', **identity,
    }
    response = post(REGISTRATION_URL, params=params,
                    data=ttEncrypt(gzip.compress(json.dumps(payload).encode())),
                    headers={'Content-Type': 'application/octet-stream;tt-data=a',
                             'User-Agent': f"com.phoenix.read/71332 (Linux; U; Android {device['os_version']}; zh_CN; {device['model']})"},
                    timeout=(10, 25))
    response.raise_for_status()
    return credentials(response.json())


PARSER_DEVICE_PROFILE = {
    'os_api': 36, 'os_version': '16', 'model': '25053RT47C',
    'brand': 'Redmi', 'manufacturer': 'Xiaomi',
    'resolution': '1280x2772', 'dpi': 520, 'abi': 'arm64-v8a',
}
