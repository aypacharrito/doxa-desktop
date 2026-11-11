# Connections and persistent evolution campaigns

ForgeMind learns through conversation memory, indexed knowledge, current web research, and verified application updates. These mechanisms complement one another but are not neural-weight training.

## Read-only knowledge connections

- A connected file or folder is read and indexed; the original is not rewritten.
- A GitHub connection downloads a repository snapshot for local indexing and never pushes commits.
- Google Drive for desktop exposes selected Drive folders as local folders that ForgeMind can index.
- Each external application needs its own API or OAuth connector. Access to one application does not imply access to another.
- Public web research can be broad, but authenticated pages, paywalls, CAPTCHAs, and blocked sites need a dedicated authorized connection.
- Explicitly supplied public URLs are opened directly. Large pasted knowledge imports automatically open and index up to 25 discovered links when their pages are retrievable.
- When web evidence appears in the model context, it is real tool output; ForgeMind must not claim that it lacks internet access.

## Persistent self-development

When the user directly asks ForgeMind to improve itself, it starts a campaign. A campaign researches the goal, builds an isolated candidate, compiles it, runs baseline and generated tests, reviews evidence, and installs only a verified candidate. If a candidate fails, it receives one repair pass. If that still fails, the campaign tries a materially different implementation. Campaign state and audit reports persist on disk, and an interrupted campaign resumes after restart.

A blocker is not an installed failure. It means repeated candidates could not verify because the goal needs to be smaller or because a required external capability is unavailable. The useful next step is to inspect the last audit report and turn the blocker into a narrower measurable goal.
