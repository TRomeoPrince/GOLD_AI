"""Isolated frozen-EXE integration test; no trading or Telegram network requests."""
import os
import json
import shutil
import socket
import subprocess
import tempfile
import sys
import sqlite3
import time
import urllib.request
from pathlib import Path

exe=Path(os.getenv('GOLD_AI_TEST_EXE', 'dist_azt/AZT_Admin.exe')).resolve()
command=[sys.executable,'-m','server.admin_launcher'] if '--source' in sys.argv else [str(exe)]
standalone = '--standalone' in sys.argv
if standalone and '--source' in sys.argv:
    raise SystemExit('Standalone smoke requires the packaged executable.')
with tempfile.TemporaryDirectory(prefix='gold-admin-smoke-') as folder:
    root=Path(folder)
    launch_dir = None
    if standalone:
        launch_dir = root / 'Downloads'
        launch_dir.mkdir()
        command = [str(shutil.copy2(exe, launch_dir / exe.name))]
        local_data = root / 'LocalAppData'
        root = local_data / 'GOLD_AI'
    (root/'server').mkdir(parents=True)
    database = root / 'server' / ('gold_ai_server.db' if standalone else 'test.db')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        port=sock.getsockname()[1]
    env={**os.environ,'PYTHONPATH':str(Path.cwd()),'GOLD_AI_HOME':str(root),'GOLD_AI_API_PORT':str(port),
         'GOLD_AI_DB_PATH':str(database),'GOLD_AI_STATE_DIR':str(root/'server'),
         'GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN':'','GOLD_AI_MARKETS':'',
         'GOLD_AI_PROJECT_ROOT':folder,'AZT_TELEGRAM_SOURCE_ROOT':str(Path.cwd()),'AZT_EXTERNAL_TELEGRAM':'true',
         'GOLD_AI_OWNER_TELEGRAM_ENABLED':'false','GOLD_AI_TEST_DIAGNOSTICS':'0'}
    subprocess.run([sys.executable, '-c', "from server.store import create_client,set_client_risk,set_subscription; c,_=create_client('Smoke Client'); set_client_risk(c.name,0.5,20,4); set_subscription(c.id,plan_code='STARTER',status='ACTIVE',starts_utc='2026-01-01T00:00:00+00:00',expires_utc='2099-01-01T00:00:00+00:00')"], env=env,check=True)
    def snapshot():
        with sqlite3.connect(database) as con:
            result=(con.execute('SELECT * FROM clients').fetchall(), con.execute('SELECT * FROM subscriptions').fetchall())
        con.close()
        return result
    before=snapshot()
    if standalone:
        for key in ('GOLD_AI_HOME', 'GOLD_AI_DB_PATH', 'GOLD_AI_STATE_DIR', 'GOLD_AI_PROJECT_ROOT',
                    'AZT_TELEGRAM_SOURCE_ROOT', 'AZT_EXTERNAL_TELEGRAM', 'PYTHONPATH'):
            env.pop(key, None)
        env.update(LOCALAPPDATA=str(local_data), USERPROFILE=folder)
    # Keep the engine alive but unable to scan any markets.
    p=subprocess.Popen([*command,'--smoke-test'],env=env,cwd=launch_dir)
    healthy=False
    deadline=time.monotonic()+60
    while p.poll() is None and time.monotonic()<deadline:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=.5) as r:
                healthy = healthy or b'GOLD_AI Owner Server' in r.read()
        except Exception:
            pass
        time.sleep(.2)
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True)
        p.wait(timeout=10)
    print('GUI exit:',p.returncode,'API healthy:',healthy)
    for log in sorted((root/'logs').glob('*.log')):
        print(log.name, log.read_text(encoding='utf-8')[-1800:])
    assert (root/'logs/signal_engine.log').read_text(encoding='utf-8').count('GOLD_AI OWNER SIGNAL ENGINE') == 2, 'Trading Start/Stop/Start failed'
    assert (root/'logs/maintenance.log').read_text(encoding='utf-8').count('Starting background service: maintenance') == 2, 'External Telegram reload failed'
    assert p.returncode==0 and healthy
    notification_status=json.loads((root/'logs/notifications_status.json').read_text(encoding='utf-8'))
    assert notification_status['state']=='NOT_CONFIGURED', 'Isolated owner-alert sender failed to start safely'
    print('Owner-alert module loaded; sending disabled for smoke test')
    assert snapshot()==before, 'Client or subscription configuration changed'
    if standalone:
        assert not (launch_dir / 'server').exists(), 'Standalone launch wrote beside downloaded EXE'
        print('Standalone launch reused isolated AppData database and ran bundled workers')
    print('Client/risk/subscription preserved')
    assert not (root/'logs/launcher.log').exists(), 'Forced shutdown occurred'
    try:
        urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=.5)
    except Exception:
        print('API stopped cleanly')
    else:
        raise AssertionError('API survived Admin shutdown')
