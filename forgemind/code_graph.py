"""Small, deterministic map of Doxa's Python source; no model or upload required."""
import ast
import hashlib
import json
import re
from pathlib import Path


def source_files(root):
    root = Path(root).resolve()
    candidates = [root / 'app.py', *(root / 'forgemind').rglob('*.py')]
    return sorted(p for p in candidates if p.is_file() and not p.is_symlink()
                  and '__pycache__' not in p.parts and p.stat().st_size < 2_000_000)


def build(root, cache):
    root, cache = Path(root).resolve(), Path(cache)
    try:
        old = json.loads(cache.read_text('utf-8'))
        if old.get('root') != str(root): old = {}
    except (OSError, ValueError):
        old = {}
    files, changed = {}, 0
    for path in source_files(root):
        rel = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        previous = old.get('files', {}).get(rel, {})
        if previous.get('sha256') == digest:
            files[rel] = previous
            continue
        changed += 1
        record = {'sha256': digest, 'symbols': [], 'imports': []}
        try:
            tree = ast.parse(raw, filename=rel)
            def walk(node, prefix=''):
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        name = prefix + child.name
                        calls = sorted({ast.unparse(n.func) for n in ast.walk(child)
                                        if isinstance(n, ast.Call)})[:100]
                        record['symbols'].append({'name': name, 'kind': type(child).__name__,
                            'line': child.lineno, 'end': child.end_lineno,
                            'summary': (ast.get_docstring(child) or '').split('\n')[0][:180],
                            'calls_observed': calls})
                        walk(child, name + '.')
                    else:
                        walk(child, prefix)
            walk(tree)
            record['imports'] = sorted({ast.unparse(n) for n in ast.walk(tree)
                if isinstance(n, (ast.Import, ast.ImportFrom))})
        except (SyntaxError, ValueError) as exc:
            record['error'] = type(exc).__name__
        files[rel] = record
    result = {'version': 1, 'root': str(root), 'files': files}
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False), 'utf-8')
    temporary.replace(cache)
    return result, changed


def query(root, cache, text, limit=10):
    graph, changed = build(root, cache)
    words = set(re.findall(r'[a-z0-9_]{2,}', text.lower()))
    results = []
    for path, record in graph['files'].items():
        for symbol in record['symbols']:
            label = path + ' ' + symbol['name'] + ' ' + symbol['summary']
            score = sum(3 * (word in label.lower()) +
                        (word in ' '.join(symbol['calls_observed']).lower()) for word in words)
            if score:
                results.append((score, {'path': path, **symbol}))
    results.sort(key=lambda x: (-x[0], x[1]['path'], x[1]['line']))
    return {'files_indexed': len(graph['files']), 'files_reparsed': changed,
            'note': 'Static Python references, not proven runtime call edges. Read these source locations before editing.',
            'matches': [r for _, r in results[:limit]]}
