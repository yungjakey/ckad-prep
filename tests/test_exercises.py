"""Tests for exercise loading, selection, and data types."""

import pytest
from ckad.exercises import (
    Action, Exercise, load_exercises, get_domains, select,
)


# -- Action enum --

class TestAction:
    def test_from_str_empty_is_enter(self):
        assert Action.from_str("") is Action.ENTER

    def test_from_str_enter(self):
        assert Action.from_str("enter") is Action.ENTER

    def test_from_str_solution(self):
        assert Action.from_str("s") is Action.SOLUTION
        assert Action.from_str("solution") is Action.SOLUTION

    def test_from_str_skip(self):
        assert Action.from_str("n") is Action.SKIP
        assert Action.from_str("skip") is Action.SKIP

    def test_from_str_quit(self):
        assert Action.from_str("q") is Action.QUIT
        assert Action.from_str("quit") is Action.QUIT

    def test_from_str_case_insensitive(self):
        assert Action.from_str("S") is Action.SOLUTION
        assert Action.from_str("Q") is Action.QUIT
        assert Action.from_str("  N  ") is Action.SKIP

    def test_from_str_rejects_unknown(self):
        with pytest.raises(ValueError, match="unknown action"):
            Action.from_str("bogus")
        with pytest.raises(ValueError, match="unknown action"):
            Action.from_str("x")

    def test_from_str_rejects_partial(self):
        with pytest.raises(ValueError):
            Action.from_str("sol")
        with pytest.raises(ValueError):
            Action.from_str("qui")


# -- Exercise dataclass --

def _make_ex(**overrides):
    defaults = dict(id="x", domain="d", domain_name="D", weight=0, title="t", task="t")
    defaults.update(overrides)
    return Exercise(**defaults)


class TestExercise:
    def test_from_dict(self):
        d = {
            "id": "test-00", "domain": "core_concepts", "domain_name": "Core Concepts",
            "weight": 13, "title": "Test exercise", "task": "Do something",
            "hints": ["hint1"], "solution": ["kubectl run foo"],
            "verify": ["kubectl get po foo"], "cleanup": ["kubectl delete pod foo"],
        }
        ex = Exercise.from_dict(d)
        assert ex.id == "test-00"
        assert ex.domain == "core_concepts"
        assert ex.hints == ("hint1",)
        assert ex.solution == ("kubectl run foo",)

    def test_from_dict_defaults(self):
        d = {"id": "x", "domain": "d", "domain_name": "D", "weight": 0, "title": "t"}
        ex = Exercise.from_dict(d)
        assert ex.task == "t"
        assert ex.hints == ()

    def test_frozen(self):
        ex = _make_ex()
        with pytest.raises(AttributeError):
            ex.id = "y"

    def test_to_dict(self):
        ex = _make_ex()
        d = ex.to_dict()
        assert d["id"] == "x"
        assert isinstance(d, dict)


# -- load_exercises --

class TestLoadExercises:
    def test_load_all(self):
        exs = load_exercises()
        assert len(exs) > 100
        assert all(isinstance(e, Exercise) for e in exs)

    def test_load_by_domain(self):
        exs = load_exercises(domain="configuration")
        assert len(exs) > 0
        assert all(e.domain == "configuration" for e in exs)

    def test_load_nonexistent_domain(self):
        exs = load_exercises(domain="nonexistent")
        assert exs == []


# -- get_domains --

class TestGetDomains:
    def test_returns_domains(self):
        domains = get_domains()
        assert "core_concepts" in domains
        assert "configuration" in domains
        assert len(domains) >= 9


# -- select --

class TestSelect:
    def test_select_count(self):
        exs = load_exercises()
        selected = select(exs, count=5, seed=42)
        assert len(selected) == 5

    def test_select_count_exceeds_pool(self):
        exs = load_exercises(domain="crd")
        selected = select(exs, count=100)
        assert len(selected) == len(exs)

    def test_select_seed_reproducible(self):
        exs = load_exercises()
        a = select(exs, count=5, seed=42)
        b = select(exs, count=5, seed=42)
        assert [e.id for e in a] == [e.id for e in b]

    def test_select_different_seeds_differ(self):
        exs = load_exercises()
        a = select(exs, count=5, seed=1)
        b = select(exs, count=5, seed=2)
        assert [e.id for e in a] != [e.id for e in b]

    def test_select_no_seed_random(self):
        exs = load_exercises()
        a = select(exs, count=5)
        b = select(exs, count=5)
        assert len(a) == 5
        assert len(b) == 5

    def test_select_weighted_domains_present(self):
        exs = load_exercises()
        selected = select(exs, count=10, seed=42)
        domains = {e.domain for e in selected}
        assert len(domains) > 1
