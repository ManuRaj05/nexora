{{- define "nexora.labels" -}}
app.kubernetes.io/part-of: nexora
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "nexora.selector" -}}
app.kubernetes.io/part-of: nexora
app.kubernetes.io/name: {{ .name }}
{{- end -}}
