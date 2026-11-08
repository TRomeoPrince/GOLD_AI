import os
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from server.admin_launcher import Services
from server.telegram_admin import request_reload


class TelegramSidecarTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.source=self.root/'source'
        runtime=self.source/'.venv/Scripts/python.exe'
        runtime.parent.mkdir(parents=True)
        runtime.touch()
        self.env=patch.dict(os.environ,{'AZT_TELEGRAM_SOURCE_ROOT':str(self.source),'AZT_EXTERNAL_TELEGRAM':'true','GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN':'test'})
        self.env.start()
        with patch.object(Services,'monitor'):
            self.services=Services(self.root)

    def tearDown(self):
        self.services.processes.clear()
        self.services.stop()
        self.env.stop()
        self.temp.cleanup()

    def test_three_external_roles_hidden_with_private_pipe_and_source_path(self):
        with patch('server.admin_launcher.subprocess.Popen') as popen:
            popen.return_value.poll.return_value=None
            self.services.start(('telegram','notifications','maintenance'))
            self.assertEqual(popen.call_count,3)
            for call in popen.call_args_list:
                self.assertEqual(call.args[0][:3],[str(self.source/'.venv/Scripts/python.exe'),'-m','server.admin_launcher'])
                self.assertEqual(call.kwargs['cwd'],self.source)
                self.assertEqual(call.kwargs['env']['GOLD_AI_HOME'],str(self.root))
                self.assertEqual(call.kwargs['env']['PYTHONPATH'],str(self.source))
                self.assertEqual(call.kwargs['creationflags'],0x08000000)
                self.assertEqual(call.kwargs['stdin'],-1)
            self.services.start(('telegram',))
            self.assertEqual(popen.call_count,3)

    def test_missing_runtime_reported_without_starting_fallback_poller(self):
        (self.source/'.venv/Scripts/python.exe').unlink()
        with patch('server.admin_launcher.subprocess.Popen') as popen:
            self.services.start(('telegram','notifications','maintenance'))
            popen.assert_not_called()
        self.assertEqual(set(self.services.errors),{'telegram','notifications','maintenance'})

    def test_reload_recovers_roles_after_runtime_is_installed(self):
        runtime=self.source/'.venv/Scripts/python.exe'
        runtime.unlink()
        self.services.start(('telegram','notifications','maintenance'))
        runtime.touch()
        request_reload(self.root)
        with patch('server.admin_launcher.subprocess.Popen') as popen:
            self.services._reload_telegram()
            self.assertEqual(popen.call_count,3)
        self.assertFalse(self.services.errors)

    def test_crashed_alert_worker_restarts_after_backoff_but_trading_does_not(self):
        worker = Mock()
        worker.poll.return_value = 1
        self.services.processes.update(telegram=worker, signal_engine=worker)
        self.services.telegram_wanted.add("telegram")
        with patch.object(self.services, "_start") as start:
            with patch("server.admin_launcher.time.monotonic", return_value=10):
                self.services._recover_telegram()
                start.assert_not_called()
            with patch("server.admin_launcher.time.monotonic", return_value=15):
                self.services._recover_telegram()
                start.assert_called_once_with(("telegram",))
            self.services.stop_named(("telegram",))
            with patch("server.admin_launcher.time.monotonic", return_value=100):
                self.services._recover_telegram()
                self.assertEqual(start.call_count, 1)

    def test_status_does_not_treat_a_stale_or_failed_worker_as_ready(self):
        worker = Mock()
        worker.poll.return_value = None
        self.services.processes["telegram"] = worker
        path = self.root / "logs/telegram_status.json"
        path.write_text(json.dumps({"state": "READY", "updated": time.time() - 60}), encoding="utf-8")
        self.assertTrue(self.services.runtime_status("telegram").startswith("STALE"))
        worker.poll.return_value = 1
        self.assertTrue(self.services.runtime_status("telegram").startswith("FAILED"))
        worker.poll.return_value = 0
        self.assertTrue(self.services.runtime_status("telegram").startswith("STOPPED"))

    def test_reload_waits_for_old_roles_and_leaves_trading_processes_alone(self):
        order=[]
        roles=('telegram','notifications','maintenance')
        for name in (*roles,'api','signal_engine','personal','hosted_1'):
            process=Mock()
            process.poll.return_value=None
            process.wait.side_effect=lambda **kw:order.append('wait')
            self.services.processes[name]=process
        request_reload(self.root)
        with patch.object(self.services,'_start',side_effect=lambda names,env:order.append(tuple(names))) as start:
            self.services._reload_telegram()
            self.services._reload_telegram()
            start.assert_called_once_with(roles,None)
        self.assertEqual(order,['wait','wait','wait',roles])
        for name in ('api','signal_engine','personal','hosted_1'):
            self.services.processes[name].stdin.close.assert_not_called()
            self.services.processes[name].wait.assert_not_called()

    def test_shutdown_or_bad_reload_file_never_restarts_workers(self):
        self.services.processes['telegram']=Mock()
        with patch.object(self.services,'start') as start:
            (self.root/'logs/telegram_reload.json').write_text('{broken')
            self.services._reload_telegram()
            self.services.monitor_stop.set()
            request_reload(self.root)
            self.services._reload_telegram()
            start.assert_not_called()


if __name__=='__main__':
    unittest.main()
