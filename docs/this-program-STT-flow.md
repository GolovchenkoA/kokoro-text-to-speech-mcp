# This program's voice-command flow

```
microphone → energy VAD gate → Vosk (4-phrase grammar) → exact match → fixed action
```

1. **Microphone**: 16 kHz mono, 100 ms blocks (on by default; `TTS_VOICE_CONTROL_ENABLED=0` turns it off).
2. **Energy VAD gate**: RMS above a threshold opens the gate. A 300 ms pre-roll and a 500 ms hangover keep the phrase intact.
3. **Vosk**: runs only while the gate is open, restricted to `pause speech`, `continue speech`, `stop speech`, `status speech` and `[unk]`.
4. **Exact match**: the command runs only if the whole utterance equals one phrase.
5. **Action**: pause, resume, stop or announce status of the current speech. Nothing else can be triggered.

## Differences from the typical flow

| Typical | This program | Why |
|---|---|---|
| Wake-word engine | none | Pretrained engines have a few fixed words; these four phrases would need custom-trained models |
| Free-form ASR | grammar-restricted Vosk | Works offline with no training and cannot recognize anything outside the four phrases |
| NLU | none | The phrases map directly to fixed actions |
| Neural VAD | energy threshold | No extra dependency and almost no cost while idle |
| Wake word, then command | the phrase is the command | One step, no extra trigger word to say |
