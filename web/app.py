"""쇼츠 자동화 웹 화면 (FastAPI).

실행: python scripts/run_web.py   →  브라우저에서 http://127.0.0.1:8000
이 컴퓨터(127.0.0.1)에서만 열린다.
"""
import hashlib
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import winsafe  # noqa: E402
from applog import setup_logging  # noqa: E402
from backup_tool import create as create_backup  # noqa: E402
from config import PROJECT_ROOT  # noqa: E402
from extract_facts import STATUS_HUMAN, STATUS_REVIEW, read_fields, save_json_atomic  # noqa: E402
from jobs import JobManager  # noqa: E402

WEB_DIR = Path(__file__).resolve().parent
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
MAX_UPLOAD = 2 * 1024 ** 3  # 2GB
MAX_DESCRIPTION = 10_000
FORMATS = ("A", "B", "C")
log = logging.getLogger("shorts.web")


class Description(BaseModel):
    text: str


class FactsEdit(BaseModel):
    values: dict[str, str]


class Approval(BaseModel):
    format: str
    checked_facts: bool = False
    checked_voice: bool = False
    checked_video: bool = False


class KeyInput(BaseModel):
    key: str


class StartRequest(BaseModel):
    from_step: str | None = None


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def create_app(root=None, manager=None):
    root = Path(root or PROJECT_ROOT)
    setup_logging(log_dir=root / "data" / "logs")
    for d in ("input", "output", "frames", "audio", "data"):
        (root / d).mkdir(parents=True, exist_ok=True)
    jobs = manager or JobManager(root)
    app = FastAPI(title="쇼츠 자동화")
    app.state.jobs = jobs
    app.state.root = root

    paths = {
        "description": root / "input" / "description.txt",
        "facts": root / "data" / "facts.json",
        "fields": root / "config" / "fields.txt",
        "approvals": root / "data" / "approvals.json",
        "render": root / "output" / "render_report.json",
        "voice": root / "audio" / "C" / "voice_report.json",
        "env": root / ".env",
    }

    def read_key():
        if not paths["env"].is_file():
            return ""
        for line in paths["env"].read_text(encoding="utf-8-sig").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "GEMINI_API_KEY":
                value = value.strip().strip('"').strip("'")
                return "" if value == "여기에키를붙여넣기" else value
        return ""

    def input_video():
        found = [p for p in (root / "input").glob("원본.*") if p.suffix.lower() in VIDEO_EXTS]
        return max(found, key=lambda p: p.stat().st_mtime) if found else None

    def ensure_idle():
        active = jobs.active()
        if active:
            raise HTTPException(409, f"제작 중에는 바꿀 수 없습니다 (작업 {active['id']}).")

    # ---------- 화면 ----------

    @app.get("/", response_class=HTMLResponse)
    def index():
        # 매번 파일을 읽으므로 index.html 을 고치면 새로고침만으로 반영된다
        return (WEB_DIR / "index.html").read_text(encoding="utf-8")

    for name in ("output", "frames", "audio"):
        app.mount(f"/files/{name}", StaticFiles(directory=root / name, check_dir=False), name=name)

    # ---------- 입력 ----------

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)):
        ensure_idle()
        ext = Path(file.filename or "").suffix.lower()
        if ext not in VIDEO_EXTS:
            raise HTTPException(400, f"영상 파일만 올릴 수 있습니다 ({', '.join(sorted(VIDEO_EXTS))}).")
        tmp = root / "input" / f".upload{ext}"
        size = 0
        try:
            with open(tmp, "wb") as out:
                while chunk := await file.read(1 << 20):
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, "파일이 너무 큽니다 (최대 2GB).")
                    out.write(chunk)
            probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                    "stream=width,height:format=duration", "-of", "json", str(tmp)],
                                   capture_output=True, text=True)
            info = json.loads(probe.stdout or "{}")
            if probe.returncode != 0 or not info.get("streams"):
                raise HTTPException(400, "영상으로 읽을 수 없는 파일입니다.")
            for old in (root / "input").glob("원본.*"):
                winsafe.unlink(old)
            final = root / "input" / f"원본{ext}"
            winsafe.replace(tmp, final)
        finally:
            tmp.unlink(missing_ok=True)
        stream = info["streams"][0]
        log.info("원본 업로드: %s (%d bytes)", final.name, size)
        return {"name": final.name, "size": size, "width": stream.get("width"), "height": stream.get("height"),
                "duration": round(float(info.get("format", {}).get("duration", 0)), 2)}

    @app.post("/api/description")
    def save_description(body: Description):
        ensure_idle()
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "설명글이 비어 있습니다.")
        if len(text) > MAX_DESCRIPTION:
            raise HTTPException(400, f"설명글이 너무 깁니다 (최대 {MAX_DESCRIPTION}자).")
        tmp = paths["description"].with_suffix(".tmp")
        tmp.write_text(text + "\n", encoding="utf-8")
        winsafe.replace(tmp, paths["description"])
        return {"saved": True, "chars": len(text)}

    # ---------- 제미나이 키 (화면에 키를 다시 보여 주지 않음) ----------

    @app.post("/api/key")
    def save_key(body: KeyInput):
        key = body.key.strip()
        if not key:
            raise HTTPException(400, "키가 비어 있습니다.")
        if any(c.isspace() for c in key) or not key.isascii() or not 20 <= len(key) <= 200:
            raise HTTPException(400, "키 모양이 이상합니다. AI Studio 에서 복사 버튼으로 다시 복사해 붙여 넣으세요.")
        lines = paths["env"].read_text(encoding="utf-8-sig").splitlines() if paths["env"].is_file() else []
        lines = [line for line in lines if line.partition("=")[0].strip() != "GEMINI_API_KEY"]
        lines.insert(0, f"GEMINI_API_KEY={key}")
        tmp = paths["env"].with_name(".env.tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        winsafe.replace(tmp, paths["env"])
        log.info("제미나이 키 저장 (글자 수 %d)", len(key))
        return {"saved": True, "length": len(key), "looks_normal": key.startswith("AIza") and len(key) == 39}

    # ---------- 제작 ----------

    @app.post("/api/jobs")
    def start_job(body: StartRequest | None = None):
        video = input_video()
        from_step = body.from_step if body else None
        if video is None and from_step in (None, "scenes"):
            raise HTTPException(400, "먼저 원본 영상을 올려 주세요.")
        if from_step in (None, "scenes", "facts") and not (
                paths["description"].is_file() and paths["description"].read_text(encoding="utf-8").strip()):
            raise HTTPException(400, "먼저 설명글을 입력하고 저장해 주세요.")
        job, created = jobs.start(from_step=from_step, video_name=video.name if video else None,
                                  reason="다시 만들기" if from_step else "제작")
        if not created:
            raise HTTPException(409, {"message": "이미 제작 중입니다. 끝날 때까지 기다려 주세요.", "job": job})
        return job

    @app.post("/api/jobs/{job_id}/resume")
    def resume_job(job_id: str):
        try:
            job, created = jobs.resume(job_id)
        except KeyError:
            raise HTTPException(404, "그런 작업이 없습니다.")
        if not created:
            raise HTTPException(409, {"message": "이미 제작 중입니다.", "job": job})
        return job

    @app.get("/api/jobs/{job_id}/log")
    def job_log(job_id: str):
        return {"log": jobs.log_text(job_id)}

    # ---------- 정보 수정 ----------

    @app.put("/api/facts")
    def edit_facts(body: FactsEdit):
        ensure_idle()
        doc = read_json(paths["facts"]) or {"fields": read_fields(paths["fields"]), "facts": {}}
        for field, value in body.values.items():
            if field not in doc["fields"]:
                raise HTTPException(400, f"모르는 항목: {field}")
            value = value.strip()
            old = doc["facts"].get(field, {})
            if value == (old.get("value") or ""):
                continue
            if value:
                doc["facts"][field] = {"value": value, "evidence": "사람이 웹 화면에서 직접 입력·수정",
                                       "status": STATUS_HUMAN, "reason": "", "edited_at":
                                           datetime.now().isoformat(timespec="seconds")}
            else:
                doc["facts"][field] = {"value": None, "evidence": None, "status": STATUS_REVIEW,
                                       "reason": "사람이 값을 지움"}
        save_json_atomic(doc, paths["facts"])
        return doc

    # ---------- 승인 ----------

    def approvals():
        data = read_json(paths["approvals"], {}) or {}
        out = {}
        for fmt, entry in data.items():
            video = root / "output" / entry.get("file", "")
            valid = video.is_file() and file_sha(video) == entry.get("sha256")
            out[fmt] = {**entry, "valid": valid}
        return out

    @app.post("/api/approve")
    def approve(body: Approval):
        ensure_idle()
        if body.format not in FORMATS:
            raise HTTPException(400, "형식은 A, B, C 중 하나입니다.")
        report = (read_json(paths["render"], {}) or {}).get("formats", {}).get(body.format)
        video = root / "output" / f"shorts_{body.format}.mp4"
        if not report or report.get("status") != "ok" or not video.is_file():
            raise HTTPException(400, "완성되고 검사를 통과한 영상만 승인할 수 있습니다.")
        missing = []
        if not body.checked_video:
            missing.append("영상과 자막을 직접 봤음")
        if not body.checked_facts:
            missing.append("가격·이름·위치가 실제로 맞는지 확인함")
        if body.format == "C" and not body.checked_voice:
            missing.append("내레이션 음성을 직접 들어 봤음")
        if missing:
            raise HTTPException(400, "승인 전에 확인해 주세요: " + ", ".join(missing))
        approved_dir = root / "output" / "approved"
        approved_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        copy = approved_dir / f"shorts_{body.format}_{stamp}.mp4"
        shutil.copy2(video, copy)
        data = read_json(paths["approvals"], {}) or {}
        data[body.format] = {"file": video.name, "sha256": file_sha(video), "approved_at":
                             datetime.now().isoformat(timespec="seconds"), "approved_copy": f"approved/{copy.name}"}
        save_json_atomic(data, paths["approvals"])
        backup = create_backup(root, label=f"approved_{body.format}")
        log.info("%s형 승인, 백업 %s", body.format, backup.name)
        return {"approved": data[body.format], "backup": backup.name}

    # ---------- 상태 ----------

    @app.get("/api/state")
    def state():
        video = input_video()
        description = paths["description"].read_text(encoding="utf-8") if paths["description"].is_file() else ""
        render = read_json(paths["render"], {}) or {}
        results = {}
        for fmt in FORMATS:
            file = root / "output" / f"shorts_{fmt}.mp4"
            entry = render.get("formats", {}).get(fmt, {})
            script = read_json(root / "output" / f"script_{fmt}.json", {}) or {}
            results[fmt] = {
                "exists": file.is_file(),
                "url": f"/files/output/shorts_{fmt}.mp4?v={int(file.stat().st_mtime)}" if file.is_file() else None,
                "report": entry,
                "title": script.get("title"),
                "label": script.get("format_label", f"{fmt}형"),
                "sheet": f"/files/frames/review/{fmt}/한눈에보기.jpg?v={int(file.stat().st_mtime)}"
                if (root / "frames" / "review" / fmt / "한눈에보기.jpg").is_file() and file.is_file() else None,
            }
        voice = read_json(paths["voice"], {}) or {}
        for item in voice.get("items", []):
            item["url"] = f"/files/audio/C/{item['file']}"
        try:
            fields = read_fields(paths["fields"])
        except Exception:
            fields = []
        key = read_key()
        return {
            "key": {"set": bool(key), "length": len(key)},
            "video": {"name": video.name, "size": video.stat().st_size} if video else None,
            "description": description,
            "job": jobs.active() or jobs.latest(),
            "facts": read_json(paths["facts"]),
            "fields": fields,
            "results": results,
            "voice": voice,
            "approvals": approvals(),
        }

    return app

