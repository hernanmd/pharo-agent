from pathlib import Path

from ai_ci_controller.tonel import parse_tonel, validate_paths

VALID_CLASS = """\
"
A demo class.
"
Class {
	#name : 'Demo',
	#superclass : 'Object',
	#instVars : [
		'count'
	],
	#category : 'Demo-Core',
	#package : 'Demo-Core'
}

{ #category : 'accessing' }
Demo class >> defaultCount [

	^ 0
]

{ #category : 'accessing' }
Demo >> count [

	^ count
]

{ #category : 'arithmetic' }
Demo >> + anInteger [

	^ count + anInteger
]

{ #category : 'accessing' }
Demo >> at: aKey put: aValue [

	^ aKey -> aValue
]
"""


def test_parses_a_valid_class():
    parsed = parse_tonel("Demo.class.st", VALID_CLASS)

    assert parsed.ok, parsed.errors
    assert parsed.kind == "Class"
    assert parsed.name == "Demo"
    assert parsed.superclass == "Object"
    assert parsed.package == "Demo-Core"
    assert parsed.instance_variables == ["count"]
    assert parsed.comment == "A demo class."


def test_extracts_selectors_and_sides():
    parsed = parse_tonel("Demo.class.st", VALID_CLASS)
    selectors = {(method.selector, method.class_side) for method in parsed.methods}

    assert ("defaultCount", True) in selectors
    assert ("count", False) in selectors
    assert ("+", False) in selectors
    assert ("at:put:", False) in selectors


def test_parses_package_files():
    parsed = parse_tonel("package.st", "Package { #name : 'Demo-Core' }\n")

    assert parsed.ok, parsed.errors
    assert parsed.kind == "Package"
    assert parsed.name == "Demo-Core"


def test_detects_unterminated_string():
    broken = VALID_CLASS.replace("^ count\n]", "^ 'oops\n]")
    parsed = parse_tonel("Demo.class.st", broken)

    assert not parsed.ok
    assert any("unterminated string" in error for error in parsed.errors)


def test_detects_receiver_mismatch():
    broken = VALID_CLASS.replace("Demo >> count [", "Wrong >> count [")
    parsed = parse_tonel("Demo.class.st", broken)

    assert not parsed.ok
    assert any("does not match class 'Demo'" in error for error in parsed.errors)


def test_detects_missing_category_chunk():
    broken = VALID_CLASS.replace("{ #category : 'arithmetic' }\n", "")
    parsed = parse_tonel("Demo.class.st", broken)

    assert not parsed.ok
    assert any("no { #category" in error for error in parsed.errors)


def test_detects_missing_superclass():
    broken = VALID_CLASS.replace("\t#superclass : 'Object',\n", "")
    parsed = parse_tonel("Demo.class.st", broken)

    assert not parsed.ok
    assert any("missing #superclass" in error for error in parsed.errors)


def test_quotes_inside_strings_do_not_break_parsing():
    source = VALID_CLASS.replace("^ count\n]", "^ 'it''s fine'\n]")
    parsed = parse_tonel("Demo.class.st", source)

    assert parsed.ok, parsed.errors


def test_character_literal_quote_is_not_a_string_start():
    source = VALID_CLASS.replace("^ count\n]", "^ $' asString\n]")
    parsed = parse_tonel("Demo.class.st", source)

    assert parsed.ok, parsed.errors


def test_brackets_inside_comments_are_ignored():
    source = VALID_CLASS.replace("^ count\n]", '"a ] bracket" ^ count\n]')
    parsed = parse_tonel("Demo.class.st", source)

    assert parsed.ok, parsed.errors


def test_validate_paths_reports_relative_problems(tmp_path: Path):
    target = tmp_path / "src" / "Demo-Core" / "Demo.class.st"
    target.parent.mkdir(parents=True)
    target.write_text(VALID_CLASS.replace("Demo >> count [", "Wrong >> count ["), encoding="utf-8")

    problems = validate_paths(tmp_path, ["src/Demo-Core/Demo.class.st"])

    assert len(problems) == 1
    assert problems[0].startswith("src/Demo-Core/Demo.class.st: ")


def test_validate_paths_ignores_missing_files(tmp_path: Path):
    assert validate_paths(tmp_path, ["deleted/Thing.class.st"]) == []
