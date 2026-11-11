from __future__ import annotations

import ast
import re


def source_excerpt(text: str, query: str, budget: int) -> str:
    """Prefer relevant complete Python functions to the start of an oversized file."""
    if len(text) <= budget:
        return text
    if budget <= 0:
        return ""
    lines = text.splitlines(keepends=True)
    terms = set(re.findall(r"[a-z][a-z0-9_]{2,}", query.lower()))
    synonyms = {"internet": {"web", "url", "fetch", "research"},
                "evolution": {"evolve", "proposal", "candidate", "verify"},
                "voice": {"transcribe", "audio", "speech"},
                "clipping": {"clip", "caption", "render"},
                "memory": {"retrieve", "database", "index"}}
    for term, related in synonyms.items():
        if term in terms:
            terms.update(related)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        half = max(1, (budget - 40) // 2)
        return (text[:half] + "\n# ... omitted middle ...\n" + text[-half:])[:budget]
    prefix = "".join(lines[:min(25, len(lines))])[:min(1500, budget // 4)]
    candidates = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno] + [item.lineno for item in node.decorator_list]) - 1
            end = node.end_lineno or node.lineno
            piece = "".join(lines[start:end])
            names = set(re.findall(r"[a-z][a-z0-9]{2,}", node.name.lower().replace("_", " ")))
            body = set(re.findall(r"[a-z][a-z0-9_]{2,}", piece.lower()))
            score = 12 * len(names & terms) + len(body & terms)
            candidates.append((score, start, piece))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    used = len(prefix)
    selected = []
    for score, start, piece in candidates:
        header = f"\n# ... source excerpt, original line {start + 1} ...\n"
        if used + len(header) + len(piece) <= budget:
            selected.append((start, header + piece))
            used += len(header) + len(piece)
    if not selected:
        # The highest-ranked function itself may be larger than the entire context.
        piece = candidates[0][2] if candidates else text
        prefix += "\n# ... partial source excerpt ...\n" + piece[:max(0, budget - len(prefix) - 40)]
        return prefix[:budget]
    return (prefix + "".join(piece for _, piece in sorted(selected)))[:budget]
