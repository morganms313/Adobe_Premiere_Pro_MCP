# subplace — SOP-styled, text-dodging caption cues written straight into the project

**Date:** 2026-10-07 · **Status:** design, awaiting Morgan's review · **Owner:** Morgan Starling

## Goal

For a CR SUB job, place every subtitle cue at its SOP position **unless that spot collides with burned-in
text**, in which case move it to the nearest clear spot. Then write the cues into the Premiere project as a
**normal caption track** that already carries the exact SOP look and each cue's final position. No Track
Style click, no per-language select-all styling.

Success looks like this: Morgan opens the bumped project and the DX and FN tracks are styled and placed. A
report lists every cue that moved, why it moved, and every cue that needs his call. On RRH S1 Main PV
it-IT, the report reproduces both of tech QC's 10/7 notes.

## Decisions (made by Morgan during brainstorming, 2026-10-07)

| # | Decision |
|---|---|
| D1 | Input is the **vendor-placed `.ass`** plus the vendor's **split DX/FN SRTs**. The vendor's font and size are ignored; vendors often don't match the SOP. |
| D2 | **Nearest clear spot to the SOP default.** Moves may go up, down, left or right. **FN stays in the top half, DX in the bottom half.** |
| D3 | A cue the vendor moved off its default is **reset to the SOP default and flagged** ("B, and flag"). |
| D4 | DX/FN labels come from the split SRTs. The report shows the **en-US line** for each cue so Morgan never has to read the language. |
| D5 | Detection: **OCR on the master** is the primary signal, because "textless" files are often just sub-less. Sample the **first, middle and last frame of each cue, plus one frame after each in-cue shot change.** |
| D6 | Output: **write caption cues directly into the `.prproj`**. It stays a real caption track, with the look and position baked into every cue. |
| D7 | The SOP look's source of truth is Morgan's exported **`.prtextstyle`** files (`CR-styles/`). |

## Non-goals (v1)

- Detecting faces or other non-text visuals.
- Changing cue timing automatically. Trims are **suggested** in the report, never applied.
- Building other aspect ratios from 16x9 picture. Each aspect's picture is an input. v1 is validated on 16x9.
- Changing cue text. Text always comes from the approved SRT import already in the project.

## How it fits the existing workflow

```
cr-premiere-versioning (unchanged)                       subplace (new)
──────────────────────────────────                       ──────────────────────────────────────────────
build per-lang sequences                                 1. read styles, cues, labels, en-US gloss
create DX (CC1) + FN (CC2) caption tracks from SRT  ──►  2. detect on-screen text on the master
leave tracks UNSTYLED, save <proj>_vN.prproj             3. place every cue (SOP default → nearest clear)
                                                         4. write styled + positioned cues → <proj>_vN+1
Morgan opens vN+1  ◄──────────────────────────────────── 5. verify frames + HTML report
```

subplace never edits an open project. It reads the saved `vN` and writes `vN+1`, following the CR
naming rule of bumping the global version. Morgan closes `vN` and opens `vN+1`.

## Components

All under `~/.claude/skills/cr-premiere-versioning/scripts/subplace/` (dotfiles-synced, so it's on both
Macs), with tests in `subplace/tests/`. Each unit has one job and a small interface.

| Unit | Does | Interface |
|---|---|---|
| `styles.py` | Decodes each `.prtextstyle`: font, size, faux bold, stroke, shadow, fill/stroke colors, anchor, x/y offsets, raw blob. Maps (language group, aspect, top/bottom) to a style. **A missing combination is an error that names the style to export.** | `load_styles(dir) -> {StyleKey: Look}` |
| `cues.py` | Parses the `.ass`: alignment, `\an`/`\pos`/margins, so it can tell whether the vendor moved a cue. Parses the SRTs. Labels each cue DX/FN by matching timing and text; a cue that matches neither is labeled by position and flagged. Attaches the en-US gloss by maximum time overlap. | `load_cues(ass, dx_srt, fn_srt, enus) -> [Cue]` |
| `detect.py` | Builds the frame set (D5) and finds shot changes with ffmpeg `scdet`. Runs CRAFT detection (shared media-qc `textdetect.py`) plus a recognition-confidence filter to drop false positives like the RRH fingers. Uses the textless difference only if it agrees with the OCR results. Caches per master file hash and dedupes frames across languages. | `detect(master, frames, textless=None) -> {frame: [Box]}` |
| `place.py` | Computes each cue's box at SOP size (real font metrics plus calibration). Checks collisions against text boxes during the cue and against other on-screen cues. Searches for the nearest clear spot (vertical moves before horizontal, inside title safe, inside the cue's half). If none, suggests a timing trim; otherwise flags. Also flags cues that run past a shot change into a graphics card. | `place(cues, detections, look, calib) -> [Placement]` |
| `prwriter.py` | Reads the gzipped `.prproj` XML and finds the target sequence's DX/FN caption tracks (reusing `capaudit.caption_tracks()`), then matches each cue to a Placement by timing and text. Builds each new cue blob from the **reference cue** plus every style value from the Look, the cue's **existing text**, and its anchor and offsets. Writes a fresh `BinaryHash` and saves `vN+1`. | `write(project_in, project_out, seq, placements, looks)` |
| `fb.py` | Minimal FlatBuffer reader/patcher for Premiere's TextDocument blobs: resolve field paths, patch scalars in place, append and repoint strings. **Unknown structure is a hard error, never a guess.** | `resolve`, `set_f32`, `set_string`, `flatten` |
| `calibrate.py` | One-time calibration per look: writes known offsets into a scratch project, renders frames, measures them, and stores the offset-to-pixel model and text-box metrics in `calib.json`. | `calibrate(look) -> Calib` |
| `report.py` | HTML contact sheet (one tile per cue: frame, detections, SOP box, final box, DX/FN, en-US line, status), JSON for scripts, and a paste-ready Airtable summary of flags. | `render(placements, frames, out_dir)` |
| `subplace.py` | CLI that runs one language and one aspect end to end. | see Usage |

`ass_to_mcc.py` (MCP repo `scripts/`) is **parked**. MCC was ruled out because Premiere imports it at the
old 4:3 grid and needs restyling per track (see `premiere_mcp_quirks`). It stays as a reference.

## The cue blob (what the writer changes)

Each caption cue in the project is `<Block><FormattedTextData Encoding="base64" BinaryHash=…>`, a FlatBuffer
TextDocument with the same schema as a `.prtextstyle` "Source Text". Fields confirmed on PPro 26.5.2:

| Path | Meaning | Source in the written cue |
|---|---|---|
| `R.0.0[0].0` | text | the existing cue (from the SRT import) |
| `R.0.0[0].1.1` | font size | Look |
| `R.0.0[0].1.5`, `.1.6` | faux bold, stroke width | Look |
| font name, colors, `R.0.12`, `R.0.14` | font, fill/stroke color, shadow opacity/distance | Look |
| `R.0.33.0` | anchor (absent = bottom-center, 1 = top-center, 6 = bottom-left …) | Placement |
| `R.0.33.1`, `R.0.33.2` | x and y offset as fractions of frame width and height | Placement |

Rules:
- **Reference cue.** One known-good, select-all-styled cue blob is checked in as a fixture. It has every field the writer touches. Every style field present in both the reference cue and the `.prtextstyle` is copied from the `.prtextstyle`. A style field the `.prtextstyle` has but the reference cue lacks **aborts the run**.
- **Strings** (text, font name) are appended at the end of the buffer and their offset repointed; the u32 size header is updated. Proven in the spike.
- **`BinaryHash`** = 96 random bits + `hex(len(blob)+12)`. PPro 26.5.2 accepted this.
- **Tracks must be unstyled.** A caption track with a Track Style (`<ParentStyle>`) is refused, because the style would overwrite every cue.
- **Multi-run cues** (inline italics): v1 writes the first run's style for the whole cue and flags the cue. Rebuilding runs is a v2 item.

## Placement detail

- **Default spot.** The anchor and y offset come from the matching style's Look: `16x9 Sub Bottom` is bottom-center −0.0694, `Top` is top-center +0.0694. 1x1, 4x5, 9x16 and the language variants come from their own files.
- **Box geometry.** Measured font metrics for the style's font at its size, using the line breaks from the SRT. A line wider than title safe is flagged. The model is corrected against `calib.json`, measured from real Premiere renders, so collision math matches what Premiere draws.
- **Search.** Candidates step outward from the default in 8 px vertical and 80 px horizontal steps. Cost is `|dy| + 1.5·|dx|`. A candidate must stay inside title safe and inside the cue's half (D2), and must not overlap detections or other cues on screen at the same time. The lowest cost wins.
- **No clear spot.** First the timing check: does ending the cue at the first frame the colliding text appears, or starting it after the text leaves, give at least 1 s of display? If so, that trim is **suggested** with exact timecodes. Otherwise the cue stays at its default and is **FLAGGED**.
- **Vendor-moved** (D3): reset to default, run the same search, report "vendor moved this".

## Usage

```
subplace.py --project <proj>_vN.prproj --sequence "<seq name>" --lang it-IT --aspect 16x9 \
            --ass <vendor Full.ass> --dx <DX.srt> --fn <FN.srt> --enus-ass <en-US Full.ass> \
            --master <master.mov> [--textless <textless.mov>] --styles <CR-styles dir> --out <report dir>
→ writes <proj>_vN+1.prproj, <out>/report.html, report.json, summary.txt
```

## Error handling

Every one of these fails loudly and **writes nothing**:
- missing style combination
- styled track
- schema or field mismatch in a blob
- a cue that can't be matched to the project
- more cues than SRT lines
- a master whose frame count doesn't match the sequence

## Verification (each run, before reporting success)

1. Decode every written cue again and compare text, anchor, offsets and style against what was intended.
2. Open `vN+1` through the MCP and export a frame at every moved cue and a sample of default cues. Confirm text is present inside the predicted box using `imgeval`/white-pixel bounds, then close it. The report includes these frames.

## Testing

- **Unit:** style decoding (all 17 CR-styles files), DX/FN matching, the search (synthetic boxes), timing suggestions, FlatBuffer patch round-trips, BinaryHash format, and refusals (styled track, missing style).
- **Golden:** the reference cue plus a Look must regenerate Morgan's hand-styled size-test cues byte-for-byte, except text and offsets.
- **Real job:** RRH S1 Main PV it-IT must flag cue 24 (credits, timing suggestion) and cue 22 (runs past a shot change into the title card), with the other six languages mostly clear. That matches what was already approved.
- **Calibration check:** rendered box edges within ±4 px of predicted.

## Risks

- **Premiere updates may change the blob schema.** Mitigation: the reference fixture plus field-presence checks fail loudly, re-calibration is one command, and frames are verified every run.
- **OCR false positives** cause unneeded moves. Mitigation: the confidence filter, and every move is visible in the report.
- **Arabic, Thai and CJK box metrics** differ from Latin. Mitigation: calibrate per style; v1 tests Latin and Arabic first.

## Open questions for Morgan

1. Title-safe margins per aspect. Use the SOP's? (Default: 5% each side.)
2. Minimum gap between a moved cue and the text it dodges. (Default: 12 px.)
3. Should the report go into the job's Lucid folder or stay local? (Default: local, plus a summary pasted into Airtable by hand.)
