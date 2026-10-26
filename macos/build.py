"""Build a self-contained Apple Silicon macOS app; never packages runtime credentials."""
import hashlib
import json
import tarfile
import urllib.request
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '源码_开源版'
BUILD = ROOT / 'macos' / 'build'
DIST = ROOT / 'macos' / 'dist'
APP = DIST / 'VIP Studio.app'


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True)


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)
    vendor = ROOT / 'macos' / 'vendor'
    sparkle = json.loads((ROOT / 'macos' / 'sparkle.json').read_text())
    if not (vendor / 'Sparkle.framework').exists():
        vendor.mkdir(parents=True, exist_ok=True)
        archive = vendor / 'Sparkle.tar.xz'
        urllib.request.urlretrieve(sparkle['url'], archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != sparkle['sha256']:
            raise RuntimeError('Sparkle distribution checksum does not match.')
        with tarfile.open(archive) as bundle:
            bundle.extractall(vendor, filter='data')
    run('swiftc', '-O', '-target', 'arm64-apple-macosx13.0', SOURCE / 'subtitle_ocr.swift', '-o', BUILD / 'subtitle_ocr')
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise SystemExit('FFmpeg must be installed on the build machine.')
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--name', 'VIPStudioBackend',
        '--distpath', BUILD / 'bundled', '--workpath', BUILD / 'pyinstaller', '--specpath', BUILD,
        '--paths', SOURCE, '--paths', SOURCE / 'liushen', '--hidden-import', '1', '--collect-submodules', 'flurl',
        '--collect-all', 'Crypto', '--add-data', f'{SOURCE / "static"}:static',
        '--add-binary', f'{Path(ffmpeg).resolve()}:.', '--add-binary', f'{BUILD / "subtitle_ocr"}:.',
        ROOT / 'macos' / 'backend.py')
    if APP.exists():
        shutil.rmtree(APP)
    (APP / 'Contents' / 'MacOS').mkdir(parents=True)
    resources = APP / 'Contents' / 'Resources'
    resources.mkdir()
    shutil.copytree(BUILD / 'bundled' / 'VIPStudioBackend', resources / 'backend', symlinks=True)
    frameworks = APP / 'Contents' / 'Frameworks'
    frameworks.mkdir()
    shutil.copytree(vendor / 'Sparkle.framework', frameworks / 'Sparkle.framework', symlinks=True)
    run('swiftc', '-O', '-target', 'arm64-apple-macosx13.0', '-F', vendor, '-framework', 'Sparkle', '-Xlinker', '-rpath', '-Xlinker', '@executable_path/../Frameworks', ROOT / 'macos' / 'VIPStudio.swift', ROOT / 'macos' / 'DesktopFeatures.swift', ROOT / 'macos' / 'Updater.swift', '-o', APP / 'Contents' / 'MacOS' / 'VIPStudio')
    run('swift', ROOT / 'macos' / 'icon.swift', BUILD / 'VIPStudio.iconset')
    run('iconutil', '-c', 'icns', BUILD / 'VIPStudio.iconset', '-o', resources / 'VIPStudio.icns')
    info = {'CFBundleIconFile': 'VIPStudio.icns', 'CFBundleName': 'VIP Studio', 'CFBundleDisplayName': 'VIP Studio', 'CFBundleIdentifier': 'studio.vip.drama',
            'CFBundleExecutable': 'VIPStudio', 'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '1.6.14',
            'CFBundleVersion': '25', 'LSMinimumSystemVersion': '26.0', 'NSHighResolutionCapable': True,
            'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True},
            'SUFeedURL': 'https://github.com/reachhwasup/vip_studio/releases/latest/download/appcast.xml',
            'SUPublicEDKey': (ROOT / 'macos' / 'update-public-key.txt').read_text().strip(),
            'SUEnableAutomaticChecks': False, 'SUAutomaticallyUpdate': False, 'SUEnableSystemProfiling': False,
            'NSHumanReadableCopyright': 'VIP Studio'}
    with (APP / 'Contents' / 'Info.plist').open('wb') as file:
        plistlib.dump(info, file)
    # Include notices for the bundled executable and its libraries.
    notices = resources / 'ThirdPartyNotices'
    notices.mkdir()
    shutil.copy2(vendor / 'LICENSE', notices / 'Sparkle-LICENSE.txt')
    shutil.copy2(SOURCE / 'LICENSE', resources / 'LICENSE.txt')
    for directory in Path('/opt/homebrew/opt').glob('*'):
        for pattern in ('COPYING*', 'LICENSE*'):
            for license_file in directory.glob(pattern):
                if license_file.is_file():
                    shutil.copy2(license_file, notices / f'{directory.name}-{license_file.name}')
    run('codesign', '--force', '--deep', '--sign', '-', APP)
    run('codesign', '--verify', '--deep', '--strict', APP)
    installer = BUILD / 'installer'
    if installer.exists():
        shutil.rmtree(installer)
    installer.mkdir()
    shutil.copytree(APP, installer / APP.name, symlinks=True)
    (installer / 'Applications').symlink_to('/Applications')
    (installer / 'Install.txt').write_text('VIP Studio — Apple Silicon, macOS 26 or later.\nDrag VIP Studio to Applications, then open it.\nThis local build is not Developer ID notarized.\nQuit only after active downloads and subtitle jobs finish.\n')
    run('hdiutil', 'create', '-volname', 'VIP Studio', '-srcfolder', installer, '-ov', '-format', 'UDZO', DIST / 'VIP Studio-macOS-AppleSilicon.dmg')
    print(f'Built: {APP}')


if __name__ == '__main__':
    main()
