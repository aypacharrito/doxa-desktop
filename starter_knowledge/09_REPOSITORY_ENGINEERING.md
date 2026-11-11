# Repository intelligence and coding workflow

Before editing a repository, build a compact map:

- languages and build systems;
- entry points and runtime processes;
- modules, classes, functions, imports, and public interfaces;
- dependency manifests and lockfiles;
- configuration and environment-variable references;
- tests, fixtures, migrations, generated files, and documentation;
- relationships between the files likely affected by the request.

Use fast filename and text search before opening large files. Read repository-specific instruction files first. Preserve unrelated user changes and never assume a dirty working tree belongs to the agent.

## Change workflow

1. Reproduce the current behavior or failing test.
2. Identify the smallest ownership boundary for the change.
3. Read callers, implementations, tests, and data contracts together.
4. Make a minimal candidate change in an isolated workspace.
5. Add or update a regression test that expresses the requested behavior.
6. Run the narrow test first, then the relevant suite, then compilation or static checks.
7. Inspect the final difference for accidental changes and generated artifacts.
8. Report actual verification output and remaining uncertainty.

## Debugging code

Trace the first causal failure rather than reacting to every downstream error. Classify failures as syntax, import/dependency, type/contract, state/data, concurrency, network, permission, configuration, or environment. A repair should target the classified cause.

Do not solve a missing dependency by importing another package unless the dependency manifest, installer, and offline behavior are intentionally updated. Prefer existing dependencies or the standard library when capability is equivalent.

## Delivering files

Artifacts should be created in a designated output folder with clear names. A deliverable is not complete merely because source code exists: confirm that the file opens, its format is valid, and its contents match the request. Keep temporary files separate from final outputs.

