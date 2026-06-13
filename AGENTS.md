# AGENTS.md

## Working Style

- This is a solo-developer project.
- Work usually happens directly on `main` in small incremental changes.
- Keep changes tightly scoped to the requested task.
- The user should be able to state only the desired end state or goal. Do not require the user to remind you to read project guidance.
- Do not create branches, worktrees, or broad refactors unless explicitly asked.
- Do not relitigate settled architecture, naming, deployment, or workflow choices unless the requested change requires it.
- Prefer targeted reads with `rg` over re-reading the whole repository.
- Preserve existing behavior unless the prompt explicitly asks to change it.
- Preserve existing local/user changes. Never revert unrelated changes.
- Do not deploy to production unless Matthew explicitly asks for production deployment in the current thread.

## First Steps In Every Task

- Check the current git status.
- Read `docs/AGENT_BRIEF.md` before broad exploration if it exists.
- Read `docs/DECISIONS.md` before revisiting architecture, naming, workflow, deployment, data shape, or other settled choices.
- Read only the files relevant to the requested change.
- Before editing, identify the likely files or modules affected.
- If the change touches live deploy behavior, scoring, parsing, cron jobs, security, or remote sync behavior, pause and summarize the plan before editing unless Matthew has already approved the approach.

## Default Interpretation Of Prompts

- Treat short prompts as intentional. Infer the narrowest reasonable implementation path from the repo brief and existing project patterns.
- The user describes the desired end state or goal; Codex is responsible for designing the solution path.
- Do not require the user to define implementation details, file choices, architecture, or command sequences unless those choices materially affect the desired outcome.
- Ask focused clarifying questions when the goal is ambiguous, when multiple outcomes are plausible, or when a missing detail would make the change risky, destructive, or likely wrong.
- Prefer one or two concrete questions over a broad planning discussion.
- If reasonable defaults are clear from existing project patterns, proceed without asking.
- If the goal is clear, proceed through implementation, verification, and a concise final report.

## Verification

Use the narrowest verification that proves the change.

For PHP or WordPress changes:

- Run `php -l` on changed PHP files.
- Run any project-specific checks documented in `docs/AGENT_BRIEF.md`.
- For risky changes, report staging or production impact.

For JavaScript, TypeScript, or frontend changes:

- Run the project lint, typecheck, test, or build command documented in `docs/AGENT_BRIEF.md`.
- If UI behavior changes, verify the relevant screen or flow when practical.

## Final Response

Always include:

- What changed
- Files changed
- Verification run and results
- Any deploy or staging risk
