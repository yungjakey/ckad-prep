#!/usr/bin/env python3
"""Parse CKAD-exercises markdown files into structured YAML exercise definitions."""

import re
import sys
import os
import yaml
from pathlib import Path

DOMAINS = {
    "a.core_concepts":        ("core_concepts", "Core Concepts", 13),
    "b.multi_container_pods": ("multi_container_pods", "Multi-container Pods", 10),
    "c.pod_design":           ("pod_design", "Pod Design", 20),
    "d.configuration":        ("configuration", "Configuration", 18),
    "e.observability":        ("observability", "Observability", 18),
    "f.services":             ("services_networking", "Services & Networking", 13),
    "g.state":                ("state_persistence", "State Persistence", 8),
    "h.helm":                 ("helm", "Helm", 0),
    "i.crd":                  ("crd", "Custom Resource Definitions", 0),
}


def extract_sections(md_text):
    """Split markdown into exercise sections by ### headings."""
    sections = []
    current = None
    for line in md_text.splitlines():
        if line.startswith("### "):
            if current:
                sections.append(current)
            current = {"title": line[4:].strip(), "lines": []}
        elif current is not None:
            current["lines"].append(line)
    if current:
        sections.append(current)
    return sections


def clean_solution_lines(raw_lines):
    """Clean solution lines: remove comments, editor commands, trim, skip blanks."""
    editor_re = re.compile(r'^(vi|vim|nano|emacs)\s+')
    cleaned = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip editor commands
        if editor_re.match(stripped):
            continue
        # Skip cat/echo of generated files (manual inspection steps)
        if stripped.startswith("cat ") and not stripped.startswith("cat /"):
            continue
        # Skip pure comment lines
        if stripped.startswith("#"):
            # Keep comments that are alternative solutions or notes with kubectl
            if "kubectl" in stripped or "helm" in stripped:
                stripped = stripped.lstrip("# ").strip()
            else:
                continue
        # Strip inline comments (but not in quoted strings)
        if "  #" in stripped:
            code_part = stripped[:stripped.index("  #")].strip()
            if code_part:
                stripped = code_part
        # Skip YAML content from embedded examples
        yaml_starts = ("apiVersion:", "kind:", "metadata:", "spec:", "status:",
                       "  containers:", "  volumes:", "  rules:", "  ports:")
        if any(stripped.startswith(y) for y in yaml_starts):
            continue
        if stripped.startswith("- ") and not stripped.startswith("- kubectl"):
            continue
        cleaned.append(stripped)
    return cleaned


def extract_solution(section_lines):
    """Extract solution commands from <details> blocks, returning cleaned command lists."""
    in_details = False
    in_code = False
    code_lang = None
    blocks = []
    current_block = []

    for line in section_lines:
        if "<details>" in line:
            in_details = True
            continue
        if "</details>" in line:
            in_details = False
            if current_block:
                blocks.append(current_block)
                current_block = []
            continue
        if not in_details:
            continue

        # Track code block state
        if "```bash" in line or "```sh" in line:
            in_code = True
            code_lang = "bash"
            continue
        if "```yaml" in line or "```YAML" in line:
            in_code = True
            code_lang = "yaml"
            continue
        if "```" in line and in_code:
            in_code = False
            code_lang = None
            if current_block:
                blocks.append(current_block)
                current_block = []
            continue

        if in_code and code_lang == "bash":
            stripped = line.strip()
            if stripped:
                current_block.append(stripped)

    return blocks


def extract_hints(section_lines):
    """Extract k8s doc reference links as hints."""
    hints = []
    for line in section_lines:
        m = re.search(r'kubernetes\.io.*?\[([^\]]+)\]\(([^)]+)\)', line)
        if m:
            hints.append(f"{m.group(1)}: {m.group(2)}")
    return hints


def infer_cleanup(solution_blocks):
    """Generate cleanup commands from solution blocks."""
    cleanup = []
    seen = set()

    for block in solution_blocks:
        for cmd in block:
            cmd_s = cmd.strip()
            # If solution already has delete, use it
            if cmd_s.startswith("kubectl delete"):
                if cmd_s not in seen:
                    cleanup.append(cmd_s)
                    seen.add(cmd_s)
                continue

            # Infer cleanup from creation commands
            # Namespaces (catch-all: deleting ns deletes everything in it)
            m = re.search(r"kubectl create (?:ns|namespace)\s+(\S+)", cmd_s)
            if m and m.group(1) != "default":
                c = f"kubectl delete ns {m.group(1)} --ignore-not-found"
                if c not in seen:
                    cleanup.append(c)
                    seen.add(c)
                continue

            # Pods
            m = re.search(r"kubectl run\s+(\S+)", cmd_s)
            if m:
                name = m.group(1)
                ns = ""
                ns_m = re.search(r"-n\s+(\S+)", cmd_s)
                if ns_m and ns_m.group(1) != "default":
                    ns = f" -n {ns_m.group(1)}"
                # Skip if --rm flag (auto-cleanup)
                if "--rm" not in cmd_s:
                    c = f"kubectl delete po {name}{ns} --ignore-not-found"
                    if c not in seen:
                        cleanup.append(c)
                        seen.add(c)
                continue

            # Deployments
            m = re.search(r"kubectl create (?:deploy|deployment)\s+(\S+)", cmd_s)
            if m:
                c = f"kubectl delete deploy {m.group(1)} --ignore-not-found"
                if c not in seen:
                    cleanup.append(c)
                    seen.add(c)
                continue

            # Services
            m = re.search(r"kubectl (?:expose|create svc|create service)\s+.*?--name=(\S+)", cmd_s)
            if m:
                c = f"kubectl delete svc {m.group(1)} --ignore-not-found"
                if c not in seen:
                    cleanup.append(c)
                    seen.add(c)
                continue

            # ConfigMaps
            m = re.search(r"kubectl create (?:cm|configmap)\s+(\S+)", cmd_s)
            if m:
                c = f"kubectl delete cm {m.group(1)} --ignore-not-found"
                if c not in seen:
                    cleanup.append(c)
                    seen.add(c)
                continue

            # Secrets
            m = re.search(r"kubectl create secret\s+\S+\s+(\S+)", cmd_s)
            if m:
                c = f"kubectl delete secret {m.group(1)} --ignore-not-found"
                if c not in seen:
                    cleanup.append(c)
                    seen.add(c)
                continue

            # ServiceAccounts
            m = re.search(r"kubectl create (?:sa|serviceaccount)\s+(\S+)", cmd_s)
            if m:
                c = f"kubectl delete sa {m.group(1)} --ignore-not-found"
                if c not in seen:
                    cleanup.append(c)
                    seen.add(c)
                continue

            # Jobs
            m = re.search(r"kubectl create job\s+(\S+)", cmd_s)
            if m:
                c = f"kubectl delete job {m.group(1)} --ignore-not-found"
                if c not in seen:
                    cleanup.append(c)
                    seen.add(c)
                continue

            # CronJobs
            m = re.search(r"kubectl create cronjob\s+(\S+)", cmd_s)
            if m:
                c = f"kubectl delete cj {m.group(1)} --ignore-not-found"
                if c not in seen:
                    cleanup.append(c)
                    seen.add(c)
                continue

            # ResourceQuota
            m = re.search(r"kubectl create quota\s+(\S+)", cmd_s)
            if m:
                # Need namespace context
                ns = "default"
                ns_m = re.search(r"(?:--namespace|-n)\s+(\S+)", cmd_s)
                if ns_m:
                    ns = ns_m.group(1)
                c = f"kubectl delete quota {m.group(1)} -n {ns} --ignore-not-found"
                if c not in seen:
                    cleanup.append(c)
                    seen.add(c)
                continue

            # LimitRange
            m = re.search(r"kubectl apply -f\s+\S+.*limitrange", cmd_s, re.IGNORECASE)
            # Hard to infer, skip

            # HPA
            if "kubectl autoscale" in cmd_s:
                c = "kubectl delete hpa --all --ignore-not-found"
                if c not in seen:
                    cleanup.append(c)
                    seen.add(c)
                continue

            # Taints
            m = re.search(r"kubectl taint node\s+(\S+)\s+(\S+)", cmd_s)
            if m:
                c = f"kubectl taint node {m.group(1)} {m.group(2)}- 2>/dev/null || true"
                if c not in seen:
                    cleanup.append(c)
                    seen.add(c)
                continue

    return cleanup if cleanup else ["echo 'No cleanup needed'"]


def infer_verify(solution_blocks):
    """Generate verification commands from solution blocks."""
    verifies = []
    seen = set()

    for block in solution_blocks:
        for cmd in block:
            cmd_s = cmd.strip()

            # Use existing get/describe commands as verify
            if cmd_s.startswith("kubectl get") or cmd_s.startswith("kubectl describe"):
                if cmd_s not in seen:
                    verifies.append(cmd_s)
                    seen.add(cmd_s)
                continue

            # Derive verify from creation commands
            m = re.search(r"kubectl run\s+(\S+)", cmd_s)
            if m and "--rm" not in cmd_s:
                name = m.group(1)
                ns = ""
                ns_m = re.search(r"-n\s+(\S+)", cmd_s)
                if ns_m:
                    ns = f" -n {ns_m.group(1)}"
                v = f"kubectl get po {name}{ns} -o jsonpath='{{.status.phase}}'"
                if v not in seen:
                    verifies.append(v)
                    seen.add(v)
                continue

            m = re.search(r"kubectl create (?:deploy|deployment)\s+(\S+)", cmd_s)
            if m:
                v = f"kubectl get deploy {m.group(1)} -o jsonpath='{{.status.readyReplicas}}'"
                if v not in seen:
                    verifies.append(v)
                    seen.add(v)
                continue

            m = re.search(r"kubectl create job\s+(\S+)", cmd_s)
            if m:
                v = f"kubectl get job {m.group(1)} -o jsonpath='{{.status.succeeded}}'"
                if v not in seen:
                    verifies.append(v)
                    seen.add(v)
                continue

            m = re.search(r"kubectl create (?:cm|configmap)\s+(\S+)", cmd_s)
            if m:
                v = f"kubectl get cm {m.group(1)} -o jsonpath='{{.data}}'"
                if v not in seen:
                    verifies.append(v)
                    seen.add(v)
                continue

            m = re.search(r"kubectl create secret\s+\S+\s+(\S+)", cmd_s)
            if m:
                v = f"kubectl get secret {m.group(1)} -o jsonpath='{{.data}}'"
                if v not in seen:
                    verifies.append(v)
                    seen.add(v)
                continue

            m = re.search(r"kubectl create (?:ns|namespace)\s+(\S+)", cmd_s)
            if m:
                v = f"kubectl get ns {m.group(1)} -o name"
                if v not in seen:
                    verifies.append(v)
                    seen.add(v)
                continue

            m = re.search(r"kubectl create (?:sa|serviceaccount)\s+(\S+)", cmd_s)
            if m:
                v = f"kubectl get sa {m.group(1)} -o jsonpath='{{.metadata.name}}'"
                if v not in seen:
                    verifies.append(v)
                    seen.add(v)
                continue

            m = re.search(r"kubectl create cronjob\s+(\S+)", cmd_s)
            if m:
                v = f"kubectl get cj {m.group(1)} -o jsonpath='{{.spec.schedule}}'"
                if v not in seen:
                    verifies.append(v)
                    seen.add(v)
                continue

    return verifies if verifies else ["echo 'Verify manually'"]


def is_trivial_query(title, solution_blocks):
    """Check if an exercise is just a query with no creation action."""
    all_cmds = " ".join(" ".join(b) for b in solution_blocks)
    has_creation = any(kw in all_cmds for kw in [
        "kubectl create", "kubectl run", "kubectl apply",
        "kubectl expose", "kubectl label", "kubectl taint",
        "kubectl autoscale", "kubectl set",
    ])
    is_query = any(kw in title.lower() for kw in [
        "get ", "show ", "display ", "view ", "describe ",
        "check ", "see ", "confirm ",
    ])
    return is_query and not has_creation


def should_merge_with_previous(current_title, prev_title):
    """Determine if current exercise should be merged with previous one."""
    ct = current_title.lower()
    pt = prev_title.lower()
    # Always merge query-only follow-ups
    query_keywords = [
        "display its", "show its", "view the", "check the",
        "get the", "see its", "confirm",
    ]
    if any(kw in ct for kw in query_keywords):
        return True
    # Merge sequential PV -> PVC -> pod exercises
    if "persistentvolumeclaim" in ct and "persistentvolume" in pt and "second pod" not in ct:
        return True
    if "busybox pod" in ct and "persistentvolumeclaim" in pt and "copy" not in ct:
        return True
    if "second pod" in ct and "busybox" in pt and "persistentvolumeclaim" in pt:
        return True
    # Merge "delete the pod you just created and mount"
    if "delete the pod" in ct and "mount" in ct:
        return True
    return False


def parse_file(filepath):
    """Parse a single markdown file into exercise dicts."""
    with open(filepath) as f:
        md_text = f.read()

    stem = Path(filepath).stem
    if stem not in DOMAINS:
        return []

    domain_id, domain_name, weight = DOMAINS[stem]
    sections = extract_sections(md_text)
    exercises = []

    for i, section in enumerate(sections):
        title = section["title"]
        lines = section["lines"]

        if len(lines) < 2:
            continue
        if title.startswith("[") and "](#" in title:
            continue

        solution_blocks = extract_solution(lines)
        hints = extract_hints(lines)

        if not solution_blocks:
            continue

        # Clean all solution blocks
        cleaned_blocks = [clean_solution_lines(block) for block in solution_blocks]
        cleaned_blocks = [b for b in cleaned_blocks if b]

        if not cleaned_blocks:
            continue

        cleanup = infer_cleanup(cleaned_blocks)
        verify = infer_verify(cleaned_blocks)

        # Flatten solution for display
        all_solution = []
        for block in cleaned_blocks:
            all_solution.extend(block)

        ex_id = f"{domain_id}-{i:02d}"
        ex = {
            "id": ex_id,
            "domain": domain_id,
            "domain_name": domain_name,
            "weight": weight,
            "title": title,
            "task": title,
            "hints": hints[:3],  # limit hints
            "solution": all_solution,
            "verify": verify,
            "cleanup": cleanup,
        }
        exercises.append(ex)

    return exercises


def merge_sequential(exercises):
    """Merge trivial query exercises and sequential state exercises."""
    if not exercises:
        return exercises

    merged = [exercises[0]]
    for ex in exercises[1:]:
        prev = merged[-1]
        if should_merge_with_previous(ex["title"], prev["title"]):
            prev["title"] += f" -> {ex['title']}"
            prev["solution"].append(f"# Then: {ex['title']}")
            prev["solution"].extend(ex["solution"])
            prev["verify"].extend(ex["verify"])
        else:
            merged.append(ex)
    return merged


def main():
    repo_path = sys.argv[1] if len(sys.argv) > 1 else "../CKAD-exercises"
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "exercises"

    os.makedirs(out_dir, exist_ok=True)

    md_files = sorted(Path(repo_path).glob("*.md"))
    all_exercises = []

    for md_file in md_files:
        if md_file.name in ("README.md", "LICENSE", "CODE_OF_CONDUCT.md", "j.podman.md"):
            continue
        exercises = parse_file(str(md_file))
        exercises = merge_sequential(exercises)
        all_exercises.extend(exercises)
        print(f"  {md_file.name}: {len(exercises)} exercises")

    # Write per-domain files
    by_domain = {}
    for ex in all_exercises:
        by_domain.setdefault(ex["domain"], []).append(ex)

    for domain_id, domain_exercises in sorted(by_domain.items()):
        out_path = os.path.join(out_dir, f"{domain_id}.yaml")
        with open(out_path, "w") as f:
            yaml.dump(domain_exercises, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        print(f"  -> {out_path} ({len(domain_exercises)} exercises)")

    # Write index
    index_path = os.path.join(out_dir, "index.yaml")
    index = [{"id": ex["id"], "domain": ex["domain"], "title": ex["title"], "weight": ex["weight"]}
             for ex in all_exercises]
    with open(index_path, "w") as f:
        yaml.dump(index, f, default_flow_style=False, sort_keys=False)

    print(f"\nTotal: {len(all_exercises)} exercises across {len(by_domain)} domains")


if __name__ == "__main__":
    main()
