"""작업 관리 테스트: 중복 실행 방지, 재시작 뒤 미완료 작업 처리, 오류 기록, 키 가리기."""
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (scripts/ 경로 추가)
import applog
import jobs


def py(code):
    return [sys.executable, "-c", code]


def steps_ok(_video=None):
    return [("one", "첫 단계", py("print('하나')")),
            ("two", "둘째 단계", py("import time; time.sleep(0.5); print('둘')")),
            ("three", "셋째 단계", py("print('셋')"))]


def steps_slow(_video=None):
    return [("one", "느린 단계", py("import time; time.sleep(1.5); print('끝')"))]


def steps_fail(_video=None):
    return [("one", "첫 단계", py("print('하나')")),
            ("two", "실패 단계", py("import sys; print('ffmpeg 오류: 구간 렌더링 실패'); sys.exit(3)")),
            ("three", "안 가는 단계", py("print('셋')"))]


def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class JobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_runs_all_steps(self):
        m = jobs.JobManager(self.root, steps_ok)
        job, created = m.start()
        self.assertTrue(created)
        job = m.wait(job["id"], 20)
        self.assertEqual(job["status"], "done")
        self.assertEqual([s["status"] for s in job["steps"]], ["done"] * 3)
        self.assertIn("둘", m.log_text(job["id"]))
        self.assertFalse(m.lock_file.exists())

    def test_pressing_start_twice_does_not_duplicate(self):
        m = jobs.JobManager(self.root, steps_slow)
        first, created1 = m.start()
        second, created2 = m.start()
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(first["id"], second["id"])
        m.wait(first["id"], 20)
        self.assertEqual(len(m.all_jobs()), 1)

    def test_many_simultaneous_clicks_make_one_job(self):
        m = jobs.JobManager(self.root, steps_slow)
        results = []
        threads = [threading.Thread(target=lambda: results.append(m.start())) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(1 for _, created in results if created), 1)
        self.assertEqual(len({job["id"] for job, _ in results}), 1)
        m.wait(results[0][0]["id"], 20)

    def test_second_server_process_cannot_start_while_first_runs(self):
        m = jobs.JobManager(self.root, steps_slow)
        job, _ = m.start()
        # 다른 프로그램이 같은 폴더로 시작해도(잠금 파일 주인이 살아 있음) 새 작업을 만들지 않음
        other = jobs.JobManager.__new__(jobs.JobManager)
        other.__dict__.update({k: v for k, v in m.__dict__.items() if k not in ("_lock", "_threads")})
        other._lock, other._threads = threading.Lock(), {}
        with mock.patch.object(other, "active", return_value=None):
            same, created = other.start()
        self.assertFalse(created)
        self.assertEqual(same["id"], job["id"])
        m.wait(job["id"], 20)

    def test_new_job_allowed_after_finish(self):
        m = jobs.JobManager(self.root, steps_ok)
        a, _ = m.start()
        m.wait(a["id"], 20)
        b, created = m.start()
        self.assertTrue(created)
        self.assertNotEqual(a["id"], b["id"])
        m.wait(b["id"], 20)

    def test_failure_is_recorded_and_later_steps_not_run(self):
        m = jobs.JobManager(self.root, steps_fail)
        with self.assertLogs("shorts.jobs", level="ERROR") as logs:
            job, _ = m.start()
            job = m.wait(job["id"], 20)
        self.assertEqual(job["status"], "failed")
        self.assertEqual([s["status"] for s in job["steps"]], ["done", "failed", "waiting"])
        self.assertIn("실패 단계 실패 (종료 코드 3)", job["error"])
        self.assertIn("구간 렌더링 실패", job["error"])
        self.assertIn("구간 렌더링 실패", m.log_text(job["id"]))
        self.assertTrue(any("구간 렌더링 실패" in line for line in logs.output))

    def test_restart_marks_unfinished_job_and_stops_child(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            jobs_dir = self.root / "data" / "jobs"
            jobs_dir.mkdir(parents=True)
            job = {"id": "old", "status": "running", "created": "2026-01-01T00:00:00", "video": None,
                   "steps": [{"key": "one", "label": "첫 단계", "status": "done"},
                             {"key": "two", "label": "둘째 단계", "status": "running"},
                             {"key": "three", "label": "셋째 단계", "status": "waiting"}],
                   "error": "", "child_pid": child.pid}
            (jobs_dir / "old.json").write_text(json.dumps(job), encoding="utf-8")
            (jobs_dir / "active.lock").write_text(json.dumps({"job_id": "old", "pid": dead_pid()}))

            m = jobs.JobManager(self.root, steps_ok)  # = 프로그램을 다시 켬
            old = m.get("old")
            self.assertEqual(old["status"], "interrupted")
            self.assertEqual(old["steps"][1]["status"], "interrupted")
            self.assertIn("이어서 하기", old["error"])
            self.assertFalse((jobs_dir / "active.lock").exists())
            self.assertIsNotNone(child.wait(timeout=5))  # 남아 있던 하위 프로그램이 멈춤

            new, created = m.resume("old")
            self.assertTrue(created)
            new = m.wait(new["id"], 20)
            self.assertEqual([s["status"] for s in new["steps"]], ["skipped", "done", "done"])
            self.assertEqual(new["status"], "done")
        finally:
            if child.poll() is None:
                child.kill()

    def test_stale_lock_from_crashed_process_is_cleared(self):
        jobs_dir = self.root / "data" / "jobs"
        jobs_dir.mkdir(parents=True)
        (jobs_dir / "active.lock").write_text(json.dumps({"job_id": "x", "pid": dead_pid()}))
        m = jobs.JobManager(self.root, steps_ok)
        job, created = m.start()
        self.assertTrue(created)
        m.wait(job["id"], 20)


class ProcessTest(unittest.TestCase):
    def test_zombie_process_counts_as_dead(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        time.sleep(1.0)  # 끝났지만 wait() 를 안 해서 좀비 상태
        try:
            self.assertFalse(jobs.pid_alive(child.pid))
        finally:
            child.wait()

    def test_stop_process_kills_stubborn_child(self):
        child = subprocess.Popen([sys.executable, "-c",
                                  "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"])
        time.sleep(0.5)
        jobs.stop_process(child.pid, wait=1.0)
        self.assertIsNotNone(child.wait(timeout=5))

    def test_lock_for_finished_job_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            m = jobs.JobManager(root, steps_ok)
            a, _ = m.start()
            m.wait(a["id"], 20)
            # 끝난 작업을 가리키는 잠금이 (살아 있는 pid 로) 남아 있어도 새 작업은 시작돼야 함
            m.lock_file.write_text(json.dumps({"job_id": a["id"], "pid": os.getpid()}))
            b, created = m.start()
            self.assertTrue(created)
            m.wait(b["id"], 20)


class RedactTest(unittest.TestCase):
    def test_api_key_is_hidden_in_log_file(self):
        key = "AIzaSECRETSECRETSECRETSECRETSECRET1234"
        with tempfile.TemporaryDirectory() as tmp:
            logger = logging.getLogger("shorts.redact_test")
            handler = logging.FileHandler(Path(tmp) / "t.log", encoding="utf-8")
            handler.addFilter(applog.RedactKeyFilter())
            logger.addHandler(handler)
            logger.propagate = False
            with mock.patch("config._read_env_file", return_value={"GEMINI_API_KEY": key}):
                logger.error("요청 실패 key=%s", key)
                try:
                    raise RuntimeError(f"bad {key}")
                except RuntimeError:
                    logger.exception("예외")
            handler.close()
            logger.removeHandler(handler)
            text = (Path(tmp) / "t.log").read_text(encoding="utf-8")
        self.assertNotIn(key, text)
        self.assertIn("[키 숨김]", text)


if __name__ == "__main__":
    unittest.main()
