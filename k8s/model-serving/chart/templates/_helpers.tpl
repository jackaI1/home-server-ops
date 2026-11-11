{{- define "model-server.labels" -}}
app.kubernetes.io/name: model-server
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Values.image.tag | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "model-server.selectorLabels" -}}
app.kubernetes.io/name: model-server
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
