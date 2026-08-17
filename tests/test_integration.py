"""Integration tests: run_session with action injection + dry-run."""

import io
from contextlib import redirect_stdout

import pytest
from ckad.exercises import (
    Exercise, create_session, load_session,
)
from ckad.cli import run_session


def _ex(id_):
    return Exercise(
        id=id_, domain="core_concepts", domain_name="Core",
        weight=13, title=f"Exercise {id_}", task=f"Do {id_}",
        solution=(f"kubectl run {id_}",), verify=("echo ok",),
        cleanup=(f"echo cleanup {id_}",),
    )


@pytest.fixture
def exercises():
    return [_ex("integ-00"), _ex("integ-01")]


@pytest.fixture
def sid():
    return f"integ-{id(exercises) if 'exercises' in dir() else 0}"


class TestRunSessionDryRun:
    def test_quit_immediately(self, exercises):
        s = f"qs-{id(exercises)}"
        create_session(s, None, [e.id for e in exercises])
        buf = io.StringIO()
        with redirect_stdout(buf):
            with pytest.raises(SystemExit) as exc:
                run_session(exercises, s, dry_run=True, action_iter=iter(["q"]))
        assert exc.value.code == 0

    def test_skip_all(self, exercises):
        s = f"sa-{id(exercises)}"
        create_session(s, None, [e.id for e in exercises])
        buf = io.StringIO()
        with redirect_stdout(buf):
            run_session(exercises, s, dry_run=True, action_iter=iter(["n", "n"]))
        loaded = load_session(s)
        assert loaded["status"] == "completed"
        assert all(e["result"] == "failed" for e in loaded["exercises"])

    def test_verify_all_pass(self, exercises):
        s = f"vp-{id(exercises)}"
        create_session(s, None, [e.id for e in exercises])
        buf = io.StringIO()
        with redirect_stdout(buf):
            run_session(exercises, s, dry_run=True, action_iter=iter(["enter", "enter"]))
        loaded = load_session(s)
        assert loaded["status"] == "completed"
        assert all(e["result"] == "passed" for e in loaded["exercises"])

    def test_solution_then_skip(self, exercises):
        s = f"ss-{id(exercises)}"
        create_session(s, None, [e.id for e in exercises])
        buf = io.StringIO()
        with redirect_stdout(buf):
            run_session(exercises, s, dry_run=True, action_iter=iter(["s", "n", "enter"]))
        loaded = load_session(s)
        assert loaded["exercises"][0]["result"] == "failed"
        assert loaded["exercises"][1]["result"] == "passed"


class TestRunSessionTrace:
    def test_trace_recorded(self, exercises):
        s = f"tr-{id(exercises)}"
        create_session(s, None, [e.id for e in exercises])
        buf = io.StringIO()
        with redirect_stdout(buf):
            run_session(exercises, s, dry_run=True, action_iter=iter(["enter", "enter"]))
        loaded = load_session(s)
        assert len(loaded["trace"]) >= 2
        for entry in loaded["trace"]:
            assert "exercise" in entry
            assert "action" in entry


class TestRunSessionNoVerify:
    def test_no_verify_skips_verification(self, exercises):
        s = f"nv-{id(exercises)}"
        create_session(s, None, [e.id for e in exercises])
        buf = io.StringIO()
        with redirect_stdout(buf):
            run_session(exercises, s, no_verify=True, dry_run=True, action_iter=iter(["enter", "enter"]))
        loaded = load_session(s)
        assert all(e["result"] == "failed" for e in loaded["exercises"])


class TestRunSessionEmpty:
    def test_empty_actions_quits(self, exercises):
        s = f"ea-{id(exercises)}"
        create_session(s, None, [e.id for e in exercises])
        buf = io.StringIO()
        with redirect_stdout(buf):
            with pytest.raises(SystemExit) as exc:
                run_session(exercises, s, dry_run=True, action_iter=iter([]))
        assert exc.value.code == 0
