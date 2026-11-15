---
name: larkspeak
description: Read text aloud on the user's local speakers and control it. Use when the user asks to read aloud, narrate, speak, say or voice something, to read the last reply or the last N messages aloud, or to pause, continue, resume, stop or check the status of speech.
---

# Larkspeak: local text-to-speech

Larkspeak speaks text on the user's own computer through the local text-to-speech MCP server. Audio is generated and played in memory; nothing is uploaded and no audio file is written.

The server is registered as `tts`. Its tools may appear as `start_speech` or with a prefix such as `mcp__tts__start_speech`. Use whichever form your tool list shows. If no speech tool is available, tell the user the MCP server is not connected and point them to `docs/PLUGIN_INSTALLATION.md`. Do not try to speak in any other way.

## Tools (the same actions as the Larkspeak buttons)

| User wants | Call | Notes |
|---|---|---|
| Read something aloud | `start_speech(text, voice?, speed?)` | Returns at once; speech continues in the background |
| Pause | `pause_speech` | |
| Continue | `resume_speech` | The user says "continue speech" |
| Stop | `stop_speech` | Discards the rest of the text |
| Ask what it is doing | `speech_status` | Playing, paused, stopped or idle |
| Choose a model and voice | `list_models` | Models, with their languages and voices |

## Rules for `start_speech`

1. Pass the text exactly as the user wants it spoken. Do not summarize, shorten, translate or add words. If the user says "read your last answer", pass that answer unchanged.
2. Pick a voice whose language matches the text. Call `list_models` when unsure, and pass `language` (for example `"de"`) to `start_speech` when the text is not in the default model's language. A voice in the wrong language sounds wrong or fails. Not every language has a voice; say so instead of guessing.
3. Only change `speed` when the user asks (1.0 is normal).
4. After starting, say in one short line how to control it. Do not repeat the text.
5. Never start speech the user did not ask for.

## Reading earlier messages

Servers that support MCP prompts offer a `speak-last-reply` prompt. It takes an optional description such as "the last message" or "last 5 messages". One message is one user message or one assistant message, and each is labelled "user" or "assistant" so the owner is clear. By default only the last message is read.

Without prompt support, collect the requested messages yourself, keep their order and labels, and call `start_speech` once with the unchanged text.

## Voice commands

When voice control is enabled on the server, the user can say "pause speech", "continue speech", "stop speech" or "status speech" out loud. These need no tool call from you.

## Buttons

The optional `larkspeak-buttons` plugin adds the same actions as small buttons under each reply: read aloud, pause, continue and stop. They are not part of this skill. If the user asks for them, tell them to install `larkspeak-buttons@larkspeak`.
