"""Topology validation, dependency ordering and focused selection."""
import hashlib
import json
from graphlib import CycleError, TopologicalSorter
import re

from dotenv import dotenv_values
from jsonschema import Draft202012Validator
import yaml

from .configuration import ConfigError

VARIABLE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')
NAME = re.compile(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?')
ENV_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


def substitute(value, environment):
    if isinstance(value, str):
        def replace(match):
            name = match.group(1)
            if name not in environment:
                raise ConfigError(f'Missing environment variable {name}')
            return environment[name]
        return VARIABLE.sub(replace, value)
    if isinstance(value, list):
        return [substitute(v, environment) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, environment) for k, v in value.items()}
    return value


def assignments(entries, label):
    result = {}
    for entry in entries:
        if '=' not in entry:
            raise ConfigError(f'{label}: expected KEY=value')
        key, value = entry.split('=', 1)
        if key in result:
            raise ConfigError(f'{label}: duplicate key {key}')
        # Matching quotes around assignment values are stripped.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key] = value
    return result


class Topology:
    def __init__(self, settings):
        self.settings = settings
        self.base = settings.topology.parent
        try:
            raw = yaml.safe_load(settings.topology.read_text())
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError('Cannot read topology YAML') from exc
        schema = json.loads((settings.root / 'platform/config/topology.schema.json').read_text())
        errors = sorted(Draft202012Validator(schema).iter_errors(raw), key=lambda e: str(e.path))
        if errors:
            # Validation errors identify the field and rule without echoing its value.
            error = errors[0]
            path = '.'.join(str(p) for p in error.path) or 'topology'
            raise ConfigError(f'{path}: invalid configuration ({error.validator})')
        self.data = substitute(raw, settings.environment)
        self.name = self.data.get('name', 'deployguard')
        self.entities = {}
        for category in ['dependencies', 'seeds', 'services', 'secret_stores']:
            for item in self.data.get(category, []):
                self.add(item['name'], category, item)
        for name in self.data.get('mocks', []):
            self.add(name, 'mocks', {'name': name})
        if not self.entities:
            raise ConfigError('Topology must contain at least one entity')
        self.graph = {name: set(item.get('depends_on', [])) | ({item['external_secret']['store']} if item.get('external_secret') else set())
                      for name, (_, item) in self.entities.items()}
        for name, dependencies in self.graph.items():
            unknown = dependencies - self.entities.keys()
            if unknown:
                raise ConfigError(f'{name}: unknown dependency {sorted(unknown)[0]}')
            for dep in dependencies:
                if self.entities[dep][1].get('type') == 'test':
                    raise ConfigError(f'{name}: suspended tests cannot be startup dependencies')
        try:
            self.order = list(TopologicalSorter(self.graph).static_order())
        except CycleError as exc:
            raise ConfigError('Dependency graph contains a cycle') from exc
        self.levels = {}
        for name in self.order:
            self.levels[name] = max((self.levels[d] + 1 for d in self.graph[name]), default=0)
        for name, (category, item) in self.entities.items():
            if category == 'services' or (category == 'seeds' and item.get('build_path')):
                self.build_path(item)
            if category in ['services', 'seeds']:
                environment = self.environment(item)
                if item.get('type') == 'test' and ('init_command' in item or 'INIT_COMMAND' in environment):
                    raise ConfigError(f'{name}: test services must prepare data inside their test program; initialization commands are unsupported')
            if category == 'mocks':
                mappings = self.base / 'mocks' / name
                files = sorted(mappings.glob('*.json'))
                if not files:
                    raise ConfigError(f'{name}: at least one mock mapping is required')
                for file in files:
                    try:
                        mapping = json.loads(file.read_text())
                    except (OSError, ValueError) as exc:
                        raise ConfigError(f'{name}: invalid JSON mapping {file.name}') from exc
                    if not isinstance(mapping, dict) or not {'request', 'response'} <= mapping.keys():
                        raise ConfigError(f'{name}: mapping requires request and response')
            if category == 'dependencies':
                if item.get('path') and not (self.base / item['path'] / 'Chart.yaml').is_file():
                    raise ConfigError(f'{name}: local chart not found')
                assignments(item.get('set', []), name)
                if not item.get('path') and not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?',item['version']):
                    raise ConfigError(f'{name}: version must be an exact Helm chart version')
                if item.get('values_file'):
                    try:
                        values = yaml.safe_load((self.base/item['values_file']).read_text())
                    except (OSError,yaml.YAMLError) as exc:
                        raise ConfigError(f'{name}: invalid values_file') from exc
                    if not isinstance(values,dict):
                        raise ConfigError(f'{name}: values_file must contain a mapping')
                    substitute(values, settings.environment)
            if category == 'seeds':
                directory = self.base/item.get('files','seeds')
                if not directory.is_dir() or any(p.is_dir() for p in directory.iterdir()):
                    raise ConfigError(f'{name}: files must be a flat seed directory')
        self.validate_secrets()
        self.signature = hashlib.sha256(json.dumps({'topology':self.data,
            'environment':{n:self.environment(i) for n,(c,i) in self.entities.items()
                           if c in ['services','seeds']},
            'values_files':{n:substitute(yaml.safe_load((self.base/i['values_file']).read_text()),
                                        settings.environment)
                            for n,(c,i) in self.entities.items() if c == 'dependencies' and i.get('values_file')},
            'secret_sources':{variable:settings.environment[variable]
                              for secret in self.data.get('secrets',[])
                              for variable in secret['values'].values()},
            'network':{'domain':settings.domain,'ingress_port':settings.ingress_port,
                       'source_port':settings.source_port,'argo_namespace':settings.argo_namespace}},
            sort_keys=True).encode()).hexdigest()

    def add(self, name, category, item):
        if not NAME.fullmatch(name) or len(name) > 40:
            raise ConfigError('Entity names must be DNS labels of at most 40 characters')
        if name in self.entities or name == f'{self.name}-environment':
            raise ConfigError(f'Duplicate or reserved entity name {name}')
        self.entities[name] = (category, item)

    def build_path(self, item):
        default = ('tests' if item.get('type') == 'test' else 'services') + '/' + item['name']
        path = (self.base / item.get('build_path', default)).resolve()
        if not (path / 'Dockerfile').is_file():
            raise ConfigError(f'{item["name"]}: Dockerfile not found at its build_path')
        return path

    def environment(self, item):
        values = {}
        if item.get('env_file'):
            path = self.build_path(item) / item['env_file']
            if not path.is_file():
                raise ConfigError(f'{item["name"]}: env_file not found')
            values = {k: substitute(v, self.settings.environment)
                      for k, v in dotenv_values(path, interpolate=False).items() if v is not None}
        values.update(assignments(item.get('env', []), item['name']))
        if any(not ENV_NAME.fullmatch(k) for k in values):
            raise ConfigError(f'{item["name"]}: invalid environment variable name')
        if set(values) & item.get('secret_env', {}).keys():
            raise ConfigError(f'{item["name"]}: env and secret_env overlap')
        return values

    def validate_secrets(self):
        declared = {}
        for secret in self.data.get('secrets', []):
            name = secret['name']
            if name in declared:
                raise ConfigError(f'Duplicate secret {name}')
            declared[name] = secret['values']
            for variable in secret['values'].values():
                if variable not in self.settings.environment:
                    raise ConfigError(f'{name}: missing secret source variable {variable}')
        for store in self.data.get('secret_stores', []):
            ref = store['token_secret']
            if ref['name'] not in declared or ref['key'] not in declared[ref['name']]:
                raise ConfigError(f'{store["name"]}: token_secret must reference a declared secret')
        stores = {s['name'] for s in self.data.get('secret_stores', [])}
        if len(stores) != len(self.data.get('secret_stores', [])):
            raise ConfigError('Duplicate secret store')
        for name, (_, item) in self.entities.items():
            external = item.get('external_secret')
            if external and external['store'] not in stores:
                raise ConfigError(f'{name}: unknown secret store')
            for ref in item.get('secret_env', {}).values():
                if ref['name'] not in declared or ref['key'] not in declared[ref['name']]:
                    raise ConfigError(f'{name}: secret_env must reference a declared secret/key')
            for ref in item.get('env_from', []):
                if ref not in declared:
                    raise ConfigError(f'{name}: env_from must reference a declared secret')

    def select(self, focus=None):
        if not focus:
            return self.order.copy()
        if focus not in self.entities:
            raise ConfigError(f'Unknown focus {focus}')
        selected, pending = set(), [focus]
        while pending:
            name = pending.pop()
            if name not in selected:
                selected.add(name)
                pending.extend(self.graph[name])
        return [name for name in self.order if name in selected]
