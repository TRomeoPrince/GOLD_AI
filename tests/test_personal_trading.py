import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from server import personal_store as ps
from server import personal_worker as pw
from server import hosted_executor as executor

class PersonalStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.patch=patch.object(ps,'DB_PATH',self.root/'test.db')
        self.patch.start()
    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()
    def test_signals_do_not_require_client_or_subscription(self):
        ps.publish_signal('signal',{'direction':'BUY'})
        self.assertIsNotNone(ps.next_signal(0,0))
        with ps.connection() as con:
            self.assertIsNone(con.execute("SELECT name FROM sqlite_master WHERE name='clients'").fetchone())
    def test_no_backlog_and_durable_per_account_duplicate_prevention(self):
        ps.publish_signal('same',{})
        self.assertIsNone(ps.next_signal(0,time.time()+1))
        self.assertTrue(ps.claim_signal('one','same'))
        self.assertFalse(ps.claim_signal('one','same'))
        ps.finish_signal('one','same','EXECUTED','ticket=1')
        self.assertFalse(ps.claim_signal('one','same'))
        self.assertTrue(ps.claim_signal('two','same'))
        ps.publish_signal('same',{})
        with ps.connection() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM owner_signals').fetchone()[0],1)
    def test_worker_consumes_shared_signal_without_registration(self):
        terminal=self.root/'terminal64.exe'
        terminal.touch()
        settings={'terminal_path':str(terminal),'login':123,'server':'Broker','risk_per_trade_pct':.9,'max_open_risk_pct':40,'max_daily_loss_pct':5}
        stop=threading.Event()
        def get_signal(cursor,since):
            if cursor==0:
                ps.publish_signal('fresh',{'setup_time':datetime.now(timezone.utc).isoformat()})
            return ps.next_signal(cursor,since)
        with patch.dict('os.environ',{'LOCALAPPDATA':str(self.root)}),patch.object(pw,'load_settings',return_value=settings),patch.object(pw,'attach'),patch.object(pw,'mt5') as mt5,patch.object(pw,'verify_account',return_value=NS(login=123,server='Broker',equity=1000)),patch.object(pw,'write_status'),patch.object(pw,'next_signal',side_effect=get_signal),patch.object(pw,'execute_signal',return_value=('EXECUTED','ticket=123')) as execute,patch.object(stop,'wait',side_effect=lambda _:stop.set()):
            pw.run(stop)
            execute.assert_called_once()
            mt5.shutdown.assert_called_once()
        with ps.connection() as con:
            self.assertEqual(con.execute('SELECT state FROM personal_deliveries').fetchone()[0],'EXECUTED')
            self.assertIsNone(con.execute("SELECT name FROM sqlite_master WHERE name='clients'").fetchone())

    def test_settings_validation_and_risk_ceiling(self):
        terminal=self.root/'terminal64.exe'
        terminal.touch()
        config={'terminal_path':str(terminal),'login':123,'server':'Broker'}
        self.assertEqual(ps.validate_settings(config)['risk_per_trade_pct'],.9)
        with self.assertRaises(ValueError):
            ps.validate_settings({**config,'risk_per_trade_pct':2.1})
        with self.assertRaises(ValueError):
            ps.validate_settings({**config,'server':''})

class PersonalGuardTests(unittest.TestCase):
    def setUp(self):
        self.settings={'login':123,'server':'Broker','risk_per_trade_pct':.9,'max_open_risk_pct':40,'max_daily_loss_pct':5}
        self.account=NS(login=123,server='Broker',equity=1000,trade_allowed=True,trade_expert=True)
        self.mt5=Mock()
        self.mt5.account_info.return_value=self.account
        self.mt5.terminal_info.return_value=NS(connected=True,trade_allowed=True,tradeapi_disabled=False)
        self.patches=[patch.object(pw,'mt5',self.mt5),patch.object(pw,'list_clients',return_value=[]),patch.object(pw,'list_hosted_accounts',return_value=[])]
        for p in self.patches:p.start()
        self.stop=threading.Event()
        self.row={'payload':json.dumps({'setup_time':datetime.now(timezone.utc).isoformat(),'direction':'BUY'})}
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
    def test_account_switch_and_stop_block_execution(self):
        self.account.login=999
        with self.assertRaisesRegex(RuntimeError,'account changed'):
            pw.verify_account(self.settings,self.stop)
        self.account.login=123
        self.stop.set()
        with self.assertRaisesRegex(RuntimeError,'stopped'):
            pw.verify_account(self.settings,self.stop)
    def test_duplicate_client_account_is_blocked(self):
        with patch.object(pw,'list_clients',return_value=[NS(mt5_login=123,mt5_server='Broker',status='ACTIVE',name='Existing')]):
            with self.assertRaisesRegex(RuntimeError,'duplicate orders'):
                pw.verify_account(self.settings)
    def test_news_lock_and_stale_signal_never_submit(self):
        with patch.object(pw,'news_lock_enabled',return_value=True),patch.object(pw,'execute_instruction') as execute:
            self.assertEqual(pw.execute_signal(self.row,self.settings,self.stop)[0],'SKIPPED')
            execute.assert_not_called()
        self.row['payload']=json.dumps({'setup_time':'2020-01-01T00:00:00+00:00'})
        with patch.object(pw,'news_lock_enabled',return_value=False),patch.object(pw,'execute_instruction') as execute:
            self.assertEqual(pw.execute_signal(self.row,self.settings,self.stop)[0],'SKIPPED')
            execute.assert_not_called()
    def test_signal_age_limits_unchanged(self):
        from datetime import timedelta
        now=datetime(2026,10,26,8,27,tzinfo=timezone.utc)
        clock=Mock()
        clock.now.return_value=now
        clock.fromisoformat.side_effect=datetime.fromisoformat
        policy={'risk_per_trade_pct':.5,'max_open_risk_pct':20,'max_daily_loss_pct':4,'daily_profit_target_enabled':False,'daily_profit_target_pct':0}
        result=NS(sent=True,ticket=1,message='ok',planned_risk_pct=.5,volume=.01)
        with patch.object(pw,'datetime',clock),patch.object(pw,'news_lock_enabled',return_value=False),patch.object(pw,'effective_risk_policy',return_value=policy),patch.object(pw,'execute_instruction',return_value=result) as execute:
            for delta,expected in ((-120,'EXECUTED'),(-1200,'EXECUTED'),(60,'EXECUTED'),(-1201,'SKIPPED'),(61,'SKIPPED')):
                with self.subTest(seconds_from_now=delta):
                    self.row['payload']=json.dumps({'setup_time':(now+timedelta(seconds=delta)).isoformat(),'direction':'BUY'})
                    execute.reset_mock()
                    self.assertEqual(pw.execute_signal(self.row,self.settings,self.stop)[0],expected)
                    if expected=='SKIPPED':execute.assert_not_called()

    def test_global_policy_and_final_order_guard(self):
        policy={'risk_per_trade_pct':.5,'max_open_risk_pct':20,'max_daily_loss_pct':4,'daily_profit_target_enabled':False,'daily_profit_target_pct':0}
        result=NS(sent=True,ticket=1,message='ok',planned_risk_pct=.5,volume=.01)
        with patch.object(pw,'news_lock_enabled',return_value=False),patch.object(pw,'effective_risk_policy',return_value=policy),patch.object(pw,'execute_instruction',return_value=result) as execute:
            self.assertEqual(pw.execute_signal(self.row,self.settings,self.stop)[0],'EXECUTED')
            self.assertEqual(execute.call_args.args[1:4],(.5,20,4))
            self.assertEqual(execute.call_args.kwargs['max_single_risk_pct'],2)
            self.assertTrue(execute.call_args.kwargs['include_all_positions'])
            guard=execute.call_args.kwargs['before_send']
            self.account.login=999
            with self.assertRaisesRegex(RuntimeError,'account changed'):guard()

class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.mt5=Mock()
        for name, value in (("ORDER_TYPE_BUY",0),("ORDER_TYPE_SELL",1),("ORDER_FILLING_FOK",0),("ORDER_FILLING_IOC",1),("ORDER_FILLING_RETURN",2),("TRADE_ACTION_DEAL",1),("ORDER_TIME_GTC",0),("TRADE_RETCODE_DONE",10009),("TRADE_RETCODE_DONE_PARTIAL",10010)):
            setattr(self.mt5,name,value)
        self.mt5.account_info.return_value=NS(equity=1000,balance=1000)
        self.mt5.terminal_info.return_value=NS(trade_allowed=True)
        self.mt5.history_deals_get.return_value=[]
        self.mt5.symbols_get.return_value=[NS(name='XAUUSD')]
        self.mt5.symbol_info.return_value=NS(visible=True,volume_min=.01,volume_max=100,volume_step=.01,filling_mode=1)
        self.mt5.symbol_info_tick.return_value=NS(ask=2000,bid=1999,time=time.time())
        self.mt5.order_calc_profit.side_effect=lambda typ,symbol,volume,entry,sl:-1000*volume
        self.mt5.positions_get.return_value=[]
        self.mt5.order_check.return_value=NS(retcode=0)
        self.patch=patch.object(executor,'mt5',self.mt5)
        self.patch.start()
        self.clock_patch=patch.object(executor,"tick_utc_epoch",side_effect=lambda api,symbol,tick:tick.time)
        self.clock_patch.start()
        self.payload={'direction':'BUY','symbol_hint':'XAUUSD','stop_loss':1990,'take_profit':2020}
    def tearDown(self):
        self.clock_patch.stop()
        self.patch.stop()
    def execute(self,**kwargs):
        return executor.execute_instruction(self.payload,.9,40,5,max_single_risk_pct=2,strict_history=True,include_all_positions=True,**kwargs)
    def test_minimum_lot_above_two_percent_rejected(self):
        self.mt5.symbol_info.return_value.volume_min=.1
        self.assertFalse(self.execute().sent)
        self.mt5.order_send.assert_not_called()
    def test_manual_position_without_stop_blocks_personal_portfolio(self):
        self.mt5.positions_get.return_value=[NS(magic=1,sl=0)]
        self.assertFalse(self.execute().sent)
        self.mt5.order_send.assert_not_called()
    def test_missing_history_and_old_quotes_fail_closed(self):
        self.mt5.history_deals_get.return_value=None
        with self.assertRaisesRegex(RuntimeError,'history unavailable'):self.execute()
        self.mt5.history_deals_get.return_value=[]
        self.mt5.symbol_info_tick.return_value.time=0
        self.assertFalse(self.execute().sent)
        self.mt5.order_send.assert_not_called()
    def test_ambiguous_submission_is_never_retried(self):
        self.mt5.order_send.return_value=None
        with self.assertRaisesRegex(RuntimeError,'review broker orders'):
            self.execute(before_send=lambda:None)
        self.mt5.order_send.assert_called_once()

    def test_stop_or_account_guard_runs_immediately_before_send(self):
        guard=Mock(side_effect=RuntimeError('account changed'))
        with self.assertRaisesRegex(RuntimeError,'account changed'):self.execute(before_send=guard)
        guard.assert_called_once()
        self.mt5.order_send.assert_not_called()

class EngineRoutingTests(unittest.TestCase):
    def test_engine_publishes_personal_signal_with_zero_customers(self):
        from dataclasses import make_dataclass
        from server import signal_engine as engine
        Signal=make_dataclass('Signal',['strategy_id','direction','setup_time','stop_loss','take_profit'])
        signal=Signal('TEST','BUY',datetime.now(timezone.utc).isoformat(),1990,2020)
        stop=threading.Event()
        client=Mock(symbol='XAUUSD',clock=NS(offset_seconds=0))
        registry=Mock()
        registry.scan.return_value=[signal]
        with patch.object(engine,'ACTIVE_MARKETS',{'GOLD':'XAUUSD'}),patch.object(engine,'MT5Client',return_value=client),patch.object(engine,'StrategyRegistry',return_value=registry),patch.object(engine,'active_clients',return_value=[]),patch.object(engine,'news_lock_enabled',return_value=False),patch.object(engine,'write_status'),patch.object(engine,'publish_signal') as publish,patch.object(stop,'wait',side_effect=lambda _:stop.set()):
            engine.main(stop)
            publish.assert_called_once()
            self.assertEqual(publish.call_args.args[1]['direction'],'BUY')

if __name__=='__main__':unittest.main()
