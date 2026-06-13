# Decisions

## Active Decisions

### Use main-first incremental development

Reason: This is a solo-developer workflow optimized for small, fast updates.

Implication: Do not introduce branches, worktrees, or multi-agent workflows unless the task is risky enough to justify the overhead or Matthew explicitly asks for it.

### Use end-state driven prompting

Reason: Matthew should be able to describe what he wants the project to do without specifying how Codex should implement it.

Implication: Codex owns solution design, file selection, implementation, and verification. Ask focused clarifying questions only when the desired end state is ambiguous or a missing detail would materially affect correctness, risk, or user-visible behavior.

### Keep changes tightly scoped

Reason: The priority is getting the requested change right the first time without breaking adjacent behavior.

Implication: Avoid unrelated cleanup, formatting churn, broad refactors, dependency changes, or architecture changes during ordinary fixes.

### Do not relitigate settled choices

Reason: Re-evaluating old naming, architecture, deployment, or workflow decisions wastes tokens and slows down incremental work.

Implication: Follow existing project patterns unless the requested change directly conflicts with them.

### Production deploys require explicit approval

Reason: Production changes can affect live sites and users.

Implication: Codex may prepare, inspect, and summarize deployment steps, but must not deploy to production unless Matthew explicitly asks in the current thread.

### Preserve existing public behavior

Reason: Existing frontend code, remote integrations, cron jobs, parser assumptions, and users may depend on current behavior.

Implication: Keep API response shapes, option names, database expectations, and output formats backward-compatible unless Matthew explicitly asks for a breaking change.

### Prefer targeted context gathering

Reason: New threads should be fast and token-efficient.

Implication: Start with `docs/AGENT_BRIEF.md`, `git status --short`, and focused `rg` searches instead of re-reading the entire repository.

## Retired Or Reconsidered Decisions

Move decisions here when they no longer apply, with a short reason.
