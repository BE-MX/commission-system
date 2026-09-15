"""Select the installed root when bootstrapping a pinned candidate deployer."""

import argparse
from pathlib import Path
import re


def resolve_live_root(argv, script):
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument('--live-root')
    parser.add_argument('--revision')
    args, remaining = parser.parse_known_args(argv)
    script = Path(script).resolve()
    if not args.live_root:
        return script.parent.parent
    live = Path(args.live_root).resolve()
    if not args.revision or not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        raise RuntimeError('Candidate deployer requires a pinned full --revision')
    expected = live / '.deploy_state/sources' / args.revision / 'deploy/publish.py'
    if script != expected:
        raise RuntimeError('Candidate deployer must run from the pinned managed source')
    if any(arg.split('=', 1)[0] in {
        '--cloud-only', '--migrate-only', '--recover-migration-149',
        '--shipping-video-routing-only', '--voucher-routing-only', '--colorwork-routing-only',
    } for arg in remaining):
        raise RuntimeError('Candidate deployer requires a normal full office/cloud release')
    return live
