# 시험지-hwp변환

공개 테스트용 최소 웹앱입니다.

기능은 단순합니다.

- PDF 시험지 업로드
- AI로 수학 문항, 보기, 정답, 짧은 해설 추출
- HWPX 파일 다운로드
- 수식 조각은 HWPX equation 스크립트로 저장

공개 테스트용으로 새로 작성한 최소 구현만 포함합니다.

## 로컬 실행

Node.js 20 이상과 Python 3이 필요합니다.

```bash
cp .env.example .env
# .env의 AI_API_KEY 값을 입력
npm start
```

브라우저에서 `http://localhost:3025`를 엽니다.

## 환경변수

| 이름 | 설명 |
| --- | --- |
| `AI_API_KEY` | PDF 분석에 사용할 API 키 |
| `AI_MODEL` | 분석 모델. 기본값은 `.env.example` 참고 |
| `PORT` | 웹 서버 포트. 기본값 `3025` |
| `PYTHON` | Python 실행 파일 경로. 기본값은 OS에 따라 자동 선택 |

## Render 배포

1. 이 저장소를 GitHub에 push합니다.
2. Render에서 **New + → Blueprint**를 선택합니다.
3. GitHub 저장소를 연결합니다.
4. `AI_API_KEY`를 Render 환경변수에 비밀값으로 등록합니다.
5. 배포 후 `/` 페이지에서 PDF 업로드를 테스트합니다.

`render.yaml`과 `Dockerfile`이 포함되어 있어 Render가 Docker Web Service로 빌드합니다.

## 공개 배포 주의

- `.env`, `.env.local`, `tmp/`는 `.gitignore`에 포함되어 있습니다.
- 업로드된 PDF와 생성된 HWPX는 서버의 임시 작업 폴더에만 저장됩니다.
- 무료 Render 인스턴스는 파일 저장이 영구 보존되지 않을 수 있습니다.
