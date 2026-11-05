"""TC-NODE · 시험 머리의 Node 버전 안내 (#567).

낮은 Node(WSL 기본 v12 등)에서 Node 를 쓰는 화면 시험이 한꺼번에 실패해도 제품 회귀로 오해하지 않게,
`tests/conftest.py` 가 시험 머리에 Node 버전과 경고를 찍는다. 그 문구를 고르는 함수만 본다(Node 를 실제로 부르지 않는다).
"""
import pytest

from tests.conftest import NODE_MIN_MAJOR, node_version_note


@pytest.mark.parametrize("raw", ["v24.22.1\n", "v22.7.0", "v23.0.0"])
def test_node_new_enough_has_no_warning(raw):
    """TC-NODE-01 · 기준 이상이면 버전만 찍고 경고는 없다."""
    note = node_version_note(raw)
    assert note == f"node: {raw.strip()}" and "⚠" not in note


@pytest.mark.parametrize("raw", ["v12.22.9\n", "v14.8.0", "v18.20.4", f"v{NODE_MIN_MAJOR - 1}.9.0"])
def test_node_too_old_warns_not_a_regression(raw):
    """TC-NODE-02 · 낮으면 「제품 회귀가 아니다」 경고를 찍는다(버전 숫자도 함께)."""
    note = node_version_note(raw)
    assert "⚠" in note and raw.strip() in note and "제품 회귀가 아니다" in note and str(NODE_MIN_MAJOR) in note


@pytest.mark.parametrize("raw", [None, "", "  \n"])
def test_node_missing_says_skip(raw):
    """TC-NODE-03 · Node 가 없으면(출력 없음) 화면 시험을 건너뛴다고 알린다."""
    assert "건너뛴다" in node_version_note(raw)


def test_node_unparsable_version_is_reported_not_crash():
    """TC-NODE-04 · 읽을 수 없는 문자열도 오류 없이 한 줄로 알린다."""
    assert "읽지 못함" in node_version_note("not-a-version")
