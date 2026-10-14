# 쇼츠 자동화 — 처음 쓰는 법 (윈도우)

## 1. 받기 (처음 한 번)
1. 깃허브에서 압축 파일(.zip)을 받습니다.
2. **압축 파일을 오른쪽 클릭 → 속성 → 아래쪽 '차단 해제' 체크 → 확인** (인터넷에서 받은 파일이라 경고가 뜨는 것을 막아 줌)
3. 압축을 풀고, 나온 폴더를 **`C:\shorts`** 로 옮기고 이름도 shorts 로 바꿉니다.
   - 바탕화면·다운로드 폴더처럼 경로가 길거나 한글이 들어간 곳에 두면 설치가 실패할 수 있습니다.

## 2. 켜기
1. `C:\shorts` 안의 **`시작하기.bat`** 을 두 번 클릭합니다.
   - "Windows의 PC 보호" 파란 창이 뜨면 **추가 정보 → 실행** 을 누릅니다.
2. 처음 한 번은 알아서 준비합니다 (10분 안팎).
   - 파이썬 3.12, 영상 도구(ffmpeg)가 없으면 자동으로 설치합니다. 설치 창이 뜨면 '예'를 눌러 주세요.
   - 필요한 부품과 목소리 자료(약 150MB)를 내려받습니다.
   - 바탕화면에 **'쇼츠 자동화' 바로가기**를 만듭니다. 다음부터는 이걸 두 번 클릭하면 됩니다.
3. 준비가 끝나면 브라우저에 화면이 저절로 열립니다. 안 열리면 주소창에 `http://127.0.0.1:8000` 을 입력하세요.
4. 끌 때는 까만 창을 닫습니다.

## 3. 화면에서 하는 순서
1. 제미나이 키 붙여 넣고 **키 저장** (처음 한 번)
2. 원본 영상 **올리기**
3. 설명글 붙여 넣고 **설명글 저장**
4. **제작 시작** → 1분쯤 기다리면 영상 3개가 나옵니다
5. 정보가 틀렸으면 고치고 **수정 반영해서 다시 만들기**
6. 영상을 보고, C형은 목소리도 들어 본 뒤 **최종 승인**

## 잘 안 될 때
- 까만 창에 나온 안내를 따라 주세요. 그래도 안 되면 까만 창을 사진으로 찍어 보내 주세요.
- 다시 만들기가 "파일을 다른 프로그램이 쓰고 있어" 로 실패하면, 화면에서 재생 중인 영상·음성을 멈추고 다시 누르세요.
- 맥은 `시작하기.command` 를 쓰면 됩니다 (처음엔 오른쪽 클릭 → 열기).

---

# 쇼츠 자동화 폴더 구조

| 폴더 | 넣을 것 | 누가 채우나 |
|---|---|---|
| `input/` | 원본 재료: 원본 영상(.mp4), 이미지, 대본/원고 텍스트(.txt), 자막 파일(.srt) | 사람이 직접 넣음 |
| `scripts/` | 자동화 프로그램 코드(.py 등): 영상 자르기, 자막 입히기, TTS, 합치기 | 개발 |
| `audio/` | 배경음악(BGM), 효과음, TTS로 만든 내레이션 음성(.mp3/.wav) | 사람 + 프로그램 |
| `frames/` | 작업 중 생기는 중간 파일: 추출한 프레임, 썸네일 후보, 임시 이미지 | 프로그램 (지워도 됨) |
| `output/` | 완성된 쇼츠 영상(1080×1920 세로 .mp4)과 썸네일 | 프로그램 |
| `backup/` | 업로드한 완성본이나 중요 원본의 사본 (날짜별 하위 폴더 권장, 예: `backup/2026-10-13/`) | 프로그램 또는 사람 |

## 작업 흐름

```
input/ (원본) ─┐
audio/ (소리) ─┼─▶ scripts/ (처리) ─▶ frames/ (임시) ─▶ output/ (완성) ─▶ backup/ (보관)
```

## 참고

- `input`, `audio`, `frames`, `output`, `backup` 안의 파일은 용량 때문에 git에 올라가지 않습니다(`.gitignore`). 코드(`scripts/`)만 저장소에 저장됩니다.
- `frames/`는 임시 폴더라 작업이 끝나면 비워도 됩니다.

## API 키 (.env)

- 키는 프로젝트 맨 위의 `.env` 파일에만 적습니다. `.env.example`을 복사해 `.env`로 이름을 바꾸고 `GEMINI_API_KEY=` 뒤에 키를 붙여 넣으세요.
- `.env`는 `.gitignore`에 들어 있어 GitHub에 올라가지 않습니다.
- 코드에서는 `scripts/config.py`의 `get_gemini_api_key()`로만 키를 읽습니다.
- 확인: `python scripts/check_key.py` → `키가 들어 있음, 글자 수 N개` (키 내용은 표시하지 않음)

## 1단계 실행: 원본 영상 → 30초 세로 쇼츠

준비(한 번만): `python3 -m venv .venv` 후 `.venv/bin/pip install -r requirements.txt` (Windows는 `.venv\Scripts\pip`), ffmpeg 설치.

1. 영상을 `input/원본.mp4` 로 넣습니다.
2. 실행: `.venv/bin/python scripts/step1.py --text "자막 문구"` (Windows: `.venv\Scripts\python scripts\step1.py --text "자막 문구"`)
3. 결과: `output/step1.mp4` (1080x1920, 30fps, H.264, 최대 30초)

- `--text`를 안 주면 `input/자막.txt`의 첫 줄, 그것도 없으면 기본 문구를 씁니다.
- 원본이 30초보다 짧으면 그 길이만큼만 만듭니다. 가로 영상은 확대 후 가운데를 잘라 양옆이 잘립니다.

## 2단계 실행: 장면 나누기 → frames/ 사진 + output/scenes.json

실행: `.venv/bin/python scripts/scenes.py` (Windows: `.venv\Scripts\python scripts\scenes.py`)

- `frames/scene_001_a.jpg`, `_b.jpg` …: 장면마다 대표 사진 2장 (장면의 1/3, 2/3 지점)
- `frames/한눈에보기.jpg`: 모든 대표 사진을 한 장에 모은 것 (제외된 장면은 빨간 X)
- `output/scenes.json`: 장면마다 `idx`, `start`/`end`(초), `shot_type`(고정/움직임/빠른 움직임), `description`(지금은 빈칸),
  `features`(sharpness 선명도, brightness 밝기, saturation 채도, warmth 따뜻함, motion 움직임), `excluded`(제외 여부)와 이유
- 장면이 너무 잘게/크게 나뉘면 `--threshold` 숫자를 바꿉니다 (낮을수록 잘게, 기본 27).
- 장면을 읽는 방식은 `scripts/scene_analyzers.py`에 있습니다. 나중에 AI 분석기를 여기에 추가하고 `--analyzer 이름`으로 고릅니다.

## 3단계 실행: 설명글에서 정보 뽑기 → data/facts.json

1. `input/description.txt` 에 영상 설명글을 붙여 넣고 저장합니다.
2. 뽑을 항목은 `config/fields.txt` 에 한 줄에 하나씩 적습니다 (지금은 음식 예시: 가게명, 메뉴명, 가격, 지역, 특징).
3. 실행: `.venv/bin/python scripts/extract_facts.py` (다른 항목 파일: `--fields config/여행.txt`)

- 항목마다 `value`, `evidence`(설명글에서 그대로 옮긴 근거), `status`, `reason` 이 저장됩니다.
- 근거가 설명글에 글자 그대로 없거나, 값이 근거 안에 없으면 `value`를 비우고 `status: "확인 필요"`로 둡니다.
- Gemini 호출이 실패하면 기존 `data/facts.json`은 그대로 둡니다.
- **"설명글에 있음"은 설명글에 그렇게 적혀 있다는 뜻이지, 사실이라는 뜻이 아닙니다.**
- 테스트: `.venv/bin/python -m unittest discover -s tests -v`

## 4단계 실행: 제목·자막·내레이션 대본 (A/B/C형)

실행: `.venv/bin/python scripts/make_scripts.py` (입력: `output/scenes.json`, `data/facts.json`)

| 형식 | 파일 | 내용 |
|---|---|---|
| A형 | `output/script_A.json` / `.txt` | 짧은 자막 중심, 장면 보여 주기 (음성 없음) |
| B형 | `output/script_B.json` / `.txt` | 다른 훅(질문으로 시작 → 답), 다른 자막 구성 (음성 없음) |
| C형 | `output/script_C.json` / `.txt` | 내레이션 + 자막 해설 (장면보다 긴 내레이션은 ⚠ 표시) |

- 문장은 `config/templates.json`의 문장 틀 + '설명글에 있음' 값으로만 만듭니다 (AI 사용 안 함).
- 틀에 숫자를 직접 적으면 실행이 거부되고, 결과에 검증 안 된 숫자·'확인 필요' 값이 있으면 저장하지 않습니다.
- 셋 중 하나라도 실패하면 아무 파일도 바꾸지 않습니다.
- 시험해 보기: `--facts tests/fixtures/facts_food.json --scenes tests/fixtures/scenes_6.json`

## 5~7단계: 음성 → 렌더링 → 웹 화면

### 처음 한 번 준비
```
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/download_models.py     # 로컬 음성(TTS)·받아쓰기(STT) 모델 약 150MB → models/
```

### 웹 화면으로 하기 (추천)
```
.venv/bin/python scripts/run_web.py             # 브라우저에서 http://127.0.0.1:8000
```
원본 영상 올리기 → 설명글 저장 → **제작 시작** → 진행 상황 → 영상 3개 미리보기 → 정보 수정 → 최종 승인.
- 개발 모드: `scripts/`, `web/` 의 .py 를 고치면 서버가 자동 재시작. `web/index.html` 은 새로고침만 하면 반영.
- 재시작이 필요한 경우: `pip install` 로 새 패키지를 깔았을 때, `--no-reload` 로 켰을 때 코드를 고쳤을 때.
- 자동 재시작이나 강제 종료로 제작이 멈추면, 다시 켰을 때 '중단됨'으로 표시되고 **이어서 하기**로 남은 단계부터 다시 합니다.

### 명령으로 하기
| 단계 | 명령 | 결과 |
|---|---|---|
| 음성 | `scripts/voice.py` | `audio/C/cue_XX.wav`, `voice_report.json` (받아쓰기 비교, 차이가 크면 '검토 필요') |
| 렌더링 | `scripts/render.py` | `output/shorts_A·B·C.mp4`, `frames/review/<형식>/` 확인용 프레임, `output/render_report.json` |
| 백업 | `scripts/backup_tool.py create` / `list` / `verify 이름` / `restore 이름` | `backup/<날짜>/` (API 키·영상·모델 제외) |

- 음성 엔진과 받아쓰기 엔진은 `config/voice.json` 에서 따로 바꿉니다 (`sherpa_kss` / `supertonic`, `sherpa_zipformer_ko`).
- 자막 크기·위치·안전 여백(유튜브 버튼에 가리지 않는 영역)은 `config/render.json`.
- 한 형식 렌더링이 실패해도 다른 형식과 이전에 완성된 파일은 지우지 않습니다. 오류는 `render_report.json` 과 `data/logs/app.log` 에 남습니다.
- **자동 비교는 발음 품질을 보장하지 못합니다. 최종 음성은 반드시 직접 들어 보세요.**

### 테스트
```
.venv/bin/python -m unittest discover -s tests -v
```
