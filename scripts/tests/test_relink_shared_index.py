"""relink-lucid.py shares its basename index through Lucid, so one crawl (usually the office mini's) serves every
Mac instead of each one re-crawling the filespaces (12+ min).  Run: python3 -m pytest scripts/tests"""
import importlib.util
import os
import time
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("relink_lucid", Path(__file__).resolve().parents[1] / "relink-lucid.py")
rl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rl)


def _write(p: Path, text: str, age_s: float = 0.0) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    t = time.time() - age_s
    os.utime(p, (t, t))
    return p


def test_shared_location_is_the_versioning_tools_folder():
    assert rl.SHARED_CACHE == ("/Volumes/crunchyroll/mvo/01_Marketing Versioning Operations/_Resources/Versioning/"
                               "Tools/.cr-relink/index.tsv")


def test_publish_copies_the_local_index_to_the_shared_spot(tmp_path):
    local = _write(tmp_path / "local/index.tsv", "a.mov\t/x/a.mov\n")
    (tmp_path / "Tools").mkdir()                               # the Versioning Tools folder already exists on Lucid
    shared = tmp_path / "Tools/.cr-relink/index.tsv"
    assert rl.publish_index(str(local), str(shared)) is True
    assert shared.read_text() == local.read_text()
    assert not list(shared.parent.glob("*.tmp"))


def test_publish_skips_when_the_tools_folder_is_not_mounted(tmp_path):
    local = _write(tmp_path / "local/index.tsv", "a\t/a\n")
    assert rl.publish_index(str(local), str(tmp_path / "missing/Tools/.cr-relink/index.tsv")) is False


def test_newer_shared_index_is_pulled_into_the_local_cache(tmp_path):
    local = _write(tmp_path / "local/index.tsv", "old\t/old\n", age_s=3600)
    shared = _write(tmp_path / "Tools/.cr-relink/index.tsv", "new\t/new\n", age_s=60)
    path, source = rl.choose_index(str(local), str(shared))
    assert source == "shared" and path == str(local) and local.read_text() == "new\t/new\n"


def test_newer_local_index_wins(tmp_path):
    local = _write(tmp_path / "local/index.tsv", "mine\t/m\n", age_s=60)
    shared = _write(tmp_path / "Tools/.cr-relink/index.tsv", "theirs\t/t\n", age_s=3600)
    assert rl.choose_index(str(local), str(shared)) == (str(local), "local")


def test_only_shared_exists(tmp_path):
    shared = _write(tmp_path / "Tools/.cr-relink/index.tsv", "s\t/s\n")
    local = tmp_path / "local/index.tsv"
    assert rl.choose_index(str(local), str(shared)) == (str(local), "shared") and local.exists()


def test_no_shared_flag_or_missing_shared_uses_local(tmp_path):
    local = _write(tmp_path / "local/index.tsv", "l\t/l\n")
    assert rl.choose_index(str(local), None) == (str(local), "local")
    assert rl.choose_index(str(local), str(tmp_path / "nope.tsv")) == (str(local), "local")


def test_neither_exists_exits_with_the_index_hint(tmp_path):
    with pytest.raises(SystemExit, match="--index"):
        rl.choose_index(str(tmp_path / "l.tsv"), str(tmp_path / "s.tsv"))


def test_crawl_skips_the_shared_index_folder(tmp_path):
    root = tmp_path / "mvo"
    _write(root / "show/a.mov", "")
    _write(root / "_Resources/Versioning/Tools/.cr-relink/index.tsv", "x\t/x\n")
    cache = tmp_path / "local/index.tsv"
    assert rl.build_index([str(root)], str(cache)) == 1
    assert "index.tsv" not in cache.read_text()
