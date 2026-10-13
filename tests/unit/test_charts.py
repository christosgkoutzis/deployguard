"""Offline Helm chart regression checks."""
import subprocess

import pytest
import yaml

from core.configuration import ROOT
from core.gitops import copy_chart


@pytest.mark.parametrize('chart',['webservice','worker','test','seed'])
def test_archetype_renders_resources_and_secret_references(tmp_path,chart):
    destination=tmp_path/chart
    copy_chart(ROOT/'platform/charts'/chart,destination)
    values={'image':{'ref':'example:immutable'},'resources':{'limits':{'memory':'128Mi'}},
            'secretEnv':{'PASSWORD':{'name':'bootstrap','key':'password'}},
            'initCommand':'echo initialize','revision':'123abc','files':{'seed.py':'print("seed")'}}
    values_file=tmp_path/'values.yaml'
    values_file.write_text(yaml.safe_dump(values))
    output=subprocess.run([str(ROOT/'.local/bin/helm'),'template','example',str(destination),'-f',str(values_file)],
                          check=True,capture_output=True,text=True).stdout
    objects=[obj for obj in yaml.safe_load_all(output) if obj]
    workload=next(o for o in objects if o['kind'] in ['Deployment','Job'] and not o['metadata']['name'].endswith('-init'))
    container=workload['spec']['template']['spec']['containers'][0]
    assert container['resources']['limits']['memory']=='128Mi'
    assert container['env'][0]['valueFrom']['secretKeyRef']['name']=='bootstrap'
    if chart=='worker':
        assert 'readinessProbe' not in container
        assert not any(o['kind'] in ['Service','Ingress'] for o in objects)
    if chart=='test':
        assert workload['spec']['suspend'] is True
        assert workload['spec']['activeDeadlineSeconds'] > 0
    if chart in ['worker','webservice']:
        init=next(o for o in objects if o['metadata']['name']=='example-init')
        assert init['metadata']['annotations']['argocd.argoproj.io/hook']=='Sync'
        assert 'optional' not in init['spec']['template']['spec']['containers'][0]['env'][0]['valueFrom']['secretKeyRef']


def test_mock_mapping_change_changes_pod_template(tmp_path):
    chart=tmp_path/'wiremock'
    copy_chart(ROOT/'platform/charts/wiremock',chart)
    annotations=[]
    for response in ['first','second']:
        values=tmp_path/'values.yaml'
        values.write_text(yaml.safe_dump({'clusterDomain':'example.test','mocks':{
            'mapping.json':'{"request":{},"response":{"body":"'+response+'"}}'}}))
        rendered=subprocess.run([str(ROOT/'.local/bin/helm'),'template','mock',str(chart),'-f',str(values)],
                                check=True,capture_output=True,text=True).stdout
        deployment=next(obj for obj in yaml.safe_load_all(rendered) if obj and obj['kind']=='Deployment')
        annotations.append(deployment['spec']['template']['metadata']['annotations']['checksum/mappings'])
    assert annotations[0] != annotations[1]
