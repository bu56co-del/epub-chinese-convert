# Project conventions for Claude Code

This is `epubconv` — an EPUB Chinese-variant converter with a Claude-Skill
exporter. End-user docs live in `README.md`; this file is for Claude Code
sessions working on the repo.

## Local environment (do NOT re-bootstrap)

The user develops on macOS. Their working tree is at
`/Users/yakafung/Desktop/ai project/epub-chinese-convert` and a venv lives
at `.venv/` with `pip install -e ".[web,llm,dev]"` already applied.

**Do not include `pip install -e ".[...]"` in commands you give the user.**
If you genuinely need a new dependency, call it out as a one-time install
step rather than burying it in the run command.

## After every PR (or feature push), provide a single Mac-terminal command

End your reply with one copy-pasteable block the user can paste into Mac
terminal that:

1. `cd`s into the project dir
2. Fetches and checks out the PR's branch
3. Activates the venv
4. Runs whatever the PR delivers (`epubconv serve`, a CLI command, etc.)

Use this template (chain with `&&` so a failure stops the rest):

```bash
cd "/Users/yakafung/Desktop/ai project/epub-chinese-convert" && \
git fetch origin <branch> && \
git checkout <branch> && \
git pull origin <branch> && \
source .venv/bin/activate && \
<feature-specific command>
```

Replace `<branch>` and `<feature-specific command>` per PR. If the feature
is the web UI, the last line is `epubconv serve` and you should also tell
the user the URL (`http://127.0.0.1:8000`).

If the PR was merged into the default branch, swap the branch reference
for the default branch (`claude/ebook-chinese-translator-mcmy8`) so the
user is testing what's actually shipped.

## Other conventions

- The user prefers Cantonese. Reply in Cantonese; keep code, commit
  messages, and file content in English.
- Develop on the branch named in the active session (typically
  `claude/connect-repo-pr-ETkRr`). Never push to the default branch.
- Always create a PR after pushing if one doesn't exist; mark it ready
  for review (not draft). Don't ask first.
- The user uses `setopt interactive_comments` in zsh, but command blocks
  you give them should still be paste-safe — avoid bare `#` comments inside
  the command itself; put any commentary outside the code block.
