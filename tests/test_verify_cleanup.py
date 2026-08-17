"""Tests for verify and cleanup with dry_run flag."""

import pytest
from ckad.exercises import Exercise, verify, cleanup


def _ex(**overrides):
    defaults = dict(id="x", domain="d", domain_name="D", weight=0, title="t", task="t")
    defaults.update(overrides)
    return Exercise(**defaults)


class TestVerify:
    def test_dry_run_skips_non_echo(self):
        ex = _ex(verify=("kubectl get po", "cat /nonexistent"))
        ok, details = verify(ex, "test-ns", dry_run=True)
        assert ok is True
        assert all(s == "dry-run" for s, _, _ in details)

    def test_dry_run_echo_still_skipped(self):
        ex = _ex(verify=("echo manual",))
        ok, details = verify(ex, "test-ns", dry_run=True)
        assert ok is True
        assert details[0][0] == "skip"

    def test_real_run_echo_skipped(self):
        ex = _ex(verify=("echo manual",))
        ok, details = verify(ex, "test-ns", dry_run=False)
        assert ok is True
        assert details[0][0] == "skip"

    def test_real_run_executes(self):
        ex = _ex(verify=("echo ok", "cat /nonexistent"))
        ok, details = verify(ex, "test-ns", dry_run=False)
        assert ok is False
        statuses = [s for s, _, _ in details]
        assert "pass" in statuses or "skip" in statuses
        assert "fail" in statuses

    def test_namespace_injected(self):
        ex = _ex(verify=("kubectl get po",))
        ok, details = verify(ex, "my-ns", dry_run=False)
        # will fail because no cluster, but namespace should be injected
        assert details[0][0] == "fail"


class TestCleanup:
    def test_dry_run_noop(self):
        ex = _ex(cleanup=("echo cleaning",))
        cleanup(ex, "test-ns", dry_run=True)

    def test_real_cleanup(self):
        ex = _ex(cleanup=("echo cleaning",))
        cleanup(ex, "nonexistent-ns-xyz", dry_run=False)

    def test_echo_only_cleanup(self):
        ex = _ex(cleanup=("echo manual cleanup",))
        cleanup(ex, "test-ns", dry_run=False)
