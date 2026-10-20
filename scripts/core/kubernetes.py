"""Native Kubernetes operations and bounded deployment readiness checks."""
import hashlib
import json
import shutil
import subprocess
import time
import uuid

from .configuration import ConfigError

SECRET_REVISION = 'deployguard.io/secret-revision'


def run(args, *, cwd=None, capture=False, input=None, timeout=600):
    try:
        result = subprocess.run([str(arg) for arg in args], cwd=cwd, input=input,
                                text=True, capture_output=capture, check=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError) as exc:
        raise ConfigError(f'{args[0]} failed; inspect its diagnostics or cluster events') from exc
    return result.stdout if capture else None


def require(*commands):
    missing = [command for command in commands if not shutil.which(command)]
    if missing:
        raise ConfigError('Missing tools: ' + ', '.join(missing) + '; see docs/get-started.md')


def secret_references(pod):
    """Return referenced Secret names and whether each is required."""
    references = {}
    def add(ref, key='name'):
        if ref and ref.get(key):
            name = ref[key]
            references[name] = references.get(name, False) or not ref.get('optional', False)
    for container in [*pod.get('containers', []), *pod.get('initContainers', [])]:
        for entry in container.get('env', []):
            add(entry.get('valueFrom', {}).get('secretKeyRef'))
        for entry in container.get('envFrom', []):
            add(entry.get('secretRef'))
    for volume in pod.get('volumes', []):
        add(volume.get('secret'), 'secretName')
        for source in volume.get('projected', {}).get('sources', []):
            add(source.get('secret'))
    return references


class Kubernetes:
    def __init__(self, settings):
        self.settings = settings

    def command(self, *args, **kwargs):
        return run(['kubectl', '--context', self.settings.context, *args], **kwargs)

    def get(self, kind, name, namespace=None, *, optional=False):
        arguments = ['-n', namespace or self.settings.namespace, 'get', kind, name, '-o', 'json']
        if optional:
            arguments.append('--ignore-not-found')
        raw = self.command(*arguments, capture=True)
        return json.loads(raw) if raw else None

    def apply(self, objects):
        if objects:
            self.command('apply', '-f', '-', input=json.dumps({'apiVersion':'v1', 'kind':'List',
                                                             'items':objects}), capture=True)

    def wait(self, label, predicate, timeout=None):
        deadline = time.monotonic() + (timeout or self.settings.timeout)
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(2)
        raise ConfigError(f'Timeout waiting for {label}')

    def owned_application(self, name, environment):
        obj = self.get('application', name, self.settings.argo_namespace, optional=True)
        if obj and obj.get('metadata', {}).get('labels', {}).get('deployguard.io/environment') != environment:
            raise ConfigError(f'Application {name} belongs to another environment')

    def application_ready(self, name, revision, *, health=True):
        obj = self.get('application', name, self.settings.argo_namespace, optional=True)
        if not obj:
            return False
        status = obj.get('status', {})
        operation = status.get('operationState', {})
        if health and operation.get('phase') in ['Failed', 'Error'] and operation.get('syncResult', {}).get('revision') == revision:
            raise ConfigError(f'ArgoCD sync failed for {name}')
        desired = obj.get('spec', {}).get('source', {}).get('targetRevision')
        synced = status.get('sync', {})
        return (desired == revision and synced.get('revision') == revision and
                synced.get('status') == 'Synced' and
                (not health or status.get('health', {}).get('status') == 'Healthy'))

    def application_diagnostics(self, name, revision=None, *, credentials=()):
        """Report reconciliation state without dumping manifests or Secret data."""
        obj = self.get('application', name, self.settings.argo_namespace, optional=True)
        if not obj:
            print('INFO: Application diagnostics: '+json.dumps({'name':name,'missing':True}), flush=True)
            return
        credentials = sorted({form for value in credentials if value
                              for form in [value, json.dumps(value)[1:-1]]}, key=len, reverse=True)
        def message(value):
            value = value or ''
            for credential in credentials:
                value = value.replace(credential, '[REDACTED]')
            return value[:2000]
        def resource(value):
            result = {key:value[key] for key in ['group','kind','namespace','name','status',
                                                'hookPhase','syncPhase','requiresPruning'] if key in value}
            if value.get('health'):
                result['health'] = value['health'].get('status')
            if value.get('message'):
                result['message'] = message(value['message'])
            return result
        status = obj.get('status', {})
        operation = status.get('operationState', {})
        sync_result = operation.get('syncResult', {})
        summary = {
            'name':name, 'requestedRevision':revision,
            'desiredRevision':obj.get('spec', {}).get('source', {}).get('targetRevision'),
            'observedRevision':status.get('sync', {}).get('revision'),
            'syncStatus':status.get('sync', {}).get('status'),
            'health':status.get('health', {}).get('status'),
            'pendingOperation':bool(obj.get('operation')),
            'conditions':[{'type':condition.get('type'), 'message':message(condition.get('message', ''))}
                          for condition in status.get('conditions', [])],
            'operation':{**{key:operation[key] for key in ['phase','startedAt','finishedAt'] if key in operation},
                         'message':message(operation.get('message', '')),
                         'revision':sync_result.get('revision'),
                         'resources':[resource(value) for value in sync_result.get('resources', [])]},
            'resources':[resource(value) for value in status.get('resources', [])],
        }
        print('INFO: Application diagnostics: '+json.dumps(summary, sort_keys=True), flush=True)

    def refresh_secret_consumers(self, application, *, refreshed=None):
        """Adopt Secret versions during sync, without storing credential values."""
        obj = self.get('application', application, self.settings.argo_namespace, optional=True)
        if not obj:
            return False
        resources = obj.get('status', {}).get('resources', [])
        for resource in resources:
            namespace = resource.get('namespace') or self.settings.namespace
            name, kind = resource['name'], resource['kind']
            if refreshed is not None and kind == 'ExternalSecret':
                identity = (namespace, name)
                external = self.get('externalsecrets.external-secrets.io', name, namespace, optional=True)
                if not external:
                    return False
                if identity not in refreshed:
                    previous_sync = external.get('status', {}).get('syncedResourceVersion')
                    self.command('-n', namespace, 'annotate', 'externalsecrets.external-secrets.io', name,
                                 'force-sync='+uuid.uuid4().hex, '--overwrite', capture=True)
                    def fresh():
                        current = self.get('externalsecrets.external-secrets.io', name, namespace)
                        status = current.get('status', {})
                        observed = status.get('syncedResourceVersion')
                        return (bool(observed) and observed != previous_sync
                                and any(c.get('type') == 'Ready' and c.get('status') == 'True'
                                        for c in status.get('conditions', [])))
                    self.wait(f'{name} Secret refresh', fresh)
                    refreshed.add(identity)
        for resource in resources:
            if resource['kind'] not in ['Deployment', 'StatefulSet']:
                continue
            namespace = resource.get('namespace') or self.settings.namespace
            name, kind = resource['name'], resource['kind']
            workload = self.get(kind, name, namespace, optional=True)
            if not workload:
                return False
            versions = {}
            for secret, required in secret_references(workload['spec']['template']['spec']).items():
                value = self.get('secret', secret, namespace, optional=True)
                if not value and required:
                    return False
                if value:
                    metadata = value['metadata']
                    versions[secret] = [metadata['uid'], metadata['resourceVersion']]
            if not versions:
                continue
            revision = hashlib.sha256(json.dumps(versions, sort_keys=True).encode()).hexdigest()
            previous = workload['metadata'].get('annotations', {}).get(SECRET_REVISION)
            if previous == revision:
                continue
            patch = {'metadata': {'annotations': {SECRET_REVISION: revision}}}
            if previous is not None:
                patch['spec'] = {'template': {'metadata': {'annotations': {SECRET_REVISION: revision}}}}
            # First observation records a baseline without restarting fresh workloads.
            self.command('-n', namespace, 'patch', kind, name, '--type', 'merge',
                         '-p', json.dumps(patch), capture=True)
            if previous is not None:
                self.command('-n', namespace, 'rollout', 'status', f'{kind.lower()}/{name}',
                             '--timeout', f'{self.settings.timeout}s')
        return True

    def job_complete(self, name, *, uid=None):
        obj = self.get('job', name, optional=True)
        if uid is not None and (not obj or obj['metadata']['uid'] != uid):
            raise ConfigError(f'Job {name} execution was removed or replaced')
        if not obj:
            return False
        conditions = obj.get('status', {}).get('conditions', [])
        if any(c['type'] in ['Failed','FailureTarget'] and c['status'] == 'True' for c in conditions):
            raise ConfigError(f'Job {name} failed')
        return any(c['type'] == 'Complete' and c['status'] == 'True' for c in conditions)
