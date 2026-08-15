{{- define "chronos-birthday-api.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "chronos-birthday-api.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "chronos-birthday-api.labels" -}}
helm.sh/chart: {{ include "chronos-birthday-api.name" . }}-{{ .Chart.Version | replace "+" "_" }}
{{ include "chronos-birthday-api.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "chronos-birthday-api.selectorLabels" -}}
app.kubernetes.io/name: {{ include "chronos-birthday-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Get PostgreSQL host
*/}}
{{- define "chronos-birthday-api.dbHost" -}}
{{- if .Values.postgresql.enabled -}}
{{- printf "%s-postgresql" .Release.Name -}}
{{- else -}}
{{- .Values.externalDatabase.host -}}
{{- end -}}
{{- end -}}

{{/*
Get Database Connection URL
*/}}
{{- define "chronos-birthday-api.databaseUrl" -}}
{{- if .Values.postgresql.enabled -}}
{{- printf "postgresql://%s:%s@%s-postgresql:5432/%s" .Values.postgresql.auth.username .Values.postgresql.auth.password .Release.Name .Values.postgresql.auth.database -}}
{{- else if .Values.externalDatabase.enabled -}}
{{- printf "postgresql://%s:%s@%s:%d/%s" .Values.externalDatabase.user .Values.externalDatabase.password .Values.externalDatabase.host (int .Values.externalDatabase.port) .Values.externalDatabase.database -}}
{{- else -}}
{{- "sqlite:///./birthdays.db" -}}
{{- end -}}
{{- end -}}
