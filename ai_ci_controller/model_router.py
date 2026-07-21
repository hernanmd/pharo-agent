from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .rag import extract_changed_files


DOC_SUFFIXES = {".md", ".markdown", ".rst", ".txt", ".adoc"}
TEST_HINTS = {
    "/test/",
    "/tests/",
    "test_",
    "_test.",
    ".spec.",
    ".test.",
    "-test/",
    "-tests/",
    "test.class.st",
    "tests.class.st",
}
LOCKFILE_NAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "Pipfile.lock",
    "Gemfile.lock",
    "Cargo.lock",
    "go.sum",
}
HIGH_RISK_PATH_PATTERNS = [
    re.compile(r"(^|/)\.github/workflows/"),
    re.compile(r"(^|/)BaselineOf[A-Za-z0-9_]*(/|\.class\.st$)"),
    re.compile(r"(^|/)package\.st$"),
    re.compile(r"(^|/)migrations?/"),
    re.compile(r"(^|/)schema\.(sql|rb|prisma|json)$"),
    re.compile(r"(^|/)(auth|oauth|security|crypto|permission|billing|payment)s?(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)(Dockerfile|docker-compose\.ya?ml|wrangler\.jsonc?|terraform|infra)(/|$)?", re.IGNORECASE),
]
HIGH_RISK_WORDS = {
    "auth",
    "authentication",
    "authorization",
    "credential",
    "crypto",
    "database",
    "encryption",
    "jwt",
    "migration",
    "oauth",
    "password",
    "payment",
    "permission",
    "privacy",
    "security",
    "session",
    "token",
}
HIGH_RISK_WORD_RE = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(sorted(HIGH_RISK_WORDS)) + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DiffStats:
    files_changed: int
    additions: int
    deletions: int
    patch_chars: int
    changed_files: list[str]
    docs_only: bool
    tests_only: bool
    has_lockfile: bool
    has_high_risk_path: bool
    has_high_risk_words: bool

    @property
    def lines_changed(self) -> int:
        return self.additions + self.deletions


@dataclass(frozen=True)
class ModelPolicy:
    default_model: str | None
    small_model: str | None
    medium_model: str | None
    large_model: str | None


@dataclass(frozen=True)
class ModelSelection:
    tier: str
    model: str
    score: int
    reasons: list[str]
    stats: DiffStats

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"

    def summary(self) -> str:
        reasons = "; ".join(self.reasons)
        return f"{self.tier} -> {self.model} (score {self.score}: {reasons})"


def classify_model(
    policy: ModelPolicy,
    *,
    title: str,
    body: str,
    diff_text: str,
    mode: str,
) -> ModelSelection:
    stats = diff_stats(title=title, body=body, diff_text=diff_text)
    score, reasons = score_change(stats, title=title, body=body, mode=mode)
    tier = tier_for_score(score)
    model = resolve_model(policy, tier)
    if not model:
        raise RuntimeError(
            "No model configured. Set MODEL or one of MODEL_SMALL, MODEL_MEDIUM, MODEL_LARGE."
        )
    resolved_tier = tier
    if tier_model(policy, tier) != model:
        resolved_tier = f"{tier}/fallback"
        reasons.append(f"{tier} model was not configured; using fallback model")
    return ModelSelection(
        tier=resolved_tier,
        model=model,
        score=score,
        reasons=reasons,
        stats=stats,
    )


def diff_stats(*, title: str, body: str, diff_text: str) -> DiffStats:
    changed_files = extract_changed_files(diff_text)
    additions = 0
    deletions = 0
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1

    normalized_files = sorted(set(changed_files))
    docs_only = bool(normalized_files) and all(is_doc_path(path) for path in normalized_files)
    tests_only = bool(normalized_files) and all(is_test_path(path) or is_doc_path(path) for path in normalized_files)
    has_lockfile = any(Path(path).name in LOCKFILE_NAMES for path in normalized_files)
    has_high_risk_path = any(is_high_risk_path(path) for path in normalized_files)
    joined_text = f"{title}\n{body}\n{diff_text}"
    has_high_risk_words = bool(HIGH_RISK_WORD_RE.search(joined_text))
    return DiffStats(
        files_changed=len(normalized_files),
        additions=additions,
        deletions=deletions,
        patch_chars=len(diff_text),
        changed_files=normalized_files,
        docs_only=docs_only,
        tests_only=tests_only,
        has_lockfile=has_lockfile,
        has_high_risk_path=has_high_risk_path,
        has_high_risk_words=has_high_risk_words,
    )


def score_change(stats: DiffStats, *, title: str, body: str, mode: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if stats.files_changed == 0:
        issue_size = len(title) + len(body)
        if issue_size > 4000:
            score += 5
            reasons.append("large issue description")
        elif issue_size > 1200:
            score += 2
            reasons.append("moderate issue description")
        else:
            reasons.append("small issue description")
    elif stats.lines_changed <= 80 and stats.files_changed <= 3 and stats.patch_chars <= 20_000:
        reasons.append("tiny diff")
    elif stats.lines_changed <= 400 and stats.files_changed <= 8 and stats.patch_chars <= 70_000:
        score += 3
        reasons.append("moderate diff")
    elif stats.lines_changed <= 1200 and stats.files_changed <= 20 and stats.patch_chars <= 160_000:
        score += 5
        reasons.append("large diff")
    else:
        score += 9
        reasons.append("very large diff")

    if stats.docs_only:
        score -= 3
        reasons.append("docs-only change")
    elif stats.tests_only and stats.lines_changed <= 300:
        score -= 2
        reasons.append("test-only or docs/test change")

    if mode == "fix":
        score += 2
        reasons.append("fix mode can modify code")
    elif mode == "respond":
        score += 3
        reasons.append("responding to review feedback needs judgement and can modify code")
    elif mode == "issue":
        score += 2
        reasons.append("issue implementation has no PR diff")

    if stats.has_lockfile:
        score += 4
        reasons.append("dependency lockfile changed")
    if stats.has_high_risk_path:
        score += 5
        reasons.append("high-risk path changed")
    if stats.has_high_risk_words:
        score += 3
        reasons.append("security/auth/data risk words present")

    score = max(0, score)
    if not reasons:
        reasons.append("default low-risk change")
    return score, reasons


def tier_for_score(score: int) -> str:
    if score >= 8:
        return "large"
    if score >= 3:
        return "medium"
    return "small"


def resolve_model(policy: ModelPolicy, tier: str) -> str | None:
    fallback_order = {
        "small": [policy.small_model, policy.medium_model, policy.default_model, policy.large_model],
        "medium": [policy.medium_model, policy.default_model, policy.large_model, policy.small_model],
        "large": [policy.large_model, policy.default_model, policy.medium_model, policy.small_model],
    }
    for model in fallback_order[tier]:
        if model:
            return model
    return None


def tier_model(policy: ModelPolicy, tier: str) -> str | None:
    if tier == "small":
        return policy.small_model
    if tier == "medium":
        return policy.medium_model
    if tier == "large":
        return policy.large_model
    return None


def is_doc_path(path: str) -> bool:
    return Path(path).suffix.lower() in DOC_SUFFIXES or path.lower().startswith("docs/")


def is_test_path(path: str) -> bool:
    lowered = f"/{path.lower()}"
    return any(hint in lowered for hint in TEST_HINTS)


def is_high_risk_path(path: str) -> bool:
    return any(pattern.search(path) for pattern in HIGH_RISK_PATH_PATTERNS)
