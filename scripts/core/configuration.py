"""Checkout configuration, environment settings and tool versions."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import tomllib

import yaml

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    """Invalid environment or topology configuration."""


@dataclass(frozen=True)
class Settings:
    root: Path
    topology: Path
    state: Path
    environment: dict
    cluster: str
    namespace: str
    argo_namespace: str
    domain: str
    ingress_port: int
    source_port: int
    timeout: int
    api_port: int = 6443

    @classmethod
    def load(cls, topology=None):
        env = {**dotenv_values(ROOT / '.env', interpolate=False), **os.environ}
        defaults = {
            'S3_ACCESS_KEY_ID': 'admin', 'CLUSTER_NAME': 'control-plane-cluster', 'NAMESPACE': 'deployguard',
            'ARGO_APP_NAMESPACE': 'argocd', 'CLUSTER_DOMAIN': '127.0.0.1.nip.io',
            'API_PORT': '6443', 'INGRESS_PORT': '8080', 'SOURCE_PORT': '8081', 'TIMEOUT_SECONDS': '600',
        }
        env = {**defaults, **{k: v for k, v in env.items() if v is not None}}
        for key in ['CLUSTER_NAME', 'NAMESPACE', 'ARGO_APP_NAMESPACE']:
            if len(env[key]) > 63 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', env[key]):
                raise ConfigError(f'{key} must be a lowercase DNS label')
        if not re.fullmatch(r'[a-zA-Z0-9.-]+', env['CLUSTER_DOMAIN']):
            raise ConfigError('CLUSTER_DOMAIN must be a hostname')
        try:
            ports = [int(env[k]) for k in ['INGRESS_PORT', 'SOURCE_PORT']]
            timeout = int(env['TIMEOUT_SECONDS'])
            api_port = int(env['API_PORT'])
        except ValueError as exc:
            raise ConfigError('Ports and TIMEOUT_SECONDS must be integers') from exc
        if any(p < 1 or p > 65535 for p in [*ports,api_port]) or timeout < 1:
            raise ConfigError('Invalid port or timeout')
        path = Path(topology or env.get('TOPOLOGY_FILE', ROOT / 'deployguard.yaml')).resolve()
        state = ROOT / '.local/state'
        return cls(ROOT, path, state, env, env['CLUSTER_NAME'], env['NAMESPACE'],
                   env['ARGO_APP_NAMESPACE'], env['CLUSTER_DOMAIN'], *ports, timeout, api_port)

    @property
    def context(self):
        return f'k3d-{self.cluster}'

    @property
    def source_url(self):
        return f'http://deployguard-source-{self.cluster}/environment.git'


def tool_versions(root=ROOT):
    with (root / 'pyproject.toml').open('rb') as manifest:
        return tomllib.load(manifest)['tool']['deployguard']['versions']


def write_yaml(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False))
