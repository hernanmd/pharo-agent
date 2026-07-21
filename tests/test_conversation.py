from ai_ci_controller.conversation import (
    AI_MARKER,
    Conversation,
    ReviewComment,
    ReviewThread,
    SubmittedReview,
    is_ai_author,
    parse_thread,
)


def comment(author="admin", body="please fix", created="2026-07-01T10:00:00Z", **overrides):
    fields = dict(
        id=1,
        author=author,
        body=body,
        path="src/Demo.class.st",
        line=12,
        diff_hunk="@@ -1 +1 @@",
        created_at=created,
    )
    fields.update(overrides)
    return ReviewComment(**fields)


def thread(*comments, id="T1", resolved=False, outdated=False):
    return ReviewThread(id=id, is_resolved=resolved, is_outdated=outdated, comments=list(comments))


def test_ai_authors_are_recognised():
    assert is_ai_author("github-actions[bot]")
    assert is_ai_author("github-actions")
    assert not is_ai_author("omar")


def test_comment_from_marker_is_treated_as_ours():
    assert comment(author="omar", body=f"hi\n\n{AI_MARKER}").from_ai
    assert not comment(author="omar", body="hi").from_ai


def test_thread_needs_response_when_human_spoke_last():
    human_last = thread(comment(id=1), comment(id=2, author="github-actions[bot]"), comment(id=3))
    ai_last = thread(comment(id=1), comment(id=2, author="github-actions[bot]"))

    assert human_last.needs_response
    assert not ai_last.needs_response


def test_resolved_threads_are_skipped():
    assert not thread(comment(), resolved=True).needs_response


def test_empty_thread_needs_no_response():
    assert not thread().needs_response


def test_root_comment_id_is_the_first_comment():
    assert thread(comment(id=41), comment(id=42)).root_comment_id == 41


def test_pending_threads_filters_correctly():
    conversation = Conversation(
        head_ref="ai/issue-7-20260701-100000",
        threads=[
            thread(comment(id=1), id="needs"),
            thread(comment(id=2), id="resolved", resolved=True),
            thread(comment(id=3), comment(id=4, author="github-actions[bot]"), id="answered"),
        ],
        reviews=[],
    )

    assert [item.id for item in conversation.pending_threads()] == ["needs"]
    assert conversation.has_pending_work()


def test_ai_branch_detection():
    def branch(name):
        return Conversation(head_ref=name, threads=[], reviews=[])

    assert branch("ai/issue-7-20260701-100000").is_ai_branch
    assert branch("ai/fix-pr-12-20260701-100000").is_ai_branch
    assert not branch("feature/login").is_ai_branch
    assert not branch("ai/something-else").is_ai_branch


def test_pending_reviews_ignores_ours_and_older_ones():
    conversation = Conversation(
        head_ref="ai/issue-1-x",
        threads=[],
        reviews=[
            SubmittedReview(id=1, author="omar", state="COMMENTED", body="old", submitted_at="2026-07-01T09:00:00Z"),
            SubmittedReview(id=2, author="github-actions[bot]", state="COMMENTED", body="mine", submitted_at="2026-07-01T10:00:00Z"),
            SubmittedReview(id=3, author="omar", state="CHANGES_REQUESTED", body="new", submitted_at="2026-07-01T11:00:00Z"),
        ],
    )

    assert [item.id for item in conversation.pending_reviews()] == [3]


def test_reviews_without_a_body_are_not_pending():
    conversation = Conversation(
        head_ref="ai/issue-1-x",
        threads=[],
        reviews=[SubmittedReview(id=1, author="omar", state="APPROVED", body="  ", submitted_at="2026-07-01T09:00:00Z")],
    )

    assert conversation.pending_reviews() == []
    assert not conversation.has_pending_work()


def test_render_includes_location_diff_and_authors():
    conversation = Conversation(
        head_ref="ai/issue-1-x",
        threads=[thread(comment(body="this selector does not exist"))],
        reviews=[],
    )

    rendered = conversation.render()

    assert "src/Demo.class.st:12" in rendered
    assert "@@ -1 +1 @@" in rendered
    assert "admin" in rendered
    assert "this selector does not exist" in rendered


def test_render_marks_outdated_threads():
    conversation = Conversation(
        head_ref="ai/issue-1-x",
        threads=[thread(comment(), outdated=True)],
        reviews=[],
    )

    assert "outdated" in conversation.render()


def test_parse_thread_falls_back_to_original_line():
    node = {
        "id": "T9",
        "isResolved": False,
        "isOutdated": True,
        "comments": {
            "nodes": [
                {
                    "databaseId": 55,
                    "body": "hi",
                    "path": "a.st",
                    "line": None,
                    "originalLine": 31,
                    "diffHunk": "@@",
                    "createdAt": "2026-07-01T10:00:00Z",
                    "author": {"login": "omar"},
                }
            ]
        },
    }

    parsed = parse_thread(node)

    assert parsed.comments[0].line == 31
    assert parsed.comments[0].id == 55


def test_parse_thread_survives_a_deleted_author():
    node = {
        "id": "T9",
        "comments": {"nodes": [{"databaseId": 1, "body": "x", "path": "a.st", "author": None}]},
    }

    assert parse_thread(node).comments[0].author == "unknown"
