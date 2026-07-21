from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .command import run

AI_MARKER = "<!-- ai-ci-controller -->"
AI_BRANCH_RE = re.compile(r"^ai/(issue|fix-pr)-\d+-")

THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      headRefName
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
          isOutdated
          comments(first: 100) {
            nodes {
              databaseId
              body
              path
              line
              originalLine
              diffHunk
              createdAt
              author { login }
            }
          }
        }
      }
      reviews(first: 100) {
        nodes {
          databaseId
          state
          body
          submittedAt
          author { login }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class ReviewComment:
    id: int
    author: str
    body: str
    path: str
    line: int | None
    diff_hunk: str
    created_at: str

    @property
    def from_ai(self) -> bool:
        return is_ai_author(self.author) or AI_MARKER in self.body

    def render(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"[{self.created_at}] {self.author} on {location}:\n{self.body.strip()}"


@dataclass(frozen=True)
class ReviewThread:
    id: str
    is_resolved: bool
    is_outdated: bool
    comments: list[ReviewComment]

    @property
    def path(self) -> str:
        return self.comments[0].path if self.comments else ""

    @property
    def line(self) -> int | None:
        return self.comments[0].line if self.comments else None

    @property
    def root_comment_id(self) -> int:
        return self.comments[0].id if self.comments else 0

    @property
    def diff_hunk(self) -> str:
        return self.comments[0].diff_hunk if self.comments else ""

    @property
    def needs_response(self) -> bool:
        if self.is_resolved or not self.comments:
            return False
        return not self.comments[-1].from_ai

    def render(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path or "(no file)"
        header = f"### Thread {self.id} on {location}"
        if self.is_outdated:
            header += " (outdated, the line has since changed)"
        parts = [header]
        if self.diff_hunk:
            parts.append(f"```diff\n{self.diff_hunk.strip()}\n```")
        parts.extend(comment.render() for comment in self.comments)
        return "\n\n".join(parts)


@dataclass(frozen=True)
class SubmittedReview:
    id: int
    author: str
    state: str
    body: str
    submitted_at: str

    @property
    def from_ai(self) -> bool:
        return is_ai_author(self.author) or AI_MARKER in self.body

    def render(self) -> str:
        return f"[{self.submitted_at}] {self.author} submitted {self.state}:\n{self.body.strip()}"


@dataclass(frozen=True)
class Conversation:
    head_ref: str
    threads: list[ReviewThread]
    reviews: list[SubmittedReview]

    @property
    def is_ai_branch(self) -> bool:
        return bool(AI_BRANCH_RE.match(self.head_ref))

    def pending_threads(self) -> list[ReviewThread]:
        return [thread for thread in self.threads if thread.needs_response]

    def pending_reviews(self) -> list[SubmittedReview]:
        latest_ai = max(
            (review.submitted_at for review in self.reviews if review.from_ai),
            default="",
        )
        return [
            review
            for review in self.reviews
            if not review.from_ai and review.body.strip() and review.submitted_at > latest_ai
        ]

    def has_pending_work(self) -> bool:
        return bool(self.pending_threads() or self.pending_reviews())

    def render(self, *, pending_only: bool = True) -> str:
        threads = self.pending_threads() if pending_only else self.threads
        reviews = self.pending_reviews() if pending_only else self.reviews

        blocks: list[str] = []
        if reviews:
            blocks.append("## Submitted reviews awaiting a response\n")
            blocks.extend(review.render() for review in reviews)
        if threads:
            blocks.append("## Review threads awaiting a response\n")
            blocks.extend(thread.render() for thread in threads)
        if not blocks:
            return "(nothing is awaiting a response)"
        return "\n\n".join(blocks)


def fetch_conversation(repo: str, pr_number: int) -> Conversation:
    owner, _, name = repo.partition("/")
    result = run(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={THREADS_QUERY}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"number={pr_number}",
        ],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not read the PR conversation:\n{result.combined_output}")

    payload = json.loads(result.stdout or "{}")
    pull_request = (
        ((payload.get("data") or {}).get("repository") or {}).get("pullRequest") or {}
    )

    threads = [
        parse_thread(node)
        for node in ((pull_request.get("reviewThreads") or {}).get("nodes") or [])
        if node
    ]
    reviews = [
        SubmittedReview(
            id=int(node.get("databaseId") or 0),
            author=((node.get("author") or {}).get("login")) or "unknown",
            state=str(node.get("state") or "COMMENTED"),
            body=str(node.get("body") or ""),
            submitted_at=str(node.get("submittedAt") or ""),
        )
        for node in ((pull_request.get("reviews") or {}).get("nodes") or [])
        if node
    ]

    return Conversation(
        head_ref=str(pull_request.get("headRefName") or ""),
        threads=[thread for thread in threads if thread.comments],
        reviews=reviews,
    )


def parse_thread(node: dict) -> ReviewThread:
    comments = []
    for comment in ((node.get("comments") or {}).get("nodes") or []):
        if not comment:
            continue
        line = comment.get("line")
        if line is None:
            line = comment.get("originalLine")
        comments.append(
            ReviewComment(
                id=int(comment.get("databaseId") or 0),
                author=((comment.get("author") or {}).get("login")) or "unknown",
                body=str(comment.get("body") or ""),
                path=str(comment.get("path") or ""),
                line=int(line) if isinstance(line, int) else None,
                diff_hunk=str(comment.get("diffHunk") or ""),
                created_at=str(comment.get("createdAt") or ""),
            )
        )
    return ReviewThread(
        id=str(node.get("id") or ""),
        is_resolved=bool(node.get("isResolved")),
        is_outdated=bool(node.get("isOutdated")),
        comments=comments,
    )


def reply_to_thread(repo: str, pr_number: int, comment_id: int, body: str) -> None:
    with_marker = body if AI_MARKER in body else f"{body}\n\n{AI_MARKER}"
    result = run(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"repos/{repo}/pulls/{pr_number}/comments/{comment_id}/replies",
            "-f",
            f"body={with_marker}",
        ],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not reply to review comment {comment_id}:\n{result.combined_output}"
        )


def post_conversation_comment(repo: str, pr_number: int, body_file: Path) -> None:
    run(["gh", "pr", "comment", str(pr_number), "--repo", repo, "--body-file", str(body_file)])


def is_ai_author(login: str) -> bool:
    return login.endswith("[bot]") or login in {"github-actions", "ai-ci-controller"}
