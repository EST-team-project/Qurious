"""선택 실행: 실제 앱·로그인·API·PG·Redis를 연결한 국면 화면 시험.

일회용 내부 Docker 앱에서만 실행한다. API·앱 JS를 대체하지 않는다.
외부 CDN의 Tailwind 3.4.17/ApexCharts 3.49.2만 로컬 원본 파일로 제공한다.
setup → 시험 앱 재시작 → persist → waiting → 과거 국면 fixture 준비 → history.
고정 스냅샷은 regime_integration_clock.py로 기준 시각을 맞춰 재현한다.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit, quote

from playwright.sync_api import sync_playwright, expect

EMAIL = 'regime.integration@example.com'
PASSWORD = 'FlowCheck-2026-long!'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--phase', choices=['setup', 'persist', 'waiting', 'history'], required=True)
    parser.add_argument('--expected-data-as-of', default='2026-11-02')
    parser.add_argument('--expected-decision-date', default='2026-11-03')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--chromium', default='/usr/bin/chromium')
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    host = urlsplit(base).hostname or ''
    assert host.startswith('qurious-regime-live-'), '일회용 시험 컨테이너 주소만 허용'
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    checks, requests, errors = [], [], []

    def passed(name):
        checks.append(name)
        print('PASS ' + name, flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = browser.new_context(viewport={'width': 1500, 'height': 1000},
            storage_state=str(out/'session.json') if args.phase != 'setup' else None)
        context.set_default_timeout(20000)

        def route(r):
            url = r.request.url
            if url.startswith(base + '/'):
                r.continue_()
            elif url.startswith('https://cdn.tailwindcss.com'):
                r.fulfill(path=str(args.assets/'tailwind.js'), content_type='text/javascript')
            elif url == 'https://cdn.jsdelivr.net/npm/apexcharts@3.49.2/dist/apexcharts.min.js':
                r.fulfill(path=str(args.assets/'apexcharts.js'), content_type='text/javascript')
            else:
                r.abort()  # 글꼴·아이콘 등 외부 장식 자산. 앱/API 요청은 위에서 그대로 보낸다.
        context.route('**/*', route)

        def attach(page):
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('response', lambda r: requests.append({'method': r.request.method,
                'path': urlsplit(r.url).path, 'status': r.status}) if r.url.startswith(base+'/api/') else None)
            return page

        page = attach(context.new_page())

        def api(path):
            response = context.request.get(base + path)
            assert response.status == 200, (path, response.status)
            return response.json()

        def open_plan(p=page):
            with p.expect_response(lambda r: urlsplit(r.url).path == '/api/rebalance/status' and r.status == 200):
                p.goto(base+'/app.html#robo-rebalance', wait_until='domcontentloaded')
            expect(p.locator('#rb-save')).to_be_visible()
            p.wait_for_function("document.getElementById('rb-drift').value !== ''")

        def save(p=page, status=200):
            with p.expect_response(lambda r: urlsplit(r.url).path == '/api/rebalance/plan' and r.request.method == 'PUT') as response:
                p.locator('#rb-save').click()
            assert response.value.status == status, response.value.text()
            if status == 200:
                expect(p.locator('#_toast_el')).to_contain_text('저장했습니다')
            return response.value.json()

        try:
            if args.phase == 'setup':
                page.goto(base+'/register.html?next='+quote('/app.html#robo-portfolio', safe=''), wait_until='domcontentloaded')
                page.locator('[name=name]').fill('국면 통합시험')
                page.locator('[name=email]').fill(EMAIL)
                page.locator('[name=password]').fill(PASSWORD)
                page.locator('[name=birth_date]').fill('1995-01-01')
                page.locator('#agree-all').check()
                with page.expect_response(lambda r: urlsplit(r.url).path == '/api/auth/register' and r.request.method == 'POST') as response:
                    page.locator('button[type=submit]').click()
                assert response.value.status == 200, response.value.text()
                page.wait_for_url('**/app.html#robo-portfolio')
                expect(page.locator('#user-name')).to_have_text('국면 통합시험')
                passed('실제 화면 가입·세션 발급·앱 진입')
                page.locator('#gnb-user').click()
                page.locator('#gnb-user-pop [data-logout]').click()
                page.wait_for_url('**/login.html')
                page.goto(base+'/login.html?next='+quote('/app.html#robo-portfolio', safe=''), wait_until='domcontentloaded')
                page.locator('[name=email]').fill(EMAIL)
                page.locator('[name=password]').fill(PASSWORD)
                with page.expect_response(lambda r: urlsplit(r.url).path == '/api/auth/login' and r.request.method == 'POST') as response:
                    page.locator('button[type=submit]').click()
                assert response.value.status == 200
                page.wait_for_url('**/app.html#robo-portfolio')
                passed('로그아웃 후 실제 로그인 폼으로 재인증')
                page.locator('#robo-risk').select_option('moderate')
                page.locator('#robo-allocation-model').select_option('regime')
                with page.expect_response(lambda r: urlsplit(r.url).path == '/api/ml/robo/allocation' and r.request.method == 'POST', timeout=240000) as response:
                    page.locator('#robo-optimize-btn').click()
                assert response.value.status == 200, response.value.text()[:500]
                allocation = response.value.json()
                expect(page.locator('#robo-allocation-saved')).to_contain_text('저장됨')
                saved = api('/api/ml/robo/allocation/latest')
                assert saved['id'] == allocation['saved']['id']
                assert saved['result']['allocation_model'] == 'regime'
                assert saved['result']['asset_model']['as_of'] == args.expected_data_as_of
                passed('실제 수집 일봉으로 배분 계산·PG 저장·저장본 조회')
                open_plan()
                assert not page.locator('#rb-regime-auto').is_checked()
                page.once('dialog', lambda d: d.accept())
                page.locator('#rb-import-allocation').click()
                expect(page.locator('#rb-regime-auto')).to_be_enabled()
                assert not page.locator('#rb-regime-auto').is_checked()
                assert not api('/api/rebalance/plan')['regime_auto']['enabled']
                page.locator('#rb-regime-auto').check()
                plan = save()
                assert plan['regime_auto']['enabled'] and not plan['auto_execute']
                assert plan['regime_auto']['source_id'] == saved['id']
                assert {t['symbol']: t['weight_pct'] for t in plan['targets']} == {
                    t['symbol']: t['weight_pct'] for t in saved['handoff']['targets']}
                (out/'expected-plan.json').write_text(json.dumps(plan, ensure_ascii=False))
                passed('실제 가져오기·명시적 활성화·목표 일치·자동 예약 OFF')
                open_plan()
                expect(page.locator('#rb-regime-auto')).to_be_checked()
                assert api('/api/rebalance/plan') == plan
                passed('새로고침 후 PG의 활성화 상태·목표 보존')
            elif args.phase == 'persist':
                expected = json.loads((out/'expected-plan.json').read_text())
                open_plan()
                assert api('/api/rebalance/plan') == expected
                expect(page.locator('#rb-regime-auto')).to_be_checked()
                passed('앱 재시작 후 세션·연결 정보·목표·수정 버전 보존')
                second = attach(context.new_page())
                open_plan(second)
                page.locator('#rb-name').fill('먼저 저장한 플랜')
                first = save()
                second.locator('#rb-name').fill('오래된 화면의 편집')
                save(second, 409)
                expect(second.locator('#_toast_el')).to_contain_text('다른 화면이나 자동 점검')
                assert second.locator('#rb-name').input_value() == '오래된 화면의 편집'
                assert api('/api/rebalance/plan')['name'] == first['name']
                passed('두 실제 화면의 동시 편집: 409·서버 보존·편집안 보존')
                second.once('dialog', lambda d: d.accept())
                second.locator('#rb-discard').click()
                expect(second.locator('#rb-name')).to_have_value(first['name'])
                passed('충돌 후 편집 취소·최신 플랜 재조회')
                second.close()
            elif args.phase == 'waiting':
                open_plan()
                before = api('/api/rebalance/plan')
                history_before = api('/api/rebalance/target-changes')
                runs_before = api('/api/rebalance/runs')
                state = api('/api/rebalance/status')['automatic_check']
                assert not state['ready'] and state['state'] == 'before_update', state
                assert state['decision_date'] == args.expected_decision_date, state
                expect(page.locator('#rb-daily-check')).to_contain_text('12:30')
                expect(page.locator('#rb-execute')).to_be_disabled()
                passed('12:30 이전 준비 대기 이유 표시·실행 버튼 차단')
                for _ in range(2):
                    with page.expect_response(lambda r: urlsplit(r.url).path == '/api/rebalance/check' and r.request.method == 'POST') as response:
                        page.locator('#rb-check').click()
                    assert response.value.status == 200, response.value.text()
                    result = response.value.json()
                    assert result['checked'] is False and result['reason'] == 'data_waiting', result
                    assert api('/api/rebalance/plan') == before
                    assert api('/api/rebalance/target-changes') == history_before
                    assert api('/api/rebalance/runs') == runs_before
                passed('자료 대기 중 반복 점검도 목표·이력·제안·완료 날짜를 보존')
            else:
                open_plan()
                state = api('/api/rebalance/status')['automatic_check']
                assert state['ready'], f"history는 준비된 자료가 필요합니다. 시험 기준 시각과 스냅샷을 확인하세요: {state}"
                assert state['decision_date'] == args.expected_decision_date, state
                assert state['data_as_of'] == args.expected_data_as_of, state
                assert round(sum(t['weight_pct'] for t in api('/api/rebalance/plan')['targets']), 2) == 33
                with page.expect_response(lambda r: urlsplit(r.url).path == '/api/rebalance/check' and r.request.method == 'POST') as response:
                    page.locator('#rb-check').click()
                assert response.value.status == 200, response.value.text()
                result = response.value.json()
                assert result.get('checked') is True, result
                assert result.get('regime_auto', {}).get('status') == 'changed' and result.get('status') == 'proposed', result
                history = api('/api/rebalance/target-changes')['changes']
                assert len(history) == 1
                assert round(sum(t['weight_pct'] for t in history[0]['before_targets']), 2) == 33
                assert round(sum(t['weight_pct'] for t in history[0]['after_targets']), 2) == 15
                page.locator('#rb-regime-history-load').locator('xpath=..').locator('summary').click()
                page.locator('#rb-regime-history-load').click()
                expect(page.locator('#rb-regime-history')).to_contain_text('상승·저변동 → 하락·고변동')
                expect(page.locator('#rb-regime-history')).to_contain_text('85.00%')
                passed('과거 국면 fixture→실제 점검 API→목표 33→15·제안·이력 표시')
                page.locator('#rb-check').click()
                expect(page.locator('#_toast_el')).to_contain_text('오늘')
                assert len(api('/api/rebalance/target-changes')['changes']) == 1
                passed('실제 반복 점검의 일별 중복 차단')
                page.locator('#rb-regime-auto').uncheck()
                plan = save()
                assert not plan['regime_auto']['enabled']
                open_plan()
                expect(page.locator('#rb-regime-auto')).not_to_be_checked()
                assert len(api('/api/rebalance/target-changes')['changes']) == 1
                passed('명시적 해제·재접속 후 OFF·기존 변경 이력 보존')
                other = browser.new_context()
                response = other.request.post(base+'/api/auth/register', data={
                    'name': '다른 시험 계정', 'email': 'regime.other@example.com', 'password': PASSWORD,
                    'birth_date': '1995-01-01', 'terms_version': '2026-10-29-v0.4',
                    'agreed': ['service','privacy','invest']})
                assert response.status == 200, response.text()
                assert other.request.get(base+'/api/rebalance/target-changes').json() == {'changes': []}
                assert other.request.get(base+'/api/ml/robo/allocation/latest').status == 404
                assert other.request.get(base+'/api/rebalance/plan').json()['targets'] == []
                passed('별도 실제 로그인 계정의 저장본·플랜·이력 격리')
                other.close()
            assert not errors, errors
            assert not any(r['method'] == 'POST' and '/execute' in r['path'] for r in requests)
            context.storage_state(path=str(out/'session.json'))
            page.screenshot(path=str(out/(args.phase+'.png')), full_page=False)
            result = {'status': 'passed', 'checks': checks, 'requests': requests, 'page_errors': errors,
                      'expected_data_as_of': args.expected_data_as_of, 'expected_decision_date': args.expected_decision_date}
        except Exception as exc:
            page.screenshot(path=str(out/(args.phase+'-failed.png')), full_page=False)
            result = {'status': 'failed', 'error': str(exc), 'checks': checks, 'requests': requests, 'page_errors': errors}
            raise
        finally:
            (out/(args.phase+'.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))
            browser.close()
    print(json.dumps({'phase': args.phase, 'status': 'passed', 'checks': len(checks)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
