"""Check the installed environment against a reviewed, exact dependency profile."""
import argparse
from importlib import metadata
import json
from pathlib import Path
import re
import sqlite3
import ssl
import sys

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {'runtime':'requirements-runtime.lock','dev':'requirements-dev.lock',
            'security':'requirements-security.lock','anthropic':'requirements-anthropic-runtime.lock'}


def canonical(name):
    return re.sub(r'[-_.]+','-',name).lower()



def native_libraries(expected):
    """Check the libraries actually loaded by the macOS PostgreSQL driver."""
    if 'psycopg-c' not in expected or sys.platform != 'darwin':
        return {'checked':False,'ok':True,'scope':'OS-native library verification is separate on this platform.'}
    try:
        import ctypes
        import certifi
        import psycopg
        spec=json.loads((ROOT/'deploy/runtime-versions.json').read_text())
        toolchains=Path(sys.base_prefix).parent
        for key in ('libpq','openssl_libpq','openssl'):
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*',spec[key]['directory']):
                raise ValueError('invalid_native_profile')
        expected_pq=toolchains/spec['libpq']['directory']/'lib/libpq.5.dylib'
        expected_ssl=toolchains/spec['openssl_libpq']['directory']/'lib/libssl.3.dylib'
        system=ctypes.CDLL('/usr/lib/libSystem.B.dylib')
        system._dyld_image_count.restype=ctypes.c_uint32
        system._dyld_get_image_name.argtypes=[ctypes.c_uint32]
        system._dyld_get_image_name.restype=ctypes.c_char_p
        images={Path(system._dyld_get_image_name(i).decode()).resolve() for i in range(system._dyld_image_count())}
        linked=expected_pq.resolve() in images and expected_ssl.resolve() in images
        if not linked:
            return {'checked':True,'ok':False,'reason':'unreviewed_linked_native_library'}
        library=ctypes.CDLL(str(expected_ssl))
        library.OpenSSL_version.argtypes=[ctypes.c_int]
        library.OpenSSL_version.restype=ctypes.c_char_p
        tls=library.OpenSSL_version(0).decode('ascii')
        ca=toolchains/spec['openssl']['directory']/'ssl/cert.pem'
        trust=ca.read_bytes()==Path(certifi.where()).read_bytes()
        major,minor=map(int,spec['libpq']['version'].split('.'))
        okay=(psycopg.pq.__impl__=='c' and psycopg.pq.version()==major*10000+minor
              and tls.startswith('OpenSSL '+spec['openssl_libpq']['version']+' ') and trust)
        return {'checked':True,'ok':okay,'implementation':psycopg.pq.__impl__,
                'libpq_version':psycopg.pq.version(),'openssl':tls,'trust_bundle_matches':trust}
    except (ImportError,OSError,ValueError,KeyError,AttributeError):
        return {'checked':True,'ok':False,'reason':'native_dependency_verification_failed'}


def inspect(profile, *, check_native=True):
    expected = {canonical(name):version for name,version in re.findall(
        r'^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^\s\\]+)',(ROOT/PROFILES[profile]).read_text(),re.M)}
    installed = {canonical(d.metadata['Name']):d.version for d in metadata.distributions()}
    missing = sorted(set(expected)-set(installed))
    unexpected = sorted(set(installed)-set(expected)-{'pip'})
    mismatched = {name:{'expected':version,'installed':installed[name]} for name,version in expected.items()
                  if name in installed and installed[name]!=version}
    native = native_libraries(expected) if check_native else {'checked':False,'ok':True}
    supported_runtime = sys.version_info[:2] == (3, 11) and sys.version_info.micro >= 18
    return {'profile':profile,'ok':not (missing or unexpected or mismatched) and supported_runtime and native['ok'],
            'supported_security_runtime':supported_runtime,'native_libraries':native,
            'python':sys.version.split()[0],'openssl':ssl.OPENSSL_VERSION,
            'sqlite_stdlib':sqlite3.sqlite_version,'pip':installed.get('pip'),
            'installed_distributions':len(installed),'expected_distributions':len(expected),
            'missing':missing,'unexpected':unexpected,'mismatched':mismatched,
            'packages':dict(sorted(installed.items()))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',choices=PROFILES,default='runtime')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=inspect(args.profile)
    if args.output:
        args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='packages'},sort_keys=True))
    return 0 if result['ok'] else 1


if __name__=='__main__':
    raise SystemExit(main())
