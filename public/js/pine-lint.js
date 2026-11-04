/* Pine Script v6 간이 문법 점검 — 커스텀 인디케이터 화면이 만든 코드를 보여 주기 전에 훑는다 (2026-11-04 · D7)
 *
 * 강사님 lumina-invest 의 pine-lint.js(checkPineV6)를 읽고 우리 규칙에 맞게 다시 썼다 — 복사가 아니다.
 * 달라진 곳: ① 확실한 것만 「오류」 · 추정은 「경고」 로 나눴다(강사님은 전부 오류) ② 문자열 안의 글자는 보지 않는다
 *  ③ 템플릿 치환이 안 된 `${…}` · JS 값(undefined · Math.)이 코드에 새는 것을 잡는다(우리 생성기가 문자열 템플릿이라)
 *  ④ v6 에서 and/or 가 단락 평가라 오른쪽의 ta.*() 가 건너뛰어질 수 있는 곳을 경고한다.
 *
 * 이 점검은 TradingView 컴파일러를 대신하지 않는다 — 통과해도 컴파일이 된다는 뜻이 아니고,
 * 의심스러우면 경고로만 말한다. 기준: https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/
 *
 * 아무것도 가져오지 않는다(DOM · 서버 없음) — 시험이 node 로 그대로 불러 돌린다.
 */

const TWO_CHAR_OPS = [":=", "=>", "==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%="];
const CLOSE_TO_OPEN = { ")": "(", "]": "[", "}": "{" };
// 뒤에 식이 없으면 확실히 문법 오류인 연산자 — `<` · `>` 는 제네릭(array<float>)의 닫는 꺾쇠일 수 있어 따로 본다
const BINARY_OPS = ["+", "-", "*", "/", "and", "or", "==", "!="];
const ASSIGN_OPS = ["=", ":=", "+=", "-="];
const WRONG_CHARS = ["{", "}", ";", "@", "`"];

/** 소스 글자를 (낱말 · 줄 · 열) 로 쪼갠다. 주석은 버리고 //@version 만 따로 모은다. */
function tokenize(source) {
  const tokens = [], versions = [], diagnostics = [];
  let i = 0, line = 1, column = 1;
  const advance = () => { if (source[i++] === "\n") { line++; column = 1; } else column++; };
  const here = () => ({ line, column, offset: i });
  const add = (at, message, severity = "error") => diagnostics.push({ line: at.line, column: at.column, message, severity });

  while (i < source.length) {
    const c = source[i], start = here();
    if (/\s/.test(c)) { advance(); continue; }

    if (source.startsWith("//", i)) {                      // 주석 — 줄 끝까지
      const end = source.indexOf("\n", i);
      const comment = source.slice(i, end < 0 ? source.length : end);
      const version = comment.match(/^\/\/@version\s*=\s*(\d+)\s*$/);
      if (version) versions.push({ ...start, version: Number(version[1]) });
      else if (/^\/\/@version\b/.test(comment)) add(start, "버전 선언 형식은 //@version=6 입니다.");
      while (i < source.length && source[i] !== "\n") advance();
      continue;
    }

    if (c === '"' || c === "'") {                          // 문자열 — Pine 에는 따옴표 세 개짜리 글자 상자가 없다
      advance();
      let closed = false, crossedLine = false;
      while (i < source.length) {
        if (source[i] === c) { advance(); closed = true; break; }
        if (source[i] === "\\") { advance(); if (i < source.length) advance(); continue; }
        if (source[i] === "\n") crossedLine = true;
        advance();
      }
      if (!closed) add(start, "문자열의 닫는 따옴표가 없습니다.");
      else if (crossedLine) add(start, "문자열이 줄을 넘어갑니다 — 닫는 따옴표 위치를 확인하세요.", "warning");
      tokens.push({ ...start, text: source.slice(start.offset, i), kind: "string" });
      continue;
    }

    if (/[a-zA-Z_]/.test(c)) {                             // 낱말 — 점으로 이은 이름(ta.sma)은 한 낱말
      while (i < source.length && /[a-zA-Z0-9_.]/.test(source[i])) advance();
      tokens.push({ ...start, text: source.slice(start.offset, i), kind: "identifier" });
      continue;
    }

    if (/\d/.test(c)) {                                    // 숫자 — 1e-5 같은 지수 꼴까지
      while (i < source.length && /[\d.]/.test(source[i])) advance();
      if (/[eE]/.test(source[i] || "") && /^[eE][+-]?\d/.test(source.slice(i, i + 3))) {
        advance();
        if (/[+-]/.test(source[i])) advance();
        while (i < source.length && /\d/.test(source[i])) advance();
      }
      tokens.push({ ...start, text: source.slice(start.offset, i), kind: "number" });
      continue;
    }

    const two = TWO_CHAR_OPS.find(op => source.startsWith(op, i));
    if (two) { advance(); advance(); tokens.push({ ...start, text: two, kind: "operator" }); }
    else { advance(); tokens.push({ ...start, text: c, kind: "symbol" }); }
  }
  return { tokens, versions, diagnostics };
}

/** and/or 오른쪽 식 안의 ta.*() 를 찾는다 — 같은 괄호 깊이에서 쉼표 · 다음 and/or · ? · 줄 바뀜 · 닫는 괄호 앞까지만 본다. */
function lazyTaCalls(tokens, n) {
  const op = tokens[n], found = [];
  let depth = 0;
  for (let j = n + 1; j < tokens.length; j++) {
    const t = tokens[j];
    if (t.kind === "string") continue;
    if (["(", "["].includes(t.text)) depth++;
    else if ([")", "]"].includes(t.text)) { if (depth === 0) break; depth--; }
    else if (depth === 0 && ([",", "?"].includes(t.text) || t.text === "and" || t.text === "or" || t.line > op.line)) break;
    if (t.kind === "identifier" && t.text.startsWith("ta.") && tokens[j + 1]?.text === "(") found.push(t);
  }
  return found;
}

/**
 * Pine v6 간이 점검.
 * 반환: { diagnostics: [{ line, column, message, severity: "error" | "warning" }], errors, warnings }
 * 줄 · 열은 1부터 센다.
 */
export function checkPineV6(source) {
  const text = String(source ?? "");
  const { tokens, versions, diagnostics } = tokenize(text);
  const add = (at, message, severity = "error") => diagnostics.push({ line: at.line, column: at.column, message, severity });
  const top = { line: 1, column: 1 };

  if (!tokens.length) add(top, "검사할 Pine 코드를 입력하세요.");
  if (!versions.length) add(top, "Pine v6 점검에는 첫머리의 //@version=6 선언이 필요합니다.");
  versions.forEach((v, n) => {
    if (v.version !== 6) add(v, `버전이 v${v.version} 입니다. 이 점검은 v6 기준이라 //@version=6 으로 맞추세요.`);
    if (n) add(v, "버전 선언이 중복되었습니다.");
  });

  const stack = [], declarations = [], namedArgs = new Map(), lazyFlagged = new Set();
  for (let n = 0; n < tokens.length; n++) {
    const t = tokens[n], next = tokens[n + 1], previous = tokens[n - 1];
    if (t.kind === "string") continue;

    // ── 코드에 있으면 안 되는 글자 ── (남은 ${…} 의 중괄호 둘은 이미 오류로 알렸으니 경고를 또 달지 않는다)
    const inTemplate = t.text === "{" ? previous?.text === "$" : t.text === "}" && stack.at(-1)?.template === true;
    if (t.text === "$" && next?.text === "{") add(t, "치환되지 않은 ${…} 가 코드에 남아 있습니다 — 코드를 만드는 쪽의 글자 템플릿을 확인하세요.");
    else if (WRONG_CHARS.includes(t.text) && !inTemplate) add(t, `Pine 코드에서 '${t.text}' 문자는 보통 쓰지 않습니다.`, "warning");
    if (t.kind === "identifier" && (t.text === "undefined" || t.text === "NaN" || t.text.startsWith("Math.") || (t.text === "Number" && next?.text === "("))) {
      add(t, `'${t.text}' 는 Pine 이 아니라 JavaScript 의 값·함수입니다 — 코드를 만들 때 섞여 들어갔을 수 있습니다.`, "warning");
    }

    // ── 괄호 짝 ──
    if (["(", "[", "{"].includes(t.text)) {
      stack.push({ ...t, callee: t.text === "(" && previous?.kind === "identifier" ? previous.text : "", template: t.text === "{" && previous?.text === "$" });
    } else if (CLOSE_TO_OPEN[t.text]) {
      if (stack.at(-1)?.text !== CLOSE_TO_OPEN[t.text]) add(t, `괄호 '${t.text}' 에 맞는 여는 괄호가 없습니다.`);
      else stack.pop();
    }

    // ── 함수 인자 ──
    if (t.text === "=" && previous?.kind === "identifier" && ["(", ","].includes(tokens[n - 2]?.text) && stack.at(-1)?.text === "(") {
      const frame = stack.at(-1), seen = namedArgs.get(frame) || new Set();
      if (seen.has(previous.text)) add(previous, `함수 인자 '${previous.text}' 가 중복되었습니다.`);
      seen.add(previous.text);
      namedArgs.set(frame, seen);
    }
    if (t.text === "," && previous?.text === "(") add(t, "첫 번째 함수 인자가 비어 있습니다.");

    // ── 연산자 · 대입 뒤에 식이 없음 ──
    if (BINARY_OPS.includes(t.text) && (!next || [")", "]", ","].includes(next.text))) add(t, "연산자 뒤에 표현식이 필요합니다.");
    if ([">", "<"].includes(t.text) && !next) add(t, "연산자 뒤에 표현식이 필요합니다.");
    if (ASSIGN_OPS.includes(t.text) && (!next || [")", "]", ",", "="].includes(next.text))) add(t, "대입 연산자 뒤에 표현식이 필요합니다.");

    // ── 스크립트 선언 ──
    if (["indicator", "strategy", "library"].includes(t.text) && next?.text === "(" && stack.length === 0) {
      declarations.push(t);
      if (t.column !== 1) add(t, "스크립트 선언은 들여쓰기 없이 맨 앞 칸에서 시작하는 것이 안전합니다.", "warning");
    }

    // ── v6 에서 없어진 것 ──
    if (["parseInt", "parseFloat"].includes(t.text) && next?.text === "(") {
      add(t, `${t.text}() 는 Pine 함수가 아닙니다. 숫자 변환에는 int(), float(), str.tonumber() 를 씁니다.`);
    }
    if (["study", "iff"].includes(t.text) && next?.text === "(") {
      add(t, `${t.text}() 는 v6 에서 쓸 수 없습니다. ${t.text === "study" ? "indicator()" : "조건 ? 값1 : 값2"} 를 씁니다.`);
    }
    if (t.text === "transp" && next?.text === "=" && stack.length) add(t, "v6 에서는 transp 인자를 쓸 수 없습니다. color.new() 로 투명도를 줍니다.");
    if (t.text === "when" && next?.text === "=" && stack.some(f => f.callee.startsWith("strategy."))) {
      add(t, "v6 의 strategy.* 함수에는 when 인자가 없습니다. if 조건문으로 감쌉니다.");
    }
    if (t.text === "bool" && next?.kind === "identifier" && tokens[n + 2]?.text === "=" && tokens[n + 3]?.text === "na") {
      add(t, "v6 에서 bool 변수에는 na 를 넣을 수 없습니다(true 또는 false 만).");
    }

    // ── v6 단락 평가 — 오른쪽 식의 ta.*() 는 왼쪽 결과에 따라 건너뛰어질 수 있다 ──
    if (t.kind === "identifier" && (t.text === "and" || t.text === "or")) {
      lazyTaCalls(tokens, n).filter(call => !lazyFlagged.has(call.offset)).forEach(call => {
        lazyFlagged.add(call.offset);       // 괄호 안 and/or 가 겹쳐도 같은 호출은 한 번만 알린다
        add(call, `v6 의 ${t.text} 는 왼쪽 값으로 결과가 정해지면 오른쪽을 계산하지 않아 ${call.text}() 가 봉마다 실행되지 않을 수 있습니다 — 먼저 변수에 계산해 두세요.`, "warning");
      });
    }
  }
  stack.forEach(t => add(t, `괄호 '${t.text}' 가 닫히지 않았습니다.`));

  if (declarations.length !== 1) {
    add(declarations[1] || top, "indicator(), strategy(), library() 중 하나의 선언이 정확히 한 번 필요합니다.");
  }

  diagnostics.sort((a, b) => a.line - b.line || a.column - b.column || (a.severity === b.severity ? 0 : a.severity === "error" ? -1 : 1));
  return {
    diagnostics,
    errors: diagnostics.filter(d => d.severity === "error").length,
    warnings: diagnostics.filter(d => d.severity === "warning").length,
  };
}

/**
 * 점검 결과를 화면에 그릴 글로 — 화면은 이 값을 textContent 로만 넣는다(글자를 HTML 로 넣지 않는다).
 * 반환: { tone: "ok" | "warn" | "error", summary, items: [{ where, label, severity, message, snippet }], more }
 */
export function formatPineCheck(result, source, max = 20) {
  const lines = String(source ?? "").split("\n");
  const list = result.diagnostics.slice(0, max);
  const note = "TradingView 컴파일 전의 간이 점검입니다";
  const summary = result.diagnostics.length
    ? `기본 문법 점검: 오류 ${result.errors}개 · 경고 ${result.warnings}개 — ${note}`
    : `기본 문법 점검: 발견된 문제 없음 — ${note}(컴파일 결과를 보장하지 않습니다)`;
  return {
    tone: result.errors ? "error" : result.warnings ? "warn" : "ok",
    summary,
    items: list.map(d => ({
      where: `${d.line}행 ${d.column}열`,
      label: d.severity === "error" ? "오류" : "경고",
      severity: d.severity,
      message: d.message,
      snippet: (lines[d.line - 1] || "").replace(/\r$/, "").trim().slice(0, 90),
    })),
    more: Math.max(0, result.diagnostics.length - list.length),
  };
}
