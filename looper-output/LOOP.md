# multi-model-issue-close

Fan-out multi-model code review → parallel worktree implement → cross-model PR review → auto-merge or fix loop. Used to close all open issues in a GitHub repo using an implementer-verifier-fixer agent pattern with cross-vendor judges.

## Goal

Close all open GitHub issues in a target repository by: (1) reading each open issue, (2) spawning a parallel Claude agent per issue to implement the fix in an isolated git worktree and file a PR, (3) reviewing each PR with a cross-model judge (DeepSeek or GLM-5.2), (4) auto-merging approved PRs, and (5) spawning fix agents for blocked PRs and re-reviewing. The loop ends when all issues are closed or three fix rounds have elapsed.

## Definition of Done

All open GitHub issues are closed (gh issue list returns empty) OR three implement-review-fix rounds have elapsed. Each closed issue has a merged PR. run-log.md records each round's implement/review/merge/fix decisions. state.json shows status: passed.

## Verification

- `all-issues-closed` (programmatic)
- `pr-quality` (judge)
- `human-final-review` (human)

## Council

- `deepseek-judge`: judge via hermes (deepseek-v4-pro)
- `gpt55-reviewer`: reviewer via hermes (gpt-5.5)
- `glm52-reviewer`: reviewer via hermes (z-ai/glm-5.2)

## Gates

- Plan gate: revise_until_clean
- Delivery gate: revise_until_clean

## Loop Control

- Max iterations: 9
- Budget: `{"tokens": 4000000, "usd": 10.0, "wall_clock_min": 60}`
- No-progress: `{"action": "stop", "max_stalled_iterations": 2, "signals": ["open issue count unchanged between rounds", "same PR blocked by same review note twice", "worktree agent exits without producing a commit"]}`

## Execution Boundary

- Mode: `in_session`
- Isolation: `worktree`
- Side effects: `{"duplicate_action_check": true, "requires_approval": true, "side_effect_list": ["git push (creates remote branch per issue)", "gh pr create (files PR per issue)", "gh pr merge (merges approved PRs)", "gh pr comment (posts review notes)", "gh issue close (closes issue on merge)"]}`

## Observability

- State file: `state.json`
- Run log: `run-log.md`
- Checkpoint granularity: `gate`

## Flow Preview

```text
+--------------------------------+
| 1. Goal + context              |
| read sources                   |
+--------------------------------+
               |
               v
+--------------------------------+
| 2. Draft plan.md               |
| state -> state.json            |
+--------------------------------+
               |
               v
+--------------------------------+
| 3. Plan gate                   |
| verdict: human                 |
+--------------------------------+
               | needs work -> revise <= 2 -> step 2
               | pass
               v
+--------------------------------+
| 4. Write delivery-N.md         |
| log -> run-log.md              |
+--------------------------------+
               |
               v
+--------------------------------+
| 5. Delivery gate               |
| verdict: deepseek-judge        |
+--------------------------------+
               | needs work -> revise <= 3 -> step 4
               | pass
               v
+--------------------------------+
| 6. Final output                |
| all gates clean                |
+--------------------------------+

Stops: pass gates | max 9 iterations | no progress x2 | budget 60m, $10.0, 4000000 tokens
```
