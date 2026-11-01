"""Build checksum-verified project-local runtimes without changing a service."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PREFIX = ROOT/'gateway-data/toolchains'
MANIFEST = ROOT/'deploy/runtime-versions.json'


def unpack(archive, target):
    # These are fixed, checksum-verified upstream releases, never user uploads.
    with tarfile.open(archive) as bundle:
        bundle.extractall(target, filter='data')


def download(spec, target):
    url = spec['url']
    if not url.startswith(('https://www.python.org/', 'https://github.com/openssl/openssl/releases/',
                           'https://www.sqlite.org/', 'https://nodejs.org/dist/', 'https://files.pythonhosted.org/', 'https://registry.npmjs.org/npm/-/', 'https://ftp.postgresql.org/pub/source/')):
        raise ValueError('unreviewed_runtime_source')
    with urllib.request.urlopen(url, timeout=60) as response, target.open('wb') as stream:  # noqa: S310 -- fixed HTTPS origins and release digests
        digest = hashlib.new(spec.get('algorithm', 'sha256'))
        while chunk := response.read(1024*1024):
            digest.update(chunk)
            stream.write(chunk)
    if digest.hexdigest() != spec['digest']:
        target.unlink()
        raise ValueError('runtime_checksum_mismatch')


def prepare():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('This reviewed native build targets macOS arm64 only.')
    spec = json.loads(MANIFEST.read_text())
    PREFIX.mkdir(parents=True, exist_ok=True)
    log = ROOT/'reports/dependency-hardening-2026-10-26/toolchain-build.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    os.nice(10)
    with tempfile.TemporaryDirectory(prefix='a2a-secure-build-',dir='/private/tmp') as folder, log.open('a') as output:
        work = Path(folder)
        def run(args, cwd, *, env=None):
            subprocess.run(args,cwd=cwd,env=env,stdout=output,stderr=subprocess.STDOUT,check=True)  # noqa: S603 -- reviewed build commands, no shell
        paths = {}
        for name in ('openssl','openssl_libpq','sqlite','python','node','npm','libpq'):
            item = spec[name]
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', item['directory']):
                raise ValueError('invalid_toolchain_directory')
            destination = PREFIX/item['directory']
            if destination.is_symlink():
                raise ValueError('toolchain_symlink_refused')
            paths[name] = destination
            if (destination/'toolchain-complete.json').is_file():
                continue
            if destination.exists():
                raise RuntimeError('incomplete_toolchain_requires_review: '+name)
            archive = work/(name+'.tar.gz')
            download(item, archive)
            source_dir = work/name
            source_dir.mkdir()
            unpack(archive, source_dir)
            source = next(source_dir.iterdir())
            if name in ('node', 'npm'):
                source.rename(destination)
            elif name in ('openssl', 'openssl_libpq'):
                mode = 'shared' if name == 'openssl_libpq' else 'no-shared'
                run(['./Configure','darwin64-arm64-cc','--prefix='+str(destination),'--libdir=lib',
                     '--openssldir='+str(paths['openssl']/'ssl'),mode,'no-tests'],source)
                run(['make','-j4'],source)
                run(['make','install_sw'],source)
            elif name == 'sqlite':
                run(['./configure','--prefix='+str(destination),'--disable-shared','--enable-static','--enable-fts5'],source)
                run(['make','-j4'],source)
                run(['make','install'],source)
            elif name == 'libpq':
                env = dict(os.environ)
                env.update(CPPFLAGS='-I'+str(paths['openssl_libpq']/'include'),
                           LDFLAGS='-L'+str(paths['openssl_libpq']/'lib'))
                run(['./configure','--prefix='+str(destination),'--with-ssl=openssl',
                     '--without-icu','--without-readline','--without-zlib'],source,env=env)
                for part in ('src/port','src/common','src/interfaces/libpq','src/bin/pg_config'):
                    run(['make','-j4','-C',part],source,env=env)
                for part in ('src/include','src/interfaces/libpq','src/bin/pg_config'):
                    run(['make','-C',part,'install'],source,env=env)
            else:
                env = dict(os.environ)
                env.update(CPPFLAGS='-I'+str(paths['sqlite']/'include'),LDFLAGS='-L'+str(paths['sqlite']/'lib'))
                run(['./configure','--prefix='+str(destination),'--with-openssl='+str(paths['openssl']),
                     '--with-ensurepip=no','--enable-loadable-sqlite-extensions'],source,env=env)
                run(['make','-j4'],source,env=env)
                run(['make','install'],source,env=env)
            (destination/'toolchain-complete.json').write_text(json.dumps(item,indent=2))
            print(json.dumps({'prepared':name,'version':item['version']}),flush=True)
        bundle = work/'certifi.whl'
        download(spec['trust_bundle'], bundle)
        with zipfile.ZipFile(bundle) as wheel:
            ca = wheel.read('certifi/cacert.pem')
        ca_path = paths['openssl']/'ssl/cert.pem'
        ca_path.parent.mkdir(parents=True, exist_ok=True)
        if ca_path.exists() and ca_path.read_bytes() != ca:
            raise RuntimeError('existing_toolchain_trust_bundle_changed')
        ca_path.write_bytes(ca)
        # Security-only CPython branches can retain old ensurepip wheels. Update
        # that bootstrap too, so a future ordinary venv does not reintroduce them.
        ensure = paths['python']/'lib/python3.11/ensurepip'
        initial = (ensure/'__init__.py').read_text()
        for package in spec['bootstrap']:
            archive = work/package['filename']
            download(package, archive)
            bundled = ensure/'_bundled'
            for old in bundled.glob(package['name']+'-*.whl'):
                if old.name != package['filename']:
                    old.unlink()
            (bundled/package['filename']).write_bytes(archive.read_bytes())
            variable = '_'+package['name'].upper()+'_VERSION'
            initial, count = re.subn(r'(?m)^'+variable+r' = "[^"]+"',
                variable+' = "'+package['version']+'"', initial)
            if count != 1:
                raise RuntimeError('unreviewed_ensurepip_shape')
        (ensure/'__init__.py').write_text(initial)
    return {name:str(path) for name,path in paths.items()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',action='store_true',required=True)
    parser.parse_args()
    print(json.dumps(prepare(),indent=2))


if __name__=='__main__':
    main()
