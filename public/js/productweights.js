/* 투자 성향별 상품 안내 — 자산 배분 비중 고르기(#179 계약을 한 곳에) (2026-10-16)
 *
 * 계약(오준영 님 #179 답글 02 · 2026-10-14 · 서버 응답 모델 app/routes/ml.py LatestAllocationResponse · AllocationWeightsResponse):
 *   1. 저장본 먼저 — GET /api/ml/robo/allocation/latest(API-ML-12) = 본인의 마지막 성공 계산 한 건.
 *      조회가 다시 계산하거나 저장본을 바꾸지 않는다.
 *   2. 404 일 때만 기본 비중 — GET /api/ml/robo/weights(API-ML-11) · 이 브라우저의 진단 성향 · 투자 기간 3년.
 *      진단 성향도 없으면 비중 없이 「진단하기」 로 안내한다(state "none").
 *   3. 그 밖 오류(연결 실패 0 · 로그인 401 · 서버 5xx · 입력 422)는 「저장본 없음」 이 아니다 — 기본 비중으로 메우지 않고
 *      까닭을 그대로 돌려준다(말없는 fallback 금지). 화면은 그 까닭과 「다시 불러오기」 를 보인다.
 *   4. handoff 가 null 이어도 비중은 읽는다 — 리밸런싱으로 넘기지 못할 뿐 같은 계산 결과다(여기서는 handoff 를 보지 않는다).
 *   5. 지금 진단 성향과 저장본 성향이 다르면 저장본을 그대로 쓰고 differs 만 켠다 — 다시 계산은 자산 배분 화면(오준영 님) 몫.
 * 무거운 배분 계산(POST /api/ml/robo/allocation)은 부르지 않는다.
 *
 * DOM · import 가 없다 — 시험(TC-PD-05)이 node 로 이 함수를 그대로 돌린다(api 를 갈아 끼워 200 · 404 · 0 · 401 · 500 을 본다).
 * 응답을 읽는 변수 이름은 products.js 머리말 규칙을 따른다 — sa 저장본 응답 · al 기본 비중 응답
 * (TC-PD-01 이 「변수.칸」 을 모아 서버 응답 칸과 맞댄다 — 칸은 줄여 쓰지 않고 sa.result.칸 꼴로 읽는다).
 */
export const DEFAULT_HORIZON_YEARS = 3;

/**
 * 돌려주는 꼴 — 화면(products.js)은 이것만 읽고 다시 판정하지 않는다.
 *   { state: "ok", source: "saved" | "default", risk_profile, horizon_years, allocations, saved_at, differs }
 *   { state: "none" }                                       저장본 없음(404) · 진단 성향도 없음
 *   { state: "error", step: "saved" | "default", status, message }
 * @param {(path: string) => Promise<object>} api  common.js 의 api — 오류에 status 를 붙여 던진다(연결 실패 0)
 * @param {{risk_profile?: string} | null} profile  이 브라우저의 진단 결과(localStorage robo_risk_profile)
 */
export async function resolveWeights(api, profile) {
  let sa = null;
  try {
    sa = await api("/api/ml/robo/allocation/latest");
  } catch (e) {
    if (e?.status !== 404) return failed("saved", e);
  }
  if (sa) {
    return {
      state: "ok", source: "saved", saved_at: sa.saved_at,
      risk_profile: sa.result.risk_profile, horizon_years: sa.result.horizon_years, allocations: sa.result.allocations,
      differs: Boolean(profile?.risk_profile) && profile.risk_profile !== sa.result.risk_profile,
    };
  }
  if (!profile?.risk_profile) return { state: "none" };
  try {
    const al = await api(`/api/ml/robo/weights?risk_profile=${encodeURIComponent(profile.risk_profile)}&horizon_years=${DEFAULT_HORIZON_YEARS}`);
    return {
      state: "ok", source: "default", saved_at: null,
      risk_profile: al.risk_profile, horizon_years: al.horizon_years, allocations: al.allocations, differs: false,
    };
  } catch (e) {
    return failed("default", e);
  }
}

function failed(step, e) {
  return { state: "error", step, status: typeof e?.status === "number" ? e.status : null, message: e?.message || "알 수 없는 오류" };
}
