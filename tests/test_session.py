"""Tests for session lifecycle, trace logging, and step function."""

import json
import time

import pytest
from ckad.exercises import (
    Action, Exercise, StepResult,
    create_session, load_session, save_session, complete_session,
    record_exercise, append_trace, list_sessions, session_progress,
    ns_prefix, step, SESSIONS_DIR,
)


@pytest.fixture
def exercise():
    return Exercise(
        id="test-00",
        domain="core_concepts",
        domain_name="Core Concepts",
        weight=13,
        title="Test exercise",
        task="Do something",
        hints=("hint1",),
        solution=("kubectl run foo",),
        verify=("kubectl get po foo",),
        cleanup=("kubectl delete pod foo",),
    )


@pytest.fixture
def session_id():
    return f"test-{int(time.time() * 1000)}"


# -- create/load --

class TestSessionCreate:
    def test_create_session(self, session_id):
        create_session(session_id, "core_concepts", ["ex-00", "ex-01"])
        s = load_session(session_id)
        assert s["id"] == session_id
        assert s["domain"] == "core_concepts"
        assert s["status"] == "active"
        assert len(s["exercises"]) == 2
        assert s["exercises"][0]["id"] == "ex-00"
        assert s["exercises"][0]["result"] is None
        assert s["trace"] == []

    def test_load_nonexistent(self):
        with pytest.raises(FileNotFoundError):
            load_session("nonexistent-session-id")


# -- record_exercise --

class TestRecordExercise:
    def test_record_pass(self, session_id):
        create_session(session_id, None, ["ex-00"])
        record_exercise(session_id, "ex-00", True, 5.0)
        s = load_session(session_id)
        assert s["exercises"][0]["result"] == "passed"
        assert s["exercises"][0]["elapsed"] == 5.0

    def test_record_fail(self, session_id):
        create_session(session_id, None, ["ex-00"])
        record_exercise(session_id, "ex-00", False, 3.0)
        s = load_session(session_id)
        assert s["exercises"][0]["result"] == "failed"

    def test_record_updates_current(self, session_id):
        create_session(session_id, None, ["ex-00", "ex-01", "ex-02"])
        s = load_session(session_id)
        assert s["current"] == 0

        record_exercise(session_id, "ex-00", True, 1.0)
        s = load_session(session_id)
        assert s["current"] == 1

        record_exercise(session_id, "ex-01", False, 1.0)
        s = load_session(session_id)
        assert s["current"] == 2

        record_exercise(session_id, "ex-02", True, 1.0)
        s = load_session(session_id)
        assert s["current"] == 3  # all done


# -- append_trace --

class TestTrace:
    def test_append_trace(self, session_id):
        create_session(session_id, None, ["ex-00"])
        append_trace(session_id, {"action": "verify", "passed": True})
        s = load_session(session_id)
        assert len(s["trace"]) == 1
        assert s["trace"][0]["action"] == "verify"
        assert s["trace"][0]["passed"] is True

    def test_trace_accumulates(self, session_id):
        create_session(session_id, None, ["ex-00"])
        append_trace(session_id, {"step": 1})
        append_trace(session_id, {"step": 2})
        append_trace(session_id, {"step": 3})
        s = load_session(session_id)
        assert len(s["trace"]) == 3


# -- complete_session --

class TestCompleteSession:
    def test_complete(self, session_id):
        create_session(session_id, None, ["ex-00"])
        complete_session(session_id)
        s = load_session(session_id)
        assert s["status"] == "completed"

    def test_progress(self, session_id):
        create_session(session_id, None, ["ex-00", "ex-01", "ex-02"])
        s = load_session(session_id)
        done, total = session_progress(s)
        assert done == 0
        assert total == 3

        record_exercise(session_id, "ex-00", True, 1.0)
        s = load_session(session_id)
        done, total = session_progress(s)
        assert done == 1


# -- ns_prefix --

class TestNsPrefix:
    def test_format(self):
        assert ns_prefix("20260817-143022") == "ckad-20260817"
    def test_short_id(self):
        assert ns_prefix("abc") == "ckad-abc"


# -- step (pure function) --

class TestStep:
    def test_enter(self, exercise, session_id):
        result = step(exercise, Action.ENTER, session_id, 2.5)
        assert isinstance(result, StepResult)
        assert result.action is Action.ENTER
        assert result.exercise_id == "test-00"
        assert result.passed is None
        assert result.elapsed == 2.5
        assert result.show_solution is False
        assert result.done is False
        assert result.ns.startswith("ckad-")

    def test_solution(self, exercise, session_id):
        result = step(exercise, Action.SOLUTION, session_id, 0.0)
        assert result.show_solution is True
        assert result.done is False

    def test_skip(self, exercise, session_id):
        result = step(exercise, Action.SKIP, session_id, 1.0)
        assert result.done is False

    def test_quit(self, exercise, session_id):
        result = step(exercise, Action.QUIT, session_id, 0.0)
        assert result.done is True
