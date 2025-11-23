{{- define "netatmo-tt-system.name" -}}
{{ include "netatmo-tt-system.fullname" . }}
{{- end }}

{{- define "netatmo-tt-system.fullname" -}}
{{ .Chart.Name }}
{{- end }}