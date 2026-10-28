"""Admin-launched hosted execution shares the hidden child lifecycle."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from server import hosted_manager as manager


class HostedSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.old=manager._supervisor
        self.temp=tempfile.TemporaryDirectory()
        self.terminal=Path(self.temp.name)/'simulated-terminal.exe'
        self.terminal.touch()
        self.record={'client_id':12,'terminal_path':str(self.terminal),'worker_pid':None,'status':'PROVISIONED'}
        self.process=Mock(pid=1234)
        self.process.poll.return_value=None
        self.services=Mock(processes={},errors={})
        self.services.start.side_effect=lambda names:self.services.processes.update({names[0]:self.process})
        manager.configure_supervisor(self.services)

    def tearDown(self):
        manager.configure_supervisor(self.old)
        self.temp.cleanup()

    def test_admin_hosted_start_uses_supervised_hidden_service_not_separate_python(self):
        with patch.object(manager,'hosted_account_for_client',return_value=self.record),patch.object(manager,'set_hosted_runtime'),patch('time.sleep'),patch.object(manager.subprocess,'Popen') as spawn:
            self.assertEqual(manager.start_worker(12),1234)
        self.services.start.assert_called_once_with(('hosted_12',))
        spawn.assert_not_called()

    def test_existing_owned_worker_is_reused_without_second_start(self):
        self.services.processes['hosted_12']=self.process
        with patch.object(manager,'hosted_account_for_client',return_value=self.record):
            self.assertEqual(manager.start_worker(12),1234)
        self.services.start.assert_not_called()

    def test_supervised_stop_is_cooperative_and_does_not_kill_mt5(self):
        self.services.processes['hosted_12']=self.process
        with patch.object(manager,'hosted_account_for_client',return_value={**self.record,'status':'ACTIVE','worker_pid':1234}),patch.object(manager,'set_hosted_runtime'),patch.object(manager,'set_hosted_account_status'),patch.object(manager,'_stop_terminal_for_record') as terminal,patch.object(manager.subprocess,'run') as command:
            manager.stop_worker(12)
        self.services.stop_named.assert_called_once_with(('hosted_12',))
        terminal.assert_not_called()
        command.assert_not_called()

    def test_unowned_legacy_worker_is_not_attached_or_killed(self):
        with patch.object(manager,'hosted_account_for_client',return_value={**self.record,'worker_pid':999}),patch.object(manager,'_pid_alive',return_value=True):
            with self.assertRaisesRegex(RuntimeError,'older independently'):
                manager.start_worker(12)
        self.services.start.assert_not_called()


if __name__=='__main__':
    unittest.main()
