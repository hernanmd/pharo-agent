from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .rag import read_text
from .tonel import TonelFile, parse_tonel

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "target",
    ".gradle",
    ".idea",
}
MAX_SELECTORS_PER_CLASS = 40
SYMBOL_PATTERNS = {
    ".py": [re.compile(r"^(?:class|def)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)],
    ".rb": [re.compile(r"^\s*(?:class|module|def)\s+([A-Za-z_][A-Za-z0-9_?!]*)", re.MULTILINE)],
    ".go": [re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)],
    ".rs": [re.compile(r"^\s*(?:pub\s+)?(?:fn|struct|enum|trait)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)],
    ".java": [re.compile(r"^\s*(?:public|private|protected).*?(?:class|interface)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)],
}
JS_PATTERNS = [
    re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)", re.MULTILINE),
    re.compile(r"^(?:export\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)", re.MULTILINE),
    re.compile(r"^(?:export\s+)?const\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?\(", re.MULTILINE),
]
for suffix in (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"):
    SYMBOL_PATTERNS[suffix] = JS_PATTERNS


@dataclass(frozen=True)
class MapEntry:
    relative_path: str
    size: int
    headline: str
    symbols: list[str]
    broken: bool


def build_repo_map(repo_dir: Path, *, max_chars: int = 40_000) -> str:
    entries = collect_entries(repo_dir)
    grouped: dict[str, list[MapEntry]] = {}
    for entry in entries:
        directory = str(Path(entry.relative_path).parent)
        grouped.setdefault(directory, []).append(entry)

    total_files = len(entries)
    packages = sum(1 for entry in entries if entry.relative_path.endswith("package.st"))
    classes = sum(1 for entry in entries if entry.headline.startswith("class "))

    lines = [
        "# Repository Map",
        "",
        f"{total_files} indexed files across {len(grouped)} directories.",
    ]
    if classes:
        lines.append(f"{classes} Pharo classes in {packages} packages.")
    lines.extend(
        [
            "",
            "This is the full structure of the repository. File bodies are not included here;",
            "the Retrieved Repository Context section below carries the most relevant ones in full,",
            "and you can read any other file with the read_file tool if it is available.",
            "",
        ]
    )

    rendered = "\n".join(lines)
    budget = max_chars - len(rendered)
    body: list[str] = []
    truncated = 0

    for directory in sorted(grouped):
        block = render_directory(directory, grouped[directory])
        if len(block) > budget:
            truncated += len(grouped[directory])
            continue
        body.append(block)
        budget -= len(block)

    if truncated:
        body.append(f"\n_{truncated} further files omitted from the map for context budget._\n")

    return rendered + "\n" + "\n".join(body).rstrip() + "\n"


def render_directory(directory: str, entries: list[MapEntry]) -> str:
    label = directory if directory not in (".", "") else "(repository root)"
    lines = [f"## {label}", ""]
    for entry in sorted(entries, key=lambda item: item.relative_path):
        name = Path(entry.relative_path).name
        marker = " **[does not parse]**" if entry.broken else ""
        headline = f" — {entry.headline}" if entry.headline else ""
        lines.append(f"- `{name}` ({entry.size} bytes){headline}{marker}")
        if entry.symbols:
            lines.append(f"    {', '.join(entry.symbols)}")
    lines.append("")
    return "\n".join(lines)


def collect_entries(repo_dir: Path) -> list[MapEntry]:
    entries: list[MapEntry] = []
    for path in sorted(repo_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in IGNORED_DIRS for part in path.relative_to(repo_dir).parts):
            continue
        try:
            relative = str(path.relative_to(repo_dir))
        except ValueError:
            continue
        entries.append(describe_file(path, relative))
    return entries


def describe_file(path: Path, relative: str) -> MapEntry:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0

    if path.name.endswith(".st"):
        return describe_tonel(path, relative, size)

    text = read_text(path, limit=200_000)
    if not text:
        return MapEntry(relative_path=relative, size=size, headline="", symbols=[], broken=False)

    return MapEntry(
        relative_path=relative,
        size=size,
        headline="",
        symbols=extract_symbols(path.suffix.lower(), text),
        broken=False,
    )


def describe_tonel(path: Path, relative: str, size: int) -> MapEntry:
    text = read_text(path)
    if not text:
        return MapEntry(relative_path=relative, size=size, headline="", symbols=[], broken=False)

    parsed = parse_tonel(relative, text)
    return MapEntry(
        relative_path=relative,
        size=size,
        headline=tonel_headline(parsed),
        symbols=tonel_selectors(parsed),
        broken=not parsed.ok,
    )


def tonel_headline(parsed: TonelFile) -> str:
    if parsed.kind == "Package":
        return f"package {parsed.name}"
    if parsed.kind == "Extension":
        return f"extension of {parsed.name}"
    if parsed.kind == "Trait":
        return f"trait {parsed.name}"
    if parsed.kind == "Class":
        headline = f"class {parsed.name} < {parsed.superclass or '?'}"
        if parsed.instance_variables:
            headline += f" | ivars: {' '.join(parsed.instance_variables)}"
        return headline
    return ""


def tonel_selectors(parsed: TonelFile) -> list[str]:
    class_side = [method.selector for method in parsed.methods if method.class_side]
    instance_side = [method.selector for method in parsed.methods if not method.class_side]

    parts: list[str] = []
    if class_side:
        parts.append("class>> " + " ".join(sorted(class_side)[:MAX_SELECTORS_PER_CLASS]))
    if instance_side:
        parts.append(">> " + " ".join(sorted(instance_side)[:MAX_SELECTORS_PER_CLASS]))
    return parts


def extract_symbols(suffix: str, text: str) -> list[str]:
    patterns = SYMBOL_PATTERNS.get(suffix)
    if not patterns:
        return []
    names: list[str] = []
    for pattern in patterns:
        for match in pattern.findall(text):
            if match not in names:
                names.append(match)
    if not names:
        return []
    shown = names[:MAX_SELECTORS_PER_CLASS]
    suffix_note = f" (+{len(names) - len(shown)} more)" if len(names) > len(shown) else ""
    return [", ".join(shown) + suffix_note]
