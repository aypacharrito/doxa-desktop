# Tools, applications, and connectors

A language model does not gain application access from a prompt. Each capability needs a tool or connector implemented by the host application.

## Tool registry pattern

A tool registry maps a stable name to a schema and an executor. The model receives only the tools relevant to the current task. Validate every input before execution and return structured observations.

Useful local tools include:

- list and search files inside an authorized workspace;
- read selected documents and code;
- create artifacts in an owned output folder;
- apply candidate patches and show differences;
- run an allowlisted project command with a timeout;
- run tests and parse failures;
- inspect repository status without discarding user changes;
- open a public URL and extract readable evidence.

External services require independent connections. GitHub, Google Drive, email, calendars, databases, and deployment providers each use their own API, OAuth grant, or local synchronized folder. Never infer one service's authorization from another.

## Connector lifecycle

1. Declare the service and minimum scopes.
2. Complete authorization through the provider.
3. Store tokens using the operating system's credential facilities rather than source code.
4. Refresh or revoke credentials cleanly.
5. Expose narrowly typed operations such as `github_read_file` or `drive_export_document`.
6. Log which operation ran without logging secrets.
7. Surface login-required, rate-limited, forbidden, and unavailable states distinctly.

## Tool-result truthfulness

Tool results are authoritative. If a page was retrieved, say so and cite its URL. If a command failed, do not claim success because the intended code looked correct. If a tool was not invoked, use future tense: “I can run…” rather than “I ran…”.

