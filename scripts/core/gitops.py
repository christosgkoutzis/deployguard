"""Translate topology to Helm/ArgoCD configuration and immutable local Git snapshots."""
from datetime import datetime, timezone
import hashlib
import time
import json
import shutil

import yaml

from .configuration import ConfigError, write_yaml
from .builds import Builds
from .kubernetes import run
from .topology import assignments, substitute

OWNER = 'deployguard.io/environment'
IGNORE_HEALTH = 'argocd.argoproj.io/ignore-healthcheck'


def copy_chart(source, destination, ancestors=()):
    """Copy a local chart and its vendored dependencies into a deployment snapshot."""
    source = source.resolve()
    if source in ancestors:
        raise ConfigError("Recursive local chart dependency")
    ancestors = (*ancestors, source)
    shutil.copytree(source, destination, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('charts', '*.tgz', '__pycache__',
                                                 '.git', '.env', '.local', '.venv', '.tools', '.deployguard'))
    # Vendored subcharts are copied before resolving file:// overrides.
    if (source / 'charts').exists():
        shutil.copytree(source / 'charts', destination / 'charts', dirs_exist_ok=True)
    chart = yaml.safe_load((source / 'Chart.yaml').read_text())
    for dep in chart.get('dependencies', []):
        repo = dep.get('repository', '')
        if not repo.startswith('file://'):
            if (source/'charts'/dep['name']).is_dir() or list((source/'charts').glob(f'{dep["name"]}-*.tgz')):
                continue
            raise ConfigError('Local charts must vendor remote subcharts before use')
        dep_source = (source / repo[7:]).resolve()
        copy_chart(dep_source, destination / 'charts' / dep['name'], ancestors)


def application(settings, topology, name, source, wave, kind):
    policy = {'syncOptions': ['CreateNamespace=true', 'RespectIgnoreDifferences=true'], 'retry': {'limit': 3,
               'backoff': {'duration':'5s','factor':2,'maxDuration':'1m'}},
              'automated': {'prune': True, 'selfHeal': True}}
    if kind == 'test':
        policy['retry'] = {'limit': 0}
        policy['automated']['selfHeal'] = False
    return {'apiVersion':'argoproj.io/v1alpha1', 'kind':'Application',
            'metadata': {'name':name, 'namespace':settings.argo_namespace,
                         'labels':{OWNER:topology.name, 'deployguard.io/type':kind},
                         'annotations':{'argocd.argoproj.io/sync-wave':str(wave)},
                         'finalizers':['resources-finalizer.argocd.argoproj.io']},
            'spec':{'project':topology.name, 'source':source,
                    'destination':{'server':'https://kubernetes.default.svc','namespace':settings.namespace},
                    'syncPolicy':policy,
                    # Secret refresh and rollout annotations are managed during sync.
                    'ignoreDifferences':[
                        {'group':'apps','kind':kind,'jsonPointers':[
                            '/metadata/annotations/deployguard.io~1secret-revision',
                            '/spec/template/metadata/annotations/deployguard.io~1secret-revision'],
                         'jqPathExpressions':[
                             '.spec.template.metadata.annotations | select(. == {})']}
                        for kind in ['Deployment','StatefulSet']
                    ] + [{'group':'external-secrets.io','kind':'ExternalSecret',
                          'jsonPointers':['/metadata/annotations/force-sync']}]}}


class Snapshot:
    def __init__(self, topology):
        self.topology = topology
        self.settings = topology.settings
        self.repo = self.settings.state / 'repository'
        self.inventory_path = self.settings.state / 'inventory.json'
        self.builds = Builds(topology)
        self.refresh_after = datetime.fromtimestamp(int(time.time()) + 1, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


    def dependency_values(self, item):
        values = {}
        if item.get('values_file'):
            values = substitute(yaml.safe_load((self.topology.base / item['values_file']).read_text()),
                                self.settings.environment)
        values.update(item.get('values', {}))
        return values


    def workload_values(self, item, artifacts, kind):
        name = item['name']
        image = item.get('image') or artifacts.get(name)
        if not image:
            raise ConfigError(f'{name}: missing build artifact')
        environment = self.topology.environment(item)
        environment_init = environment.pop('INIT_COMMAND', '')
        init = item.get('init_command') or environment_init
        external = item.get('external_secret', {})
        values = {'image':{'ref':image}, 'env':environment,
                  'secretEnv':item.get('secret_env', {}), 'envFrom':item.get('env_from', []),
                  'externalSecret':{'enabled':bool(external), 'vaultPath':external.get('path',''),
                                    'secretStore':external.get('store',''), 'secretStoreKind':'SecretStore',
                                    'refreshAfter':self.refresh_after if external else ''},
                  'resources':item.get('resources', {}), 'initCommand':init,
                  'timeout':item.get('timeout', self.settings.timeout),
                  'command':item.get('command', []), 'args':item.get('args', [])}
        if kind == 'webservice':
            values.update({'service':{'port':80,'targetPort':item.get('port',8000)},
                           'ingress':{'host':f'{name}.{self.settings.domain}'},
                           'health':{'path':item.get('health_endpoint','/health')}})
        if kind == 'test':
            values.update({'suspended':True, 'runId':'registered'})
        return values

    def no_secrets(self, value):
        def strings(node):
            if isinstance(node, str):
                yield node
            elif isinstance(node, dict):
                for child in node.values():
                    yield from strings(child)
            elif isinstance(node, list):
                for child in node:
                    yield from strings(child)
        scalars = list(strings(value))
        for secret in self.topology.data.get('secrets', []):
            for variable in secret['values'].values():
                credential = self.settings.environment[variable]
                if credential and any(credential == scalar or (len(credential) >= 8 and credential in scalar)
                                      for scalar in scalars):
                    raise ConfigError(f'Secret source {variable} appears in generated configuration; use a Secret reference')

    def commit(self, message):
        run(['git','add','--all'], cwd=self.repo)
        # Generated snapshots use a dedicated Git identity and disabled commit hooks.
        run(['git','-c','user.name=DeployGuard','-c','user.email=local@deployguard.invalid',
             '-c','core.hooksPath=/dev/null','-c','commit.gpgsign=false','commit','--allow-empty','-m',message],
            cwd=self.repo, capture=True)
        revision = run(['git','rev-parse','HEAD'], cwd=self.repo, capture=True).strip()
        run(['git','update-server-info'], cwd=self.repo)
        return revision

    def create(self, selected, *, prune=False):
        if not (self.repo / '.git').exists():
            self.repo.mkdir(parents=True, exist_ok=True)
            run(['git','init','--initial-branch=main'], cwd=self.repo, capture=True)
        previous = json.loads(self.inventory_path.read_text()) if self.inventory_path.exists() else {}
        if previous and (previous['environment'] != self.topology.name or
                         previous['context'] != self.settings.context or
                         previous['namespace'] != self.settings.namespace):
            raise ConfigError('Generated state belongs to another environment; use a separate checkout')
        artifacts = self.builds.artifacts()
        entries = {} if prune else previous.get('applications', {}).copy()
        for name in selected:
            category, item = self.topology.entities[name]
            print(f'INFO: Generating deployment configuration for {name}', flush=True)
            values_path = self.repo / 'payload/values' / f'{name}.yaml'
            if category == 'secret_stores':
                store = {'apiVersion':'external-secrets.io/v1','kind':'SecretStore',
                    'metadata':{'name':name,'namespace':self.settings.namespace},
                    'spec':{'provider':{'vault':{'server':item['server'],'path':item.get('path','secret'),
                        'version':'v2','auth':{'tokenSecretRef':item['token_secret']}}}}}
                self.no_secrets(store)
                write_yaml(self.repo / 'payload/stores' / name / 'store.yaml', store)
                entries[name] = {'kind':category,'source':{'repoURL':self.settings.source_url,
                    'path':f'payload/stores/{name}'},'wave':self.topology.levels[name]}
                continue
            if category == 'dependencies' and not item.get('path'):
                values = self.dependency_values(item)
                parameters = [{'name':k,'value':v} for k,v in assignments(item.get('set',[]),name).items()]
                self.no_secrets({'values':values,'parameters':parameters})
                source = {'repoURL':item['repo'], 'chart':item['chart'],
                          'targetRevision':item['version'],
                          'helm':{'releaseName':name,'valuesObject':values,'parameters':parameters}}
                entries[name] = {'kind':category,'source':source,'wave':self.topology.levels[name]}
                continue
            if category == 'dependencies':
                chart = self.topology.base / item['path']
                values = self.dependency_values(item)
                # Dotted and indexed parameter keys use native Helm parsing.
                parameters = [{'name':k,'value':v} for k,v in assignments(item.get('set',[]),name).items()]
                kind = category
            elif category == 'mocks':
                chart = self.settings.root / 'platform/charts/wiremock'
                values = {'clusterDomain':self.settings.domain,
                          'mocks':{p.name:p.read_text() for p in sorted((self.topology.base/'mocks'/name).glob('*.json'))}}
                parameters, kind = [], category
            else:
                kind = item.get('type', 'webservice') if category == 'services' else 'seed'
                chart = self.settings.root / 'platform/charts' / ('seed' if kind == 'seed' else kind)
                values = self.workload_values(item, artifacts, kind)
                if kind == 'seed':
                    directory = self.topology.base / item.get('files','seeds')
                    if not directory.is_dir():
                        raise ConfigError(f'{name}: seed files directory not found')
                    values['files'] = {p.name:p.read_text() for p in sorted(directory.iterdir()) if p.is_file()}
                    credential_digest = hashlib.sha256(json.dumps({s['name']:{k:self.settings.environment[v]
                        for k,v in s['values'].items()} for s in self.topology.data.get('secrets',[])},sort_keys=True).encode()).hexdigest()
                    values['revision'] = hashlib.sha256((yaml.safe_dump(values)+credential_digest).encode()).hexdigest()[:12]
                parameters = []
            self.no_secrets(values)
            target = self.repo / 'payload/charts' / name
            if target.exists():
                shutil.rmtree(target)
            copy_chart(chart, target)
            write_yaml(values_path, values)
            entries[name] = {'kind':kind, 'source':{'repoURL':self.settings.source_url,
                'path':f'payload/charts/{name}', 'helm':{'releaseName':name,
                'valueFiles':[f'../../values/{name}.yaml'], 'parameters':parameters}},
                'wave':self.topology.levels[name]}
            if kind == 'seed':
                entries[name]['job'] = f'{name}-{values["revision"]}'
        print('INFO: Recording generated charts and values in Git', flush=True)
        payload_revision = self.commit('Update generated charts and values')
        apps = self.repo / 'applications'
        apps.mkdir(exist_ok=True)
        if prune:
            for file in apps.glob('*.yaml'):
                file.unlink()
        for name in selected:
            entry = entries[name]
            if 'chart' not in entry['source']:
                entry['source']['targetRevision'] = payload_revision
            obj = application(self.settings, self.topology, name, entry['source'], entry['wave'],entry['kind'])
            self.no_secrets(obj)
            write_yaml(apps / f'{name}.yaml', obj)
        for name in set(entries) - set(selected):
            path = apps / f'{name}.yaml'
            retained = yaml.safe_load(path.read_text())
            retained['metadata'].setdefault('annotations', {})[IGNORE_HEALTH] = 'true'
            write_yaml(path, retained)
        print('INFO: Recording environment Applications in Git', flush=True)
        revision = self.commit('Update environment applications')
        inventory = {'environment':self.topology.name,'context':self.settings.context,
                     'namespace':self.settings.namespace,'revision':revision,'selected':selected,
                     'applications':entries,'topology':str(self.settings.topology),'topology_digest':self.topology.signature}
        return self.save_environment(inventory)

    def run_test(self, name, run_id):
        """Record a test execution using its deployed chart, configuration and image."""
        inventory = json.loads(self.inventory_path.read_text())
        entry = inventory['applications'][name]
        path = f'payload/values/{name}.yaml'
        values = yaml.safe_load(run(['git','show',f'{entry["source"]["targetRevision"]}:{path}'],
                                    cwd=self.repo,capture=True))
        values.update({'suspended':False,'runId':run_id})
        write_yaml(self.repo/path,values)
        run(['git','restore','--source',entry['source']['targetRevision'],'--',entry['source']['path']],
            cwd=self.repo,capture=True)
        entry['source']['targetRevision'] = self.commit(f'Run test {name}')
        for application_name in inventory['applications']:
            path = self.repo/'applications'/f'{application_name}.yaml'
            obj = yaml.safe_load(path.read_text())
            annotations = obj['metadata'].setdefault('annotations', {})
            if application_name == name:
                obj['spec']['source'] = entry['source']
                annotations.pop(IGNORE_HEALTH, None)
            else:
                annotations[IGNORE_HEALTH] = 'true'
            write_yaml(path, obj)
        inventory['revision'] = self.commit(f'Execute test {name}')
        return self.save_environment(inventory)

    def save_environment(self, inventory):
        root = application(self.settings,self.topology,f'{self.topology.name}-environment',
                           {'repoURL':self.settings.source_url,'targetRevision':inventory['revision'],
                            'path':'applications'},0,'environment')
        root['spec']['destination']['namespace'] = self.settings.argo_namespace
        write_yaml(self.settings.state/'root-application.yaml',root)
        self.inventory_path.write_text(json.dumps(inventory,indent=2)+'\n')
        return root, inventory

    def bootstrap_secrets(self):
        result = []
        for secret in self.topology.data.get('secrets', []):
            result.append({'apiVersion':'v1','kind':'Secret','type':'Opaque',
                'metadata':{'name':secret['name'],'namespace':self.settings.namespace,
                            'labels':{OWNER:self.topology.name}},
                'stringData':{k:self.settings.environment[v] for k,v in secret['values'].items()}})
        return result
