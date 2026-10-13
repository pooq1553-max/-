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
