# Windows 설치 가이드

로컬 Windows PC에서 face swap 돌리는 방법. 사진이 어디로도 안 올라감.

## 원클릭 방법 (추천)

1. 이 레포를 ZIP으로 받아 압축 풀기
   (GitHub → Code 버튼 → Download ZIP → `Documents\faceswap-app` 같은 곳에 압축 해제)
2. 폴더 안에서 **`setup.bat` 더블클릭** — Python·라이브러리·모델을 자동으로 설치하고 바탕화면에 아이콘을 만들어 줍니다. 5~10분 걸림.
3. 이후엔 언제든 **바탕화면의 "FaceSwap" 아이콘 더블클릭** → 브라우저에서 앱이 열림. 사진 두 장 드래그해서 올리고 **스왑 실행** 버튼 누르면 결과 표시됨.

`setup.bat` 중 Python이 없어서 winget으로 자동 설치가 되면 안내 메시지가 뜨는데, 그때는 **새 명령창을 열어 setup.bat을 한 번 더 실행**하면 됩니다.

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

**`ModuleNotFoundError: No module named 'insightface'`**
→ 가상환경 활성화 안 함. `.\.venv\Scripts\Activate.ps1` 먼저 실행.

**모델 다운로드 403 / 실패**
→ 회사 방화벽일 가능성. `download_models.py` 안 URL을 브라우저로 직접 다운받아서 `models\inswapper_128.onnx` 위치에 놓기.

**결과 얼굴이 흐릿함**
→ inswapper는 128px로 얼굴을 만들어서 고해상도 타깃에서는 살짝 부드럽게 보임. GFPGAN 후처리 붙이면 개선됨. 필요하면 얘기해주세요.

**"no face detected in source image"**
→ 소스 사진의 얼굴이 너무 작거나 옆모습이라 검출 실패. 정면·가까운 사진으로.
