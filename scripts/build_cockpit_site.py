#!/usr/bin/env python3
"""Build an additive, content-addressed Cockpit site. This script never deploys."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def build_site(output: Path, root: Path = ROOT):
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output must be an empty directory; existing files are never removed')
    source = root / 'bi_agent/web/static/cockpit'
    files = sorted(p for p in source.rglob('*') if p.is_file() and not any(x.startswith('.') for x in p.relative_to(source).parts))
    identity = hashlib.sha256()
    for p in files:
        identity.update(str(p.relative_to(source)).encode() + b'\0' + p.read_bytes())
    version = identity.hexdigest()[:20]
    prefix = f'/static/cockpit/releases/{version}'
    output.mkdir(parents=True, exist_ok=True)
    assets = output / prefix.lstrip('/')
    for p in files:
        target = assets / p.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(p.read_bytes())
    html = (source / 'index.html').read_text()
    html = html.replace('@@APP_ROOT_PATH@@', '').replace('@@COCKPIT_PAGE@@', 'overview').replace('@@COCKPIT_VERSION@@', version)
    html = html.replace('/static/cockpit/', prefix + '/').replace('content="/static/cockpit"', f'content="{prefix}"')
    if '@@' in html:
        raise ValueError('Unresolved HTML template placeholder')
    (output / 'index.html').write_text(html)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    (output / 'release.json').write_text(json.dumps(dict(commit=commit, assetVersion=version, assets=prefix,
        cardContract='cockpit-cards-v1', pageContract='whole-page-v1')) + '\n')
    for p in sorted(output.rglob('*')):
        if p.is_file() and p.suffix in {'.js', '.css', '.html', '.json', '.svg', '.md'}:
            data = p.read_bytes()
            compressed = gzip.compress(data, compresslevel=6, mtime=0)
            if len(data) >= 256 and len(compressed) < len(data):
                p.with_name(p.name + '.gz').write_bytes(compressed)
    (output / 'manifest.sha256').write_text(''.join(
        hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + str(p.relative_to(output)) + '\n'
        for p in sorted(output.rglob('*')) if p.is_file()))
    return dict(output=str(output), assetVersion=version, files=sum(p.is_file() for p in output.rglob('*')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_site(args.output)))
