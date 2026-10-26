import os
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from server.admin_launcher import Services

class LauncherTests(unittest.TestCase):
    def test_child_pipe_shutdown_and_log(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'server').mkdir()
            env = {'PYTHONPATH': str(Path.cwd()), 'GOLD_AI_HOME': folder,
                   'GOLD_AI_DB_PATH': str(root / 'server' / 'test.db')}
            with patch.dict(os.environ, env):
                services = Services(root)
                try:
                    services.start(('probe',))
                    p = services.processes['probe']
                    services.start(('probe',))
                    self.assertIs(p, services.processes['probe'])
                    for _ in range(100):
                        if 'worker ready' in (root / 'logs' / 'probe.log').read_text():
                            break
                        time.sleep(.05)
                    self.assertIn('worker ready', (root / 'logs' / 'probe.log').read_text())
                finally:
                    services.stop()
                self.assertEqual(p.returncode, 0)

    def test_occupied_port_does_not_start_any_services(self):
        with tempfile.TemporaryDirectory() as folder, socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1',8765))
            except OSError:
                pass  # An existing listener also verifies the conflict path.
            services=Services(Path(folder))
            try:
                services.start()
                self.assertFalse(services.processes)
                self.assertIn('occupied', services.errors['stack'])
            finally:
                services.stop()

    def test_retry_with_owned_api_does_not_probe_its_port(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            services=Services(Path(folder))
            api=Mock()
            api.poll.return_value=None
            services.processes['api']=api
            try:
                with patch('server.admin_launcher.socket.socket') as sock:
                    services.start(('api',))
                    sock.assert_not_called()
            finally:
                services.processes.clear()
                services.stop()

    def test_personal_start_from_script_entrypoint(self):
        import runpy
        from unittest.mock import Mock
        module=runpy.run_path(str(Path(__file__).resolve().parents[1]/'server/admin_launcher.py'),run_name='frozen_entrypoint_test')
        services=object.__new__(module['Services'])
        services.start=Mock()
        with patch('server.personal_store.load_settings',return_value={}):
            services.start_personal()
        services.start.assert_called_once_with(('signal_engine','personal'))

    def test_missing_token_visible(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN':''}):
            services=Services(Path(folder))
            try:
                services.start(('telegram',))
                self.assertIn('Not configured',services.status())
                self.assertFalse(services.processes)
            finally:
                services.stop()

if __name__=='__main__':
    unittest.main()
