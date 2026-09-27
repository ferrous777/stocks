import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
CODE_DIRS = (
    'analysis', 'config', 'market_calendar', 'market_data', 'recommendations',
    'scheduler', 'storage', 'strategies', 'templates', 'utils', 'performance',
    'alerts', 'plaid_integration', 'time_estimation',
)
ROOT_FILES = ('app.py', 'main.py', 'wsgi.py', 'requirements.txt', 'version.py', '__init__.py')


@pytest.fixture
def deployment_checkout(tmp_path):
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    for name in CODE_DIRS:
        shutil.copytree(ROOT / name, checkout / name,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.db', '*.json'))
    for name in (*ROOT_FILES, 'deploy_clean.sh'):
        shutil.copy2(ROOT / name, checkout / name)
    (checkout / 'scripts').mkdir()
    for name in ('deploy_to_pythonanywhere.sh', 'pythonanywhere_daily_hook.py',
                 'pythonanywhere_daily_hook_server.py'):
        shutil.copy2(ROOT / 'scripts' / name, checkout / 'scripts' / name)
    for name in ('data', 'cache', 'results', 'logs', 'reports', 'performance'):
        (checkout / name).mkdir(exist_ok=True)
        (checkout / name / 'preserve.txt').write_text('local runtime sentinel')
    return checkout


@pytest.fixture
def isolated_remote(tmp_path, monkeypatch):
    remote = tmp_path / 'remote'
    remote.mkdir()
    commands = tmp_path / 'commands.jsonl'
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    rsync = shutil.which('rsync')
    assert rsync, 'Deployment tests require rsync'
    # Exercise real rsync locally; intercept every SSH call to prevent deployment.
    for command in ('rsync', 'ssh'):
        path = bin_dir / command
        path.write_text(f'#!{sys.executable}\n' + '''import json, os, subprocess, sys
from pathlib import Path
command = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['DEPLOY_TEST_COMMANDS'], 'a') as log:
    log.write(json.dumps({'command': command, 'args': args,
                         'stdin': sys.stdin.read() if command == 'ssh' else ''}) + '\\n')
if command == 'rsync':
    if os.environ.get('DEPLOY_TEST_FAIL'):
        sys.exit(23)
    args[-1] = os.environ['DEPLOY_TEST_REMOTE'] + '/'
    sys.exit(subprocess.call([os.environ['DEPLOY_TEST_RSYNC'], *args]))
''')
        path.chmod(0o755)
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('DEPLOY_TEST_REMOTE', str(remote))
    monkeypatch.setenv('DEPLOY_TEST_COMMANDS', str(commands))
    monkeypatch.setenv('DEPLOY_TEST_RSYNC', rsync)
    return remote, commands


@pytest.mark.parametrize('with_static', [False, True])
def test_direct_deploy_preserves_runtime_files_and_includes_hook_imports(
    deployment_checkout, isolated_remote, tmp_path, with_static
):
    remote, commands = isolated_remote
    if with_static:
        (deployment_checkout / 'static').mkdir()
        (deployment_checkout / 'static' / 'asset.css').write_text('/* asset sentinel */')
    for name in ('data', 'cache', 'results', 'logs', 'reports', 'performance'):
        (remote / name).mkdir()
        (remote / name / 'preserve.txt').write_text('server runtime sentinel')
    subprocess.run(['bash', str(deployment_checkout / 'deploy_clean.sh')],
                   cwd=tmp_path, check=True, capture_output=True, text=True)
    for name in (*ROOT_FILES, 'pythonanywhere_daily_hook.py',
                 'performance/prediction_tracker.py', 'performance/config.py',
                 'alerts/alert_engine.py', 'plaid_integration/plaid_client.py',
                 'time_estimation/ensemble.py'):
        assert (remote / name).is_file(), name
    for name in ('data', 'cache', 'results', 'logs', 'reports', 'performance'):
        assert (remote / name / 'preserve.txt').read_text() == 'server runtime sentinel'
    assert (remote / 'static' / 'asset.css').exists() == with_static
    calls = [json.loads(line) for line in commands.read_text().splitlines()]
    assert calls[-1]['command'] == 'ssh'
    assert calls[-1]['args'][-1].startswith('touch ')
    wsgi_setup = next(call['stdin'] for call in calls if call['stdin'])
    subprocess.run(['bash', '-n'], input=wsgi_setup, text=True, check=True)
    wsgi_source = wsgi_setup.split("<<'WSGI'\n", 1)[1].split('\nWSGI', 1)[0]
    compile(wsgi_source, '<deployed wsgi>', 'exec')
    # Execute the remote setup against a temporary WSGI file, with no SSH access.
    wsgi_file = tmp_path / 'wsgi.py'
    wsgi_file.write_text('# existing server configuration\n')
    local_setup = wsgi_setup.replace('/var/www/ferrous77_pythonanywhere_com_wsgi.py', str(wsgi_file))
    subprocess.run(['bash'], input=local_setup, text=True, check=True)
    assert wsgi_file.read_text().strip() == wsgi_source.strip()
    assert next(tmp_path.glob('wsgi.py.backup.*')).read_text() == '# existing server configuration\n'


def test_failed_upload_stops_before_wsgi_changes(deployment_checkout, isolated_remote, monkeypatch):
    _, commands = isolated_remote
    monkeypatch.setenv('DEPLOY_TEST_FAIL', '1')
    result = subprocess.run(['bash', str(deployment_checkout / 'deploy_clean.sh')],
                            capture_output=True, text=True)
    assert result.returncode == 23
    calls = [json.loads(line) for line in commands.read_text().splitlines()]
    assert [call['command'] for call in calls] == ['rsync']


@pytest.mark.parametrize('with_static', [False, True])
def test_offline_package_contains_code_without_runtime_data(deployment_checkout, tmp_path, with_static):
    if with_static:
        (deployment_checkout / 'static').mkdir()
        (deployment_checkout / 'static' / 'asset.css').write_text('/* asset sentinel */')
    subprocess.run(['bash', str(deployment_checkout / 'scripts/deploy_to_pythonanywhere.sh')],
                   cwd=tmp_path, check=True, capture_output=True, text=True)
    with tarfile.open(deployment_checkout / 'stocks-app.tar.gz') as archive:
        names = {member.name.removeprefix('./') for member in archive.getmembers()}
        for name in (*ROOT_FILES, 'pythonanywhere_daily_hook.py',
                     'performance/prediction_tracker.py', 'performance/config.py',
                     'alerts/alert_engine.py', 'plaid_integration/plaid_client.py',
                     'time_estimation/ensemble.py'):
            assert name in names
        assert not any(name.endswith('preserve.txt') for name in names)
        assert not any(name.split('/')[0] in {'cache', 'data', 'results', 'logs', 'reports'}
                       for name in names)
        installer = archive.extractfile('./deploy_server.sh').read().decode()
        staging = tmp_path / 'staging'
        archive.extractall(staging, filter='data')
    subprocess.run(['bash', '-n'], input=installer, text=True, check=True)
    assert 'find /home' not in installer
    assert 'rm -' not in installer
    target = tmp_path / 'server'
    (target / 'performance').mkdir(parents=True)
    (target / 'performance' / 'preserve.txt').write_text('server runtime sentinel')
    (target / 'unrelated').mkdir()
    (target / 'unrelated' / 'app.py').write_text('# unrelated application\n')
    local_installer = staging / 'deploy_server.sh'
    local_installer.write_text(installer.replace('/home/ferrous77', str(target)))
    subprocess.run(['bash', str(local_installer)], cwd=tmp_path, check=True,
                   capture_output=True, text=True)
    assert (target / 'performance' / 'preserve.txt').read_text() == 'server runtime sentinel'
    assert (target / 'unrelated' / 'app.py').read_text() == '# unrelated application\n'
    assert (target / 'pythonanywhere_daily_hook.py').is_file()
    assert (target / 'performance' / 'prediction_tracker.py').is_file()
    assert (target / 'static' / 'asset.css').exists() == with_static
