# Agent execution: turn requests into verified action

An assistant talks; an agent changes observable state through tools. Use this state machine for work that requires action:

1. **Interpret** — identify the requested outcome, target, constraints, and proof of completion.
2. **Inspect** — retrieve relevant memory, files, repository structure, current application state, and tool availability.
3. **Plan** — choose the smallest sequence of reversible actions. State assumptions that affect the result.
4. **Act** — invoke a typed tool with explicit inputs. Never pretend that prose or sample code executed.
5. **Observe** — capture the tool's actual output, changed files, exit status, and errors.
6. **Repair** — diagnose the first causal error, adjust the plan, and retry with a materially different correction.
7. **Verify** — run focused tests plus existing regression tests. Check the requested user-visible behavior.
8. **Commit** — install only a verified candidate and preserve rollback information.
9. **Report** — distinguish completed work, evidence, limitations, and the next useful action.

## Action contract

Every action should have:

- a stable action name;
- validated structured inputs;
- a declared writable scope;
- a timeout or cancellation path;
- structured output containing status, evidence, and errors;
- idempotency behavior when retrying could duplicate work;
- an audit record suitable for debugging.

The application, not the language model, is authoritative about whether an action happened. A model may propose `run_tests`, but only the returned process result proves tests ran. A model may propose `write_file`, but only a verified file digest proves the write occurred.

## Planning discipline

For a broad request, create a backlog of measurable objectives. Execute one objective per cycle. Avoid combining UI redesign, dependency changes, database migration, and new integrations in one patch unless a single testable slice genuinely requires them.

Prefer this task record:

```text
Objective: observable result
Inputs: files, user instruction, retrieved evidence
Actions: ordered tool calls
Verification: commands and expected behavior
Status: pending | active | verified | installed | blocked | rejected
Evidence: paths, test output, sources, hashes
```

## Stop conditions

Retry when new evidence suggests a different implementation can work. Pause when the same normalized blocker recurs, a credential is missing, the target is unavailable, or the goal cannot be measured. Endless identical retries are not learning.

