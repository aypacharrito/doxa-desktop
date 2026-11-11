# Practical software architecture reference

Organize capabilities around stable boundaries:

- **Domain/core** — task records, plans, tool requests, evidence, and verification results.
- **Application services** — orchestration and workflows.
- **Adapters** — filesystem, database, network, model runtime, speech, and external APIs.
- **Interface** — desktop UI, CLI, or web endpoints.

Core logic should not import UI widgets or provider-specific SDKs. Adapters should implement small interfaces so they can be replaced in tests.

## Durable work

Long-running tasks need persistent state. Save a task before execution, record each transition atomically, and make restart behavior explicit. A durable job should be resumable or safely restartable. Use idempotency keys for operations that could duplicate side effects.

## Concurrency

Keep expensive inference, indexing, network requests, and subprocesses off the UI thread. Send progress through a thread-safe queue. Protect shared model and database access. Cancellation should be cooperative and checked between bounded operations; a single model call also needs a timeout or interrupt mechanism.

## Data design

Store source, timestamp, confidence, and correction history with learned facts. Keep conversation messages, durable memory, indexed documents, tool observations, and evaluation records distinct. Database migrations should be versioned and tested against existing data.

## Dependency choices

Prefer the standard library or an already installed dependency when adequate. A new dependency requires a declared version range, installer integration, import test, license awareness, and a clear reason. Optional capabilities should fail gracefully when their extra dependency is absent.

