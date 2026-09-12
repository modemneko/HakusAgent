"""把 CI 构建产物（多平台安装包）同步到 v0.3.0 Release。"""
import io
import json
import pathlib
import ssl
import subprocess
import urllib.request
import zipfile

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

cred = subprocess.run(['git', 'credential', 'fill'],
                      input='protocol=https\nhost=github.com\n',
                      capture_output=True, text=True).stdout
token = [l.split('=', 1)[1] for l in cred.splitlines() if l.startswith('password=')][0]


def auth_get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'hakus-release', 'Authorization': f'Bearer {token}'})
    return urllib.request.urlopen(req, context=ctx)


def auth_json(url):
    with auth_get(url) as r:
        return json.loads(r.read())


class NoAuthRedirectHandler(urllib.request.HTTPRedirectHandler):
    """重定向到签名 URL 时剥离 Authorization，避免 Azure 校验冲突。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return urllib.request.Request(newurl, headers={'User-Agent': 'hakus-release'})


def download_artifact(art, dest):
    opener = urllib.request.build_opener(NoAuthRedirectHandler, urllib.request.HTTPSHandler(context=ctx))
    req = urllib.request.Request(art['archive_download_url'],
                                 headers={'User-Agent': 'hakus-release', 'Authorization': f'Bearer {token}'})
    with opener.open(req) as r, open(dest, 'wb') as f:
        f.write(r.read())


def upload(name, path, ctype):
    data = pathlib.Path(path).read_bytes()
    req = urllib.request.Request(f'{UPLOAD_BASE}?name={name}', data=data, method='POST',
                                 headers={'User-Agent': 'hakus-release', 'Authorization': f'Bearer {token}',
                                          'Content-Type': ctype})
    with urllib.request.urlopen(req, context=ctx) as r:
        print(f'  upload {name}: {r.status}', flush=True)


RUN_ID = '34694654980'
WANT = ['hakusai-android-arm64-apk', 'hakusai-android-x86_64-apk', 'desktop-macos-x64',
        'desktop-macos-arm64', 'desktop-linux',
        'hakuscli-windows-x64.exe', 'hakuscli-windows-arm64.exe', 'hakuscli-macos-arm64',
        'hakuscli-macos-x64', 'hakuscli-linux-x64', 'hakuscli-linux-arm64',
        'hakuscli-android-arm64.tar.gz']

arts_resp = auth_json(f'https://api.github.com/repos/modemneko/HakusAgent/actions/runs/{RUN_ID}/artifacts?per_page=100')
arts = arts_resp.get('artifacts', [])
rel = auth_json('https://api.github.com/repos/modemneko/HakusAgent/releases/tags/v0.3.0')
UPLOAD_BASE = rel['upload_url'].split('{')[0]

for name in WANT:
    art = next((a for a in arts if a['name'] == name), None)
    if not art:
        print(f'skip {name}: 无产物', flush=True)
        continue
    print(f'{name}: downloading {art["size_in_bytes"] // 1024 // 1024}MB...', flush=True)
    zip_path = f'{name}.artifact.zip'
    download_artifact(art, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(f'extract_{name}')
    inner = [p for p in pathlib.Path(f'extract_{name}').rglob('*') if p.is_file()]
    target = None
    for cand in inner:
        if name.startswith('hakusai-android') and cand.suffix == '.apk':
            target = cand
            break
        if 'macos' in name and cand.suffix == '.dmg':
            target = target or cand
        if name == 'desktop-linux' and cand.suffix in ('.deb', '.AppImage'):
            target = target or cand
    if not target:
        target = inner[0]
    ctype = 'application/vnd.android.package-archive' if target.suffix == '.apk' else 'application/octet-stream'
    upload(target.name, str(target), ctype)
    pathlib.Path(zip_path).unlink(missing_ok=True)
print('DONE')
