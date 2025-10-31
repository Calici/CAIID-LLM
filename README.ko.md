# Drug Researcher

Drug Researcher는 FastAPI 백엔드, Next.js 인터페이스, 선택적인 로컬 LLM 런타임을 하나의 Docker 기반 작업공간으로 묶은 프로젝트입니다. 이 문서는 `docker-compose.yml`에서 조정할 수 있는 항목, 데이터가 저장되는 위치, Lite/Heavy 실행 방법을 안내합니다.

## 사전 준비
- Docker 24+ 및 Compose v2
- Heavy 모드 옵션: NVIDIA Container Toolkit( GPU 가속 LLaMA 서버용)
- 저장소를 서브모듈까지 포함해 클론합니다: `git clone https://github.com/Calici/mindblowing-llm --recurse-submodules`

## Lite 모드 빠른 시작
1. 프로젝트 루트에서 백엔드가 필요로 하는 시크릿을 export 합니다(예: `export OPENAI_API_KEY=sk-...`).
2. (선택) 포트나 저장 경로를 바꾸려면 `.env` 파일을 만들어 `docker-compose.yml`과 같은 위치에 저장합니다.
3. 프런트엔드와 백엔드만 빌드 및 기동합니다.  
   `docker compose up --build chat-backend chat-frontend`
4. 브라우저에서 `http://localhost:3000`을 열고 백엔드가 `http://localhost:8000`에서 응답하는지 확인합니다.
5. 종료할 때는 `Ctrl+C`로 중단한 뒤 `docker compose down`으로 컨테이너를 정리합니다.

## 환경 변수와 포트 오버라이드

아래 예시는 인라인으로(`APP_DB_PATH=/mnt/prod.db docker compose up`) 실행하거나 저장소 루트에 `.env` 파일을 만들어 적용할 수 있습니다. `docker-compose.yml`이 이미 해당 변수들을 참조하므로, Compose가 값을 자동으로 치환합니다.

### `chat-backend` 서비스
- **환경 변수**: `APP_DB_PATH`, `APP_DATA_PATH`, `APP_ASSETS_PATH`를 설정하여 SQLite 및 생성 파일을 다른 마운트 위치에 보관할 수 있습니다. 예시 `.env` 내용:  
  ```
  APP_DB_PATH=/data/prod.db
  APP_DATA_PATH=/data
  APP_ASSETS_PATH=/assets
  ```
  이후 `docker compose up chat-backend`를 실행하면 백엔드가 새로운 경로를 사용합니다.
- **포트**: 호스트 포트를 겹치지 않도록 변경합니다. Compose 파일에서 `- "18000:8000"`처럼 수정하거나 `CHAT_BACKEND_PORT=18000`을 export 한 뒤, 항목을 `- "${CHAT_BACKEND_PORT:-8000}:8000"` 형태로 변경해 환경별로 손쉽게 바꿀 수 있습니다.

### `chat-frontend` 서비스
- **환경 변수**: `NEXT_PUBLIC_API_URL`을 덮어써 UI가 원격 백엔드와 통신하도록 합니다.  
  ```
  NEXT_PUBLIC_API_URL=https://api.example.com
  ```
  `docker compose up --build chat-frontend`로 재빌드하여 Next.js가 새 값을 반영하도록 합니다.
- **포트**: UI 포트를 다시 매핑하려면 Compose 항목을 `- "${FRONTEND_PORT:-3000}:3000"`으로 바꾸고 `FRONTEND_PORT=3300 docker compose up chat-frontend`처럼 실행합니다. 컨테이너 내부는 3000을 유지하면서 호스트에선 다른 포트를 노출합니다.

### `llama` 서비스
- **환경 변수**: `LLAMA_ARG_*` 항목은 모두 CLI 플래그로 전달됩니다. HTTP 서버 포트를 8181로 옮기고 다른 모델을 사용하려면 다음과 같이 설정합니다.  
  ```
  LLAMA_ARG_PORT=8181
  LLAMA_ARG_MODEL=/llm-models/llama-3-8b.gguf
  ```
  해당 모델 경로가 존재하도록 볼륨 매핑을 조정한 뒤 `docker compose up llama`를 실행합니다.
- **포트**: 호스트 포트도 새 값과 맞추려면 매핑을 `- "8181:8181"`로 수정하거나 `- "${LLAMA_PORT:-8080}:${LLAMA_ARG_PORT:-8080}"`처럼 파라미터화하여 환경별로 쉽게 변경할 수 있습니다.

### Compose 활용 팁
- `docker compose up chat-backend chat-frontend`처럼 필요한 서비스만 지정하면, 설정한 오버라이드가 적용된 상태로 사용하지 않는 컨테이너를 띄우지 않을 수 있습니다.
- 환경별 설정은 `env.development`, `env.staging` 등으로 저장한 뒤 `docker compose --env-file env.staging up`으로 필요한 파일을 선택해 로드합니다.

## 데이터 저장 구조
- `./data`(호스트) ↔ `/data`(백엔드 컨테이너): SQLite `local.db`와 백엔드가 생성하는 파일이 저장됩니다. 다른 경로나 관리형 볼륨을 쓰고 싶다면 `docker-compose.yml`의 볼륨 항목을 바꿉니다.
- `APP_DB_PATH`, `APP_DATA_PATH`, `APP_ASSETS_PATH`: 백엔드가 읽고 쓰는 경로를 정의합니다. 클라우드 스토리지나 별도 마운트를 사용하려면 이 변수들을 새로운 경로로 덮어씁니다.
- `./models`(호스트) ↔ `/llm-models`(llama 컨테이너): `.gguf` 모델 가중치를 보관합니다. 모델마다 서브 폴더를 만들고 Compose 볼륨 경로만 바꾸면 신속하게 다른 모델로 교체할 수 있습니다.
- `chat-frontend/.next` 출력물은 이미지 안에 포함됩니다. 업로드나 캐시를 유지하려면 `chat-frontend` 서비스에 별도의 `volumes` 항목을 추가해 원하는 경로에 호스트 디렉터리를 매핑하세요.

## 실행 모드

### Lite 모드 (프런트엔드 + 백엔드)
1. 실행 전에 필요한 백엔드 API 키를 export 합니다(예: `export OPENAI_API_KEY=...`).
2. UI와 API만 빌드 및 실행합니다.  
   `docker compose up --build chat-backend chat-frontend`
3. `http://localhost:3000`에 접속하면 프런트엔드가 기본값으로 `http://localhost:8000`에 있는 백엔드와 통신합니다.

### Heavy 모드 (프런트엔드 + 백엔드 + 로컬 LLaMA 서버)
1. 호스트에 GPU 드라이버와 NVIDIA Container Toolkit이 준비되어 있어야 합니다.
2. 사용할 `.gguf` 모델을 `./models` 아래에 두고, 필요하다면 `docker-compose.yml`의 볼륨 경로를 수정합니다.
3. 필요한 경우 llama 이미지를 재빌드하면서 모든 서비스를 기동합니다.  
   `docker compose up --build`
4. LLaMA HTTP 서버는 `http://localhost:8080`에서 대기합니다. 백엔드가 해당 주소를 참조하도록 환경 변수나 서비스 디스커버리 설정을 조정하세요.

모든 서비스를 종료하려면 `docker compose down`을 사용합니다. `--volumes` 옵션을 추가하면 `./data`에 저장된 SQLite 데이터베이스와 캐시를 함께 삭제할 수 있습니다.
