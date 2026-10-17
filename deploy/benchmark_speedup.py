"""Isolated, reproducible file-work benchmark. Never connects to production."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import statistics
import shutil
import subprocess
import tempfile
import time
import types

import npm_cache
import remote_static
import static_retention


def measure(function, *args):
    start = time.perf_counter()
    result = function(*args)
    return time.perf_counter() - start, result


def run(state, baseline, assets, dependencies=None, install=False):
    state.mkdir(parents=True, exist_ok=True)
    old = types.ModuleType('baseline_retention')
    source = subprocess.check_output(['git', 'show', baseline + ':deploy/static_retention.py'], text=True)
    exec(compile(source, 'baseline_static_retention.py', 'exec'), old.__dict__)
    result = {'baseline': baseline, 'assets': assets, 'scope': 'local isolated warm filesystem benchmark'}
    with tempfile.TemporaryDirectory(prefix='speedup-', dir=state) as tmp:
        root = Path(tmp)
        kept, files = [], {}
        for i in range(assets):
            data = (str(i).encode() + b'-asset') * 128
            files['assets/' + str(i) + '.js'] = hashlib.sha256(data).hexdigest()
        files['index.html'] = hashlib.sha256(b'index').hexdigest()
        for label in ('active', 'rollback-1', 'rollback-2'):
            folder = root / label
            (folder / 'assets').mkdir(parents=True)
            for i in range(assets):
                (folder / 'assets' / (str(i) + '.js')).write_bytes((str(i).encode() + b'-asset') * 128)
            (folder / 'index.html').write_bytes(b'index')
            kept.append((folder, files))
        union = static_retention.asset_union([files])
        samples = {'before': [], 'after': []}
        hashes = {}
        plans = {}
        for round_number in range(3):
            order = [('before', old), ('after', static_retention)]
            if round_number % 2: order.reverse()
            for name, module in order:
                original, calls = module.sha, Counter()
                def traced(path):
                    calls[str(path)] += 1
                    return original(path)
                module.sha = traced
                try:
                    elapsed, plan = measure(module.plan_cleanup, kept, [], union)
                finally:
                    module.sha = original
                samples[name].append(elapsed)
                hashes[name] = sum(calls.values())
                plans[name] = plan
        assert plans['before'] == plans['after'], 'Cleanup semantics changed'
        result['retention'] = {'seconds': samples, 'median_seconds': {k: statistics.median(v) for k, v in samples.items()},
                               'hash_calls_per_round': hashes, 'identical_plan': True}
        # Asset merge comparison uses the previous implementation verbatim.
        remote_source = subprocess.check_output(['git', 'show', baseline + ':deploy/remote_static.py'], text=True)
        prior_remote = types.ModuleType('baseline_remote_static')
        exec(compile(remote_source, 'baseline_remote_static.py', 'exec'), prior_remote.__dict__)
        merge = {}
        for name, function in [('before', prior_remote.retain_assets), ('after', remote_static.retain_assets)]:
            destination = root / ('merge-' + name)
            destination.mkdir()
            elapsed, _ = measure(function, kept[0][0], destination)
            merge[name] = elapsed
        result['asset_copy_seconds'] = merge
        (state / 'benchmark.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        if dependencies:
            # Only read existing dependencies. Cache and restored files live in
            # this temporary tree, retired by TemporaryDirectory on exit.
            key = 'b' * 64
            if not (dependencies / 'node_modules/vite/bin/vite.js').is_file():
                raise ValueError('Benchmark requires an installed Vite dependency tree')
            elapsed, _ = measure(npm_cache.store, dependencies, root / 'cache', key)
            restore = root / 'restore' / dependencies.name
            restore.mkdir(parents=True)
            restored_seconds, restored = measure(npm_cache.restore, restore, root / 'cache', key)
            assert restored
            receipt = json.loads((root / 'cache/npm-cache' / dependencies.name / (key + '.json')).read_text())
            for file, _ in static_retention.walk_files(restore / 'node_modules'):
                relative = file.relative_to(restore / 'node_modules')
                assert static_retention.sha(file) == static_retention.sha(dependencies / 'node_modules' / relative)
            vite = subprocess.check_output(['node', str(restore / 'node_modules/vite/bin/vite.js'), '--version'], text=True).strip()
            subprocess.run(['node', '-e', "require('esbuild').transformSync('const x = 1', {minify:true})"], cwd=restore, check=True)
            result['dependencies'] = {'store_seconds': elapsed, 'restore_seconds': restored_seconds,
                'files': receipt['files'], 'bytes': receipt['bytes'], 'all_bytes_match': True, 'vite': vite, 'esbuild': 'passed'}
            if install:
                fresh = root / 'fresh' / dependencies.name
                fresh.mkdir(parents=True)
                for name in ('package.json', 'package-lock.json', '.npmrc'):
                    if (dependencies / name).is_file():
                        shutil.copyfile(dependencies / name, fresh / name)
                start = time.perf_counter()
                subprocess.run([shutil.which('npm.cmd' if os.name == 'nt' else 'npm'), 'ci', '--prefer-offline', '--no-audit', '--no-fund'],
                               cwd=fresh, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
                result['dependencies']['fresh_npm_ci_seconds'] = time.perf_counter() - start
    (state / 'benchmark.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='d821f507054451cabc4f57bcd746a897cbe0abf3')
    parser.add_argument('--assets', type=int, default=3366)
    parser.add_argument('--dependencies', type=Path)
    parser.add_argument('--compare-install', action='store_true')
    args = parser.parse_args()
    state = Path(__file__).resolve().parents[1] / '.deploy_state/speedup-benchmark'
    print(json.dumps(run(state, args.baseline, args.assets, args.dependencies, args.compare_install), indent=2), flush=True)
