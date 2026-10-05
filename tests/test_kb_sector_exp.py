"""섹터 법령 근거 답 실험 시험 (TC-SX) — `collector/kb_sector_exp.py` · 평가 도구의 정답 칸 (목표 기능 ① · 설계서 5.3.7).

여기서 지키는 것 —
1. 평가셋 정답 칸 「문서:조」 는 **마지막 콜론**에서 나눈다 — 실험 문서 ID 에는 콜론이 있다(`sec:은행법`). 첫 콜론에서 나누면
   정답 18개가 모두 「놓침」 으로 잘못 세진다(2026-10-05 실측).
2. 실험 문서 ID 는 근거 DB 의 영문 ID 와 겹치지 않는 머리(`sec:`)를 단다.
3. 「넣은 길」 은 이 프로세스에서만 — 사본 DB 경로 · 다른 컬렉션으로 바꾸고, 운영 경로 · 컬렉션 이름을 건드리지 않는다.

네트워크 · 실제 DB 를 쓰지 않는다.
"""
from __future__ import annotations

import pytest

from collector import kb_answer_eval as KA, kb_eval as KE, kb_sector_exp as X


HEAD = "id\t질문\t정답\t기대\t의도_묶음\t섞임_낱말\t메모\n"


def test_gold_split_on_last_colon(tmp_path):
    """TC-SX-01 · 정답 칸은 마지막 콜론에서 — 「sec:은행법:제8조」 → (sec:은행법, 제8조) · 옛 꼴(stt_act:제8조)도 그대로."""
    p = tmp_path / "set.tsv"
    p.write_text(HEAD + "S01\t은행업 자본금은?\tsec:은행법:제8조; stt_act:제8조\tanswer\tsector\t\t\n", encoding="utf-8")
    assert KE.load(p)[0]["gold"] == [("sec:은행법", "제8조"), ("stt_act", "제8조")]
    assert KA.load(p)[0]["gold"] == [("sec:은행법", "제8조"), ("stt_act", "제8조")]
    assert KE.first_hit([{"doc_id": "sec:은행법", "article": "제8조"}], KE.load(p)[0]["gold"]) == 1


def test_doc_id_prefix_and_experiment_switch_is_local(monkeypatch):
    """TC-SX-02 · 실험 문서 ID 는 `sec:` + 띄어쓰기 뺀 이름 · 실험 스위치는 사본 DB · 다른 컬렉션으로만 바꾼다."""
    assert X.doc_id_for("중대재해 처벌 등에 관한 법률") == "sec:중대재해처벌등에관한법률"
    monkeypatch.delenv("KB_DB_PATH", raising=False)
    monkeypatch.setattr(X.kb_law, "KB_DB_PATH", X.kb_law.KB_DB_PATH)
    monkeypatch.setattr(X.kb_text, "KB_COLLECTION", "kb_v1")
    X._use_experiment()
    assert X.kb_text.KB_COLLECTION == "kb_v1_sector" and X.kb_law.KB_DB_PATH == X.EXP_DB
    import os
    assert os.environ["KB_DB_PATH"] == str(X.EXP_DB) and X.EXP_DB.name == "kb_exp_sector.sqlite3"
