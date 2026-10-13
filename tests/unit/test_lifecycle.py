"""CLI failure diagnostics, readiness scope and Secret rollout regression checks."""
from copy import deepcopy
from contextlib import nullcontext
from http.client import RemoteDisconnected
import json
from types import SimpleNamespace

import pytest

from core.cli import failure_message, main, source_server, wait_environment
from core.configuration import ConfigError
from core.kubernetes import Kubernetes, SECRET_REVISION, secret_references


@pytest.mark.parametrize('error', [
    FileNotFoundError(2, 'sensitive-exception-value', '/sensitive-path'),
    ValueError('sensitive-exception-value'),
    json.JSONDecodeError('sensitive-exception-value', 'sensitive-input', 2),
])
def test_cli_failure_reports_source_and_type_without_input_values(monkeypatch, capsys, error):
    monkeypatch.setattr('core.cli.Settings.load', lambda path: None)
    def fail(settings):
        raise error
    monkeypatch.setattr('core.cli.Topology', fail)
    assert main(['validate']) == 1
    message = capsys.readouterr().err
    assert type(error).__name__ in message
    assert 'cli.py:' in message and '(main)' in message
    assert 'sensitive-exception-value' not in message
    assert 'sensitive-input' not in message and 'sensitive-path' not in message
    if isinstance(error, OSError):
        assert 'errno=2' in message
    if isinstance(error, json.JSONDecodeError):
        assert 'JSON line 1, column 3' in message


def test_configuration_errors_keep_their_actionable_message():
    assert failure_message(ConfigError('Unknown focus missing-service')) == 'Unknown focus missing-service'


@pytest.mark.parametrize('connection_error', [ConnectionResetError, RemoteDisconnected])
@pytest.mark.parametrize('becomes_ready', [True, False])
def test_git_source_readiness_retries_connection_failures_until_deadline(
        monkeypatch, tmp_path, connection_error, becomes_ready):
    settings = SimpleNamespace(root=tmp_path, state=tmp_path/'state', cluster='fixture', source_port=8081)
    commands = []
    def docker(args, **kwargs):
        commands.append(args)
        return ''
    monkeypatch.setattr('core.cli.run', docker)
    monkeypatch.setattr('core.cli.tool_versions', lambda root: {'nginx':'nginx:test'})
    times = iter([0, 0, 1, 2] if becomes_ready else [0, 0, 1, 30])
    sleeps = []
    monkeypatch.setattr('core.cli.time.monotonic', lambda: next(times))
    monkeypatch.setattr('core.cli.time.sleep', sleeps.append)
    probes = []
    def probe(url, *, timeout):
        probes.append(url)
        assert url == 'http://127.0.0.1:8081/environment.git/info/refs'
        assert timeout == 3
        if len(probes) <= 2:
            raise connection_error('Source is starting')
        return nullcontext(SimpleNamespace(status=200))
    monkeypatch.setattr('core.cli.urllib.request.urlopen', probe)
    if becomes_ready:
        source_server(settings, 'fixture')
        assert len(probes) == 3
    else:
        with pytest.raises(ConfigError, match='Local Git source server did not become ready'):
            source_server(settings, 'fixture')
        assert len(probes) == 2
    assert sleeps == [1, 1]
    assert [args[:2] for args in commands] == [['docker','container'], ['docker','run']]


def test_verification_ignores_parent_and_test_health_but_checks_selected_services():
    calls=[]
    class Fake:
        settings=SimpleNamespace(argo_namespace='argocd')
        def get(self,kind,name,namespace=None,**kwargs):
            return {'spec':{'source':{'targetRevision':'child'}}}
        def application_ready(self,name,revision,*,health=True):
            calls.append((name,health))
            return True
        def wait(self,label,predicate):
            assert predicate()
    inventory={'revision':'root','selected':['api','checks'],'applications':{
        'api':{'kind':'webservice','source':{'targetRevision':'child'}},
        'checks':{'kind':'test','source':{'targetRevision':'child'}},
        'unselected':{'kind':'worker','source':{'targetRevision':'old'}}}}
    wait_environment(Fake(),SimpleNamespace(name='fixture'),inventory)
    assert calls == [('api',True),('checks',False),('fixture-environment',False)]
    calls.clear()
    wait_environment(Fake(),SimpleNamespace(name='fixture'),inventory,['api'])
    assert calls == [('api',True),('fixture-environment',False)]


def test_secret_references_include_env_files_and_projected_volumes():
    pod={'containers':[{'env':[{'valueFrom':{'secretKeyRef':{'name':'direct','key':'password'}}}],
                        'envFrom':[{'secretRef':{'name':'optional','optional':True}}]}],
         'volumes':[{'secret':{'secretName':'mounted'}},
                    {'projected':{'sources':[{'secret':{'name':'projected'}}]}}]}
    assert secret_references(pod) == {'direct':True,'optional':False,'mounted':True,'projected':True}


def test_only_changed_secret_versions_roll_consumers(monkeypatch):
    kube=Kubernetes(SimpleNamespace(namespace='app',argo_namespace='argocd',timeout=30))
    app={'status':{'resources':[{'kind':'Deployment','name':'api','namespace':'app'}]}}
    workload={'metadata':{'annotations':{}},'spec':{'template':{'metadata':{},'spec':{
        'containers':[{'envFrom':[{'secretRef':{'name':'passwords'}}]}]}}}}
    secret={'metadata':{'uid':'secret-uid','resourceVersion':'1'}}
    patches=[]
    rollouts=[]
    def get(kind,name,namespace=None,**kwargs):
        return deepcopy({'application':app,'Deployment':workload,'secret':secret}[kind])
    def command(*args,**kwargs):
        if 'patch' in args:
            patch=json.loads(args[args.index('-p')+1])
            patches.append(patch)
            workload['metadata']['annotations'].update(patch['metadata']['annotations'])
            if 'spec' in patch:
                workload['spec']['template']['metadata'].update(patch['spec']['template']['metadata'])
        else:
            assert 'rollout' in args
            rollouts.append(args)
    monkeypatch.setattr(kube,'get',get)
    monkeypatch.setattr(kube,'command',command)
    assert kube.refresh_secret_consumers('api')
    assert 'spec' not in patches[0] and not rollouts
    assert kube.refresh_secret_consumers('api') and len(patches)==1
    secret['metadata']['resourceVersion']='2'
    assert kube.refresh_secret_consumers('api')
    assert len(rollouts)==1
    assert patches[-1]['spec']['template']['metadata']['annotations'][SECRET_REVISION]
    assert kube.refresh_secret_consumers('api') and len(rollouts)==1


def test_external_secret_refresh_requires_new_operator_acknowledgement(monkeypatch):
    kube=Kubernetes(SimpleNamespace(namespace='app',argo_namespace='argocd',timeout=30))
    app={'status':{'resources':[{'kind':'ExternalSecret','name':'credentials','namespace':'app'}]}}
    external={'status':{'syncedResourceVersion':'previous',
                        'conditions':[{'type':'Ready','status':'True'}]}}
    requests=[]
    def get(kind,name,namespace=None,**kwargs):
        return deepcopy(app if kind=='application' else external)
    def command(*args,**kwargs):
        assert 'annotate' in args
        requests.append(args)
    def wait(label,predicate):
        assert predicate() is False, 'Old Ready status accepted before the requested refresh'
        external['status']['syncedResourceVersion']='refreshed'
        assert predicate() is True
    monkeypatch.setattr(kube,'get',get)
    monkeypatch.setattr(kube,'command',command)
    monkeypatch.setattr(kube,'wait',wait)
    refreshed=set()
    assert kube.refresh_secret_consumers('api',refreshed=refreshed)
    assert kube.refresh_secret_consumers('api',refreshed=refreshed)
    assert len(requests)==1
