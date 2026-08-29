{{- define "common.labels" -}}
app: {{ .Release.Name }}
{{- end -}}

{{- define "common.deployment" -}}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-workload
  labels:
    {{- include "common.labels" . | nindent 4 }}
spec:
  replicas: 1
  selector:
    matchLabels:
      {{- include "common.labels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "common.labels" . | nindent 8 }}
    spec:
      containers:
      - name: {{ .Release.Name }}
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
        imagePullPolicy: IfNotPresent
        {{- if .Values.resources }}
        resources:
{{ toYaml .Values.resources | indent 10 }}
        {{- end }}
        {{- if .Values.service }}
        ports:
        - containerPort: {{ .Values.service.targetPort }}
        readinessProbe:
          {{- if eq (default "http" .Values.health.path) "tcp" }}
          tcpSocket:
            port: {{ .Values.service.targetPort }}
          {{- else }}
          httpGet:
            path: {{ default "/health" .Values.health.path }}
            port: {{ .Values.service.targetPort }}
          {{- end }}
          initialDelaySeconds: 5
        {{- end }}
        {{- if .Values.env }}
        env:
        {{- range $key, $val := .Values.env }}
        - name: {{ $key }}
          value: {{ $val | quote }}
        {{- end }}
        {{- end }}
        {{- if .Values.externalSecret.enabled }}
        envFrom:
        - secretRef:
            name: {{ .Release.Name }}-secret
        {{- end }}
{{- end -}}

{{- define "common.service" -}}
apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name }}-service
spec:
  selector:
    {{- include "common.labels" . | nindent 4 }}
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
    - host: {{ .Values.ingress.host }}
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
{{- if .Values.externalSecret.enabled -}}
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: {{ .Release.Name }}-secrets
spec:
  refreshInterval: {{ default "15s" .Values.externalSecret.refreshInterval }}
  secretStoreRef:
    name: {{ default "vault-backend" .Values.externalSecret.secretStore }}
    kind: {{ default "ClusterSecretStore" .Values.externalSecret.secretStoreKind }}
  target:
    name: {{ .Release.Name }}-secret
    creationPolicy: Owner
  dataFrom:
    - extract:
        key: {{ default (printf "deployguard/%s" .Release.Name) .Values.externalSecret.vaultPath }}
{{- end -}}
{{- end -}}

{{- define "common.initjob" -}}
{{- if .Values.initCommand -}}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ .Release.Name }}-init
  annotations:
    helm.sh/hook: pre-install,pre-upgrade
    helm.sh/hook-weight: "-5"
    helm.sh/hook-delete-policy: hook-succeeded
spec:
  template:
    metadata:
      labels:
        app: {{ .Release.Name }}-init
    spec:
      restartPolicy: Never
      containers:
      - name: init-task
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
        imagePullPolicy: Never
        command: ["/bin/sh", "-c"]
        args: [{{ .Values.initCommand | quote }}]
        volumeMounts:
        - name: seeds-volume
          mountPath: /seeds/
          readOnly: true
        {{- if .Values.env }}
        env:
        {{- range $key, $val := .Values.env }}
        - name: {{ $key }}
          value: {{ $val | quote }}
        {{- end }}
        {{- end }}
        {{- if .Values.externalSecret.enabled }}
        envFrom:
        - secretRef:
            name: {{ .Release.Name }}-secret
            optional: true
        {{- end }}
      volumes:
      - name: seeds-volume
        configMap:
          name: deployguard-platform-seeds
          optional: true
{{- end -}}
{{- end -}}

{{- define "common.job" -}}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ .Release.Name }}-workload
  labels:
    {{- include "common.labels" . | nindent 4 }}
spec:
  backoffLimit: 0
  template:
    metadata:
      labels:
        {{- include "common.labels" . | nindent 8 }}
    spec:
      restartPolicy: Never
      containers:
        - name: {{ .Release.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: IfNotPresent
          {{- if .Values.resources }}
          resources: {{ toYaml .Values.resources | indent 12 }}
          {{- end }}
          {{- if .Values.env }}
          env:
          {{- range $key, $val := .Values.env }}
          - name: {{ $key }}
            value: {{ $val | quote }}
          {{- end }}
          {{- end }}
          {{- if .Values.externalSecret.enabled }}
          envFrom:
          - secretRef:
              name: {{ .Release.Name }}-secret
            {{- end }}
{{- end -}}
