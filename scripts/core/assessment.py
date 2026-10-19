"""Static code checks and runner-only functional acceptance assessments."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import urllib.request

from jsonschema import Draft202012Validator
import yaml

from .configuration import ConfigError, ROOT, Settings
from .kubernetes import Kubernetes
from .gitops import OWNER
from .topology import Topology

EXCLUDED = {'.git', '.local', '.venv', '.tools', '.deployguard', '__pycache__'}

def files():
    for path in ROOT.rglob('*'):
        if path.is_file() and not any(part in EXCLUDED for part in path.relative_to(ROOT).parts):
            yield path


def check_code():
    count=0
    for path in files():
        suffix=path.suffix
        if suffix=='.py':
            ast.parse(path.read_text(),filename=str(path))
        elif suffix=='.sh' or path == ROOT/'scripts/deployguard':
            subprocess.run(['bash','-n',str(path)],check=True)
        elif suffix=='.json':
            json.loads(path.read_text())
        elif suffix=='.toml':
            tomllib.loads(path.read_text())
        elif suffix in ['.yaml','.yml'] and 'templates' not in path.parts:
            list(yaml.safe_load_all(path.read_text()))
        else:
            continue
        count+=1
    Draft202012Validator.check_schema(json.loads((ROOT/'platform/config/topology.schema.json').read_text()))
    print(f'SUCCESS: {count} files passed read-only syntax/schema checks')

def cli(*args,expected=0,timeout=None,environment=None):
    environment={**os.environ,**(environment or {})}
    if timeout:
        environment['TIMEOUT_SECONDS']=str(timeout)
    result=subprocess.run([str(ROOT/'scripts/deployguard'),*args],cwd=ROOT,env=environment)
    if expected==0:
        assert result.returncode==0, 'Expected command success'
    else:
        assert result.returncode!=0, 'A negative assessment unexpectedly passed'

def inventory():
    return json.loads((ROOT/'.local/state/inventory.json').read_text())

def image(kube,name):
    return kube.get('deployment',name+'-workload')['spec']['template']['spec']['containers'][0]['image']

def scenario(mode):
    settings=Settings.load()
    topology=Topology(settings)
    selected=topology.select('e2e-tests' if mode=='focused' else None)
    state=inventory()
    assert state['selected']==selected
    build=json.loads((ROOT/'.local/state/artifacts.json').read_text())
    expected={name for name in selected if topology.entities[name][0]=='services' or
              topology.entities[name][0]=='seeds' and topology.entities[name][1].get('build_path')}
    assert {b['imageName'] for b in build['builds']}==expected
    kube=Kubernetes(settings)
    apps=json.loads(kube.command('-n',settings.argo_namespace,'get','applications','-l',
                               OWNER+'='+topology.name,'-o','json',capture=True))['items']
    assert {a['metadata']['name'] for a in apps}==set(selected)|{topology.name+'-environment'}
    if mode=='focused':
        assert 'dozzle' not in selected and 'kafbat-ui' not in selected
    for key in ['VAULT_ROOT_TOKEN','POSTGRES_PASSWORD','S3_SECRET_ACCESS_KEY','RABBITMQ_PASSWORD',
                'REDIS_PASSWORD','ELASTIC_PASSWORD']:
        value=settings.environment[key]
        # Scan every committed generated revision, not just the latest tree.
        revisions=subprocess.run(['git','rev-list','--all'],cwd=ROOT/'.local/state/repository',
                                 check=True,capture_output=True,text=True).stdout.splitlines()
        for revision in revisions:
            tree=subprocess.run(['git','grep','-F','-e',value,revision],cwd=ROOT/'.local/state/repository',
                                capture_output=True,text=True)
            assert tree.returncode==1, 'Generated Git history contains a credential or scan failed'
    print('SUCCESS: Scenario build, selection and secret-free snapshot contracts passed')

def generic():
    with tempfile.TemporaryDirectory(prefix='assessment-', dir=ROOT/'.local/tmp') as directory:
        base=Path(directory)/'fixture'
        shutil.copytree(ROOT/'tests/platform-fixture', base)
        _generic(base)

def _generic(base):
    def command(*args, environment=None, **kwargs):
        cli(*args, environment={'TOPOLOGY_FILE':str(base/'topology.yaml'),
                               **(environment or {})}, **kwargs)

    settings=Settings.load(base/'topology.yaml')
    kube=Kubernetes(settings)
    for kind,name in [('service','fixture-worker-service'),('ingress','fixture-worker-ingress')]:
        assert not kube.command('-n',settings.namespace,'get',kind,name,'--ignore-not-found',
                                '-o','name',capture=True).strip()
    old_image=image(kube,'fixture-api')
    seed=inventory()['applications']['prepare']['job']
    old_seed_uid=kube.get('job',seed)['metadata']['uid']
    command('sync')
    assert image(kube,'fixture-api')==old_image
    assert kube.get('job',seed)['metadata']['uid']==old_seed_uid, 'Unchanged platform seed reran'
    registered = kube.get('job','fixture-tests-workload')
    assert registered['spec']['suspend'] is True, 'Sync unexpectedly started tests'
    command('test','fixture-tests')
    first_uid = kube.get('job','fixture-tests-workload')['metadata']['uid']
    command('test','fixture-tests')
    assert kube.get('job','fixture-tests-workload')['metadata']['uid'] != first_uid, 'Test execution reused an old Job'
    # A test run must leave other deployments and completed suites untouched.
    command('test','fixture-other-tests')
    other_uid=kube.get('job','fixture-other-tests-workload')['metadata']['uid']
    before=inventory()
    command('test','fixture-tests')
    assert kube.get('job','fixture-other-tests-workload')['metadata']['uid']==other_uid
    after=inventory()
    for name,entry in before['applications'].items():
        if name!='fixture-tests':
            assert after['applications'][name]['source']==entry['source'], 'Test changed another source revision'
    # Change a Secret input and require a consumer rollout and adoption of its value.
    changed_password='changed-ci-fixture-credential'
    before=kube.get('deployment','fixture-api-workload')['spec']['template']
    command('sync',environment={'FIXTURE_PASSWORD':changed_password})
    assert kube.get('deployment','fixture-api-workload')['spec']['template']!=before
    with urllib.request.urlopen(f'http://fixture-api.{settings.domain}:{settings.ingress_port}/data',timeout=10) as response:
        assert json.load(response)['secret_digest']==hashlib.sha256(changed_password.encode()).hexdigest()
    command('sync')
    # Editing mappings must update live WireMock behavior, not only the ConfigMap.
    mapping=base/'mocks/fixture-mock/mapping.json'
    original_mapping=mapping.read_text()
    try:
        changed=json.loads(original_mapping)
        changed['response']['jsonBody']['revision']='changed-mapping'
        mapping.write_text(json.dumps(changed))
        command('sync')
        with urllib.request.urlopen(f'http://fixture-mock.{settings.domain}:{settings.ingress_port}/fixture',timeout=10) as response:
            assert json.load(response)['revision']=='changed-mapping'
    finally:
        mapping.write_text(original_mapping)
    command('sync')
    # Make an unrelated retained app unhealthy through an ArgoCD-owned source.
    data=yaml.safe_load((base/'topology.yaml').read_text())
    data['services'][1]['command']=['/bin/sh','-c','exit 29']
    failure=base/'unrelated-failure.yaml'
    failure.write_text(yaml.safe_dump(data))
    try:
        command('sync','--topology',str(failure),'--focus','fixture-worker',expected=1,timeout=90)
        kube.wait('unrelated worker unhealthy',lambda:kube.get('application','fixture-worker',settings.argo_namespace)
                  .get('status',{}).get('health',{}).get('status')!='Healthy')
        command('sync','--focus','fixture-api')
        command('verify')
        assert kube.get('application','fixture-worker',settings.argo_namespace)
    finally:
        failure.unlink()
    command('sync')
    seed_source = base/'seeds/prepare.py'
    original_seed = seed_source.read_text()
    try:
        seed_source.write_text(original_seed+'\n# Changed seed input assessed by CI\n')
        command('sync','--focus','fixture-api')
        changed_seed = inventory()['applications']['prepare']['job']
        assert changed_seed != seed, 'Changed platform seed inputs were ignored'
        assert kube.get('job',changed_seed)['metadata']['uid'] != old_seed_uid
    finally:
        seed_source.write_text(original_seed)
    command('sync')
    source=base/'code/http-app/app.py'
    original=source.read_text()
    try:
        source.write_text(original.replace('fixture-v1','fixture-v2'))
        command('sync','--focus','fixture-api')
        assert image(kube,'fixture-api')!=old_image, 'A source edit did not update the running image'
        with urllib.request.urlopen(f'http://fixture-api.{settings.domain}:{settings.ingress_port}/data',timeout=10) as response:
            assert json.load(response)['version']=='fixture-v2'
        assert kube.get('application','fixture-worker',settings.argo_namespace)
        command('sync','--focus','fixture-api','--prune')
        assert not kube.command('-n',settings.argo_namespace,'get','application','fixture-worker',
                                '--ignore-not-found','-o','name',capture=True).strip()
    finally:
        source.write_text(original)
    command('sync')
    command('test','fixture-tests')
    retry_topology=base/'retry-topology.yaml'
    data=yaml.safe_load((base/'topology.yaml').read_text())
    data['services'][2]['env']=['FAIL_ONCE=1']
    retry_topology.write_text(yaml.safe_dump(data))
    try:
        command('sync','--topology',str(retry_topology))
        command('test','fixture-tests','--topology',str(retry_topology),expected=1)
        failed_uid=kube.get('job','fixture-tests-workload')['metadata']['uid']
        command('verify','--topology',str(retry_topology))
        command('test','fixture-tests','--topology',str(retry_topology))
        assert kube.get('job','fixture-tests-workload')['metadata']['uid']!=failed_uid
    finally:
        retry_topology.unlink()
    command('sync')
    command('sync','--focus','unknown',expected=1)
    data=yaml.safe_load((base/'topology.yaml').read_text())
    failure=base/'failure.yaml'
    data['services'][0]['init_command']='exit 37'
    failure.write_text(yaml.safe_dump(data))
    command('sync','--topology',str(failure),'--focus','fixture-api',expected=1,timeout=90)
    init_pods = json.loads(kube.command('-n',settings.namespace,'get','pods','-l',
        'app=fixture-api-init','-o','json',capture=True))['items']
    assert any(state.get('state',{}).get('terminated',{}).get('exitCode') == 37
        for pod in init_pods for state in pod.get('status',{}).get('containerStatuses',[])), 'Expected initialization failure was not observed'
    command('sync')
    data=yaml.safe_load((base/'topology.yaml').read_text())
    data['dependencies']=[{'name':'missing-chart','repo':'https://example.invalid',
                          'chart':'missing','version':'1.0.0'}]
    data['services'][0]['depends_on'].append('missing-chart')
    failure.write_text(yaml.safe_dump(data))
    command('sync','--topology',str(failure),'--focus','fixture-api',expected=1,timeout=45)
    missing = kube.get('application','missing-chart',settings.argo_namespace)
    assert any(c.get('type') in ['ComparisonError','InvalidSpecError']
        for c in missing.get('status',{}).get('conditions',[])), 'Missing chart did not cause the expected ArgoCD error'
    command('sync','--prune')
    checks=base/'code/checks/checks.py'
    original_checks=checks.read_text()
    try:
        checks.write_text('raise RuntimeError("deliberate CI test failure")\n')
        command('sync')
        command('test','fixture-tests',expected=1)
        failed = kube.get('job','fixture-tests-workload')
        assert any(c['type'] in ['Failed','FailureTarget'] and c['status']=='True'
            for c in failed.get('status',{}).get('conditions',[])), 'Expected test failure was not observed'
    finally:
        checks.write_text(original_checks)
    command('sync')
    command('test','fixture-tests')
    failure.unlink()
    print('SUCCESS: Generic paths, config, image updates, focus lifecycle and negative cases passed')

def diagnostics():
    settings=Settings.load()
    kube=Kubernetes(settings)
    topology=None
    credentials=[]
    try:
        topology=Topology(settings)
        credentials=[settings.environment[variable] for secret in topology.data.get('secrets', [])
                     for variable in secret['values'].values()]
    except ConfigError:
        print('WARNING: Topology is invalid; Application messages will be omitted')
    try:
        kube.command('get','nodes','-o','wide')
    except ConfigError:
        pass
    for namespace in [settings.namespace,settings.argo_namespace,'external-secrets']:
        try:
            kube.command('-n',namespace,'get','pods')
            pods=json.loads(kube.command('-n',namespace,'get','pods','-o','json',capture=True))['items']
            for pod in pods:
                status=pod.get('status',{})
                if status.get('phase')=='Succeeded':
                    continue
                ready=any(c.get('type')=='Ready' and c.get('status')=='True'
                          for c in status.get('conditions',[]))
                if not ready:
                    name=pod['metadata']['name']
                    kube.command('-n',namespace,'describe','pod',name)
                    try:
                        kube.command('-n',namespace,'logs',name,'--all-containers=true','--tail=100')
                    except Exception:
                        pass
            kube.command('-n',namespace,'get','events','--field-selector','type=Warning',
                         '--sort-by=.lastTimestamp')
        except Exception:
            pass
    kube.command('-n',settings.argo_namespace,'get','applications')
    if topology is not None:
        apps=json.loads(kube.command('-n',settings.argo_namespace,'get','applications','-o','json',capture=True))['items']
        for app in apps:
            status=app.get('status', {})
            if status.get('sync', {}).get('status') != 'Synced' or status.get('health', {}).get('status') != 'Healthy':
                kube.application_diagnostics(app['metadata']['name'], credentials=credentials)


def assess(target, mode='full'):
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ConfigError('The assess command runs only in GitHub Actions; use verify and test for local checks')
    if target == 'scenario':
        scenario(mode)
    elif target == 'generic':
        generic()
    else:
        diagnostics()
