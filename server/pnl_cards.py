"""Render actual observed trade/journal values over non-destructive template copies."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import math
import os
import uuid
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
from .ui_theme import asset_path


def _font(size, bold=False):
    font = Path(os.getenv('WINDIR','C:/Windows'))/'Fonts'/('segoeuib.ttf' if bold else 'segoeui.ttf')
    try:
        return ImageFont.truetype(str(font), max(10,int(size)))
    except OSError:
        return ImageFont.load_default(size=max(10,int(size)))


def _number(value, digits=2):
    if value is None:
        return '—'
    number=float(value)
    return f'{number:,.{digits}f}' if math.isfinite(number) else '—'


def _money(value, currency=''):
    if value is None:
        return '—'
    try:
        number=float(value)
    except (ValueError,TypeError):
        return '—'
    if not math.isfinite(number):
        return '—'
    sign='+' if number >= 0 else '−'
    code=str(currency or 'Account currency')
    return f'{sign}${abs(number):,.2f}' if code.upper()=='USD' else f'{sign}{abs(number):,.2f} {code}'


def _strategy(value):
    return str(value or 'Not recorded').replace('_',' ').title()


def _quantity(value):
    if value is None:
        return '—'
    number=float(value)
    return f'{number:.8f}'.rstrip('0').rstrip('.') if math.isfinite(number) else '—'


def _stop(value):
    if value is None:
        return '—'
    return 'Not set' if float(value)==0 else _number(value,2)


def _stale(value, now=None):
    if not value:
        return True
    try:
        observed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if observed.tzinfo is None:
            return True
        return abs(((now or datetime.now(timezone.utc))-observed).total_seconds())>60
    except (ValueError,TypeError):
        return True


def _fit_text(draw, text, width, size, *, bold=False, minimum=22):
    text=str(text)
    if len(text)>512:
        text=text[:511]+'…'
    font=_font(size,bold)
    while draw.textbbox((0,0),text,font=font)[2]>width and size>minimum:
        size-=1
        font=_font(size,bold)
    while draw.textbbox((0,0),text,font=font)[2]>width and len(text)>3:
        text=text[:-2]+'…'
    return text,font


def _canvas(positive=True):
    """Preserve the supplied landscape with a feathered, transparent text area.

    Older versions pasted a nearly opaque #08131f rectangle across the middle
    of the supplied image. This removed the nature background from every card.
    Instead, soften the preprinted demo labels on a *copy* of the original by
    blurring the underlying pixels in place. The card has NO colored fill; the
    original photograph is visible through the entire information region.
    """
    template = asset_path('IMAGES/PnL_CARDS/' + ('PROFIT.jpg' if positive else 'LOSS.jpg'))
    with Image.open(template) as original:
        image = ImageOps.fit(original.convert('RGB'), (1080, 1350), centering=(.5, .38))
    # Original demo figures are embedded in the supplied JPEG. A feathered
    # local blur obscures those old figures without inserting a solid panel.
    # Keep the image scenery, colors, skyline and source templates untouched.
    mask = Image.new('L', image.size, 0)
    area = (68, 282, 1012, 1226)
    ImageDraw.Draw(mask).rounded_rectangle(area, radius=34, fill=235)
    mask = mask.filter(ImageFilter.GaussianBlur(24))
    soft = image.filter(ImageFilter.GaussianBlur(36))
    image.paste(soft, (0, 0), mask)
    draw = ImageDraw.Draw(image)
    return image, draw, template


def _save(image,template,output=None):
    destination=Path(output) if output else Path.cwd()/'logs'/'cards'/('AZT_'+uuid.uuid4().hex+'.png')
    # Guard both official templates, regardless of the selected result template.
    originals={asset_path('IMAGES/PnL_CARDS/'+name+'.jpg').resolve() for name in ('PROFIT','LOSS')}
    if destination.resolve() in originals:
        raise ValueError('The original template cannot be overwritten.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    image.save(destination,format='PNG')
    return destination


def _display_time(value, display_timezone):
    zone=ZoneInfo(display_timezone)
    if not value:
        return 'Time unavailable'
    dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Card timestamps must be timezone-aware UTC values.')
    return dt.astimezone(zone).strftime('%d %b %Y  %H:%M %Z')


def _render(title, amount, currency, details, footnote, *, output=None, positive=True, state='', headline=None):
    image,draw,template=_canvas(positive)
    def text(y,value,size,color='#edf3ee',bold=False):
        value,font=_fit_text(draw,value,860,size,bold=bold)
        draw.text((110,y),value,font=font,fill=color)
    text(315,'AGORA ZION TRADER',34,'#e8bd67',True)
    text(380,title,48,bold=True)
    text(450,state or 'OBSERVED RESULT',27,'#aebfb9')
    color='#6ed6ac' if positive else '#fa8586'
    pnl=float(amount)
    if not math.isfinite(pnl):
        raise ValueError('PnL must be finite.')
    # Do not claim dollar PnL for a non-USD broker account.
    text(505,headline or _money(pnl,currency),62 if headline else 80,'#e8bd67' if headline else color,True)
    for index,(label,value) in enumerate(details[:7]):
        y=635+index*70
        draw.line((110,y-10,970,y-10),fill='#2b4148',width=1)
        value,font=_fit_text(draw,value,590,31,bold=True,minimum=23)
        draw.text((110,y),str(label).upper(),font=_font(20),fill='#aebfb9')
        draw.text((375,y-3),value,font=font,fill='#edf3ee')
    text(1160,footnote,21,'#aebfb9')
    return _save(image,template,output)


def render_trade_card(trade, *, display_timezone='UTC', output=None):
    raw_pnl=trade.get('pnl',trade.get('profit'))
    pnl=0 if raw_pnl is None else float(raw_pnl)
    state=trade.get('state','CLOSED')
    is_open=state.upper()=='OPEN'
    result='OPEN POSITION' if is_open else str(trade.get('result') or 'CLOSED TRADE')
    if is_open and _stale(trade.get('observed_utc')):
        result+=' · STALE SNAPSHOT'
    result+=' · '+str(trade.get('account_key') or trade.get('account_label') or 'Account unavailable')
    currency=str(trade.get('currency') or 'Account currency')
    details=[('Ticket',trade.get('ticket','—')),('Strategy',_strategy(trade.get('strategy'))),('Size / Entry',_quantity(trade.get('volume'))+' lot / '+_number(trade.get('entry'),2)),('Current' if is_open else 'Exit',_number(trade.get('current_price') if is_open else trade.get('exit'),2)),('SL / TP',_stop(trade.get('sl'))+' / '+_stop(trade.get('tp'))),('Planned risk',(_number(trade.get('risk_pct'),3)+'%') if trade.get('risk_pct') is not None else 'Not recorded'),('Time',_display_time(trade.get('closed_utc') or trade.get('observed_utc') or trade.get('opened_utc'),display_timezone))]
    return _render(str(trade.get('symbol','TRADE'))+'  '+str(trade.get('direction','')),pnl,currency,details,'AZT  •  '+display_timezone+'  •  '+('Floating values may change' if is_open else 'Confirmed broker history'),output=output,positive=pnl>=0,state=result,headline='PnL not available' if raw_pnl is None else None)


def render_journal_card(journal, *, display_timezone='UTC', output=None):
    pnl=float(journal.get('pnl') or 0)
    by_currency=journal.get('pnl_by_currency',{})
    if len(by_currency)>1:
        amount=0
        currency='Mixed currencies: see breakdown'
    else:
        amount=pnl
        currency=journal.get('currency') or next(iter(by_currency),'Account currency')
    details=[('Date',journal.get('date','—')),('Closed trades',journal.get('trades_taken',journal.get('trade_count',0))),('Wins / Losses',str(journal.get('wins',0))+' / '+str(journal.get('losses',0))),('Win rate',_number(journal.get('win_rate',0))+'%'),('Strategies',', '.join(_strategy(v) for v in journal.get('strategies_used',[])) or 'Not recorded'),('Currency PnL',', '.join(_money(v,k) for k,v in by_currency.items()) or _money(pnl,currency)),('Timezone',display_timezone)]
    return _render('DAILY JOURNAL  '+str(journal.get('date','')),amount,currency,details,'AZT  •  Broker records grouped by selected local date',output=output,positive=pnl>=0,state='DAILY SUMMARY',headline='Multiple currencies' if len(by_currency)>1 else None)


def render_stop_update_card(event, *, display_timezone='UTC', output=None):
    """An observed SL change; rendering never changes a broker stop/order."""
    currency=str(event.get('currency') or 'Account currency')
    old=event.get('old_sl')
    new=event.get('new_sl',event.get('sl'))
    reason=str(event.get('reason','')).upper()
    title='TRAILING SL UPDATED' if reason=='TRAILING' else 'STOP LOSS UPDATED'
    direction=str(event.get('direction','')).upper()
    improved=False
    if old is not None and new is not None:
        try:
            improved=float(new)>float(old) if direction=='BUY' else float(new)<float(old) if direction=='SELL' else False
        except (ValueError,TypeError):
            pass
    details=[('Position',str(event.get('symbol','—'))+' '+direction),('Ticket',event.get('ticket','—')),('Current price',_number(event.get('current_price'),2)),('Floating PnL',_money(event.get('pnl',event.get('profit')),currency)),('At previous SL',_money(event.get('old_sl_pnl'),currency) if old else 'Not set'),('At new SL',_money(event.get('new_sl_pnl',event.get('sl_pnl')),currency) if new else 'Not set'),('Updated',_display_time(event.get('changed_utc') or event.get('observed_utc'),display_timezone))]
    return _render(title,0,currency,details,'Estimated stop PnL excludes future fees/slippage',output=output,positive=improved,state=str(event.get('account_key') or 'Account unavailable')+' · Observed update',headline=_stop(old)+'  →  '+_stop(new))


def render_positions_cards(positions, *, display_timezone='UTC', output_dir=None):
    """Readable two-position pages, including per-currency floating totals."""
    rows=list(positions)
    folder=Path(output_dir) if output_dir else Path.cwd()/'logs'/'cards'
    folder.mkdir(parents=True,exist_ok=True)
    pages=[rows[index:index+2] for index in range(0,len(rows),2)] or [[]]
    totals={}
    known_pnl=0
    for row in rows:
        value=row.get('pnl',row.get('profit'))
        if value is not None and math.isfinite(float(value)):
            key=str(row.get('currency') or 'Account currency')
            totals[key]=totals.get(key,0)+float(value)
            known_pnl+=1
    outputs=[]
    for index,page in enumerate(pages):
        image,draw,template=_canvas(sum(totals.values())>=0 if len(totals)==1 else True)
        def line(y,value,size=30,color='#edf3ee',bold=False):
            value,font=_fit_text(draw,value,860,size,bold=bold)
            draw.text((110,y),value,font=font,fill=color)
        line(315,'AGORA ZION TRADER',34,'#e8bd67',True)
        line(377,'OPEN POSITIONS',50,bold=True)
        line(445,f'{len(rows)} open · Page {index+1}/{len(pages)}',27,'#aebfb9')
        total_text='  |  '.join(_money(value,key) for key,value in totals.items()) or ('Floating PnL unavailable' if rows else 'No observed positions')
        if totals and known_pnl<len(rows):
            total_text+=' (partial)'
        line(498,total_text,42,'#6ed6ac' if len(totals)<=1 and sum(totals.values())>=0 else '#e8bd67',True)
        if not page:
            line(640,'No open positions recorded.',34)
            line(710,'Waiting for an enabled MT5 worker snapshot.',27,'#aebfb9')
        for position_index,row in enumerate(page):
            top=595+position_index*260
            draw.rounded_rectangle((94,top-12,988,top+235),radius=18,fill='#102630',outline='#40545b',width=1)
            currency=str(row.get('currency') or 'Account currency')
            side=str(row.get('direction','')).upper()
            line(top,f"{side} {row.get('symbol','—')} · {_quantity(row.get('volume'))} lot",33,'#fa8586' if side=='SELL' else '#6ed6ac',True)
            line(top+43,str(row.get('account_key') or 'Account unavailable')+' · #'+str(row.get('ticket','—')),22,'#aebfb9')
            line(top+80,'Entry '+_number(row.get('entry'),2)+'   ·   Current '+_number(row.get('current_price'),2),28)
            line(top+116,'SL '+_stop(row.get('sl'))+'  ('+_money(row.get('sl_pnl'),currency)+')',28)
            line(top+151,'TP '+_stop(row.get('tp'))+'  ('+_money(row.get('tp_pnl'),currency)+')',28)
            line(top+190,'Floating '+_money(row.get('pnl',row.get('profit')),currency),29,bold=True)
        observed=next((row.get('observed_utc') for row in page if row.get('observed_utc')),None)
        stale=any(_stale(row.get('observed_utc')) for row in page)
        line(1100,'STALE SNAPSHOT — reconnect MT5 for current values' if stale else 'Latest observed snapshot',24,'#e8bd67' if stale else '#aebfb9')
        line(1140,_display_time(observed,display_timezone),23,'#aebfb9')
        line(1180,'Floating values change · stop/target amounts are estimates',21,'#aebfb9')
        outputs.append(_save(image,template,folder/f'AZT_positions_{uuid.uuid4().hex}_{index+1}.png'))
    return outputs
