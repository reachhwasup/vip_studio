"""Download optional model files once; no video or subtitle files are modified."""
from pathlib import Path
import os
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
from huggingface_hub import snapshot_download

root = Path.home() / '.cache' / 'short-drama-downloader' / 'funasr'
revisions = {
    'fa-zh': 'd7701644d6e336f093501241beca010519c0986f',
    'paraformer-zh': 'd7811ee3ac581fbcfdeb37c98c6ba674028433dc',
    'fsmn-vad': 'df20e6b30c653645fa4ff125cacfcabd1020a669',
    'ct-punc': 'd0e55e2b8722a78b63705ff443d09c4f86e5d750',
}
for name, revision in revisions.items():
    print('Downloading ' + name, flush=True)
    snapshot_download('funasr/' + name, revision=revision, local_dir=root / name,
                      allow_patterns=['*.pt', '*.yaml', '*.json', '*.mvn', 'seg_dict'],
                      max_workers=2)
print('All local speech and alignment models downloaded.', flush=True)
