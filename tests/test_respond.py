import json

from ai_ci_controller.cli import parse_response_plan, render_response_summary, render_thread_reply
from ai_ci_controller.conversation import AI_MARKER, ReviewComment, ReviewThread
from ai_ci_controller.model_router import DiffStats, ModelSelection, score_change


def make_thread(thread_id: str) -> ReviewThread:
    return ReviewThread(
        id=thread_id,
        is_resolved=False,
        is_outdated=False,
        comments=[
            ReviewComment(
                id=1,
                author="omar",
                body="please fix",
                path="src/Demo.class.st",
                line=12,
                diff_hunk="@@",
                created_at="2026-07-01T10:00:00Z",
            )
        ],
    )


def plan_json(**overrides) -> str:
    payload = {
        "summary": "Two points raised.",
        "review_reply": "Thanks for the review.",
        "responses": [
            {
                "thread_id": "T1",
                "verdict": "agree",
                "reply": "You are right, the guard is missing.",
                "evidence": "",
                "change": "Add a nil check in Demo>>count",
            },
            {
                "thread_id": "T2",
                "verdict": "disagree",
                "reply": "That selector does exist.",
                "evidence": "OrderedCollection new addAll: #(1 2) -> an OrderedCollection(1 2)",
                "change": "",
            },
        ],
    }
    payload.update(overrides)
    return json.dumps(payload)


THREADS = [make_thread("T1"), make_thread("T2")]


def test_plan_keeps_valid_responses():
    plan = parse_response_plan(plan_json(), THREADS)

    assert plan["summary"] == "Two points raised."
    assert plan["review_reply"] == "Thanks for the review."
    assert [item["verdict"] for item in plan["responses"]] == ["agree", "disagree"]
    assert plan["responses"][0]["change"] == "Add a nil check in Demo>>count"


def test_plan_drops_responses_for_unknown_threads():
    payload = json.loads(plan_json())
    payload["responses"].append({"thread_id": "T99", "verdict": "agree", "reply": "x", "change": "y"})

    plan = parse_response_plan(json.dumps(payload), THREADS)

    assert {item["thread_id"] for item in plan["responses"]} == {"T1", "T2"}


def test_plan_drops_duplicate_thread_responses():
    payload = json.loads(plan_json())
    payload["responses"].append({"thread_id": "T1", "verdict": "disagree", "reply": "second", "change": ""})

    plan = parse_response_plan(json.dumps(payload), THREADS)

    assert len(plan["responses"]) == 2
    assert plan["responses"][0]["reply"] == "You are right, the guard is missing."


def test_plan_backfills_threads_the_model_ignored():
    payload = json.loads(plan_json())
    payload["responses"] = [payload["responses"][0]]

    plan = parse_response_plan(json.dumps(payload), THREADS)

    backfilled = [item for item in plan["responses"] if item["thread_id"] == "T2"]
    assert backfilled and backfilled[0]["verdict"] == "needs-clarification"


def test_plan_normalises_an_unknown_verdict():
    payload = json.loads(plan_json())
    payload["responses"][0]["verdict"] = "sure thing"

    plan = parse_response_plan(json.dumps(payload), THREADS)

    assert plan["responses"][0]["verdict"] == "needs-clarification"


def test_plan_discards_changes_attached_to_a_disagreement():
    payload = json.loads(plan_json())
    payload["responses"][1]["change"] = "rewrite everything"

    plan = parse_response_plan(json.dumps(payload), THREADS)

    assert plan["responses"][1]["change"] == ""


def test_plan_recovers_json_wrapped_in_prose():
    wrapped = f"Sure, here you go:\n```json\n{plan_json()}\n```"

    plan = parse_response_plan(wrapped, THREADS)

    assert len(plan["responses"]) == 2


def test_agreed_reply_cites_the_pushed_sha():
    item = {"verdict": "agree", "reply": "Fixed.", "evidence": "", "change": "add a guard"}

    body = render_thread_reply(item, {"attempted": True, "pushed": True, "sha": "abc1234", "detail": ""})

    assert "**Agreed** — fixed in `abc1234`." in body
    assert "Change: add a guard" in body
    assert AI_MARKER in body


def test_agreed_reply_admits_a_failed_fix():
    item = {"verdict": "agree", "reply": "Fixed.", "evidence": "", "change": "add a guard"}
    amend = {"attempted": True, "pushed": False, "sha": "", "detail": "tests failed"}

    body = render_thread_reply(item, amend)

    assert "did not land: tests failed" in body


def test_disagreement_includes_evidence_and_defers_to_the_human():
    item = {
        "verdict": "disagree",
        "reply": "That selector does exist.",
        "evidence": "OrderedCollection new addAll: #(1 2) -> an OrderedCollection(1 2)",
        "change": "",
    }

    body = render_thread_reply(item, {"attempted": False, "pushed": False, "sha": "", "detail": ""})

    assert "not right" in body
    assert "leaving it for you to decide" in body
    assert "an OrderedCollection(1 2)" in body


def test_clarification_reply_asks_rather_than_asserts():
    item = {"verdict": "needs-clarification", "reply": "Which case?", "evidence": "", "change": ""}

    body = render_thread_reply(item, {"attempted": False, "pushed": False, "sha": "", "detail": ""})

    assert "Need a steer" in body
    assert "Which case?" in body


def selection() -> ModelSelection:
    stats = DiffStats(
        files_changed=1,
        additions=1,
        deletions=0,
        patch_chars=10,
        changed_files=["a.st"],
        docs_only=False,
        tests_only=False,
        has_lockfile=False,
        has_high_risk_path=False,
        has_high_risk_words=False,
    )
    return ModelSelection(tier="medium", model="m", score=3, reasons=["r"], stats=stats)


class FakeContext:
    def __init__(self, pharo_used=True):
        self.pharo_used = pharo_used
        self.skills = type("S", (), {"summary": lambda self: "pharo"})()


def test_summary_counts_verdicts_and_reports_the_push():
    plan = parse_response_plan(plan_json(), THREADS)
    amend = {"attempted": True, "pushed": True, "sha": "abc1234", "detail": "pushed as abc1234"}

    summary = render_response_summary(plan, amend, selection(), FakeContext())

    assert "1 agreed, 1 disputed, 0 needing a steer" in summary
    assert "pushed to this branch as `abc1234`" in summary
    assert "Disputed threads are left unresolved on purpose" in summary
    assert "live Pharo image" in summary


def test_summary_explains_when_nothing_was_pushed():
    plan = parse_response_plan(plan_json(), THREADS)
    amend = {"attempted": True, "pushed": False, "sha": "", "detail": "validation failed"}

    summary = render_response_summary(plan, amend, selection(), FakeContext(pharo_used=False))

    assert "No commit was pushed: validation failed" in summary
    assert "live Pharo image" not in summary


def test_respond_mode_routes_above_plain_fix_mode():
    stats = selection().stats
    respond_score, _ = score_change(stats, title="t", body="b", mode="respond")
    fix_score, _ = score_change(stats, title="t", body="b", mode="fix")

    assert respond_score > fix_score
