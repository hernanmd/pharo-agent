from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path


SKILLS_DIRNAME = ".ai/skills"
FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<frontmatter>.*?)\n---\s*\n(?P<body>.*)\Z", re.DOTALL)
LIST_KEYS = {"when", "tools", "validate"}
BOOL_KEYS = {"always"}
INT_KEYS = {"priority"}


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    when: list[str]
    always: bool
    tools: list[str]
    validate: list[str]
    priority: int
    body: str
    path: str

    def matches(self, changed_files: list[str]) -> bool:
        if self.always:
            return True
        return any(path_matches(path, pattern) for pattern in self.when for path in changed_files)


@dataclass(frozen=True)
class SkillSelection:
    skills: list[Skill]
    skipped: list[str] = field(default_factory=list)

    @property
    def tools(self) -> list[str]:
        names: list[str] = []
        for skill in self.skills:
            for tool in skill.tools:
                if tool not in names:
                    names.append(tool)
        return names

    @property
    def validate_commands(self) -> list[str]:
        commands: list[str] = []
        for skill in self.skills:
            for command in skill.validate:
                if command not in commands:
                    commands.append(command)
        return commands

    def summary(self) -> str:
        if not self.skills:
            return "(none)"
        return ", ".join(skill.name for skill in self.skills)


def load_skills(repo_dir: Path, *, subdir: str = SKILLS_DIRNAME) -> list[Skill]:
    skills_dir = repo_dir / subdir
    if not skills_dir.is_dir():
        return []

    skills: list[Skill] = []
    for path in sorted(skills_dir.rglob("*.md")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        skill = parse_skill(text, path=str(path.relative_to(repo_dir)), fallback_name=path.stem)
        if skill:
            skills.append(skill)
    return sorted(skills, key=lambda skill: (-skill.priority, skill.name))


def select_skills(
    skills: list[Skill],
    *,
    changed_files: list[str],
    max_chars: int = 24_000,
) -> SkillSelection:
    selected: list[Skill] = []
    skipped: list[str] = []
    budget = max_chars

    for skill in skills:
        if not skill.matches(changed_files):
            continue
        cost = len(skill.body)
        if cost > budget:
            skipped.append(f"{skill.name} (over context budget)")
            continue
        selected.append(skill)
        budget -= cost

    return SkillSelection(skills=selected, skipped=skipped)


def parse_skill(text: str, *, path: str, fallback_name: str) -> Skill | None:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None

    fields = parse_frontmatter(match.group("frontmatter"))
    body = match.group("body").strip()
    if not body:
        return None

    return Skill(
        name=str(fields.get("name") or fallback_name),
        description=str(fields.get("description") or ""),
        when=[str(item) for item in fields.get("when", [])],
        always=bool(fields.get("always", False)),
        tools=[str(item) for item in fields.get("tools", [])],
        validate=[str(item) for item in fields.get("validate", [])],
        priority=int(fields.get("priority", 0) or 0),
        body=body,
        path=path,
    )


def parse_frontmatter(text: str) -> dict[str, object]:
    fields: dict[str, object] = {}
    current_list_key: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if current_list_key and line.lstrip().startswith("- "):
            value = scalar(line.lstrip()[2:])
            fields.setdefault(current_list_key, [])
            fields[current_list_key].append(value)  # type: ignore[union-attr]
            continue

        key_value = re.match(r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(?P<value>.*)$", line)
        if not key_value:
            continue

        key = key_value.group("key")
        value = key_value.group("value").strip()
        current_list_key = None

        if not value and key in LIST_KEYS:
            fields[key] = []
            current_list_key = key
            continue
        if key in LIST_KEYS:
            fields[key] = parse_list(value)
            continue
        if key in BOOL_KEYS:
            fields[key] = value.strip().lower() in {"true", "yes", "1", "on"}
            continue
        if key in INT_KEYS:
            try:
                fields[key] = int(value)
            except ValueError:
                fields[key] = 0
            continue
        fields[key] = scalar(value)

    for key in LIST_KEYS:
        fields.setdefault(key, [])
    return fields


def parse_list(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [scalar(item) for item in split_items(value) if scalar(item)]


def split_items(value: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in value:
        if quote:
            if char == quote:
                quote = None
            else:
                current.append(char)
            continue
        if char in ("'", '"'):
            quote = char
            continue
        if char == ",":
            items.append("".join(current))
            current = []
            continue
        current.append(char)
    items.append("".join(current))
    return [item.strip() for item in items if item.strip()]


def scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def path_matches(path: str, pattern: str) -> bool:
    path = path.lstrip("./")
    pattern = pattern.strip()
    if not pattern:
        return False
    candidates = {pattern}
    if pattern.startswith("**/"):
        candidates.add(pattern[3:])
    if not pattern.startswith("**/"):
        candidates.add(f"**/{pattern}")
    return any(fnmatch.fnmatch(path, candidate) for candidate in candidates)


def render_skills(selection: SkillSelection) -> str:
    if not selection.skills:
        return ""

    lines = [
        "# Repository Skills",
        "",
        "These instructions come from the target repository and describe how to work in it.",
        "Follow them over your own general assumptions about the language or toolchain.",
        "",
    ]
    for skill in selection.skills:
        lines.append(f"## Skill: {skill.name}")
        if skill.description:
            lines.append(f"_{skill.description}_")
        lines.extend(["", skill.body, ""])
    return "\n".join(lines).rstrip() + "\n"
