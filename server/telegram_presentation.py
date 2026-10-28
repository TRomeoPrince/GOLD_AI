"""Pure AZT Telegram HTML. No broker, database or network operations."""
from datetime import datetime, timezone
from html import escape, unescape
import math
import re
from zoneinfo import ZoneInfo

POSITIONS_PER_PAGE = 2


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and not isinstance(value, bool) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _safe(value, limit=100):
    text = str(value or '—')
    text = re.sub(r'[\x00-\x08\x0b-\x1f]', '', text)
    text = re.sub(r'(?:bot)?[0-9]{5,}:[A-Za-z0-9_-]{20,}', '[redacted]', text)
    text = re.sub(r'(?i)\b(password|secret|token|api[_ -]?key)\s*[=:]\s*\S+', r'\1=[redacted]', text)
    if len(text) > limit:
        text = text[:limit-1] + '…'
    return escape(text)


def _decimal(value, digits=2):
    number = _number(value)
    if number is None:
        return 'Not available'
    return f'{number:,.{digits}f}' if abs(number) < 1e12 else f'{number:.4g}'


def _lots(value):
    number = _number(value)
    if number is not None and abs(number) >= 1e12:
        return f'{number:.4g}'
    return f'{number:.8f}'.rstrip('0').rstrip('.') if number is not None else 'Not available'


def money(value, currency='USD', signed=True):
    number = _number(value)
    if number is None:
        return 'Not available'
    code = str(currency or 'account currency').strip().upper()[:20]
    sign = ('+' if number >= 0 else '−') if signed else ('−' if number < 0 else '')
    amount = _decimal(abs(number))
    return sign + ('$' + amount if code == 'USD' else amount + ' ' + _safe(code, 20))


def strategy_name(value):
    value = str(value or 'Not recorded')
    return _safe({'SUPPORT_RESISTANCE': 'Support & Resistance', 'MOMENTUM_SCALP': 'Momentum Scalp',
                  'PULLBACK': 'Pullback'}.get(value.upper(), value.replace('_', ' ').title()), 40)


def _stamp(value, zone='UTC'):
    if not value:
        return 'Time unavailable'
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            return 'Time unavailable'
        return dt.astimezone(ZoneInfo(zone)).strftime('%d %b %Y · %H:%M:%S %Z')
    except (ValueError, TypeError, KeyError):
        return 'Time unavailable'


def _side(trade):
    side = str(trade.get('direction', '')).upper()
    return ('🟢 BUY' if side == 'BUY' else '🔴 SELL' if side == 'SELL' else _safe(side, 12))


def _levels(trade):
    currency = trade.get('currency')
    entry_label='Requested entry' if str(trade.get('entry_basis','')).upper().startswith('REQUESTED') else 'Entry'
    return [f"{entry_label}  <b>{_decimal(trade.get('entry'), 3)}</b>",
            f"SL      <b>{'Not set' if _number(trade.get('sl')) == 0 else _decimal(trade.get('sl'), 3)}</b>  ({money(trade.get('sl_pnl'), currency)})",
            f"TP      <b>{'Not set' if _number(trade.get('tp')) == 0 else _decimal(trade.get('tp'), 3)}</b>  ({money(trade.get('tp_pnl'), currency)})"]


def format_new_trade(trade, display_timezone='UTC'):
    risk = _number(trade.get('risk_pct'))
    portfolio = _number(trade.get('portfolio_after_pct'))
    limit = _number(trade.get('max_open_risk_pct'))
    lines = ['🚀 <b>AZT — NEW TRADE</b>', '',
             f"{_side(trade)}  <b>{_safe(trade.get('symbol'), 25)}</b> · {_lots(trade.get('volume'))} lot",
             f"Strategy  <b>{strategy_name(trade.get('strategy') or trade.get('strategy_id'))}</b>",
             '', *_levels(trade), '',
             '<b>Risk &amp; exposure</b>',
             f"Planned risk  <b>{risk:.3f}%</b>" if risk is not None else 'Planned risk  Not recorded',
             'Risk amount  ' + money(trade.get('risk_cash'), trade.get('currency'), False),
             f"Portfolio after entry  <b>{portfolio:.3f}% / {limit:.3f}%</b>" if portfolio is not None and limit is not None else 'Portfolio after entry  Not recorded',
             '', f"Ticket  <code>{_safe(trade.get('ticket'), 30)}</code>",
             f"Account  {_safe(trade.get('account_key'), 60)}",
             '🕒 ' + _stamp(trade.get('executed_utc') or trade.get('opened_utc') or trade.get('observed_utc'), display_timezone),
             '<i>SL/TP amounts are price estimates; fees and slippage may change the outcome.</i>']
    return '\n'.join(lines)


def _pages(title, blocks, *, max_blocks=4):
    pages, current = [], []
    for block in blocks:
        if current and (len(current) >= max_blocks or len(title) + sum(map(len, current)) + len(block) > 3700):
            pages.append(title + '\n\n' + '\n\n'.join(current))
            current = []
        current.append(block)
    if current or not pages:
        pages.append(title + ('\n\n' + '\n\n'.join(current) if current else ''))
    return [text + (f'\n\n<i>Page {i+1}/{len(pages)}</i>' if len(pages)>1 else '') for i,text in enumerate(pages)]


def _totals(rows):
    groups = {}
    for row in rows:
        currency = str(row.get('currency') or 'account currency').upper()
        groups.setdefault(currency, []).append(row)
    blocks=[]
    for currency, trades in groups.items():
        lines=[f'<b>Portfolio totals · {_safe(currency,20)}</b>']
        for field,label in [('pnl','Floating P/L'),('sl_pnl','At all SLs'),('tp_pnl','At all TPs')]:
            values=[_number(t.get(field)) for t in trades]
            known=[value for value in values if value is not None]
            if len(known)==len(trades):
                value=money(sum(known),currency)
            else:
                value='Not available (incomplete data)'
            lines.append(f'{label}  <b>{value}</b>')
        blocks.append('\n'.join(lines))
    return blocks


def format_positions(positions, display_timezone='UTC', now=None):
    rows=list(positions)
    title=f'📊 <b>AZT — OPEN POSITIONS ({len(rows)})</b>'
    if not rows:
        return [title+'\n\nNo open positions are recorded.\n<i>Positions appear after a running MT5 worker supplies its snapshot.</i>']
    current = now or datetime.now(timezone.utc)
    blocks=[]
    for index,trade in enumerate(rows,1):
        observed=trade.get('observed_utc')
        try:
            dt=datetime.fromisoformat(str(observed).replace('Z','+00:00'))
            stale=dt.tzinfo is None or not -60 <= (current-dt).total_seconds() <= 60
        except (ValueError,TypeError):
            stale=True
        lines=[f"<b>{index}. {_side(trade)} {_safe(trade.get('symbol'),25)}</b> · {_lots(trade.get('volume'))} lot",
               f"Strategy  {strategy_name(trade.get('strategy'))}",
               f"Account  {_safe(trade.get('account_key'),60)}",
               *_levels(trade),
               f"Current  <b>{_decimal(trade.get('current_price'),3)}</b>",
               f"Floating P/L  <b>{money(trade.get('pnl'),trade.get('currency'))}</b>",
               f"Ticket  <code>{_safe(trade.get('ticket'),30)}</code>",
               ('⚠️ <b>STALE SNAPSHOT</b> · ' if stale else '🕒 Snapshot · ')+_stamp(observed,display_timezone)]
        blocks.append('\n'.join(lines))
    totals=_totals(rows)
    # Common one/two-currency portfolios repeat their compact summary on every
    # positions page; unusually many currencies get complete separate pages.
    if len(totals)<=2:
        pages=_pages(title,blocks,max_blocks=POSITIONS_PER_PAGE)
        summary='\n\n'+'\n\n'.join(totals)+'\n<i>SL/TP totals are estimates before fees/slippage.</i>'
        return [page+summary for page in pages]
    return _pages(title,blocks,max_blocks=POSITIONS_PER_PAGE)+_pages('📊 <b>AZT — CURRENCY TOTALS</b>',totals)


def format_journal(report, display_timezone='UTC'):
    title='📒 <b>AZT — DAILY JOURNAL</b>\n'+_safe(report.get('date'),100)+' · '+_safe(display_timezone,60)
    rows=list(report.get('trades') or [])
    pnl=report.get('pnl_by_currency') or {}
    if not pnl and report.get('currency') and _number(report.get('pnl')) is not None:
        pnl={report['currency']:report['pnl']}
    currency_lines=[f'<b>{money(value,currency)}</b>' for currency,value in pnl.items()]
    totals='\n'.join(currency_lines) or 'No closed P/L recorded'
    extra_currency_pages=[]
    if len(totals)>650:
        totals='Multiple currencies — complete totals follow on summary pages.'
        extra_currency_pages=_pages('📒 <b>AZT — JOURNAL CURRENCY TOTALS</b>',currency_lines,max_blocks=20)
    risk=_number(report.get('risk_used'))
    win_rate=_number(report.get('win_rate'))
    strategies=list(report.get('strategies_used') or [])
    strategy_summary=', '.join(strategy_name(s) for s in strategies[:3]) or 'Not recorded'
    if len(strategies)>3:
        strategy_summary+=f' (+{len(strategies)-3} more; see trade details)'
    summary='\n'.join([f"Trades  <b>{int(report.get('trades_taken',len(rows)))}</b>",
                       f"Wins / Losses  <b>{int(report.get('wins',0))} / {int(report.get('losses',0))}</b>",
                       f"Win rate  <b>{win_rate:.1f}%</b>" if win_rate is not None else 'Win rate  Not available',
                       'Net closed P/L  '+totals,
                       f'Risk recorded  {risk:.3f}%' if risk is not None else 'Risk recorded  Not available',
                       'Strategies  '+strategy_summary])
    if not rows:
        return [title+'\n\n'+summary+'\n\nNo closed trades recorded for this local date.']+extra_currency_pages
    details=[]
    for index,trade in enumerate(rows,1):
        details.append('\n'.join([f"<b>{index}. {_side(trade)} {_safe(trade.get('symbol'),35)}</b> · {money(trade.get('pnl'),trade.get('currency'))}",
                    f"{strategy_name(trade.get('strategy'))} · {_lots(trade.get('volume'))} lot",
                    f"Entry / Exit  {_decimal(trade.get('entry'),3)} / {_decimal(trade.get('exit'),3)}",
                    f"Result  {_safe(trade.get('result'),35)}",
                    f"Ticket  <code>{_safe(trade.get('ticket'),60)}</code> · {_safe(trade.get('account_key'),80)}",
                    'Closed  '+_stamp(trade.get('closed_utc'),display_timezone)]))
    return _pages(title+'\n\n'+summary,details,max_blocks=4)+extra_currency_pages


def format_stop_update(event, display_timezone='UTC'):
    trade=event.get('trade') or event
    trailing=str(event.get('reason') or trade.get('reason') or '').upper()=='TRAILING'
    title='🔒 <b>AZT — '+('TRAILING SL UPDATED' if trailing else 'STOP LOSS UPDATED')+'</b>'
    old=event.get('old_sl',trade.get('old_sl'))
    new=event.get('new_sl',trade.get('new_sl',trade.get('sl')))
    currency=trade.get('currency',event.get('currency'))
    return '\n'.join([title,'',f"{_side(trade)} <b>{_safe(trade.get('symbol'),35)}</b> · {_lots(trade.get('volume'))} lot",
            f"Ticket  <code>{_safe(trade.get('ticket'),60)}</code>",
            f"SL  <b>{_decimal(old,3)} → {_decimal(new,3)}</b>",
            f"Estimated P/L at SL  {money(event.get('old_sl_pnl',trade.get('old_sl_pnl')),currency)} → <b>{money(event.get('new_sl_pnl',trade.get('new_sl_pnl')),currency)}</b>",
            f"Account  {_safe(trade.get('account_key'),100)}",
            '🕒 '+_stamp(event.get('changed_utc') or event.get('observed_utc') or trade.get('changed_utc') or trade.get('observed_utc'),display_timezone),
            '<i>Observed broker change. This alert does not modify your stop.</i>'])


def format_runtime_alert(account,state,message):
    state=str(state).upper()
    labels={'READY':('🟢','Personal MT5 connected'), 'RECOVERED':('🟢','Personal MT5 reconnected'),
            'RECONNECTING':('🟠','MT5 reconnecting'),'DEGRADED':('🟠','MT5 connection needs attention'),
            'ERROR':('🔴','Personal MT5 needs attention'),'STOPPED':('⏸','Personal trading stopped')}
    icon,title=labels.get(state,('ℹ️',state.replace('_',' ').title()))
    body='Ready for fresh signals.' if state in {'READY','RECOVERED'} else str(message or '')
    body=re.sub(r'https?://\S+','[link hidden]',body)
    return f'{icon} <b>AZT — {_safe(title,80)}</b>\nAccount  {_safe(account,100)}\n\n{_safe(body,600)}'


def caption_summary(text, limit=1024):
    """Plain caption, leaving the complete HTML in its separate message."""
    plain=unescape(re.sub(r'<[^>]+>','',str(text)))
    return plain if len(plain)<=limit else plain[:max(0,limit-1)]+'…'
