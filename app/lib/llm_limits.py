"""답을 만드는 LLM 호출의 출력 상한 · 문맥 창 — 값은 설정(app/config.py) 한 곳에서 읽는다.

왜 따로 두나 (2026-10-08 · 강사님 th06 e815be3 반영)
- 강사님 10-07 판은 에이전트 답 · 그래프 RAG · RAG 체인의 출력 상한을 2048 / 3000 → 256토큰, 문맥 창을 2048 로
  줄였다(GPU 없는 서버에서 빨리 답하려고). 세 파일에 글자로 박혀 있다.
- 이 PC(llama3.1)에서 답 노드와 같은 프롬프트로 표본 3문항을 재니 자연 길이가 454 · 684 · 579토큰이었고,
  256 에서는 셋 다 문장 중간에 끊겼으며 끝의 「투자 권유 아님」 고지가 있던 두 답에서 모두 사라졌다.
- 그래서 값은 설정 두 칸(LLM_ANSWER_NUM_PREDICT · LLM_NUM_CTX)에 두고, 강사님 파일 세 곳은 이 함수를 부르는
  한 줄씩만 바꾼다 — 다음 반영 때 갈리는 곳을 줄인다. 판단(JSON 한 줄) 노드는 강사님 256 그대로 둔다.
"""
from app.config import settings


def answer_options() -> dict:
    """Ollama 옵션 조각. 문맥 창이 0 이면 넣지 않는다(Ollama 기본 · 반영 전과 같음)."""
    opts: dict = {"num_predict": int(settings.LLM_ANSWER_NUM_PREDICT)}
    if int(settings.LLM_NUM_CTX) > 0:
        opts["num_ctx"] = int(settings.LLM_NUM_CTX)
    return opts
