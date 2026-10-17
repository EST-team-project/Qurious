/* 투자 정보 리서치 — 목록 줄 묶기 · 종목 칸 판단 · 스위치 글 (DOM 없는 판단 모듈 · 2026-10-17)
 *
 * research.js 가 그리기 전에 부른다. 화면 결정(Figma 「투자 정보 리서치」 03-2 — 설계 A · 세 안 공통 · 2026-10-17):
 *   ① 같은 제목은 한 줄로 묶는다 — 뉴스만. 공시는 회사마다 같은 보고서 이름(「주식등의대량보유상황보고서」)이라 묶으면 다른
 *      회사의 공시가 사라진다. 묶음은 처음(가장 최근) 나온 자리에 두고, 쪽 넘기기는 서버 그대로다(「더 보기」 로 받은 줄까지
 *      다시 묶는다 — 지난 목록과 같은 쪽 넘기기를 지킨다).
 *   ② 제목이 사이트 이름뿐인 기사(서버가 `site_name_title` 로 알림 — 규칙은 app/services/data_search.py 한 곳)는 목록 줄에서
 *      빼 받은 목록 끝에 게시처마다 한 묶음으로 모은다(모의투자 점검 L11 — 첫 화면 맨 위 열 줄 가운데 여섯이 「KBS 뉴스」).
 *   ③ 종목 칸에 친 글 — 이름이나 코드가 정확히 같은 것 하나면 그 종목, 여럿이면 제안 목록, 없으면 「찾지 못했습니다」
 *      (점검 <표 2> — 치자마자 Enter 는 제안 목록이 뜨기 전이라 아무 일도 없었다).
 *   ④ 스위치 글 「이름표 없는 기사까지 보기 (n건 숨김)」 — n 은 서버 facets.untagged 의 합(화면이 다시 세지 않는다).
 * 판단을 이 파일에 두어 Node 로 시험한다(tests/test_research_screen.py TC-RS-07 ~ 09).
 */

/** 같은 제목인지 볼 열쇠 — 앞뒤 빈칸 · 겹친 빈칸만 접는다(글자는 바꾸지 않는다 — 「- 국민일보」 같은 꼬리도 그대로) */
export function researchTitleKey(title) {
  return String(title || "").replace(/\s+/g, " ").trim();
}

/** 목록 줄 묶기 — { rows: [{ it, same: [it…] }], siteGroups: [{ title, publisher, items: [it…] }] }
 *  rows 는 받은 차례 그대로(묶인 줄은 처음 자리에) · siteGroups 는 화면이 목록 끝에 그린다. */
export function groupResearchRows(items) {
  const rows = [];
  const byTitle = new Map();
  const sites = new Map();
  for (const it of items || []) {
    if (it.site_name_title) {
      const publisher = (it.extra || {}).publisher || "";
      const title = researchTitleKey(it.title);
      const key = `${publisher}\u0000${title}`;
      if (!sites.has(key)) sites.set(key, { title, publisher, items: [] });
      sites.get(key).items.push(it);
      continue;
    }
    if (it.kind === "news") {
      const key = researchTitleKey(it.title);
      const row = byTitle.get(key);
      if (row) { row.same.push(it); continue; }
      const fresh = { it, same: [] };
      byTitle.set(key, fresh);
      rows.push(fresh);
      continue;
    }
    rows.push({ it, same: [] });
  }
  return { rows, siteGroups: [...sites.values()] };
}

/** 종목 칸 판단 — rows 는 국내 종목 후보([{ code, name, market }]) · q 는 친 글.
 *  { kind: "pick", code, name } · { kind: "list" }(여럿 · 정확히 같은 것이 없음) · { kind: "none" } · { kind: "empty" } */
export function resolveStockQuery(rows, q) {
  const want = String(q || "").trim();
  if (!want) return { kind: "empty" };
  const list = rows || [];
  if (!list.length) return { kind: "none" };
  const fold = s => String(s || "").replace(/\s+/g, "").toUpperCase();
  const exact = list.filter(x => fold(x.name) === fold(want) || fold(x.code) === fold(want));
  if (exact.length === 1) return { kind: "pick", code: exact[0].code, name: exact[0].name };
  return { kind: "list" };
}

/** 스위치 글 — 끄면(투자 관련만) 「… (n건 숨김)」 · 켜면 「… (n건 함께)」 · n 은 서버 facets.untagged 의 합(0 이면 화면이 감춘다) */
export function researchSwitchText(tagged, untagged) {
  const n = Object.values(untagged || {}).reduce((a, v) => a + (Number(v) || 0), 0);
  return { n, text: `이름표 없는 기사까지 보기 (${n.toLocaleString("ko-KR")}건 ${tagged ? "숨김" : "함께"})` };
}
