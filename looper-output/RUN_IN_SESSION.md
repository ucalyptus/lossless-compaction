# Run `multi-model-issue-close` In This Session

Use this prompt when the user wants to run the Looper-designed loop in the current LLM session.
This is the default/easy execution path. The Python runner is the advanced path for running later or outside the session.

## Operator Instructions

You are executing a Looper-designed loop in this current session.
Follow the resolved spec below, write handoff files into the workspace, and enforce the caps manually.
Do not use `run-loop.py` unless the user explicitly asks for the advanced external runner.

1. Create the workspace directory if it does not exist.
2. Read the context sources before drafting the plan.
3. Draft `plan.md` in the workspace.
4. Run the plan gate. Apply programmatic checks when available. For judge criteria, use the configured judge only after consent for any non-local egress; otherwise ask the user to approve a human/current-session substitute.
5. Revise until the gate passes or `max_revisions` is reached.
6. Produce `delivery-N.md` in the workspace.
7. Run the delivery gate after each delivery.
8. Stop when all delivery criteria pass, a cap is reached, or the user stops the loop.
9. Keep `state.json` current with status, iteration, last gate, consent, and blockers.
10. Append a compact entry to `run-log.md` after every context read, model call, check, gate verdict, revision, blocker, and stop decision.
11. Compare each blocker against the previous blocker. If the same blocker repeats for the configured no-progress window, stop or ask for the configured human checkpoint instead of revising again.
12. Treat token and USD budgets as operator limits in this session: if exact accounting is unavailable, stop and ask before continuing when the loop appears likely to exceed them.

## Files

- Source spec: `loop.yaml`
- Human summary: `LOOP.md`
- Resolved spec: `loop.resolved.json`
- Workspace: `./loop-workspace`
- State file: `state.json`
- Run log: `run-log.md`

## Goal

Close all open GitHub issues in a target repository by: (1) reading each open issue, (2) spawning a parallel Claude agent per issue to implement the fix in an isolated git worktree and file a PR, (3) reviewing each PR with a cross-model judge (DeepSeek or GLM-5.2), (4) auto-merging approved PRs, and (5) spawning fix agents for blocked PRs and re-reviewing. The loop ends when all issues are closed or three fix rounds have elapsed.

## Definition Of Done

All open GitHub issues are closed (gh issue list returns empty) OR three implement-review-fix rounds have elapsed. Each closed issue has a merged PR. run-log.md records each round's implement/review/merge/fix decisions. state.json shows status: passed.

## Context Sources

- Run command `["gh", "issue", "list", "--repo", "ksimback/lossless-compaction", "--state", "open", "--json", "number,title,body"]`
- Run command `["gh", "pr", "list", "--repo", "ksimback/lossless-compaction", "--state", "open", "--json", "number,title,headRefName,reviewDecision"]`
- Run command `["git", "log", "--oneline", "-20"]`

## Verification Criteria

- `all-issues-closed` programmatic: run `["bash", "-c", "test -z \"$(gh issue list --repo ksimback/lossless-compaction --state open --json number -q '.[].number')\""]` and expect `exit_zero`
- `pr-quality` judge rubric: Each merged PR in this round: (a) references the issue it closes, (b) makes a focused change that directly addresses the issue description, (c) does not introduce new test failures (check for test file changes alongside code changes), and (d) has a coherent commit message. Flag any PR where the change is unrelated to the issue or where core logic was removed rather than fixed.

- `human-final-review` human signoff: All PRs have been implemented, reviewed, and merged. Please spot-check 2-3 closed issues and their linked PRs to confirm the fixes are sound. Type 'pass' to accept the run, or describe what needs revision.


## Council

- `deepseek-judge` judge via `["hermes", "chat", "--provider", "deepseek", "-m", "deepseek-v4-pro", "-q"]` (non-local; timeout 120s)
- `gpt55-reviewer` reviewer via `["hermes", "chat", "-q"]` (non-local; timeout 120s)
- `glm52-reviewer` reviewer via `["hermes", "chat", "--provider", "openrouter", "-m", "z-ai/glm-5.2", "-q"]` (non-local; timeout 180s)

## Gates

### plan_gate

- When: `after_plan`
- Policy: `revise_until_clean`
- Verdict source: `human`
- Criteria: `pr-quality`
- Max revisions: `2`

### delivery_gate

- When: `after_each_delivery`
- Policy: `revise_until_clean`
- Verdict source: `deepseek-judge`
- Criteria: `all-issues-closed, pr-quality`
- Max revisions: `3`

## Loop Control

- Max iterations: `9`
- Budget: `{"tokens": 4000000, "usd": 10.0, "wall_clock_min": 60}`
- No-progress: `{"action": "stop", "max_stalled_iterations": 2, "signals": ["open issue count unchanged between rounds", "same PR blocked by same review note twice", "worktree agent exits without producing a commit"]}`
- Human checkpoints: `after_plan`
- Stop conditions:
  - all-issues-closed criterion passes (gh issue list empty)
  - max_iterations reached
  - no_progress detected for 2 consecutive rounds
  - any budget cap exceeded

## Execution Boundary

- Mode: `in_session`
- Isolation: `worktree`
- Side effects: `{"duplicate_action_check": true, "requires_approval": true, "side_effect_list": ["git push (creates remote branch per issue)", "gh pr create (files PR per issue)", "gh pr merge (merges approved PRs)", "gh pr comment (posts review notes)", "gh issue close (closes issue on merge)"]}`

If the loop needs scheduled runs, child-agent lifecycle management, concurrency control, or restart-safe step retries, stop and tell the user this Looper spec should be handed to a durable orchestrator.

## Observability

- State file: `state.json`
- Run log: `run-log.md`
- Checkpoint granularity: `gate`

Use `state.json` for the latest resumable status and `run-log.md` for the append-only history of what happened.

## Privacy

- Before sending `plan, deliveries, issue-descriptions, code-diffs` to `deepseek-judge`, confirm consent and apply redactions `.env, .env.*, secrets/**, **/*.key, ~/.env`.
- Before sending `plan, deliveries, issue-descriptions` to `gpt55-reviewer`, confirm consent and apply redactions `.env, .env.*, secrets/**, **/*.key, ~/.env`.
- Before sending `deliveries, code-diffs` to `glm52-reviewer`, confirm consent and apply redactions `.env, .env.*, secrets/**, **/*.key, ~/.env`.

## Start Now

If the user asked to run now, begin at step 1 under Operator Instructions and keep going until a stop condition is reached.
