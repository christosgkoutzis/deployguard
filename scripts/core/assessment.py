"""Static validation and CI assessments of deployment behavior."""
import ast
import base64
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

def cli(*args,expected=0,timeout=None,environment=None,observe=None):
    environment={**os.environ,**(environment or {})}
    if timeout:
        environment['TIMEOUT_SECONDS']=str(timeout)
    arguments=[str(ROOT/'scripts/deployguard'),*args]
    if observe is None:
        result=subprocess.run(arguments,cwd=ROOT,env=environment)
    else:
        with tempfile.TemporaryFile(mode='w+',dir=ROOT/'.local/tmp') as output:
            process=subprocess.Popen(arguments,cwd=ROOT,env=environment,stdout=output,stderr=subprocess.STDOUT)
            try:
                while process.poll() is None:
                    observe()
                    try:
                        process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        pass
                observe()
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                output.seek(0)
                result=subprocess.CompletedProcess(arguments,process.returncode,stdout=output.read())
                print(result.stdout,end='',flush=True)
    if expected==0:
        assert result.returncode==0, 'Expected command success'
    else:
        assert result.returncode!=0, 'A negative assessment unexpectedly passed'
    return result

def inventory():
    return json.loads((ROOT/'.local/state/inventory.json').read_text())

def image(kube,name):
    return kube.get('deployment',name+'-workload')['spec']['template']['spec']['containers'][0]['image']


def refresh_scenario_secret(kube):
    namespace=kube.settings.namespace
    original=base64.b64decode(kube.get('secret','python-backend-secret')['data']['SEEDED_BY']).decode()
    marker='ci-secret-refresh-'+os.urandom(12).hex()
    before=kube.get('deployment','python-backend-workload')['spec']['template']
    def update(value):
        kube.command('-n',namespace,'exec','vault-0','--','/bin/sh','-ec',
                     'export VAULT_ADDR=http://127.0.0.1:8200; '
                     'export VAULT_TOKEN="$(cat /vault/userconfig/bootstrap/token)"; '
                     'vault kv patch -mount=secret deployguard/python-backend "SEEDED_BY=$1" >/dev/null',
                     'vault-secret-update',value,capture=True)
    def observed():
        return kube.command('-n',namespace,'exec','deployment/python-backend-workload','--',
                            'python','-c','import os; print(os.environ["SEEDED_BY"])',capture=True).strip()
    try:
        update(marker)
        cli('sync','--focus','python-backend')
        value=base64.b64decode(kube.get('secret','python-backend-secret')['data']['SEEDED_BY']).decode()
        assert value==marker, 'Vault change did not reach the ESO-managed Secret'
        assert kube.get('deployment','python-backend-workload')['spec']['template']!=before, 'Vault change did not roll the consumer'
        assert observed()==marker, 'The running consumer retained the previous Vault value'
    finally:
        update(original)
        cli('sync','--focus','e2e-tests')
        assert observed()==original, 'The restored Vault value did not reach the running consumer'
    print('SUCCESS: Vault changes reached ESO and the running consumer; original value restored')


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
        refresh_scenario_secret(kube)
    for key in ['VAULT_ROOT_TOKEN','POSTGRES_PASSWORD','S3_SECRET_ACCESS_KEY','RABBITMQ_PASSWORD',
                'REDIS_PASSWORD','ELASTIC_PASSWORD']:
        value=settings.environment[key]
        # Credential checks cover the generated repository's full commit history.
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
        return cli(*args, environment={'TOPOLOGY_FILE':str(base/'topology.yaml'),
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
    # Each test execution preserves other Applications and completed Jobs.
    command('test','fixture-other-tests')
    other_uid=kube.get('job','fixture-other-tests-workload')['metadata']['uid']
    before=inventory()
    command('test','fixture-tests')
    assert kube.get('job','fixture-other-tests-workload')['metadata']['uid']==other_uid
    after=inventory()
    for name,entry in before['applications'].items():
        if name!='fixture-tests':
            assert after['applications'][name]['source']==entry['source'], 'Test changed another source revision'
    # Secret updates reach running containers through a rollout.
    changed_password='changed-ci-fixture-credential'
    before=kube.get('deployment','fixture-api-workload')['spec']['template']
    command('sync',environment={'FIXTURE_PASSWORD':changed_password})
    assert kube.get('deployment','fixture-api-workload')['spec']['template']!=before
    with urllib.request.urlopen(f'http://fixture-api.{settings.domain}:{settings.ingress_port}/data',timeout=10) as response:
        assert json.load(response)['secret_digest']==hashlib.sha256(changed_password.encode()).hexdigest()
    command('sync')
    # Mapping changes take effect in the running mock server.
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
    # Focus succeeds while a retained, unselected worker remains unhealthy.
    data=yaml.safe_load((base/'topology.yaml').read_text())
    data['services'][1]['command']=['/bin/sh','-c','exit 29']
    failure=base/'unrelated-failure.yaml'
    failure.write_text(yaml.safe_dump(data))
    try:
        command('sync','--topology',str(failure),'--focus','fixture-worker',expected=1,timeout=90)
        kube.wait('unrelated worker unhealthy',lambda:kube.get('application','fixture-worker',settings.argo_namespace)
                  .get('status',{}).get('health',{}).get('status')!='Healthy')
        retained_source=inventory()['applications']['fixture-worker']['source']
        retained_template=kube.get('deployment','fixture-worker-workload')['spec']['template']
        command('sync','--focus','fixture-api')
        command('verify')
        worker=kube.get('application','fixture-worker',settings.argo_namespace)
        assert inventory()['applications']['fixture-worker']['source']==retained_source, 'Focus changed the retained worker inventory'
        assert worker, 'Focus removed the retained worker Application'
        worker_source=worker['spec']['source']
        # ArgoCD's API omits empty Helm parameter lists.
        worker_source.setdefault('helm',{}).setdefault('parameters',[])
        assert worker_source==retained_source, 'Focus changed retained worker source fields: '+', '.join(
            sorted(key for key in worker_source.keys() | retained_source.keys()
                   if worker_source.get(key)!=retained_source.get(key)))
        assert kube.get('deployment','fixture-worker-workload')['spec']['template']==retained_template, 'Focus changed the retained worker workload'
        assert worker.get('status',{}).get('health',{}).get('status') in ['Progressing','Degraded'], 'Retained worker health was masked'
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
        registered=kube.get('job','fixture-tests-workload')
        environment=registered['spec']['template']['spec']['containers'][0].get('env',[])
        assert registered['spec']['suspend'] is True, 'Retry assessment ran before the test command'
        assert any(e['name']=='FAIL_ONCE' and e.get('value')=='1' for e in environment), 'Retry assessment failure input was not deployed'
        command('test','fixture-tests','--topology',str(retry_topology),expected=1)
        failed=kube.get('job','fixture-tests-workload')
        assert any(c['type'] in ['Failed','FailureTarget'] and c['status']=='True'
                   for c in failed.get('status',{}).get('conditions',[])), 'First test execution did not retain its failed Job'
        failed_uid=failed['metadata']['uid']
        command('verify','--topology',str(retry_topology))
        assert kube.get('job','fixture-tests-workload')['metadata']['uid']==failed_uid, 'Verification replaced the failed test execution'
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
    def init_pods():
        return json.loads(kube.command('-n',settings.namespace,'get','pods','-l',
                          'app=fixture-api-init','-o','json',capture=True))['items']
    previous_pods={pod['metadata']['uid'] for pod in init_pods()}
    exit_codes=set()
    def observe_initialization():
        for pod in init_pods():
            if pod['metadata']['uid'] in previous_pods:
                continue
            for container in pod.get('status',{}).get('containerStatuses',[]):
                terminated=container.get('state',{}).get('terminated')
                if terminated:
                    exit_codes.add(terminated['exitCode'])
    result=command('sync','--topology',str(failure),'--focus','fixture-api',expected=1,
                   observe=observe_initialization)
    assert 37 in exit_codes, 'Expected initialization exit code 37 was not observed'
    assert any(message in result.stdout for message in [
        'ERROR: Initialization failed for fixture-api',
        'ERROR: ArgoCD sync failed for fixture-api']), 'Initialization failure was not reported'
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
