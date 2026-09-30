"""시험이 저장소 루트의 `app` 패키지를 찾게 한다 (CI 는 `pytest tests/` 로 돌린다)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
