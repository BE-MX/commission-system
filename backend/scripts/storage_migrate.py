"""Explicit inventory/copy entry point. Credentials are read, never printed."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.core.storage.cos import CosObjectStore
from app.core.storage.migration import inventory, write_manifest, copy_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    scan = commands.add_parser('inventory')
    scan.add_argument('--root', type=Path, required=True)
    scan.add_argument('--domain', required=True)
    scan.add_argument('--source-instance', required=True)
    scan.add_argument('--manifest', type=Path, required=True)
    transfer = commands.add_parser('copy')
    transfer.add_argument('--manifest', type=Path, required=True)
    transfer.add_argument('--credentials-file', type=Path, required=True)
    transfer.add_argument('--journal', type=Path, required=True)
    transfer.add_argument('--apply', action='store_true', required=True)
    args = parser.parse_args()
    if args.command == 'inventory':
        manifest = inventory(args.root, domain=args.domain, source_instance=args.source_instance)
        write_manifest(manifest, args.manifest)
        print(json.dumps({'files': len(manifest['files']), 'bytes': sum(r['size'] for r in manifest['files'])}))
    else:
        if args.journal.resolve() in {args.manifest.resolve(), args.credentials_file.resolve()}:
            raise ValueError('Journal must not replace migration inputs or credentials')
        settings = Settings(_env_file=args.credentials_file)
        manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
        store = CosObjectStore(manifest['domain'], settings=settings)
        print(json.dumps(copy_manifest(manifest, store, args.journal, cache_root=Path(settings.COS_CACHE_ROOT))))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Provider exceptions and configuration validation may include secrets.
        print(f'Migration failed ({type(exc).__name__}); no source deletion or database cutover performed', file=sys.stderr)
        raise SystemExit(1) from None
