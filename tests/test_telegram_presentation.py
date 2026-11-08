"""Telegram views use fixtures only: no network, broker or persistent store."""
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
import os
import unittest
from unittest.mock import patch

from server import client_telegram as telegram
from server import telegram_presentation as views

NOW=datetime(2026,10,28,0,30,tzinfo=timezone.utc)


def position(ticket='123', **changes):
    row=dict(ticket=ticket,symbol='XAUUSD.c',direction='SELL',strategy='PULLBACK',
             volume=.03,entry=4062.22,entry_basis='ACTUAL_FILL',current_price=4061.91,
             sl=4067.34,tp=4054.81,sl_pnl=-15.36,tp_pnl=22.23,pnl=.93,
             currency='USC',risk_pct=1.63,risk_cash=15.36,portfolio_after_pct=5.117,
             max_open_risk_pct=40,account_key='Broker-Live3|1234',
             observed_utc=NOW.isoformat(),executed_utc=NOW.isoformat(),
             closed_utc=NOW.isoformat(),result='WIN',exit=4054.81)
    row.update(changes)
    return row


class BalancedHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack=[]
    def handle_starttag(self,tag,attrs):
        if tag not in {'b','i','code'}:
            raise AssertionError('Unexpected HTML '+tag)
        self.stack.append(tag)
    def handle_endtag(self,tag):
        if not self.stack or self.stack.pop()!=tag:
            raise AssertionError('Unbalanced HTML '+tag)


class PresentationTests(unittest.TestCase):
    def bounded(self,pages):
        for page in pages:
            self.assertLessEqual(len(page.encode('utf-16-le'))//2,4096)
            parser=BalancedHTML()
            parser.feed(page)
            self.assertEqual(parser.stack,[])

    def test_new_trade_contains_prices_risk_currency_and_human_time(self):
        text=views.format_new_trade(position(currency='USD'),'Africa/Kampala')
        for value in ('AZT — NEW TRADE','XAUUSD.c','Pullback','4,062.220','−$15.36',
                      '+$22.23','1.630%','5.117% / 40.000%','03:30:00 EAT','123'):
            self.assertIn(value,text)
        self.assertNotIn('GOLD|',text)
        self.assertNotIn('2026-10-28T',text)
        self.bounded([text])

    def test_cent_account_never_becomes_dollars(self):
        text=views.format_new_trade(position())
        self.assertIn('15.36 USC',text)
        self.assertNotIn('$',text)

    def test_requested_price_and_unset_stops_are_honest(self):
        text=views.format_new_trade(position(entry_basis='REQUESTED',sl=0,tp=0,sl_pnl=None,tp_pnl=None,risk_cash=None))
        self.assertIn('Requested entry',text)
        self.assertEqual(text.count('Not set'),2)
        self.assertGreaterEqual(text.count('Not available'),3)

    def test_untrusted_text_is_escaped_and_secrets_are_redacted(self):
        text=views.format_new_trade(position(symbol='<b>BAD</b>',strategy='A&B',account_key='password=secret123 <script>'))
        self.assertIn('&lt;b&gt;BAD&lt;/b&gt;',text)
        self.assertIn('A&amp;B',text)
        self.assertNotIn('secret123',text)
        self.assertNotIn('<script>',text)
        self.bounded([text])

    def test_positions_mark_old_missing_and_future_snapshots(self):
        for observed in ('2026-10-28T00:20:00+00:00','2026-10-28T00:32:00+00:00',None):
            with self.subTest(observed=observed):
                self.assertIn('STALE SNAPSHOT',views.format_positions([position(observed_utc=observed)],now=NOW)[0])
        self.assertNotIn('STALE SNAPSHOT',views.format_positions([position()],now=NOW)[0])

    def test_positions_keep_detailed_fields_and_currency_totals(self):
        text=views.format_positions([position(),position('456',currency='USD',pnl=-2)],now=NOW)[0]
        for label in ('Entry','Current','Floating P/L','At all SLs','At all TPs','Ticket','Account','USC','−$2.00'):
            self.assertIn(label,text)
        self.bounded([text])

    def test_incomplete_stop_totals_cannot_publish_a_misleading_sum(self):
        text=views.format_positions([position(),position('456',sl_pnl=None)],now=NOW)[0]
        self.assertIn('At all SLs  <b>Not available (incomplete data)</b>',text)
        self.assertIn('At all TPs  <b>+44.46 USC</b>',text)

    def test_thousand_positions_remain_bounded_and_all_tickets_preserved(self):
        rows=[position(str(900000+i)) for i in range(1000)]
        pages=views.format_positions(rows,now=NOW)
        self.assertEqual(len(pages),500)
        combined='\n'.join(pages)
        for row in rows:
            self.assertIn('<code>'+row['ticket']+'</code>',combined)
        self.bounded(pages)

    def test_long_html_values_and_many_currencies_are_bounded(self):
        rows=[position(str(9000+i),symbol='<'*500,strategy='&'*500,account_key='"'*500,
                       currency='"'*20+str(i)) for i in range(40)]
        self.bounded(views.format_positions(rows,now=NOW))
        report=dict(date='2026-10-28',trades=rows,trades_taken=40,wins=30,losses=10,
                    win_rate=75,pnl_by_currency={r['currency']:1 for r in rows},strategies_used=['&'*500]*40)
        self.bounded(views.format_journal(report))

    def test_journal_keeps_complete_trade_list_and_mixed_currency_results(self):
        rows=[position(str(7000+i),currency='USD' if i%2 else 'USC') for i in range(21)]
        report=dict(date='2026-10-28',trades=rows,trades_taken=21,wins=15,losses=6,
                    win_rate=15/21*100,pnl_by_currency={'USD':10,'USC':-5},risk_used=3,
                    strategies_used=['PULLBACK','SUPPORT_RESISTANCE'])
        pages=views.format_journal(report,'Africa/Kampala')
        combined='\n'.join(pages)
        for row in rows:
            self.assertIn('<code>'+row['ticket']+'</code>',combined)
        for value in ('15 / 6','71.4%','+$10.00','−5.00 USC','Support &amp; Resistance','03:30:00 EAT'):
            self.assertIn(value,combined)
        self.assertNotIn('2026-10-28T',combined)
        self.bounded(pages)

    def test_stop_changes_do_not_invent_a_trailing_actor(self):
        event=position(old_sl=4067.34,new_sl=4064.5,old_sl_pnl=-15.36,new_sl_pnl=-6.84)
        text=views.format_stop_update(event)
        self.assertIn('STOP LOSS UPDATED',text)
        self.assertNotIn('TRAILING',text)
        self.assertIn('4,067.340 → 4,064.500',text)
        self.assertIn('−15.36 USC → <b>−6.84 USC</b>',text)
        self.assertIn('−15.36 USC → <b>−6.84 USC</b>',views.format_stop_update({'kind':'SL_UPDATED','trade':event}))
        self.assertIn('TRAILING SL UPDATED',views.format_stop_update(dict(event,reason='TRAILING')))

    def test_runtime_ready_is_clear_and_other_errors_hide_urls(self):
        text=views.format_runtime_alert('Broker|1234','READY','debug signal key')
        self.assertIn('Ready for fresh signals',text)
        self.assertNotIn('debug signal',text)
        token='123456:'+('A'*35)
        error=views.format_runtime_alert('Broker|1234','ERROR','https://api.telegram.org/bot'+token+' failed token='+token)
        self.assertNotIn(token,error)
        self.assertNotIn('https://',error)
        self.bounded([error])


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.bot=telegram.ClientTelegramBot('fixture-token')
        self.patches=[patch.object(telegram,'client_by_telegram_chat',return_value=SimpleNamespace(id=12)),
                      patch('server.azt_store.preferences',return_value={'display_timezone':'Africa/Kampala'}),
                      patch.object(self.bot,'send_message'),patch.object(self.bot,'send_photo'),
                      patch.object(self.bot,'_record_command')]
        self.mocks=[p.start() for p in self.patches]
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patches)])

    def handle(self,text):
        self.bot._handle({'chat':{'id':34},'text':text})

    def test_positions_second_page_scopes_data_and_sends_full_html_plus_card(self):
        rows=[position(str(100+i)) for i in range(5)]
        with patch('server.trade_telemetry.list_trades',return_value=rows) as listing,patch('server.pnl_cards.render_positions_cards',return_value=[Path('fixture.png')]) as renderer:
            self.handle('/positions 2')
        listing.assert_called_once_with(12,state='OPEN')
        renderer.assert_called_once_with(rows[2:4],display_timezone='Africa/Kampala')
        self.assertEqual(self.mocks[2].call_args.kwargs,{'parse_mode':'HTML'})
        self.assertIn('<code>102</code>',self.mocks[2].call_args.args[1])
        self.mocks[3].assert_called_once()
        self.assertNotIn('Entry',self.mocks[3].call_args.args[2])

    def test_invalid_page_is_friendly_and_does_not_send_a_photo(self):
        with patch('server.trade_telemetry.list_trades',return_value=[]):
            self.handle('/positions 99')
        self.assertIn('Choose a page from 1 to 1',self.mocks[2].call_args.args[1])
        self.mocks[3].assert_not_called()

    def test_positions_still_sends_scoped_text_when_card_cannot_render(self):
        with patch('server.trade_telemetry.list_trades',return_value=[position('501')]) as listing,patch('server.pnl_cards.render_positions_cards',side_effect=FileNotFoundError('private path')),self.assertLogs(level='WARNING') as logs:
            self.handle('/positions')
        listing.assert_called_once_with(12,state='OPEN')
        self.mocks[2].assert_called_once()
        self.assertIn('<code>501</code>',self.mocks[2].call_args.args[1])
        self.mocks[3].assert_not_called()
        self.assertNotIn('private path',str(logs.output))

    def test_journal_date_uses_client_scope_timezone_and_full_text(self):
        report=dict(date='2026-10-27',trades=[position()],trades_taken=1,wins=1,losses=0,win_rate=100,pnl_by_currency={'USC':.93})
        with patch('server.trade_telemetry.daily_journal',return_value=report) as journal,patch('server.pnl_cards.render_journal_card',return_value=Path('fixture.png')):
            self.handle('/journal 2026-10-27')
        journal.assert_called_once_with(12,date='2026-10-27',timezone='Africa/Kampala')
        self.assertIn('Wins / Losses',self.mocks[2].call_args.args[1])
        self.assertEqual(self.mocks[2].call_args.kwargs,{'parse_mode':'HTML'})
        self.mocks[3].assert_called_once()

    def test_invalid_date_does_not_query_journal(self):
        with patch('server.trade_telemetry.daily_journal') as journal:
            self.handle('/journal 2026-02-30')
        journal.assert_not_called()
        self.assertIn('valid local date',self.mocks[2].call_args.args[1])

    def test_rich_photo_failure_is_sticky_without_replaying_command(self):
        self.mocks[3].side_effect=TimeoutError('fixture-token')
        with patch('server.trade_telemetry.list_trades',return_value=[position()]) as listing,patch('server.pnl_cards.render_positions_cards',return_value=[Path('fixture.png')]):
            with self.assertRaises(telegram.TelegramRequestError):
                self.handle('/positions')
        self.assertEqual(listing.call_count,1)
        self.assertEqual(self.mocks[2].call_count,1)
        self.assertIsNotNone(self.bot._last_reply_error)
        self.assertNotIn('fixture-token',self.bot._last_reply_error)


class ConfirmationTests(unittest.TestCase):
    def test_send_requires_positive_integer_confirmation(self):
        bot=telegram.ClientTelegramBot('fixture-token')
        for message_id in (None,0,False,'12'):
            with self.subTest(message_id=message_id),patch.object(bot,'_api',return_value={'ok':True,'result':{'message_id':message_id}}):
                with self.assertRaises(telegram.TelegramRequestError):
                    bot.send_message(34,'Fixture')

    def test_optional_html_mode_is_forwarded_and_oversize_html_is_not_cut(self):
        bot=telegram.ClientTelegramBot('fixture-token')
        with patch.object(bot,'_api',return_value={'ok':True,'result':{'message_id':12}}) as api:
            bot.send_message(34,'<b>Fixture</b>',parse_mode='HTML')
            self.assertEqual(api.call_args.args[1]['parse_mode'],'HTML')
            with self.assertRaises(telegram.TelegramRequestError):
                bot.send_message(34,'<b>'+('x'*4096)+'</b>',parse_mode='HTML')
            self.assertEqual(api.call_count,1)


if __name__=='__main__':
    unittest.main()
