"""의사결정 출처·회차 표시 실제 HTML·JS를 합성 API 응답으로 Chrome에서 검증한다.

python tests/e2e/decision_sources.py --chrome /path/to/chrome --profile /tmp/decision-sources-profile --out /tmp/decision-sources-evidence
Windows Chrome을 WSL에서 호출하면 --profile은 Windows 임시 경로를 지정한다.
운영 앱 접속·자격증명·주문 없이 실행한다.
"""
import argparse,html,importlib.util,json,re,subprocess,threading
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('signal_view',ROOT/'app/services/decision_signal_view.py')
view=importlib.util.module_from_spec(spec); spec.loader.exec_module(view)
current='2026-10-19T02:00:00Z'
old=view.signal_view({'symbol':'OLD.KS','name':'이전 회차','signal':'SELL','score':-2},{'aggressive':False},'2026-10-19T01:00:00Z')
a=view.signal_view({'symbol':'005930.KS','name':'동일 종목 <b>문자</b>','signal':'BUY','score':2,'reasons':['RSI 과매도'], 'source':'me','basis':{'as_of':'2026-10-16','interval':'1d'}},{'aggressive':False},current)
b=view.signal_view({'symbol':'005930.KS','name':'배치 동일 종목','signal':'HOLD','score':5,'source':'batch','basis':{'as_of':1792375200,'interval':'5m'}},{'aggressive':True},current)
c=view.signal_view({'symbol':'000660.KS','name':'계산 실패','signal':'UNAVAILABLE','score':0,'error':'지표 계산 실패','source':'me'},{'aggressive':False},current)
strategy=view.signal_view({'symbol':'005930.KS','name':'사용자 전략','signal':'SELL','score':2,'action':'매도','basis':{'normalized_score':.7}},{'aggressive':False,'strategy':{'applied':True,'id':'s1','version':3}},current)
fixture=json.dumps({'signals':[old,a,b,c], 'strategy':strategy},ensure_ascii=False).replace('<','\\u003c')
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--chrome',required=True)
parser.add_argument('--profile',required=True)
parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--port',type=int,default=18961)
parser.add_argument('--bind',default='127.0.0.1')
parser.add_argument('--browser-host',default='localhost',help='Windows Chrome에서 WSL localhost 전달이 안 되면 WSL IP 지정 (--bind 0.0.0.0)')
args=parser.parse_args()
OUT=args.out
OUT.mkdir(parents=True,exist_ok=True)
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw): super().__init__(*a,directory=str(ROOT/'public'),**kw)
    def log_message(self,*a): pass
    def do_GET(self):
        if self.path=='/decision-sources-test':
            page=(ROOT/'public/app.html').read_text()
            page=re.sub(r'<script\b[^>]*>.*?</script>','',page,flags=re.S)
            page=page.replace('</head>', '<meta http-equiv="Content-Security-Policy" content="default-src \'self\' \'unsafe-inline\' data:; connect-src \'none\';"><style>.hidden{display:none}.view{display:none!important}[data-view="robo-decision"]{display:block!important}</style></head>')
            page=page.replace('</body>', '<script type="module">const fixture='+fixture+';\n'+(ROOT/'tests/e2e/decision_sources.js').read_text()+'</script></body>')
            data=page.encode(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
        else: super().do_GET()
server=ThreadingHTTPServer((args.bind,args.port),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    proc=subprocess.run([args.chrome,'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--user-data-dir='+args.profile,'--virtual-time-budget=8000','--dump-dom',f'http://{args.browser_host}:{server.server_port}/decision-sources-test'],capture_output=True,timeout=45)
    (OUT/'browser-dom.html').write_bytes(proc.stdout)
    (OUT/'browser-stderr.log').write_bytes(proc.stderr)
    m=re.search(r'<pre id="decision-sources-result">(.*?)</pre>',proc.stdout.decode('utf-8',errors='replace'),re.S)
    if not m: raise RuntimeError('Browser result missing; see evidence logs')
    result=json.loads(html.unescape(m[1])); (OUT/'browser-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)); print(json.dumps(result,ensure_ascii=False)); assert result['ok']
finally: server.shutdown()
