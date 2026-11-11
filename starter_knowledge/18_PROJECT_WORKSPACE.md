# Controlled project workspace

ForgeMind treats an owner-selected software repository differently from ordinary indexed knowledge.

## Project workflow

1. Map and index the original project as read-only knowledge.
2. Create a separate candidate copy under ForgeMind's application data.
3. Exclude dependency caches, build outputs, version-control metadata, and common secret files.
4. Make or inspect proposed changes only in the candidate.
5. Display the exact unified difference from the original.
6. Run detected compilation and test commands inside the candidate.
7. Refuse application if checks fail or the original project changed after the candidate was created.
8. Require explicit owner approval to apply verified changes.
9. Create a rollback backup before touching the original.

Project knowledge, candidate construction, verification, application, and rollback are separate stages. A
model saying that code looks correct is not verification. Passing checks does not prove every behavior, but it
provides objective evidence and prevents obvious failures from reaching the original project.

The current Project Workspace is the execution foundation. Automatic model-authored project patches should be
added as a separate capability that writes only to the candidate and remains subject to the same diff, test,
approval, and rollback gates.
