"""Install Python dependencies and pinned tools inside the checkout."""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import venv

ROOT = Path(__file__).resolve().parents[2]


class InstallError(ValueError):
    """A prerequisite or downloaded tool failed validation."""


def run(arguments, **kwargs):
    subprocess.run([str(argument) for argument in arguments], check=True, **kwargs)


def target_platform():
    systems = {'Linux': 'linux', 'Darwin': 'darwin'}
    architectures = {'x86_64': 'amd64', 'amd64': 'amd64', 'arm64': 'arm64', 'aarch64': 'arm64'}
    try:
        return systems[platform.system()], architectures[platform.machine().lower()]
    except KeyError as exc:
        raise InstallError('Tool installation supports Linux/macOS on amd64/arm64') from exc


def verify_checksum(binary, checksum_file, filename=None):
    lines = checksum_file.read_text().splitlines()
    if filename:
        lines = [line for line in lines if line.split() and
                 Path(line.split()[-1].lstrip('*')).name == filename]
    if len(lines) != 1 or not lines[0].split():
        raise InstallError(f'Missing or ambiguous checksum for {binary.name}')
    expected = lines[0].split()[0].lower()
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise InstallError(f'Invalid checksum for {binary.name}')
    with binary.open('rb') as source:
        actual = hashlib.file_digest(source, 'sha256').hexdigest()
    if actual != expected:
        raise InstallError(f'Checksum mismatch for {binary.name}')


def install_tools(root, system, architecture):
    with (root/'pyproject.toml').open('rb') as manifest:
        versions = tomllib.load(manifest)['tool']['deployguard']['versions']
    destination = root/'.local/bin'
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='install-', dir=root/'.local/tmp') as temporary:
        staging = Path(temporary)

        def download(url, name):
            path = staging/name
            run(['curl', '--fail', '--silent', '--show-error', '--location',
                 '--connect-timeout', '30', '--max-time', '300', url, '--output', path], timeout=360)
            return path

        kubectl = download(f'https://dl.k8s.io/release/{versions["kubectl"]}/bin/{system}/{architecture}/kubectl', 'kubectl')
        checksum = download(f'https://dl.k8s.io/release/{versions["kubectl"]}/bin/{system}/{architecture}/kubectl.sha256', 'kubectl.sha256')
        verify_checksum(kubectl, checksum)

        archive_name = f'helm-{versions["helm"]}-{system}-{architecture}.tar.gz'
        archive = download(f'https://get.helm.sh/{archive_name}', 'helm.tar.gz')
        checksum = download(f'https://get.helm.sh/{archive_name}.sha256sum', 'helm.sha256')
        verify_checksum(archive, checksum)
        run(['tar', '-xzf', archive, '-C', staging])

        k3d_name = f'k3d-{system}-{architecture}'
        k3d_url = f'https://github.com/k3d-io/k3d/releases/download/{versions["k3d"]}'
        k3d = download(f'{k3d_url}/{k3d_name}', 'k3d')
        checksum = download(f'{k3d_url}/checksums.txt', 'k3d-checksums')
        verify_checksum(k3d, checksum, k3d_name)

        skaffold_url = f'https://storage.googleapis.com/skaffold/releases/{versions["skaffold"]}/skaffold-{system}-{architecture}'
        skaffold = download(skaffold_url, 'skaffold')
        checksum = download(skaffold_url+'.sha256', 'skaffold.sha256')
        verify_checksum(skaffold, checksum)

        for source in [kubectl, k3d, skaffold, staging/f'{system}-{architecture}/helm']:
            target = destination/source.name
            prepared = staging/f'{source.name}.installed'
            shutil.copyfile(source, prepared)
            prepared.chmod(0o755)
            prepared.replace(target)


def create_configuration(root):
    """Create .env from the example while preserving existing configuration."""
    example = (root/'.env.example').read_bytes()
    try:
        descriptor = os.open(root/'.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as destination:
            destination.write(example)
    except FileExistsError:
        return False
    return True


def install(root=ROOT, *, assessment=False):
    system, architecture = target_platform()
    missing = [command for command in ['curl', 'tar'] if not shutil.which(command)]
    if missing:
        raise InstallError('Missing installation prerequisites: '+', '.join(missing))
    if sys.version_info < (3, 11):
        raise InstallError('Python 3.11 or newer is required')
    for directory in ['tmp', 'cache/pip', 'cache/python']:
        (root/'.local'/directory).mkdir(parents=True, exist_ok=True)
    environment = root/'.local/venv'
    python = environment/'bin/python'
    if environment.exists():
        if not python.is_file():
            raise InstallError('Existing .local/venv is incomplete; it has not been replaced')
    else:
        venv.EnvBuilder(with_pip=True).create(environment)
    run([python, '-c', 'import sys; sys.exit(sys.version_info < (3, 11))'])
    project = str(root)+('[assessment]' if assessment else '')
    run([python, '-m', 'pip', 'install', '--editable', project], cwd=root)
    install_tools(root, system, architecture)
    created = create_configuration(root)
    print('INFO: Checkout-local Python dependencies and pinned tools installed.')
    if created:
        print('INFO: Created .env from .env.example. Set your credentials and environment configuration.')
    else:
        print('INFO: Existing .env retained.')
    print('INFO: Run ./scripts/deployguard doctor to check application prerequisites.')


def main(argv=None):
    parser = argparse.ArgumentParser(prog='./scripts/deployguard install',
        description='Install DeployGuard into this checkout without changing the cluster')
    parser.add_argument('--assessment', action='store_true', help='Include dependencies for local tool tests')
    args = parser.parse_args(argv)
    try:
        install(assessment=args.assessment)
    except (InstallError, OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f'ERROR: Installation failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
