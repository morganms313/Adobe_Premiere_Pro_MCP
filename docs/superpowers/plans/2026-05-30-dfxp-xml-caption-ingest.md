# DFXP/XML Native Caption Ingestion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `create_caption_track` accept a `.dfxp`/`.xml` (TTML-family, Premiere "Transcript"-type) project item and place it on a caption track natively — preserving whatever positioning Premiere retains — the way it already does for `.srt`.

**Architecture:** A throwaway `debug_eval_script` tool lets us probe the live Premiere caption API to discover which ExtendScript call accepts a Transcript-type item (the current 2-arg `sequence.createCaptionTrack(item, time)` throws `Illegal Parameter type` on DFXP). We bake the discovered call into `createCaptionTrack` as a native branch, then delete the debug tool before commit. Native-only: no transcode fallback (team always has `.srt` backups). If no native call exists, ship only an improved error message.

**Tech Stack:** TypeScript (tsc → `dist/`), ExtendScript (ES3) via file-bridge `bridge.executeScript()`, MCP SDK. Live host: Adobe Premiere Pro 2025.

**Spec:** `docs/superpowers/specs/2026-05-30-dfxp-xml-caption-ingest-design.md`

---

## CRITICAL ENVIRONMENT NOTES (read before any task)

- **Edit + build in the MAIN repo only:** `/Users/morgan/Documents/Projects/Adobe_Premiere_Pro_MCP` (branch `integration/all-fixes`). The live MCP server runs `node <mainrepo>/dist/index.js`. Editing a worktree does nothing to the live server.
- **Concurrency gate:** a second session edits this same MCP (track-muting). Before EVERY `npm run build`, run `git status --porcelain` in the main repo and confirm `src/tools/index.ts` has no foreign uncommitted edits. If it does, STOP and coordinate.
- **Reconnect is the user's job:** `npm run build` updates `dist/` but the running server only loads it when the user reconnects the MCP in Claude Code. Each task that says "RECONNECT GATE" means: stop, ask the user to reconnect, wait for confirmation before continuing.
- **Line numbers drift** (large file, shared). Anchor every edit by the grep pattern given, not by line number.
- **Caption read-back is impossible** via the Adobe API (`read_sequence_captions` always returns trackCount:0). The ONLY verification that a caption track rendered is the user scrubbing the Program monitor. Plan accordingly — "test" = live MCP call + user visual confirm.
- **Live test project:** `Claude_Testing_MS_v1.prproj`, sequence id `40c98f59-79ea-4f87-b895-a2115e84708b`.
- **Test caption files** (already on disk, lucid folder):
  `…/OGB_S1_0001_TeaserPV-CastAnnouncementPVpt2/01_FINISHING_FILES/05_Translation/01_SRTs/US_English_en_US/_zOLD/claude_caption_tests_2026-05-30/`
  → `TheOgresBride_S001_CastPV_Part2_ENUS_ppro.dfxp`, `…_ppro.xml` (and `…_smpte.*`).
  SRT regression file (lucid root): `…/US_English_en_US/OGB_S1_Teaser_Full_CastAnnouncementPVpt2_16x9_2398_DX_en-US.srt`.

---

## File Structure

- **Modify:** `src/tools/index.ts`
  - Tool-list schema array — add temporary `debug_eval_script` schema (Task 1), remove it (Task 7).
  - Dispatch `switch` — add/remove `case 'debug_eval_script'` (Tasks 1/7).
  - `private async debugEvalScript(...)` method — add/remove (Tasks 1/7).
  - `private async createCaptionTrack(...)` method — add native DFXP/XML branch (Task 5).
  - `create_caption_track` schema `description` — mention DFXP/XML support (Task 5).
- **No new files.** All changes live in the one tools file, following the existing single-file pattern.
- **Reference (do not edit):** `src/bridge/index.ts` — `executeScript()` + `EXTENDSCRIPT_HELPERS` (defines `__findSequence`, `__findProjectItem`).

---

## Task 1: Add temporary `debug_eval_script` tool

**Files:**
- Modify: `src/tools/index.ts` (3 sites: schema array, dispatch case, method)

- [ ] **Step 1: Add the schema entry.** Find the schema block anchored by `name: 'create_caption_track',`. Immediately BEFORE the `{` that opens that object, insert:

```typescript
      {
        name: 'debug_eval_script',
        description: 'TEMPORARY DEBUG TOOL — runs raw ExtendScript in the Premiere host and returns its result. Remove before shipping.',
        inputSchema: z.object({
          script: z.string().describe('Raw ExtendScript body. Use JSON.stringify(...) as the return value.')
        })
      },
```

- [ ] **Step 2: Add the dispatch case.** Find `case 'create_caption_track':`. Immediately BEFORE it, insert:

```typescript
        case 'debug_eval_script':
          return await this.debugEvalScript(args.script);
```

- [ ] **Step 3: Add the method.** Find `private async createCaptionTrack(`. Immediately BEFORE that line, insert:

```typescript
  private async debugEvalScript(script: string): Promise<any> {
    return await this.bridge.executeScript(script);
  }

```

- [ ] **Step 4: Concurrency gate + build.**

Run:
```bash
cd /Users/morgan/Documents/Projects/Adobe_Premiere_Pro_MCP
git status --porcelain src/tools/index.ts   # must show only OUR M line
npm run build
```
Expected: tsc exits 0, no errors. `dist/tools/index.js` mtime updates.

- [ ] **Step 5: RECONNECT GATE.** Ask the user to reconnect the premiere-pro MCP, then confirm `debug_eval_script` is callable (it will appear in the deferred-tool list). Do NOT commit this tool — it is throwaway.

---

## Task 2: Probe — confirm the discriminator (SRT vs DFXP item)

**Goal:** Learn what makes the DFXP item different from the SRT item at the ExtendScript level, so we know what kind of object the native call must accept.

- [ ] **Step 1: Ensure both items exist in the project.** Via MCP `import_media`, import the SRT (`…_DX_en-US.srt`) and the DFXP (`…_ppro.dfxp`) test files. Record their returned ids.

- [ ] **Step 2: Dump both items' ExtendScript shape.** Call `debug_eval_script` with (substitute the two real nodeIds):

```javascript
var out = {};
function dump(id, label){
  var it = __findProjectItem(id);
  if(!it){ out[label]="NOT FOUND"; return; }
  var info = { name: it.name, type: it.type, nodeId: it.nodeId };
  try { info.isSequence = it.isSequence(); } catch(e){}
  // enumerate own + inherited keys/methods
  var keys = [];
  for (var k in it) { keys.push(k); }
  info.keys = keys.join(",");
  // MediaType via metadata column if present
  try { info.mediaType = it.getProjectMetadata ? "has-getProjectMetadata" : "no"; } catch(e){}
  out[label] = info;
}
dump("SRT_NODEID_HERE","srt");
dump("DFXP_NODEID_HERE","dfxp");
JSON.stringify(out);
```

Expected: a diff in `type` and/or available methods between the two. Record exactly what differs (this is the crux). Likely the DFXP item is a Transcript-media item whose `type`/interpretation the 2-arg `createCaptionTrack` rejects.

- [ ] **Step 3: Record findings** inline in this plan under Task 2 (append a `FINDINGS:` block). No commit (debug only).

---

## Task 3: Probe — find a caption-attach call that accepts the DFXP item

**Goal:** Discover the exact ExtendScript call that places the Transcript-type DFXP item onto a caption track.

- [ ] **Step 1: Try candidate calls, one per `debug_eval_script` invocation.** For each candidate, wrap in try/catch and return the error string so a failure does not wedge. Candidates, in order:

Candidate A — 2-arg (baseline, expected to FAIL, confirms repro):
```javascript
var seq=__findSequence("40c98f59-79ea-4f87-b895-a2115e84708b");
var it=__findProjectItem("DFXP_NODEID_HERE");
try { var r=seq.createCaptionTrack(it,0); JSON.stringify({ok:true,r:String(r)}); }
catch(e){ JSON.stringify({ok:false,err:e.toString()}); }
```

Candidate B — explicit subtitle format enum (3-arg):
```javascript
var seq=__findSequence("40c98f59-79ea-4f87-b895-a2115e84708b");
var it=__findProjectItem("DFXP_NODEID_HERE");
var fmt = (typeof Sequence!=='undefined' && Sequence.CAPTION_FORMAT_SUBTITLE!==undefined) ? Sequence.CAPTION_FORMAT_SUBTITLE : 0;
try { var r=seq.createCaptionTrack(it,0,fmt); JSON.stringify({ok:true,r:String(r),fmt:String(fmt)}); }
catch(e){ JSON.stringify({ok:false,err:e.toString()}); }
```

Candidate C — `importFiles` directly onto the active sequence's caption track (newer transcript path):
```javascript
var ok = app.project.importFiles(
  ["/Volumes/marketing/Marketing Globalization/The_Ogres_Bride/Season_1/OGB_S1_0001_TeaserPV-CastAnnouncementPVpt2/01_FINISHING_FILES/05_Translation/01_SRTs/US_English_en_US/_zOLD/claude_caption_tests_2026-05-30/TheOgresBride_S001_CastPV_Part2_ENUS_ppro.dfxp"],
  true, app.project.getInsertionBin(), false);
JSON.stringify({importedReturn:String(ok)});
```

Candidate D — enumerate caption-related methods actually present on the sequence object:
```javascript
var seq=__findSequence("40c98f59-79ea-4f87-b895-a2115e84708b");
var ms=[]; for (var k in seq){ if(/caption|transcript|subtitle/i.test(k)) ms.push(k); }
JSON.stringify({captionMethods:ms});
```

- [ ] **Step 2: After each candidate, the user scrubs** the Program monitor / Captions panel to confirm whether a rendering caption track appeared (read-back is impossible via API). Record per-candidate: error string (if any) + user's visual result.

- [ ] **Step 3: Identify the winning call.** The winner = the candidate that produces a rendering caption track from the DFXP item without error. Record its EXACT ExtendScript as `WINNING_CALL` in a `FINDINGS:` block appended to this task.

- [ ] **Step 4: Decision branch.**
  - If a winner exists → proceed to Task 5 (implement native branch).
  - If NONE works → native ingest is impossible. SKIP Task 5's native code; do Task 4 instead (improved error), then continue.

---

## Task 4: (Branch — only if Task 3 found NO winner) Improved error for DFXP/XML

**Files:** Modify `src/tools/index.ts` — `createCaptionTrack` method.

- [ ] **Step 1: Add an early, clear error.** In `createCaptionTrack`, after `var projectItem = __findProjectItem(...)` resolves, add a name-extension check that returns a helpful message for `.dfxp`/`.xml` instead of the raw `Illegal Parameter type`. Insert into the script string, right after the project-item-not-found guard:

```javascript
        var __nm = (projectItem.name||"").toLowerCase();
        if (/\.(dfxp|xml|ttml|itt)$/.test(__nm)) {
          return JSON.stringify({ success:false,
            error: "This Premiere/ExtendScript build cannot attach a "+__nm.split('.').pop()+" (Transcript-type) item to a caption track. Import the .srt backup of this subtitle instead — positioning is not preserved by SRT, apply a Track Style after import.",
            unsupportedFormat: __nm.split('.').pop() });
        }
```

- [ ] **Step 2: Build (with concurrency gate) + RECONNECT GATE** (as Task 1 Step 4–5).
- [ ] **Step 3: Verify** via MCP `create_caption_track` on the DFXP item → expect the new helpful error, not `Illegal Parameter type`. Then jump to Task 6 (cleanup) — there is no native path to test.

---

## Task 5: (Branch — only if Task 3 found a winner) Implement native DFXP/XML branch

**Files:** Modify `src/tools/index.ts` — `createCaptionTrack` method + its schema `description`.

- [ ] **Step 1: Insert the native branch.** In `createCaptionTrack`'s script string, after the project-item guard and before the existing format-resolution block, add a format-detection branch that runs `WINNING_CALL` for DFXP/XML and falls through to the existing logic for everything else. Template (replace `__WINNING_CALL__` with the EXACT ExtendScript captured in Task 3, using the JS vars `sequence`, `projectItem`, `startAtTime`):

```javascript
        var __nm = (projectItem.name||"").toLowerCase();
        var __isTTML = /\.(dfxp|xml|ttml|itt)$/.test(__nm);
        if (__isTTML) {
          try {
            var __r = __WINNING_CALL__;   // e.g. sequence.createCaptionTrack(projectItem, startAtTime, Sequence.CAPTION_FORMAT_SUBTITLE)
            return JSON.stringify({ success:true, message:"Caption track created (native TTML-family)", sourceFormat:__nm.split('.').pop(), apiResult:String(__r) });
          } catch (eTT) {
            return JSON.stringify({ success:false, error:"Native "+__nm.split('.').pop()+" attach failed: "+eTT.toString(), unsupportedFormat:__nm.split('.').pop() });
          }
        }
```

- [ ] **Step 2: Update the tool description.** Find the `create_caption_track` schema `description:` and replace its text with:

```typescript
        description: 'Creates a caption track on a sequence from an imported caption/subtitle item. Accepts .srt (subtitle) and natively-attachable TTML-family items (.dfxp, .xml). Import the file via import_media first, then pass its projectItemId. Positioning from TTML regions is preserved as far as Premiere honors it; .srt carries no positioning.',
```

- [ ] **Step 3: Concurrency gate + build.**
```bash
cd /Users/morgan/Documents/Projects/Adobe_Premiere_Pro_MCP
git status --porcelain src/tools/index.ts
npm run build
```
Expected: tsc exits 0.

- [ ] **Step 4: RECONNECT GATE.** Ask user to reconnect the MCP; wait for confirmation.

---

## Task 6: Live verification (native branch)

**Goal:** Confirm DFXP and XML each produce a rendering caption track via one MCP call, and SRT still works.

- [ ] **Step 1: DFXP.** MCP `import_media` the `…_ppro.dfxp`, then `create_caption_track(sequenceId, <dfxpId>)`. Expected response: `success:true, sourceFormat:"dfxp"`.
- [ ] **Step 2: User scrub-confirms** a caption track renders for the DFXP (read-back impossible via API). Record result.
- [ ] **Step 3: XML.** Repeat Step 1–2 with `…_ppro.xml`. Expected `sourceFormat:"xml"`, user confirms render.
- [ ] **Step 4: SRT regression.** `import_media` the `…_DX_en-US.srt`, `create_caption_track(sequenceId, <srtId>)`. Expected `success:true`; user confirms the dialogue caption track still renders (no regression).
- [ ] **Step 5: Record** all three outcomes in this plan under Task 6 `RESULTS:`.

---

## Task 7: Remove the debug tool and commit the feature

**Files:** Modify `src/tools/index.ts` (revert the 3 Task-1 sites).

- [ ] **Step 1: Delete the schema entry** (`name: 'debug_eval_script'` object), **the dispatch case** (`case 'debug_eval_script':` + its return line), and **the method** (`private async debugEvalScript`). Verify none remain:
```bash
grep -c "debug_eval_script\|debugEvalScript" src/tools/index.ts   # expect 0
```

- [ ] **Step 2: Concurrency gate + build.**
```bash
cd /Users/morgan/Documents/Projects/Adobe_Premiere_Pro_MCP
git status --porcelain src/tools/index.ts
npm run build           # expect tsc exit 0
grep -c "debug" dist/tools/index.js | cat   # sanity: debug tool gone from bundle
```

- [ ] **Step 3: RECONNECT GATE.** User reconnects; confirm `debug_eval_script` is GONE from the tool list and `create_caption_track` still works on DFXP (quick re-call).

- [ ] **Step 4: Commit.**
```bash
cd /Users/morgan/Documents/Projects/Adobe_Premiere_Pro_MCP
git add src/tools/index.ts docs/superpowers/plans/2026-05-30-dfxp-xml-caption-ingest.md
git commit -m "feat(captions): accept DFXP/XML TTML-family items in create_caption_track

Adds native ingest of .dfxp/.xml (Transcript-type) caption items, preserving
Premiere-retained positioning. Native-only (team keeps .srt backups); clear
error when a build cannot attach a Transcript item. Verified live on PPro 2025.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5:** Do NOT push (per user GitHub rules, pushes are explicit + default to morganms313). Leave committed locally; tell the user it's ready and the muting session can resume.

---

## Task 8: Update memory

**Files:** Modify `~/.claude/projects/-Users-morgan-Documents-Projects-Adobe-Premiere-Pro-MCP/memory/premiere_mcp_quirks.md` and `cr_premiere_caption_workflow.md`.

- [ ] **Step 1:** In `premiere_mcp_quirks.md`, update the caption section: DFXP/XML now ingest natively via `create_caption_track` (or, if Task 4 branch: record that native attach is impossible on this build and SRT-backup is the path). Note `.itt`/`.ttml` extensions still rejected at import.
- [ ] **Step 2:** In `cr_premiere_caption_workflow.md`, update the pipeline: DFXP can now go straight in (positioning-preserving as far as Premiere honors it); SRT remains the positionless fallback. Note positioning-correctness is still an open phase.
- [ ] **Step 3:** No commit needed (memory files are outside the repo).

---

## Self-Review notes

- **Spec coverage:** success criterion #1 (DFXP/XML → rendering track) = Tasks 3+5+6; #2 (SRT no regression) = Task 6 Step 4; #3 (clear error if native impossible) = Task 4. Spike mechanic = Tasks 1–3. Concurrency gate = every build step. Cleanup of debug tool = Task 7.
- **Spike-dependent code:** `WINNING_CALL` in Task 5 is intentionally captured live in Task 3 before Task 5 runs — this is a spike, the exact host call is unknowable until probed. Task 3 Step 3 mandates recording it verbatim before Task 5 consumes it.
- **No unit tests:** Adobe's caption read-back limitation makes automated assertion impossible; verification is live MCP call + user visual scrub throughout. This is a documented constraint, not a gap.
- **Placeholder check:** the one deliberate placeholder (`DEالبUG`) is a read-gate with explicit correction instructions; `WINNING_CALL` / nodeids are spike outputs with explicit capture steps. No silent TODOs.
