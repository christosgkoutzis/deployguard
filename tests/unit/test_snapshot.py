import json

import pytest
import yaml

from core.configuration import ConfigError,ROOT,Settings
from core.gitops import IGNORE_HEALTH, Snapshot, application
from core.topology import Topology


def platform(tmp_path,services,extras=None,environment=None):
    path=tmp_path/'deployguard.yaml'
    path.write_text(yaml.safe_dump({'services':services,**(extras or {})}))
    for item in services:
        default=('tests' if item.get('type')=='test' else 'services')+'/'+item['name']
        directory=tmp_path/item.get('build_path',default)
        directory.mkdir(parents=True,exist_ok=True)
        (directory/'Dockerfile').write_text('FROM scratch\n')
    settings=Settings(ROOT,path,tmp_path/'state',environment or {},'test','deployguard','argocd',
                      '127.0.0.1.nip.io',8080,8081,30)
    settings.state.mkdir()
    topology=Topology(settings)
    snapshot=Snapshot(topology)
    snapshot.builds.artifacts_path.write_text(json.dumps({'builds':[{'imageName':s['name'],
        'tag':s['name']+':immutable-test'} for s in services]}))
    return topology,snapshot


def test_builds_only_selected_paths(tmp_path):
    topology,snapshot=platform(tmp_path,[{'name':'api','build_path':'custom/api'}, {'name':'unused'}])
    config=snapshot.builds.build_config(topology.select('api'))
    assert [a['image'] for a in config['build']['artifacts']] == ['api']
    assert config['build']['artifacts'][0]['context'] == str(tmp_path/'custom/api')
    assert config['build']['local']['push'] is False


def test_worker_has_no_http_configuration(tmp_path):
    topology,snapshot=platform(tmp_path,[{'name':'consumer','type':'worker'}])
    values=snapshot.workload_values(topology.entities['consumer'][1],snapshot.builds.artifacts(),'worker')
    assert 'service' not in values and 'health' not in values
    assert values['externalSecret']['enabled'] is False


def test_tests_register_suspended_and_rerun_explicitly(tmp_path):
    topology,snapshot=platform(tmp_path,[{'name':'checks','type':'test'}])
    item=topology.entities['checks'][1]
    assert snapshot.workload_values(item,snapshot.builds.artifacts(),'test')['suspended'] is True
    assert snapshot.workload_values(item,snapshot.builds.artifacts(),'test','run-123')['suspended'] is False


def test_secret_values_cannot_enter_snapshots(tmp_path):
    topology,snapshot=platform(tmp_path,[{'name':'api'}],
        {'secrets':[{'name':'bootstrap','values':{'password':'PASSWORD'}}]},
        {'PASSWORD':'synthetic-super-secret'})
    with pytest.raises(ConfigError,match='Secret source'):
        snapshot.no_secrets({'env':{'PASSWORD':'synthetic-super-secret'}})
    snapshot.no_secrets({'secretEnv':{'PASSWORD':{'name':'bootstrap','key':'password'}}})


def test_child_health_order_is_declared(tmp_path):
    topology,snapshot=platform(tmp_path,[{'name':'api'}])
    obj=application(topology.settings,topology,'api',{'repoURL':'http://local','targetRevision':'abc'},3,'webservice')
    assert obj['metadata']['annotations']['argocd.argoproj.io/sync-wave']=='3'
    assert obj['spec']['syncPolicy']['automated']=={'prune':True,'selfHeal':True}
    assert obj['spec']['project']==topology.name
    assert 'RespectIgnoreDifferences=true' in obj['spec']['syncPolicy']['syncOptions']
    assert all('secret-revision' in pointer or pointer.endswith('/force-sync')
               for entry in obj['spec']['ignoreDifferences'] for pointer in entry['jsonPointers'])


def fake_snapshots(monkeypatch, snapshot):
    revisions = iter([f'{n:040x}' for n in range(1, 40)])
    trees = {}
    def commit(message):
        revision = next(revisions)
        trees[revision] = {str(p.relative_to(snapshot.repo)):p.read_bytes()
                          for p in snapshot.repo.rglob('*') if p.is_file() and '.git' not in p.parts}
        return revision
    def native(args, **kwargs):
        if args[:2] == ['git','init']:
            (snapshot.repo/'.git').mkdir()
            return ''
        if args[:2] == ['git','show']:
            revision,path = args[2].split(':',1)
            return trees[revision][path].decode()
        assert args[:3] == ['git','restore','--source']
        revision,prefix = args[3],args[5]
        for path,data in trees[revision].items():
            if path.startswith(prefix+'/'):
                (snapshot.repo/path).parent.mkdir(parents=True,exist_ok=True)
                (snapshot.repo/path).write_bytes(data)
        return ''
    monkeypatch.setattr('core.gitops.run',native)
    monkeypatch.setattr(snapshot,'commit',commit)


def test_snapshot_pins_payload_and_retains_unselected_apps(tmp_path, monkeypatch):
    topology, snapshot = platform(tmp_path, [{'name':'api'}, {'name':'consumer','type':'worker'}])
    fake_snapshots(monkeypatch, snapshot)
    root, initial = snapshot.create(topology.select())
    assert root['spec']['source']['targetRevision'] != initial['applications']['api']['source']['targetRevision']
    consumer = yaml.safe_load((snapshot.repo/'applications/consumer.yaml').read_text())
    _, focused = snapshot.create(topology.select('api'))
    assert set(focused['applications']) == {'api','consumer'}
    retained = yaml.safe_load((snapshot.repo/'applications/consumer.yaml').read_text())
    assert retained['spec'] == consumer['spec']
    assert retained['metadata']['annotations'][IGNORE_HEALTH] == 'true'
    _, pruned = snapshot.create(topology.select('api'), prune=True)
    assert set(pruned['applications']) == {'api'}
    assert not (snapshot.repo/'applications/consumer.yaml').exists()


def test_snapshot_registers_and_replaces_only_requested_test(tmp_path, monkeypatch):
    topology, snapshot = platform(tmp_path, [{'name':'checks','type':'test'}])
    fake_snapshots(monkeypatch, snapshot)
    snapshot.create(topology.select())
    values = snapshot.repo/'payload/values/checks.yaml'
    assert yaml.safe_load(values.read_text())['suspended'] is True
    snapshot.run_test('checks','execution-1')
    executed = yaml.safe_load(values.read_text())
    assert executed['suspended'] is False and executed['runId'] == 'execution-1'
    snapshot.create(topology.select())
    assert yaml.safe_load(values.read_text())['suspended'] is True


def test_dependency_values_use_native_precedence_and_scalar_substitution(tmp_path):
    (tmp_path/'chart-values.yaml').write_text('replicas: 1\nlabel: ${LABEL}\n')
    topology, snapshot = platform(tmp_path, [{'name':'api'}], {'dependencies':[
        {'name':'db','repo':'https://example.invalid','chart':'db','version':'1.0.0',
         'values_file':'chart-values.yaml','values':{'replicas':2}}]}, {'LABEL':'local label'})
    assert snapshot.dependency_values(topology.entities['db'][1]) == {'replicas':2,'label':'local label'}


def test_local_chart_dependency_cycle_is_rejected(tmp_path):
    from core.gitops import copy_chart
    for name, other in [('first','second'), ('second','first')]:
        directory = tmp_path/name
        directory.mkdir()
        (directory/'Chart.yaml').write_text(yaml.safe_dump({'apiVersion':'v2','name':name,
            'version':'1.0.0','dependencies':[{'name':other,'version':'1.0.0','repository':f'file://../{other}'}]}))
    with pytest.raises(ConfigError, match='Recursive local chart dependency'):
        copy_chart(tmp_path/'first', tmp_path/'output')


def test_running_one_suite_preserves_other_payloads_and_revisions(tmp_path,monkeypatch):
    topology,snapshot = platform(tmp_path,[{'name':'api'},{'name':'checks','type':'test'},
                                          {'name':'other-checks','type':'test'}])
    fake_snapshots(monkeypatch,snapshot)
    _,initial = snapshot.create(topology.select())
    before = {str(p.relative_to(snapshot.repo)):p.read_bytes()
              for p in (snapshot.repo/'payload').rglob('*') if p.is_file()}
    chart = snapshot.repo/'payload/charts/checks/values.yaml'
    deployed_chart = chart.read_bytes()
    chart.write_text('uncommitted: input must not be deployed by test\n')
    monkeypatch.setattr('core.gitops.copy_chart',lambda *a,**kw:pytest.fail('Test recopied live source'))
    _,executed = snapshot.run_test('checks','execution-1')
    assert chart.read_bytes() == deployed_chart
    assert executed['selected'] == initial['selected']
    for name in ['api','other-checks']:
        assert executed['applications'][name]['source'] == initial['applications'][name]['source']
    for path,data in before.items():
        if path != 'payload/values/checks.yaml':
            assert (snapshot.repo/path).read_bytes() == data
    checks_revision = executed['applications']['checks']['source']['targetRevision']
    snapshot.run_test('other-checks','execution-2')
    latest = json.loads(snapshot.inventory_path.read_text())
    assert latest['applications']['checks']['source']['targetRevision'] == checks_revision
    assert yaml.safe_load((snapshot.repo/'payload/values/checks.yaml').read_text())['runId']=='execution-1'


def test_unchanged_seed_does_not_rerun_when_sync_refresh_time_changes(tmp_path,monkeypatch):
    (tmp_path/'seeds').mkdir()
    (tmp_path/'seeds/prepare.py').write_text('print("prepare")\n')
    topology,snapshot = platform(tmp_path,[{'name':'api'}],{'seeds':[
        {'name':'prepare','image':'python:3.11-slim','files':'seeds','command':['python','/seeds/prepare.py']}]})
    fake_snapshots(monkeypatch,snapshot)
    _,initial = snapshot.create(topology.select())
    snapshot.refresh_after='2099-01-01T00:00:00Z'
    _,repeated = snapshot.create(topology.select())
    assert repeated['applications']['prepare']['job'] == initial['applications']['prepare']['job']
