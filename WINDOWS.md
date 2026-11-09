# Windows 설치 가이드

로컬 Windows PC에서 face swap 돌리는 방법. 사진이 어디로도 안 올라감.

## 원클릭 방법 (추천)

1. 이 레포를 ZIP으로 받아 압축 풀기
   (GitHub → Code 버튼 → Download ZIP → `Documents\faceswap-app` 같은 곳에 압축 해제)
2. 폴더 안에서 **`setup.bat` 더블클릭** — Python·라이브러리·모델을 자동으로 설치하고 바탕화면에 아이콘을 만들어 줍니다. 5~10분 걸림.
3. 이후엔 언제든 **바탕화면의 "FaceSwap" 아이콘 더블클릭** → 앱 창이 열림. 사진을 고르고 **스왑 실행** 버튼을 누르면 결과가 표시됨.

`setup.bat` 중 Python이 없어서 winget으로 자동 설치가 되면 안내 메시지가 뜨는데, 그때는 **새 명령창을 열어 setup.bat을 한 번 더 실행**하면 됩니다.

## 다른 컴퓨터로 옮기기

폴더를 통째로 복사하지 마세요. `.venv` 안에는 이전 컴퓨터의 경로가 박혀
있어서 옮기면 깨집니다. 새로 설치하는 편이 빠르고 확실합니다.

**새 컴퓨터에서**: 위 원클릭 방법 그대로 (ZIP 받기 → `setup.bat`). 끝입니다.

**옛 컴퓨터에서 챙길 것은 내가 만든 사진·영상뿐입니다.** 나머지는 전부
다시 받아집니다.

| 무엇 | 옮기나 | 왜 |
|---|---|---|
| 내 사진·영상·결과물 | **반드시 복사** | 다시 만들 수 없음 |
| `models\` 폴더 (약 900MB) | 선택 | 복사하면 다운로드 시간을 아낌 |
| 소스 코드 | 안 해도 됨 | GitHub에서 받음 |
| `.venv\` | **복사 금지** | 경로가 박혀 있어 깨짐 |
| `%USERPROFILE%\.insightface\` | 안 해도 됨 | 첫 실행 때 자동으로 받음 |

인터넷이 느리다면 `models\` 폴더만 USB로 옮겨두고, 새 컴퓨터에서 압축을
푼 폴더 안에 같은 위치로 넣은 뒤 `setup.bat`을 실행하세요. 이미 있는
모델은 다시 받지 않습니다.

## 수동 설치 (원클릭이 안 될 때)

## 1. Python 설치

**Python 3.11** 을 권장 (3.12+ 는 insightface 설치가 자주 깨짐).

1. https://www.python.org/downloads/windows/ 에서 **Python 3.11.x** 설치 파일 다운로드
2. 설치할 때 **"Add python.exe to PATH"** 체크박스 반드시 체크
3. 설치 후 PowerShell 열고 확인:
   ```powershell
   python --version
   ```
   `Python 3.11.x` 나오면 OK.

## 2. 코드 받기

**옵션 A — Git 있으면**
```powershell
cd $HOME
git clone -b claude/face-swap-program-mts7mz https://github.com/pooq1553-max/-.git faceswap-app
cd faceswap-app
```

**옵션 B — Git 없으면**
1. GitHub 브라우저에서 `claude/face-swap-program-mts7mz` 브랜치 열기
2. 초록색 **Code** 버튼 → **Download ZIP**
3. 압축 풀고 `Documents\faceswap-app` 같은 곳에 폴더 이동
4. PowerShell에서:
   ```powershell
   cd $HOME\Documents\faceswap-app
   ```

## 3. 가상환경 만들기 (선택이지만 권장)

시스템 파이썬을 오염시키지 않기 위해:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

만약 `Activate.ps1` 실행이 정책 때문에 막히면 한 번만:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
그러고 다시 `Activate.ps1` 실행. 프롬프트 앞에 `(.venv)` 붙으면 성공.

## 4. 라이브러리 설치

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

이 단계에서 약 300~500MB 다운로드됨. 5~10분 걸림.

만약 `insightface` 설치 중 `error: Microsoft Visual C++ 14.0 or greater is required` 나오면:
- https://visualstudio.microsoft.com/visual-cpp-build-tools/ 에서 Build Tools 설치
- "Desktop development with C++" 워크로드 체크해서 설치
- 이후 위 `pip install` 다시 실행

## 5. 스왑 모델 다운로드

```powershell
python download_models.py
```

`models\inswapper_128.onnx` (~554MB) 가 받아짐. 처음 한 번만.

## 6. 사용

```powershell
# 사진 두 장 준비 (예: face.jpg, body.jpg 를 프로젝트 폴더에 넣기)
python -m faceswap -s face.jpg -t body.jpg -o out.jpg
```

- `-s face.jpg` : 얼굴 **가져올** 사진
- `-t body.jpg` : 얼굴 **바꿀** 사진 (몸/배경)
- `-o out.jpg` : 결과 저장 경로

첫 실행 시 InsightFace 검출기 모델(buffalo_l, ~300MB)이 `%USERPROFILE%\.insightface\` 에 자동 다운로드됨. 그 후엔 오프라인 동작.

### 옵션

```powershell
# 타깃에 여러 명이 있어도 제일 큰 얼굴 하나만 교체
python -m faceswap -s face.jpg -t group.jpg -o out.jpg --target-face largest

# 타깃의 두번째 얼굴만 (0부터 시작)
python -m faceswap -s face.jpg -t group.jpg -o out.jpg --target-face index --target-face-index 1

# GPU 사용 (NVIDIA 그래픽카드 + CUDA 필요)
pip install onnxruntime-gpu
python -m faceswap -s face.jpg -t body.jpg -o out.jpg --device cuda
```

## 다음번 사용

터미널 새로 열면:
```powershell
cd $HOME\Documents\faceswap-app
.\.venv\Scripts\Activate.ps1
python -m faceswap -s face.jpg -t body.jpg -o out.jpg
```
설치/모델 다운은 다시 안 해도 됨.

## 자주 나오는 문제

### 앱이 아예 안 열림

검은 창에 빨간 글씨가 뜨고 닫힘.

- **`ModuleNotFoundError: No module named '...'`**
  → 라이브러리가 빠졌습니다. 폴더에서 터미널을 열고:
  `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`
- **`SyntaxError` 또는 `unterminated string literal`**
  → 파일이 다운로드 중 잘렸습니다. 그 파일을 지우고 다시 받으세요.
  아래 "파일 다시 받기" 참고.
- **`TclError: bad screen distance`**
  → 코드 문제입니다. 해당 파일을 다시 받으세요.

### 처리 도중 갑자기 꺼짐 (`error code -1`)

파이썬 오류 메시지 없이 창이 닫히면 프로그램이 에러를 낸 게 아니라
**프로세스가 강제 종료된 것**입니다. 보통 메모리 부족입니다.

앱 폴더의 **`faceswap_log.txt`** 를 메모장으로 열어보세요. 100프레임마다
메모리 사용량이 기록되어 있습니다.

- 숫자가 계속 올라가다 끊겼다면 → 메모리 부족이 맞습니다.
  처리 해상도를 **540p나 480p로 낮추고**, 브라우저 등 다른 프로그램을
  닫고, 긴 영상은 짧게 나눠서 처리하세요.
- 메모리가 멀쩡한데 끊겼다면 → 메모리 문제가 아닙니다. 로그 끝부분에
  크래시 위치가 찍혀 있는지 확인하세요.

중간에 꺼져도 저장 폴더에 **`.partial.mp4`** 파일이 남습니다. 그때까지
처리된 부분이니 이름을 바꿔서 쓰면 됩니다.

### 저장할 때 "액세스할 수 없습니다 / Permission denied"

거의 항상 둘 중 하나입니다.

1. **저장 경로를 원본 영상과 같은 파일로 지정함** — 원본을 읽으면서 같은
   파일에 덮어쓸 수는 없습니다. 다른 이름으로 지정하세요.
2. **그 파일이 다른 프로그램에서 열려 있음** — 동영상 플레이어를 닫으세요.

지금은 앱이 저장에 실패해도 옆에 `_1`을 붙인 이름으로 결과를 남깁니다.
완료 창에 바뀐 경로가 표시됩니다.

### 한글 파일명 사진·영상이 안 열림

해결되어 있습니다. 그래도 문제가 생기면 파일명을 영어로 바꿔보세요.

### 원본이 입을 벌려도 스왑된 얼굴은 입을 다물고 있음

**"원본 입 모양 유지"** 체크박스를 켜세요(기본 켜짐). 입 부분만 원본을
남겨 말하는 움직임이 살아납니다. 강도를 낮추면 스왑된 입과 섞입니다.

이건 스왑 모델 자체의 한계라서 소스 사진을 여러 장 넣어도 해결되지
않습니다.

### 결과 얼굴이 흐릿함

**"화질 개선"** 체크박스를 켜세요. 처음 켤 때 모델(약 330MB)을 받을지
물어봅니다. 동영상에서는 처리 시간이 2~3배 늘어납니다.

### "소스 사진에서 얼굴을 찾지 못했어요"

얼굴이 너무 작거나 옆모습입니다. 정면이고 크게 나온 사진을 쓰세요.
여러 장 고르면 그중 쓸 수 있는 것만 알아서 골라 씁니다.

### 모델 다운로드 실패 (403 등)

방화벽일 수 있습니다. `download_models.py` 안에 적힌 주소를 브라우저로
직접 열어 받은 뒤 `models\inswapper_128.onnx` 위치에 두세요.

### PowerShell에서 `Activate.ps1` 실행 거부

실행 정책 때문입니다. 활성화하지 말고 venv의 파이썬을 직접 부르세요:

```
.\.venv\Scripts\python.exe -m pip install ...
```

### 너무 느림

- 처리 해상도를 **720p / 540p / 480p** 로 낮추면 2~5배 빨라집니다
- 화질 개선을 끄면 2~3배 빨라집니다
- 긴 영상은 짧게 잘라서 처리하세요

CPU 기준 30초 영상에 15~30분이 정상입니다.

## 파일 다시 받기

파일 하나가 깨졌을 때, 폴더에서 터미널을 열고 (파일명을 바꿔가며):

```
.\.venv\Scripts\python.exe -c "import urllib.request as u; u.urlretrieve('https://raw.githubusercontent.com/pooq1553-max/-/claude/face-swap-program-mts7mz/desktop_app.py','desktop_app.py'); print('done')"
```

`faceswap\` 안의 파일이면 경로를 양쪽 다 `faceswap/video.py` 처럼 바꾸면
됩니다. 받은 뒤 확인:

```
.\.venv\Scripts\python.exe -m py_compile desktop_app.py
```

아무 메시지도 안 나오면 정상입니다.

## 폴더 안에 뭐가 있는지

| 이름 | 무엇 |
|---|---|
| `setup.bat` | 최초 설치 (한 번만) |
| `desktop.bat` | 앱 실행 |
| `desktop_app.py` | 앱 화면 |
| `faceswap\` | 실제 처리 코드 |
| `models\` | 스왑·화질개선 모델 (약 900MB) |
| `.venv\` | 설치된 라이브러리 (옮기면 깨짐) |
| `faceswap_log.txt` | 문제 생겼을 때 볼 기록 |
| `tools\disk_cleanup.bat` | 디스크 공간 정리 도우미 |

