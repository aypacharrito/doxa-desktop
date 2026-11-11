# Testing, evaluation, and reliable self-improvement

Compilation catches syntax errors; it does not establish that a feature works. Use layered verification:

1. **Structural checks** — files parse, imports resolve, schemas validate.
2. **Unit tests** — pure functions and boundary validation.
3. **Integration tests** — database, filesystem, subprocess, and connector adapters.
4. **Workflow tests** — user request through tool execution to visible result.
5. **Regression suite** — existing behavior remains intact.
6. **Evaluation cases** — model-assisted behavior is scored against fixed examples.

Network-dependent behavior should have deterministic mocked tests plus a separately labeled live smoke test. Tests must never require an uncontrolled public service merely to verify ordinary local behavior.

## Evaluation records

Store the goal, application version, model, settings, retrieved evidence, proposed actions, changed files, test output, review findings, duration, and final status. Compare before-and-after results using the same evaluation set.

Good evaluation dimensions include correctness, task completion, truthful tool reporting, source relevance, code quality, regression risk, latency, and recoverability. More tokens or more stored documents are not themselves evidence of improvement.

## Repair strategy

When verification fails:

- preserve the complete error output;
- extract a normalized blocker signature;
- identify the earliest causal failure;
- give the repair step the changed files and relevant unchanged dependencies;
- make one focused repair;
- rerun the complete relevant suite;
- avoid repeating a proposal whose blocker signature already recurred.

Never weaken or delete an independent baseline test merely to make a candidate pass.

