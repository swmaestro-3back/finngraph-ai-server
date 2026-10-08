"""ETL Postgres 조회 — 커넥션을 받아 행(dict)만 돌려준다.

커넥션 수명·실패 처리·응답 모델 조립은 호출하는 쪽(service) 소관이다.
값은 응답 모델이 그대로 받도록 Decimal → float, date/datetime → ISO 문자열로 바꿔 돌려준다.
입력은 전부 %(name)s 파라미터로만 나간다.
"""

from .base import plain
from .disclosure import fetch_disclosure_briefs
from .event import fetch_event_detail, fetch_event_meta
from .news import fetch_news_briefs
from .quote import fetch_stock_quotes, fetch_theme_quotes

__all__ = [
    "plain",
    "fetch_disclosure_briefs",
    "fetch_event_detail",
    "fetch_event_meta",
    "fetch_news_briefs",
    "fetch_stock_quotes",
    "fetch_theme_quotes",
]
