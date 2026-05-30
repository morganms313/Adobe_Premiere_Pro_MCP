# DFXP/XML caption ingestion for `create_caption_track`

**Date:** 2026-05-30
**Status:** Design — awaiting user review
**Scope:** This phase = **ingestion parity only**. Make the MCP place a `.dfxp`/`.xml` (TTML-family) caption file onto a caption track, the same way it already does for `.srt`. **Positioning (FN-top / DX-bottom) is explicitly OUT OF SCOPE** for this phase and will be tackled separately.

## Problem

`create_caption_track` (src/tools/index.ts ~5043) works for `.srt` but rejects `.dfxp`/`.xml` items with `"Error: Illegal Parameter type"`.

Established facts (this session, Premiere Pro 2025, live test project `Claude_Testing_MS_v1.prproj`):
- `.dfxp` and `.xml` **import fine** via `import_media` (`.itt`/`.ttml` extensions are rejected at import with "File format not supported" — out of scope; we standardize on `.dfxp`/`.xml`).
- Imported DFXP item metadata: `MediaType: Transcript`, `Captions: Subtitle`, with valid CaptionsStart/End. So Premiere ingests it as a real caption source.
- Dragging that item to the timeline **does** produce a rendering caption track (proves the data path exists in Premiere) — it renders top-justified, which tells us *some* position data is retained. Positioning correctness is a later phase.
- At the MCP layer, both `.srt` and `.dfxp` items report `type: "footage"` — so the discriminator that makes `createCaptionTrack` reject DFXP lives deeper in the ExtendScript item object, not in the surface type. **Identifying that discriminator is the core unknown.**
- The current `createCaptionTrack` already falls back to a 2-arg `sequence.createCaptionTrack(projectItem, atTime)` call; that 2-arg call itself is what throws on a DFXP item. So the fix is not just the format-enum arg (that was the earlier SRT fix) — it's something about how the Transcript item is passed/attached.

## Goal / success criteria

1. One `create_caption_track` call places a `.dfxp` **or** `.xml` item onto a caption track that **renders** in the Program monitor.
2. `.srt` ingestion continues to work unchanged (no regression).
3. The tool response reports which internal strategy succeeded (`native` vs `transcode-srt`) so the caller knows whether positioning data was preserved.

Non-goals this phase: correct top/bottom positioning; `.itt`/`.ttml` extension import; caption read-back (Adobe API can't).

## Approach: Staged A→B with automatic, transparent fallback

`create_caption_track` detects caption file type and tries two strategies in order; a single call always yields a track if either path works.

- **Strategy A — native (preferred):** make ExtendScript's caption-attach accept the Transcript-type item directly. Preserves whatever positioning Premiere retains. Exact call TBD by the spike (below).
- **Strategy B — transcode fallback (guaranteed):** parse the DFXP/XML cues (begin/end/text), write a temp `.srt` into the same lucid folder as the source, and run the existing proven SRT ingest path. Loses positioning, but guarantees the feature ships.

**Fallback is automatic but TRANSPARENT:** the call falls back A→B on its own (caller always gets a track in one call), and the response includes `strategy: "native" | "transcode-srt"` (+ a human note). Per user (2026-05-30): option A = automatic fallback, surfaced in the response — not silent, not refuse-and-stop.

## The spike (de-risks Strategy A without N rebuilds)

There is no generic raw-ExtendScript tool, so probing the live caption API would otherwise cost an edit→build→reconnect per attempt.

**Add ONE temporary `debug_eval_script` tool** that passes a raw ExtendScript string straight to the existing `bridge.executeScript()` (same execution path every tool already uses). Build/reconnect **once**, then iterate freely against the live Premiere to:
1. Enumerate the DFXP Transcript item's real ExtendScript properties/methods and diff against the SRT item (find the discriminator).
2. Try caption-attach variants until one accepts the Transcript item (e.g. alternate arg forms, `importFiles`-into-sequence paths, or any caption-specific method the item exposes).
3. Capture the exact working call.

Then bake the working call into `createCaptionTrack` as Strategy A and **delete `debug_eval_script`** before shipping. It never lands in the committed feature.

If the spike proves **no** ExtendScript path accepts a Transcript item → Strategy A is impossible; ship Strategy B alone (still meets the success criteria, minus positioning). Either way the phase delivers a working DFXP/XML ingest.

## Build / run / reconnect loop

- **The live MCP server runs from the MAIN repo, not a worktree:**
  `claude_desktop_config.json` → `premiere-pro` → `node /Users/morgan/Documents/Projects/Adobe_Premiere_Pro_MCP/dist/index.js` (env `PREMIERE_TEMP_DIR=/tmp/premiere-mcp-bridge`). Branch `integration/all-fixes`.
- **All edits + `npm run build` happen in that main repo checkout.** (This spec lives there too.)
- `npm run build` (tsc → `dist/`) updates the bundle, but the running server only picks it up when **Claude Code reconnects the MCP** — a manual step the user performs.
- **Reconnect cadence:** user is at the machine and happy to restart as needed (~2 reconnects expected: one after adding `debug_eval_script`, one after baking in the fix + removing it). Optimize for debugging speed, not minimizing restarts.

## Testing & verification

Live, in `Claude_Testing_MS_v1.prproj` (sequence `40c98f59-79ea-4f87-b895-a2115e84708b`):
1. Import the `.dfxp` test file, call `create_caption_track` → expect success + `strategy` reported.
2. Repeat for `.xml`.
3. Re-run `.srt` ingest → confirm no regression.
4. Caption read-back is impossible via API, so **rendering is confirmed visually by the user scrubbing** the timeline (quick check). Positioning is NOT judged this phase.

Test files currently parked in:
`…/05_Translation/01_SRTs/US_English_en_US/_zOLD/claude_caption_tests_2026-05-30/` (`*_ppro.dfxp`, `*_ppro.xml`, `*_smpte.*`).

## Risks

- **Strategy A may be impossible** (ExtendScript caption DOM is thin). Mitigated by guaranteed Strategy B.
- **`debug_eval_script` is a raw-eval tool** — temporary, removed before commit; never shipped. (Also note OSS policy: nothing requiring a human-present modal gets PR'd upstream — this tool is local-only and deleted, so N/A.)
- **No automated regression harness** for captions; verification is manual/visual per Adobe's read-back limitation.

## Out of scope (future phases)

- Correct FN-top / DX-bottom positioning on import (investigate whether Premiere honors TTML `region`/`tts:origin`, or whether Track Styles must be applied — Track Styles are not scriptable per this session's UXP-source check).
- `.itt`/`.ttml` extension import.
- Track Style automation (computer-use) — user's explicit last resort, only when away from machine.
