# Coding standards

## Design

- Keep core logic separate from user interfaces, networks, and storage adapters.
- Make dependencies explicit and replaceable.
- Validate data at boundaries.
- Choose boring, maintainable solutions unless complexity earns its cost.
- Avoid global mutable state when a scoped object will work.

## Implementation

- Use descriptive names and short functions with one clear responsibility.
- Handle expected failures with useful messages.
- Do not catch broad exceptions unless the boundary can recover or add context.
- Use parameterized database queries.
- Make file writes atomic when practical: write a temporary file, then replace.

## Testing

- Test public behavior rather than private implementation details.
- Cover the happy path, empty input, malformed input, and one realistic failure.
- Keep tests deterministic and independent of public networks unless explicitly integration tests.
- A bug fix should include a test that fails before the fix and passes afterward.

## Code review questions

1. Is the result correct for ordinary and edge cases?
2. Could this lose, overwrite, or expose data?
3. Is the error behavior understandable?
4. Is the change smaller than it needs to be?
5. Can another developer verify it without guessing?
