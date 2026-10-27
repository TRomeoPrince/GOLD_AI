import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from server import personal_store,personal_worker

class PersonalAlertHookTests(unittest.TestCase):
    def test_committed_result_enqueues_only_its_actual_state(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(personal_store,'DB_PATH',Path(folder)/'test.db'):
            for state in ('EXECUTED','REJECTED','SKIPPED','ERROR_REVIEW'):
                with self.subTest(state=state):
                    key='signal-'+state
                    personal_store.claim_signal('account',key)
                    with patch('server.telegram_notifications.enqueue_owner_event') as queue:
                        personal_store.finish_signal('account',key,state,'ticket=1' if state=='EXECUTED' else 'not executed')
                        queue.assert_called_once()
                        self.assertIn('GOLD_AI PERSONAL '+state,queue.call_args.args[1])
                        self.assertEqual(queue.call_args.kwargs['database'],Path(folder)/'test.db')
                        with personal_store.connection() as con:
                            self.assertEqual(con.execute('SELECT state FROM personal_deliveries WHERE signal_key=?',(key,)).fetchone()[0],state)
    def test_notification_queue_failure_cannot_undo_execution_record(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(personal_store,'DB_PATH',Path(folder)/'test.db'):
            personal_store.claim_signal('account','signal')
            with patch('server.telegram_notifications.enqueue_owner_event',side_effect=OSError('unavailable')),self.assertLogs(level='WARNING'):
                personal_store.finish_signal('account','signal','EXECUTED','ticket=1')
            with personal_store.connection() as con:
                self.assertEqual(con.execute('SELECT state FROM personal_deliveries').fetchone()[0],'EXECUTED')
    def test_missing_execution_row_does_not_send_false_alert(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(personal_store,'DB_PATH',Path(folder)/'test.db'),patch('server.telegram_notifications.enqueue_owner_event') as queue:
            self.assertFalse(personal_store.finish_signal('account','missing','EXECUTED','ticket=1'))
            queue.assert_not_called()
    def test_runtime_alert_queue_failure_cannot_stop_worker(self):
        with patch('server.telegram_notifications.enqueue_owner_event',side_effect=OSError('unavailable')),self.assertLogs(level='WARNING'):
            personal_worker._runtime_alert('key','READY','account','Waiting for signals')

if __name__=='__main__':unittest.main()
