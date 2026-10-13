{{- define "common.labels" -}}
app: {{ .Release.Name }}
app.kubernetes.io/name: {{ .Release.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "common.image" -}}
{{- if .Values.image.ref -}}
{{- .Values.image.ref -}}
{{- else -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag -}}
{{- end -}}
{{- end -}}

{{- define "common.environment" -}}
{{- if or .Values.env .Values.secretEnv }}
env:
{{- range $key, $val := .Values.env }}
  - name: {{ $key }}
    value: {{ $val | quote }}
{{- end }}
{{- range $key, $ref := .Values.secretEnv }}
  - name: {{ $key }}
    valueFrom:
      secretKeyRef:
        name: {{ $ref.name }}
        key: {{ $ref.key }}
{{- end }}
{{- end }}
{{- if or .Values.envFrom .Values.externalSecret.enabled }}
envFrom:
{{- range .Values.envFrom }}
  - secretRef:
      name: {{ . }}
{{- end }}
{{- if .Values.externalSecret.enabled }}
  - secretRef:
      name: {{ .Release.Name }}-secret
{{- end }}
{{- end }}
{{- end -}}

{{- define "common.container" -}}
- name: {{ .Release.Name }}
  image: {{ include "common.image" . | quote }}
  imagePullPolicy: IfNotPresent
  {{- if .Values.command }}
  command: {{ .Values.command | toJson }}
  {{- end }}
  {{- if .Values.args }}
  args: {{ .Values.args | toJson }}
  {{- end }}
  {{- if .Values.resources }}
  resources:
    {{- .Values.resources | toYaml | nindent 4 }}
  {{- end }}
  {{- include "common.environment" . | nindent 2 }}
{{- end -}}

{{- define "common.deployment" -}}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-workload
  labels:
    {{- include "common.labels" . | nindent 4 }}
  annotations:
    argocd.argoproj.io/sync-wave: "2"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {{ .Release.Name }}
  template:
    metadata:
      labels:
        {{- include "common.labels" . | nindent 8 }}
    spec:
      containers:
        {{- include "common.container" . | nindent 8 }}
        {{- if .Values.service }}
          ports:
            - containerPort: {{ .Values.service.targetPort }}
          readinessProbe:
            {{- if eq .Values.health.path "tcp" }}
            tcpSocket:
              port: {{ .Values.service.targetPort }}
            {{- else }}
            httpGet:
              path: {{ .Values.health.path | quote }}
              port: {{ .Values.service.targetPort }}
            {{- end }}
            initialDelaySeconds: 5
            timeoutSeconds: 3
        {{- end }}
{{- end -}}

{{- define "common.service" -}}
apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name }}-service
spec:
  selector:
    app: {{ .Release.Name }}
  ports:
    - protocol: TCP
      port: {{ .Values.service.port }}
      targetPort: {{ .Values.service.targetPort }}
{{- end -}}

{{- define "common.ingress" -}}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ .Release.Name }}-ingress
spec:
  ingressClassName: traefik
  rules:
    - host: {{ .Values.ingress.host | quote }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ .Release.Name }}-service
                port:
                  number: {{ .Values.service.port }}
{{- end -}}

{{- define "common.externalsecret" -}}
{{- if .Values.externalSecret.enabled }}
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: {{ .Release.Name }}-secrets
  annotations:
    argocd.argoproj.io/sync-wave: "0"
    {{- if .Values.externalSecret.refreshAfter }}
    deployguard.io/refresh-after: {{ .Values.externalSecret.refreshAfter | quote }}
    {{- end }}
spec:
  refreshInterval: 15s
  secretStoreRef:
    name: {{ required "externalSecret.secretStore is required" .Values.externalSecret.secretStore }}
    kind: {{ default "SecretStore" .Values.externalSecret.secretStoreKind }}
  target:
    name: {{ .Release.Name }}-secret
    creationPolicy: Owner
  dataFrom:
    - extract:
        key: {{ required "externalSecret.vaultPath is required" .Values.externalSecret.vaultPath | quote }}
{{- end }}
{{- end -}}

{{- define "common.initjob" -}}
{{- if .Values.initCommand }}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ .Release.Name }}-init
  annotations:
    argocd.argoproj.io/hook: Sync
    argocd.argoproj.io/sync-wave: "1"
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation,HookSucceeded
spec:
  backoffLimit: 0
  activeDeadlineSeconds: {{ .Values.timeout }}
  template:
    metadata:
      labels:
        app: {{ .Release.Name }}-init
    spec:
      restartPolicy: Never
      containers:
        - name: init-task
          image: {{ include "common.image" . | quote }}
          imagePullPolicy: IfNotPresent
          command: ["/bin/sh", "-c"]
          args: [{{ .Values.initCommand | quote }}]
          {{- if .Values.resources }}
          resources:
            {{- .Values.resources | toYaml | nindent 12 }}
          {{- end }}
          {{- include "common.environment" . | nindent 10 }}
{{- end }}
{{- end -}}

{{- define "common.job" -}}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ .Release.Name }}-workload
  labels:
    {{- include "common.labels" . | nindent 4 }}
  annotations:
    argocd.argoproj.io/sync-options: Force=true,Replace=true
spec:
  suspend: {{ .Values.suspended }}
  backoffLimit: 0
  activeDeadlineSeconds: {{ .Values.timeout }}
  template:
    metadata:
      labels:
        {{- include "common.labels" . | nindent 8 }}
      annotations:
        deployguard.io/run-id: {{ .Values.runId | quote }}
    spec:
      restartPolicy: Never
      containers:
        {{- include "common.container" . | nindent 8 }}
{{- end -}}
