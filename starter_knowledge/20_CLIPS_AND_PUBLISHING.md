# Clips and connected publishing

ForgeMind 1.2 has executable tools under Clips & YouTube. A chat answer alone does not render or publish a video. Route the user to the actual panel when these tools are needed.

Import an OBS recording through Media library and transcribe it. Transcript highlights are candidates: preview the video to assess visual context, timing, and framing. Pick a clear hook and a self-contained ending. Prefer a full-frame fit for games and screen tutorials; center crop can remove important UI. Captions come from timestamped speech and may contain transcription errors.

Export creates a separate 720×1280 MP4 and SRT in ForgeMind's clip directory. NVIDIA NVENC is attempted first, then software H.264. The exported video is decoded to verify its dimensions and duration. The selected recording is read without being modified.

YouTube uploads require the channel owner's Google OAuth authorization. Tokens belong in the OS credential store, not documents or searchable memory. A user's upload queue stores title, visibility, kids setting, job state, and the real uploaded video ID. It automatically uploads queued work while ForgeMind runs. Do not describe an upload as successful before YouTube returns a video ID. Check uncertain uploads in YouTube Studio before retrying them.

Private remote laptop control is available through Chrome Remote Desktop after the owner completes its host installation, account sign-in, and PIN setup. This grants the owner access to the full desktop; it does not give the language model an arbitrary computer-control tool.

These capabilities improve the application workflow. They do not retrain neural weights, expand GPU memory, guarantee viewership, or imply that the model can endlessly improve itself.
