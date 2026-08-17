"""Exercise loading, session management, selection, and state machine."""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from enum import Enum
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

EXERCISES_DIR = Path(str(resources.files("ckad") / "exercises"))
SESSIONS_DIR = Path.home() / ".ckad" / "sessions"


# -- action enum --

class Action(Enum):
    ENTER = "enter"
    SOLUTION = "solution"
    SKIP = "skip"
    QUIT = "quit"

    @classmethod
    def from_str(cls, s: str) -> Action:
        s = s.strip().lower()
        if s == "" or s == "enter":
            return cls.ENTER
        if s in ("s", "solution"):
            return cls.SOLUTION
        if s in ("n", "skip"):
            return cls.SKIP
        if s in ("q", "quit"):
            return cls.QUIT
        raise ValueError(f"unknown action: {s!r}")


# -- exercise dataclass --

@dataclass(frozen=True)
class Exercise:
    id: str
    domain: str
    domain_name: str
    weight: int
    title: str
    task: str
    hints: tuple[str, ...] = ()
    solution: tuple[str, ...] = ()
    verify: tuple[str, ...] = ()
    cleanup: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, d: dict) -> Exercise:
        return cls(
            id=d["id"],
            domain=d["domain"],
            domain_name=d["domain_name"],
            weight=d.get("weight", 0),
            title=d["title"],
            task=d.get("task", d["title"]),
            hints=tuple(d.get("hints", [])),
            solution=tuple(d.get("solution", [])),
            verify=tuple(d.get("verify", [])),
            cleanup=tuple(d.get("cleanup", [])),
        )

    def to_dict(self) -> dict:
        return asdict(self)


# -- exercise loading --

def load_exercises(domain: str | None = None) -> list[Exercise]:
    exercises: list[Exercise] = []
    for yml in sorted(EXERCISES_DIR.glob("*.yaml")):
        if yml.name == "index.yaml":
            continue
        with open(yml) as f:
            data = yaml.safe_load(f)
        if data:
            exercises.extend(Exercise.from_dict(d) for d in data)
    if domain:
        exercises = [e for e in exercises if e.domain == domain]
    return exercises


def get_domains() -> list[str]:
    return [y.stem for y in sorted(EXERCISES_DIR.glob("*.yaml")) if y.name != "index.yaml"]


def select(exercises: list[Exercise], count: int = 10, seed: int | None = None) -> list[Exercise]:
    if count >= len(exercises):
        return exercises[:]
    if seed is not None:
        random.seed(seed)

    by_domain: dict[str, list[Exercise]] = {}
    for ex in exercises:
        by_domain.setdefault(ex.domain, []).append(ex)

    total_weight = sum(exs[0].weight or 1 for exs in by_domain.values())
    selected: list[Exercise] = []
    for dom_exs in by_domain.values():
        w = dom_exs[0].weight or 1
        n = min(max(1, round(count * w / total_weight)), len(dom_exs))
        selected.extend(random.sample(dom_exs, n))

    if len(selected) > count:
        selected = random.sample(selected, count)
    elif len(selected) < count:
        remaining = [e for e in exercises if e not in selected]
        selected.extend(random.sample(remaining, min(count - len(selected), len(remaining))))

    random.shuffle(selected)
    return selected[:count]


# -- sessions --

def _session_dir(sid: str) -> Path:
    return SESSIONS_DIR / sid


def _session_file(sid: str) -> Path:
    return _session_dir(sid) / "session.json"


def create_session(sid: str, domain: str | None, exercise_ids: list[str]) -> dict:
    d = _session_dir(sid)
    d.mkdir(parents=True, exist_ok=True)
    session = {
        "id": sid,
        "domain": domain,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "active",
        "exercises": [{"id": eid, "result": None, "elapsed": 0} for eid in exercise_ids],
        "current": 0,
        "trace": [],
    }
    _session_file(sid).write_text(json.dumps(session, indent=2))
    return session


def load_session(sid: str) -> dict:
    return json.loads(_session_file(sid).read_text())


def save_session(session: dict) -> None:
    _session_file(session["id"]).write_text(json.dumps(session, indent=2))


def list_sessions() -> list[dict]:
    if not SESSIONS_DIR.exists():
        return []
    sessions = []
    for d in sorted(SESSIONS_DIR.iterdir(), reverse=True):
        sf = d / "session.json"
        if sf.exists():
            sessions.append(json.loads(sf.read_text()))
    return sessions


def kill_session(sid: str) -> None:
    session = load_session(sid)
    ns_prefix_val = ns_prefix(sid)
    out, _, _ = run(f"kubectl get ns -o name 2>/dev/null | grep '{ns_prefix_val}' || true")
    if out:
        for ns in out.splitlines():
            run(f"kubectl delete {ns} --wait=false")
    session["status"] = "killed"
    save_session(session)


def delete_session(sid: str) -> None:
    kill_session(sid)
    shutil.rmtree(_session_dir(sid), ignore_errors=True)


def ns_prefix(sid: str) -> str:
    return f"ckad-{sid[:8]}"


# -- results & trace --

def record_exercise(sid: str, exercise_id: str, passed: bool, elapsed: float) -> None:
    session = load_session(sid)
    for ex in session["exercises"]:
        if ex["id"] == exercise_id:
            ex["result"] = "passed" if passed else "failed"
            ex["elapsed"] = round(elapsed, 1)
            break
    session["current"] = next(
        (i for i, e in enumerate(session["exercises"]) if e["result"] is None),
        len(session["exercises"]),
    )
    save_session(session)


def append_trace(sid: str, entry: dict[str, Any]) -> None:
    session = load_session(sid)
    session.setdefault("trace", []).append(entry)
    save_session(session)


def complete_session(sid: str) -> None:
    session = load_session(sid)
    session["status"] = "completed"
    save_session(session)


def session_progress(session: dict) -> tuple[int, int]:
    done = sum(1 for e in session["exercises"] if e["result"] is not None)
    return done, len(session["exercises"])


# -- pure update --

@dataclass
class StepResult:
    action: Action
    exercise_id: str
    passed: bool | None  # None if skipped or quit
    elapsed: float
    show_solution: bool
    done: bool  # True if session should end
    ns: str


def step(
    exercise: Exercise,
    action: Action,
    sid: str,
    elapsed: float,
) -> StepResult:
    """Pure state transition. No side effects."""
    ns = f"{ns_prefix(sid)}-{exercise.domain[:12]}"
    return StepResult(
        action=action,
        exercise_id=exercise.id,
        passed=None,
        elapsed=elapsed,
        show_solution=action == Action.SOLUTION,
        done=action == Action.QUIT,
        ns=ns,
    )


# -- shell --

def run(cmd: str, timeout: int = 30) -> tuple[str, str, int]:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, check=False)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", f"timeout {timeout}s", -1


# -- verify & cleanup (IO, not pure) --

def verify(ex: Exercise, ns: str, dry_run: bool = False) -> tuple[bool, list[tuple[str, str, str]]]:
    out: list[tuple[str, str, str]] = []
    ok = True
    for cmd in ex.verify:
        if cmd.startswith("echo "):
            out.append(("skip", cmd, "manual"))
            continue
        if dry_run:
            out.append(("dry-run", cmd, "skipped (--dry-run)"))
            continue
        c = cmd if "-n " in cmd or "--namespace " in cmd else f"{cmd} -n {ns}"
        stdout, stderr, rc = run(c)
        if rc == 0:
            out.append(("pass", cmd, stdout or "(ok)"))
        else:
            out.append(("fail", cmd, stderr or stdout or f"rc={rc}"))
            ok = False
    return ok, out


def cleanup(ex: Exercise, ns: str, dry_run: bool = False) -> None:
    if dry_run:
        return
    for cmd in ex.cleanup:
        if cmd.startswith("echo "):
            continue
        run(f"kubectl delete ns {ns} --ignore-not-found --wait=false")
        return
    for cmd in ex.cleanup:
        if not cmd.startswith("echo "):
            c = cmd if "-n " in cmd or "--namespace " in cmd else f"{cmd} -n {ns}"
            run(c, timeout=60)


# -- fzf pickers --

def _has_fzf() -> bool:
    return shutil.which("fzf") is not None


def fzf_session_picker() -> str | None:
    if not _has_fzf():
        print("fzf not found. Install: brew install fzf", file=sys.stderr)
        return None
    sessions = list_sessions()
    if not sessions:
        print("No sessions.", file=sys.stderr)
        return None
    lines = []
    for s in sessions:
        done, total = session_progress(s)
        lines.append(f"{s['id']}  {s.get('domain') or 'all':20s}  {done}/{total}  {s['status']}")
    proc = subprocess.run(
        ["fzf", "--prompt", "sessions> ", "--reverse", "--height", "40%", "--border"],
        input="\n".join(lines), capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.strip().split()[0]


def fzf_exercise_picker(session: dict) -> str | None:
    if not _has_fzf():
        return None
    lines = []
    for ex in session["exercises"]:
        status = ex["result"] or "pending"
        lines.append(f"{ex['id']:35s}  {status}")
    preview_cmd = f"cat {SESSIONS_DIR}/{session['id']}/session.json 2>/dev/null | grep -A2 '\"id\":' || true"
    proc = subprocess.run(
        ["fzf", "--prompt", "exercises> ", "--reverse", "--height", "50%", "--border",
         "--preview", preview_cmd],
        input="\n".join(lines), capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.strip().split()[0]


def fzf_kill_picker() -> str | None:
    if not _has_fzf():
        return None
    sessions = [s for s in list_sessions() if s["status"] == "active"]
    if not sessions:
        print("No active sessions.", file=sys.stderr)
        return None
    lines = []
    for s in sessions:
        done, total = session_progress(s)
        lines.append(f"{s['id']}  {s.get('domain') or 'all':20s}  {done}/{total}")
    proc = subprocess.run(
        ["fzf", "--prompt", "kill> ", "--reverse", "--height", "40%", "--border",
         "--header", "Select session to kill (deletes k8s namespaces)"],
        input="\n".join(lines), capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.strip().split()[0]
