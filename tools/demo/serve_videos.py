"""발표자료 로컬 재생 서버. MP4 중간 이동에 필요한 단일 byte Range를 지원한다.

python tools/demo/serve_videos.py --port 8766
브라우저: http://localhost:8766/오준영/영상.html
"""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "docs/phase-3/06-retrospective"


class VideoHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        self._remaining = None
        path = Path(self.translate_path(self.path))
        value = self.headers.get("Range")
        if not value or not path.is_file():
            return super().send_head()
        try:
            source = path.open("rb")
        except OSError:
            self.send_error(404, "File not found")
            return None
        stat = os.fstat(source.fileno())
        size = stat.st_size
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
        start, end = 0, -1
        try:
            if match and any(match.groups()) and size:
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), size - 1) if last else size - 1
                elif int(last) > 0:
                    start, end = max(0, size - int(last)), size - 1
        except ValueError:
            start, end = 0, -1
        if start > end or start >= size:
            source.close()
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        self.send_response(206)
        self.send_header("Content-type", self.guess_type(str(path)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Last-Modified", self.date_time_string(stat.st_mtime))
        self.end_headers()
        source.seek(start)
        self._remaining = end - start + 1
        return source

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def copyfile(self, source, outputfile):
        if self._remaining is None:
            return super().copyfile(source, outputfile)
        remaining = self._remaining
        while remaining:
            chunk = source.read(min(64 * 1024, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--directory", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    if not args.directory.is_dir():
        parser.error("발표자료 폴더가 없습니다.")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(VideoHandler, directory=str(args.directory.resolve())))
    print(f"발표자료: http://localhost:{server.server_port}/오준영/영상.html", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
