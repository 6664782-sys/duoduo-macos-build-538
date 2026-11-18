from pathlib import Path
import base64, hashlib, io, json, os, shutil, stat, subprocess, sys, zipfile
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def key():
    result = base64.b64decode(os.environ['DUODUO_BUILD_KEY'])
    assert len(result) == 32
    return result

def unpack():
    data = b''.join(p.read_bytes() for p in sorted(Path('.').glob('input.[0-9][0-9][0-9]')))
    assert hashlib.sha256(data).hexdigest() == Path('input.sha256').read_text().strip()
    assert data[:10] == b'DUODUO-CI1'
    source = AESGCM(key()).decrypt(data[10:22], data[22:], b'DuoduoBuild/v1/source')
    with zipfile.ZipFile(io.BytesIO(source)) as z:
        assert sum(i.file_size for i in z.infolist()) < 1024*1024*1024
        for name in z.namelist():
            p = Path(name)
            assert p.parts[0] == 'client' and '..' not in p.parts and not p.is_absolute()
        z.extractall()
    for p in Path('client').rglob('*.sh'):
        p.chmod(p.stat().st_mode | stat.S_IXUSR)

def build():
    arch = os.environ['BUILD_ARCH']
    log = Path('private-build.log').open('wb')
    if arch == 'x64':
        subprocess.run(['plutil','-replace','FLTEnableImpeller','-bool','NO','macos/Runner/Info.plist'],cwd='client',stdout=log,stderr=log,check=True)
    for command in [
        ['flutter','pub','get'],
        ['flutter','build','macos','--release','--dart-define=APP_ENV=stable','--dart-define-from-file=.duoduo-build-defines.json'],
    ]:
        result = subprocess.run(command,cwd='client',stdout=log,stderr=log)
        if result.returncode:
            print('Private build failed; details are included only in the encrypted artifact.')
            sys.exit(result.returncode)
    dist = Path('client/dist'); dist.mkdir(exist_ok=True)
    app = 'build/macos/Build/Products/Release/Duoduo.app'
    assert Path('client',app).is_dir()
    name = f'Duoduo-5.3.8-macOS-{arch}-unsigned'
    subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',app,'dist/'+name+'.zip'],cwd='client',stdout=log,stderr=log,check=True)
    subprocess.run(['hdiutil','create','-volname','朵朵云','-srcfolder',app,'-ov','-format','UDZO','dist/'+name+'.dmg'],cwd='client',stdout=log,stderr=log,check=True)
    (dist/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(dist.iterdir()) if p.suffix in {'.dmg','.zip'}))
    log.close()

def seal():
    arch = os.environ['BUILD_ARCH']
    payload = io.BytesIO()
    with zipfile.ZipFile(payload,'w',zipfile.ZIP_STORED) as z:
        log = Path('private-build.log')
        if log.exists(): z.write(log,'private-build.log')
        dist = Path('client/dist')
        if dist.exists():
            for p in dist.iterdir():
                if p.is_file(): z.write(p,'dist/'+p.name)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key()).encrypt(nonce,payload.getvalue(),f'DuoduoBuild/v1/artifact/{arch}'.encode())
    out = Path('sealed');out.mkdir(exist_ok=True)
    file = out/f'Duoduo-5.3.8-{arch}.enc'
    file.write_bytes(b'DUODUO-CI1'+nonce+ciphertext)
    file.with_suffix('.sha256').write_text(hashlib.sha256(file.read_bytes()).hexdigest()+'\n')

if __name__ == '__main__':
    {'unpack':unpack,'build':build,'seal':seal}[sys.argv[1]]()
