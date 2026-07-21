from pathlib import Path

from ai_ci_controller.skills import load_skills, path_matches, render_skills, select_skills

PHARO_SKILL = """\
---
name: pharo
description: How to work with Pharo code
when:
  - "src/**/*.st"
  - "**/*.class.st"
tools: [pharo_eval, pharo_class_source]
validate:
  - "./bin/run-pharo-tests"
priority: 10
---

Use the live image to check selectors.
"""

ALWAYS_SKILL = """\
---
name: house-style
description: Always applies
always: true
---

Keep commits small.
"""

NO_FRONTMATTER = "Just a plain note with no frontmatter.\n"


def write_skills(tmp_path: Path, files: dict[str, str]) -> Path:
    skills_dir = tmp_path / ".ai" / "skills"
    skills_dir.mkdir(parents=True)
    for name, content in files.items():
        (skills_dir / name).write_text(content, encoding="utf-8")
    return tmp_path


def test_loads_and_orders_by_priority(tmp_path: Path):
    repo = write_skills(tmp_path, {"pharo.md": PHARO_SKILL, "style.md": ALWAYS_SKILL})

    skills = load_skills(repo)

    assert [skill.name for skill in skills] == ["pharo", "house-style"]
    assert skills[0].tools == ["pharo_eval", "pharo_class_source"]
    assert skills[0].validate == ["./bin/run-pharo-tests"]
    assert skills[0].priority == 10


def test_ignores_files_without_frontmatter(tmp_path: Path):
    repo = write_skills(tmp_path, {"note.md": NO_FRONTMATTER})

    assert load_skills(repo) == []


def test_missing_skills_directory_is_not_an_error(tmp_path: Path):
    assert load_skills(tmp_path) == []


def test_selects_by_changed_path(tmp_path: Path):
    repo = write_skills(tmp_path, {"pharo.md": PHARO_SKILL, "style.md": ALWAYS_SKILL})
    skills = load_skills(repo)

    matched = select_skills(skills, changed_files=["src/Demo/Demo.class.st"])
    unmatched = select_skills(skills, changed_files=["README.md"])

    assert [skill.name for skill in matched.skills] == ["pharo", "house-style"]
    assert [skill.name for skill in unmatched.skills] == ["house-style"]


def test_selection_aggregates_tools_and_validation(tmp_path: Path):
    repo = write_skills(tmp_path, {"pharo.md": PHARO_SKILL, "style.md": ALWAYS_SKILL})

    selection = select_skills(load_skills(repo), changed_files=["src/Demo/Demo.class.st"])

    assert selection.tools == ["pharo_eval", "pharo_class_source"]
    assert selection.validate_commands == ["./bin/run-pharo-tests"]
    assert selection.summary() == "pharo, house-style"


def test_selection_respects_context_budget(tmp_path: Path):
    repo = write_skills(tmp_path, {"style.md": ALWAYS_SKILL})

    selection = select_skills(load_skills(repo), changed_files=[], max_chars=5)

    assert selection.skills == []
    assert selection.skipped == ["house-style (over context budget)"]


def test_render_includes_body_and_description(tmp_path: Path):
    repo = write_skills(tmp_path, {"pharo.md": PHARO_SKILL})

    rendered = render_skills(select_skills(load_skills(repo), changed_files=["a.class.st"]))

    assert "## Skill: pharo" in rendered
    assert "How to work with Pharo code" in rendered
    assert "Use the live image to check selectors." in rendered


def test_render_empty_selection_is_empty(tmp_path: Path):
    assert render_skills(select_skills([], changed_files=[])) == ""


def test_path_matching_handles_leading_globstar():
    assert path_matches("Demo.class.st", "**/*.class.st")
    assert path_matches("src/a/b/Demo.class.st", "**/*.class.st")
    assert path_matches("src/a/Demo.class.st", "src/**/*.st")
    assert not path_matches("docs/readme.md", "src/**/*.st")


def test_inline_list_and_block_list_parse_the_same(tmp_path: Path):
    inline = PHARO_SKILL.replace(
        'when:\n  - "src/**/*.st"\n  - "**/*.class.st"',
        'when: ["src/**/*.st", "**/*.class.st"]',
    )
    repo = write_skills(tmp_path, {"pharo.md": inline})

    skills = load_skills(repo)

    assert skills[0].when == ["src/**/*.st", "**/*.class.st"]
