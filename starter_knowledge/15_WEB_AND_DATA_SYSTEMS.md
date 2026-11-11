# Web, API, database, and application-development foundations

## HTTP and APIs

Treat HTTP status, timeout, content type, redirects, authentication, and rate limits as data. Validate URLs and cap response size. Parse structured JSON according to a schema. Retry only transient failures and use bounded exponential backoff. Never retry authentication or validation failures indefinitely.

For web research, separate discovery from evidence retrieval. Search results identify candidate pages; direct page extraction supplies evidence. Record URL, title, retrieval time, and whether the page was complete, blocked, login-required, or unavailable.

## Databases

Use parameterized queries, explicit transactions, foreign keys, and migrations. Index fields used for frequent filtering or joins, but measure query plans before adding indexes. Backups are not proven until restoration is tested. Keep secrets out of database URLs committed to code.

## Backend services

Validate requests at the boundary and return consistent error structures. Separate authentication, authorization, business rules, and persistence. Make background work durable when it must survive process restarts. Add health checks that test meaningful dependencies without exposing private state.

## Frontend interfaces

Design around user tasks and observable states: idle, loading, partial, success, empty, cancelled, and error. Keep the interface responsive, preserve drafts, and make destructive actions explicit. Accessibility includes keyboard navigation, readable contrast, labels, focus behavior, and usable error text.

## Deployment

Local GPU inference is best kept on the owner’s machine. A hosted frontend can call a local or hosted backend, but serverless deployment does not automatically provide a consumer GPU or persistent local files. Choose deployment only after identifying runtime, storage, network, authentication, and availability requirements.

