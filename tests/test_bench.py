import json
from pathlib import Path

from ai_ci_controller.bench import (
    BenchReport,
    BenchResult,
    BenchTask,
    extract_code,
    load_tasks,
    parse_yes_no,
    render_scorecard,
    score_review,
    score_selector,
    score_tonel,
)

VALID_TONEL = """\
Class {
	#name : 'Counter',
	#superclass : 'Object',
	#instVars : [ 'count' ],
	#category : 'Bench-Core',
	#package : 'Bench-Core'
}

{ #category : 'accessing' }
Counter >> count [

	^ count
]
"""


def task(kind="tonel", **expect) -> BenchTask:
    return BenchTask(name="t", kind=kind, description="", prompt="p", expect=expect)


class FakePharo:
    def __init__(self, result: str, is_error: bool = False):
        self.result = result
        self.is_error = is_error
        self.calls: list[str] = []

    def evaluate(self, code: str) -> tuple[str, bool]:
        self.calls.append(code)
        return self.result, self.is_error


def test_real_benchmark_tasks_all_load_and_are_well_formed():
    tasks = load_tasks(Path("benchmarks/tasks"))

    assert len(tasks) >= 8
    for item in tasks:
        assert item.prompt.strip(), f"{item.name} has no prompt"
        if item.kind == "selector":
            assert item.expect.get("ground_truth"), f"{item.name} has no ground_truth expression"
        if item.kind == "review":
            assert item.expect.get("expect_file"), f"{item.name} has no expect_file"
        if item.kind == "tonel":
            assert item.expect.get("expect_selectors"), f"{item.name} expects no selectors"


def test_task_list_fields_parse_as_lists():
    tasks = {item.name: item for item in load_tasks(Path("benchmarks/tasks"))}

    keyword_task = tasks["tonel-keyword-selector"]
    assert keyword_task.expect["expect_selectors"] == ["at:put:", "initialize"]


def test_tonel_scoring_accepts_valid_source():
    status, detail = score_tonel(task(expect_class="Counter", expect_selectors=["count"]), VALID_TONEL)

    assert status == "pass"
    assert "1 method" in detail


def test_tonel_scoring_accepts_source_inside_a_code_fence():
    fenced = f"Here you go:\n```smalltalk\n{VALID_TONEL}```\n"

    status, _ = score_tonel(task(expect_class="Counter", expect_selectors=["count"]), fenced)

    assert status == "pass"


def test_tonel_scoring_rejects_unparseable_output():
    status, detail = score_tonel(task(expect_selectors=["count"]), "class Counter:\n  pass")

    assert status == "fail"
    assert "does not parse as Tonel" in detail


def test_tonel_scoring_rejects_a_missing_selector():
    status, detail = score_tonel(task(expect_selectors=["count", "increment"]), VALID_TONEL)

    assert status == "fail"
    assert "increment" in detail


def test_tonel_scoring_rejects_the_wrong_class_name():
    status, detail = score_tonel(task(expect_class="Registry", expect_selectors=[]), VALID_TONEL)

    assert status == "fail"
    assert "expected 'Registry'" in detail


def test_tonel_scoring_checks_the_class_side():
    status, detail = score_tonel(
        task(expect_selectors=[], expect_class_selectors=["default"]), VALID_TONEL
    )

    assert status == "fail"
    assert "class-side" in detail


def test_tonel_scoring_rejects_empty_output():
    assert score_tonel(task(expect_selectors=[]), "   ")[0] == "fail"


def test_selector_scoring_agrees_with_the_image():
    pharo = FakePharo("true")

    status, detail = score_selector(task("selector", ground_truth="expr"), "yes", pharo=pharo)

    assert status == "pass"
    assert pharo.calls == ["expr"]
    assert "agrees with the image" in detail


def test_selector_scoring_catches_a_hallucinated_method():
    status, detail = score_selector(
        task("selector", ground_truth="expr"), "Yes, it does.", pharo=FakePharo("false")
    )

    assert status == "fail"
    assert "claimed it exists when it does not" in detail


def test_selector_scoring_catches_wrongly_denying_a_real_method():
    status, detail = score_selector(task("selector", ground_truth="e"), "no", pharo=FakePharo("true"))

    assert status == "fail"
    assert "claimed it does not exist when it does" in detail


def test_selector_scoring_rejects_a_non_answer():
    status, detail = score_selector(
        task("selector", ground_truth="e"), "It depends on the version.", pharo=FakePharo("true")
    )

    assert status == "fail"
    assert "did not answer yes or no" in detail


def test_selector_scoring_reports_a_broken_ground_truth():
    status, detail = score_selector(
        task("selector", ground_truth="e"), "yes", pharo=FakePharo("MessageNotUnderstood", is_error=True)
    )

    assert status == "error"
    assert "ground truth expression failed" in detail


def test_selector_scoring_skips_without_an_image():
    assert score_selector(task("selector", ground_truth="e"), "yes", pharo=None)[0] == "skip"


def test_review_scoring_accepts_a_finding_in_the_right_file():
    output = json.dumps(
        {"findings": [{"file": "src/Bench-Core/Counter.class.st", "title": "count may be nil"}]}
    )

    status, _ = score_review(
        task("review", expect_file="src/Bench-Core/Counter.class.st", expect_keywords=["nil"]), output
    )

    assert status == "pass"


def test_review_scoring_rejects_a_finding_in_the_wrong_file():
    output = json.dumps({"findings": [{"file": "README.md", "title": "typo"}]})

    status, detail = score_review(
        task("review", expect_file="src/Bench-Core/Counter.class.st", expect_keywords=[]), output
    )

    assert status == "fail"
    assert "README.md" in detail


def test_review_scoring_rejects_an_empty_finding_list():
    status, detail = score_review(task("review", expect_file="a.st"), json.dumps({"findings": []}))

    assert status == "fail"
    assert "no findings" in detail


def test_review_scoring_rejects_non_json():
    assert score_review(task("review", expect_file="a.st"), "looks fine to me")[0] == "fail"


def test_review_scoring_requires_a_keyword_when_one_is_asked_for():
    output = json.dumps({"findings": [{"file": "a.st", "title": "style nit"}]})

    status, detail = score_review(
        task("review", expect_file="a.st", expect_keywords=["nil", "initialize"]), output
    )

    assert status == "fail"
    assert "never mentioned" in detail


def test_yes_no_parsing():
    assert parse_yes_no("yes") is True
    assert parse_yes_no("No.") is False
    assert parse_yes_no("  TRUE  ") is True
    assert parse_yes_no("maybe") is None


def test_extract_code_prefers_the_block_containing_a_class_definition():
    output = "```\nnot it\n```\n```smalltalk\nClass {\n#name : 'X'\n}\n```"

    assert "Class {" in extract_code(output)


def test_extract_code_falls_back_to_raw_output():
    assert extract_code("Class { #name : 'X' }") == "Class { #name : 'X' }"


def report_with(*statuses: str) -> BenchReport:
    report = BenchReport(model="m", grounded=True)
    for index, status in enumerate(statuses):
        report.results.append(
            BenchResult(
                task=task(kind="tonel"),
                status=status,
                detail=f"detail {index}",
                output="",
                seconds=1.0,
            )
        )
    return report


def test_report_excludes_skips_from_the_score():
    report = report_with("pass", "fail", "skip", "skip")

    assert report.total == 2
    assert report.passed == 1
    assert report.pass_rate == 0.5


def test_report_with_only_skips_does_not_divide_by_zero():
    assert report_with("skip", "skip").pass_rate == 0.0


def test_scorecard_flags_harness_errors_separately_from_a_low_score():
    scorecard = render_scorecard(report_with("pass", "error"))

    assert "failed inside the harness" in scorecard
    assert "say nothing about the model" in scorecard


def test_scorecard_warns_when_the_image_was_missing():
    scorecard = render_scorecard(report_with("pass", "skip"))

    assert "no Pharo image was available" in scorecard


def test_scorecard_records_grounding_mode():
    grounded = render_scorecard(report_with("pass"))
    report = report_with("pass")
    report.grounded = False

    assert "with a live Pharo image" in grounded
    assert "no tools (raw model)" in render_scorecard(report)


def test_scorecard_never_claims_to_be_a_gate():
    assert "not a gate" in render_scorecard(report_with("fail", "fail"))


def test_load_tasks_ignores_a_missing_directory(tmp_path: Path):
    assert load_tasks(tmp_path / "nope") == []


def test_load_tasks_ignores_unknown_kinds(tmp_path: Path):
    directory = tmp_path / "tasks"
    directory.mkdir()
    (directory / "bad.md").write_text("---\nname: x\nkind: nonsense\n---\n\nbody\n", encoding="utf-8")

    assert load_tasks(directory) == []
