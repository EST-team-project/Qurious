"""주소 검사 — 자료를 직접 받기 전에 「받아도 되는 주소인가」 를 본다(크롤링 세 화면 · 설계 2 · 2026-10-07).

왜 필요한가
-----------
수동 크롤링(`POST /api/ingest/crawl/url` · `/async`)은 로그인만 하면 **아무 주소나** 받았다. 서버가 대신 요청을 보내므로
`http://127.0.0.1:…` · `http://169.254.169.254/…`(클라우드 메타데이터) 같은 내부 주소도 부를 수 있었고(서버 측 요청 위조 ·
SSRF — 2026-09-17 분석 A11), robots.txt 가 전면 금지인 네이버 금융도 긁었다. 결정 ①(네이버 긁기는 「막음」 예시로만)과
설계 2(허용 목록에 있는 출처만)를 서버에서 지킨다.

차례대로 보고 처음 걸린 곳에서 멈춘다
  1. 형식    http · https · 기본 포트(80 · 443)만 · 주소 안의 계정 정보(`user@host`) 금지
  2. 내부망  호스트가 가리키는 **모든** IP 가 공인 주소여야 한다 — 사설 · 루프백 · 링크 로컬 · 예약 · 멀티캐스트 · 미지정이면 막는다.
            IP 를 바로 적은 주소도 같다. 이름을 풀지 못하면 막는다.
  3. 허용 목록 이용 조건을 확인한 출처(``ALLOWED``)만. 목록 밖은 막는다 — robots.txt 를 받으러 가지도 않는다.
  4. robots  그 출처의 robots.txt 가 이 경로를 금지하면 막는다. robots.txt 를 받지 못하면(없음 · 시간 초과) 허용 목록 판정을 따른다.

리다이렉트 — 받는 길(`services/crawl.py` 의 `crawl_url` · `follow_redirects=True`)은 처음 주소만 검사하면 허용된 곳이
내부망 주소로 돌려보낼 때 그대로 따라간다. 받은 **뒤** 마지막 주소를 다시 보면 내부망 요청은 이미 나간 뒤라 늦다 → httpx 요청
훅(``guard_request``)이 처음 주소와 리다이렉트로 옮겨 갈 주소마다 **보내기 전에** 같은 네 검사를 하고, 막히면 ``BlockedHop``(400)
으로 멈춘다(2026-10-08). 크롤러가 오류를 삼켜 「0청크 · 성공」 으로 끝나지 않게 그 예외는 다시 던진다.

남는 위험 — 검사한 뒤 실제로 받을 때 DNS 가 다른 주소를 줄 수 있다(DNS 재바인딩). 허용 목록이 공공기관 몇 곳뿐이라 받아들인다
(훅이 보내기 직전에 이름을 다시 풀어 틈을 좁힐 뿐 없애지는 못한다).

네트워크 — 이름 풀기와 robots.txt 받기는 함수를 바꿔 끼울 수 있다(시험은 네트워크 없이 돈다).
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from fastapi import HTTPException

#: 받아도 되는 출처 — 호스트 이름이 **정확히** 같아야 한다(하위 도메인도 따로 적는다). 이용 조건 근거는
#: docs/조사/공시-재무-뉴스-이용조건-조사.md · 정책브리핑은 기사마다 공공누리 유형을 따로 본다.
ALLOWED: dict[str, str] = {
    "opendart.fss.or.kr": "전자공시 OpenAPI",
    "dart.fss.or.kr": "전자공시 원문",
    "www.korea.kr": "정책브리핑 — 기사마다 공공누리 유형 확인",
    "apis.data.go.kr": "공공데이터포털",
    "ecos.bok.or.kr": "한국은행 경제통계",
}

#: 화면에 「막음」 예시로 보이는 출처(결정 ①) — 목록 밖이라 어차피 막히고, 까닭을 함께 보인다.
BLOCKED_EXAMPLES: dict[str, str] = {
    "finance.naver.com": "robots.txt 전면 금지",
}

USER_AGENT = "Mozilla/5.0 (compatible; FinAgent/1.0)"   # services/crawl.py 와 같은 이름 — robots 판정도 이 이름으로
ROBOTS_TIMEOUT = 5.0

Resolver = Callable[[str], list[str]]
RobotsFetcher = Callable[[str], str | None]


def _resolve(host: str) -> list[str]:
    """호스트가 가리키는 IP 전부(IPv4 · IPv6)."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({i[4][0] for i in infos})


def _fetch_robots(origin: str) -> str | None:
    """robots.txt 본문. 없거나(4xx) 받지 못하면 None — 그때는 허용 목록 판정을 따른다."""
    try:
        r = httpx.get(origin + "/robots.txt", timeout=ROBOTS_TIMEOUT, follow_redirects=False,
                      headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError:
        return None
    return r.text if r.status_code == 200 else None


def _bad_ip(ip: str) -> str | None:
    a = ipaddress.ip_address(ip.split("%", 1)[0])
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    for flag, why in (("is_loopback", "루프백"), ("is_private", "사설"), ("is_link_local", "링크 로컬"),
                      ("is_multicast", "멀티캐스트"), ("is_reserved", "예약"), ("is_unspecified", "미지정")):
        if getattr(a, flag):
            return f"{why} 주소 {a}"
    if not a.is_global:                                  # 위 이름에 없는 비공인 대역(100.64.0.0/10 공유 주소 등)
        return f"공인 주소가 아님 {a}"
    return None


def check(url: str, *, resolve: Resolver | None = None, fetch_robots: RobotsFetcher | None = None) -> dict:
    """주소 하나를 검사한다 — {url, host, ok, verdict, reason, source, checks[]}.

    이름 풀기 · robots 받기는 부를 때 모듈의 함수를 찾는다 — 시험이 바꿔 끼우면 라우트를 거친 검사도 네트워크 없이 돈다.
    """
    resolve = resolve or _resolve
    fetch_robots = fetch_robots or _fetch_robots
    checks: list[dict] = []
    out = {"url": url, "host": "", "ok": False, "verdict": "막음", "reason": "", "source": "", "checks": checks}

    def stop(name: str, reason: str) -> dict:
        checks.append({"name": name, "ok": False, "note": reason})
        out["reason"] = reason
        return out

    s = (url or "").strip()
    try:
        u = urlsplit(s)
        port = u.port
    except ValueError:
        return stop("형식", "주소 꼴이 아니다")
    host = (u.hostname or "").rstrip(".").lower()
    out["host"] = host
    if u.scheme not in ("http", "https") or not host:
        return stop("형식", "http · https 주소만 받는다")
    if u.username or u.password:
        return stop("형식", "주소 안에 계정 정보를 넣을 수 없다")
    if port not in (None, 80, 443):
        return stop("형식", f"기본 포트(80 · 443)만 — {port}")
    checks.append({"name": "형식", "ok": True, "note": u.scheme})

    try:
        ips = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            ips = resolve(host)
        except OSError:
            return stop("내부망", "주소를 풀 수 없다(이름 풀이 실패)")
    bad = [w for w in (_bad_ip(ip) for ip in ips) if w]
    if not ips or bad:
        return stop("내부망", "내부망 주소는 받지 않는다 — " + (", ".join(bad) or "가리키는 IP 없음"))
    checks.append({"name": "내부망", "ok": True, "note": ", ".join(ips[:3]) + (" …" if len(ips) > 3 else "")})

    if host not in ALLOWED:
        extra = BLOCKED_EXAMPLES.get(host)
        return stop("허용 목록", "허용 목록 밖" + (f" — {extra}" if extra else ""))
    out["source"] = ALLOWED[host]
    checks.append({"name": "허용 목록", "ok": True, "note": ALLOWED[host]})

    origin = f"{u.scheme}://{u.netloc.split('@')[-1]}"
    text = fetch_robots(origin)
    if text is None:
        checks.append({"name": "robots", "ok": True, "note": "robots.txt 없음 · 받지 못함 — 허용 목록을 따른다"})
    else:
        rp = RobotFileParser()
        rp.parse(text.splitlines())
        if not rp.can_fetch(USER_AGENT, s):
            return stop("robots", "robots.txt 가 이 경로를 금지한다")
        checks.append({"name": "robots", "ok": True, "note": "robots.txt 가 허용"})
    out.update(ok=True, verdict="허용", reason="허용 목록 · 내부망 · robots 를 지났다")
    return out


async def ensure_allowed(url: str) -> dict:
    """라우트에서 부르는 한 줄 — 막히면 400(까닭 · 허용 목록을 담은 객체), 지나면 검사 결과를 돌려준다."""
    v = await asyncio.to_thread(check, url)
    if not v["ok"]:
        raise HTTPException(400, {"message": f"받을 수 없는 주소 — {v['reason']}",
                                  "hint": "허용 목록: " + " · ".join(ALLOWED)})
    return v


class BlockedHop(HTTPException):
    """리다이렉트로 옮겨 갈(또는 처음) 주소가 검사에 막혔다 — 그 주소로는 요청을 보내지 않았다.

    HTTPException(400) 이라 라우트 안에서 올라오면 그대로 400 이 된다(라우트가 따로 잡지 않아도 된다).
    """

    def __init__(self, url: str, verdict: dict):
        self.url, self.verdict = url, verdict
        super().__init__(400, {"message": f"리다이렉트로 옮겨 간 주소를 받을 수 없다 — {verdict['reason']}",
                               "url": url, "hint": "허용 목록: " + " · ".join(ALLOWED)})


async def guard_request(request: httpx.Request) -> None:
    """httpx 요청 훅 — `AsyncClient(event_hooks={"request": [guard_request]})` 로 건다.

    httpx 는 리다이렉트를 따라갈 때 새 요청마다 이 훅을 **보내기 전에** 부른다. 그래서 허용된 곳이 내부망 · 목록 밖으로
    돌려보내도 그 요청은 나가지 않는다. 처음 요청도 다시 본다 — 라우트의 검사와 실제 연결 사이의 틈을 좁힌다.
    """
    url = str(request.url)
    v = await asyncio.to_thread(check, url)
    if not v["ok"]:
        raise BlockedHop(url, v)


def rules() -> dict:
    """화면의 「허용 목록에 있는 곳만」 표 — 허용 출처와 막음 예시 · 내부망 줄."""
    return {
        "allowed": [{"host": h, "label": v, "verdict": "허용"} for h, v in ALLOWED.items()],
        "blocked": [{"host": h, "label": v, "verdict": "막음"} for h, v in BLOCKED_EXAMPLES.items()]
                   + [{"host": "내부망 주소", "label": "127.0.0.1 · 10.x · 192.168.x 같은 사설 주소", "verdict": "막음"}],
        "order": ["형식", "내부망", "허용 목록", "robots"],
    }
