[1mdiff --git a/public/app.html b/public/app.html[m
[1mindex ab3a618..b3957bc 100644[m
[1m--- a/public/app.html[m
[1m+++ b/public/app.html[m
[36m@@ -1779,12 +1779,16 @@[m
                     <button id="robo-metrics-refresh" class="btn-secondary text-xs">지표 갱신</button>[m
                   </div>[m
                 </div>[m
[31m-                <p class="text-xs mb-5" style="color:var(--text-mute);">본 프로젝트의 백테스트·성과 검증 방법론은 Khushi (2026)의 QFRS[m
[32m+[m[32m                <p class="text-xs mb-5" style="color:var(--text-mute);">본 프로젝트의 백테스트·성과 검증 방법론은 Khushi의 QFRS (2026)[m
                   논문을 참조하였습니다.</p>[m
[31m-                <!-- KPI 카드 영역 -->[m
[32m+[m[32m                <!-- 요약 카드 -->[m
                 <div id="robo-metrics-cards" class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5"></div>[m
[31m-                <!-- 차트 영역 (Equity Curve / Drawdown) -->[m
[32m+[m
[32m+[m[32m                <!-- 차트 -->[m
                 <div id="robo-metrics-chart" style="height: 300px;"></div>[m
[32m+[m
[32m+[m[32m                <!-- 🆕 상세 지표 테이블 -->[m
[32m+[m[32m                <div id="robo-metrics-table" class="mt-5"></div>[m
               </div>[m
             </div>[m
           </div>[m
[36m@@ -2703,16 +2707,36 @@[m [mRC_i = wi × (Σw)_i / √(w'Σw)[m
           </div>[m
 [m
           <!-- 금융 강의 (2026-10-01) — 강의실 · 주제 화면. 자리만 두고 내용은 js/finlearn.js 가 그린다 -->[m
[31m-          <div class="view" data-view="fin-lectures"><div id="finlearn-hub"></div></div>[m
[31m-          <div class="view" data-view="fin-topic-futures"><div class="finlearn-topic"></div></div>[m
[31m-          <div class="view" data-view="fin-topic-funds"><div class="finlearn-topic"></div></div>[m
[31m-          <div class="view" data-view="fin-topic-bonds"><div class="finlearn-topic"></div></div>[m
[31m-          <div class="view" data-view="fin-topic-allocation"><div class="finlearn-topic"></div></div>[m
[31m-          <div class="view" data-view="fin-topic-company"><div class="finlearn-topic"></div></div>[m
[31m-          <div class="view" data-view="fin-topic-stocks"><div class="finlearn-topic"></div></div>[m
[31m-          <div class="view" data-view="fin-topic-technical"><div class="finlearn-topic"></div></div>[m
[31m-          <div class="view" data-view="fin-topic-industry"><div class="finlearn-topic"></div></div>[m
[31m-          <div class="view" data-view="fin-topic-macro"><div class="finlearn-topic"></div></div>[m
[32m+[m[32m          <div class="view" data-view="fin-lectures">[m
[32m+[m[32m            <div id="finlearn-hub"></div>[m
[32m+[m[32m          </div>[m
[32m+[m[32m          <div class="view" data-view="fin-topic-futures">[m
[32m+[m[32m            <div class="finlearn-topic"></div>[m
[32m+[m[32m          </div>[m
[32m+[m[32m          <div class="view" data-view="fin-topic-funds">[m
[32m+[m[32m            <div class="finlearn-topic"></div>[m
[32m+[m[32m          </div>[m
[32m+[m[32m          <div class="view" data-view="fin-topic-bonds">[m
[32m+[m[32m            <div class="finlearn-topic"></div>[m
[32m+[m[32m          </div>[m
[32m+[m[32m          <div class="view" data-view="fin-topic-allocation">[m
[32m+[m[32m            <div class="finlearn-topic"></div>[m
[32m+[m[32m          </div>[m
[32m+[m[32m          <div class="view" data-view="fin-topic-company">[m
[32m+[m[32m            <div class="finlearn-topic"></div>[m
[32m+[m[32m          </div>[m
[32m+[m[32m          <div class="view" data-view="fin-topic-stocks">[m
[32m+[m[32m            <div class="finlearn-topic"></div>[m
[32m+[m[32m          </div>[m
[32m+[m[32m          <div class="view" data-view="fin-topic-technical">[m
[32m+[m[32m            <div class="finlearn-topic"></div>[m
[32m+[m[32m          </div>[m
[32m+[m[32m          <div class="view" data-view="fin-topic-industry">[m
[32m+[m[32m            <div class="finlearn-topic"></div>[m
[32m+[m[32m          </div>[m
[32m+[m[32m          <div class="view" data-view="fin-topic-macro">[m
[32m+[m[32m            <div class="finlearn-topic"></div>[m
[32m+[m[32m          </div>[m
 [m
           <!-- 5-2. 로그 / 이벤트 -->[m
           <div class="view" data-view="sysadmin-logs">[m
[1mdiff --git a/public/js/robo.js b/public/js/robo.js[m
[1mindex 852e10f..b90694e 100644[m
[1m--- a/public/js/robo.js[m
[1m+++ b/public/js/robo.js[m
[36m@@ -377,10 +377,12 @@[m [mlet _roboMetricsChart = null;[m
 async function loadRoboPerformanceMetrics() {[m
   const cardsEl = document.getElementById("robo-metrics-cards");[m
   const chartEl = document.getElementById("robo-metrics-chart");[m
[32m+[m[32m  const tableEl = document.getElementById("robo-metrics-table");   // 🆕[m
   if (!cardsEl) return;[m
 [m
   cardsEl.innerHTML = `<div class="text-xs col-span-4" style="color:var(--text-mute);">지표 계산 중...</div>`;[m
   if (chartEl) chartEl.innerHTML = "";[m
[32m+[m[32m  if (tableEl) tableEl.innerHTML = "";                             // 🆕[m
 [m
   try {[m
     const data = await api("/api/paper/performance/metrics");[m
[36m@@ -399,6 +401,7 @@[m [masync function loadRoboPerformanceMetrics() {[m
     const trColor = (data.total_return || 0) >= 0 ? "var(--green)" : "var(--red)";[m
     const dsrColor = (m.dsr || 0) >= 0.95 ? "var(--green)" : "var(--text)";[m
 [m
[32m+[m[32m    // ── 요약 카드 4개 ──────────────────────────────────[m
     cardsEl.innerHTML = `[m
       <div class="card" style="padding:12px;text-align:center;">[m
         <div class="text-xs" style="color:var(--text-mute);">누적 수익률</div>[m
[36m@@ -417,14 +420,14 @@[m [masync function loadRoboPerformanceMetrics() {[m
         <div class="font-bold" style="color:${dsrColor}">${m.dsr == null ? "-" : (m.dsr * 100).toFixed(1) + "%"}</div>[m
       </div>`;[m
 [m
[32m+[m[32m    // ── 차트 (스타일 그대로 유지) ─────────────────────[m
     if (chartEl && Array.isArray(data.equity_curve) && data.equity_curve.length > 1) {[m
       if (_roboMetricsChart) { _roboMetricsChart.destroy(); _roboMetricsChart = null; }[m
 [m
[31m-      // 날짜 라벨 (MM-DD 형식)[m
       const rawDates = Array.isArray(data.snap_dates) ? data.snap_dates : [];[m
       const labels = data.equity_curve.map((_, i) => {[m
         const d = rawDates[i];[m
[31m-        return d ? d.slice(5) : `#${i + 1}`;   // "2026-09-17" → "09-17"[m
[32m+[m[32m        return d ? d.slice(5) : `#${i + 1}`;[m
       });[m
 [m
       const series = [{[m
[36m@@ -470,6 +473,94 @@[m [masync function loadRoboPerformanceMetrics() {[m
       });[m
       _roboMetricsChart.render();[m
     }[m
[32m+[m
[32m+[m[32m    // ── 🆕 상세 지표 테이블 ───────────────────────────[m
[32m+[m[32m    if (tableEl) {[m
[32m+[m[32m      const rows = [[m
[32m+[m[32m        {[m
[32m+[m[32m          name: "누적 수익률",[m
[32m+[m[32m          value: pct(data.total_return),[m
[32m+[m[32m          tone: (data.total_return || 0) >= 0 ? "up" : "down",[m
[32m+[m[32m          desc: "전체 기간 누적 수익률 (스냅샷 시작 대비)",[m
[32m+[m[32m          ref: "기본 지표",[m
[32m+[m[32m        },[m
[32m+[m[32m        {[m
[32m+[m[32m          name: "MDD (Maximum Drawdown)",[m
[32m+[m[32m          value: pct(m.mdd),[m
[32m+[m[32m          tone: "down",[m
[32m+[m[32m          desc: "고점 대비 최대 하락폭 — 위험의 크기, 낮을수록 좋음",[m
[32m+[m[32m          ref: "Magdon-Ismail & Atiya (2004)",[m
[32m+[m[32m        },[m
[32m+[m[32m        {[m
[32m+[m[32m          name: "Sharpe Ratio",[m
[32m+[m[32m          value: num(m.sharpe_ratio),[m
[32m+[m[32m          tone: (m.sharpe_ratio || 0) >= 1 ? "up" : "neutral",[m
[32m+[m[32m          desc: "위험 1단위당 초과수익. 1.0 이상 양호, 2.0 이상 우수",[m
[32m+[m[32m          ref: "Sharpe (1966)",[m
[32m+[m[32m        },[m
[32m+[m[32m        {[m
[32m+[m[32m          name: "Sortino Ratio",[m
[32m+[m[32m          value: num(m.sortino_ratio),[m
[32m+[m[32m          tone: (m.sortino_ratio || 0) >= 1 ? "up" : "neutral",[m
[32m+[m[32m          desc: "하방 변동성만 반영한 위험조정 수익률 — 상승 변동은 페널티 없음",[m
[32m+[m[32m          ref: "Sortino & Price (1994)",[m
[32m+[m[32m        },[m
[32m+[m[32m        {[m
[32m+[m[32m          name: "Sterling Ratio",[m
[32m+[m[32m          value: num(m.sterling_ratio),[m
[32m+[m[32m          tone: (m.sterling_ratio || 0) >= 0.5 ? "up" : "neutral",[m
[32m+[m[32m          desc: "상위 3개 MDD 평균 대비 연환산 초과수익 — 이상치에 강건",[m
[32m+[m[32m          ref: "Sterling (1970s)",[m
[32m+[m[32m        },[m
[32m+[m[32m        {[m
[32m+[m[32m          name: "Calmar Ratio",[m
[32m+[m[32m          value: num(m.calmar_ratio),[m
[32m+[m[32m          tone: (m.calmar_ratio || 0) >= 0.5 ? "up" : "neutral",[m
[32m+[m[32m          desc: "최대 MDD 대비 연환산 초과수익 — 보수적 하방 리스크 지표",[m
[32m+[m[32m          ref: "Young (1991)",[m
[32m+[m[32m        },[m
[32m+[m[32m        {[m
[32m+[m[32m          name: "Deflated Sharpe Ratio (DSR)",[m
[32m+[m[32m          value: m.dsr == null ? "-" : (m.dsr * 100).toFixed(1) + "%",[m
[32m+[m[32m          tone: (m.dsr || 0) >= 0.95 ? "up" : "down",[m
[32m+[m[32m          desc: "이 샤프 지수가 우연이 아닐 확률 (0~1). 0.95 이상 통계적 유의",[m
[32m+[m[32m          ref: "Bailey & López de Prado (2014)",[m
[32m+[m[32m        },[m
[32m+[m[32m      ];[m
[32m+[m
[32m+[m[32m      const toneColor = (t) =>[m
[32m+[m[32m        t === "up" ? "var(--green)" : t === "down" ? "var(--red)" : "var(--text)";[m
[32m+[m
[32m+[m[32m      tableEl.innerHTML = `[m
[32m+[m[32m        <h4 class="text-sm font-semibold mb-3" style="color:var(--text-dim);">[m
[32m+[m[32m          📋 상세 지표 (${data.snapshot_count}개 스냅샷 기준)[m
[32m+[m[32m        </h4>[m
[32m+[m[32m        <div class="overflow-x-auto">[m
[32m+[m[32m          <table class="w-full text-xs" style="border-collapse:collapse;">[m
[32m+[m[32m            <thead>[m
[32m+[m[32m              <tr style="border-bottom:1px solid var(--border);color:var(--text-mute);">[m
[32m+[m[32m                <th style="text-align:left;padding:8px 6px;">지표</th>[m
[32m+[m[32m                <th style="text-align:right;padding:8px 6px;">값</th>[m
[32m+[m[32m                <th style="text-align:left;padding:8px 6px;">의미</th>[m
[32m+[m[32m                <th style="text-align:left;padding:8px 6px;">참조</th>[m
[32m+[m[32m              </tr>[m
[32m+[m[32m            </thead>[m
[32m+[m[32m            <tbody>[m
[32m+[m[32m              ${rows.map(r => `[m
[32m+[m[32m                <tr style="border-bottom:1px solid var(--border);">[m
[32m+[m[32m                  <td style="padding:8px 6px;font-weight:600;">${escHtml(r.name)}</td>[m
[32m+[m[32m                  <td style="padding:8px 6px;text-align:right;font-weight:700;color:${toneColor(r.tone)};">${r.value}</td>[m
[32m+[m[32m                  <td style="padding:8px 6px;color:var(--text-dim);">${escHtml(r.desc)}</td>[m
[32m+[m[32m                  <td style="padding:8px 6px;font-size:11px;color:var(--text-mute);">${escHtml(r.ref)}</td>[m
[32m+[m[32m                </tr>`).join("")}[m
[32m+[m[32m            </tbody>[m
[32m+[m[32m          </table>[m
[32m+[m[32m        </div>[m
[32m+[m[32m        <p class="text-xs mt-3" style="color:var(--text-mute);">[m
[32m+[m[32m          ※ 모든 지표는 무위험수익률 ${(data.params?.risk_free_rate * 100).toFixed(1)}% · 시도 횟수 ${data.params?.n_trials}회 기준으로 산출됩니다.[m
[32m+[m[32m          DSR이 0.95 미만이면 이 전략은 우연일 가능성을 배제할 수 없습니다.[m
[32m+[m[32m        </p>`;[m
[32m+[m[32m    }[m
   } catch (e) {[m
     cardsEl.innerHTML = `<div class="text-xs col-span-4" style="color:var(--red);">[m
       지표를 불러오지 못했습니다: ${escHtml(e.message)}[m
