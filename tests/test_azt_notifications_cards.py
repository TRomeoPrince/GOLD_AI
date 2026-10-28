import hashlib
import gc
from contextlib import closing
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from server import store,client_notifications as delivery,client_telegram as telegram,pnl_cards,workspace_settings

TOKEN='123456:'+('A'*35)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.db=self.root/'test.db'
        self.database=patch.object(store,'DB_PATH',self.db)
        self.database.start()
        self.environment=patch.dict(os.environ,{'GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN':TOKEN,'GOLD_AI_STATE_DIR':str(self.root)})
        self.environment.start()
        self.client,_=store.create_client('Simulation')
        with closing(store.connect()) as con, con:
            con.execute('UPDATE clients SET telegram_chat_id=123 WHERE id=?',(self.client.id,))

    def tearDown(self):
        self.environment.stop()
        self.database.stop()
        gc.collect()
        self.temp.cleanup()

    def test_optional_copy_is_durable_deduplicated_and_never_sends_during_enqueue(self):
        with patch.object(telegram,'ClientTelegramBot') as network:
            self.assertTrue(delivery.enqueue_client_message(self.client.id,'Message',event_key='a',database=self.db))
            self.assertFalse(delivery.enqueue_client_message(self.client.id,'Changed',event_key='a',database=self.db))
            network.assert_not_called()
        with delivery.connection(self.db) as con:
            row=dict(con.execute('SELECT * FROM azt_telegram_delivery').fetchone())
        self.assertNotIn(TOKEN,str(row))
        self.assertEqual(row['state'],'PENDING')

    def test_success_is_not_resent_and_retry_cannot_reset_sent(self):
        delivery.enqueue_client_message(self.client.id,'Message',database=self.db)
        bot=Mock()
        bot.send_message.return_value=42
        with patch.object(telegram,'ClientTelegramBot',return_value=bot):
            self.assertTrue(delivery.process_one(self.db))
            self.assertFalse(delivery.process_one(self.db))
        bot.send_message.assert_called_once_with(123,'Message')
        row=delivery.delivery_rows(self.db)[0]
        self.assertEqual(row['state'],'SENT')
        self.assertIn('preserved',delivery.retry_delivery(row,self.db))

    def test_destination_change_holds_private_copy(self):
        delivery.enqueue_client_message(self.client.id,'Private',database=self.db)
        with closing(store.connect()) as con, con:
            con.execute('UPDATE clients SET telegram_chat_id=999 WHERE id=?',(self.client.id,))
        with patch.object(telegram,'ClientTelegramBot') as network:
            self.assertFalse(delivery.process_one(self.db))
            network.assert_not_called()
        self.assertEqual(delivery.delivery_rows(self.db)[0]['state'],'HELD')
        with closing(store.connect()) as con, con:
            con.execute('UPDATE clients SET telegram_chat_id=123 WHERE id=?',(self.client.id,))
        bot=Mock()
        bot.send_message.return_value=99
        with patch.object(telegram,'ClientTelegramBot',return_value=bot):
            self.assertTrue(delivery.process_one(self.db))
        bot.send_message.assert_called_once_with(123,'Private')

    def test_network_failure_queues_retry_without_exposing_token(self):
        delivery.enqueue_client_message(self.client.id,'Message',database=self.db)
        bot=Mock()
        bot.send_message.side_effect=TimeoutError('secret '+TOKEN)
        with patch.object(telegram,'ClientTelegramBot',return_value=bot),self.assertLogs(level='WARNING') as logs:
            delivery.process_one(self.db)
        row=delivery.delivery_rows(self.db)[0]
        self.assertEqual((row['state'],row['attempts']),('RETRY',1))
        self.assertNotIn(TOKEN,str(row)+str(logs.output))

    def test_unlinked_client_still_receives_in_app_message(self):
        from server import azt_store
        with closing(store.connect()) as con, con:
            con.execute('UPDATE clients SET telegram_chat_id=NULL WHERE id=?',(self.client.id,))
        result=azt_store.send_message(self.client.id,'Title','Inside AZT',also_telegram=True)
        self.assertFalse(result['telegram_queued'])
        messages=azt_store.messages(self.client.id)
        self.assertEqual(messages[0]['body'],'Inside AZT')
        azt_store.mark_message_read(self.client.id,messages[0]['id'])
        self.assertEqual(azt_store.messages(self.client.id,True),[])


class CardTests(unittest.TestCase):
    def test_template_copies_render_actual_values_without_changing_originals(self):
        from PIL import Image
        templates=[pnl_cards.asset_path('IMAGES/PnL_CARDS/'+name+'.jpg') for name in ('PROFIT','LOSS')]
        hashes=[hashlib.sha256(p.read_bytes()).digest() for p in templates]
        with tempfile.TemporaryDirectory() as folder:
            for index,pnl in enumerate((42.5,-10.4)):
                trade=dict(ticket='501',symbol='XAUUSD.m',direction='BUY',state='CLOSED',pnl=pnl,currency='EUR',entry=2000,exit=2001,closed_utc='2026-10-27T00:30:00+00:00')
                output=pnl_cards.render_trade_card(trade,display_timezone='America/New_York',output=Path(folder)/f'{index}.png')
                with Image.open(output) as image:
                    self.assertEqual(image.format,'PNG')
                    self.assertGreater(image.width,900)
            with self.assertRaises(ValueError):
                pnl_cards.render_trade_card(trade,output=templates[1])
        self.assertEqual(hashes,[hashlib.sha256(p.read_bytes()).digest() for p in templates])

    def test_timezone_requires_aware_timestamp_and_converts_across_date_boundary(self):
        self.assertIn('26 Oct 2026',pnl_cards._display_time('2026-10-27T00:30:00+00:00','America/New_York'))
        with self.assertRaises(ValueError):
            pnl_cards._display_time('2026-10-27T00:30:00','UTC')

    def test_mixed_currency_journal_does_not_publish_a_zero_aggregate(self):
        with patch.object(pnl_cards,'_render',return_value=Path('mock.png')) as render:
            pnl_cards.render_journal_card({'pnl':None,'pnl_by_currency':{'USD':10,'EUR':-5},'date':'2026-10-27'})
        self.assertEqual(render.call_args.kwargs['headline'],'Multiple currencies')

    def test_settings_validate_timezone_retry_and_reminders(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GOLD_AI_STATE_DIR':folder}):
            workspace_settings.save_settings(display_timezone='Africa/Kampala',retry_interval=5,retry_cap=30,reminder_days=[3,1,0])
            self.assertEqual(workspace_settings.load_settings()['display_timezone'],'Africa/Kampala')
            with self.assertRaises(ValueError):
                workspace_settings.save_settings(retry_cap=1)


class CommandCardTests(unittest.TestCase):
    def test_subscription_reports_effective_access_and_user_timezone(self):
        from types import SimpleNamespace
        from server import azt_store
        bot=telegram.ClientTelegramBot(TOKEN)
        summary={'effective_status':'EXPIRED','subscription':{'plan_code':'STARTER','expires_utc':'2026-10-27T00:00:00+00:00'}}
        with patch.object(telegram,'client_by_telegram_chat',return_value=SimpleNamespace(id=12)),patch.object(azt_store,'subscription_summary',return_value=summary),patch.object(azt_store,'preferences',return_value={'display_timezone':'Africa/Kampala'}),patch.object(bot,'send_message') as send,patch.object(bot,'_record_command'):
            bot._handle({'chat':{'id':34},'text':'/subscription'})
        self.assertIn('EXPIRED',send.call_args.args[1])
        self.assertIn('03:00:00+03:00',send.call_args.args[1])
    def test_linked_positions_are_scoped_to_the_client(self):
        from types import SimpleNamespace
        from server import trade_telemetry,azt_store
        bot=telegram.ClientTelegramBot(TOKEN)
        with patch.object(telegram,'client_by_telegram_chat',return_value=SimpleNamespace(id=12)),patch.object(azt_store,'preferences',return_value={'display_timezone':'UTC'}),patch.object(trade_telemetry,'list_trades',return_value=[]) as listing,patch.object(bot,'send_message') as send,patch.object(bot,'_record_command'):
            bot._handle({'chat':{'id':34},'text':'/positions'})
        listing.assert_called_once_with(12,state='OPEN')
        send.assert_called_once()

    def test_unlinked_request_cannot_read_trade_history(self):
        from server import trade_telemetry
        bot=telegram.ClientTelegramBot(TOKEN)
        with patch.dict(os.environ,{'TELEGRAM_ADMIN_ID':'','GOLD_AI_OWNER_TELEGRAM_CHAT_ID':''}),patch.object(telegram,'client_by_telegram_chat',return_value=None),patch.object(trade_telemetry,'list_trades') as listing,patch.object(bot,'send_message') as send,patch.object(bot,'_record_command'):
            bot._handle({'chat':{'id':34},'text':'/positions'})
        listing.assert_not_called()
        self.assertIn('/link',send.call_args.args[1])


if __name__=='__main__':
    unittest.main()
