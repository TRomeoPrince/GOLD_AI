"""Durable optional Telegram copies. In-app delivery is independent of this queue."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
import sqlite3
import time
import uuid


def _database(database=None):
    if database is not None:
        return database
    from .store import DB_PATH
    return DB_PATH


@contextmanager
def connection(database=None):
    con=sqlite3.connect(_database(database), timeout=.25)
    con.row_factory=sqlite3.Row
    try:
        con.executescript('''CREATE TABLE IF NOT EXISTS azt_telegram_delivery (
            id INTEGER PRIMARY KEY,event_key TEXT UNIQUE NOT NULL,client_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,token_fingerprint TEXT NOT NULL,message TEXT NOT NULL,
            media_path TEXT NOT NULL DEFAULT '',state TEXT NOT NULL DEFAULT 'PENDING',
            attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,
            claimed_at REAL,claim_id TEXT,message_id INTEGER,last_error TEXT NOT NULL DEFAULT '',
            created_utc TEXT NOT NULL,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS azt_telegram_commands (
            id INTEGER PRIMARY KEY,client_id INTEGER,command TEXT NOT NULL,state TEXT NOT NULL,created_utc TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS azt_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,message TEXT NOT NULL,client_id INTEGER,created_utc TEXT NOT NULL,event_key TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS azt_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,client_id INTEGER NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,created_utc TEXT NOT NULL,read_utc TEXT NOT NULL DEFAULT '',event_key TEXT UNIQUE);
        ''')
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _token():
    return os.getenv('GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN','').strip()


def _fingerprint(token):
    return hashlib.sha256(token.encode()).hexdigest()


def enqueue_client_message(client_id,text,*,event_key=None,database=None,media_path=None):
    try:
        token=_token()
        if not token:
            return False
        with connection(database) as con:
            client=con.execute('SELECT * FROM clients WHERE id=?',(int(client_id),)).fetchone()
            if client is None or not client['telegram_chat_id'] or client['status'] in {'ARCHIVED','REVOKED'}:
                return False
            key=event_key or uuid.uuid4().hex
            return con.execute('INSERT OR IGNORE INTO azt_telegram_delivery(event_key,client_id,chat_id,token_fingerprint,message,media_path,created_utc,updated) VALUES(?,?,?,?,?,?,?,?)',(str(key),int(client_id),int(client['telegram_chat_id']),_fingerprint(token),str(text)[:4096],str(media_path or ''),datetime.now(timezone.utc).isoformat(),time.time())).rowcount==1
    except Exception as exc:
        logging.warning('Client Telegram copy could not be queued (%s).',type(exc).__name__)
        return False


def enqueue_trade_event(client_id,trade,*,event_key=None,database=None):
    try:
        text=f"AZT • {trade.get('result',trade.get('state','TRADE'))}\n{trade.get('symbol','')} {trade.get('direction','')} • Ticket {trade.get('ticket','—')}\nPnL: {trade.get('pnl',trade.get('profit',0))} {trade.get('currency','')}"
        record_system_event('TRADE_'+str(trade.get('state','EVENT')),text,client_id=client_id,event_key='event:'+str(event_key) if event_key else None,database=database)
        if client_id is not None:
            with connection(database) as con:
                con.execute('INSERT OR IGNORE INTO azt_messages(client_id,title,body,created_utc,event_key) VALUES(?,?,?,?,?)',(client_id,'AZT Trade '+str(trade.get('state','Update')),text,datetime.now(timezone.utc).isoformat(),'inapp:'+str(event_key) if event_key else None))
        from .pnl_cards import render_trade_card
        from .workspace_settings import load_settings
        timezone_name=load_settings()['display_timezone']
        if client_id is not None:
            from .azt_store import preferences
            timezone_name=preferences(client_id).get('display_timezone','UTC')
        card=render_trade_card(trade,display_timezone=timezone_name)
        if client_id is None:
            from .telegram_notifications import enqueue_owner_event
            return enqueue_owner_event(event_key or uuid.uuid4().hex,text,database=database,media_path=card)
        return enqueue_client_message(client_id,text,event_key=event_key,database=database,media_path=card)
    except Exception as exc:
        logging.warning('Trade card alert could not be queued (%s).',type(exc).__name__)
        return False


def record_system_event(kind,message,*,client_id=None,event_key=None,database=None):
    try:
        with connection(database) as con:
            con.execute('INSERT OR IGNORE INTO azt_events(kind,message,client_id,created_utc,event_key) VALUES(?,?,?,?,?)',(str(kind)[:80],str(message)[:4000],client_id,datetime.now(timezone.utc).isoformat(),event_key))
        return True
    except Exception as exc:
        logging.warning('AZT notification unavailable (%s).',type(exc).__name__)
        return False


def _claim(database=None):
    token=_token()
    if not token:
        return None
    now=time.time()
    with connection(database) as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute("UPDATE azt_telegram_delivery SET state=CASE WHEN attempts>=5 THEN 'FAILED' ELSE 'RETRY' END,claim_id=NULL,claimed_at=NULL,last_error='Interrupted send; delivery outcome may be unknown.' WHERE state='CLAIMED' AND claimed_at<?",(now-60,))
        con.execute("UPDATE azt_telegram_delivery SET state='HELD',last_error='Original destination or configuration is no longer active.' WHERE state IN ('PENDING','RETRY') AND (token_fingerprint<>? OR NOT EXISTS(SELECT 1 FROM clients c WHERE c.id=client_id AND c.telegram_chat_id=chat_id AND c.status NOT IN ('ARCHIVED','REVOKED')))",(_fingerprint(token),))
        con.execute("UPDATE azt_telegram_delivery SET state=CASE WHEN attempts>=5 THEN 'FAILED' WHEN attempts=0 THEN 'PENDING' ELSE 'RETRY' END,last_error='' WHERE state='HELD' AND token_fingerprint=? AND EXISTS(SELECT 1 FROM clients c WHERE c.id=client_id AND c.telegram_chat_id=chat_id AND c.status NOT IN ('ARCHIVED','REVOKED'))",(_fingerprint(token),))
        row=con.execute("SELECT * FROM azt_telegram_delivery WHERE state IN ('PENDING','RETRY') AND next_attempt<=? AND attempts<5 ORDER BY id LIMIT 1",(now,)).fetchone()
        if row is None:
            return None
        claim=uuid.uuid4().hex
        con.execute("UPDATE azt_telegram_delivery SET state='CLAIMED',attempts=attempts+1,claimed_at=?,claim_id=?,updated=? WHERE id=?",(now,claim,now,row['id']))
        return {**dict(row),'attempts':int(row['attempts'])+1,'claim_id':claim,'token':token}


def process_one(database=None):
    row=_claim(database)
    if not row:
        return False
    from .client_telegram import ClientTelegramBot
    from .telegram_notifications import _safe_error
    try:
        bot=ClientTelegramBot(token=row['token'])
        message_id=bot.send_photo(row['chat_id'],row['media_path'],row['message']) if row['media_path'] else bot.send_message(row['chat_id'],row['message'])
        if not isinstance(message_id,int) or message_id<=0:
            raise RuntimeError('Telegram returned no message confirmation.')
        with connection(database) as con:
            con.execute("UPDATE azt_telegram_delivery SET state='SENT',message_id=?,last_error='',claim_id=NULL,claimed_at=NULL,updated=? WHERE id=? AND state='CLAIMED' AND claim_id=?",(message_id,time.time(),row['id'],row['claim_id']))
    except Exception as exc:
        summary=_safe_error(exc,row['token'])
        with connection(database) as con:
            con.execute("UPDATE azt_telegram_delivery SET state=?,next_attempt=?,last_error=?,claim_id=NULL,claimed_at=NULL,updated=? WHERE id=? AND state='CLAIMED' AND claim_id=?",('FAILED' if row['attempts']>=5 else 'RETRY',time.time()+min(120,5*2**(row['attempts']-1)),summary,time.time(),row['id'],row['claim_id']))
        logging.warning('Client Telegram delivery failed: %s',summary)
    return True


def delivery_rows(database=None):
    result=[]
    with connection(database) as con:
        result.extend({**dict(r),'kind':'CLIENT'} for r in con.execute('SELECT id,event_key,message,state,attempts,last_error FROM azt_telegram_delivery ORDER BY id DESC LIMIT 100'))
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='owner_telegram_outbox'").fetchone():
            result.extend({**dict(r),'id':r['event_key'],'kind':'OWNER'} for r in con.execute('SELECT event_key,message,state,attempts,last_error FROM owner_telegram_outbox ORDER BY created DESC LIMIT 100'))
    return result


def retry_delivery(row,database=None):
    with connection(database) as con:
        table='owner_telegram_outbox' if row['kind']=='OWNER' else 'azt_telegram_delivery'
        key='event_key' if row['kind']=='OWNER' else 'id'
        changed=con.execute(f"UPDATE {table} SET state='RETRY',attempts=0,next_attempt=0,last_error='',claim_id=NULL,claimed_at=NULL WHERE {key}=? AND state IN ('FAILED','RETRY')",(row['id'],)).rowcount
    return 'Retry queued.' if changed else 'Only failed or retrying alerts can be retried. Sent alerts are preserved.'


def record_command(command,state,client_id=None,database=None):
    try:
        with connection(database) as con:
            con.execute('INSERT INTO azt_telegram_commands(client_id,command,state,created_utc) VALUES(?,?,?,?)',(client_id,str(command).split()[0][:40],state,datetime.now(timezone.utc).isoformat()))
    except Exception as exc:
        logging.warning('Command history unavailable (%s).',type(exc).__name__)


def command_rows(database=None):
    with connection(database) as con:
        return [dict(r) for r in con.execute('SELECT * FROM azt_telegram_commands ORDER BY id DESC LIMIT 100')]


def run_maintenance(stop):
    from .azt_store import maintenance_tick
    from .personal_store import write_status
    while not stop.is_set():
        try:
            maintenance_tick()
            process_one()
            write_status('maintenance',state='READY',message='Subscriptions, in-app reminders and optional Telegram copies are monitored.')
        except Exception as exc:
            logging.warning('AZT maintenance retry (%s).',type(exc).__name__)
            try:
                write_status('maintenance',state='ERROR',message='Background maintenance will retry; see logs.')
            except OSError:
                pass
        stop.wait(3)
