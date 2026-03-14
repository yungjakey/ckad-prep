# CKAD Exam Reference

## Init
```bash
set -o vi

alias e=vim
alias c=clear
alias kg="k get"
alias kd="k describe"
alias kr="k run"
alias ke="k exec"
alias ka="k apply -f"
alias kc="k config"
alias kx="kc use-context"                                            # poor mans kubectx
alias kn="kc set-context --current --namespace"                      # poor mans kubens

del() { k delete "$@" --grace-period 0 --force; }                    # delete a resource without waiting
run() { kr tmp --image nginx:alpine --rm -it -- "$@"; del pod tmp; } # run a cmd in an existing pod
s() { ssh ckad$1; }                                                  # ssh into ckad scenario
p() { scp .bash_aliases ckad$1:~/; }                                 # scp custom aliases into remote

export VIMINIT="set ai"                                              # set autoindent to work on remote
```

## Shell shortcuts
### History

| expression | meaning | example |
|---|---|---|
| `!!` | last command | `sudo !!` |
| `!$` | last arg of prev cmd | `vim !$` |
| `!*` | all args of prev cmd | `cp !* ~/backup/` |
| `!^` | first arg of prev cmd | `cat !^` |
| `!:2` | 2nd word (0=cmd, 1=first arg…) | `echo !:2` |
| `!:2-4` | words 2 through 4 | `cp !:2-4 /tmp/` |
| `!:2*` | word 2 to end | `rm !:2*` |
| `!cmd` | last cmd starting with "cmd" | `!git` |
| `!?str?` | last cmd containing "str" | `!?kubectl?` |
| `^old^new` | quick substitution in last cmd | `^typo^fixed` |
| `!!:gs/a/b` | global substitution on last cmd | `!!:gs/dev/prd` |

### Arguments

| expression | meaning | example |
|---|---|---|
| `"${@:2}"` | all args from $2 onward | `f() { cmd "${@:2}"; }` |
| `"${@:2:3}"` | 3 args starting at $2 | `f() { cmd "${@:2:3}"; }` |
| `"${@:(-2)}"` | last 2 args | `f() { cmd "${@:(-2)}"; }` |
| `"${@:1:$#-1}"` | all args except last | `f() { cmd "${@:1:$#-1}"; }` |
| `$#` | arg count | `[ $# -lt 2 ] && exit 1` |
| `$0` | script / function name | `echo "Usage: $0 <file>"` |

## Context & Namespace
```bash
kn <ns>              # switch namespace       — do FIRST on every question
kx <ctx>             # switch context         - rarely needed
kc view --minify     # verify current context - if unsure
```

## Pods
```bash
# Generate base yaml
kr pod1 --image=nginx $do > pod.yaml
kr pod1 --image=busybox $do --command -- sh -c "sleep 2d" > pod.yaml
e pod.yaml
ka pod.yaml

kg pod
kd pod
k logs pod1
k logs pod1 -c container-name        # multi-container pod
ke -it pod1 -- sh
ke -it deploy/frontend -- sh
ke deploy/frontend -- wget api:2222
del pod1

# Temporary pod for testing
run -- curl api:2222
run -- wget www.google.com
```

## Deployments
```bash
k create deploy nginx --image=nginx --replicas=3
k scale deploy nginx --replicas=5
k set image deploy/nginx nginx=nginx:1.25
k rollout status deploy/nginx
k rollout history deploy/nginx
k rollout history deploy/nginx --revision=3   # inspect specific revision image
k rollout undo deploy/nginx                   # undo to previous revision
k rollout undo deploy/nginx --to-revision=2
k edit deploy nginx                           # live edit, saves immediately
```

## Deployment Strategies
```bash
# Blue/Green — two full deployments, switch service selector
# 1. deploy v2 alongside v1 (different label e.g. version: v2)
# 2. k edit svc my-svc  →  change selector to point to v2
# 3. del old deployment when confirmed

# Canary — route small % of traffic to new version
# 1. deploy v2 with fewer replicas (e.g. 1 vs 9 for v1)
# 2. both deployments share same service selector label
# 3. gradually scale v2 up, v1 down
```


## CronJobs

```bash
k create cronjob backup --schedule="*/1 * * * *" --image=busybox -- sh -c 'date'
```

| Position | Field        | Range |
|----------|--------------|-------|
| 1        | Minute       | 0–59  |
| 2        | Hour         | 0–23  |
| 3        | Day of Month | 1–31  |
| 4        | Month        | 1–12  |
| 5        | Day of Week  | 0–6   |

| Char | Meaning | Example |
|------|---------|---------|
| `*`  | Every value | `*` |
| `,`  | List | `1,5` |
| `-`  | Range | `1-5` |
| `/`  | Step | `*/10` |

| Macro | Equivalent |
|-------|------------|
| `@yearly` / `@annually` | `0 0 1 1 *` |
| `@monthly` | `0 0 1 * *` |
| `@weekly` | `0 0 * * 0` |
| `@daily` / `@midnight` | `0 0 * * *` |
| `@hourly` | `0 * * * *` |

## ConfigMaps & Secrets
```bash
# ConfigMap
k create cm app-config --from-literal=KEY=val
k create cm web-config --from-file=index.html=/path/to/file   # key=filename

# Secret
k create secret generic app-secret --from-literal=user=test --from-literal=pass=pwd
```

## Labels & Annotations
```bash
kg pod -l app=v1
k label pod nginx app=v2 --overwrite
k annotate pod nginx description='desc'

# Bulk operations — modifies ALL matching pods in one shot
k label pod -l type=worker protected=true
k label pod -l type=runner protected=true
k annotate pod -l protected=true protected="do not delete this pod"
```

## RBAC
```bash
k create sa my-sa
k create role pod-reader --verb=get,list,watch --resource=pods
k create rolebinding rb --role=pod-reader --serviceaccount=default:my-sa
k auth can-i list pods --as=system:serviceaccount:default:my-sa

# ClusterRole / ClusterRoleBinding for cluster-wide access
k create clusterrole pod-reader --verb=get,list,watch --resource=pods
k create clusterrolebinding crb --clusterrole=pod-reader --serviceaccount=default:my-sa
```

## Services
```bash
# Expose pod or deployment
k expose pod nginx --port=80 --name=nginx-svc
k expose deploy nginx --port=80 --name=nginx-svc
k expose pod my-pod --name=my-svc --port=3333 --target-port=80

# Service types:
# ClusterIP    — internal only (default)
# NodePort     — exposes on every node IP:port (external, manual)
# LoadBalancer — cloud LB, includes NodePort (external, automatic)

# NodePort fields (outside→inside):
# nodePort: 30100  — external traffic hits node on this port
# port: 8080       — service listens on this port inside cluster
# targetPort: 80   — forwards to container on this port

# Fix selector mismatch (common exam issue):
kg svc my-svc -o yaml | grep -A3 selector   # check svc selector
kg pods --show-labels                        # check pod labels
k edit svc my-svc                            # fix selector to match pods

# DNS:
# within same namespace: curl api:2222
# cross-namespace:       curl api.venus:2222

kg endpoints my-svc
```

## Ingress
```bash
k create ingress my-ing --rule="host/path=svc:port"
kg ingress
kd ingress my-ing
```

## Observability
```bash
k logs pod1
k logs pod1 --previous                           # logs from crashed container
k logs pod1 -c container-name                    # specific container
k logs deploy/my-deploy -c sidecar-con           # sidecar logs
k top pod                                        # resource usage
k top pod --containers                           # per container
k top node
```

## Debug
```bash
kd pod nginx
kd pod nginx | grep -A5 Events     # most useful — shows what's wrong
k logs pod1 --previous             # logs from crashed container
kg pod nginx -o yaml > fix.yaml
e fix.yaml
del pod nginx && ka fix.yaml       # force recreate
kg events -n my-ns                 # cluster-wide events
k top pod                          # check resource usage
```

## Quick Ref
```bash
k explain pod.spec.containers
k explain job.spec
k explain networkpolicy.spec.egress
kg pod -o jsonpath='{.status.podIP}'
kg pods -o custom-columns=NAME:.metadata.name,IP:.status.podIP
kg pods --show-labels
kg all -n my-ns                    # get everything in namespace
k api-resources                    # list all resource types with shortnames
k api-resources --namespaced=true  # only namespaced resources
```
## Docker / Podman
```bash
# run sudo first
sudo -i 

# docker
docker build -t registry.example.com/image:tag /path
docker push registry.example.com/image:tag
docker ps

# podman
podman images
podman run -d --name my-container registry.example.com/image:tag
podman logs my-container > /path/to/logs
```

## Helm
```bash
helm repo add <n> <url>
helm repo update
helm search repo <chart> --versions              # find available versions
helm install <release> <chart>
helm install <release> <chart> --set replicaCount=2
helm upgrade <release> <chart>                   # upgrade to latest
helm delete <release>
helm list                                        # list all releases
helm list --pending                              # find stuck/broken releases
```

