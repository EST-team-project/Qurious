"""
한국투자증권 (KIS) Open API 클라이언트
공식 문서: https://apiportal.koreainvestment.com/
모의투자 지원: base_url = https://openapivts.koreainvestment.com:29443
실전투자:     base_url = https://openapi.koreainvestment.com:9443
"""
import asyncio
import httpx
from datetime import datetime, timedelta, timezone
from .base import (
    BrokerClient, TokenInfo, PriceInfo, AccountBalance, BalanceItem, FillInfo, FillSummary,
)

REAL_URL  = "https://openapi.koreainvestment.com:9443"
PAPER_URL = "https://openapivts.koreainvestment.com:29443"


class KISClient(BrokerClient):
    def __init__(self, app_key: str, app_secret: str, paper: bool = True):
        self.app_key    = app_key
        self.app_secret = app_secret
        self.base_url   = PAPER_URL if paper else REAL_URL
        self.paper      = paper
        self._token: str | None = None
        self._token_exp: datetime | None = None

    @staticmethod
    def _split_account(account_no: str) -> tuple[str, str]:
        """계좌번호를 종합계좌번호(8자리)와 계좌상품코드(2자리)로 가른다.

        KIS 는 이 둘을 `CANO` · `ACNT_PRDT_CD` 로 따로 받는다.
        `50201820-01` · `5020182001` 둘 다 받아들이고, 상품코드가 없으면
        `01`(종합위탁)로 본다.

        🔴 빈 칸을 보내면 조용히 실패하지 않는다 — 잔고 조회가 **HTTP 500** 으로
           떨어진다 (2026-09-20 모의계좌에서 확인). 이전에는 `account_no[8:]` 로
           잘라 8자리 계좌번호에서 빈 문자열이 나갔다.
        """
        digits = (account_no or "").replace("-", "").strip()
        if len(digits) >= 10:
            return digits[:8], digits[8:10]
        return digits[:8], "01"

    @staticmethod
    def _check(body: dict, what: str) -> dict:
        """KIS 응답의 성공 여부를 본다.

        🔴 **KIS 는 실패해도 HTTP 200 을 준다.** 성공 여부는 본문의 `rt_cd` 에 있고
           (`0` 이 성공), 이유는 `msg_cd` · `msg1` 에 담긴다. `raise_for_status()`
           만으로는 거부된 주문이 그대로 성공으로 올라간다.

           실제로 2026-09-20(일) 모의계좌에 낸 주문이
           `{"rt_cd":"1","msg_cd":"40100000","msg1":"모의투자 영업일이 아닙니다."}`
           로 거부됐는데, 화면에는 `{"ok": true}` 가 뜨고 "주문 완료" 알림까지 나갔다.
        """
        if str(body.get("rt_cd", "0")).strip() not in ("0", ""):
            msg = str(body.get("msg1", "")).strip()
            raise RuntimeError(f"KIS {what} 실패 [{body.get('msg_cd', '')}] {msg}".strip())
        return body

    def _headers(self, tr_id: str, extra: dict | None = None) -> dict:
        h = {
            "content-type":   "application/json; charset=utf-8",
            "authorization":  f"Bearer {self._token}",
            "appkey":         self.app_key,
            "appsecret":      self.app_secret,
            "tr_id":          tr_id,
            "custtype":       "P",
        }
        if extra:
            h.update(extra)
        return h

    async def get_token(self) -> TokenInfo:
        async with httpx.AsyncClient(verify=False, timeout=10) as cli:
            r = await cli.post(
                f"{self.base_url}/oauth2/tokenP",
                json={
                    "grant_type": "client_credentials",
                    "appkey":     self.app_key,
                    "appsecret":  self.app_secret,
                },
            )
            r.raise_for_status()
            d = r.json()
        self._token = d["access_token"]
        return TokenInfo(access_token=self._token, expires_in=d.get("expires_in", 86400))

    async def _ensure_token(self):
        if not self._token:
            await self.get_token()

    async def get_price(self, symbol: str) -> PriceInfo:
        await self._ensure_token()
        # 6자리 코드 (005930) → KIS는 종목코드만
        code = symbol.replace(".KS", "").replace(".KQ", "")
        async with httpx.AsyncClient(verify=False, timeout=10) as cli:
            r = await cli.get(
                f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
                headers=self._headers("FHKST01010100"),
                params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
            )
            r.raise_for_status()
            o = self._check(r.json(), "현재가 조회")["output"]
        return PriceInfo(
            symbol    = symbol,
            name      = o.get("hts_kor_isnm", ""),
            current   = float(o.get("stck_prpr", 0)),
            open      = float(o.get("stck_oprc", 0)),
            high      = float(o.get("stck_hgpr", 0)),
            low       = float(o.get("stck_lwpr", 0)),
            volume    = int(o.get("acml_vol", 0)),
            change    = float(o.get("prdy_vrss", 0)),
            change_pct= float(o.get("prdy_ctrt", 0)),
        )

    async def get_balance(self, account_no: str) -> AccountBalance:
        await self._ensure_token()
        cano, acnt_prdt = self._split_account(account_no)
        tr_id = "VTTC8434R" if self.paper else "TTTC8434R"
        async with httpx.AsyncClient(verify=False, timeout=10) as cli:
            r = await cli.get(
                f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
                headers=self._headers(tr_id),
                params={
                    "CANO":               cano,
                    "ACNT_PRDT_CD":       acnt_prdt,
                    "AFHR_FLPR_YN":       "N",
                    "OFL_YN":             "",
                    "INQR_DVSN":          "02",
                    "UNPR_DVSN":          "01",
                    "FUND_STTL_ICLD_YN":  "N",
                    "FNCG_AMT_AUTO_RDPT_YN": "N",
                    "PRCS_DVSN":          "01",
                    "CTX_AREA_FK100":     "",
                    "CTX_AREA_NK100":     "",
                },
            )
            r.raise_for_status()
            data = self._check(r.json(), "잔고 조회")

        holdings = []
        for h in data.get("output1", []):
            qty = int(h.get("hldg_qty", 0))
            if qty <= 0:
                continue
            avg   = float(h.get("pchs_avg_pric", 0))
            curr  = float(h.get("prpr", 0))
            eval_ = float(h.get("evlu_amt", 0))
            gain  = float(h.get("evlu_pfls_amt", 0))
            pct   = float(h.get("evlu_pfls_rt", 0))
            holdings.append(BalanceItem(
                symbol        = h.get("pdno", ""),
                name          = h.get("prdt_name", ""),
                quantity      = qty,
                avg_price     = avg,
                current_price = curr,
                eval_amount   = eval_,
                gain_loss     = gain,
                gain_pct      = pct,
            ))

        s2 = data.get("output2", [{}])[0]
        return AccountBalance(
            total_eval = float(s2.get("tot_evlu_amt", 0)),
            total_buy  = float(s2.get("pchs_amt_smtl_amt", 0)),
            total_gain = float(s2.get("evlu_pfls_smtl_amt", 0)),
            holdings   = holdings,
            cash       = float(s2.get("dnca_tot_amt", 0)),  # 예수금
        )

    async def place_order(
        self, account_no: str, symbol: str, side: str, quantity: int, price: float
    ) -> dict:
        await self._ensure_token()
        cano, acnt_prdt = self._split_account(account_no)
        code = symbol.replace(".KS", "").replace(".KQ", "")
        # 신 TR ID 를 쓴다. 구 TR(TTTC0802U 매수 · TTTC0801U 매도)은 KIS 스펙에
        # "구TR은 사전고지 없이 막힐 수 있으므로 반드시 신TR로 변경이용" 이라고 적혀 있다.
        #   (구) TTTC0802U 매수 → (신) TTTC0012U  ·  (구) TTTC0801U 매도 → (신) TTTC0011U
        # 모의투자는 접두사만 V 로 바뀐다 (VTTC0012U · VTTC0011U).
        if side == "buy":
            tr_id = "VTTC0012U" if self.paper else "TTTC0012U"
        else:
            tr_id = "VTTC0011U" if self.paper else "TTTC0011U"

        async with httpx.AsyncClient(verify=False, timeout=10) as cli:
            r = await cli.post(
                f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash",
                headers=self._headers(tr_id),
                json={
                    "CANO":         cano,
                    "ACNT_PRDT_CD": acnt_prdt,
                    "PDNO":         code,
                    "ORD_DVSN":     "00",   # 지정가
                    "ORD_QTY":      str(quantity),
                    "ORD_UNPR":     str(int(price)),
                    # 거래소를 KRX 로 못 박는다. 넥스트레이드(NXT) 출범 뒤로는 이 칸을
                    # 비우면 어느 거래소로 갈지 모르고, 위탁수수료 요율이 갈린다
                    # (뱅키스 온라인 KRX 0.0140527% vs NXT 0.0130527%).
                    # 우리 비용 계산이 KRX 요율을 기준으로 하므로 거래소를 고정한다.
                    "EXCG_ID_DVSN_CD": "KRX",
                },
            )
            r.raise_for_status()
        # rt_cd 를 반드시 본다 — 거부된 주문을 성공으로 넘기면 자동매매가
        # 있지도 않은 체결을 전제로 다음 판단을 한다.
        return self._check(r.json(), f"{side} 주문")

    async def get_daily_ohlcv(self, symbol: str, start: str, end: str) -> list[dict]:
        """일봉 OHLCV. start/end: YYYYMMDD"""
        await self._ensure_token()
        code = symbol.replace(".KS", "").replace(".KQ", "")
        async with httpx.AsyncClient(verify=False, timeout=10) as cli:
            r = await cli.get(
                f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-price",
                headers=self._headers("FHKST01010400"),
                params={
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD":          code,
                    "FID_PERIOD_DIV_CODE":     "D",
                    "FID_ORG_ADJ_PRC":         "0",
                    "FID_INPUT_DATE_1":         start,
                    "FID_INPUT_DATE_2":         end,
                },
            )
            r.raise_for_status()
            data = self._check(r.json(), "일봉 조회")
        out = []
        for row in data.get("output", []):
            out.append({
                "date":   row.get("stck_bsop_date", ""),
                "open":   float(row.get("stck_oprc", 0)),
                "high":   float(row.get("stck_hgpr", 0)),
                "low":    float(row.get("stck_lwpr", 0)),
                "close":  float(row.get("stck_clpr", 0)),
                "volume": int(row.get("acml_vol", 0)),
            })
        return out

    # ── 체결 조회 ──────────────────────────────────────────────────────
    # 주식일별주문체결조회는 **같은 URL 인데 TR ID 로 기간이 갈린다.**
    # 3개월 이내와 3개월 이전이 서로 다른 TR 이라, 한쪽만 알면 과거 체결을 못 본다.
    #   3개월 이내 : TTTC0081R (실전) · VTTC0081R (모의)
    #   3개월 이전 : CTSC9215R (실전) · VTSC9215R (모의)
    # 근거: KIS 공식 예제 저장소 koreainvestment/open-trading-api
    #       examples_llm/domestic_stock/inquire_daily_ccld/inquire_daily_ccld.py
    _CCLD_RECENT_DAYS = 90  # 🟡 "3개월" 의 근사값. 경계에서는 넉넉한 쪽(과거 TR)을 쓴다

    @staticmethod
    def _parse_num(value, cast=float, default=0):
        """KIS 는 빈 문자열·공백을 숫자 칸에 그대로 담아 보낸다."""
        try:
            s = str(value).strip().replace(",", "")
            return cast(s) if s else cast(default)
        except (TypeError, ValueError):
            return cast(default)

    async def get_daily_fills(
        self, account_no: str, start: str, end: str, symbol: str | None = None
    ) -> list[FillInfo]:
        """기간 내 주문·체결 내역 (요약은 버린다 — 추상 인터페이스 호환용)."""
        fills, _ = await self.get_daily_fills_with_summary(account_no, start, end, symbol)
        return fills

    async def get_daily_fills_with_summary(
        self, account_no: str, start: str, end: str, symbol: str | None = None
    ) -> tuple[list[FillInfo], FillSummary | None]:
        """기간 내 주문·체결 내역을 **요약 한 줄까지** 증권사에서 그대로 받아 온다.

        우리가 낸 주문이 `orders` 테이블에 없어도 여기서 되찾을 수 있다 —
        실전 주문 경로(`stocks.py` · `auto_trade.py`)는 증권사에 주문만 내고
        DB 에는 아무것도 남기지 않기 때문이다.

        응답이 두 칸으로 나뉜다
        ----------------------
        - `output1` : 주문별 목록 → `FillInfo` 들
        - `output2` : 조회 범위 전체 합계 → `FillSummary`

        🔴 **제비용 칸(`prsm_tlex_smtl`)은 `output2` 에 있다.** 2026-09-20 까지
           이 함수는 `output1` 만 모으고 `output2` 를 버렸다. 그래서 체결이 있어도
           대조할 값이 오지 않았다. 실계좌로 바꿔도 결과는 같았을 것이다 —
           버리는 쪽이 코드였기 때문이다.

        연속조회에서는 **마지막 쪽의 `output2`** 를 쓴다. KIS 는 쪽마다 그 시점까지의
        누적 합계를 주므로, 중간 쪽 값을 쓰면 일부만 더한 값이 된다.
        """
        await self._ensure_token()
        cano, acnt_prdt = self._split_account(account_no)

        # 조회 시작일이 3개월보다 오래됐으면 과거 TR 로 간다.
        # 경계를 넘나드는 기간을 한 번에 조회하면 KIS 가 한쪽만 돌려주므로,
        # 호출하는 쪽에서 기간을 나눠 두 번 부르는 것이 맞다 (여기서는 나누지 않는다).
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self._CCLD_RECENT_DAYS)).strftime("%Y%m%d")
        old = start < cutoff
        if self.paper:
            tr_id = "VTSC9215R" if old else "VTTC0081R"
        else:
            tr_id = "CTSC9215R" if old else "TTTC0081R"

        params = {
            "CANO":            cano,
            "ACNT_PRDT_CD":    acnt_prdt,
            "INQR_STRT_DT":    start,
            "INQR_END_DT":     end,
            "SLL_BUY_DVSN_CD": "00",   # 00 전체 / 01 매도 / 02 매수
            "INQR_DVSN":       "00",   # 00 역순 / 01 정순
            "PDNO":            (symbol or "").replace(".KS", "").replace(".KQ", ""),
            "CCLD_DVSN":       "00",   # 00 전체 — 미체결까지 받아 두고 여기서 거른다
            "ORD_GNO_BRNO":    "",
            "ODNO":            "",
            "INQR_DVSN_3":     "00",   # 00 전체 (현금·신용·담보…)
            "INQR_DVSN_1":     "",
            "EXCG_ID_DVSN_CD": "KRX",  # KRX / NXT / SOR / ALL
            "CTX_AREA_FK100":  "",
            "CTX_AREA_NK100":  "",
        }

        rows: list[dict] = []
        summary_raw: dict | None = None
        tr_cont = ""
        async with httpx.AsyncClient(verify=False, timeout=15) as cli:
            for page in range(20):  # 무한루프 방지. 20쪽이면 하루 체결로는 충분하다
                r = await cli.get(
                    f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
                    headers=self._headers(tr_id, {"tr_cont": tr_cont}),
                    params=params,
                )
                r.raise_for_status()
                body = self._check(r.json(), "체결 조회")
                rows.extend(body.get("output1") or [])
                # output2 는 요약 한 줄이다. 객체로 올 수도, 1행 배열로 올 수도 있어
                # 둘 다 받는다. 체결이 0건이어도 이 칸은 (0 으로 채워져) 온다 —
                # 그래서 **주문을 내지 않고도 칸의 위치를 확인할 수 있다.**
                o2 = body.get("output2")
                if isinstance(o2, list):
                    o2 = o2[0] if o2 else None
                if isinstance(o2, dict) and o2:
                    summary_raw = o2  # 마지막 쪽이 최종 누적값

                # 연속조회: 응답 헤더 tr_cont 가 M/F 면 다음 쪽이 있다.
                nxt = (r.headers.get("tr_cont") or "").strip().upper()
                if nxt not in ("M", "F"):
                    break
                params["CTX_AREA_FK100"] = (body.get("ctx_area_fk100") or "").strip()
                params["CTX_AREA_NK100"] = (body.get("ctx_area_nk100") or "").strip()
                tr_cont = "N"
                # 모의투자에도 초당 유량 제한(EGW00201)이 걸린다 — 쪽 사이를 띄운다
                await asyncio.sleep(3)

        out: list[FillInfo] = []
        for row in rows:
            # 01 매도 · 02 매수. KIS 는 코드로만 주고 이름 칸(sll_buy_dvsn_cd_name)은
            # "현금매수" 처럼 수식어가 붙어 있어 코드로 판단한다.
            side = "sell" if str(row.get("sll_buy_dvsn_cd", "")).strip() == "01" else "buy"
            # 🟡 prsm_tlex_smtl = 추정제비용합계. 강사님 카탈로그의 한글 라벨은 이 칸을
            #    "총체결금액" 이라 적어 두었으나 필드명(prsm 추정 · tlex 제비용 · smtl 합계)과
            #    어긋난다. 라벨이 아니라 필드명을 따르고, 원문을 raw 에 남겨 둔다.
            # 🔴 이 칸은 실제로는 output1(주문별)이 아니라 output2(요약)에 있다.
            #    주문별로도 올 경우를 대비해 계속 읽지만, 평소에는 None 이 되고
            #    대조는 `FillSummary.total_fees` 로 한다.
            fee_raw = str(row.get("prsm_tlex_smtl", "")).strip()
            out.append(FillInfo(
                broker_order_id = str(row.get("odno", "")).strip(),
                symbol          = str(row.get("pdno", "")).strip(),
                name            = str(row.get("prdt_name", "")).strip(),
                side            = side,
                order_date      = str(row.get("ord_dt", "")).strip(),
                order_time      = str(row.get("ord_tmd", "")).strip(),
                order_quantity  = self._parse_num(row.get("ord_qty"), int),
                order_price     = self._parse_num(row.get("ord_unpr")),
                filled_quantity = self._parse_num(row.get("tot_ccld_qty"), int),
                avg_fill_price  = self._parse_num(row.get("avg_prvs")),
                gross_amount    = self._parse_num(row.get("tot_ccld_amt")),
                # 빈 칸이면 None (알려주지 않음) — 0.0 (0원을 뗌) 과 구분한다
                total_fees      = self._parse_num(fee_raw) if fee_raw else None,
                cancelled       = str(row.get("cncl_yn", "")).strip().upper() == "Y",
                # KIS 응답의 이 칸만 카멜과 스네이크가 섞여 있다 (excg_id_dvsn_Cd)
                exchange        = (str(row.get("excg_id_dvsn_Cd") or row.get("excg_id_dvsn_cd") or "").strip() or None),
                raw             = row,
            ))

        summary = None
        if summary_raw is not None:
            s_fee = str(summary_raw.get("prsm_tlex_smtl", "")).strip()
            summary = FillSummary(
                total_order_quantity  = self._parse_num(summary_raw.get("tot_ord_qty"), int),
                total_filled_quantity = self._parse_num(summary_raw.get("tot_ccld_qty"), int),
                avg_buy_price         = self._parse_num(summary_raw.get("pchs_avg_pric")),
                gross_amount          = self._parse_num(summary_raw.get("tot_ccld_amt")),
                # 빈 칸이면 None (알려주지 않음) — 0.0 (0원을 뗌) 과 구분한다
                total_fees            = self._parse_num(s_fee) if s_fee else None,
                raw                   = summary_raw,
            )
        return out, summary
