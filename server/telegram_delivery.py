"""Render queued facts in the external Telegram process, just before delivery."""
import json
import sqlite3
from contextlib import closing
from html import escape
from pathlib import Path


def _timezone(row, database):
    if row.get('client_id') is not None:
        from .client_notifications import _database
        with closing(sqlite3.connect(_database(database))) as con:
            value=con.execute('SELECT display_timezone FROM clients WHERE id=?',(row['client_id'],)).fetchone()
        return value[0] if value and value[0] else 'UTC'
    from .workspace_settings import load_settings
    return load_settings()['display_timezone']


def prepare(row, *, database=None):
    if not row.get('event_json'):
        return row['message'],row.get('media_path') or None,None
    event=json.loads(row['event_json'])
    from .telegram_presentation import format_new_trade,format_stop_update,format_runtime_alert
    from .pnl_cards import render_trade_card,render_stop_update_card
    tz=_timezone(row,database)
    kind=event.get('kind')
    trade=event.get('trade') or {}
    if kind=='NEW_TRADE':
        # Full execution details remain selectable, readable Telegram text.
        return format_new_trade(trade,display_timezone=tz),None,'HTML'
    if kind=='SL_UPDATED':
        text=format_stop_update(trade,display_timezone=tz)
        card=render_stop_update_card(trade,display_timezone=tz)
        return text,card if len(text)<=1024 else None,'HTML'
    if kind=='TRADE_CLOSED':
        currency=escape(str(trade.get('currency') or 'account currency'))
        pnl=trade.get('pnl',trade.get('profit'))
        amount='Unavailable' if pnl is None else f'{float(pnl):+,.2f} {currency}'
        text=(f"<b>AZT · TRADE CLOSED</b>\n{escape(str(trade.get('symbol','')))} · {escape(str(trade.get('direction','')))}"
              f"\nTicket #{escape(str(trade.get('ticket','—')))}\nRealized P/L: <b>{amount}</b>"
              f"\nReason: {escape(str(trade.get('result') or 'Closed'))}")
        return text,render_trade_card(trade,display_timezone=tz),'HTML'
    if kind=='RUNTIME':
        return format_runtime_alert(event.get('account',''),event.get('state',''),event.get('message','')),None,'HTML'
    raise ValueError('Unknown Telegram presentation event; retained for review.')


def send_queued(bot,row,*,database=None):
    text,media,parse_mode=prepare(row,database=database)
    kwargs={'parse_mode':parse_mode} if parse_mode else {}
    if media:
        try:
            return bot.send_photo(row['chat_id'],media,text,**kwargs)
        finally:
            # Typed events can be rendered again from their durable facts. Keep
            # repeated stop updates/retries from accumulating temporary PNGs.
            try:
                path=Path(media).resolve()
                if row.get('event_json') and path.is_relative_to((Path.cwd()/'logs/cards').resolve()):
                    path.unlink(missing_ok=True)
            except OSError:
                pass
    return bot.send_message(row['chat_id'],text,**kwargs)
