from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .command import run


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    body: str
    url: str
    base_ref: str
    head_ref: str
    head_repo_name_with_owner: str
    head_owner: str
    base_repo_name_with_owner: str
    author_login: str

    @property
    def same_repository(self) -> bool:
        return self.head_repo_name_with_owner == self.base_repo_name_with_owner


def gh_json(args: list[str], *, cwd: Path | None = None) -> dict:
    result = run(["gh", *args], cwd=cwd)
    return json.loads(result.stdout)


def issue_json(repo: str, issue_number: int) -> dict:
    return gh_json(
        [
            "issue",
            "view",
            str(issue_number),
            "--repo",
            repo,
            "--json",
            "number,title,body,url",
        ]
    )


def pr_metadata(repo: str, pr_number: int) -> PullRequest:
    payload = gh_json(
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            ",".join(
                [
                    "number",
                    "title",
                    "body",
                    "url",
                    "baseRefName",
                    "headRefName",
                    "headRepository",
                    "headRepositoryOwner",
                    "baseRepository",
                    "author",
                ]
            ),
        ]
    )
    return PullRequest(
        number=int(payload["number"]),
        title=payload.get("title") or "",
        body=payload.get("body") or "",
        url=payload.get("url") or "",
        base_ref=payload.get("baseRefName") or "main",
        head_ref=payload.get("headRefName") or "",
        head_repo_name_with_owner=(payload.get("headRepository") or {}).get("nameWithOwner") or "",
        head_owner=(payload.get("headRepositoryOwner") or {}).get("login") or "",
        base_repo_name_with_owner=(payload.get("baseRepository") or {}).get("nameWithOwner") or repo,
        author_login=(payload.get("author") or {}).get("login") or "",
    )


def pr_diff(repo: str, pr_number: int) -> str:
    return run(["gh", "pr", "diff", str(pr_number), "--repo", repo, "--patch"]).stdout


def clone_repo(repo: str, destination: Path) -> None:
    run(["gh", "repo", "clone", repo, str(destination)])


def checkout_pr(repo_dir: Path, pr_number: int) -> None:
    run(["gh", "pr", "checkout", str(pr_number)], cwd=repo_dir)


def checkout_base(repo_dir: Path, base_ref: str, branch_name: str) -> None:
    run(["git", "fetch", "origin", base_ref], cwd=repo_dir)
    run(["git", "switch", "-c", branch_name, f"origin/{base_ref}"], cwd=repo_dir)


def post_pr_comment(repo: str, pr_number: int, body_file: Path) -> None:
    run(["gh", "pr", "comment", str(pr_number), "--repo", repo, "--body-file", str(body_file)])


def create_draft_pr(
    repo: str,
    *,
    base: str,
    head: str,
    title: str,
    body_file: Path,
) -> str:
    result = run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            repo,
            "--draft",
            "--base",
            base,
            "--head",
            head,
            "--title",
            title,
            "--body-file",
            str(body_file),
        ]
    )
    return result.stdout.strip()

