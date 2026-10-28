"""Render actual observed trade/journal values over non-destructive template copies."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import math
import os
import uuid
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont, ImageFilter
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


def _display_time(value, display_timezone):
    zone=ZoneInfo(display_timezone)
    if not value:
        return 'Time unavailable'
    dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Card timestamps must be timezone-aware UTC values.')
    return dt.astimezone(zone).strftime('%d %b %Y  %H:%M %Z')


def _render(title, amount, currency, details, footnote, *, output=None, positive=True, state='', headline=None):
    template=asset_path('IMAGES/PnL_CARDS/'+('PROFIT.jpg' if positive else 'LOSS.jpg'))
    with Image.open(template) as original:
        image=original.convert('RGB').copy()
    width,height=image.size
    bounds=(int(width*.075),int(height*.235),int(width*.925),int(height*.86))
    # Template example values must never remain visible as if they were actual
    # account values. Blur the copy, then fully cover its data panel.
    # Sample prices printed on the supplied template are replaced completely.
    # Reuse its clean sky as the glass texture, retaining the official exterior,
    # sun/star and landscape without ghosting the template's example numbers.
    texture=image.crop((0,0,width,int(height*.22))).resize((bounds[2]-bounds[0],bounds[3]-bounds[1]))
    texture=texture.filter(ImageFilter.GaussianBlur(3))
    texture=Image.blend(texture,Image.new('RGB',texture.size,'#08131f'),.78)
    image.paste(texture,bounds)
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle(bounds, radius=int(width*.03),outline='#e8bd67',width=max(2,int(width*.003)))
    x=int(width*.115)
    max_width=int(width*.77)
    def text(y,value,size,color='#edf3ee',bold=False):
        font=_font(width*size,bold)
        value=str(value)
        while draw.textbbox((0,0),value,font=font)[2] > max_width and len(value)>3:
            value=value[:-2]+'…'
        draw.text((x,int(height*y)),value,font=font,fill=color)
    text(.265,'AGORA ZION TRADER',.033,'#e8bd67',True)
    text(.315,title,.035,bold=True)
    text(.365,state or 'OBSERVED RESULT',.021,'#9eaea9')
    color='#6ed6ac' if positive else '#fa8586'
    pnl=float(amount)
    if not math.isfinite(pnl):
        raise ValueError('PnL must be finite.')
    # Do not claim dollar PnL for a non-USD broker account.
    prefix='$' if currency=='USD' else ''
    text(.405,headline or f"{'+' if pnl>=0 else '-'}{prefix}{abs(pnl):,.2f} {currency if currency!='USD' else ''}",.045 if headline else .075,'#e8bd67' if headline else color,True)
    start=.515
    step=.071
    for index,(label,value) in enumerate(details[:7]):
        row,column=divmod(index,2)
        left=x+column*int(width*.397)
        top=int(height*(start+row*step))
        right=int(width*.885) if index==6 else left+int(width*.37)
        draw.rounded_rectangle((left-8,top,right,top+int(height*.061)),radius=9,fill='#142630',outline='#53605b',width=1)
        draw.text((left,top+5),str(label).upper(),font=_font(width*.013),fill='#b1bdb4')
        val=str(value)
        font=_font(width*.018,True)
        while draw.textbbox((0,0),val,font=font)[2]>right-left-10 and len(val)>3:
            val=val[:-2]+'…'
        draw.text((left,top+int(height*.026)),val,font=font,fill='#edf3ee')
    text(.814,footnote,.017,'#9eaea9')
    destination=Path(output) if output else Path.cwd()/'logs'/'cards'/('AZT_'+uuid.uuid4().hex+'.png')
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.resolve()==template.resolve():
        raise ValueError('The original template cannot be overwritten.')
    image.save(destination,format='PNG')
    return destination


def render_trade_card(trade, *, display_timezone='UTC', output=None):
    pnl=trade.get('pnl',trade.get('profit',0))
    pnl=0 if pnl is None else float(pnl)
    state=trade.get('state','CLOSED')
    is_open=state.upper()=='OPEN'
    result='FLOATING / UNREALIZED' if is_open else str(trade.get('result') or 'CLOSED')
    currency=str(trade.get('currency') or 'Account currency')
    details=[('Account',trade.get('account_key','—')),('Ticket / Strategy',f"{trade.get('ticket','—')} / {trade.get('strategy') or '—'}"),('Lots',_number(trade.get('volume'))),('Entry / '+('Current' if is_open else 'Exit'),_number(trade.get('entry'),3)+' / '+_number(trade.get('current_price') if is_open else trade.get('exit'),3)),('SL / TP',_number(trade.get('sl'),3)+' / '+_number(trade.get('tp'),3)),('Risk',(_number(trade.get('risk_pct'),3)+'%') if trade.get('risk_pct') is not None else 'Not recorded'),('Time',_display_time(trade.get('closed_utc') or trade.get('observed_utc') or trade.get('opened_utc'),display_timezone))]
    return _render(str(trade.get('symbol','TRADE'))+'  '+str(trade.get('direction','')),pnl,currency,details,'AZT  •  '+display_timezone+'  •  '+('Floating values may change' if is_open else 'Confirmed broker history'),output=output,positive=pnl>=0,state=result)


def render_journal_card(journal, *, display_timezone='UTC', output=None):
    pnl=float(journal.get('pnl') or 0)
    by_currency=journal.get('pnl_by_currency',{})
    if len(by_currency)>1:
        amount=0
        currency='Mixed currencies: see breakdown'
    else:
        amount=pnl
        currency=journal.get('currency') or next(iter(by_currency),'Account currency')
    details=[('Trades',journal.get('trades_taken',journal.get('trade_count',0))),('Wins / Losses',str(journal.get('wins',0))+' / '+str(journal.get('losses',0))),('Win rate',_number(journal.get('win_rate',0))+'%'),('Strategies',', '.join(journal.get('strategies_used',[])) or 'Not recorded'),('Risk used',str(journal.get('risk_used') if journal.get('risk_used') is not None else 'Not recorded')),('Currency PnL',', '.join(f'{k}: {v:+.2f}' for k,v in by_currency.items()) or str(currency)),('Display timezone',display_timezone)]
    return _render('DAILY JOURNAL  '+str(journal.get('date','')),amount,currency,details,'AZT  •  Broker records grouped by selected local date',output=output,positive=pnl>=0,state='DAILY SUMMARY',headline='Multiple currencies' if len(by_currency)>1 else None)
