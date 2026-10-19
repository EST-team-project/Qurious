"""가상 장부 기록과 증권사 접수·체결 근거를 구분한다. 과거 로그도 같은 규칙으로 읽는다."""


def failure_message(live: dict) -> str:
    code = str(live.get("code") or live.get("reason") or "")
    raw = str(live.get("error") or "")
    if code == "KIS_TOKEN_RATE_LIMIT" or "EGW00133" in raw:
        return "접속 토큰 발급 제한입니다. 잠시 뒤 연동 상태를 확인해 주세요."
    if code == "KIS_TOKEN_UNAVAILABLE":
        return "접속 토큰을 준비하지 못했습니다. 인증 정보와 토큰 저장소를 확인해 주세요."
    if "/oauth2/tokenP" in raw:
        return "접속 토큰 발급에 실패해 주문을 전송하지 못했습니다. 인증 정보와 발급 제한을 확인해 주세요."
    return {
        "kis_credentials_not_configured": "KIS 인증 정보가 연결되지 않았습니다.",
        "broker_not_configured": "증권사 주문 연결이 설정되지 않았습니다.",
        "market_closed": "주문 가능한 장 운영시간이 아닙니다.",
        "risk_store_unavailable": "위험관리 저장소에 연결하지 못했습니다.",
    }.get(code, "증권사 응답과 계좌 주문 내역을 확인해 주세요.")


def describe_trade(trade: dict, mode: str | None = None, tracked: dict | None = None) -> dict:
    virtual = trade.get("virtual_status", trade.get("status")) in ("filled", "virtual_filled")
    live = trade.get("live_order") or {}
    state = str((tracked or {}).get("status") or live.get("status") or "").upper()
    if trade.get("type") == "risk" or (not virtual and trade.get("status") == "skipped"):
        status, label, level, detail = "skipped", "주문 생략", "warning", trade.get("reason", "")
    elif tracked and state == "FILLED" and (tracked.get("filled_quantity") or 0) > 0:
        status, label, level, detail = "broker_filled", "증권사 체결 확인", "success", "증권사 체결 조회로 수량과 평균 체결가를 확인했습니다."
    elif tracked and (tracked.get("filled_quantity") or 0) > 0:
        status, label, level, detail = "broker_partial", "증권사 일부 체결", "warning", "일부 수량의 체결만 확인됐습니다. 잔여 주문 상태를 확인해 주세요."
    elif state in ("UNKNOWN", "PENDING", "LOST") or live.get("code") in ("GATEWAY_UNREACHABLE", "ORDER_SUBMISSION_UNKNOWN"):
        status, label, level, detail = "broker_unknown", "증권사 접수 여부 미확인", "warning", "응답을 확인하지 못했습니다. 재주문 전에 증권사 주문 내역을 확인해 주세요."
    elif state in ("ERROR", "REJECTED", "FAILED"):
        status, label, level, detail = "broker_failed", "증권사 주문 실패", "error", failure_message(live)
    elif state in ("CANCELLED", "CANCELED", "EXPIRED"):
        status, label, level, detail = "broker_cancelled", "증권사 주문 취소·만료", "warning", "가상 장부 기록과 계좌 보유 내역을 확인해 주세요."
    elif state == "SKIPPED":
        status, label, level, detail = "broker_skipped", "증권사 주문 미전송", "warning", failure_message(live)
    elif state in ("SUBMITTED", "ACCEPTED", "PENDING", "PARTIAL", "PARTIALLY_FILLED", "FILLED", "CANCEL_REQUESTED"):
        status, label, level, detail = "broker_submitted", "증권사 접수·체결 미확인", "warning", "주문 접수는 체결이 아닙니다. 증권사 체결 내역을 확인해 주세요."
    elif mode == "paper" and virtual and not live:
        status, label, level, detail = "virtual_filled", "가상 체결", "info", "앱 가상 장부에만 기록했으며 증권사 주문은 전송하지 않았습니다."
    else:
        status, label, level, detail = "broker_unknown", "증권사 주문 근거 없음", "warning", "기존 로그에 접수·체결 근거가 없습니다. 증권사 계좌에서 확인해 주세요."
    ledger = "과거 가상 장부 기록 있음 · KIS 체결을 뜻하지 않음" if virtual else "가상 장부 미반영"
    if status == "virtual_filled":
        ledger = "가상매매 전용 장부 기록"
    if virtual and status in ("broker_failed", "broker_skipped"):
        ledger = "가상 장부에만 기록됨"
    return {"status": status, "label": label, "level": level, "detail": detail, "ledger": ledger,
            "virtual_status": "filled" if virtual else trade.get("virtual_status", "not_recorded"),
            "filled_quantity": (tracked or {}).get("filled_quantity"),
            "avg_filled_price": (tracked or {}).get("avg_filled_price")}
