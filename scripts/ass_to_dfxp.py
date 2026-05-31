#!/usr/bin/env python3
"""Convert a combined .ass (FN+Dx, top/bottom via styles) into a Premiere-ingestable DFXP
that positions each cue using the two levers Premiere's scripting import actually honors:

  VERTICAL  -> number of leading <br/> before the text. Premiere anchors captions to the TOP
               and ignores region/displayAlign/origin on scripting import; each leading <br/>
               pushes the cue down ~1 row. Calibrated (1080p / Arial / fontSize 21):
               0 br = top, 15 br = clean bottom safe-area. FN/signs -> top (0). Dialogue -> bottom (15).
  HORIZONTAL -> leading NBSP (&#160;). tts:textAlign is ignored on import (text left-anchors);
               the line sits on a ~42-col monospace grid, so center => leading = round((42-len)/2).
               MUST be NBSP, not regular spaces — Premiere collapses runs of regular leading
               spaces (~16u each, too weak); NBSP holds full char width (~54u each).

Both calibrations are for 1080p Arial 21; retune BOTTOM_BR / GRID_COLS for other res/font.
Discovered + verified live on Premiere Pro 25.6.5, 2026-05-30. See memory: cr_premiere_caption_workflow.

Usage: ass_to_dfxp.py input.ass output.dfxp
"""
import re, sys, html

BOTTOM_BR = 15          # leading <br/> for a 1-line bottom cue (calibrated 1080p/Arial/21)
TOP_BR    = 0           # leading <br/> for a top cue
GRID_COLS = 42          # line char-capacity at this size; center => leading = (GRID_COLS-len)/2
FPS_NUM, FPS_DEN = 24000, 1001   # 23.976

def center_pad(plain_line):
    """Leading NBSP entities to horizontally center one visible text line (monospace-grid model).
    MUST be NBSP (&#160;), not regular spaces: Premiere collapses runs of regular leading spaces
    (~16u each) but honors NBSP at full char width (~54u each). Calibrated GRID_COLS=42 assumes NBSP."""
    n = max(0, round((GRID_COLS - len(plain_line)) / 2))
    return "&#160;" * n

# .ass styles that belong at TOP (forced narrative / signs)
TOP_STYLES = {"top", "italicstop", "flashbacktop", "flashbackitalicstop", "overlaptop", "sign_generic"}

def ass_secs(t):
    h, m, rest = t.split(":"); s, cs = rest.split(".")
    return int(h)*3600 + int(m)*60 + int(s) + int(cs)/100.0

def frames(sec): return int(round(sec * FPS_NUM / FPS_DEN))

def tc(f):   # frame count -> HH:MM:SS:FF (24 nominal frame field)
    fps = 24
    return f"{f//(fps*3600):02d}:{(f//(fps*60))%60:02d}:{(f//fps)%60:02d}:{f%fps:02d}"

def conv_text(raw):
    """ASS inline -> TTML, per-line center-padded with leading NBSP.
    \\N -> line break; {\\i1}/{\\i0} -> italic span; other override tags stripped.
    Each visible line gets leading NBSP so it centers (Premiere ignores tts:textAlign on import)."""
    lines = [[]]            # list of segments per line; segment = (text, italic)
    plains = [""]           # plain (tag-free) text per line, for width measure
    ital = False
    for part in re.split(r"(\{[^}]*\})", raw):
        if part.startswith("{") and part.endswith("}"):
            if re.search(r"\\i1", part): ital = True
            if re.search(r"\\i0", part): ital = False
            continue
        for j, seg in enumerate(re.split(r"\\N|\\n", part)):
            if j:
                lines.append([]); plains.append("")
            if seg:
                lines[-1].append((seg, ital))
                plains[-1] += seg
    out_lines = []
    for segs, plain in zip(lines, plains):
        pad = center_pad(plain)
        buf = [pad] if pad else []   # NBSP entities — already XML-safe, do NOT html.escape (would double-encode)
        for text, it in segs:
            esc = html.escape(text)
            buf.append(f'<span tts:fontStyle="italic">{esc}</span>' if it else esc)
        out_lines.append("".join(buf))
    return "<br/>".join(out_lines)

def text_line_count(rendered):
    return rendered.count("<br/>") + 1

def main():
    src, out = sys.argv[1], sys.argv[2]
    events = []
    for line in open(src, encoding="utf-8"):
        if not line.startswith("Dialogue:"): continue
        f = line[len("Dialogue:"):].strip().split(",", 9)
        start, end, style, text = f[1].strip(), f[2].strip(), f[3].strip(), f[9]
        region = "top" if style in TOP_STYLES else "bottom"
        rendered = conv_text(text)
        events.append((frames(ass_secs(start)), frames(ass_secs(end)), region, rendered))
    events.sort(key=lambda e: e[0])

    ps = []
    for sf, ef, region, rendered in events:
        if region == "top":
            lead = TOP_BR
        else:
            # keep the LAST line of a multi-line cue at the bottom row
            lead = max(0, BOTTOM_BR - (text_line_count(rendered) - 1))
        pad = "<br/>" * lead
        ps.append(f'      <p begin="{tc(sf)}" end="{tc(ef)}" tts:textAlign="center" region="{region}" style="basic">{pad}{rendered}</p>')

    doc = f'''<?xml version="1.0" encoding="utf-8"?>
<tt xml:lang="en" xmlns="http://www.w3.org/ns/ttml" xmlns:tts="http://www.w3.org/ns/ttml#styling" xmlns:ttm="http://www.w3.org/ns/ttml#metadata" xmlns:ttp="http://www.w3.org/ns/ttml#parameter" ttp:timeBase="media" ttp:frameRate="24" ttp:frameRateMultiplier="1000 1001" xmlns:smpte="http://www.smpte-ra.org/schemas/2052-1/2010/smpte-tt" xmlns:m608="http://www.smpte-ra.org/schemas/2052-1/2010/smpte-tt#cea608">
  <head>
    <metadata>
      <ttm:title>ass_to_dfxp positioned</ttm:title>
      <ttm:desc>SMPTE Timed Text document created by Subtitle Edit</ttm:desc>
      <smpte:information xmlns:m608="http://www.smpte-ra.org/schemas/2052-1/2010/smpte-tt#cea608" origin="http://www.smpte-ra.org/schemas/2052-1/2010/smpte-tt#cea608" mode="Preserved" m608:channel="CC1" m608:programName="Demo" m608:captionService="F1C1CC" />
    </metadata>
    <styling>
      <style xml:id="basic" tts:color="white" tts:fontFamily="Arial" tts:backgroundColor="transparent" tts:fontSize="21" tts:fontWeight="normal" tts:fontStyle="normal" />
    </styling>
    <layout>
      <region xml:id="bottom" tts:backgroundColor="transparent" tts:showBackground="whenActive" tts:origin="10% 55%" tts:extent="80% 80%" tts:displayAlign="after" />
      <region xml:id="top" tts:backgroundColor="transparent" tts:showBackground="whenActive" tts:origin="10% 10%" tts:extent="80% 80%" tts:displayAlign="before" />
    </layout>
  </head>
  <body>
    <div>
{chr(10).join(ps)}
    </div>
  </body>
</tt>
'''
    open(out, "w", encoding="utf-8").write(doc)
    top = sum(1 for e in events if e[2] == "top")
    bot = sum(1 for e in events if e[2] == "bottom")
    print(f"WROTE {out} | {len(events)} cues (top={top}, bottom={bot})")
    for sf, ef, region, rendered in events:
        plain = re.sub("<[^>]+>", "", rendered)
        lead = TOP_BR if region == "top" else max(0, BOTTOM_BR - (text_line_count(rendered) - 1))
        print(f"  [{region:6}] br={lead:2} {tc(sf)} {plain[:48]}")

main()
