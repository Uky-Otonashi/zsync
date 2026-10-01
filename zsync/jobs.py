"""后台任务管理: 构建/恢复等长操作在线程中执行, GUI 轮询进度。"""
from __future__ import annotations

import threading
import time
import traceback
import uuid


class Job:
    def __init__(self, kind: str, label: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.label = label
        self.status = "running"  # running | done | error
        self.created_at = time.time()
        self.finished_at: float | None = None
        self.phase = ""
        self.percent = 0.0
        self.detail = ""
        self.result: dict | None = None
        self.error: str | None = None
        self.log: list[str] = []
        self._lock = threading.Lock()

    def prog(self, phase: str, pct, detail: str = ""):
        with self._lock:
            self.phase = phase
            self.percent = float(pct)
            self.detail = detail
            if detail:
                self.log.append(f"[{time.strftime('%H:%M:%S')}] {phase}: {detail}")

    def finish(self, result: dict | None = None):
        with self._lock:
            self.status = "done"
            self.finished_at = time.time()
            self.result = result
            self.percent = 100

    def fail(self, err: str):
        with self._lock:
            self.status = "error"
            self.finished_at = time.time()
            self.error = err
            self.log.append(f"[{time.strftime('%H:%M:%S')}] 错误: {err}")

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "kind": self.kind,
                "label": self.label,
                "status": self.status,
                "phase": self.phase,
                "percent": self.percent,
                "detail": self.detail,
                "error": self.error,
                "result": self.result,
                "created_at": self.created_at,
                "finished_at": self.finished_at,
                "log": self.log[-200:],
            }


class JobManager:
    def __init__(self, maxlen: int = 100):
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._maxlen = maxlen

    def start(self, kind: str, label: str, fn) -> Job:
        """fn(job) -> dict(result); 异常即失败。"""
        job = Job(kind, label)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > self._maxlen:
                old = self._order.pop(0)
                self._jobs.pop(old, None)

        def runner():
            try:
                result = fn(job)
                job.finish(result or {})
            except Exception as e:  # noqa: BLE001
                job.fail(f"{e}\n{traceback.format_exc(limit=3)}")

        threading.Thread(target=runner, daemon=True, name=f"zsync-{kind}-{job.id}").start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[dict]:
        with self._lock:
            ids = list(reversed(self._order))
        return [self._jobs[i].to_dict() for i in ids if i in self._jobs]
