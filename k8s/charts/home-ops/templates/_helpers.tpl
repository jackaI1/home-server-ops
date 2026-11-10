{{- define "home-ops.labels" -}}
app.kubernetes.io/part-of: home-ops
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "home-ops.postgresHost" -}}
postgres
{{- end -}}

{{- define "home-ops.securityContext" -}}
allowPrivilegeEscalation: false
capabilities:
  drop: [ALL]
seccompProfile:
  type: RuntimeDefault
{{- end -}}
