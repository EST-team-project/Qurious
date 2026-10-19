"""자산배분 예측 표시 실제 HTML·JS를 합성 API 응답으로 Chrome에서 검증한다.

python tests/e2e/allocation_predictions.py --chrome /path/to/chrome --profile /tmp/allocation-predictions-profile --out /tmp/allocation-predictions-evidence
Windows Chrome을 WSL에서 호출하면 --profile은 Windows 임시 경로를 지정한다.
운영 앱 접속·자격증명·주문 없이 실행한다.
"""
import argparse,html,importlib.util,json,re,subprocess,threading
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('allocation_view',ROOT/'app/services/allocation_prediction_view.py')
view=importlib.util.module_from_spec(spec); spec.loader.exec_module(view)
base={'risk_profile':'moderate','horizon_years':3,'amount_manwon':5000,
      'allocations':{'국내주식':30,'현금':70},'projections':[],'stock_picks':[]}
for annual,ex in [(300,None),(-90,{'signal':1,'signal_label':'매수','probability_pct':48.2}), (0,None)]:
    base['stock_picks'].append({'name':'검증 종목 <b>문자</b>','weight':10,
        'reason':f'연환산 수익률 10%, 변동성 20%, AI 예측 수익률 {annual:.1f}% (매수, 신뢰도 0.31)',
        'ai_prediction':{'pred_ann_return_pct':annual,'confidence':.31,'signal':1,
            'model_signal':1,'model_signal_probability_pct':48.2,'explanation':ex,
            'quality':{'reliable':False,'cls_val_accuracy':.30,'baseline_accuracy':.36}}})
fixture=json.dumps(view.allocation_view(base),ensure_ascii=False).replace('<','\\u003c')
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
        if self.path=='/allocation-predictions-test':
            page=(ROOT/'public/app.html').read_text()
            page=re.sub(r'<script\b[^>]*>.*?</script>','',page,flags=re.S)
            page=page.replace('</head>', '<meta http-equiv="Content-Security-Policy" content="default-src \'self\' \'unsafe-inline\' data:; connect-src \'none\';"><style>.hidden{display:none}.view{display:none!important}[data-view="robo-portfolio"]{display:block!important}</style></head>')
            page=page.replace('</body>', '<script type="module">const fixture='+fixture+';\n'+(ROOT/'tests/e2e/allocation_predictions.js').read_text()+'</script></body>')
            data=page.encode(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
        else: super().do_GET()
server=ThreadingHTTPServer((args.bind,args.port),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    proc=subprocess.run([args.chrome,'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--user-data-dir='+args.profile,'--virtual-time-budget=8000','--dump-dom',f'http://{args.browser_host}:{server.server_port}/allocation-predictions-test'],capture_output=True,timeout=45)
    (OUT/'browser-dom.html').write_bytes(proc.stdout)
    (OUT/'browser-stderr.log').write_bytes(proc.stderr)
    m=re.search(r'<pre id="allocation-predictions-result">(.*?)</pre>',proc.stdout.decode('utf-8',errors='replace'),re.S)
    if not m: raise RuntimeError('Browser result missing; see evidence logs')
    result=json.loads(html.unescape(m[1])); (OUT/'browser-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)); print(json.dumps(result,ensure_ascii=False)); assert result['ok']
finally: server.shutdown()
