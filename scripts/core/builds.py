"""Skaffold configuration, selected image builds and k3d image imports."""
import json

from .configuration import write_yaml
from .kubernetes import run


class Builds:
    def __init__(self, topology):
        self.topology = topology
        self.settings = topology.settings
        self.artifacts_path = self.settings.state / 'artifacts.json'

    def artifacts(self):
        data = json.loads(self.artifacts_path.read_text())
        return {entry['imageName']: entry['tag'] for entry in data['builds']}

    def build_config(self, selected):
        artifacts = []
        for name in selected:
            category, item = self.topology.entities[name]
            if category == 'services' or (category == 'seeds' and item.get('build_path')):
                artifacts.append({'image':name, 'context':str(self.topology.build_path(item)),
                                  'docker':{'dockerfile':'Dockerfile'}})
        return {'apiVersion':'skaffold/v4beta13','kind':'Config',
                'metadata':{'name':self.topology.name},
                'build':{'local':{'push':False,'useBuildkit':True},
                         'tagPolicy':{'inputDigest':{}}, 'artifacts':artifacts}}

    def build(self, selected):
        config = self.build_config(selected)
        config_path = self.settings.state / 'skaffold.yaml'
        write_yaml(config_path, config)
        if not config['build']['artifacts']:
            self.artifacts_path.write_text('{"builds":[]}\n')
            return
        timeout = max(self.settings.timeout, 1200)
        run(['skaffold', 'build', '--filename', config_path,
             '--kube-context', self.settings.context, '--file-output', self.artifacts_path],
            cwd=self.settings.root, timeout=timeout)
        run(['k3d', 'image', 'import', *self.artifacts().values(), '-c', self.settings.cluster],
            timeout=timeout)
