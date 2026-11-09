"""실제 HTTP 응답으로 MP4 구간 재생에 필요한 byte Range 계약을 확인한다."""
from functools import partial
import http.client
from http.server import ThreadingHTTPServer
import importlib.util
from pathlib import Path
from threading import Thread

import pytest


@pytest.fixture
def video_server(tmp_path):
    path = Path(__file__).resolve().parents[1] / "tools/demo/serve_videos.py"
    spec = importlib.util.spec_from_file_location("video_server_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "clip.mp4").write_bytes(b"0123456789")
    (tmp_path / "empty.mp4").touch()
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(module.VideoHandler, directory=str(tmp_path)))
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("method,path,value,status,content_range,length,body", [
    ("GET", "/clip.mp4", None, 200, None, 10, b"0123456789"),
    ("GET", "/clip.mp4", "bytes=2-5", 206, "bytes 2-5/10", 4, b"2345"),
    ("GET", "/clip.mp4", "bytes=7-", 206, "bytes 7-9/10", 3, b"789"),
    ("GET", "/clip.mp4", "bytes=-3", 206, "bytes 7-9/10", 3, b"789"),
    ("GET", "/clip.mp4", "bytes=8-99", 206, "bytes 8-9/10", 2, b"89"),
    ("HEAD", "/clip.mp4", "bytes=2-5", 206, "bytes 2-5/10", 4, b""),
    ("GET", "/clip.mp4", "bytes=10-", 416, "bytes */10", 0, b""),
    ("GET", "/clip.mp4", "bytes=5-2", 416, "bytes */10", 0, b""),
    ("GET", "/clip.mp4", "bytes=-0", 416, "bytes */10", 0, b""),
    ("GET", "/empty.mp4", "bytes=0-", 416, "bytes */0", 0, b""),
])
def test_video_ranges_over_http(video_server, method, path, value, status, content_range, length, body):
    client = http.client.HTTPConnection("127.0.0.1", video_server, timeout=5)
    try:
        client.request(method, path, headers={"Range": value} if value else {})
        response = client.getresponse()
        assert response.status == status
        assert response.getheader("Accept-Ranges") == "bytes"
        assert response.getheader("Content-Range") == content_range
        assert int(response.getheader("Content-Length")) == length
        assert response.read() == body
    finally:
        client.close()
