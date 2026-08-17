"""CKAD prep CLI - session-aware with fzf pickers, agent-playable."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time

from ckad.exercises import (
    Action,
    Exercise,
    append_trace,
    cleanup,
    complete_session,
    create_session,
    delete_session,
    fzf_exercise_picker,
    fzf_kill_picker,
    fzf_session_picker,
    kill_session,
    list_sessions,
    load_exercises,
    load_session,
    ns_prefix,
    record_exercise,
    run,
    select,
    session_progress,
    verify,
)

# -- ansi --
R = "\033[0m"
B = "\033[1m"
D = "\033[2m"
RED = "\033[1;31m"
GRN = "\033[1;32m"
YEL = "\033[1;33m"
CYN = "\033[1;36m"
WHT = "\033[1;37m"


def fmt_time(s: float) -> str:
    m, s = divmod(int(s), 60)
    return f"{m:02d}:{s:02d}"


# -- render (IO) --

def render_exercise(ex: Exercise, i: int, total: int, ns: str) -> None:
    print(f"\n{B}{CYN}{'=' * 60}{R}")
    print(f"{B}{CYN}  Exercise {i}/{total}  {D}ns={ns}{R}")
    print(f"{B}{CYN}{'=' * 60}{R}\n")
    print(f"{B}{WHT}{ex.title}{R}\n")
    for h in ex.hints:
        print(f"  {D}{h}{R}")


def render_solution(ex: Exercise) -> None:
    print(f"\n{B}{GRN}--- Solution ---{R}")
    for cmd in ex.solution:
        print(f"  {GRN}{cmd}{R}")
    print(f"{GRN}---{R}\n")


def render_verify_result(ok: bool, details: list[tuple[str, str, str]]) -> None:
    if ok:
        print(f"  {GRN}{B}PASSED{R}")
    else:
        print(f"  {RED}{B}FAILED{R}")
        for st, cmd, detail in details:
            if st == "fail":
                print(f"    {RED}{cmd}{R}")
                print(f"    {D}{detail[:200]}{R}")


def render_summary(session: dict) -> None:
    done, _ = session_progress(session)
    passed = sum(1 for e in session["exercises"] if e["result"] == "passed")
    total_time = sum(e.get("elapsed", 0) for e in session["exercises"])
    print(f"\n{B}{CYN}{'=' * 60}{R}")
    print(f"{B}  Session {session['id']}  {passed}/{done} passed  {fmt_time(total_time)}{R}")
    print(f"{CYN}{'=' * 60}{R}")
    for e in session["exercises"]:
        icon = {"passed": f"{GRN}+", "failed": f"{RED}-"}.get(e["result"], f"{D}?{R}")
        print(f"  {icon} {e['id']:35s} {fmt_time(e.get('elapsed', 0)):>6s}")
    print()


def render_progress(sid: str, t0: float) -> None:
    session = load_session(sid)
    done, _ = session_progress(session)
    passed = sum(1 for e in session["exercises"] if e["result"] == "passed")
    print(f"\n  {D}{passed}/{done} passed | {fmt_time(time.time() - t0)}{R}")


# -- input (IO, with injection support) --

def read_action(action_iter: iter[str] | None = None) -> Action:
    """Read action from input or injected action stream."""
    if action_iter is not None:
        try:
            raw = next(action_iter)
        except StopIteration:
            return Action.QUIT
        print(raw)
        try:
            return Action.from_str(raw)
        except ValueError:
            print(f"  {D}(unknown action: {raw!r}, treating as enter){R}")
            return Action.ENTER
    raw = input(f"  {D}> {R}").strip().lower()
    try:
        return Action.from_str(raw)
    except ValueError:
        print(f"  {D}(unknown action: {raw!r}, treating as enter){R}")
        return Action.ENTER


def read_confirm(prompt: str, action_iter: iter[str] | None = None) -> bool:
    if action_iter is not None:
        try:
            raw = next(action_iter)
        except StopIteration:
            return False
        return raw.strip().lower() in ("y", "yes")
    return input(prompt).strip().lower() in ("y", "yes")


# -- session runner (the core loop) --

def run_session(
    exercises: list[Exercise],
    sid: str,
    no_verify: bool = False,
    dry_run: bool = False,
    action_iter: iter[str] | None = None,
) -> dict:
    """Run a session loop. Returns the final session dict.

    action_iter: if provided, actions are read from this iterator instead of input().
    """
    total = len(exercises)
    t0 = time.time()

    print(f"\n{B}CKAD Practice - {total} exercises{R}")
    print(f"{D}Session: {sid}  ns prefix: {ns_prefix(sid)}{R}")
    if dry_run:
        print(f"{YEL}  DRY RUN - no kubectl commands will execute{R}")
    print(f"{D}Enter=verify  s=solution  n=skip  q=quit{R}")
    print(f"{D}Target: {fmt_time(330 * total)} (~5.5 min/question){R}\n")
    if action_iter is None:
        time.sleep(1)

    for i, ex in enumerate(exercises, 1):
        ns = f"{ns_prefix(sid)}-{ex.domain[:12]}"
        render_exercise(ex, i, total, ns)

        ex_t0 = time.time()
        showed_solution = False
        skipped = False

        while True:
            action = read_action(action_iter)

            if action == Action.QUIT:
                cleanup(ex, ns, dry_run=dry_run)
                render_summary(load_session(sid))
                sys.exit(0)

            if action == Action.SOLUTION:
                render_solution(ex)
                showed_solution = True
                continue

            if action == Action.SKIP:
                elapsed = time.time() - ex_t0
                record_exercise(sid, ex.id, False, elapsed)
                append_trace(sid, {
                    "exercise": ex.id, "action": "skip",
                    "elapsed": round(elapsed, 1),
                })
                print(f"  {D}skipped{R}")
                skipped = True
                break

            # ENTER -> verify
            break

        if not no_verify and not showed_solution and not skipped:
            print(f"  {D}verifying...{R}")
            ok, details = verify(ex, ns, dry_run=dry_run)
            elapsed = time.time() - ex_t0
            render_verify_result(ok, details)

            if not ok and action_iter is None and read_confirm(f"  {D}s for solution, enter to continue...{R}", action_iter):
                render_solution(ex)

            record_exercise(sid, ex.id, ok, elapsed)
            append_trace(sid, {
                "exercise": ex.id, "action": "verify",
                "passed": ok, "elapsed": round(elapsed, 1),
                "details": [{"status": s, "cmd": c, "output": o[:200]} for s, c, o in details],
            })
        else:
            elapsed = time.time() - ex_t0
            record_exercise(sid, ex.id, False, elapsed)
            append_trace(sid, {
                "exercise": ex.id, "action": "verify_skip",
                "passed": False, "elapsed": round(elapsed, 1),
            })

        cleanup(ex, ns, dry_run=dry_run)
        render_progress(sid, t0)

    complete_session(sid)
    session = load_session(sid)
    render_summary(session)
    return session


# -- commands --

def cmd_run(args: argparse.Namespace) -> None:
    if getattr(args, "auto", False):
        return cmd_test(args)

    exercises = load_exercises(domain=args.domain)

    if args.review:
        failed = set()
        for s in list_sessions():
            for e in s["exercises"]:
                if e["result"] == "failed":
                    failed.add(e["id"])
        if not failed:
            print(f"{GRN}Nothing to review.{R}")
            return
        exercises = [e for e in exercises if e.id in failed]

    if not exercises:
        print(f"{RED}No exercises found.{R}")
        sys.exit(1)

    exercises = select(exercises, count=args.count, seed=args.seed)
    sid = time.strftime("%Y%m%d-%H%M%S")
    create_session(sid, args.domain, [e.id for e in exercises])

    _, _, rc = run("kubectl cluster-info 2>/dev/null")
    if rc != 0:
        print(f"{RED}No cluster. Run: scripts/setup.sh{R}")
        if input("Continue anyway? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit(1)

    def on_sigint(sig, frame):
        print(f"\n{YEL}Interrupted{R}")
        render_summary(load_session(sid))
        sys.exit(0)
    signal.signal(signal.SIGINT, on_sigint)

    # --actions injection
    action_iter = None
    if args.actions:
        action_iter = iter(args.actions.split(","))

    run_session(exercises, sid, no_verify=args.no_verify, action_iter=action_iter)


def cmd_test(args: argparse.Namespace) -> None:
    exercises = load_exercises(domain=args.domain)
    if not exercises:
        print(json.dumps({"error": "no exercises found"}))
        sys.exit(1)

    exercises = select(exercises, count=args.count, seed=args.seed)
    sid = time.strftime("%Y%m%d-%H%M%S")
    create_session(sid, args.domain, [e.id for e in exercises])

    results = []
    for ex in exercises:
        ns = f"{ns_prefix(sid)}-{ex.domain[:12]}"
        t0 = time.time()

        ok, details = verify(ex, ns, dry_run=args.dry_run)
        elapsed = time.time() - t0
        record_exercise(sid, ex.id, ok, elapsed)
        cleanup(ex, ns, dry_run=args.dry_run)

        results.append({
            "exercise": ex.id,
            "domain": ex.domain,
            "passed": ok,
            "elapsed": round(elapsed, 1),
            "details": [{"status": s, "cmd": c, "output": o[:200]} for s, c, o in details],
        })

    complete_session(sid)

    passed = sum(1 for r in results if r["passed"])
    output = {
        "session": sid,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }
    print(json.dumps(output, indent=2))
    sys.exit(0 if passed == len(results) else 1)


def cmd_sessions(args: argparse.Namespace) -> None:
    sid = fzf_session_picker()
    if not sid:
        return
    session = load_session(sid)
    done, total = session_progress(session)
    print(f"\n{B}Session {sid}{R}  {done}/{total} done  {session['status']}")
    print(f"Domain: {session.get('domain') or 'all'}  ns prefix: {ns_prefix(sid)}\n")

    if session["status"] != "active":
        print(f"{D}Session is {session['status']}. Showing results only.{R}")
        render_summary(session)
        return

    ex = fzf_exercise_picker(session)
    if not ex:
        return
    print(f"  Selected: {ex}")
    print(f"  {D}To resume the full session, run: uv run ckad attach {sid}{R}")


def cmd_attach(args: argparse.Namespace) -> None:
    session = load_session(args.session_id)
    if session["status"] != "active":
        print(f"{RED}Session {args.session_id} is {session['status']}{R}")
        sys.exit(1)

    remaining = [e for e in session["exercises"] if e["result"] is None]
    if not remaining:
        print(f"{GRN}Session already complete.{R}")
        render_summary(session)
        return

    all_exercises = {e.id: e for e in load_exercises()}
    exercises = [all_exercises[e["id"]] for e in remaining if e["id"] in all_exercises]
    sid = args.session_id

    print(f"\n{B}Resuming session {sid}{R} - {len(exercises)} exercises remaining")
    print(f"{D}ns prefix: {ns_prefix(sid)}{R}\n")
    if args.actions is None:
        time.sleep(1)

    def on_sigint(sig, frame):
        print(f"\n{YEL}Interrupted{R}")
        render_summary(load_session(sid))
        sys.exit(0)
    signal.signal(signal.SIGINT, on_sigint)

    action_iter = iter(args.actions.split(",")) if args.actions else None
    run_session(exercises, sid, no_verify=args.no_verify, action_iter=action_iter)


def cmd_kill(args: argparse.Namespace) -> None:
    sid = args.session_id or fzf_kill_picker()
    if not sid:
        return
    kill_session(sid)
    print(f"{GRN}Killed session {sid}{R}")


def cmd_delete(args: argparse.Namespace) -> None:
    sid = args.session_id or fzf_kill_picker()
    if not sid:
        return
    ch = input(f"Delete session {sid} and all its data? [y/N] ").strip().lower()
    if ch in ("y", "yes"):
        delete_session(sid)
        print(f"{GRN}Deleted session {sid}{R}")


def cmd_list(args: argparse.Namespace) -> None:
    if args.target == "sessions":
        sessions = list_sessions()
        if not sessions:
            print(f"{D}No sessions.{R}")
            return
        print(f"\n{'ID':22s} {'DOMAIN':20s} {'PROGRESS':10s} {'STATUS'}")
        print("-" * 65)
        for s in sessions:
            done, total = session_progress(s)
            print(f"{s['id']:22s} {(s.get('domain') or 'all'):20s} {done}/{total:<5d} {s['status']}")
        print()
    else:
        exercises = load_exercises(domain=args.domain)
        by_d: dict[str, list] = {}
        for e in exercises:
            by_d.setdefault(e.domain, []).append(e)
        print(f"\n{B}Domains:{R}")
        for d in sorted(by_d):
            exs = by_d[d]
            w = exs[0].weight if exs else 0
            print(f"  {d:30s} {len(exs):3d} exercises  (weight: {w}%)")
        print(f"\n{B}All exercises:{R}")
        cur = None
        for e in exercises:
            if e.domain != cur:
                cur = e.domain
                print(f"\n  {CYN}{e.domain_name}{R} ({e.weight}%)")
            print(f"    {e.id:30s} {e.title[:65]}")
        print(f"\n  Total: {len(exercises)}")


# -- main --

def main() -> None:
    p = argparse.ArgumentParser(prog="ckad", description="CKAD practice on kind")
    sub = p.add_subparsers(dest="command")

    # run (default)
    run_p = sub.add_parser("run", help="start a new session")
    run_p.add_argument("-n", "--count", type=int, default=10)
    run_p.add_argument("-d", "--domain", default=None)
    run_p.add_argument("--review", action="store_true")
    run_p.add_argument("--seed", type=int, default=None)
    run_p.add_argument("--no-verify", action="store_true")
    run_p.add_argument("--auto", action="store_true",
                       help="non-interactive: run all exercises, verify, output JSON")
    run_p.add_argument("--dry-run", action="store_true",
                       help="skip kubectl commands, verify from YAML only")
    run_p.add_argument("--actions", type=str, default=None,
                       help="comma-separated actions to inject (e.g. 'enter,s,n,q')")

    # test
    test_p = sub.add_parser("test", help="auto-run exercises (non-interactive)")
    test_p.add_argument("-n", "--count", type=int, default=3)
    test_p.add_argument("-d", "--domain", default=None)
    test_p.add_argument("--seed", type=int, default=42)
    test_p.add_argument("--no-verify", action="store_true")
    test_p.add_argument("--dry-run", action="store_true",
                        help="skip kubectl commands, verify from YAML only")

    # sessions
    sub.add_parser("sessions", aliases=["ss"], help="pick a session with fzf")

    # attach
    attach_p = sub.add_parser("attach", aliases=["a"], help="resume a session")
    attach_p.add_argument("session_id")
    attach_p.add_argument("--no-verify", action="store_true")
    attach_p.add_argument("--dry-run", action="store_true")
    attach_p.add_argument("--actions", type=str, default=None,
                          help="comma-separated actions to inject")

    # kill
    kill_p = sub.add_parser("kill", aliases=["k"], help="kill active session")
    kill_p.add_argument("session_id", nargs="?")

    # delete
    del_p = sub.add_parser("delete", aliases=["rm"], help="delete session")
    del_p.add_argument("session_id", nargs="?")

    # list
    list_p = sub.add_parser("list", aliases=["ls"], help="list sessions or exercises")
    list_p.add_argument("target", nargs="?", default="sessions",
                        choices=["sessions", "exercises"])
    list_p.add_argument("-d", "--domain", default=None)

    # results
    res_p = sub.add_parser("results", aliases=["r"], help="show session results")
    res_p.add_argument("session_id", nargs="?")

    args = p.parse_args()

    if args.command in ("sessions", "ss"):
        cmd_sessions(args)
    elif args.command in ("attach", "a"):
        cmd_attach(args)
    elif args.command in ("kill", "k"):
        cmd_kill(args)
    elif args.command in ("delete", "rm"):
        cmd_delete(args)
    elif args.command in ("list", "ls"):
        cmd_list(args)
    elif args.command in ("results", "r"):
        if args.session_id:
            render_summary(load_session(args.session_id))
        else:
            sid = fzf_session_picker()
            if sid:
                render_summary(load_session(sid))
    elif args.command == "test":
        cmd_test(args)
    else:
        cmd_run(args)
