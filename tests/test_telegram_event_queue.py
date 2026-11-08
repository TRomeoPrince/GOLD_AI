import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock,patch
from server import personal_store,telegram_notifications as owner
from server import client_notifications as client
from server import telegram_delivery as delivery


class TypedTelegramEventTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.database=Path(self.temp.name)/'events.db'
        self.env=patch.dict(os.environ,{'GOLD_AI_OWNER_TELEGRAM_ENABLED':'true','GOLD_AI_OWNER_TELEGRAM_BOT_TOKEN':'123456:'+'A'*35,'GOLD_AI_OWNER_TELEGRAM_CHAT_ID':'111'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_personal_execution_and_later_open_snapshot_share_one_entry_alert(self):
        details={'ticket':'123','symbol':'XAUUSD','direction':'SELL','entry':4160.31,'currency':'USC','state':'OPEN'}
        with patch.object(personal_store,'DB_PATH',self.database),patch('server.pnl_cards.render_trade_card') as render:
            personal_store.claim_signal('Broker|12','signal')
            personal_store.finish_signal('Broker|12','signal','EXECUTED','ticket=123',details=details)
            self.assertFalse(client.enqueue_trade_event(None,{**details,'account_key':'Broker|12'},event_key='personal-trade:Broker|12:OPEN:123',database=self.database))
            render.assert_not_called()
        with owner._connection(self.database) as con:
            rows=con.execute('SELECT * FROM owner_telegram_outbox').fetchall()
        self.assertEqual(len(rows),1)
        event=json.loads(rows[0]['event_json'])
        self.assertEqual(event['kind'],'NEW_TRADE')
        self.assertEqual(event['trade']['currency'],'USC')

    def test_schema_upgrade_preserves_legacy_queued_message(self):
        with closing(sqlite3.connect(self.database)) as con,con:
            con.execute('CREATE TABLE owner_telegram_outbox(event_key TEXT PRIMARY KEY,message TEXT NOT NULL,chat_id INTEGER NOT NULL,token_fingerprint TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,state TEXT NOT NULL DEFAULT \'PENDING\',attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,claimed_at REAL,claim_id TEXT,message_id INTEGER,last_error TEXT NOT NULL DEFAULT \'\')')
            con.execute("INSERT INTO owner_telegram_outbox(event_key,message,chat_id,token_fingerprint,created,updated) VALUES('old','Old alert',111,'fingerprint',1,1)")
        with owner._connection(self.database) as con:
            row=dict(con.execute('SELECT * FROM owner_telegram_outbox').fetchone())
        bot=Mock()
        delivery.send_queued(bot,row,database=self.database)
        bot.send_message.assert_called_once_with(111,'Old alert')
        self.assertEqual((row['event_json'],row['state']),('','PENDING'))

    def test_sender_renders_current_style_at_delivery_not_in_trading_worker(self):
        event={'kind':'NEW_TRADE','trade':{'ticket':'1','currency':'USC'}}
        self.assertTrue(owner.enqueue_owner_event('typed','stored fallback',database=self.database,event=event))
        with owner._connection(self.database) as con:
            row=dict(con.execute('SELECT * FROM owner_telegram_outbox').fetchone())
        with patch('server.workspace_settings.load_settings',return_value={'display_timezone':'UTC'}),patch('server.telegram_presentation.format_new_trade',return_value='<b>NEW STYLE</b>') as fmt:
            bot=Mock()
            delivery.send_queued(bot,row,database=self.database)
        fmt.assert_called_once_with(event['trade'],display_timezone='UTC')
        bot.send_message.assert_called_once_with(111,'<b>NEW STYLE</b>',parse_mode='HTML')

    def test_stop_update_card_is_sent_with_formatted_caption(self):
        row={'chat_id':111,'event_json':json.dumps({'kind':'SL_UPDATED','trade':{'old_sl':10,'new_sl':11}})}
        with patch('server.workspace_settings.load_settings',return_value={'display_timezone':'UTC'}),patch('server.telegram_presentation.format_stop_update',return_value='SL 10 → 11'),patch('server.pnl_cards.render_stop_update_card',return_value='preview.png'):
            bot=Mock()
            delivery.send_queued(bot,row,database=self.database)
        bot.send_photo.assert_called_once_with(111,'preview.png','SL 10 → 11',parse_mode='HTML')

    def test_renderer_failure_preserves_confirmed_text_and_sends_once(self):
        row={'chat_id':111,'event_json':json.dumps({'kind':'SL_UPDATED','trade':{'old_sl':10,'new_sl':11}})}
        with patch('server.workspace_settings.load_settings',return_value={'display_timezone':'UTC'}),patch('server.telegram_presentation.format_stop_update',return_value='SL 10 → 11'),patch('server.pnl_cards.render_stop_update_card',side_effect=FileNotFoundError('private path')):
            bot=Mock()
            delivery.send_queued(bot,row,database=self.database)
        bot.send_message.assert_called_once_with(111,'SL 10 → 11',parse_mode='HTML')
        bot.send_photo.assert_not_called()

    def test_runtime_alert_does_not_depend_on_workspace_timezone(self):
        row={'chat_id':111,'event_json':json.dumps({'kind':'RUNTIME','state':'READY','message':'Ready'})}
        with patch('server.workspace_settings.load_settings',side_effect=ValueError('invalid settings')):
            bot=Mock()
            delivery.send_queued(bot,row,database=self.database)
        bot.send_message.assert_called_once()


if __name__=='__main__':
    unittest.main()
