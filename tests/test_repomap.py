from pathlib import Path

from ai_ci_controller.repomap import build_repo_map

CLASS_SOURCE = """\
Class {
	#name : 'Demo',
	#superclass : 'Object',
	#instVars : [ 'count' ],
	#package : 'Demo-Core'
}

{ #category : 'accessing' }
Demo >> count [

	^ count
]

{ #category : 'accessing' }
Demo class >> build [

	^ self new
]
"""

BROKEN_SOURCE = """\
Class {
	#name : 'Broken',
	#package : 'Demo-Core'
}
"""


def build_repo(tmp_path: Path) -> Path:
    package = tmp_path / "src" / "Demo-Core"
    package.mkdir(parents=True)
    (package / "Demo.class.st").write_text(CLASS_SOURCE, encoding="utf-8")
    (package / "package.st").write_text("Package { #name : 'Demo-Core' }\n", encoding="utf-8")
    (tmp_path / "tool.py").write_text("class Runner:\n    pass\n\ndef main():\n    pass\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("noise\n", encoding="utf-8")
    return tmp_path


def test_map_lists_pharo_classes_with_superclass_and_selectors(tmp_path: Path):
    repo_map = build_repo_map(build_repo(tmp_path))

    assert "class Demo < Object" in repo_map
    assert "ivars: count" in repo_map
    assert "class>> build" in repo_map
    assert ">> count" in repo_map


def test_map_lists_package_files(tmp_path: Path):
    repo_map = build_repo_map(build_repo(tmp_path))

    assert "package Demo-Core" in repo_map


def test_map_extracts_python_symbols(tmp_path: Path):
    repo_map = build_repo_map(build_repo(tmp_path))

    assert "Runner, main" in repo_map


def test_map_excludes_vendored_directories(tmp_path: Path):
    repo_map = build_repo_map(build_repo(tmp_path))

    assert "junk.js" not in repo_map


def test_map_flags_files_that_do_not_parse(tmp_path: Path):
    repo = build_repo(tmp_path)
    (repo / "src" / "Demo-Core" / "Broken.class.st").write_text(BROKEN_SOURCE, encoding="utf-8")

    repo_map = build_repo_map(repo)

    assert "Broken.class.st" in repo_map
    assert "does not parse" in repo_map


def test_map_respects_the_character_budget(tmp_path: Path):
    repo = build_repo(tmp_path)

    full = build_repo_map(repo)
    trimmed = build_repo_map(repo, max_chars=450)

    assert len(trimmed) < len(full)
    assert "omitted from the map for context budget" in trimmed
    assert "# Repository Map" in trimmed
