"""백업과 복원. 단계 0의 backup/ 폴더 방식을 그대로 쓰고, 복원과 무결성 확인을 더했다.

사용법:
    python scripts/backup_tool.py create [--label 이름]     # 백업 만들기
    python scripts/backup_tool.py list                      # 백업 목록
    python scripts/backup_tool.py verify 백업이름           # 파일이 손상되지 않았는지 확인
    python scripts/backup_tool.py restore 백업이름 [--with-code]

백업에 넣는 것: 코드·설정(git 이 추적하는 파일), data/ 의 JSON(정보·승인·작업 기록),
               input/description.txt, output/ 의 JSON(장면·대본·렌더 결과), audio/C/voice_report.json
넣지 않는 것: .env(API 키), 원본·완성 영상, 음성 파일, models/(대용량 모델)
복원은 데이터만 되돌린다 (--with-code 를 주면 코드·설정도). 복원 직전 상태를 먼저 자동 백업한다.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import CODE_ROOT, PROJECT_ROOT

EXCLUDE_NAMES = {".env"}
EXCLUDE_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".wav", ".mp3", ".m4a",
                    ".onnx", ".bin", ".safetensors", ".pt", ".gguf", ".tar", ".bz2"}


class BackupError(Exception):
    pass


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def allowed(rel):
    name = Path(rel).name
    if name in EXCLUDE_NAMES or name.startswith(".env.") and name != ".env.example":
        return False
    return Path(rel).suffix.lower() not in EXCLUDE_SUFFIXES


def code_files(code_root):
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=code_root, capture_output=True, text=True, check=True)
        files = [f for f in out.stdout.splitlines() if f]
    except (OSError, subprocess.CalledProcessError):
        files = [str(p.relative_to(code_root)) for d in ("scripts", "config", "web", "tests")
                 for p in (code_root / d).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    return sorted(f for f in files if allowed(f) and not f.startswith("backup/"))


def data_files(root):
    patterns = ["data/*.json", "data/jobs/*.json", "input/description.txt", "output/*.json",
                "audio/C/voice_report.json"]
    files = set()
    for pattern in patterns:
        files |= {str(p.relative_to(root)) for p in root.glob(pattern) if p.is_file()}
    return sorted(f for f in files if allowed(f))


def create(root=PROJECT_ROOT, code_root=CODE_ROOT, label=""):
    root, code_root = Path(root), Path(code_root)
    name = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + (f"_{label}" if label else "")
    dest = root / "backup" / name
    tmp = root / "backup" / f".{name}.tmp"
    tmp.mkdir(parents=True)
    manifest = {"created": datetime.now().isoformat(timespec="seconds"), "label": label, "files": {}}
    try:
        for kind, base, files in (("code", code_root, code_files(code_root)), ("data", root, data_files(root))):
            for rel in files:
                src = base / rel
                if not src.is_file():
                    continue
                target = tmp / kind / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
                manifest["files"][f"{kind}/{rel}"] = sha256(target)
        (tmp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.rename(dest)  # 다 복사된 뒤에만 완성된 백업으로 보이게
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return dest


def list_backups(root=PROJECT_ROOT):
    base = Path(root) / "backup"
    return sorted(p.name for p in base.iterdir() if p.is_dir() and (p / "manifest.json").is_file()) \
        if base.is_dir() else []


def verify(name, root=PROJECT_ROOT):
    folder = Path(root) / "backup" / name
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        raise BackupError(f"백업이 없거나 완성되지 않았습니다: {name}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems = []
    for rel, digest in manifest["files"].items():
        path = folder / rel
        if not path.is_file():
            problems.append(f"없음: {rel}")
        elif sha256(path) != digest:
            problems.append(f"내용이 바뀜: {rel}")
    return manifest, problems


def restore(name, root=PROJECT_ROOT, code_root=CODE_ROOT, with_code=False):
    root, code_root = Path(root), Path(code_root)
    manifest, problems = verify(name, root)
    if problems:
        raise BackupError("백업이 손상되어 복원하지 않습니다:\n  " + "\n  ".join(problems))
    safety = create(root, code_root, label="before_restore")
    folder = root / "backup" / name
    restored = []
    for rel in manifest["files"]:
        kind, inner = rel.split("/", 1)
        if kind == "code" and not with_code:
            continue
        if not allowed(inner):
            continue
        target = (code_root if kind == "code" else root) / inner
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".restore_tmp")
        shutil.copy2(folder / rel, tmp)
        tmp.replace(target)
        restored.append(inner)
    return restored, safety


def main():
    parser = argparse.ArgumentParser(description="백업 만들기·확인·복원")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--label", default="")
    sub.add_parser("list")
    v = sub.add_parser("verify")
    v.add_argument("name")
    r = sub.add_parser("restore")
    r.add_argument("name")
    r.add_argument("--with-code", action="store_true")
    args = parser.parse_args()

    if args.cmd == "create":
        dest = create(label=args.label)
        count = len(json.loads((dest / "manifest.json").read_text(encoding="utf-8"))["files"])
        print(f"백업 완료: {dest} (파일 {count}개, API 키·영상·모델 제외)")
    elif args.cmd == "list":
        for name in list_backups():
            print(name)
    elif args.cmd == "verify":
        manifest, problems = verify(args.name)
        print("이상 없음" if not problems else "문제 발견:\n  " + "\n  ".join(problems))
        return 1 if problems else 0
    elif args.cmd == "restore":
        restored, safety = restore(args.name, with_code=args.with_code)
        print(f"복원 완료: {len(restored)}개 파일. 복원 전 상태는 {safety.name} 에 백업했습니다.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BackupError as e:
        print(f"오류: {e}")
        sys.exit(1)
