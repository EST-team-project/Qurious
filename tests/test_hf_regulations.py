"""TC-HR — 상품 안내 규제 근거 원문 데이터셋 정리(scripts/hf_regulations.py) · 2026-10-12

무엇을 지키나
1. 받은 원문 여덟을 원문마다 폴더(page.html · text.txt · meta.json) · 색인 · 매니페스트로 정리하고, 다시 돌려도 같다(멱등).
2. 열쇠 · 제목 · 주소는 요건 상수표(app/services/etp_requirements.py)에서 온다 — 상수표의 출처가 모두 색인에 있다
   (사본이 없는 증권사 공지 · 감독규정은 「주소만」 줄로).
3. 매니페스트의 sha256 이 파일과 같다 — 올리기 관문 2(로컬 무결성)가 기대는 값.
4. 받은 폴더에 원문이 하나라도 없으면 아무것도 쓰지 않고 멈춘다(말없이 일부만 올리지 않게).
네트워크 · 토큰은 쓰지 않는다(올리기 · 대조는 시험 밖).
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from app.services import etp_requirements as etp
from scripts import hf_regulations as hr


@pytest.fixture
def src(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr(hr, "OUT_DIR", out)
    monkeypatch.setattr(hr, "META_DIR", out / "meta")
    monkeypatch.setattr(hr, "MANIFEST_PATH", out / "meta" / "manifest.json")
    d = tmp_path / "받음"
    d.mkdir()
    for name in hr.FILE_KEYS:
        (d / name).write_text(f"<html><head><title>{name}</title><script>x()</script></head>"
                              f"<body><p>{name} 본문 &amp; 표</p></body></html>", encoding="utf-8")
    return d


def _index(out: Path) -> list[dict]:
    with (out / "index.tsv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def test_build_lays_out_sources_and_is_idempotent(src):
    assert hr.build(src) == 0
    out = hr.OUT_DIR
    rows = _index(out)
    copies = [r for r in rows if r["copy"] == "True"]
    assert len(copies) == len(hr.FILE_KEYS) == 8
    for r in copies:
        d = out / Path(r["path"]).parent
        assert (d / "page.html").exists() and (d / "text.txt").exists()
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        assert meta["key"] == r["key"] and meta["url"].startswith("https://")
        assert "<script>" not in (d / "text.txt").read_text(encoding="utf-8")      # 본문 글자에는 스크립트가 없다
    first = json.loads(hr.MANIFEST_PATH.read_text(encoding="utf-8"))
    assert hr.build(src) == 0                                                     # 다시 돌려도
    again = json.loads(hr.MANIFEST_PATH.read_text(encoding="utf-8"))
    assert first["files"] == again["files"]                                       # 같은 파일 · 같은 sha256


def test_every_requirement_source_is_indexed_and_keys_match(src):
    assert hr.build(src) == 0
    rows = {r["key"]: r for r in _index(hr.OUT_DIR)}
    assert set(etp.SOURCES) <= set(rows)                       # 상수표가 쓰는 출처는 모두 색인에
    for key, s in etp.SOURCES.items():
        assert rows[key]["url"] == s["url"] and rows[key]["title"] == s["title"]   # 제목 · 주소는 상수표에서
    links = {k for k, r in rows.items() if r["copy"] == "False"}
    assert links == set(etp.SOURCES) - set(hr.FILE_KEYS.values())                  # 사본 없는 것 = 받지 않은 출처
    assert "single_stock" in rows["fsc_2026_07_24"]["used_by"]                     # 쓰는 곳이 요건 열쇠로 이어진다


def test_manifest_sha256_matches_files(src):
    assert hr.build(src) == 0
    man = json.loads(hr.MANIFEST_PATH.read_text(encoding="utf-8"))
    assert man["copies"] == 8 and man["as_of"] == etp.AS_OF
    for f in man["files"]:
        p = hr.OUT_DIR / f["path"]
        assert hashlib.sha256(p.read_bytes()).hexdigest() == f["sha256"] and p.stat().st_size == f["bytes"]
    assert not any(f["path"].startswith("meta/") for f in man["files"])          # 매니페스트가 자기를 세지 않는다


def test_missing_source_stops_without_writing(src):
    next(iter(src.iterdir())).unlink()
    assert hr.build(src) == 1
    assert not hr.OUT_DIR.exists()                                                 # 아무것도 쓰지 않았다
