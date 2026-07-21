# Local AI CI Controller

This repository now includes a small controller that sits between GitHub and a locally hosted model. The model never receives a GitHub token and never talks to GitHub directly.

```text
GitHub workflow_dispatch
        |
self-hosted runner
        |
scripts/ai-ci-controller
        |-- gh + git clone/checkout
        |-- local RAG context pack
        |-- Ollama review call
        |-- aider edit pass for fix modes
        |-- lint/tests + git diff --check
        |-- PR comment or draft PR
```

## What It Can Do

- `review-pr`: checks out a pull request, retrieves relevant local repo context, asks Ollama for a structured review, validates file/line references, and posts a PR comment.
- `fix-pr`: checks out a pull request, gives Aider a scoped task with retrieved context and existing review comments, runs validation, commits the result, pushes a branch, and opens a draft follow-up PR.
- `issue-pr`: checks out the default branch, implements a GitHub issue with Aider, validates it, and opens a draft PR.

## Runner Setup

Install these on the dedicated CI machine:

```bash
ollama pull <your-coding-model>
OLLAMA_CONTEXT_LENGTH=8192 ollama serve

python -m pip install aider-install
aider-install

gh auth login
```

For GitHub Actions, register the machine as a self-hosted runner with the label `local-ai`.

Set these repository or organization variables:

- `LOCAL_AI_MODEL`: the Ollama model name, for example `qwen2.5-coder:14b`.
- `OLLAMA_BASE_URL`: optional, defaults to `http://127.0.0.1:11434`.
- `LOCAL_AI_TEST_CMD`: optional final test command.
- `LOCAL_AI_LINT_CMD`: optional final lint command.

The workflows use `GITHUB_TOKEN`. For a long-running shared service, use a GitHub App or a fine-grained token scoped only to the target repositories.

## Run Locally

```bash
export MODEL="<your-coding-model>"
export OLLAMA_BASE_URL="http://127.0.0.1:11434"
export TEST_CMD="pytest -q"

./scripts/ai-ci-controller review-pr --repo OWNER/REPO --pr 123 --dry-run
./scripts/ai-ci-controller fix-pr --repo OWNER/REPO --pr 123 --dry-run
./scripts/ai-ci-controller issue-pr --repo OWNER/REPO --issue 456 --dry-run
```

Remove `--dry-run` only after the runner, credentials, model, and validation commands are correct.

## RAG And Validation

The controller builds a local context pack from the checked out repository. It ranks changed files highest, then tests, docs, manifests, and files with lexical overlap against the PR title, body, and diff. The pack is written under the run artifacts directory as `rag-context.md`.

Validation is deliberately outside the model:

- review findings are sanitized so missing files, path traversal, and invalid line numbers are dropped or corrected;
- fix modes reject edits to secrets, `.env` files, and `.github/workflows`;
- `git diff --check` always runs before publishing;
- configured lint and test commands must pass before a draft PR is pushed.

This is not a replacement for human review. The generated PRs stay in draft state and branch protection should remain required.

## GitHub Actions

The included workflows are manual:

- `Local AI PR Review`
- `Local AI PR Autofix`
- `Local AI Issue PR`

Manual dispatch is intentional. Do not run untrusted public pull-request code on a valuable self-hosted machine. If you later add automatic triggers, restrict them to trusted private repositories or isolate each job in a disposable VM/container.

