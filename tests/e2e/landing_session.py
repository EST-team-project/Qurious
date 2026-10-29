"""격리 앱의 실제 HTTP 가입·로그인·로그아웃과 첫 화면 이동을 확인한다."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    database_url = urlparse(os.environ["DATABASE_URL"])
    assert database_url.hostname == "test-db"
    db = database_url.path.lstrip("/")
    assert db.startswith("qurious_operations_") and db.endswith("_test")
    assert urlparse(os.environ["REDIS_URL"]).hostname == "operations-redis"
    from app.routes.auth import TERMS_VERSION, REQUIRED_AGREEMENTS
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    checks = []
    with (out / "landing-server.log").open("w") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "18000"],
            env={**os.environ, "RUN_MIGRATIONS_ON_STARTUP": "false"}, stdout=log, stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url="http://127.0.0.1:18000", timeout=10,
                              headers={"Origin": "http://127.0.0.1:18000"}) as client:
                for _ in range(60):
                    assert process.poll() is None, "app exited during startup"
                    try:
                        if client.get("/api/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(.5)
                else:
                    raise AssertionError("app startup timeout")
                response = client.get("/")
                assert response.status_code == 200 and 'id="intro-skip"' in response.text
                checks.append("logged_out_root_is_landing")
                response = client.get("/index.html")
                assert response.status_code == 307 and response.headers["location"] == "/"
                checks.append("index_alias_redirects_to_root")
                email = uuid.uuid4().hex + "@example.com"
                password = "Synthetic-session-test-129!"
                response = client.post("/api/auth/register", json={"email": email, "password": password,
                    "name": "세션시험", "birth_date": "1990-01-01", "terms_version": TERMS_VERSION,
                    "agreed": list(REQUIRED_AGREEMENTS)})
                assert response.status_code == 200, ("signup", response.status_code)
                for path in ("/", "/login.html", "/register.html"):
                    response = client.get(path)
                    assert response.status_code == 307 and response.headers["location"] == "/app.html", path
                assert client.get("/app.html").status_code == 200
                checks.append("real_signup_session_redirects_root_login_register_to_app")
                assert client.post("/api/auth/logout").status_code == 200
                response = client.get("/")
                assert response.status_code == 200 and 'id="intro-skip"' in response.text
                checks.append("logout_returns_to_landing")
                response = client.post("/api/auth/login", json={"email": email, "password": password})
                assert response.status_code == 200, ("login", response.status_code)
                response = client.get("/", follow_redirects=True)
                assert response.status_code == 200 and response.url.path == "/app.html"
                checks.append("real_login_and_redirect_chain_reaches_app")
                client.cookies.clear()
                response = client.get("/", headers={"Cookie": "fin_session=invalid-synthetic-session"})
                assert response.status_code == 200 and 'id="intro-skip"' in response.text
                checks.append("invalid_session_returns_to_landing")
            result = {"ok": True, "checks": checks, "production_changed": False}
            (out / "landing-result.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result))
        finally:
            process.terminate()
            process.wait(timeout=15)


if __name__ == "__main__":
    main()
