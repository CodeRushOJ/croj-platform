{{- define "coderushoj.image" -}}
{{- $name := .name -}}
{{- $image := .image -}}
{{- if and $image.requireDigest (empty $image.digest) -}}
{{- fail (printf "%s.image.digest is required when %s.image.requireDigest=true" $name $name) -}}
{{- end -}}
{{- if $image.digest -}}
{{- printf "%s@%s" $image.repository $image.digest -}}
{{- else -}}
{{- printf "%s:%s" $image.repository $image.tag -}}
{{- end -}}
{{- end -}}

{{- define "coderushoj.selectorLabels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}
