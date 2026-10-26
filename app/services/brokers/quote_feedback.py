"""증권사 조회 실패를 사용자 안내로 바꾼다. 예외 원문·URL·인증 정보는 반환하지 않는다."""
import logging

import httpx

from .kis_token import KISTokenError

logger = logging.getLogger(__name__)
KEY_ERRORS = frozenset({"EGW00102", "EGW00103", "EGW00104", "EGW00105"})


class BrokerQuoteError(RuntimeError):
    def __init__(self, vendor_code=None):
        super().__init__("증권사 현재가 응답을 확인하지 못했습니다.")
        self.vendor_code = vendor_code


class BrokerBalanceError(RuntimeError):
    def __init__(self, vendor_code=None):
        super().__init__("증권사 잔고 응답을 확인하지 못했습니다.")
        self.vendor_code = vendor_code


def quote_failure(exc: Exception) -> dict:
    return _read_failure(exc, scope="quote", label="현재가", prefix="QUOTE")


def balance_failure(exc: Exception) -> dict:
    return _read_failure(exc, scope="balance", label="잔고", prefix="BALANCE")


def _read_failure(exc: Exception, *, scope: str, label: str, prefix: str) -> dict:
    code = getattr(exc, "code", None)
    vendor = getattr(exc, "vendor_code", None)
    status = getattr(exc, "upstream_status", None)
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        try:
            body = exc.response.json()
            if isinstance(body, dict):
                vendor = body.get("error_code") or body.get("msg_cd")
        except ValueError:
            pass
    # 문자열 검색으로 403을 토큰 한도로 단정하지 않는다.
    if code == "KIS_TOKEN_RATE_LIMIT" or vendor == "EGW00133":
        public_code = "TOKEN_RATE_LIMIT"
        message = "접속 토큰 발급이 제한됐거나 다른 요청의 발급을 기다리고 있습니다."
        hint = "1분 뒤 다시 눌러 주세요. 자동매매나 다른 조회의 토큰 발급과 겹칠 수 있습니다."
    elif isinstance(vendor, str) and vendor in KEY_ERRORS:
        public_code = "INVALID_CREDENTIALS"
        message = "증권사가 App Key 또는 App Secret을 확인하지 못했습니다."
        hint = "모의·실전 환경에 맞는 App Key와 App Secret인지 확인하고 저장한 뒤 다시 시도해 주세요."
    elif status in (401, 403):
        public_code = "BROKER_AUTH_REJECTED"
        message = "증권사가 인증 또는 접근 권한을 거절했습니다."
        hint = "저장한 App Key·App Secret, 모의·실전 환경과 API 이용 권한을 확인해 주세요. 이 응답만으로 토큰 발급 제한이라고 단정할 수 없습니다."
    elif status == 429 or vendor == "EGW00201":
        public_code = f"{prefix}_RATE_LIMIT"
        message = "증권사 조회 요청이 일시적으로 제한됐습니다."
        hint = "연속 조회를 멈추고 잠시 뒤 다시 눌러 주세요."
    elif isinstance(exc, KISTokenError):
        public_code = "TOKEN_UNAVAILABLE"
        message = "접속 토큰을 준비하지 못했습니다."
        hint = "잠시 뒤 다시 시도하고, 계속되면 관리자에게 연결 상태 확인을 요청해 주세요."
    elif isinstance(exc, httpx.TimeoutException):
        public_code = f"{prefix}_TIMEOUT"
        message = f"증권사의 {label} 응답이 늦어 확인하지 못했습니다."
        hint = "잠시 뒤 다시 눌러 주세요. 계속되면 증권사 서비스 상태를 확인해 주세요."
    else:
        public_code = f"{prefix}_UNAVAILABLE"
        message = f"{label} 조회를 완료하지 못했습니다."
        hint = "잠시 뒤 다시 시도하고, 계속되면 관리자에게 연결 상태 확인을 요청해 주세요."
    # 요청 URL·헤더·본문이나 예외 문자열은 로그에도 남기지 않는다.
    known_vendor = vendor if isinstance(vendor, str) and vendor in KEY_ERRORS | {"EGW00133", "EGW00201"} else "other"
    logger.warning("Broker %s failed: code=%s exception=%s upstream_status=%s vendor=%s",
                   scope, public_code, type(exc).__name__, status, known_vendor)
    return {"code": public_code, "message": message, "hint": hint,
            "scope": scope, "account_verified": False,
            "retry_after_seconds": 60 if public_code == "TOKEN_RATE_LIMIT" else None}
