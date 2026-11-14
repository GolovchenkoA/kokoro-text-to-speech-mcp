# Typical voice-command (STT) flow

```
microphone → VAD → wake-word engine → speech-to-text (ASR) → intent (NLU) → action
```

1. **Microphone**: continuous audio stream, 16 kHz mono.
2. **VAD (voice activity detection)**: a very cheap check whether anyone is speaking. If not, nothing heavier runs.
3. **Wake-word engine**: a tiny neural network (CNN/CRNN/DS-CNN, often under 1 MB) on 20–40 ms MFCC or log-mel frames. It outputs a keyword probability and fires a wake event when it stays above a threshold for a few frames. It runs on-device, all the time.
4. **ASR (speech-to-text)**: after the wake event, a full recognizer transcribes the free-form command.
5. **Intent (NLU)**: the transcript is mapped to an intent and parameters.
6. **Action**: the intent is executed.
