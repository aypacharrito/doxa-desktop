# Real computer tasks and owner override

ForgeMind version 1.4 includes Computer tasks, a local screen/action/check controller.
It is different from Chrome Remote Desktop, which lets the owner use the laptop remotely.

Open Computer tasks, download vision once, and describe one concrete outcome in the task box.
Start task explicitly. Do not type commands to yourself in chat and claim they were executed.
Computer: followed by a task in chat opens the controller; it does not secretly start clicking.

The controller temporarily replaces the text model with the vision model on the GPU.
It operates the primary monitor, observes screenshots, sends one action, and checks the next screen.
Controls: move the physical mouse or type to pause; Ctrl+Alt+F11 pause/resume;
Ctrl+Alt+F12 stop; Pause/Resume and STOP buttons remain visible.
After takeover it re-observes before acting. Login/permission/resource failures may require the owner.

Outcomes and local audit paths are indexed as knowledge. The latest screen image and action log live
under the owner's local ForgeMind computer directory. Actual outcomes, not generated descriptions,
are evidence of completion. The local-model final visual verifier can still make mistakes.

Computer tasks do not change neural model weights. Background Growth Lab continues separate
tested application upgrades when idle. Stop/pause controls remain necessary for owner override.
Giving more task records improves retrievable context, not unlimited general intelligence.
