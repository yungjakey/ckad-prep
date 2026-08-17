# CKAD Prep - Setup

## Prerequisites
- kind, kubectl, helm installed
- Python 3.10+
- uv (https://docs.astral.sh/uv/)
- fzf (https://github.com/junegunn/fzf) for session pickers

## First-time setup
```bash
uv sync
scripts/setup.sh      # creates kind cluster + metrics-server + ingress-nginx
```

## Usage

### Run a new session
```bash
uv run ckad                      # 10 random exercises
uv run ckad run -n 5             # 5 exercises
uv run ckad run -d configuration # one domain
uv run ckad run --review         # redo previously failed exercises
```

### Session management
```bash
uv run ckad sessions             # fzf picker: list/attach to sessions
uv run ckad attach <session-id>  # resume a session from where you left off
uv run ckad kill                 # fzf picker: kill active session + k8s namespaces
uv run ckad kill <session-id>    # kill specific session
uv run ckad delete               # fzf picker: delete session data
```

### List
```bash
uv run ckad ls                   # list sessions
uv run ckad ls exercises         # list all exercises
uv run ckad ls exercises -d config  # list by domain
```

### Results
```bash
uv run ckad results              # fzf picker for session results
uv run ckad results <session-id> # show specific session results
```

## Session model
- Sessions live in `~/.ckad/sessions/<timestamp>/session.json`
- Each session tracks exercises selected, results, and status
- Exercise namespaces use prefix `ckad-<session[:8]>-<domain>` for isolation
- Killing a session deletes all its k8s namespaces
- Sessions persist between runs; attach to resume unfinished ones

## Teardown
```bash
scripts/cleanup.sh
```

## Re-generating exercises
```bash
python3 parse_exercises.py ../CKAD-exercises src/ckad/exercises
```
