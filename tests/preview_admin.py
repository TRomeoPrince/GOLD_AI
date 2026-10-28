"""Isolated visual review window. Never starts services, network or MT5."""
import os
from pathlib import Path
import tempfile
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

with tempfile.TemporaryDirectory(prefix='azt-ui-preview-') as folder:
    root=Path(folder)
    (root/'server').mkdir()
    (root/'logs').mkdir()
    os.environ.update(GOLD_AI_DB_PATH=str(root/'server/test.db'),GOLD_AI_STATE_DIR=str(root/'server'),GOLD_AI_OWNER_TELEGRAM_ENABLED='false',GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN='')
    from server.admin_gui import GoldAIAdmin
    app=GoldAIAdmin(None)
    def review():
        app.state('normal')
        app.geometry('1280x800')
        app.title('AZT Admin • ISOLATED UI PREVIEW')
        app.status.set('ISOLATED UI PREVIEW — no network, services or trading account enabled.')
    app.after(150,review)
    app.after(300000,app.close_app)
    app.mainloop()
