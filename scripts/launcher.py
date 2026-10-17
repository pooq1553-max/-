"""두 번 클릭 실행용 도우미. '시작하기.bat'(윈도우) / '시작하기.command'(맥)가 이 파일을 부른다.

하는 일 (이미 된 것은 건너뜀):
  1. ffmpeg(영상 도구)가 있는지 확인하고, 없으면 설치를 시도하거나 방법을 알려 줌
  2. 필요한 파이썬 부품 설치 (requirements.txt 가 바뀌었을 때만)
  3. 목소리·받아쓰기 자료(models/) 내려받기 (없을 때만)
  4. .env(제미나이 키 파일)가 없으면 예시를 복사해 만들어 둠
  5. 웹 화면을 켜고 브라우저를 자동으로 엶 (이미 켜져 있으면 브라우저만 엶)
표준 라이브러리만 쓰므로 부품을 설치하기 전에도 실행된다.
"""
import hashlib
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8000
URL = f"http://127.0.0.1:{PORT}"
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"


def say(msg=""):
    print(msg, flush=True)


def stop(msg):
    say("")
    say("=" * 60)
    say(msg)
    say("=" * 60)
    if IS_WIN:
        input("\n엔터를 누르면 창이 닫힙니다...")
    sys.exit(1)


def add_to_path(folder):
    os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")


def find_winget_ffmpeg():
    """winget 으로 설치한 ffmpeg 위치 (새 창을 열기 전에는 PATH 에 안 잡히므로 직접 찾음)."""
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    links = local / "Microsoft" / "WinGet" / "Links"
    if (links / "ffmpeg.exe").is_file():
        return links
    for exe in (local / "Microsoft" / "WinGet" / "Packages").glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"):
        return exe.parent
    return None


def has_ffmpeg():
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def check_python_and_folder():
    if sys.version_info[:2] not in ((3, 12), (3, 13)):
        stop(f"이 프로그램은 파이썬 3.12 또는 3.13 이 필요합니다 (지금: {platform.python_version()}).\n"
             "1) https://www.python.org/downloads/ 에서 3.12 를 설치합니다.\n"
             "2) 프로그램 폴더 안의 .venv 폴더를 지웁니다.\n"
             "3) '시작하기'를 다시 두 번 클릭합니다.")
    if IS_WIN:
        if not str(ROOT).isascii():
            stop(f"프로그램 폴더 경로에 한글이나 특수 문자가 있습니다:\n  {ROOT}\n"
                 "목소리 도구가 이런 경로를 읽지 못합니다. 폴더를 C:\\shorts 로 옮긴 뒤 다시 실행해 주세요.\n"
                 "(폴더를 옮겼다면 그 안의 .venv 폴더는 지우고 실행하세요)")
        if len(str(ROOT)) > 60:
            stop(f"프로그램 폴더 경로가 너무 깁니다 ({len(str(ROOT))}자):\n  {ROOT}\n"
                 "윈도우는 경로가 길면 설치가 실패합니다. 폴더를 C:\\shorts 로 옮긴 뒤 다시 실행해 주세요.\n"
                 "(폴더를 옮겼다면 그 안의 .venv 폴더는 지우고 실행하세요)")


def ensure_ffmpeg():
    add_to_path(ROOT)  # 프로그램 폴더에 ffmpeg.exe 를 넣어 둔 경우
    if IS_WIN and not has_ffmpeg() and find_winget_ffmpeg():
        add_to_path(find_winget_ffmpeg())
    if has_ffmpeg():
        return
    say("[1/5] 영상 도구(ffmpeg)가 없어서 설치합니다 (몇 분 걸릴 수 있어요)…")
    if IS_WIN and shutil.which("winget"):
        subprocess.run(["winget", "install", "-e", "--id", "Gyan.FFmpeg",
                        "--accept-source-agreements", "--accept-package-agreements"])
        found = find_winget_ffmpeg()
        if found:
            add_to_path(found)
        if has_ffmpeg():
            say("영상 도구 설치 완료.")
            return
        stop("ffmpeg 설치를 마쳤습니다.\n설치를 반영하려면 이 창을 닫고 '시작하기'를 한 번 더 두 번 클릭해 주세요.")
    if IS_MAC and shutil.which("brew"):
        subprocess.run(["brew", "install", "ffmpeg"])
        if has_ffmpeg():
            return
    if IS_WIN:
        stop("영상 도구(ffmpeg)를 자동으로 설치하지 못했습니다.\n"
             "1) https://www.gyan.dev/ffmpeg/builds/ 에서 'ffmpeg-release-essentials.zip' 을 받아 압축을 풉니다.\n"
             "2) 그 안의 bin 폴더에 있는 ffmpeg.exe, ffprobe.exe 를 이 프로그램 폴더에 복사합니다.\n"
             "3) '시작하기'를 다시 두 번 클릭합니다.")
    if IS_MAC:
        stop("영상 도구(ffmpeg)가 필요합니다.\n"
             "1) https://brew.sh 의 안내대로 Homebrew 를 설치합니다.\n"
             "2) 터미널에 brew install ffmpeg 를 입력합니다.\n"
             "3) '시작하기'를 다시 두 번 클릭합니다.")
    stop("영상 도구(ffmpeg)를 설치해 주세요. (예: sudo apt install ffmpeg)")


def ensure_packages():
    req = ROOT / "requirements.txt"
    marker = Path(sys.prefix) / ".shorts_installed"
    digest = hashlib.sha256(req.read_bytes()).hexdigest()
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == digest:
        return
    say("[2/5] 필요한 부품을 설치합니다. 처음 한 번은 몇 분 걸릴 수 있어요…")
    code = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q",
                           "-r", str(req)]).returncode
    if code != 0:
        stop("부품 설치에 실패했습니다. 인터넷 연결을 확인하고 다시 두 번 클릭해 주세요.")
    marker.write_text(digest, encoding="utf-8")


def ensure_models():
    needed = ["vits-mimic3-ko_KO-kss_low", "sherpa-onnx-zipformer-korean-2024-06-24"]
    if all((ROOT / "models" / n).is_dir() for n in needed):
        return
    say("[3/5] 목소리·받아쓰기 자료를 내려받습니다 (약 150MB, 처음 한 번만)…")
    code = subprocess.run([sys.executable, str(ROOT / "scripts" / "download_models.py")]).returncode
    if code != 0:
        stop("목소리 자료를 받지 못했습니다. 인터넷 연결을 확인하고 다시 두 번 클릭해 주세요.")


def ensure_env():
    env, example = ROOT / ".env", ROOT / ".env.example"
    if not env.exists() and example.exists():
        shutil.copy(example, env)
        say("[4/5] 제미나이 키는 화면이 열리면 맨 위 '제미나이 키' 칸에 붙여 넣으세요.")


def make_desktop_shortcut():
    """윈도우: 처음 한 번 바탕화면에 '쇼츠 자동화' 바로가기를 만든다."""
    marker = Path(sys.prefix) / ".shorts_shortcut"
    if not IS_WIN or marker.exists():
        return
    script = ("$d=[Environment]::GetFolderPath('Desktop');"
              "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d '쇼츠 자동화.lnk'));"
              "$s.TargetPath=$env:SHORTS_BAT;$s.WorkingDirectory=$env:SHORTS_DIR;$s.Save()")
    env = {**os.environ, "SHORTS_BAT": str(ROOT / "시작하기.bat"), "SHORTS_DIR": str(ROOT)}
    try:
        code = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                              env=env, capture_output=True, timeout=30).returncode
        if code == 0:
            say("바탕화면에 '쇼츠 자동화' 바로가기를 만들었습니다. 다음부터는 그걸 두 번 클릭하세요.")
    except (OSError, subprocess.SubprocessError):
        pass
    marker.write_text("1", encoding="utf-8")


def port_in_use():
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def server_ready():
    try:
        with urllib.request.urlopen(URL + "/api/state", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def main():
    os.chdir(ROOT)
    os.environ["PYTHONUTF8"] = "1"  # 윈도우에서도 한글을 UTF-8 로
    say("쇼츠 자동화를 준비합니다.")
    check_python_and_folder()
    ensure_ffmpeg()
    ensure_packages()
    ensure_models()
    ensure_env()
    make_desktop_shortcut()
    if port_in_use():
        say("이미 켜져 있습니다. 브라우저를 엽니다.")
        webbrowser.open(URL)
        return 0
    say("[5/5] 화면을 켭니다…")
    server = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "run_web.py"), "--no-reload",
                               "--port", str(PORT)])
    for _ in range(120):
        if server.poll() is not None:
            stop("화면을 켜지 못했습니다. 위에 나온 오류 내용을 캡처해서 보내 주세요.")
        if server_ready():
            break
        time.sleep(0.5)
    if os.environ.get("SHORTS_NO_BROWSER") != "1":
        webbrowser.open(URL)
    say("")
    say(f"브라우저에서 {URL} 이 열렸습니다. 안 열리면 주소창에 직접 입력하세요.")
    say("끝내려면 이 창을 닫으세요.")
    try:
        return server.wait()
    except KeyboardInterrupt:
        server.terminate()
        return 0


if __name__ == "__main__":
    sys.exit(main())
