"""Topology validation and dependency selection checks."""
from dataclasses import replace

import pytest
import yaml

from core.configuration import ConfigError, ROOT, Settings
from core.topology import Topology


@pytest.fixture
def environment(tmp_path):
    settings = Settings(ROOT,tmp_path/'deployguard.yaml',tmp_path/'state',{},
                        'test','deployguard','argocd','127.0.0.1.nip.io',8080,8081,30)
    def load(data, variables=None):
        settings.topology.write_text(yaml.safe_dump(data))
        for item in [*data.get('services',[]),*data.get('seeds',[])]:
            if item.get('image'):
                continue
            default = ('tests' if item.get('type') == 'test' else 'services')+'/'+item['name']
            directory = tmp_path/item.get('build_path',default)
            directory.mkdir(parents=True,exist_ok=True)
            (directory/'Dockerfile').write_text('FROM scratch\n')
        return Topology(replace(settings,environment=variables or {}))
    return load


def test_focus_includes_dependencies_of_dependencies(environment):
    topology = environment({'services':[{'name':'api','depends_on':['db']}],
        'dependencies':[{'name':'db','repo':'https://example.invalid','chart':'db',
                         'version':'1.0.0','depends_on':['broker']},
                        {'name':'broker','repo':'https://example.invalid','chart':'broker','version':'1.0.0'}]})
    assert topology.select('api') == ['broker','db','api']


def test_unknown_focus_fails(environment):
    topology = environment({'services':[{'name':'api'}]})
    with pytest.raises(ConfigError,match='Unknown focus'):
        topology.select('typo')


@pytest.mark.parametrize('data',[
    {'services':[{'name':'api','depends_on':['missing']}]},
    {'services':[{'name':'a','depends_on':['b']},{'name':'b','depends_on':['a']}]},
    {'services':[{'name':'same'},{'name':'same'}]},
    {'services':[{'name':'bad_name'}]},
    {'services':[{'name':'api','type':'unknown'}]},
    {'services':[{'name':'api','port':70000}]},
    {'services':[{'name':'api','health_endpoint':'bad'}]},
    {'services':[{'name':'api','unexpected':True}]},
])
def test_invalid_contracts_fail(environment,data):
    with pytest.raises(ConfigError):
        environment(data)


def test_custom_path_worker_and_env_file(environment):
    topology = environment({'services':[{'name':'consumer','type':'worker','build_path':'custom/consumer',
                                        'env':['MESSAGE="hello world"']}]})
    assert topology.build_path(topology.entities['consumer'][1]).name == 'consumer'
    assert topology.environment(topology.entities['consumer'][1]) == {'MESSAGE':'hello world'}


def test_substitution_keeps_yaml_structure(environment):
    payload = 'value: [not, yaml]\n# still one scalar'
    topology = environment({'services':[{'name':'api','env':['MESSAGE=${MESSAGE}']}]},{'MESSAGE':payload})
    assert topology.environment(topology.entities['api'][1])['MESSAGE'] == payload


def test_unresolved_variable_is_not_silently_kept(environment):
    with pytest.raises(ConfigError,match='Missing environment variable'):
        environment({'services':[{'name':'api','env':['MESSAGE=${ABSENT}']}]})


def test_optional_secrets(environment):
    topology = environment({'services':[{'name':'api'}]})
    assert 'external_secret' not in topology.entities['api'][1]


def test_secret_store_is_an_implicit_dependency(environment):
    topology = environment({'services':[{'name':'api','external_secret':{'store':'vault-store','path':'test/api'}}],
        'dependencies':[{'name':'vault','repo':'https://example.invalid','chart':'vault','version':'1.0.0'}],
        'secrets':[{'name':'token','values':{'token':'TOKEN'}}],
        'secret_stores':[{'name':'vault-store','server':'http://vault:8200',
                         'token_secret':{'name':'token','key':'token'},'depends_on':['vault']}]},{'TOKEN':'test-token'})
    assert topology.select('api') == ['vault','vault-store','api']


def test_unknown_secret_reference_fails(environment):
    with pytest.raises(ConfigError,match='secret_env'):
        environment({'services':[{'name':'api','secret_env':{'PASSWORD':{'name':'missing','key':'password'}}}]})


def test_missing_env_file_fails(environment):
    with pytest.raises(ConfigError,match='env_file'):
        environment({'services':[{'name':'api','env_file':'.missing'}]})


def test_command_preserves_repeated_flags_and_arguments(environment):
    command=['python','-W','ignore','-W','default::DeprecationWarning','app.py']
    topology=environment({'services':[{'name':'api','command':command,'args':['same','same']}]})
    assert topology.entities['api'][1]['command']==command
    assert topology.entities['api'][1]['args']==['same','same']


@pytest.mark.parametrize('configuration',[
    {'init_command':'python prepare.py'},
    {'env':['INIT_COMMAND=python prepare.py']},
    {'env_file':'test.env'},
])
def test_test_services_reject_separate_initialization(environment,tmp_path,configuration):
    directory=tmp_path/'tests/checks'
    directory.mkdir(parents=True)
    (directory/'test.env').write_text('INIT_COMMAND=python prepare.py\n')
    with pytest.raises(ConfigError,match='prepare data inside their test program'):
        environment({'services':[{'name':'checks','type':'test',**configuration}]})


@pytest.mark.parametrize('version',['latest','1.2','1.2.x','>=1.0.0','~1.2.3'])
def test_remote_chart_requires_an_exact_version(environment,version):
    with pytest.raises(ConfigError,match='exact Helm chart version'):
        environment({'dependencies':[{'name':'db','repo':'https://example.invalid',
                                     'chart':'db','version':version}]})
