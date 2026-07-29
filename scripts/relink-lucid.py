#!/usr/bin/env python3
"""relink-lucid.py — bulk-relink Premiere projects after the Crunchyroll
LucidLink filespace migration.

A .prproj is gzipped XML holding plain POSIX media paths. When CR moved from
the old `marketing` filespace to `crunchyroll/{mvo,creativemarketing}`, every
stored path went stale, so Premiere shows the relink dialog on open and then
crawls the FUSE mount looking for each file — slow, and once per project.

This resolves the paths offline instead:

  1. an ordered PREFIX table handles the mechanical part of the move
     (everything below those prefixes survived the migration unchanged), then
  2. a basename index of the new filespaces catches assets that were actually
     reshuffled, then
  3. Premiere's own stored offline verdict is cleared for whatever now resolves
     — it trusts that verdict on the next open, so a corrected path alone still
     comes up offline.

Any absolute path that no longer resolves goes through this, not just old-space
ones — projects touched since the migration carry paths into the new space that
have since gone stale on their own.

Candidates are scored purely by agreement with the old path, so the resolver
never applies a house-style default. Where the old path genuinely doesn't say
which variant it wanted (most often Reg vs No-Reg CTA cards, which changes the
deliverable), the path is reported ambiguous and left untouched.

Rewritten projects open fully online — no dialog, no folder scan.

    relink-lucid.py --index                     # build/refresh the file index
    relink-lucid.py --dry-run DIR_OR_PRPROJ...  # report, touch nothing
    relink-lucid.py --fix     DIR_OR_PRPROJ...  # rewrite (leaves .bak)

Premiere must be closed for any project passed to --fix.
"""

from __future__ import annotations

import argparse
import gzip
import os
import re
import shutil
import sys
import time
from collections import defaultdict
from xml.sax.saxutils import escape, unescape

# Roots of the new filespaces, crawled by --index.
INDEX_ROOTS = [
    "/Volumes/crunchyroll/creativemarketing",
    "/Volumes/crunchyroll/mvo",
]

# Ordered old->new prefix rewrites. Longest/most specific first: the first
# entry a path matches wins, so CR_Brand2024_SimpleCards must precede the
# general "Marketing Globalization" rule.
PREFIXES = [
    (
        "/Volumes/marketing/Marketing Globalization/CR_Brand2024_SimpleCards/",
        "/Volumes/crunchyroll/mvo/01_Marketing Versioning Operations/"
        "_Resources/GFX/CR_Brand_SimpleCards/",
    ),
    (
        "/Volumes/marketing/Marketing Globalization/",
        "/Volumes/crunchyroll/mvo/01_Marketing Versioning Operations/",
    ),
    (
        "/Volumes/marketing/002_CRUNCHYROLL CREATIVE/",
        "/Volumes/crunchyroll/creativemarketing/",
    ),
    # Snapshot mounts were read-only dailies of the old space; their contents
    # map to the same place as the live paths did.
    (
        "/Volumes/marketing (Snapshots)/",
        "/Volumes/crunchyroll/creativemarketing/",
    ),
]

# The PREFIX table above only applies to paths under the old filespace, but any
# absolute path that no longer resolves is worth relinking. Projects touched
# since the migration can carry paths into the *new* space that have since gone
# stale on their own — e.g. CR_Brand2024_SimpleCards was later renamed
# CR_Brand_SimpleCards, leaving half-relinked projects pointing at nothing.
OLD_SPACE = ("/Volumes/marketing",)

# Candidates under these roots are canonical shared libraries; everything else
# is a project-local copy and a worse relink target.
PREFER = (
    "/_Resources/GFX/CR_Brand_SimpleCards/",
    "/02_Source_Library/02_GFX/",
    "/02_Source_Library/",
)

# Path components that mark a superseded or duplicated copy. These only count
# against a candidate when the *old* path didn't carry the same marker — a file
# that already lived in a zOLD folder should relink to the zOLD folder.
DEMOTE = ("zold", "zzold", "archive", "_old", "old", "backup", "snapshot",
          # per-project "collect files" copies of shared library assets
          "07_2026_project_collect")

# The migration renamed some directory levels. Normalising them lets component
# matching see through the rename — critical for the Reg / No-Reg distinction,
# which changes the deliverable and must never be decided by a global default.
SYNONYMS = {
    "with_reg": "reg",
    "with_cr_registered_trademark": "reg",
    "_with_registered_trademark": "reg",
    "no_reg": "noreg",
    "no_cr_registered_trademark": "noreg",
    "cr_brand2024_simplecards": "cr_brand_simplecards",
}

# Regenerable Premiere artifacts. Never worth relinking; Premiere rebuilds them.
IGNORE = (".prv/", "adobe premiere pro video previews", "/media cache",
          ".pek", ".cfa", ".ims")

PATH_ELEMENTS = ("FilePath", "ActualMediaFilePath")

CACHE = os.path.expanduser("~/.cache/cr-relink/index.tsv")


# --------------------------------------------------------------------------
# index


def build_index(roots: list[str], cache: str) -> int:
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    tmp = cache + ".tmp"
    n = 0
    started = time.time()
    with open(tmp, "w", encoding="utf-8", errors="surrogateescape") as out:
        for root in roots:
            if not os.path.isdir(root):
                print(f"  ! skipping {root} (not mounted)", file=sys.stderr)
                continue
            print(f"  crawling {root} ...", file=sys.stderr)
            for dirpath, _dirnames, filenames in os.walk(root, onerror=None):
                for fn in filenames:
                    if fn == ".DS_Store":
                        continue
                    out.write(fn + "\t" + os.path.join(dirpath, fn) + "\n")
                    n += 1
    os.replace(tmp, cache)
    print(f"  indexed {n:,} files in {time.time() - started:.0f}s -> {cache}",
          file=sys.stderr)
    return n


def load_index(cache: str) -> dict[str, list[str]]:
    if not os.path.exists(cache):
        sys.exit(f"no index at {cache} — run: {sys.argv[0]} --index")
    idx: dict[str, list[str]] = defaultdict(list)
    with open(cache, encoding="utf-8", errors="surrogateescape") as fh:
        for line in fh:
            name, _, path = line.rstrip("\n").partition("\t")
            if path:
                idx[name].append(path)
    return idx


# --------------------------------------------------------------------------
# resolution


def _components(path: str) -> list[str]:
    out = []
    for c in path.lower().split("/"):
        if c:
            out.append(SYNONYMS.get(c, c))
    return out


def _suffix_score(a: list[str], b: list[str]) -> int:
    """Number of trailing path components a and b have in common."""
    n = 0
    while n < min(len(a), len(b)) and a[-1 - n] == b[-1 - n]:
        n += 1
    return n


def _rank(old: str, cand: str) -> tuple:
    """Higher is better. Everything is measured against the *old* path, so no
    global house-style default can override what the project actually used."""
    o, c = _components(old), _components(cand)
    oset, cset = set(o), set(c)
    return (
        _suffix_score(o, c),
        # How much of the old path survives anywhere in the candidate. This is
        # what keeps Reg with Reg, a language with its language, and so on.
        len(oset & cset),
        # Markers the candidate adds that the old path never had.
        -len([d for d in DEMOTE if d in cset and d not in oset]),
        any(p in cand for p in PREFER),
        -len(c),  # prefer the shallower of two otherwise-equal candidates
    )


class Resolver:
    """Maps a stale absolute path to its new home. Memoized per run."""

    def __init__(self, index: dict[str, list[str]]):
        self.index = index
        self.cache: dict[str, tuple[str | None, str]] = {}
        self.ambiguous: dict[str, list[str]] = {}
        self.picked: dict[str, tuple[str, int]] = {}

    def resolve(self, old: str) -> tuple[str | None, str]:
        """-> (new_path_or_None, status). Status is one of:
        online | prefix | index | picked | ambiguous | nomatch | skipped | foreign"""
        if old in self.cache:
            return self.cache[old]
        result = self._resolve(old)
        self.cache[old] = result
        return result

    def _resolve(self, old: str) -> tuple[str | None, str]:
        if not old.startswith("/"):
            return None, "foreign"
        low = old.lower()
        if any(pat in low for pat in IGNORE):
            return None, "skipped"
        if os.path.exists(old):
            return None, "online"

        if old.startswith(OLD_SPACE):
            for a, b in PREFIXES:
                if old.startswith(a):
                    cand = b + old[len(a):]
                    if os.path.exists(cand):
                        return cand, "prefix"
                    break  # first matching rule wins; fall through to the index

        # Never trust the index blindly — it is a snapshot, and the filespaces
        # keep moving. A candidate that no longer exists is no candidate.
        cands = [c for c in self.index.get(os.path.basename(old), [])
                 if os.path.exists(c)]
        if not cands:
            return None, "nomatch"
        best = max(_rank(old, c) for c in cands)
        winners = [c for c in cands if _rank(old, c) == best]
        if len(winners) == 1:
            if len(cands) == 1:
                return winners[0], "index"
            # Several real candidates existed; the ranking broke the tie. Worth
            # surfacing so the choice can be sanity-checked.
            self.picked[old] = (winners[0], len(cands))
            return winners[0], "picked"
        self.ambiguous[old] = winners
        return None, "ambiguous"


# --------------------------------------------------------------------------
# project rewriting

MEDIA_BLOCK = re.compile(r"<Media\b.*?</Media>", re.DOTALL)
OFFLINE_REASON = re.compile(r"\s*<OfflineReason>[^<]*</OfflineReason>")


def read_project(path: str) -> tuple[str, bool]:
    """-> (xml_text, was_gzipped)"""
    with open(path, "rb") as fh:
        head = fh.read(2)
    if head == b"\x1f\x8b":
        with gzip.open(path, "rb") as fh:
            return fh.read().decode("utf-8", errors="surrogateescape"), True
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", errors="surrogateescape"), False


def write_project(path: str, xml: str, gzipped: bool) -> None:
    data = xml.encode("utf-8", errors="surrogateescape")
    if gzipped:
        with gzip.open(path, "wb") as fh:
            fh.write(data)
    else:
        with open(path, "wb") as fh:
            fh.write(data)


def process(project: str, resolver: Resolver, apply: bool) -> dict:
    xml, gzipped = read_project(project)
    project_dir = os.path.dirname(os.path.abspath(project))
    stats = defaultdict(int)
    unresolved: list[tuple[str, str]] = []
    seen: set[str] = set()

    def rewrite_paths(text: str) -> str:
        def sub(m: re.Match) -> str:
            tag, raw = m.group(1), m.group(2)
            old = unescape(raw)
            new, status = resolver.resolve(old)
            if old not in seen:
                seen.add(old)
                stats[status] += 1
                if status in ("ambiguous", "nomatch", "picked"):
                    unresolved.append((status, old))
            if new is None:
                return m.group(0)
            return f"<{tag}>{escape(new)}</{tag}>"

        pattern = re.compile(
            r"<(%s)>([^<]*)</\1>" % "|".join(PATH_ELEMENTS)
        )
        return pattern.sub(sub, text)

    def fix_block(m: re.Match) -> str:
        block = rewrite_paths(m.group(0))
        # <RelativePath> is stored relative to the project file, so recompute
        # it from whatever this block now points at.
        anchor = None
        for tag in ("ActualMediaFilePath", "FilePath"):
            hit = re.search(r"<%s>([^<]*)</%s>" % (tag, tag), block)
            if hit:
                cand = unescape(hit.group(1))
                if cand.startswith("/") and os.path.exists(cand):
                    anchor = cand
                    break
        if anchor:
            rel = os.path.relpath(anchor, project_dir)
            block = re.sub(
                r"<RelativePath>[^<]*</RelativePath>",
                lambda _: f"<RelativePath>{escape(rel)}</RelativePath>",
                block,
            )
            # Premiere records its offline verdict in the project and trusts it
            # on the next open — fixing the path is not enough, the item stays
            # offline until the verdict is cleared. Only online media omits the
            # element, so drop it now that this block points at a real file.
            block, n = OFFLINE_REASON.subn("", block)
            stats["cleared"] += n
        return block

    new_xml = MEDIA_BLOCK.sub(fix_block, xml)
    # Catch any path elements that live outside a <Media> block.
    new_xml = rewrite_paths(new_xml)

    changed = new_xml != xml
    if apply and changed:
        backup = project + ".bak"
        if not os.path.exists(backup):
            shutil.copy2(project, backup)
        write_project(project, new_xml, gzipped)

    return {
        "project": project,
        "stats": dict(stats),
        "unresolved": unresolved,
        "changed": changed,
    }


# --------------------------------------------------------------------------
# cli


def collect_projects(targets: list[str]) -> list[str]:
    out: list[str] = []
    for t in targets:
        if os.path.isdir(t):
            for dirpath, dirnames, filenames in os.walk(t):
                dirnames[:] = [
                    d for d in dirnames
                    if d != "Adobe Premiere Pro Auto-Save"
                ]
                out += [
                    os.path.join(dirpath, f)
                    for f in filenames
                    if f.endswith(".prproj")
                ]
        elif t.endswith(".prproj"):
            out.append(t)
        else:
            print(f"  ! not a project or directory: {t}", file=sys.stderr)
    return sorted(out)


ORDER = ["prefix", "index", "picked", "ambiguous", "nomatch",
         "online", "skipped", "foreign", "cleared"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", action="store_true",
                    help="crawl the new filespaces and cache a file index")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be relinked, change nothing")
    ap.add_argument("--fix", action="store_true",
                    help="rewrite the projects in place (leaves a .bak)")
    ap.add_argument("--cache", default=CACHE, help=f"index location [{CACHE}]")
    ap.add_argument("targets", nargs="*",
                    help=".prproj files or directories to scan")
    args = ap.parse_args()

    if args.index:
        build_index(INDEX_ROOTS, args.cache)
        if not args.targets:
            return 0

    if not (args.dry_run or args.fix):
        ap.error("pass --dry-run or --fix (or --index on its own)")
    if not args.targets:
        ap.error("no targets given")

    projects = collect_projects(args.targets)
    if not projects:
        print("no .prproj files found")
        return 1

    resolver = Resolver(load_index(args.cache))
    totals: dict[str, int] = defaultdict(int)
    results = []

    for p in projects:
        try:
            r = process(p, resolver, apply=args.fix)
        except Exception as exc:  # a corrupt or in-use project shouldn't halt the batch
            print(f"\n{p}\n  ! FAILED: {exc}", file=sys.stderr)
            continue
        results.append(r)
        for k, v in r["stats"].items():
            totals[k] += v

        rel = os.path.relpath(p)
        summary = "  ".join(
            f"{k}={r['stats'][k]}" for k in ORDER if r["stats"].get(k)
        ) or "no media paths"
        flag = "" if args.dry_run else (" [written]" if r["changed"] else " [no change]")
        print(f"\n{rel}\n  {summary}{flag}")
        for status, path in r["unresolved"]:
            print(f"    {status.upper():9} {path}")
            if status == "ambiguous":
                for c in resolver.ambiguous.get(path, []):
                    print(f"              -> {c}")
            elif status == "picked":
                chosen, n = resolver.picked[path]
                print(f"              -> {chosen}   ({n} candidates)")

    print("\n" + "=" * 70)
    print(f"{len(results)} project(s)")
    for k in ORDER:
        if totals.get(k):
            print(f"  {k:10} {totals[k]}")
    if args.dry_run:
        print("\ndry run — nothing written. Re-run with --fix to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
