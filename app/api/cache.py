"""브라우저 캐시 헤더 — kg-api 응답은 사용자별 데이터가 아니고 인증도 없으므로 브라우저가 잠시 쥐고 있어도 된다.

`private` 로 두어 브라우저만 캐시한다(CDN·게이트웨이는 쿼리 문자열 키 설정을 따로 보장하지 않는다).
`stale-while-revalidate` 는 만료 직후 요청을 옛 응답으로 바로 그리고 뒤에서 새로 받게 한다.
오류 응답(404·503)에는 붙이지 않는다 — 라우트가 성공 경로에서만 부른다.

예산은 데이터가 실제로 바뀌는 주기에서 온다:
- 그래프(시세 포함)·이벤트 상세(관련 기업 시세 포함): ETL 이 장중 매시간 일봉·등락률을 다시 계산한다.
  클라이언트 메모리 캐시(AUTO_REFRESH_MS, 5분)와 같은 주기로 둔다 — 최악의 경우 둘이 겹쳐 10분 전 시세다.
- 간선 근거(기사 제목·발행일·공시 접수일): 관계가 다시 적재될 때만 바뀌고 기사 행 자체는 불변이다.
"""

from __future__ import annotations

from fastapi import Response

GRAPH_MAX_AGE = 300
EVENT_MAX_AGE = 300
EVIDENCE_MAX_AGE = 600


def cache_control(max_age: int, stale: int | None = None) -> str:
    """Cache-Control 값. stale 이 None 이면 max_age 만큼 더 stale-while-revalidate 를 준다."""
    stale = max_age if stale is None else stale
    value = f"private, max-age={max_age}"
    if stale > 0:
        value += f", stale-while-revalidate={stale}"
    return value


def cacheable(response: Response, max_age: int, stale: int | None = None) -> None:
    response.headers["Cache-Control"] = cache_control(max_age, stale)
