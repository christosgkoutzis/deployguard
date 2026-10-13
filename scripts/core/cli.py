"""Explicit commands: importing this module never builds or changes a cluster."""
import argparse
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import shutil
import sys
import subprocess
import time
import traceback
import urllib.error
import urllib.request
import uuid

from .configuration import ConfigError, Settings, tool_versions
from .builds import Builds
from .kubernetes import Kubernetes, require, run
from .gitops import OWNER, Snapshot
from .topology import Topology
from .assessment import assess, check_code


def load_inventory(settings):
    path = settings.state/'inventory.json'
    if not path.is_file():
        raise ConfigError('No generated inventory; sync this environment first')
    inventory = json.loads(path.read_text())
    if inventory['context'] != settings.context or inventory['namespace'] != settings.namespace:
        raise ConfigError('Inventory does not match the configured cluster/namespace')
    return inventory


def doctor(settings):
    require('docker','git','kubectl','helm','k3d','skaffold')
    print(f'INFO: Tools present. Explicit target: {settings.context}/{settings.namespace}')
    print('INFO: Toolchain baseline: ' + json.dumps(tool_versions(settings.root),sort_keys=True))


def setup(settings):
    doctor(settings)
    clusters = json.loads(run(['k3d','cluster','list','-o','json'],capture=True))
    if not any(c['name'] == settings.cluster for c in clusters):
        run(['k3d','cluster','create',settings.cluster,'--image',tool_versions(settings.root)['k3s'],
             '--servers','1','--agents','2','-p',f'127.0.0.1:{settings.ingress_port}:80@loadbalancer',
             '--api-port',f'127.0.0.1:{settings.api_port}','--kubeconfig-switch-context=false','--wait'])
    else:
        print('INFO: Existing cluster retained; no reset or recreation performed')


def bootstrap(topology):
    settings = topology.settings
    doctor(settings)
    kube = Kubernetes(settings)
    kube.command('get','namespace','kube-system',capture=True)
    kube.apply([{'apiVersion':'v1','kind':'Namespace','metadata':{'name':name}}
                for name in [settings.namespace,settings.argo_namespace,'external-secrets']])
    versions = tool_versions(settings.root)
    run(['helm','upgrade','--install','argocd','argo-cd','--repo','https://argoproj.github.io/argo-helm',
         '--version',versions['argocd_chart'],'--kube-context',settings.context,
         '--namespace',settings.argo_namespace,'--values',settings.root/'platform/config/argocd-values.yaml',
         '--set-string',f'server.ingress.hostname=argocd.{settings.domain}',
         '--wait','--timeout',f'{settings.timeout}s'])
    if topology.data.get('secret_stores'):
        run(['helm','upgrade','--install','external-secrets','external-secrets',
             '--repo','https://charts.external-secrets.io','--version',versions['eso_chart'],
             '--kube-context',settings.context,'--namespace','external-secrets',
             '--set','installCRDs=true','--wait','--timeout',f'{settings.timeout}s'])
    project = {'apiVersion':'argoproj.io/v1alpha1','kind':'AppProject',
               'metadata':{'name':topology.name,'namespace':settings.argo_namespace,
                           'labels':{OWNER:topology.name}},
               'spec':{'sourceRepos':['*'],'destinations':[
                   {'server':'https://kubernetes.default.svc','namespace':settings.namespace},
                   {'server':'https://kubernetes.default.svc','namespace':settings.argo_namespace}],
                   'clusterResourceWhitelist':[{'group':'*','kind':'*'}]}}
    kube.apply([project])
    print('INFO: Platform bootstrapped for the explicit local k3d context')


def source_server(settings, environment):
    name = f'deployguard-source-{settings.cluster}'
    # Docker's JSON format emits one object per line, not a JSON array.
    listing = run(['docker','container','ls','--all','--format','{{json .}}'],capture=True)
    exists = any(json.loads(line)['Names'] == name for line in listing.splitlines())
    source = str(settings.state/'repository/.git')
    if exists:
        info = json.loads(run(['docker','inspect',name],capture=True))[0]
        if info.get('Config',{}).get('Labels',{}).get(OWNER) != environment:
            raise ConfigError('Source server name is owned by another environment')
        if not any(m['Source'] == source and m['Destination'] == '/usr/share/nginx/html/environment.git'
                   for m in info.get('Mounts',[])):
            raise ConfigError('Source server belongs to another checkout; use a different CLUSTER_NAME')
        if not info['State']['Running']:
            run(['docker','start',name],capture=True)
    else:
        run(['docker','run','--detach','--name',name,'--label',f'{OWNER}={environment}',
             '--network',f'k3d-{settings.cluster}','--publish',f'127.0.0.1:{settings.source_port}:80',
             '--mount',f'type=bind,source={source},target=/usr/share/nginx/html/environment.git,readonly',
             tool_versions(settings.root)['nginx']],capture=True)
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{settings.source_port}/environment.git/info/refs',timeout=3) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError,TimeoutError,ConnectionError):
            time.sleep(1)
    raise ConfigError('Local Git source server did not become ready')


def wait_environment(kube, topology, inventory, selected=None, *, refresh=False):
    selected = inventory['selected'] if selected is None else selected
    refreshed = set()
    for name in selected:
        entry = inventory['applications'][name]
        def ready(n=name,e=entry):
            obj = kube.get('application',n,kube.settings.argo_namespace,optional=True)
            if not obj or obj.get('spec',{}).get('source',{}).get('targetRevision') != e['source']['targetRevision']:
                return False
            if refresh and e['kind'] != 'test' and not kube.refresh_secret_consumers(n,refreshed=refreshed):
                return False
            return kube.application_ready(n,e['source']['targetRevision'],health=e['kind']!='test')
        kube.wait(name,ready)
    # The parent must apply this revision; unrelated child health cannot gate focus or retries.
    kube.wait('parent configuration',lambda:kube.application_ready(
        f'{topology.name}-environment',inventory['revision'],health=False))


def sync(topology, focus=None, prune=False):
    settings = topology.settings
    selected = topology.select(focus)
    doctor(settings)
    snapshot = Snapshot(topology)
    previous_applications = set()
    if snapshot.inventory_path.exists():
        existing = load_inventory(settings)
        if existing['environment'] != topology.name:
            raise ConfigError('Generated state belongs to another environment; use a separate checkout')
        previous_applications = set(existing['applications'])
    settings.state.mkdir(parents=True,exist_ok=True)
    # Secret-bearing or floating dependency parameters are rejected before builds.
    for name in selected:
        category,item = topology.entities[name]
        if category == 'dependencies':
            snapshot.no_secrets({'set':item.get('set',[]),'values':snapshot.dependency_values(item)})
            if not item.get('path') and any(c in item['version'] for c in '*<>=~^'):
                raise ConfigError(f'{name}: exact dependency chart version required')
        if category in ['services','seeds']:
            snapshot.no_secrets(topology.environment(item))
    kube = Kubernetes(settings)
    kube.command('get','namespace',settings.namespace,capture=True)
    for name in [f'{topology.name}-environment',*selected]:
        kube.owned_application(name,topology.name)
    for secret in snapshot.bootstrap_secrets():
        raw = kube.command('-n',settings.namespace,'get','secret',secret['metadata']['name'],
                           '--ignore-not-found','-o','json',capture=True)
        if raw and json.loads(raw).get('metadata',{}).get('labels',{}).get(OWNER) != topology.name:
            raise ConfigError('A bootstrap Secret is already owned outside this environment')
    # Record existing consumers before credentials change; no restart on first observation.
    for name in selected:
        kube.refresh_secret_consumers(name)
    kube.apply(snapshot.bootstrap_secrets())
    for name in selected:
        kube.refresh_secret_consumers(name)
    Builds(topology).build(selected)
    print('INFO: Generating deployment snapshot', flush=True)
    root, inventory = snapshot.create(selected,prune=prune)
    print('INFO: Starting local Git source', flush=True)
    source_server(settings,topology.name)
    print('INFO: Applying environment Application', flush=True)
    kube.apply([root])
    kube.command('-n',settings.argo_namespace,'patch','application',f'{topology.name}-environment',
                 '--type','merge','-p',json.dumps({'operation':{'sync':{'prune':True}}}),capture=True)
    wait_environment(kube,topology,inventory,refresh=True)
    if prune:
        for name in previous_applications - set(selected):
            kube.wait(f'{name} pruning',lambda n=name: not kube.command(
                '-n',settings.argo_namespace,'get','application',n,
                '--ignore-not-found','-o','name',capture=True).strip())
    for name in selected:
        item = topology.entities[name][1]
        if topology.entities[name][0] == 'services' and (item.get('init_command') or topology.environment(item).get('INIT_COMMAND')):
            entry = inventory['applications'][name]
            obj = kube.get('application',name,settings.argo_namespace)
            if obj.get('status',{}).get('operationState',{}).get('syncResult',{}).get('revision') != entry['source']['targetRevision']:
                kube.command('-n',settings.argo_namespace,'patch','application',name,'--type','merge',
                    '-p',json.dumps({'operation':{'sync':{'prune':True}}}),capture=True)
                def initialized(n=name,r=entry['source']['targetRevision']):
                    operation=kube.get('application',n,settings.argo_namespace).get('status',{}).get('operationState',{})
                    if operation.get('syncResult',{}).get('revision') != r:
                        return False
                    if operation.get('phase') in ['Failed','Error']:
                        raise ConfigError(f'Initialization failed for {n}')
                    return operation.get('phase')=='Succeeded'
                kube.wait(f'{name} initialization',initialized)
    verify(topology,inventory)
    print('INFO: Environment synced and verified')


def verify(topology, inventory=None, selected=None):
    settings = topology.settings
    inventory = inventory or load_inventory(settings)
    if inventory.get('topology_digest') != topology.signature:
        raise ConfigError('Topology changed since the last sync; sync before verification')
    kube = Kubernetes(settings)
    selected = inventory['selected'] if selected is None else selected
    wait_environment(kube,topology,inventory,selected)
    for name in selected:
        entry = inventory['applications'][name]
        kind = entry['kind']
        if kind == 'seed':
            kube.wait(name,lambda n=entry['job']:kube.job_complete(n))
        if kind not in ['webservice','worker','mocks']:
            continue
        deployment = name + ('-deployment' if kind == 'mocks' else '-workload')
        kube.command('-n',settings.namespace,'rollout','status',f'deployment/{deployment}',
                     '--timeout',f'{settings.timeout}s')
        if kind in ['webservice','mocks']:
            item = topology.entities[name][1]
            path = '/__admin/' if kind == 'mocks' else item.get('health_endpoint','/health')
            url = f'http://{name}.{settings.domain}:{settings.ingress_port}{path}'
            def healthy():
                try:
                    with urllib.request.urlopen(url,timeout=5) as response:
                        return 200 <= response.status < 300
                except (urllib.error.URLError,TimeoutError):
                    return False
            kube.wait(f'{name} ingress health',healthy)
    print('INFO: Selected inventory verification passed; test Jobs are assessed by ./scripts/deployguard test')


def test(topology, name):
    if name not in topology.entities or topology.entities[name][1].get('type') != 'test':
        raise ConfigError('Test command requires a declared test service')
    settings = topology.settings
    inventory = load_inventory(settings)
    if name not in inventory['selected']:
        raise ConfigError('Test was not selected; sync the full environment or focus this test first')
    prerequisites = [entity for entity in topology.select(name) if entity != name]
    verify(topology,inventory,prerequisites)
    kube = Kubernetes(settings)
    job = f'{name}-workload'
    snapshot = Snapshot(topology)
    run_id = uuid.uuid4().hex
    root,inventory = snapshot.run_test(name,run_id)
    kube.apply([root])
    def current_job():
        raw = kube.command('-n',settings.namespace,'get','job',job,
                           '--ignore-not-found','-o','json',capture=True)
        if not raw:
            return False
        obj = json.loads(raw)
        return obj.get('spec',{}).get('template',{}).get('metadata',{}).get('annotations',{}).get('deployguard.io/run-id') == run_id
    kube.wait(f'{job} new execution',current_job)
    follower = subprocess.Popen(['kubectl','--context',settings.context,'-n',settings.namespace,
        'logs',f'job/{job}','--all-containers=true','--follow',
        f'--pod-running-timeout={settings.timeout}s'])
    try:
        kube.wait(job,lambda:kube.job_complete(job))
    finally:
        try:
            follower.wait(timeout=5)
        except subprocess.TimeoutExpired:
            follower.terminate()
            try:
                follower.wait(timeout=5)
            except subprocess.TimeoutExpired:
                follower.kill()
                follower.wait()
        if follower.returncode:
            kube.command('-n',settings.namespace,'logs',f'job/{job}','--all-containers=true','--tail=200')
    print(f'SUCCESS: {name} Job completed')


@contextmanager
def operation_lock(settings):
    settings.state.mkdir(parents=True,exist_ok=True)
    with (settings.state/'operation.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ConfigError('Another DeployGuard operation is already running') from exc
        try:
            yield
        finally:
            fcntl.flock(lock,fcntl.LOCK_UN)


def clear_scenario(settings,skip_dependencies=False):
    # Only known demo assets move to a backup; custom files and cluster state stay in place.
    assets=['services/python-backend','services/python-worker','services/report-worker',
            'services/ruby-gateway','tests/e2e-tests','mocks/external-api-mock','seeds/vault-seeder']
    if not skip_dependencies:
        assets += ['platform/dependencies/confluent-kafka-chart','platform/dependencies/rabbitmq-instance-chart']
    backup=settings.state/'scenario-backups'/uuid.uuid4().hex
    for relative in assets:
        source=settings.root/relative
        if source.exists():
            destination=backup/relative
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.move(str(source),str(destination))
    print(f'INFO: Demo assets moved to {backup}. Custom files and running cluster resources retained.')
    print('INFO: Replace deployguard.yaml before the next sync; it still references the demo.')


def failure_message(error):
    """Describe unexpected failures without printing input or exception values."""
    if isinstance(error, ConfigError):
        return str(error)
    details = [type(error).__name__]
    if isinstance(error, OSError) and error.errno is not None:
        details.append(f'errno={error.errno}')
    if isinstance(error, json.JSONDecodeError):
        details.append(f'JSON line {error.lineno}, column {error.colno}')
    directory = Path(__file__).parent
    locations = [f'{Path(frame.f_code.co_filename).name}:{line} ({frame.f_code.co_name})'
                 for frame, line in traceback.walk_tb(error.__traceback__)
                 if Path(frame.f_code.co_filename).parent == directory]
    if locations:
        details.append(' -> '.join(locations))
    return 'Operation failed: ' + '; '.join(details)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='./scripts/deployguard', description='DeployGuard standalone local development tool',
        epilog='Install this checkout with ./scripts/deployguard install [--assessment].')
    parser.add_argument('--topology')
    commands = parser.add_subparsers(dest='command',required=True)
    for command in ['validate','doctor','setup','bootstrap','verify','list-tests']:
        commands.add_parser(command)
    commands.add_parser('check',help='Read-only code and schema checks')
    assess_parser = commands.add_parser('assess',help='GitHub Actions functional assessment only')
    assess_parser.add_argument('assessment',choices=['scenario','generic','diagnostics'])
    assess_parser.add_argument('--mode',choices=['full','focused'],default='full')
    sync_parser = commands.add_parser('sync')
    sync_parser.add_argument('--focus')
    sync_parser.add_argument('--prune',action='store_true',help='Remove unselected owned applications')
    clear_parser = commands.add_parser('clear-scenario')
    clear_parser.add_argument('--skip-dependencies',action='store_true')
    test_parser = commands.add_parser('test')
    test_parser.add_argument('name')
    for subparser in commands.choices.values():
        subparser.add_argument('--topology', default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.command == 'check':
            check_code()
            return 0
        if args.command == 'assess':
            assess(args.assessment,args.mode)
            return 0
        settings = Settings.load(args.topology)
        if args.command == 'doctor':
            doctor(settings)
        elif args.command == 'setup':
            with operation_lock(settings):
                setup(settings)
        elif args.command == 'clear-scenario':
            with operation_lock(settings):
                clear_scenario(settings,args.skip_dependencies)
        else:
            topology = Topology(settings)
            if args.command == 'validate':
                print('INFO: Topology valid: ' + ', '.join(topology.order))
            elif args.command == 'list-tests':
                for name,(_,item) in topology.entities.items():
                    if item.get('type') == 'test':
                        print(name)
            elif args.command == 'bootstrap':
                with operation_lock(settings):
                    bootstrap(topology)
            elif args.command == 'sync':
                with operation_lock(settings):
                    sync(topology,args.focus,args.prune)
            elif args.command == 'verify':
                verify(topology)
            elif args.command == 'test':
                with operation_lock(settings):
                    test(topology,args.name)
    except (ConfigError,OSError,ValueError) as exc:
        print(f'ERROR: {failure_message(exc)}', file=sys.stderr)
        return 1
    return 0
