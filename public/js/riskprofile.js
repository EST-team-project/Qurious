/* #251: 로그인 확인 뒤 계정별로 읽는 이 브라우저의 투자 성향.
 * clientId는 /api/me가 반환하는 계정별 고유 식별자다. 공용 옛 값은 주인을 알 수 없어 옮기지 않는다.
 * 서버 저장·기기 간 동기화는 하지 않는다. 다른 계정으로 전환한 뒤 도착한 응답도 저장하지 않는다. */
const PREFIX = "robo_risk_profile:v1:";
const PROFILES = new Set(["conservative", "moderate", "aggressive"]);
const LEVELS = new Set(["안정형", "안정추구형", "위험중립형", "적극투자형", "공격투자형"]);
let context = null;
let memory = null;

function normalize(value) {
  if (!value || !PROFILES.has(value.risk_profile) || !LEVELS.has(value.level)
      || !Number.isInteger(value.score) || value.score < 0 || value.score > 35) return null;
  return {level: value.level, risk_profile: value.risk_profile, score: value.score};
}

export function setRiskProfileUser(clientId) {
  memory = null;
  context = typeof clientId === "string" && clientId.trim()
    ? {key: PREFIX + encodeURIComponent(clientId)} : null;
}

export function riskProfileContext() { return context; }

export function hasLegacyRiskProfile() {
  try { return Boolean(context && localStorage.getItem("robo_risk_profile")); } catch (_) { return false; }
}

export function readRiskProfile() {
  if (!context) return null;
  if (memory) return {...memory};
  try { return normalize(JSON.parse(localStorage.getItem(context.key) || "null")); }
  catch (_) { return null; }
}

/** saved: 브라우저 저장, memory: 현재 탭만, unavailable: 로그인 미확인·계정 전환·잘못된 값 */
export function saveRiskProfile(value, owner) {
  const profile = normalize(value);
  if (!context || owner !== context || !profile) return "unavailable";
  memory = profile;
  try { localStorage.setItem(context.key, JSON.stringify(profile)); return "saved"; }
  catch (_) { return "memory"; }
}
