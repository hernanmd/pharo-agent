from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path


TEXT_SUFFIXES = {
    ".c",
    ".cc",
    ".cfg",
    ".conf",
    ".cpp",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".lua",
    ".md",
    ".mjs",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".smalltalk",
    ".st",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

ALWAYS_INCLUDE_NAMES = {
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "pyproject.toml",
    "package.json",
    "pnpm-lock.yaml",
    "package-lock.json",
    "requirements.txt",
    "Gemfile",
    "go.mod",
    "Cargo.toml",
}

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "by",
    "for",
    "from",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}


@dataclass(frozen=True)
class ContextFile:
    path: Path
    relative_path: str
    score: float
    content: str


def build_context_pack(
    repo_dir: Path,
    *,
    query: str,
    diff_text: str,
    max_files: int = 24,
    max_chars: int = 70_000,
) -> str:
    changed_files = set(extract_changed_files(diff_text))
    query_terms = tokenize(query + "\n" + diff_text)
    files = collect_candidate_files(repo_dir)
    ranked = sorted(
        (
            score_file(path, repo_dir, query_terms, changed_files)
            for path in files
        ),
        key=lambda item: item.score,
        reverse=True,
    )

    selected: list[ContextFile] = []
    budget = max_chars
    for item in ranked:
        if item.score <= 0 and len(selected) >= 6:
            break
        if len(selected) >= max_files or budget <= 0:
            break
        content = read_text(item.path)
        if not content:
            continue
        content = trim_text(content, min(12_000, budget))
        if not content:
            continue
        selected.append(
            ContextFile(
                path=item.path,
                relative_path=str(item.path.relative_to(repo_dir)),
                score=item.score,
                content=content,
            )
        )
        budget -= len(content)

    return render_context(selected, changed_files)


def extract_changed_files(diff_text: str) -> list[str]:
    files: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                path = parts[3]
                if path.startswith("b/"):
                    files.append(path[2:])
    return files


@dataclass(frozen=True)
class ScoredPath:
    path: Path
    score: float


def collect_candidate_files(repo_dir: Path) -> list[Path]:
    ignored_dirs = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "dist", "build"}
    candidates: list[Path] = []
    for path in repo_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored_dirs for part in path.parts):
            continue
        if path.name in ALWAYS_INCLUDE_NAMES or path.suffix.lower() in TEXT_SUFFIXES:
            candidates.append(path)
    return candidates


def score_file(
    path: Path,
    repo_dir: Path,
    query_terms: set[str],
    changed_files: set[str],
) -> ScoredPath:
    relative = str(path.relative_to(repo_dir))
    path_terms = tokenize(relative.replace("/", " "))
    score = 0.0
    if relative in changed_files:
        score += 100.0
    if path.name in ALWAYS_INCLUDE_NAMES:
        score += 25.0
    if "/test" in f"/{relative.lower()}" or relative.lower().startswith("test"):
        score += 10.0
    overlap = query_terms & path_terms
    score += len(overlap) * 8.0
    content = read_text(path, limit=20_000)
    if content:
        content_terms = tokenize(content)
        score += min(35.0, len(query_terms & content_terms) * 1.5)
        score -= math.log10(max(len(content), 1)) * 0.25
    return ScoredPath(path=path, score=score)


def tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.lower())
    return {token for token in tokens if token not in STOP_WORDS}


def read_text(path: Path, *, limit: int | None = None) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if b"\0" in data[:4096]:
        return ""
    if limit is not None:
        data = data[:limit]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("latin-1")
        except UnicodeDecodeError:
            return ""


def trim_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = int(limit * 0.7)
    tail = limit - head
    return f"{text[:head]}\n\n[...snipped...]\n\n{text[-tail:]}"


def render_context(files: list[ContextFile], changed_files: set[str]) -> str:
    lines = [
        "# Retrieved Repository Context",
        "",
        "This context was selected locally from the checked out repository.",
        "Changed files are weighted highest, followed by tests, docs, manifests, and lexical matches.",
        "",
    ]
    if changed_files:
        lines.extend(["## Changed Files", ""])
        lines.extend(f"- {path}" for path in sorted(changed_files))
        lines.append("")

    for item in files:
        lines.extend(
            [
                f"## {item.relative_path}",
                f"Score: {item.score:.2f}",
                "",
                "```text",
                item.content.rstrip(),
                "```",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"

