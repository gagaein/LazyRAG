#!/usr/bin/env python3
"""Exercise a slim Python runtime and its real RAG bundle without an installer.

Run with the staged algorithm Python. Uses temporary data and child processes;
does not install into the base environment or touch the user's knowledge bases.
"""

import argparse
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import signal
import site
import socket
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, build_opener
import zipfile


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class HTTPSRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require(urlparse(newurl).scheme == 'https', 'Refusing an HTTP downgrade')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def base_imports():
    for name in ('spacy', 'pymilvus', 'milvus_lite'):
        require(importlib.util.find_spec(name) is None, f'{name} still exists in base; this is not a slim runtime')
    for name in ('dashscope', 'numpy', 'pandas', 'sklearn', 'umap', 'fitz', 'docx', 'pptx', 'openpyxl'):
        importlib.import_module(name)
        print(f'BASE_IMPORT_OK {name}', flush=True)


def overlay_imports(overlay):
    site.addsitedir(str(overlay))
    for name in ('lazyllm.tools.rag', 'spacy', 'pymilvus', 'milvus_lite', 'bm25s', 'Stemmer', 'sentencepiece', 'nltk'):
        importlib.import_module(name)
        print(f'OVERLAY_IMPORT_OK {name}', flush=True)


def serve(overlay, data, port):
    site.addsitedir(str(overlay))
    entry = next(e for e in importlib.metadata.distribution('milvus-lite').entry_points
                 if e.group == 'console_scripts' and e.name == 'milvus-lite')
    sys.argv = ['milvus-lite', 'server', '--data-dir', str(data), '--host', '127.0.0.1', '--port', str(port)]
    entry.load()()


def milvus_roundtrip(overlay, data, logs):
    site.addsitedir(str(overlay))
    from pymilvus import MilvusClient

    for cycle in (1, 2):
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        with (logs / f'milvus-server-{cycle}.log').open('w', encoding='utf-8') as log:
            command = [sys.executable, '-I', '-B', '-X', 'utf8', str(Path(__file__).resolve()),
                       '--worker', 'server', '--overlay', str(overlay), '--data', str(data), '--port', str(port)]
            server = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            client = None
            try:
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    require(server.poll() is None, f'Milvus server exited; see {log.name}')
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=.2):
                            break
                    except OSError:
                        time.sleep(.2)
                else:
                    raise RuntimeError('Milvus server readiness timeout')
                client = MilvusClient(uri=f'http://127.0.0.1:{port}', timeout=20)
                if cycle == 1:
                    client.create_collection(collection_name='component_check', dimension=2, timeout=20)
                    client.insert(collection_name='component_check',
                                  data=[{'id': 1, 'vector': [1., 0.], 'text': 'durable component data'}], timeout=20)
                else:
                    client.load_collection(collection_name='component_check', timeout=20)
                result = client.search(collection_name='component_check', data=[[1., 0.]], limit=1,
                                       output_fields=['text'], timeout=20)
                require(result and result[0] and result[0][0]['id'] == 1, f'Unexpected search result: {result}')
                print('MILVUS_INSERT_SEARCH_OK' if cycle == 1 else 'MILVUS_RESTART_SEARCH_OK', flush=True)
                if cycle == 1:
                    client.flush(collection_name='component_check', timeout=20)
                    print('MILVUS_FLUSH_OK', flush=True)
                else:
                    client.drop_collection(collection_name='component_check', timeout=20)
                    print('MILVUS_DROP_OK', flush=True)
            finally:
                try:
                    if client is not None:
                        client.close()
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait()


def run_child(name, arguments, logs):
    log_path = logs / f'{name}.log'
    command = [sys.executable, '-I', '-B', '-X', 'utf8', str(Path(__file__).resolve()), '--worker', name, *arguments]
    options = ({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt'
               else {'start_new_session': True})
    with log_path.open('w', encoding='utf-8') as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, **options)
        try:
            result = child.wait(timeout=240)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], stdout=log, stderr=log)
            else:
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            raise RuntimeError(f'{name} timed out; see {log_path}')
    if result != 0:
        lines = log_path.read_text(encoding='utf-8', errors='replace').strip().splitlines()
        detail = lines[-1][-2000:] if lines else 'No child output'
        raise RuntimeError(f'{name} failed (exit {result}): {detail}; see {log_path}')


def acquire_bundle(entry, directory, bundle_dir):
    if bundle_dir:
        archive = bundle_dir / entry['filename']
    else:
        address = entry['url']
        parsed = urlparse(address)
        require(parsed.scheme == 'https' and not parsed.username and not parsed.password,
                'Catalog must contain a direct HTTPS download URL without credentials')
        archive = directory / 'download.zip'
        size = 0
        with build_opener(HTTPSRedirects()).open(address, timeout=45) as response, archive.open('wb') as target:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                require(size <= entry['sizeBytes'], 'Download exceeds catalog size')
                target.write(chunk)
    require(archive.stat().st_size == entry['sizeBytes'], 'ZIP size does not match catalog')
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    require(digest.hexdigest() == entry['sha256'], 'ZIP SHA-256 does not match catalog')
    return archive


def extract_bundle(archive, directory, entry):
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read('bundle-manifest.json'))
        for key in ('id', 'revision', 'baseFingerprint', 'platform', 'arch', 'pythonAbi', 'packages'):
            require(manifest.get(key) == entry.get(key), f'Bundle manifest mismatch: {key}')
        total = 0
        for item in bundle.infolist():
            name = item.filename
            require('\\' not in name and ':' not in name and '..' not in name.split('/'), 'Unsafe ZIP path')
            require(name == 'bundle-manifest.json' or name.startswith('site-packages/'), 'Unexpected ZIP entry')
            require(not stat.S_ISLNK(item.external_attr >> 16), 'ZIP symlinks are not supported')
            target = directory / name
            require(target.resolve().is_relative_to(directory.resolve()), 'ZIP path escapes temporary directory')
            total += item.file_size
            require(total <= entry['unpackedBytes'] + 1024 * 1024, 'ZIP exceeds declared expanded size')
            bundle.extract(item, directory)
            if os.name != 'nt' and not item.is_dir():
                target.chmod((item.external_attr >> 16) & 0o777 or 0o600)
    return directory / 'site-packages'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, help='Staged slim runtime root (contains config/python-components.json)')
    parser.add_argument('--bundle-dir', type=Path, help='Use local bundle instead of downloading the catalog URL')
    parser.add_argument('--report', type=Path, help='JSON report; defaults to desktop/dist/component-check/<platform>/report.json')
    parser.add_argument('--worker', choices=['base', 'overlay', 'milvus', 'server'], help=argparse.SUPPRESS)
    parser.add_argument('--overlay', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--data', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--logs', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--port', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        if args.worker == 'base':
            base_imports()
        elif args.worker == 'overlay':
            overlay_imports(args.overlay)
        elif args.worker == 'milvus':
            milvus_roundtrip(args.overlay, args.data, args.logs)
        else:
            serve(args.overlay, args.data, args.port)
        return 0
    if not args.runtime:
        parser.error('--runtime is required')
    target_platform = 'windows' if sys.platform == 'win32' else sys.platform
    arch = {'amd64': 'amd64', 'x86_64': 'amd64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(platform.machine().lower())
    output = (args.report or Path(__file__).resolve().parents[1] / 'dist/component-check' /
              f'{target_platform}-{arch}' / 'report.json').resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    logs = output.parent / ('run-' + time.strftime('%Y%m%d-%H%M%S') + '-' + str(os.getpid()))
    logs.mkdir()
    report = {'platform': target_platform, 'arch': arch, 'python': sys.executable,
              'runtime': str(args.runtime.resolve()), 'logs': str(logs), 'checks': [], 'passed': False}

    def check(name, action):
        print(f'RUN {name}', flush=True)
        try:
            value = action()
        except Exception as error:
            report['checks'].append({'name': name, 'passed': False, 'error': str(error)})
            raise
        report['checks'].append({'name': name, 'passed': True})
        print(f'PASS {name}', flush=True)
        return value

    try:
        def preflight():
            require(Path(sysconfig.get_path('purelib')).resolve().is_relative_to(
                (args.runtime / 'deps/python/algorithm').resolve()), 'Run using this runtime\'s algorithm Python')
            catalog = json.loads((args.runtime / 'config/python-components.json').read_text())
            entry = catalog['components']['rag']
            for key, value in [('platform', target_platform), ('arch', arch),
                               ('pythonAbi', f'cp{sys.version_info.major}{sys.version_info.minor}')]:
                require(entry[key] == value, f'Wrong {key}: catalog {entry[key]}, interpreter {value}')
            require(Path(entry['filename']).name == entry['filename'], 'Invalid bundle filename')
            report.update(filename=entry['filename'], sha256=entry['sha256'],
                          source=str(args.bundle_dir) if args.bundle_dir else entry['url'])
            return entry
        entry = check('runtime compatibility', preflight)
        check('slim base imports', lambda: run_child('base', [], logs))
        with tempfile.TemporaryDirectory(prefix='lazymind-component-check-') as temporary:
            root = Path(temporary)
            archive = check('bundle download/local file + SHA256', lambda: acquire_bundle(entry, root, args.bundle_dir))
            overlay = check('bundle extraction + manifest', lambda: extract_bundle(archive, root / 'payload', entry))
            check('RAG overlay imports', lambda: run_child('overlay', ['--overlay', str(overlay)], logs))
            check('Milvus insert + flush + restart + search + drop', lambda: run_child(
                'milvus', ['--overlay', str(overlay), '--data', str(root / 'milvus'), '--logs', str(logs)], logs))
        report['passed'] = True
    except Exception as error:
        report['error'] = str(error)
        print(f'FAIL {error}', file=sys.stderr, flush=True)
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'REPORT {output}', flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
