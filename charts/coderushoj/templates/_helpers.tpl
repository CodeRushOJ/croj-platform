{{- define "coderushoj.image" -}}
{{- if eq .profile "production" -}}
{{- $digest := required (printf "production image digest is required for %s" .image.repository) .image.digest -}}
{{- printf "%s@%s" .image.repository $digest -}}
{{- else if .image.digest -}}
{{- printf "%s@%s" .image.repository .image.digest -}}
{{- else -}}
{{- printf "%s:%s" .image.repository .image.tag -}}
{{- end -}}
{{- end -}}

{{- define "coderushoj.selectorLabels" -}}
app.kubernetes.io/name: coderushoj
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
