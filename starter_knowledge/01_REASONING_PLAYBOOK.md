# Reasoning and problem-solving playbook

Use this loop for substantial work:

1. **Define success.** Restate the desired observable result and constraints.
2. **Inventory evidence.** Identify known facts, supplied files, assumptions, and missing information.
3. **Find the smallest useful slice.** Choose a change that can be completed and checked quickly.
4. **Consider failure modes.** Look for concurrency, malformed input, network failure, and recovery needs.
5. **Implement clearly.** Prefer readable names, explicit interfaces, and minimal dependencies.
6. **Verify behavior.** Use focused tests, realistic examples, and negative cases. Never equate compilation with correctness.
7. **Report honestly.** Separate completed work, verification evidence, remaining limitations, and the next best improvement.

For debugging:

- Reproduce before changing code.
- Read the complete error and identify the first causal failure, not the last symptom.
- Compare expected state with observed state.
- Change one variable at a time.
- Add a regression test when practical.
- Remove temporary instrumentation after the cause is confirmed.

For research:

- Prefer primary documentation and original data.
- Check dates when facts can change.
- Treat search snippets as leads, not complete evidence.
- State when a conclusion is an inference.
