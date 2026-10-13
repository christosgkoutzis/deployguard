"""Installer safety and launcher forwarding checks; no network or cluster flows."""
import hashlib
import json
import shutil
import subprocess
import sys

import pytest

from core.configuration import ROOT
from core.installation import InstallError, create_configuration, verify_checksum


def test_configuration_is_created_once_without_overwriting_user_values(tmp_path):
    (tmp_path/'.env.example').write_text('PASSWORD=example\n')
    assert create_configuration(tmp_path) is True
    assert (tmp_path/'.env').stat().st_mode & 0o777 == 0o600
    (tmp_path/'.env').write_text('PASSWORD=user-configured\n')
    assert create_configuration(tmp_path) is False
    assert (tmp_path/'.env').read_text() == 'PASSWORD=user-configured\n'


def test_existing_configuration_symlink_is_preserved(tmp_path):
    (tmp_path/'.env.example').write_text('PASSWORD=example\n')
    target = tmp_path/'user.env'
    target.write_text('PASSWORD=user-configured\n')
    (tmp_path/'.env').symlink_to(target)
    assert create_configuration(tmp_path) is False
    assert target.read_text() == 'PASSWORD=user-configured\n'
    assert (tmp_path/'.env').is_symlink()


@pytest.mark.parametrize('artifact', [
    'k3d-linux-amd64', 'k3d-linux-arm64', 'k3d-darwin-amd64', 'k3d-darwin-arm64',
])
@pytest.mark.parametrize('prefix', ['', '_dist/', './', '*_dist/'])
def test_downloaded_tools_require_the_selected_published_checksum(tmp_path, artifact, prefix):
    binary = tmp_path/'k3d'
    binary.write_bytes(b'verified-tool-input')
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    checksum = tmp_path/'checksums.txt'
    checksum.write_text('0'*64+'  unrelated-file\n'+digest+'  '+prefix+artifact+'\n')
    verify_checksum(binary, checksum, artifact)
    binary.write_bytes(b'corrupted-input')
    with pytest.raises(InstallError, match='Checksum mismatch'):
        verify_checksum(binary, checksum, artifact)
    with pytest.raises(InstallError, match='Missing or ambiguous'):
        verify_checksum(binary, checksum, 'missing-file')


def test_duplicate_checksum_filenames_are_rejected(tmp_path):
    binary = tmp_path/'k3d'
    binary.write_bytes(b'verified-tool-input')
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    checksum = tmp_path/'checksums.txt'
    checksum.write_text(digest+'  k3d-linux-amd64\n'+digest+'  _dist/k3d-linux-amd64\n')
    with pytest.raises(InstallError, match='Missing or ambiguous'):
        verify_checksum(binary, checksum, 'k3d-linux-amd64')


def test_launcher_preserves_arguments_and_sets_checkout_local_paths(tmp_path):
    scripts = tmp_path/'scripts'
    scripts.mkdir()
    launcher = scripts/'deployguard'
    shutil.copy2(ROOT/'scripts/deployguard', launcher)
    executable = tmp_path/'.local/venv/bin/deployguard'
    executable.parent.mkdir(parents=True)
    executable.write_text(f'#!{sys.executable}\n'+
        'import json,os,sys\nprint(json.dumps({"arguments":sys.argv[1:],'
        '"environment":{k:os.environ[k] for k in ["PATH","TMPDIR","PIP_CACHE_DIR","PYTHONPYCACHEPREFIX"]}}))\n')
    executable.chmod(0o755)
    result = subprocess.run([str(launcher),'validate','--topology','a path/topology.yaml'],
                            check=True,capture_output=True,text=True,cwd=tmp_path)
    output = json.loads(result.stdout)
    assert output['arguments'] == ['validate','--topology','a path/topology.yaml']
    environment = output['environment']
    assert environment['PATH'].split(':')[:2] == [str(tmp_path/'.local/venv/bin'),str(tmp_path/'.local/bin')]
    assert environment['TMPDIR'] == str(tmp_path/'.local/tmp')
    assert environment['PIP_CACHE_DIR'] == str(tmp_path/'.local/cache/pip')
    assert environment['PYTHONPYCACHEPREFIX'] == str(tmp_path/'.local/cache/python')


def test_launcher_requires_explicit_installation(tmp_path):
    (tmp_path/'scripts').mkdir()
    launcher = tmp_path/'scripts/deployguard'
    shutil.copy2(ROOT/'scripts/deployguard', launcher)
    result = subprocess.run([str(launcher),'setup'],capture_output=True,text=True)
    assert result.returncode != 0
    assert 'install first' in result.stderr
    assert not (tmp_path/'.local').exists()
