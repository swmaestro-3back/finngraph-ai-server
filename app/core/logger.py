import logging
import os
import sys
from pathlib import Path

# 파일 로그 저장 위치 (LOG_TO_FILE이 켜진 로컬 개발에서만 사용).
#   - LOG_DIR 환경변수가 있으면 그 경로
#   - 없으면 프로젝트 루트의 logs/
_DEFAULT_LOG_ROOT = Path(__file__).parents[2] / "logs"
_LOG_ROOT = Path(os.environ.get("LOG_DIR", _DEFAULT_LOG_ROOT))


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# 파일 로그 여부.
#   - 로컬 개발: 기본 True → info/debug/error.log 파일 생성 (디버깅 편의)
#   - 컨테이너: LOG_TO_FILE=false → stdout으로만 출력 (12-factor 표준).
#     로그 수집/로테이션/보관은 Docker/K8s 등 런타임이 책임진다.
_LOG_TO_FILE = _env_flag("LOG_TO_FILE", default=True)

# 콘솔(stdout) 로그 레벨. 운영 중 LOG_LEVEL=DEBUG 등으로 조절 가능.
_CONSOLE_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

_FORMATTER = logging.Formatter(
    "[%(asctime)s] [%(module)s] [%(levelname)s] %(message)s",
    "%Y-%m-%d %H:%M:%S",
)

# uvicorn --reload 등으로 setup_logging이 두 번 호출돼도 handler가 중복 등록되지 않게 한다.
_configured = False


def setup_logging() -> None:
    """애플리케이션 시작 시 한 번만 호출한다.

    root logger에 handler를 붙여, 각 모듈에서 logging.getLogger(__name__)로 얻은
    logger가 별도 설정 없이 이 handler들을 통해 출력되게 한다 (propagation).

    로그는 항상 stdout으로 흘려보낸다(컨테이너 표준). LOG_TO_FILE이 켜진
    로컬 개발에서만 부가적으로 파일에도 남긴다.
    """
    global _configured
    if _configured:
        return

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 콘솔(stdout) — 컨테이너에서는 `docker logs`로 수집되는 유일한 경로.
    # logging.StreamHandler는 레코드마다 flush하므로 PYTHONUNBUFFERED 없이도 실시간 출력된다.
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(_CONSOLE_LEVEL)
    console_handler.setFormatter(_FORMATTER)
    root_logger.addHandler(console_handler)

    # 파일 로그는 로컬 개발 편의용. 컨테이너(LOG_TO_FILE=false)에서는 붙이지 않는다.
    if _LOG_TO_FILE:
        _LOG_ROOT.mkdir(parents=True, exist_ok=True)

        # DEBUG 이상 전부 debug.log에 저장
        debug_handler = logging.FileHandler(_LOG_ROOT / "debug.log", encoding="utf-8")
        debug_handler.setLevel(logging.DEBUG)
        debug_handler.setFormatter(_FORMATTER)

        # INFO 이상은 info.log에 저장
        info_handler = logging.FileHandler(_LOG_ROOT / "info.log", encoding="utf-8")
        info_handler.setLevel(logging.INFO)
        info_handler.setFormatter(_FORMATTER)

        # ERROR 이상은 error.log에 저장
        error_handler = logging.FileHandler(_LOG_ROOT / "error.log", encoding="utf-8")
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(_FORMATTER)

        root_logger.addHandler(debug_handler)
        root_logger.addHandler(info_handler)
        root_logger.addHandler(error_handler)

    _configured = True
