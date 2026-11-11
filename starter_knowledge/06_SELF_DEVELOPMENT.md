# Self-development method

ForgeMind can improve its own application through measurable evolution cycles.

Each campaign begins with one user-supplied goal. ForgeMind researches current information, selects relevant source files, proposes exact changes in an isolated candidate, compiles the candidate, runs baseline tests and any generated evaluation tests, reviews the code difference, and assigns a score. A verified candidate can be installed automatically. The previous live files are preserved for rollback. A campaign has no fixed attempt ceiling; it continues with different implementations until one verifies, the owner stops it, or the same concrete external/compiler/test obstacle repeats and needs new input.

Self-development can improve:

- Memory and retrieval behavior
- Research workflows
- User-interface features
- Coding and analysis tools
- Prompts and specialized knowledge
- Evaluation coverage
- Application structure, dependencies, installers, tools, and plugins

Within its owned application workspace, ForgeMind may create, edit, move, reorganize, and remove files. User-connected files and repositories are read-only. Baseline verifier tests, rollback records, the active memory database, and the model file remain independent so a candidate cannot declare itself successful by erasing its evaluation mechanism.

Self-development does not automatically retrain the base language model. The model remains a fixed GGUF file unless deliberately replaced or fine-tuned through a separate training process.

Good evolution goals are narrow and testable:

- Improve source citations by comparing claims from multiple pages.
- Add a conversation export function with unit tests.
- Add repository language statistics for JavaScript and TypeScript.
- Improve error reporting when an indexed PDF cannot be parsed.

Poor goals are unbounded or impossible to evaluate:

- Become infinitely intelligent.
- Make every answer perfect.
- Learn everything on the internet.

Growth should be judged by repeatable evidence: a working capability, passing regression tests, focused evaluations, and an inspectable difference from the previous version.
