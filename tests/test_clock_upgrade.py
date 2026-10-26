import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from server import personal_store, store, signal_engine

class ClockUpgradeTests(unittest.TestCase):
    def test_corrected_key_never_republishes_legacy_owner_setup(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(personal_store,'DB_PATH',Path(folder)/'test.db'):
            old='GOLD|MOMENTUM_SCALP|BUY|2026-10-26 10:25:00+00:00'
            signal=NS(strategy_id='MOMENTUM_SCALP',direction='BUY',setup_time='2026-10-26 08:25:00+00:00')
            new=signal_engine._signal_key('GOLD',signal)
            self.assertEqual(signal_engine._legacy_signal_key('GOLD',signal,7200),old)
            self.assertTrue(personal_store.publish_signal(old,{}))
            self.assertFalse(personal_store.publish_signal(new,{},legacy_key=old))
            with personal_store.connection() as con:
                self.assertEqual(con.execute('SELECT count(*) FROM owner_signals').fetchone()[0],1)
    def test_corrected_client_key_does_not_duplicate_already_executed_setup(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(store,'DB_PATH',Path(folder)/'test.db'):
            connections=[]
            real_connect=store.connect
            def tracked_connect():
                con=real_connect()
                connections.append(con)
                return con
            try:
                with patch.object(store,'connect',side_effect=tracked_connect):
                    client,_=store.create_client('Clock test')
                    self.assertTrue(store.enqueue_instruction(client.id,'old','{}'))
                    row=store.next_instruction(client.id)
                    store.acknowledge_instruction(client.id,row['id'],'EXECUTED','ticket=1')
                    self.assertFalse(store.enqueue_instruction(client.id,'new','{}',legacy_key='old'))
                    self.assertIsNone(store.next_instruction(client.id))
                    self.assertTrue(store.enqueue_instruction(client.id,'fresh','{}',legacy_key='unseen'))
            finally:
                for con in connections:con.close()

if __name__=='__main__':unittest.main()
