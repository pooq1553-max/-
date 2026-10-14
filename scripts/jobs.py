"""제작 작업(job) 관리: 중복 실행 막기, 진행 상황 저장, 재시작 뒤 미완료 작업 처리, 오류 기록.

작업은 단계(STEPS)를 차례로 실행한다. 각 단계는 scripts/ 의 프로그램을 따로 띄워(subprocess) 실행하므로
한 단계가 멈추거나 죽어도 웹 서버는 살아 있고, 출력은 data/jobs/<id>.log 에 남는다.

상태: queued(대기) → running(진행 중) → done(완료) / partial(일부 실패) / failed(실패)
      프로그램이 중간에 꺼지면 다음 시작 때 running 이던 작업을 interrupted(중단됨)로 바꾼다.
"""
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from extract_facts import save_json_atomic

SCRIPTS_DIR = Path(__file__).resolve().parent
log = logging.getLogger("shorts.jobs")

ACTIVE = ("queued", "running")


def default_steps(video_name=None):
    py = sys.executable
    video = ["--input", f"input/{video_name}"] if video_name else []
    return [
        ("scenes", "장면 나누기", [py, str(SCRIPTS_DIR / "scenes.py"), "--no-open", *video]),
        ("facts", "설명글에서 정보 뽑기 (Gemini)", [py, str(SCRIPTS_DIR / "extract_facts.py")]),
        ("scripts", "제목·자막·내레이션 대본 만들기", [py, str(SCRIPTS_DIR / "make_scripts.py")]),
        ("voice", "내레이션 음성 만들기 + 받아쓰기 비교", [py, str(SCRIPTS_DIR / "voice.py")]),
        ("render", "영상 3개 렌더링 (A/B/C)", [py, str(SCRIPTS_DIR / "render.py"), *video]),
    ]


def now():
    return datetime.now().isoformat(timespec="seconds")


def pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # 조회 권한만
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # 죽었지만 정리되지 않은 '좀비' 프로세스는 살아 있는 것으로 치지 않음 (Linux)
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text()
        return stat.rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def stop_process(pid, wait=5.0):
    """하위 프로그램을 멈춘다: 먼저 부드럽게(TERM), 안 멈추면 강제로(KILL)."""
    if not pid_alive(pid):
        return
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError:
        return
    end = time.time() + wait
    while time.time() < end:
        if not pid_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(int(pid), getattr(signal, "SIGKILL", signal.SIGTERM))
    except OSError:
        pass


class JobManager:
    def __init__(self, root, steps_factory=default_steps, env=None):
        self.root = Path(root)
        self.dir = self.root / "data" / "jobs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock_file = self.dir / "active.lock"
        self.steps_factory = steps_factory
        self.env = {**os.environ, "SHORTS_ROOT": str(self.root), "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1", **(env or {})}
        self._lock = threading.Lock()
        self._threads = {}
        self.recover()

    # ---------- 저장 ----------

    def _path(self, job_id):
        return self.dir / f"{job_id}.json"

    def save(self, job):
        job["updated"] = now()
        save_json_atomic(job, self._path(job["id"]))

    def get(self, job_id):
        try:
            return json.loads(self._path(job_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def all_jobs(self):
        jobs = []
        for p in self.dir.glob("*.json"):
            try:
                jobs.append(json.loads(p.read_text(encoding="utf-8")))
            except ValueError:
                log.warning("작업 파일을 읽지 못함: %s", p.name)
        return sorted(jobs, key=lambda j: j.get("created", ""))

    def latest(self):
        jobs = self.all_jobs()
        return jobs[-1] if jobs else None

    def active(self):
        return next((j for j in reversed(self.all_jobs()) if j["status"] in ACTIVE), None)

    # ---------- 재시작 뒤 정리 ----------

    def recover(self):
        """이전 실행에서 끝나지 못한 작업을 '중단됨'으로 바꾸고, 남은 하위 프로그램을 멈춘다."""
        with self._lock:
            owner = self._read_lock().get("pid")
            if owner and owner != os.getpid() and pid_alive(owner) and self._lock_job_active():
                log.info("다른 프로그램(pid %s)이 작업 중이라 정리하지 않음", owner)
                return
            for job in self.all_jobs():
                if job["status"] not in ACTIVE:
                    continue
                stop_process(job.get("child_pid"))
                for step in job["steps"]:
                    if step["status"] == "running":
                        step["status"] = "interrupted"
                job["status"] = "interrupted"
                job["error"] = "프로그램이 작업 도중 종료되었습니다. '이어서 하기'로 남은 단계부터 다시 실행하세요."
                job["child_pid"] = None
                self.save(job)
                log.warning("미완료 작업 %s 를 중단됨으로 표시", job["id"])
            self.lock_file.unlink(missing_ok=True)

    def _lock_job_active(self):
        job = self.get(self._read_lock().get("job_id") or "")
        return bool(job and job["status"] in ACTIVE)

    def _read_lock(self):
        try:
            return json.loads(self.lock_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    # ---------- 시작 ----------

    def start(self, from_step=None, reason="제작", video_name=None):
        """작업을 시작한다. 이미 진행 중이면 새로 만들지 않고 그 작업을 돌려준다. (job, 새로 만들었는지)"""
        with self._lock:
            current = self.active()
            if current:
                return current, False
            # 다른 프로그램(서버 두 개 등)이 잡고 있으면 거절
            try:
                fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                owner = self._read_lock()
                # 잠금은 '주인이 살아 있고 그 작업이 정말 진행 중'일 때만 유효
                if pid_alive(owner.get("pid")) and self._lock_job_active():
                    return self.get(owner.get("job_id")), False
                self.lock_file.unlink(missing_ok=True)
                fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            steps = self.steps_factory(video_name)
            keys = [k for k, _, _ in steps]
            begin = keys.index(from_step) if from_step in keys else 0
            job = {
                "id": datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6],
                "status": "queued", "reason": reason, "created": now(), "video": video_name,
                "steps": [{"key": k, "label": label, "status": "skipped" if i < begin else "waiting",
                           "started": None, "finished": None, "returncode": None}
                          for i, (k, label, _) in enumerate(steps)],
                "error": "", "child_pid": None,
            }
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"job_id": job["id"], "pid": os.getpid()}, f)
            self.save(job)
            thread = threading.Thread(target=self._run, args=(job, steps), daemon=True)
            self._threads[job["id"]] = thread
            thread.start()
            log.info("작업 시작 %s (%s, %s 단계부터)", job["id"], reason, keys[begin])
            return job, True

    def resume(self, job_id):
        """중단·실패한 작업을 끝나지 않은 첫 단계부터 새 작업으로 다시 시작한다."""
        old = self.get(job_id)
        if not old:
            raise KeyError(job_id)
        first = next((s["key"] for s in old["steps"] if s["status"] not in ("done", "skipped")), None)
        return self.start(from_step=first, reason=f"이어서 하기 ({job_id})", video_name=old.get("video"))

    def wait(self, job_id, timeout=None):
        thread = self._threads.get(job_id)
        if thread:
            thread.join(timeout)
        return self.get(job_id)

    # ---------- 실행 ----------

    def _run(self, job, steps):
        log_path = self.dir / f"{job['id']}.log"
        job["status"] = "running"
        self.save(job)
        try:
            with open(log_path, "a", encoding="utf-8") as out:
                for state, (key, label, cmd) in zip(job["steps"], steps):
                    if state["status"] == "skipped":
                        continue
                    state["status"], state["started"] = "running", now()
                    self.save(job)
                    out.write(f"\n===== {label} ({key}) {now()} =====\n")
                    out.flush()
                    proc = subprocess.Popen(cmd, cwd=self.root, env=self.env, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                            errors="replace")
                    job["child_pid"] = proc.pid
                    self.save(job)
                    tail = []
                    with proc:
                        for line in proc.stdout:
                            out.write(line)
                            out.flush()
                            tail = (tail + [line.rstrip()])[-15:]
                        code = proc.wait()
                    job["child_pid"] = None
                    state["returncode"], state["finished"] = code, now()
                    if code == 0:
                        state["status"] = "done"
                    elif key == "render" and code == 2:
                        state["status"] = "partial"
                        job["error"] = f"{label}: 일부 형식만 완성\n" + "\n".join(tail)
                    else:
                        state["status"] = "failed"
                        job["error"] = f"{label} 실패 (종료 코드 {code})\n" + "\n".join(tail)
                        job["status"] = "failed"
                        log.error("작업 %s 단계 %s 실패: %s", job["id"], key, "\n".join(tail))
                        self.save(job)
                        return
                    self.save(job)
            job["status"] = "partial" if any(s["status"] == "partial" for s in job["steps"]) else "done"
            if job["status"] == "partial":
                log.error("작업 %s 일부 실패: %s", job["id"], job["error"])
            self.save(job)
        except Exception as e:
            log.exception("작업 %s 실행 중 예외", job["id"])
            job["status"], job["error"] = "failed", f"작업 실행 중 오류: {e}"
            for s in job["steps"]:
                if s["status"] == "running":
                    s["status"] = "failed"
            self.save(job)
        finally:
            job["finished"] = now()
            self.save(job)
            with self._lock:
                if self._read_lock().get("job_id") == job["id"]:
                    self.lock_file.unlink(missing_ok=True)
            log.info("작업 끝 %s: %s", job["id"], job["status"])

    def log_text(self, job_id, max_chars=20000):
        path = self.dir / f"{job_id}.log"
        if not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[-max_chars:]


def wait_until(predicate, timeout=30, interval=0.1):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(interval)
    return False
