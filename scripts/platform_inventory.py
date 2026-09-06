"""Read-only source inventory for platform audits; never imports application bootstrap."""
import ast
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inventory():
    endpoints = []
    domains = {}
    for path in sorted((ROOT / 'backend/app').rglob('*.py')):
        source = path.read_text(encoding='utf-8-sig')
        tree = ast.parse(source)
        domain = path.relative_to(ROOT / 'backend/app').parts[0]
        domains.setdefault(domain, {'files': 0, 'endpoints': 0})['files'] += 1
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                if not isinstance(deco, ast.Call) or not isinstance(deco.func, ast.Attribute):
                    continue
                if deco.func.attr not in ('get', 'post', 'put', 'patch', 'delete', 'websocket'):
                    continue
                if not deco.args or not isinstance(deco.args[0], ast.Constant):
                    continue
                # Include function signature and route dependencies; this flags candidates,
                # not proven missing auth (router-level dependencies may apply).
                head = '\n'.join(source.splitlines()[node.lineno - 1:node.body[0].lineno - 1])
                endpoints.append({'file': path.relative_to(ROOT).as_posix(), 'line': node.lineno,
                                  'method': deco.func.attr.upper(), 'path': deco.args[0].value,
                                  'function': node.name, 'async': isinstance(node, ast.AsyncFunctionDef),
                                  'auth_candidate': not re.search(r'Depends|Security', head + ast.unparse(deco))})
                domains[domain]['endpoints'] += 1
    pages = []
    for subdir, pattern in [('frontend/src', '*.vue'), ('frontend-pm/src', '*.vue'),
                            ('frontend/public', '*.html'), ('miniprogram/pages', '*.wxml')]:
        for path in sorted((ROOT / subdir).rglob(pattern)):
            source = path.read_text(encoding='utf-8-sig')
            pages.append({'file': path.relative_to(ROOT).as_posix(),
                          'lines': len(source.splitlines()),
                          'transition_all': len(re.findall(r'transition(?:-property)?\s*:\s*all\b', source)),
                          'hex_colors': len(re.findall(r'#[0-9a-fA-F]{3,8}\b', source)),
                          'backdrop_filters': len(re.findall(r'(?<!-)backdrop-filter\s*:', source)),
                          'reduced_motion': 'prefers-reduced-motion' in source,
                          'timers': len(re.findall(r'\bsetInterval\(', source)),
                          'tables': len(re.findall(r'<el-table\b(?!-)', source))})
    return {'domains': domains, 'endpoints': endpoints, 'surfaces': pages,
            'summary': {'backend_files': sum(d['files'] for d in domains.values()),
                        'endpoints': len(endpoints), 'surfaces': len(pages),
                        'methods': dict(Counter(e['method'] for e in endpoints))}}


if __name__ == '__main__':
    print(json.dumps(inventory(), ensure_ascii=False, indent=2))
