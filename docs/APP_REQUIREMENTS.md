# App requirements

High-level requirements that must never be broken. Every change, new model and new feature has to satisfy all of them.

## 1. Commercial use

- The app may use only models (speech synthesis, speech recognition and any other) whose license allows commercial use.
- The license of every model, voice set and dependency must be checked before it is added, and recorded in the third-party notices.
- A model whose license forbids or restricts commercial use must not be added, not even as an optional extra.

## 2. In-memory audio only

- During text-to-speech the app must not save any audio file. No WAV, MP3 or temporary file, on disk or in a temp directory.
- All audio is generated, processed and played in memory.
- The same applies to microphone input used for voice control: it is processed in memory and never stored.

## 3. CPU fallback

- Every model must work on a CPU.
- When a GPU is configured but not available, the app must fall back to the CPU automatically instead of failing.
- A model that cannot run on a CPU must not be added.
