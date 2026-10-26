"""Frozen worker failure path; no configured account and no MT5 connection."""
import json
import os
import subprocess
import tempfile
from pathlib import Path
exe=Path(os.getenv('GOLD_AI_TEST_EXE','dist_personal/GOLD_AI_Admin.exe')).resolve()
with tempfile.TemporaryDirectory(prefix='gold-personal-smoke-') as folder:
    root=Path(folder)
    (root/'server').mkdir()
    env={**os.environ,'GOLD_AI_HOME':folder,'GOLD_AI_STATE_DIR':str(root/'server'),'GOLD_AI_DB_PATH':str(root/'server/test.db')}
    process=subprocess.run([str(exe),'--service','personal'],env=env,stdin=subprocess.DEVNULL,timeout=30)
    status=json.loads((root/'logs/personal_status.json').read_text())
    assert process.returncode==1 and status['state']=='ERROR',status
    assert 'personal_account.json' in status['message']
    print('Frozen personal worker rejects missing settings without connecting MT5 or placing orders')
