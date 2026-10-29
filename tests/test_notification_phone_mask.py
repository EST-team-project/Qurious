"""TC-NM — 알림 설정 응답이 전화번호를 가린다(S162 · 가입 약관 조사에서 나온 작은 고침).

화면(settings.js)이 받은 값을 그대로 다시 저장하므로, 가린 값이 실제 번호를 덮어쓰지 않아야 한다.
"""
from pathlib import Path

from app.routes.notification import keep_phone, mask_phone

ROOT = Path(__file__).resolve().parents[1]


def test_mask_phone_keeps_only_the_last_four_digits():
    assert mask_phone("010-1234-5678") == "***-****-5678"
    assert mask_phone("01012345678") == "*******5678"
    assert mask_phone("+82 10-1234-5678") == "+** **-****-5678"
    assert mask_phone("") == ""
    assert mask_phone("1234") == "****"      # 네 자리 이하는 전부 가린다
    assert mask_phone("1234") != "1234"


def test_masked_value_sent_back_keeps_the_stored_number_and_empty_clears_it():
    stored = "010-1234-5678"
    assert keep_phone(mask_phone(stored), stored) == stored          # 가린 채 되돌아오면 유지
    assert keep_phone("010-9999-0000", stored) == "010-9999-0000"    # 새 번호는 저장
    assert keep_phone("", stored) == ""                              # 비우면 지운다(예전 동작 그대로)


def test_route_masks_every_phone_field_in_the_response_and_uses_keep_on_save():
    src = (ROOT / "app" / "routes" / "notification.py").read_text(encoding="utf-8")
    for field in ("kakao_phone", "sms_from", "sms_to"):
        assert f"mask_phone(row.{field})" in src, f"{field} 응답이 가려지지 않았다"
        assert f"keep_phone(body.{field}, row.{field})" in src, f"{field} 저장이 가린 값에 덮이지 않게 보호되지 않았다"
