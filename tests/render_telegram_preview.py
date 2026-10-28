"""Generate explicitly simulated Telegram samples without MT5/network access."""
from datetime import datetime, timezone
from pathlib import Path
from server.pnl_cards import render_trade_card, render_stop_update_card, render_positions_cards, render_journal_card


def main():
    folder=Path.cwd()/'logs'/'telegram_preview'
    now=datetime.now(timezone.utc).isoformat()
    trade=dict(account_key='SIMULATION | Example Broker|123',ticket='SIM-501',symbol='XAUUSD.c',
        direction='SELL',state='OPEN',volume=.001,entry=4160.31,current_price=4158.72,
        sl=4161.9,tp=4157.2,sl_pnl=-1.59,tp_pnl=3.11,pnl=.93,currency='USC',
        observed_utc=now,strategy='PULLBACK',risk_pct=.879)
    outputs=[render_trade_card(trade,display_timezone='Africa/Kampala',output=folder/'simulated_trade.png'),
        render_stop_update_card(dict(trade,old_sl=4161.90,new_sl=4160.50,old_sl_pnl=-1.59,
            new_sl_pnl=-.19,changed_utc=now,reason='TRAILING'),display_timezone='Africa/Kampala',output=folder/'simulated_sl_update.png')]
    outputs+=render_positions_cards([trade,dict(trade,ticket='SIM-502',direction='BUY',volume=.03,
        entry=4159.5,current_price=4158.72,sl=4157.3,tp=4163.9,pnl=-2.34,sl_pnl=-6.6,tp_pnl=13.2)],
        display_timezone='Africa/Kampala',output_dir=folder)
    outputs.append(render_journal_card(dict(date='SIMULATION · 28 Oct 2026',pnl=12.4,currency='USC',
        pnl_by_currency={'USC':12.4},trades_taken=7,wins=4,losses=3,win_rate=57.14,
        strategies_used=['PULLBACK','SUPPORT_RESISTANCE']),display_timezone='Africa/Kampala',output=folder/'simulated_journal.png'))
    for path in outputs:
        print(path)


if __name__=='__main__':
    main()
