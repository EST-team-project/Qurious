"""실제 HTTP 응답으로 통합 서비스의 회귀를 점검한다. 외부 서비스는 별도 분류한다."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import urllib.error
import urllib.request


def check(base, method, path, payload=None):
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
    request = urllib.request.Request(base + path, data=body, method=method,
        headers={'Content-Type': 'application/json'} if body else {})
    try:
        with urllib.request.urlopen(request, timeout=50) as response:
            raw = response.read()
            value = json.loads(raw) if 'json' in response.headers.get('Content-Type', '') else None
            return {'path': path, 'method': method, 'status': response.status, 'bytes': len(raw), 'value': value}
    except urllib.error.HTTPError as error:
        return {'path': path, 'method': method, 'status': error.code, 'error': error.read().decode('utf-8')[:240]}
    except Exception as error:
        return {'path': path, 'method': method, 'status': 0, 'error': str(error)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://localhost:8000')
    parser.add_argument('--external', action='store_true')
    args = parser.parse_args()
    cases = [('GET', path, None) for path in [
        '/health', '/openapi.json', '/', '/analysis/', '/analysis/js/app.js',
        '/analysis/images/income-statement.png', '/images/korea-global-economy-position.png',
        '/api/health', '/api/system/resources', '/api/learn/doc/03', '/api/learn/doc/voca',
        '/api/search?q=%EC%B1%84%EA%B6%8C', '/api/vocabulary-exam', '/api/quiz/day/1',
        '/api/quant/lean/samsung', '/api/quant/lean/hyundai', '/api/quant/lean/samsung-em',
        '/api/rag/status', '/learning/documents', '/api/market/chart-patterns',
        '/api/market/recent-ipo-list', '/api/macro/kospi-ex/meta', '/api/tax/sample',
        '/api/nps/domestic-equity-holdings?year=2025&limit=5',
    ]]
    cases += [('POST', path, payload) for path, payload in [
        ('/api/visitors/heartbeat', {'visitor_id':'integration-smoke'}),
        ('/api/rag/search', {'query':'채권 금리', 'top_k':3}),
        ('/api/rag/ask', {'query':'채권 금리', 'top_k':3, 'provider':'rag'}),
        ('/api/quant/backtest', {'n_days':252}),
        ('/api/quant/portfolio', {'n_simulations':500}),
        ('/api/quant/risk', {}),
        ('/api/ml/kmeans', {'n_samples':100, 'n_clusters':3}),
        ('/api/ml/linear-regression', {'n_samples':50}),
        ('/api/macro/simulation', {}),
        ('/chat', {'question':'채권 금리', 'domain':'finance', 'session_id':'integration-smoke'}),
        ('/chat/orchestrate', {'question':'ETF 분산투자', 'domain':'finance', 'session_id':'integration-smoke'}),
        ('/api/ml/cross-validation', {'n_samples':200,'cv':3}),
        ('/api/ml/random-forest', {}),
        ('/api/ml/svm', {}),
        ('/api/ml/mlp', {'n_samples':200, 'max_iter':50}),
        ('/api/cv/circle-animation', {'width':128,'height':128,'fps':10}),
        ('/api/dl/cnn-timeseries', {'n_samples':500,'epochs':5}),
        ('/api/dl/lstm-predictor', {'n_days':500,'epochs':10,'hidden_size':16}),
        ('/api/dl/transformer-timeseries', {'seq_len':20,'d_model':16,'epochs':10}),
    ]]
    if args.external:
        cases = [('GET','/api/home/market-candle?market=kospi&period=1mo',None),
            ('POST','/api/market/snapshot',{'tickers':['AAPL']}),
            ('POST','/api/dart/company-search',{'company_name':'삼성전자','limit':1}),
            ('POST','/api/industry/porter',{}),
            ('POST','/api/macro/realtime',{})]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda c:check(args.base.rstrip('/'),*c), cases))
    failures = []
    for item in results:
        value = item.pop('value', None)
        if item['path'] == '/openapi.json' and value:
            required=['/auth/login','/auth/calendar-events','/api/auth/login','/api/dart/company-search','/chat/orchestrate','/backtests/run']
            item['missing_paths']=[p for p in required if p not in value['paths']]
            item['api_paths']=len(value['paths'])
            if item['missing_paths']: failures.append(item['path'])
        if item['path']=='/api/rag/search' and value:
            item['chunks']=value['count']
            item['sources']=[r['source_doc'] for r in value['results']]
            if not value['count']: failures.append(item['path'])
        if item['path'].startswith('/api/search') and value:
            item['hits']=len(value['hits'])
            if not item['hits']: failures.append(item['path'])
        if item['path'] == '/chat' and value:
            item['references'] = len(value.get('references', []))
            item['answer_mode'] = 'extractive' if '문서 발췌 모드' in value.get('answer','') else 'remote'
            if not item['references']: failures.append(item['path'])
        if item['path'] == '/chat/orchestrate' and value:
            item['tools'] = [t['tool'] for t in value.get('tool_calls', [])]
            if not item['tools']: failures.append(item['path'])
        if item['status'] != 200: failures.append(item['path'])
        print(json.dumps(item, ensure_ascii=False))
    print(json.dumps({'checks':len(results),'failures':failures},ensure_ascii=False))
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
