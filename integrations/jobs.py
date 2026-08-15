import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_JOB_TTL_S = 3600
_KEEP_MAX = 20


@dataclass
class Job:
    id: str
    ticker: str
    state: str = "queued"  # queued | running | done | error
    events: List[dict] = field(default_factory=list)
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    next_seq: int = 0
    subscribers: List["asyncio.Queue"] = field(default_factory=list)


_JOBS: Dict[str, Job] = {}
_running_job_id: Optional[str] = None


def create(ticker: str) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], ticker=ticker)
    _JOBS[job.id] = job
    _reap()
    return job


def get(job_id: str) -> Optional[Job]:
    return _JOBS.get(job_id)


def append(job: Job, event: dict) -> None:
    """Must run on the event loop thread. Callers on the TA worker thread hop
    back via loop.call_soon_threadsafe(jobs.append, job, event) — a plain
    asyncio.Queue.put_nowait() is not thread-safe to call directly."""
    event = dict(event)
    event["seq"] = job.next_seq
    job.next_seq += 1
    job.events.append(event)
    for q in job.subscribers:
        q.put_nowait(event)


def subscribe(job: Job) -> "asyncio.Queue":
    q: "asyncio.Queue" = asyncio.Queue()
    job.subscribers.append(q)
    return q


def unsubscribe(job: Job, q: "asyncio.Queue") -> None:
    if q in job.subscribers:
        job.subscribers.remove(q)


def list_recent(limit: int = 20) -> List[Job]:
    return sorted(_JOBS.values(), key=lambda j: j.created_at, reverse=True)[:limit]


def try_start(job_id: str) -> bool:
    """Non-blocking 'only one deep run at a time' gate. Plain global check is
    safe here: FastAPI runs a single event loop thread, and there is no
    `await` between the check and the set, so it can't race with another
    request handler."""
    global _running_job_id
    if _running_job_id is not None:
        return False
    _running_job_id = job_id
    return True


def finish(job_id: str) -> None:
    global _running_job_id
    if _running_job_id == job_id:
        _running_job_id = None


def _reap(ttl_s: int = _JOB_TTL_S, keep: int = _KEEP_MAX) -> None:
    now = time.time()
    stale = [jid for jid, j in _JOBS.items() if now - j.created_at > ttl_s]
    for jid in stale:
        _JOBS.pop(jid, None)
    if len(_JOBS) > keep:
        for j in sorted(_JOBS.values(), key=lambda j: j.created_at)[: len(_JOBS) - keep]:
            _JOBS.pop(j.id, None)
