# Multimodal studio architecture

An all-in-one assistant does not need one neural network that performs every task. A practical private studio
routes each task to a specialized local or authorized remote engine while preserving one memory, interface,
project workspace, and audit trail.

## Local media pipeline

- Images and screenshots: record a read-only source, inspect metadata, run a local vision-language model, and
  store the resulting description as searchable knowledge. OCR is a lightweight fallback for visible text.
- Audio and OBS recordings: decode audio locally, transcribe it with timestamps, and index the transcript.
- Video understanding: transcribe the audio, sample representative frames, run those frames through the local
  vision model, and store both evidence streams together.
- Video generation: route a storyboard to a local open video model when hardware permits, or to an explicitly
  authorized provider. Generation and understanding are separate capabilities.

On an 8 GB RTX 4070, ForgeMind switches between the coding and vision models rather than keeping both in VRAM.
The speech model defaults to CPU int8 so it can transcribe while avoiding GPU-memory conflicts. Original media
is not rewritten. Derived transcripts, frame samples, analyses, and indexes live in ForgeMind's application
data and remain inspectable.

Media analysis can be wrong. Preserve links to the original file and timestamps so claims can be checked.
