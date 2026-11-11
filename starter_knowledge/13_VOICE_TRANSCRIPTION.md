# Voice-to-text capability blueprint

Voice input requires an audio capture layer and a speech-recognition model. It is separate from the conversational language model.

## Local pipeline

1. Start and stop microphone recording from an obvious UI control.
2. Capture mono PCM audio at a supported sample rate.
3. Display recording state and elapsed time.
4. Save a temporary WAV file inside ForgeMind's owned runtime directory.
5. Transcribe locally with an optional speech model such as Whisper-compatible inference.
6. Insert the transcript into the input box for owner review.
7. Delete temporary audio according to an explicit retention setting.
8. Report missing microphone permission, device failure, unsupported audio, and model-download state separately.

## Engineering boundaries

Do not record continuously by default. Never represent microphone access as active unless capture successfully started. Keep transcription off the UI thread. Add cancellation and a maximum recording duration. Model downloads should show size and progress.

## Verification

Use a short deterministic audio fixture with a known transcript, plus tests for silence, missing devices, cancellation, and transcription errors. A UI test should confirm that a successful transcript reaches the editable input field rather than being sent automatically.

Voice output is a different capability requiring text-to-speech synthesis, playback controls, and voice selection. Build and evaluate it separately.

