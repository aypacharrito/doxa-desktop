# How ForgeMind should grow

ForgeMind improves through four inspectable layers:

1. **Pinned memory** — stable user facts and preferences. Add one by typing `Remember: ...`.
2. **Indexed knowledge** — repositories, notes, PDFs, standards, and project decisions.
3. **Tools** — narrowly authorized capabilities such as testing code, reading files, or querying a service.
4. **Model upgrades or fine-tuning** — deliberate replacement or training evaluated against a fixed test set.

## Correction format

When correcting ForgeMind, use:

```text
Remember: When working on [project], [specific fact or preference].
```

Good memories are specific, durable, and independently understandable. Avoid saving temporary status as permanent memory.

## Evaluation loop

Maintain a set of representative questions with expected qualities:

- Can it explain the architecture of an indexed project accurately?
- Can it locate the right file for a feature?
- Can it propose a change without inventing unavailable APIs?
- Does it distinguish local knowledge from web evidence?
- Does it acknowledge uncertainty?

Run the same evaluation after changing the model, system instructions, retrieval, or tools. Improvement means better measured results, not simply more stored text.
