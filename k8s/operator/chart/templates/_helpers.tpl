{{- define "serviceapp-operator.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "serviceapp-operator.labels" -}}
app.kubernetes.io/name: {{ include "serviceapp-operator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "serviceapp-operator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "serviceapp-operator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
