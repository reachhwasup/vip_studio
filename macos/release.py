"""Create signed GitHub update assets. The private key stays in macOS Keychain."""
import hashlib
import json
import plistlib
import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist'
APP = DIST / 'VIP Studio.app'
REPO = 'https://github.com/reachhwasup/vip_studio'
ACCOUNT = 'studio.vip.drama'


def main():
    info = plistlib.loads((APP / 'Contents/Info.plist').read_bytes())
    version = info['CFBundleShortVersionString']
    output = DIST / ('release-' + version)
    output.mkdir(exist_ok=True)
    archive = output / f'VIP-Studio-{version}-macos-arm64.zip'
    subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(APP), str(archive)], check=True)
    signer = ROOT / 'vendor/bin/sign_update'
    signature = subprocess.check_output([str(signer), '--account', ACCOUNT, '-p', str(archive)], text=True).strip()
    subprocess.run([str(signer), '--account', ACCOUNT, '--verify', str(archive), signature], check=True)
    sparkle = 'http://www.andymatuschak.org/xml-namespaces/sparkle'
    ET.register_namespace('sparkle', sparkle)
    feed = ET.Element('rss', {'version': '2.0'})
    channel = ET.SubElement(feed, 'channel')
    ET.SubElement(channel, 'title').text = 'VIP Studio Updates'
    ET.SubElement(channel, 'link').text = REPO + '/releases'
    item = ET.SubElement(channel, 'item')
    ET.SubElement(item, 'title').text = 'VIP Studio ' + version
    ET.SubElement(item, f'{{{sparkle}}}version').text = info['CFBundleVersion']
    ET.SubElement(item, f'{{{sparkle}}}shortVersionString').text = version
    ET.SubElement(item, f'{{{sparkle}}}minimumSystemVersion').text = info['LSMinimumSystemVersion']
    ET.SubElement(item, 'description').text = 'Download up to four episodes at once with a control on the Downloads page. Subtitle processing runs separately so new video downloads can continue, and generated captions are saved as SRT without extra transcript JSON files.'
    ET.SubElement(item, 'enclosure', {'url': f'{REPO}/releases/download/v{version}/{archive.name}', 'length': str(archive.stat().st_size), 'type': 'application/octet-stream', f'{{{sparkle}}}edSignature': signature})
    feed_path = output / 'appcast.xml'
    ET.ElementTree(feed).write(feed_path, encoding='utf-8', xml_declaration=True)
    # Signed feed as well as signed archives; Sparkle verifies the downloaded app.
    subprocess.run([str(signer), '--account', ACCOUNT, str(feed_path)], check=True)
    (output / 'latest.json').write_text(json.dumps({'version': version, 'platform': 'macos-arm64', 'download_url': f'{REPO}/releases/download/v{version}/VIP-Studio-{version}-macos-arm64.dmg'}, indent=2)+'\n')
    dmg = output / f'VIP-Studio-{version}-macos-arm64.dmg'
    shutil.copy2(DIST / 'VIP Studio-macOS-AppleSilicon.dmg', dmg)
    (output / 'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(asset.read_bytes()).hexdigest() + '  ' + asset.name + '\n' for asset in (archive, dmg)))
    print('Signed release assets:', output)


if __name__ == '__main__':
    main()
