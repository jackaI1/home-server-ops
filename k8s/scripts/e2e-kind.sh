#!/usr/bin/env bash
# End-to-end checks against an already deployed release (see .github/workflows/kubernetes.yml).
# Checks rollouts, the API, a backup and a restore, and which pods can reach which.
# Needs kubectl and the kubeconfig pointing at the test cluster. Cleans up its probe pods.
set -euo pipefail

NS="${NS:-home-ops}"
PORT="${PORT:-18000}"
RESULTS=0
PROBES=(probe-allowed probe-stranger)
forward_pid=""

# shellcheck disable=SC2329  # called by the EXIT trap
cleanup() {
  [[ -n "$forward_pid" ]] && kill "$forward_pid" 2>/dev/null || true
  kubectl -n "$NS" delete pod "${PROBES[@]}" --ignore-not-found --wait=false >/dev/null 2>&1 || true
  kubectl delete pod probe-outside -n default --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT

pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; RESULTS=1; }

check() {  # check <expected: ok|blocked> <description> <command...>
  local expected="$1" desc="$2"; shift 2
  if "$@" >/dev/null 2>&1; then actual=ok; else actual=blocked; fi
  if [[ "$actual" == "$expected" ]]; then pass "$desc ($actual)"; else fail "$desc (expected $expected, got $actual)"; fi
}

kubectl -n "$NS" rollout status deployment/telemetry --timeout=180s
kubectl -n "$NS" rollout status statefulset/postgres --timeout=180s

echo "== API"
kubectl -n "$NS" port-forward service/telemetry "$PORT:80" >/tmp/home-ops-forward.log 2>&1 &
forward_pid=$!
for _ in $(seq 1 30); do curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break; sleep 1; done
check ok "health endpoint answers" curl -fsS "http://127.0.0.1:$PORT/health"
check ok "record is accepted" curl -fsS -X POST "http://127.0.0.1:$PORT/passes" -H 'Content-Type: application/json' \
  -d '{"satellite":"e2e","observed_at":"2025-01-01T00:00:00Z","elevation":45}'
readback="$(curl -fsS "http://127.0.0.1:$PORT/passes?satellite=e2e")"
if [[ "$readback" == *'"e2e"'* ]]; then pass "record is read back"; else fail "record is not read back"; fi
kill "$forward_pid" 2>/dev/null || true; forward_pid=""

echo "== backup and restore"
kubectl -n "$NS" delete job manual-backup restore-check --ignore-not-found --wait=true
kubectl -n "$NS" create job --from=cronjob/backup manual-backup
kubectl -n "$NS" wait --for=condition=complete job/manual-backup --timeout=300s
backup_log="$(kubectl -n "$NS" logs job/manual-backup)"
if [[ "$backup_log" == *"wrote /backups/telemetry-"* ]]; then pass "backup wrote a dump"; else fail "backup did not write a dump"; fi

echo "== restore the dump into a scratch database and compare row counts"
kubectl -n "$NS" apply -f - <<YAML
apiVersion: batch/v1
kind: Job
metadata:
  name: restore-check
  labels: {app.kubernetes.io/component: backup}
spec:
  backoffLimit: 0
  template:
    metadata:
      labels: {app.kubernetes.io/name: backup, app.kubernetes.io/component: backup}
    spec:
      restartPolicy: Never
      securityContext: {runAsNonRoot: true, runAsUser: 999, runAsGroup: 999, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: restore
          image: postgres:16
          env:
            - {name: PGHOST, value: postgres}
            - {name: PGUSER, value: telemetry}
            - {name: PGPASSWORD, valueFrom: {secretKeyRef: {name: postgres-credentials, key: POSTGRES_PASSWORD}}}
          command: [sh, -c]
          args:
            - |
              set -eu
              latest=\$(ls -t /backups/telemetry-*.sql.gz | head -1)
              psql -d postgres -v ON_ERROR_STOP=1 -c 'DROP DATABASE IF EXISTS restore_check' -c 'CREATE DATABASE restore_check'
              gunzip -c "\$latest" | psql -d restore_check -v ON_ERROR_STOP=1 -q
              restored=\$(psql -d restore_check -Atc 'SELECT count(*) FROM passes')
              live=\$(psql -d telemetry -Atc 'SELECT count(*) FROM passes')
              echo "live=\$live restored=\$restored"
              if [ "\$restored" -eq 0 ] || [ "\$restored" -ne "\$live" ]; then
                echo "row count mismatch: live=\$live restored=\$restored" >&2
                exit 1
              fi
              psql -d postgres -qc 'DROP DATABASE restore_check'
          securityContext:
            allowPrivilegeEscalation: false
            capabilities: {drop: [ALL]}
          volumeMounts:
            - {name: backups, mountPath: /backups, readOnly: true}
      volumes:
        - name: backups
          persistentVolumeClaim: {claimName: backups}
YAML
if kubectl -n "$NS" wait --for=condition=complete job/restore-check --timeout=300s; then
  pass "restore completed and row counts match"
else
  fail "restore failed"
fi
kubectl -n "$NS" logs job/restore-check | tail -3

echo "== network policy enforcement (probe pods)"
probe_pod() {  # probe_pod <name> <label-key=value or empty>
  local labels="app: unrelated"
  [[ -n "$2" ]] && labels="${2%%=*}: ${2#*=}"
  cat <<POD
apiVersion: v1
kind: Pod
metadata: {name: $1, labels: {$labels}}
spec:
  securityContext: {runAsNonRoot: true, runAsUser: 65534, seccompProfile: {type: RuntimeDefault}}
  containers:
    - name: probe
      image: busybox:1.36
      command: [sleep, "900"]
      securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
POD
}
{ probe_pod probe-allowed access=telemetry-client; echo '---'; probe_pod probe-stranger ""; } | kubectl -n "$NS" apply -f -
kubectl -n default apply -f - >/dev/null <<YAML
apiVersion: v1
kind: Pod
metadata: {name: probe-outside}
spec:
  containers:
    - name: probe
      image: busybox:1.36
      command: [sleep, "900"]
YAML
kubectl -n "$NS" wait --for=condition=Ready pod/probe-allowed pod/probe-stranger --timeout=180s
kubectl wait --for=condition=Ready pod/probe-outside -n default --timeout=180s

# shellcheck disable=SC2329  # called through check
http_ok() { kubectl exec -n "$1" "$2" -- wget -q -T 4 -O- "http://telemetry.$NS.svc.cluster.local/health"; }
# shellcheck disable=SC2329  # called through check
db_ok() { kubectl exec -n "$1" "$2" -- nc -z -w 4 "postgres.$NS.svc.cluster.local" 5432; }

check ok      "labelled client in $NS reaches the API"            http_ok "$NS" probe-allowed
check blocked "pod in another namespace is refused by the API"   http_ok default probe-outside
check blocked "unlabelled pod in $NS is refused by the API"      http_ok "$NS" probe-stranger
check blocked "labelled client cannot reach PostgreSQL directly" db_ok "$NS" probe-allowed
check blocked "other namespace cannot reach PostgreSQL"          db_ok default probe-outside
check blocked "unlabelled pod cannot reach PostgreSQL"           db_ok "$NS" probe-stranger
check ok      "cluster DNS still resolves from a locked-down pod" kubectl exec -n "$NS" probe-stranger -- nslookup telemetry."$NS".svc.cluster.local
check blocked "locked-down pod cannot reach the internet"        kubectl exec -n "$NS" probe-stranger -- wget -q -T 4 -O- http://1.1.1.1

if [[ $RESULTS -eq 0 ]]; then echo "ALL CHECKS PASSED"; else echo "SOME CHECKS FAILED"; fi
exit $RESULTS
