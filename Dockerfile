# Dockerfile은 이미지를 빌드하기 위한 스크립트를 작성하는 곳
# 내 어플리케이션에 대한 이미지는 내가 직접 빌드해야하기 때문에 스크립트가 존재할 수 밖에 없음

FROM python:3.14-slim

# uv 설치 (astral 공식 이미지에서 바이너리만 복사해 별도 설치 단계 없이 사용)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 컨테이너에서는 파일 로그를 남기지 않고 stdout으로만 출력한다(12-factor 표준).
# 로그 수집/로테이션/보관은 Docker/K8s 등 런타임이 책임진다.
ENV LOG_TO_FILE=false

WORKDIR /app

# 의존성 먼저 설치해 레이어 캐시를 활용 (소스만 바뀔 땐 재설치 스킵).
# --frozen: uv.lock 그대로 설치, --no-dev: dev 그룹 제외,
# --no-install-project: 로컬 패키지는 설치하지 않음(아래에서 경로로 직접 실행하므로 불필요).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-build

# 애플리케이션 소스
COPY app ./app

# 최상위 import(`from core import ...`)가 동작하도록 app/ 를 작업 디렉토리로 둔다
WORKDIR /app/app

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]