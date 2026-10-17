"""웹 화면 실행.

    python scripts/run_web.py            # 개발 모드: 코드(.py)를 고치면 서버가 자동으로 다시 시작
    python scripts/run_web.py --no-reload
    python scripts/run_web.py --port 8001

브라우저에서 http://127.0.0.1:8000 을 엽니다. 끌 때는 터미널에서 Ctrl+C.

자동 반영:
  - web/index.html  → 브라우저 새로고침만 하면 반영 (서버 재시작 필요 없음)
  - scripts/*.py, web/*.py → 개발 모드에서 자동 재시작
  - config/*.json, fields.txt → 다음 제작부터 반영 (재시작 필요 없음)
서버 재시작이 필요한 경우: 새 패키지 설치(pip install) 후, --no-reload 로 켰을 때 코드를 고친 후.
주의: 자동 재시작은 진행 중인 제작을 멈춥니다. 다시 켜지면 그 작업은 '중단됨'으로 표시되고
      화면의 '이어서 하기'로 남은 단계부터 다시 실행할 수 있습니다.
"""
import argparse
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="쇼츠 자동화 웹 화면")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-reload", action="store_true")
    args = parser.parse_args()
    reload = not args.no_reload
    print(f"브라우저에서 http://127.0.0.1:{args.port} 을 여세요. (끄기: Ctrl+C)")
    print("개발 모드: 코드를 고치면 자동으로 다시 시작합니다." if reload else "자동 재시작 꺼짐.")
    sys.path.insert(0, str(ROOT))
    uvicorn.run("web.app:create_app", factory=True, host="127.0.0.1", port=args.port, reload=reload,
                reload_dirs=[str(ROOT / "scripts"), str(ROOT / "web")] if reload else None,
                app_dir=str(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
