# Automatic improvement and what actually grows

ForgeMind 1.3 has a Growth Lab, persistent task queue, and idle-time planner. A new Growth Lab database enables background improvement and seeds small goals for readable clip captions, accurate sampled frame timestamps, and useful export diagnostics. After 60 seconds of user inactivity, a loaded local model works on one queued goal through SelfEvolver's research, source selection, candidate edits, actual tests, repairs, review, installation, and rollback-preserving workflow. It restarts when idle to load installed code, then continues the queue.

When the queue empties, the planner uses owner priorities, source files, and recorded outcomes to propose small new upgrades. It deduplicates goals and retains unsuccessful tasks with their evidence. Recurring blockers may require a missing dependency, credentials, better source context, a smaller goal, or a stronger model. Do not tell the owner that more permission can fix every failure.

Growth Lab owns application-development goals. User-selected projects such as Pacifica CRM remain under Project workspace's separate workflow; a background application goal does not authorize publishing content, spending money, or changing connected personal repositories. Stop evolution pauses the queue and stops an active campaign after its current model operation.

Engineering evidence includes test outcomes, attempts, elapsed time, changed files, and audit reports. These must come from executed jobs. A model saying "I improved" is not evidence. Passing a test suite gives evidence for covered behavior, not unlimited correctness. A local model's self-review score is not an independent benchmark or IQ measure.

Memory growth stores retrievable information. Application growth changes tools and workflows. Neural-weight training requires a separate compatible checkpoint, trainer, data, computing resources, and held-out evaluation; Growth Lab does not silently train or replace neural weights. ForgeMind runs its own local model and is not an instance or copy of the assistant helping build it.
