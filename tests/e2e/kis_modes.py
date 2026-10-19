"""#211 실제 HTML·설정/대시보드 JS를 합성 API 응답으로 Chrome에서 검증한다.

python tests/e2e/kis_modes.py --chrome /path/to/chrome --profile /tmp/kis-mode-profile --out /tmp/kis-mode-evidence
Windows Chrome을 WSL에서 호출하면 --profile은 Windows 임시 경로를 지정한다.
운영 앱 접속·자격증명·주문 없이 실행한다.
"""
import argparse,html,json,re,subprocess,threading
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--chrome',required=True)
parser.add_argument('--profile',required=True)
parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--port',type=int,default=18961)
args=parser.parse_args()
OUT=args.out
OUT.mkdir(parents=True,exist_ok=True)
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw): super().__init__(*a,directory=str(ROOT/'public'),**kw)
    def log_message(self,*a): pass
    def do_GET(self):
        if self.path=='/issue211-test':
            page=(ROOT/'public/app.html').read_text()
            page=re.sub(r'<script\b[^>]*>.*?</script>','',page,flags=re.S)
            page=page.replace('</head>', '<meta http-equiv="Content-Security-Policy" content="default-src \'self\' \'unsafe-inline\' data:; connect-src \'none\';"><style>.hidden{display:none}.view{display:none!important}[data-view="settings"]{display:block!important}</style></head>')
            page=page.replace('</body>', '<script type="module">'+(ROOT/'tests/e2e/kis_modes.js').read_text()+'</script></body>')
            data=page.encode(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
        else: super().do_GET()
server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    proc=subprocess.run([args.chrome,'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--user-data-dir='+args.profile,'--virtual-time-budget=8000','--dump-dom',f'http://localhost:{server.server_port}/issue211-test'],capture_output=True,timeout=45)
    (OUT/'browser-dom.html').write_bytes(proc.stdout)
    (OUT/'browser-stderr.log').write_bytes(proc.stderr)
    m=re.search(r'<pre id="kis-mode-result">(.*?)</pre>',proc.stdout.decode('utf-8',errors='replace'),re.S)
    if not m: raise RuntimeError('Browser result missing; see evidence logs')
    result=json.loads(html.unescape(m[1])); (OUT/'browser-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)); print(json.dumps(result,ensure_ascii=False)); assert result['ok']
finally: server.shutdown()
