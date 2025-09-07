# Screenshare Extension (Screen → Frames → Reasoning)

This extension adds a **Screenshare MCP server** and a set of `/screenshare` commands for **Gemini-CLI**.  
Use it to **list displays**, **capture screenshots/bursts**, and run **stream mode** for continuous reasoning.

---

## Commands

- **/screenshare** — quick help and examples.
- **/screenshare:devices** — list available displays and geometry.
- **/screenshare:status** — show current source (monitor, region, scale).
- **/screenshare:capture** — single screenshot.  
  Options: `save_dir`, `format` (`jpg` | `png`), `prompt`, `outfile`
- **/screenshare:stream** — burst of frames → Gemini reasoning → pause → repeat.

*(Optional if you keep them:)*  
- **/screenshare:start** — initialize source (monitor/region/scale).  
- **/screenshare:stop** — release the source.

---

## Typical Flow

1. `/screenshare:devices`  
2. `/screenshare:capture prompt="Summarize this slide deck"`  
3. `/screenshare:stream duration_ms=10000 mode=reply`  

---

## Stream Mode (High-level)

- Captures a burst of frames using `screenshare_burst` (`n`, `period_ms`, **or** `duration_ms`).
- Keeps every other frame (stride) to reduce redundancy.
- Builds `@file` tokens and appends an instruction based on mode:
  - **reply**: interpret + reply as assistant (default).
  - **transcribe**: only transcribe the content (e.g., ASL signing).
  - **both**: show transcript first, then assistant reply.

---

## Requirements

Server (screen-based Screenshare MCP):

- `mcp` or `fastmcp`
- `mss` (fast, cross-platform screen capture)
- `pillow` (image encoding/resizing)

---

## Platforms

- **macOS**: requires **Screen Recording** permission for your terminal.  
  System Settings → Privacy & Security → **Screen Recording**
- **Linux**: works with X11 or Wayland; ensure your session supports screenshotting via `mss`.
- **Windows**: works with native APIs via `mss`.

---

## Examples

List displays:

/screenshare:devices


Single capture with reasoning:


/screenshare:capture prompt="What is highlighted on screen?"


Capture with alias file for reuse:


/screenshare:capture outfile=slide.jpg prompt="Summarize this slide"


5s stream at 200ms spacing, reply mode:


/screenshare:stream duration_ms=5000 period_ms=200 mode=reply


Transcription-only loop, 3 cycles, 10s pause:


/screenshare:stream cycles=3 pause_secs=10 mode=transcribe


---

## Troubleshooting

- **“Screen source closed”**
  - Run `/screenshare:capture` or `/screenshare:stream`; they auto-start if needed.
  - If it still fails, check OS permissions for screen recording.
- **Black images**
  - On macOS: ensure Terminal/iTerm/VS Code is checked under Screen Recording.
  - On Linux: some Wayland desktops restrict capture; try X11 session.
- **Permission denied**
  - Re-run app after granting screen recording permissions.

---

## Safety

- No shell execution inside the MCP server.  
- `/screenshare:capture` and `/screenshare:stream` auto-stop after ~60 minutes (safety cap).

---

## Notes

- `prompt` integration lets you run one-shot Gemini turns directly with screenshots.  
- If you prefer manual control, keep `/screenshare:start` and `/screenshare:stop`.  
- File tokens (`@file`) are passed automatically into Gemini prompts.
