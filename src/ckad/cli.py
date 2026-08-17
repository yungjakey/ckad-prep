"""CKAD prep CLI - session-aware with fzf pickers."""

from __future__ import annotations

import argparse
import signal
import sys
import time

from ckad.exercises import (
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


def verify(ex: dict, ns: str) -> tuple[bool, list[tuple[str, str, str]]]:
    out = []
    ok = True
    for cmd in ex.get("verify", []):
        if cmd.startswith("echo "):
            out.append(("skip", cmd, "manual"))
            continue
        # inject namespace if not already present
        c = cmd if "-n " in cmd or "--namespace " in cmd else f"{cmd} -n {ns}"
        stdout, stderr, rc = run(c)
        if rc == 0:
            out.append(("pass", cmd, stdout or "(ok)"))
        else:
            out.append(("fail", cmd, stderr or stdout or f"rc={rc}"))
            ok = False
    return ok, out


def cleanup(ex: dict, ns: str) -> None:
    for cmd in ex.get("cleanup", []):
        if cmd.startswith("echo "):
            continue
        # delete the namespace directly (nukes everything in it)
        run(f"kubectl delete ns {ns} --ignore-not-found --wait=false")
        return
    # fallback: run individual cleanup commands with namespace
    for cmd in ex.get("cleanup", []):
        if not cmd.startswith("echo "):
            c = cmd if "-n " in cmd or "--namespace " in cmd else f"{cmd} -n {ns}"
            run(c, timeout=60)


def print_ex(ex: dict, i: int, total: int, ns: str) -> None:
    print(f"\n{B}{CYN}{'=' * 60}{R}")
    print(f"{B}{CYN}  Exercise {i}/{total}  {D}ns={ns}{R}")
    print(f"{B}{CYN}{'=' * 60}{R}\n")
    print(f"{B}{WHT}{ex['title']}{R}\n")
    for h in ex.get("hints", []):
        print(f"  {D}{h}{R}")


def print_solution(ex: dict) -> None:
    print(f"\n{B}{GRN}--- Solution ---{R}")
    for cmd in ex["solution"]:
        print(f"  {GRN}{cmd}{R}")
    print(f"{GRN}---{R}\n")


def summary(session: dict) -> None:
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


# -- commands --

def cmd_run(args: argparse.Namespace) -> None:
    """Start a new session."""
    exercises = load_exercises(domain=args.domain)

    if args.review:
        # collect failed exercise ids across all sessions
        failed = set()
        for s in list_sessions():
            for e in s["exercises"]:
                if e["result"] == "failed":
                    failed.add(e["id"])
        if not failed:
            print(f"{GRN}Nothing to review.{R}")
            return
        exercises = [e for e in exercises if e["id"] in failed]

    if not exercises:
        print(f"{RED}No exercises found.{R}")
        sys.exit(1)

    exercises = select(exercises, count=args.count, seed=args.seed)
    sid = time.strftime("%Y%m%d-%H%M%S")
    session = create_session(sid, args.domain, [e["id"] for e in exercises])

    # cluster check
    _, _, rc = run("kubectl cluster-info 2>/dev/null")
    if rc != 0:
        print(f"{RED}No cluster. Run: scripts/setup.sh{R}")
        if input("Continue anyway? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit(1)

    def on_sigint(sig, frame):
        print(f"\n{YEL}Interrupted{R}")
        summary(load_session(sid))
        sys.exit(0)
    signal.signal(signal.SIGINT, on_sigint)

    total = len(exercises)
    t0 = time.time()

    print(f"\n{B}CKAD Practice - {total} exercises{R}")
    print(f"{D}Session: {sid}  ns prefix: {ns_prefix(sid)}{R}")
    print(f"{D}Enter=verify  s=solution  n=skip  q=quit{R}")
    print(f"{D}Target: {fmt_time(330 * total)} (~5.5 min/question){R}\n")
    time.sleep(1)

    for i, ex in enumerate(exercises, 1):
        ns = f"{ns_prefix(sid)}-{ex['domain'][:12]}"
        print_ex(ex, i, total, ns)

        ex_t0 = time.time()
        showed_solution = False

        while True:
            ans = input(f"  {D}> {R}").strip().lower()
            if ans == "q":
                cleanup(ex, ns)
                summary(load_session(sid))
                sys.exit(0)
            if ans == "s":
                print_solution(ex)
                showed_solution = True
                continue
            if ans == "n":
                elapsed = time.time() - ex_t0
                record_exercise(sid, ex["id"], False, elapsed)
                print(f"  {D}skipped{R}")
                break
            break

        if not args.no_verify and not showed_solution:
            print(f"  {D}verifying...{R}")
            ok, details = verify(ex, ns)
            elapsed = time.time() - ex_t0
            if ok:
                print(f"  {GRN}{B}PASSED{R}")
            else:
                print(f"  {RED}{B}FAILED{R}")
                for st, cmd, detail in details:
                    if st == "fail":
                        print(f"    {RED}{cmd}{R}")
                        print(f"    {D}{detail[:200]}{R}")
                if input(f"  {D}s for solution, enter to continue...{R}").strip().lower() == "s":
                    print_solution(ex)
            record_exercise(sid, ex["id"], ok, elapsed)
        else:
            elapsed = time.time() - ex_t0
            record_exercise(sid, ex["id"], False, elapsed)

        cleanup(ex, ns)
        session = load_session(sid)
        done, _ = session_progress(session)
        passed = sum(1 for e in session["exercises"] if e["result"] == "passed")
        print(f"\n  {D}{passed}/{done} passed | {fmt_time(time.time() - t0)}{R}")

    complete_session(sid)
    summary(load_session(sid))


def cmd_sessions(args: argparse.Namespace) -> None:
    """fzf picker to select and attach to a session."""
    sid = fzf_session_picker()
    if not sid:
        return
    session = load_session(sid)
    done, total = session_progress(session)
    print(f"\n{B}Session {sid}{R}  {done}/{total} done  {session['status']}")
    print(f"Domain: {session.get('domain') or 'all'}  ns prefix: {ns_prefix(sid)}\n")

    if session["status"] != "active":
        print(f"{D}Session is {session['status']}. Showing results only.{R}")
        summary(session)
        return

    ex = fzf_exercise_picker(session)
    if not ex:
        return
    print(f"  Selected: {ex}")
    print(f"  {D}To resume the full session, run: uv run ckad attach {sid}{R}")


def cmd_attach(args: argparse.Namespace) -> None:
    """Resume a session from where it left off."""
    session = load_session(args.session_id)
    if session["status"] != "active":
        print(f"{RED}Session {args.session_id} is {session['status']}{R}")
        sys.exit(1)

    # find next uncompleted exercise
    remaining = [e for e in session["exercises"] if e["result"] is None]
    if not remaining:
        print(f"{GRN}Session already complete.{R}")
        summary(session)
        return

    all_exercises = {e["id"]: e for e in load_exercises()}
    exercises = [all_exercises[e["id"]] for e in remaining if e["id"] in all_exercises]
    sid = args.session_id

    print(f"\n{B}Resuming session {sid}{R} - {len(exercises)} exercises remaining")
    print(f"{D}ns prefix: {ns_prefix(sid)}{R}\n")
    time.sleep(1)

    t0 = time.time()
    for i, ex in enumerate(exercises, 1):
        ns = f"{ns_prefix(sid)}-{ex['domain'][:12]}"
        print_ex(ex, i, len(exercises), ns)

        ex_t0 = time.time()
        showed_solution = False

        while True:
            ans = input(f"  {D}> {R}").strip().lower()
            if ans == "q":
                summary(load_session(sid))
                sys.exit(0)
            if ans == "s":
                print_solution(ex)
                showed_solution = True
                continue
            if ans == "n":
                record_exercise(sid, ex["id"], False, time.time() - ex_t0)
                print(f"  {D}skipped{R}")
                break
            break

        if not args.no_verify and not showed_solution:
            print(f"  {D}verifying...{R}")
            ok, details = verify(ex, ns)
            elapsed = time.time() - ex_t0
            if ok:
                print(f"  {GRN}{B}PASSED{R}")
            else:
                print(f"  {RED}{B}FAILED{R}")
                for st, cmd, detail in details:
                    if st == "fail":
                        print(f"    {RED}{cmd}{R}")
                        print(f"    {D}{detail[:200]}{R}")
                if input(f"  {D}s for solution, enter to continue...{R}").strip().lower() == "s":
                    print_solution(ex)
            record_exercise(sid, ex["id"], ok, elapsed)
        else:
            record_exercise(sid, ex["id"], False, time.time() - ex_t0)

        cleanup(ex, ns)
        session = load_session(sid)
        done, _ = session_progress(session)
        passed = sum(1 for e in session["exercises"] if e["result"] == "passed")
        print(f"\n  {D}{passed}/{done} passed | {fmt_time(time.time() - t0)}{R}")

    complete_session(sid)
    summary(load_session(sid))


def cmd_kill(args: argparse.Namespace) -> None:
    """Kill active sessions (fzf picker or direct id)."""
    sid = args.session_id or fzf_kill_picker()
    if not sid:
        return
    kill_session(sid)
    print(f"{GRN}Killed session {sid}{R}")


def cmd_delete(args: argparse.Namespace) -> None:
    """Delete session directory entirely."""
    sid = args.session_id or fzf_kill_picker()
    if not sid:
        return
    ch = input(f"Delete session {sid} and all its data? [y/N] ").strip().lower()
    if ch in ("y", "yes"):
        delete_session(sid)
        print(f"{GRN}Deleted session {sid}{R}")


def cmd_list(args: argparse.Namespace) -> None:
    """List sessions or exercises."""
    if args.target == "sessions":
        sessions = list_sessions()
        if not sessions:
            print(f"{D}No sessions.{R}")
            return
        print(f"\n{'ID':22s} {'DOMAIN':20s} {'PROGRESS':10s} {'STATUS'}")
        print("-" * 65)
        for s in sessions:
            done, total = session_progress(s)
            print(f"{s['id']:22s} {(s.get('domain') or 'all'):20s} {done}/{total:<8s} {s['status']}")
        print()
    else:
        exercises = load_exercises(domain=args.domain)
        by_d: dict[str, list] = {}
        for e in exercises:
            by_d.setdefault(e["domain"], []).append(e)
        print(f"\n{B}Domains:{R}")
        for d in sorted(by_d):
            exs = by_d[d]
            w = exs[0]["weight"] if exs else 0
            print(f"  {d:30s} {len(exs):3d} exercises  (weight: {w}%)")
        print(f"\n{B}All exercises:{R}")
        cur = None
        for e in exercises:
            if e["domain"] != cur:
                cur = e["domain"]
                print(f"\n  {CYN}{e['domain_name']}{R} ({e['weight']}%)")
            print(f"    {e['id']:30s} {e['title'][:65]}")
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

    # sessions (fzf picker)
    sub.add_parser("sessions", aliases=["ss"], help="pick a session with fzf")

    # attach
    attach_p = sub.add_parser("attach", aliases=["a"], help="resume a session")
    attach_p.add_argument("session_id")
    attach_p.add_argument("--no-verify", action="store_true")

    # kill
    kill_p = sub.add_parser("kill", aliases=["k"], help="kill active session")
    kill_p.add_argument("session_id", nargs="?")

    # delete
    del_p = sub.add_parser("delete", aliases=["rm"], help="delete session")
    del_p.add_argument("session_id", nargs="?")

    # list
    list_p = sub.add_parser("list", aliases=["ls"], help="list sessions or exercises")
    list_p.add_argument("target", nargs="?", default="sessions", choices=["sessions", "exercises"])
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
            summary(load_session(args.session_id))
        else:
            sid = fzf_session_picker()
            if sid:
                summary(load_session(sid))
    else:
        # default: run
        cmd_run(args)
