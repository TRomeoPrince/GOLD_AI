import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from server.trade_events import execution_details,SignalOutcome


class ExecutionPresentationFactsTests(unittest.TestCase):
    def facts(self,api=None,result=None):
        api=api or Mock()
        api.account_info.return_value=SimpleNamespace(currency='USC',server='Broker',login=12)
        api.order_calc_profit.side_effect=[-159,311]
        result=result or SimpleNamespace(price=4160.31,volume=.01)
        return execution_details(api,result,{'price':4160,'volume':.02,'sl':4161.9,'tp':4157.2,'symbol':'XAUUSD','type':1},
                                 {'direction':'SELL','strategy_id':'PULLBACK'},ticket=123,risk_pct=.879,
                                 portfolio_after_pct=5.117,max_open_risk_pct=40),api

    def test_actual_fill_native_currency_and_signed_broker_estimates(self):
        data,api=self.facts()
        self.assertEqual((data['entry'],data['volume'],data['entry_basis']),(4160.31,.01,'FILLED'))
        self.assertEqual((data['currency'],data['sl_pnl'],data['tp_pnl'],data['risk_cash']),('USC',-159,311,159))
        self.assertEqual(data['portfolio_after_pct'],5.117)
        api.order_send.assert_not_called()

    def test_missing_fill_is_explicitly_requested_not_assumed_fill(self):
        data,_=self.facts(result=SimpleNamespace(price=0,volume=0))
        self.assertEqual((data['entry'],data['volume'],data['entry_basis']),(4160,.02,'REQUESTED'))

    def test_optional_account_and_calculation_failure_cannot_change_broker_result(self):
        api=Mock()
        api.account_info.side_effect=OSError('gone')
        api.order_calc_profit.side_effect=OSError('gone')
        data=execution_details(api,SimpleNamespace(price=float('nan')),{'sl':0,'tp':0}, {},ticket=123,risk_pct=.5,portfolio_after_pct=.5,max_open_risk_pct=20)
        self.assertEqual(data['ticket'],'123')
        self.assertIsNone(data['sl_pnl'])
        self.assertNotIn('currency',data)
        state,message=SignalOutcome('EXECUTED','ok',data)
        self.assertEqual((state,message),('EXECUTED','ok'))

    def test_account_switch_cannot_mislabel_cash_estimates(self):
        api=Mock()
        api.account_info.return_value=SimpleNamespace(currency='USD',server='Other',login=99)
        expected=SimpleNamespace(currency='USC',server='Broker',login=12)
        data=execution_details(api,SimpleNamespace(price=10,volume=.1),{'sl':9,'tp':11,'symbol':'GOLD'}, {},ticket=1,risk_pct=1,portfolio_after_pct=1,max_open_risk_pct=20,verified_account=expected)
        self.assertEqual((data['currency'],data['account_key']),('USC','Broker|12'))
        self.assertIsNone(data['sl_pnl'])
        api.order_calc_profit.assert_not_called()


if __name__=='__main__':
    unittest.main()
