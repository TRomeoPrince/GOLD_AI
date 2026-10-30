"""Page based AZT owner workspace; business operations remain in tested stores."""
from __future__ import annotations
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from . import ui_theme as ui
from . import store


class AdminWorkspace:
    def _build(self):
        ui.apply_theme(self)
        self.control_buttons = []
        self.service_status = tk.StringVar(value='')  # compatibility, details live on Telegram page
        self.status = tk.StringVar(value='AZT is ready. Personal trading starts only when enabled.')
        self.control_message = self.status
        self.news_var = tk.BooleanVar(value=store.news_lock_enabled())
        from .workspace_settings import load_settings
        self.display_timezone = tk.StringVar(value=load_settings()['display_timezone'])
        self.page_name = tk.StringVar(value='Dashboard')
        self.compact_status = tk.StringVar(value='Starting services')
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        sidebar = tk.Frame(self, bg=ui.BG, width=174)
        sidebar.grid(row=0, column=0, rowspan=3, sticky='ns')
        sidebar.grid_propagate(False)
        tk.Label(sidebar, text='AZT', bg=ui.BG, fg=ui.GOLD, font=('Segoe UI Semibold', 33)).pack(anchor='w', padx=20, pady=(26, 0))
        tk.Label(sidebar, text='OWNER WORKSPACE', bg=ui.BG, fg=ui.MUTED, font=('Segoe UI', 9)).pack(anchor='w', padx=20, pady=(0, 30))
        self.nav = {}
        self.pages = {}
        for title in ('Dashboard', 'Clients', 'Trades', 'Journal', 'Telegram', 'Risk', 'Settings'):
            button = ttk.Button(sidebar, text=title, style='Nav.TButton', command=lambda name=title: self.show_page(name))
            button.pack(fill='x', padx=8, pady=3)
            self.nav[title] = button
        tk.Label(sidebar, text='AGORA ZION\nTRADER', bg=ui.BG, fg=ui.GOLD, font=('Segoe UI', 10), justify='left').pack(side='bottom', anchor='w', padx=20, pady=25)
        self.header = tk.Canvas(self, height=122, bg=ui.BG, highlightthickness=0)
        self.header.grid(row=0, column=1, sticky='ew')
        self.header.bind('<Configure>', self._paint_header)
        container = ttk.Frame(self)
        container.grid(row=1, column=1, sticky='nsew')
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        for title in self.nav:
            page = ui.ScrollPage(container)
            page.grid(row=0, column=0, sticky='nsew')
            self.pages[title] = page
        footer = ttk.Frame(self, padding=(18, 9))
        footer.grid(row=2, column=1, sticky='ew')
        self.status_label = ttk.Label(footer, textvariable=self.status, style='Muted.TLabel', wraplength=800)
        self.status_label.pack(fill='x')
        footer.bind('<Configure>', lambda event: self.status_label.configure(wraplength=max(200, event.width-40)))
        self._build_dashboard(self.pages['Dashboard'].body)
        self._build_clients(self.pages['Clients'].body)
        self._build_trades(self.pages['Trades'].body)
        self._build_journal(self.pages['Journal'].body)
        self._build_telegram(self.pages['Telegram'].body)
        self._build_risk(self.pages['Risk'].body)
        self._build_settings(self.pages['Settings'].body)
        self.show_page('Dashboard')

    def _paint_header(self, event=None):
        width = max(300, self.header.winfo_width())
        self.header.delete('all')
        try:
            from PIL import Image, ImageOps, ImageTk
            if getattr(self,'_header_width',None)!=width:
                if not hasattr(self,'_header_source'):
                    with Image.open(ui.asset_path('IMAGES/BACKGROUND/BACKGROUND.jpg')) as source:
                        self._header_source=source.convert('RGB')
                image = ImageOps.fit(self._header_source, (width, 122), centering=(.5, .33))
                shade = Image.new('RGB', image.size, ui.BG)
                image = Image.blend(image, shade, .66)
                self._header_image = ImageTk.PhotoImage(image)
                self._header_width=width
            self.header.create_image(0, 0, image=self._header_image, anchor='nw')
        except (OSError, ImportError):
            pass
        self.header.create_text(25, 28, text='AGORA ZION TRADER', anchor='nw', fill=ui.GOLD, font=('Segoe UI Semibold', 22))
        self.header.create_text(27, 73, text=self.page_name.get() + '  /  ' + self.compact_status.get(), anchor='nw', fill=ui.TEXT, font=('Segoe UI', 11))
        self.header.create_line(0, 121, width, 121, fill=ui.EDGE)

    def show_page(self, name):
        self.pages[name].tkraise()
        self.page_name.set(name)
        for key, button in self.nav.items():
            button.configure(style='Selected.Nav.TButton' if key == name else 'Nav.TButton')
        self._paint_header()
        if hasattr(self, 'tree'):
            self.refresh()

    def _title(self, parent, title, subtitle=''):
        ttk.Label(parent, text=title, style='Heading.TLabel').pack(anchor='w', pady=(0, 5))
        if subtitle:
            label = ttk.Label(parent, text=subtitle, style='Muted.TLabel', wraplength=850)
            label.pack(fill='x', pady=(0, 15))
            parent.bind('<Configure>', lambda event: label.configure(wraplength=max(240, event.width-12)), add='+')

    def _actions(self, parent, actions, controls=False):
        bar = ui.FlowBar(parent)
        bar.pack(fill='x', pady=(6, 14))
        for action in actions:
            text, callback, *style = action
            button = bar.add(text, callback, style[0] if style else 'TButton')
            if controls:
                self.control_buttons.append(button)
        return bar

    def _build_dashboard(self, parent):
        self._title(parent, 'Your trading workspace', 'Live connections, account activity and client access in one place.')
        self._actions(parent, [('Start Signals', self.start_trading, 'Accent.TButton'), ('Stop Signals', self.stop_trading), ('Start My MT5 Trading', self.start_personal_trading), ('Stop My MT5 Trading', self.stop_personal_trading), ('Personal MT5 Settings', self.personal_settings), ('Start ngrok', self.start_ngrok)], controls=True)
        ttk.Checkbutton(parent, text='News Lock — block new entries', variable=self.news_var, command=self.toggle_news_lock).pack(anchor='w', pady=(0, 15))
        self.card_frame = ttk.Frame(parent)
        self.card_frame.pack(fill='x')
        self.cards = {}
        for key, title in (('signal_engine', 'Signal Engine'), ('personal', 'Personal MT5'), ('api', 'Owner API'), ('ngrok', 'Shared ngrok'), ('telegram', 'Telegram Bot'), ('notifications', 'Notifications'), ('news', 'News Lock'), ('pnl', 'Today PnL'), ('positions', 'Open Positions'), ('clients', 'Clients'), ('subscriptions', 'Subscription Alerts')):
            box = tk.Frame(self.card_frame, bg=ui.BG, highlightbackground=ui.EDGE, highlightthickness=1, padx=15, pady=12)
            tk.Label(box, text=title.upper(), bg=ui.BG, fg=ui.MUTED, font=('Segoe UI', 9)).pack(anchor='w')
            value = tk.Label(box, text='—', bg=ui.BG, fg=ui.TEXT, font=('Segoe UI Semibold', 16), anchor='w')
            value.pack(fill='x', pady=(5, 0))
            self.cards[key] = (box, value)
        self.card_frame.bind('<Configure>', self._layout_cards)
        self._title(parent, 'Floating positions', 'Snapshots are supplied by running personal, hosted and client workers. “—” means unavailable.')
        self._actions(parent, [('View All Trades', lambda: self.show_page('Trades'))])
        self.preview_tree = ui.make_table(parent, [('account','Account',160), ('symbol','Symbol',100), ('direction','Side',80), ('volume','Lots',70), ('pnl','Floating PnL',120), ('observed','Observed UTC',180)], height=4)

    def _layout_cards(self, event=None):
        width = max(200, self.card_frame.winfo_width())
        columns = max(1, min(4, width // 205))
        for column in range(4):
            self.card_frame.columnconfigure(column, weight=1 if column < columns else 0)
        for index, (box, _) in enumerate(self.cards.values()):
            box.grid(row=index//columns, column=index%columns, sticky='nsew', padx=(0, 9), pady=(0, 10))

    def _build_clients(self, parent):
        self._title(parent, 'Clients & access', 'Manage access, messages, payment review, promotions and configurable plans.')
        tabs = ttk.Notebook(parent)
        tabs.pack(fill='both', expand=True)
        client = ttk.Frame(tabs, padding=10)
        tabs.add(client, text='Clients')
        self._actions(client, [('Add', self.add_client, 'Accent.TButton'), ('Edit', self.edit_client), ('Accounts', self.client_accounts), ('Activate', lambda: self.change_status('ACTIVE')), ('Pause', lambda: self.change_status('PAUSED')), ('Revoke', lambda: self.change_status('REVOKED')), ('Delete / Archive', self.archive_client, 'Danger.TButton'), ('Subscription', self.manage_subscription), ('Issue 30-Day Trial', self.issue_distributor_trial), ('Revoke Trial', self.revoke_distributor_trial), ('Convert Trial', self.convert_distributor_trial), ('Message', self.message_client), ('Copy Pairing', self.copy_pairing), ('Hosted MT5', self.show_hosted_requests), ('Use PC Client', self.use_pc_mode), ('Refresh', self.refresh)])
        columns = [('name','Client',135), ('status','Status',85), ('subscription','Subscription',165), ('mode','Execution',100), ('mt5','MT5 Login',110), ('server','Server',150), ('telegram','Telegram',140), ('risk','Risk/Trade',90), ('open','Max Open',90), ('daily','Daily Loss',90), ('profit','Daily Target',100)]
        self.tree = ui.make_table(client, columns, height=12)
        self.tree.bind('<<TreeviewSelect>>', self.on_select)
        payments = ttk.Frame(tabs, padding=10)
        tabs.add(payments, text='Payments')
        self._actions(payments, [('Approve selected', lambda: self.review_payment(True)), ('Reject selected', lambda: self.review_payment(False)), ('View proof / hash', self.payment_details), ('Refresh', self.refresh)])
        self.payments_tree = ui.make_table(payments, [('id','ID',60), ('client','Client',130), ('plan','Plan',100), ('amount','Amount',110), ('method','Method',150), ('status','Status',100), ('created','Submitted UTC',180)], height=12)
        promos = ttk.Frame(tabs, padding=10)
        tabs.add(promos, text='Promo Codes')
        self._actions(promos, [('Create / Edit Code', self.edit_promo), ('Redemptions', self.promo_details), ('Disable selected', self.disable_promo), ('Refresh', self.refresh)])
        self.promos_tree = ui.make_table(promos, [('code','Code',170), ('plan','Plan',100), ('days','Days',60), ('max','Max Uses',90), ('used','Used',70), ('remaining','Remaining',90), ('accounts','MT5/User',90), ('enabled','Enabled',90), ('expires','Expires UTC',180)], height=12)
        plans = ttk.Frame(tabs, padding=10)
        tabs.add(plans, text='Plans & Referrals')
        self._actions(plans, [('Create / Edit Plan', self.edit_plan), ('Referral rewards', self.referral_settings), ('Refresh', self.refresh)])
        self.plans_tree = ui.make_table(plans, [('code','Plan',120), ('name','Name',180), ('amount','Price',130), ('days','Days',70), ('accounts','MT5 Limit',100), ('trial','Trial Days',100), ('enabled','Enabled',90)], height=9)

    def _build_trades(self, parent):
        self._title(parent, 'Trades', 'Stored UTC snapshots; display uses the timezone chosen in Settings. Broker SL/TP remain in place when trading is stopped.')
        self.trade_state = tk.StringVar(value='OPEN')
        filters = ttk.Frame(parent)
        filters.pack(fill='x')
        ttk.Combobox(filters, values=['OPEN', 'CLOSED', 'ALL'], textvariable=self.trade_state, state='readonly', width=14).pack(side='left', padx=(0, 10))
        self._actions(parent, [('Refresh', self.refresh), ('Render selected PnL card', self.render_selected_card)])
        self.trades_tree = ui.make_table(parent, [('scope','Account / Client',160), ('ticket','Ticket',105), ('symbol','Symbol',100), ('direction','Side',70), ('strategy','Strategy',140), ('volume','Lots',70), ('entry','Entry',100), ('current','Current / Exit',110), ('sl','SL',95), ('tp','TP',95), ('pnl','PnL',100), ('time','Time',190), ('result','Result',120)], height=14)
        self.trade_state.trace_add('write', lambda *_: self.refresh())
        self.trade_rows = {}

    def _build_journal(self, parent):
        self._title(parent, 'Daily journal', 'Daily boundaries follow your display timezone. Only observed broker records are included.')
        self.journal_date = tk.StringVar(value=datetime.now(timezone.utc).strftime('%Y-%m-%d'))
        ttk.Entry(parent, textvariable=self.journal_date, width=16).pack(anchor='w')
        self._actions(parent, [('Load Journal', self.refresh_journal), ('Render Journal Card', self.render_journal_card)])
        self.journal_summary = tk.StringVar(value='Waiting for account data.')
        ttk.Label(parent, textvariable=self.journal_summary, wraplength=800, style='Heading.TLabel').pack(fill='x', pady=(6, 15))
        self.journal_tree = ui.make_table(parent, [('scope','Account',180), ('ticket','Ticket',100), ('symbol','Symbol',100), ('strategy','Strategy',140), ('pnl','PnL',100), ('risk','Risk %',90), ('time','Closed',190), ('notes','Notes / Result',160)], height=12)

    def _build_telegram(self, parent):
        self._title(parent, 'Telegram & notifications', 'Delivery details, linked accounts and operational messages belong here.')
        self.telegram_summary = tk.StringVar(value='Connecting')
        label = ttk.Label(parent, textvariable=self.telegram_summary, wraplength=850)
        label.pack(fill='x', pady=10)
        parent.bind('<Configure>', lambda e: label.configure(wraplength=max(240, e.width-12)), add='+')
        self._actions(parent, [('Message selected client', self.message_client), ('Broadcast active clients', self.broadcast), ('Retry selected failed alert', self.retry_notification), ('Refresh', self.refresh), ('Open Logs', self.open_logs)])
        tabs = ttk.Notebook(parent)
        tabs.pack(fill='both', expand=True)
        self.telegram_trees = {}
        definitions = {
            'Linked Clients': [('client','Client',150), ('username','Username',160), ('chat','Chat ID',170)],
            'Delivery Queue': [('id','ID',120), ('kind','Audience',100), ('state','State',100), ('attempts','Attempts',85), ('message','Message',400), ('error','Last Issue',350)],
            'Notifications': [('time','UTC',190), ('kind','Type',120), ('message','Message',650)],
            'Commands': [('time','UTC',190), ('client','Client',120), ('command','Command',160), ('state','Result',160)],
        }
        for title, columns in definitions.items():
            frame = ttk.Frame(tabs, padding=8)
            tabs.add(frame, text=title)
            self.telegram_trees[title] = ui.make_table(frame, columns, height=10)
        self.telegram_trees['Linked Clients'].bind('<<TreeviewSelect>>', self._select_telegram_client)
        self.logs_text = tk.Text(parent, height=8, wrap='word', relief='flat', bg=ui.BG, fg=ui.MUTED, font=('Consolas', 9))
        self.logs_text.pack(fill='x', pady=12)

    def _build_risk(self, parent):
        self._title(parent, 'Risk controls', 'Owner limits can tighten client settings. Existing hard ceilings and News Lock remain enforced.')
        self._actions(parent, [('Global Risk Policy', self.show_global_risk_control), ('Select Client', lambda: self.show_page('Clients')), ('Save Client Policy', self.save_risk)])
        self.risk_trade = tk.StringVar(value='.9')
        self.risk_open = tk.StringVar(value='40')
        self.risk_daily = tk.StringVar(value='5')
        self.profit_daily = tk.StringVar(value='3')
        self.risk_trade_enabled = tk.BooleanVar(value=True)
        self.risk_open_enabled = tk.BooleanVar(value=True)
        self.risk_daily_enabled = tk.BooleanVar(value=True)
        self.profit_daily_enabled = tk.BooleanVar(value=False)
        self.selected_risk = tk.StringVar(value='Select a client on the Clients page.')
        ttk.Label(parent, textvariable=self.selected_risk, foreground=ui.GOLD).pack(anchor='w', pady=14)
        for label, var, enabled in [('Risk per trade %', self.risk_trade, self.risk_trade_enabled), ('Maximum open risk %', self.risk_open, self.risk_open_enabled), ('Daily loss limit %', self.risk_daily, self.risk_daily_enabled), ('Daily profit target %', self.profit_daily, self.profit_daily_enabled)]:
            box = ttk.LabelFrame(parent, text=label, padding=14)
            box.pack(fill='x', pady=7)
            ttk.Checkbutton(box, text='Use client override', variable=enabled).pack(side='left')
            ttk.Entry(box, textvariable=var, width=15).pack(side='right')

    def _build_settings(self, parent):
        self._title(parent, 'Workspace settings', 'UTC is stored internally. Timezone affects display and journal boundaries only.')
        ttk.Label(parent, text='Display timezone').pack(anchor='w', pady=(10, 5))
        ttk.Combobox(parent, textvariable=self.display_timezone, values=['UTC', 'Africa/Kampala', 'Europe/London', 'America/New_York', 'Asia/Dubai', 'Asia/Tokyo'], width=35).pack(anchor='w')
        self._actions(parent, [('Save timezone', self.save_timezone), ('Reconnect settings', self.reconnect_settings), ('Subscription reminders', self.reminder_settings), ('Personal MT5 Settings', self.personal_settings), ('Open Logs', self.open_logs)])
        self._title(parent, 'Shared infrastructure', 'ngrok runs independently and is reused by other projects. Its lifetime is separate from the Admin window.')
        self._actions(parent, [('Start ngrok', self.start_ngrok), ('Hosted MT5 Requests', self.show_hosted_requests)])
        self.settings_detail = tk.StringVar(value='')
        ttk.Label(parent, textvariable=self.settings_detail, wraplength=800, style='Muted.TLabel').pack(fill='x', pady=18)

    def _backend(self):
        from . import azt_store
        return azt_store

    def _guard(self, action):
        try:
            result = action()
            self.status.set(str(result) if isinstance(result, str) else 'Saved.')
            self.refresh()
            return result
        except Exception as exc:
            messagebox.showerror('AZT', str(exc), parent=self)

    def refresh(self):
        if not hasattr(self, 'tree'):
            return
        backend = self._backend()
        clients = store.list_clients()
        names = {c.id: c.name for c in clients}
        rows = []
        for c in clients:
            sub = backend.subscription_summary(c.id)
            rows.append((c.id, (c.name, c.status, f"{sub['subscription']['plan_code']} / {sub['effective_status']}", c.execution_mode, c.mt5_login or '—', c.mt5_server or '—', ('@'+c.telegram_username) if c.telegram_username else '—', f'{c.risk_per_trade_pct:.2f}%', f'{c.max_open_risk_pct:.1f}%', f'{c.max_daily_loss_pct:.1f}%', f'{c.daily_profit_target_pct:.1f}%' if c.daily_profit_target_enabled else 'OFF')))
        ui.set_rows(self.tree, rows)
        if self.selected_name:
            for key, values in rows:
                if values[0] == self.selected_name:
                    self.tree.selection_set(str(key))
        self.selected_risk.set('Client: '+self.selected_name if self.selected_name else 'Select a client on the Clients page.')
        self.news_var.set(store.news_lock_enabled())
        payments = backend.list_payments()
        self.payment_rows = {str(p['id']): p for p in payments}
        ui.set_rows(self.payments_tree, [(p['id'], (p['id'], names.get(p['client_id'], f"Archived #{p['client_id']}"), p.get('plan_code', ''), f"{p.get('amount', 0)} {p.get('currency','')}", p.get('method', p.get('provider','')), p['status'], p.get('created_utc',''))) for p in payments])
        promos = backend.promos()
        self.promo_rows = {p['code']: p for p in promos}
        ui.set_rows(self.promos_tree, [(p['code'], (p['code'], p['plan_code'], p['duration_days'], p['max_redemptions'], p.get('usage_count',0), p.get('remaining_uses','—'), p['max_mt5_accounts'], bool(p['enabled']), p.get('expires_utc',''))) for p in promos])
        plans = backend.plans()
        self.plan_rows = {p['code']: p for p in plans}
        ui.set_rows(self.plans_tree, [(p['code'], (p['code'], p['name'], 'Not configured' if p['amount'] is None else f"{p['amount']} {p['currency']}", p['duration_days'], p['max_mt5_accounts'], p['trial_days'], bool(p['enabled']))) for p in plans])
        ui.set_rows(self.telegram_trees['Linked Clients'], [(c.id, (c.name, c.telegram_username or '—', c.telegram_chat_id or 'Not linked')) for c in clients])
        self.refresh_trades()
        self.refresh_notifications()

    def refresh_trades(self):
        from .trade_telemetry import list_trades
        rows = list_trades(state=None if self.trade_state.get() == 'ALL' else self.trade_state.get())
        self.trade_rows = {str(i): row for i, row in enumerate(rows)}
        ui.set_rows(self.trades_tree, [(i, (row.get('account_key',''), row.get('ticket',''), row.get('symbol',''), row.get('direction',''), row.get('strategy') or '—', row.get('volume',''), row.get('entry',''), row.get('current_price', row.get('exit','')), row.get('sl',''), row.get('tp',''), row.get('pnl',row.get('profit',0)), self._time(row.get('closed_utc') or row.get('opened_utc') or row.get('observed_utc')), row.get('result',row.get('state','')))) for i,row in self.trade_rows.items()])
        open_rows = list_trades(state='OPEN', limit=6)
        ui.set_rows(self.preview_tree, [(i, (row.get('account_key',''), row.get('symbol',''), row.get('direction',''), row.get('volume',''), row.get('pnl',0), row.get('observed_utc',''))) for i,row in enumerate(open_rows)])

    def _time(self, value):
        if not value:
            return '—'
        from zoneinfo import ZoneInfo
        try:
            return datetime.fromisoformat(str(value).replace('Z','+00:00')).astimezone(ZoneInfo(self.display_timezone.get())).strftime('%Y-%m-%d %H:%M:%S %Z')
        except (ValueError, KeyError):
            return str(value)

    def refresh_journal(self):
        from .trade_telemetry import daily_journal
        try:
            report = daily_journal(date=self.journal_date.get(), timezone=self.display_timezone.get())
            self.current_journal = report
            pnl=report.get('pnl')
            pnl_text=f'{pnl:+.2f}' if pnl is not None else ', '.join(f'{currency} {amount:+.2f}' for currency,amount in report.get('pnl_by_currency',{}).items())
            self.journal_summary.set(f"{report.get('date',self.journal_date.get())}  ·  Trades {report.get('trades_taken',report.get('trade_count',0))}  ·  Wins {report.get('wins',0)}  ·  Losses {report.get('losses',0)}  ·  PnL {pnl_text}  ·  Win rate {report.get('win_rate',0):.1f}%\nRisk: {report.get('risk_used') if report.get('risk_used') is not None else 'Not recorded'}  ·  Strategies: {', '.join(report.get('strategies_used',[]))}")
            ui.set_rows(self.journal_tree, [(i,(r.get('account_key',''),r.get('ticket',''),r.get('symbol',''),r.get('strategy') or '—',r.get('pnl',0),r.get('risk_pct') if r.get('risk_pct') is not None else '—',self._time(r.get('closed_utc')),r.get('notes',r.get('result','')))) for i,r in enumerate(report.get('trades',[]))])
        except Exception as exc:
            self.status.set(str(exc))

    def refresh_notifications(self):
        from .client_notifications import delivery_rows, command_rows
        rows = delivery_rows()
        self.delivery_rows = {str(i): row for i,row in enumerate(rows)}
        ui.set_rows(self.telegram_trees['Delivery Queue'], [(i,(r['id'],r['kind'],r['state'],r['attempts'],r['message'],r.get('last_error',''))) for i,r in self.delivery_rows.items()])
        ui.set_rows(self.telegram_trees['Notifications'], [(i,(e.get('created_utc',''),e.get('kind',''),e.get('message',e.get('body','')))) for i,e in enumerate(self._backend().system_events())])
        ui.set_rows(self.telegram_trees['Commands'], [(i,(e['created_utc'],e.get('client_id') or '—',e['command'],e['state'])) for i,e in enumerate(command_rows())])
        if self.services:
            self.telegram_summary.set('Bot: '+self.services.runtime_status('telegram')+'\nOwner alerts: '+self.services.runtime_status('notifications'))
            lines = []
            for name in ('telegram','notifications','maintenance'):
                path = self.services.logs/(name+'.log')
                if path.exists():
                    with path.open('rb') as stream:
                        stream.seek(max(0,path.stat().st_size-2200))
                        text=stream.read().decode('utf-8','replace')
                        text=re.sub(r'(?:bot)?[0-9]{5,}:[A-Za-z0-9_-]{20,}','[redacted bot token]',text)
                        lines.append(name.upper()+'\n'+text)
            self.logs_text.configure(state='normal')
            self.logs_text.delete('1.0','end')
            self.logs_text.insert('1.0','\n'.join(lines))
            self.logs_text.configure(state='disabled')

    def update_services(self):
        if self.closing:
            return
        try:
            self._update_cards()
            if self.page_name.get() in {'Telegram','Trades','Clients'}:
                self.refresh()
        except Exception as exc:
            self.status.set('Status refresh: '+str(exc))
        self.after(4000, self.update_services)

    def _update_cards(self):
        backend = self._backend()
        clients = store.list_clients()
        for name in ('signal_engine','personal','telegram','notifications'):
            text = self.services.runtime_status(name) if self.services else 'off'
            value = text.split(':',1)[0]
            if self.services and name in self.services.processes and self.services.processes[name].poll() is not None:
                value = 'OFFLINE'
            self.cards[name][1].configure(text=value[:23], fg=ui.GREEN if value in {'READY','SCANNING','CONNECTED','IDLE','DELIVERED'} else ui.MUTED if value.lower() in {'off','stopped','starting'} else ui.GOLD)
        health = self.services.health if self.services else ''
        api_ok = 'API: healthy' in health
        self.cards['api'][1].configure(text='Connected' if api_ok else 'Offline', fg=ui.GREEN if api_ok else ui.RED)
        tunnel_ok = 'ngrok: https://' in health
        self.cards['ngrok'][1].configure(text='Connected' if tunnel_ok else 'No tunnel', fg=ui.GREEN if tunnel_ok else ui.MUTED)
        self.cards['news'][1].configure(text='Blocking Entries' if store.news_lock_enabled() else 'Entries Allowed', fg=ui.GOLD if store.news_lock_enabled() else ui.GREEN)
        self.cards['clients'][1].configure(text=str(len(clients)))
        alerts = sum(backend.subscription_summary(c.id)['effective_status'] in {'EXPIRING SOON','EXPIRED','PAST_DUE'} for c in clients)
        self.cards['subscriptions'][1].configure(text=str(alerts), fg=ui.GOLD if alerts else ui.GREEN)
        from .trade_telemetry import overview
        snapshot = overview(timezone=self.display_timezone.get())
        observed = snapshot.get('accounts') or snapshot.get('account_count') or snapshot.get('observed_utc')
        pnl = snapshot.get('today_pnl', snapshot.get('pnl'))
        mixed=len(snapshot.get('today_pnl_by_currency',{}))>1
        self.cards['pnl'][1].configure(text='Multiple currencies' if mixed else f'{pnl:+.2f}' if pnl is not None and observed else '—', fg=ui.GREEN if (pnl or 0)>=0 else ui.RED)
        self.cards['positions'][1].configure(text=str(snapshot.get('open_positions',snapshot.get('position_count','—'))) if observed else '—')
        self.compact_status.set('API connected' if api_ok else 'API offline')
        self._paint_header()

    def edit_client(self):
        client = self._selected_client_record()
        if not client:
            return
        pref = self._backend().preferences(client.id)
        summary = self._backend().subscription_summary(client.id)
        ui.form_dialog(self,'Edit Client', [('name','Name',client.name),('telegram_username','Telegram username',client.telegram_username),('max_mt5_accounts','Maximum MT5 accounts',summary['max_mt5_accounts']),('display_timezone','Display timezone',pref.get('display_timezone','UTC'))], lambda v:self._guard(lambda:self._backend().edit_client(client.id, name=v['name'],telegram_username=v['telegram_username'],max_mt5_accounts=int(v['max_mt5_accounts']),display_timezone=v['display_timezone'])))

    def client_accounts(self):
        client=self._selected_client_record()
        if client:
            window=tk.Toplevel(self)
            window.title(client.name+' • MT5 Accounts')
            window.geometry('760x500')
            tabs=ttk.Notebook(window)
            tabs.pack(fill='both',expand=True,padx=10,pady=10)
            accounts_page=ttk.Frame(tabs)
            deliveries_page=ttk.Frame(tabs)
            tabs.add(accounts_page,text='MT5 Accounts')
            tabs.add(deliveries_page,text='Execution Review')
            table=ui.make_table(accounts_page,[('id','ID',60),('login','Login',120),('server','Broker server',190),('status','Status',120)],height=7)
            deliveries=ui.make_table(deliveries_page,[('instruction','Instruction',100),('account','Account ID',100),('status','State',120),('signal','Signal',350),('dispatched','Dispatched UTC',200)],height=7)
            delivery_rows={}
            def load():
                ui.set_rows(table,[(a['id'],(a['id'],a['login'],a['server'],a['status'])) for a in self._backend().list_accounts(client.id)])
                rows=self._backend().instruction_deliveries(client.id)
                delivery_rows.clear()
                delivery_rows.update({str(index):row for index,row in enumerate(rows)})
                ui.set_rows(deliveries,[(index,(row['instruction_id'],row['account_id'],row['status'],row.get('signal_key',''),row.get('dispatched_utc',''))) for index,row in delivery_rows.items()])
            def change(enabled):
                selection=table.selection()
                if not selection:
                    return
                if not messagebox.askyesno('MT5 account access',('Enable' if enabled else 'Disable')+' this account for new automated entries? Existing positions remain at the broker.',parent=window):
                    return
                self._guard(lambda:(self._backend().enable_account if enabled else self._backend().disable_account)(client.id,int(selection[0])))
                load()
            footer=ttk.Frame(window,padding=10)
            footer.pack(fill='x')
            ttk.Button(footer,text='Disable selected',command=lambda:change(False)).pack(side='left',padx=5)
            ttk.Button(footer,text='Enable selected',command=lambda:change(True)).pack(side='left',padx=5)
            def resolve():
                selection=deliveries.selection()
                if not selection:
                    return
                row=delivery_rows[selection[0]]
                if row['status']!='DISPATCHED':
                    messagebox.showinfo('Execution review','Only an unresolved DISPATCHED instruction can be resolved.',parent=window)
                    return
                if not messagebox.askyesno('Confirm broker reconciliation','Check the actual MT5 account history first. This marks the uncertain delivery reviewed and permits fresh signals. It will NEVER resend this instruction. Have you reconciled it with the broker?',parent=window):
                    return
                note=simpledialog.askstring('Reconciliation note','Record what you confirmed in MT5:',parent=window)
                if note and note.strip():
                    self._guard(lambda:self._backend().resolve_delivery(client.id,row['account_id'],row['instruction_id'],note.strip()))
                    load()
            ttk.Button(footer,text='Resolve selected delivery',command=resolve).pack(side='left',padx=5)
            ttk.Button(footer,text='Close',command=window.destroy).pack(side='right')
            load()

    def _select_telegram_client(self,_event=None):
        selection=self.telegram_trees['Linked Clients'].selection()
        if selection:
            client=store.client_by_id(int(selection[0]))
            if client:
                self.selected_name=client.name
                self.selected_risk.set('Client: '+client.name)

    def archive_client(self):
        client = self._selected_client_record()
        if client and messagebox.askyesno('Archive client',f'Archive {client.name}? New trading and sessions will be blocked. Historical trades, messages and payments will be retained.',parent=self):
            self._guard(lambda:self._backend().archive_client(client.id))
            self.selected_name=''
            self.refresh()

    def manage_subscription(self):
        client = self._selected_client_record()
        if not client:
            return
        summary = self._backend().subscription_summary(client.id)
        sub=summary['subscription']
        ui.form_dialog(self,'Renew / Extend Subscription', [('plan_code','Plan',sub['plan_code']),('days','Duration in days',30),('max_mt5_accounts','MT5 account limit',summary['max_mt5_accounts'])],lambda v:self._guard(lambda:self._backend().renew_subscription(client.id,int(v['days']),plan_code=v['plan_code'],max_mt5_accounts=int(v['max_mt5_accounts']))),description='An active expiry is extended from its current end. Expired access restarts from now. Payment approvals also extend automatically.')

    def message_client(self):
        client=self._selected_client_record()
        if not client:
            return
        self._message_dialog(client)

    def broadcast(self):
        self._message_dialog(None)

    def _message_dialog(self,client):
        def send(v):
            backend=self._backend()
            if client:
                backend.send_message(client.id,v['title'],v['body'],also_telegram=v['telegram']=='Yes')
            else:
                backend.broadcast_message(v['title'],v['body'],also_telegram=v['telegram']=='Yes')
            self.status.set('Message saved for in-app delivery. Optional Telegram copies are queued.')
        ui.form_dialog(self,'Message '+(client.name if client else 'All Active Clients'), [('title','Title','AZT Update'),('body','Message',''),('telegram','Also send Telegram copy','No',['No','Yes'])], send,description='Clients receive this in their app even without Telegram. Telegram copies go only to linked chats.')

    def edit_plan(self):
        selected=self.plans_tree.selection()
        p=self.plan_rows.get(selected[0],{}) if selected else {}
        def save(v):
            self._backend().save_plan(v['code'],name=v['name'],amount=float(v['amount']) if v['amount'] else None,currency=v['currency'],duration_days=int(v['days']),max_mt5_accounts=int(v['accounts']),trial_days=int(v['trial']),enabled=v['enabled']=='Yes')
            self.refresh()
        ui.form_dialog(self,'Plan Configuration',[('code','Plan code',p.get('code','')),('name','Display name',p.get('name','')),('amount','Price (blank until decided)',p.get('amount')),('currency','Currency',p.get('currency','USD')),('days','Paid duration days',p.get('duration_days',30)),('accounts','Maximum MT5 accounts',p.get('max_mt5_accounts',1)),('trial','Trial days',p.get('trial_days',7)),('enabled','Enabled','Yes' if p.get('enabled',True) else 'No',['Yes','No'])],save)

    def edit_promo(self):
        selected=self.promos_tree.selection()
        p=self.promo_rows.get(selected[0],{}) if selected else {}
        def save(v):
            self._backend().save_promo(v['code'],plan_code=v['plan'],duration_days=int(v['days']),max_redemptions=int(v['uses']),max_mt5_accounts=int(v['accounts']),expires_utc=v['expires'],enabled=v['enabled']=='Yes',one_use_per_user=v['once']=='Yes')
            self.refresh()
        ui.form_dialog(self,'Giveaway / Promo Code',[('code','Code',p.get('code','AZT-GIVEAWAY')),('plan','Plan granted',p.get('plan_code','STARTER')),('days','Access days',p.get('duration_days',30)),('uses','Maximum redemptions',p.get('max_redemptions',20)),('accounts','MT5 accounts per user',p.get('max_mt5_accounts',2)),('expires','Expiry UTC (ISO, blank = none)',p.get('expires_utc','')),('enabled','Enabled','Yes' if p.get('enabled',True) else 'No',['Yes','No']),('once','One use per user','Yes' if p.get('one_use_per_user',True) else 'No',['Yes','No'])],save)

    def disable_promo(self):
        selected=self.promos_tree.selection()
        if selected:
            p=self.promo_rows[selected[0]]
            self._guard(lambda:self._backend().save_promo(p['code'],plan_code=p['plan_code'],duration_days=p['duration_days'],max_redemptions=p['max_redemptions'],max_mt5_accounts=p['max_mt5_accounts'],expires_utc=p.get('expires_utc',''),enabled=False,one_use_per_user=bool(p['one_use_per_user'])))

    def promo_details(self):
        selected=self.promos_tree.selection()
        if selected:
            self._show_text('Promo Redemptions',json.dumps(self._backend().promo_redemptions(selected[0]),indent=2,default=str))

    def referral_settings(self):
        current=self._backend().referral_settings()
        ui.form_dialog(self,'Referral Rewards',[('enabled','Enable rewards','Yes' if current['enabled'] else 'No',['No','Yes']),('mode','Reward type',current['mode'],['PERCENT','FIXED']),('value','Reward value',current['value']),('currency','Fixed reward currency',current['currency']),('recurring','Reward renewals','Yes' if current['recurring'] else 'No',['No','Yes'])],lambda v:self._backend().set_referral_settings(enabled=v['enabled']=='Yes',mode=v['mode'],value=float(v['value']),recurring=v['recurring']=='Yes',currency=v['currency']),description='No commission is assumed. Set and enable a policy only after agreeing subscription pricing. Rewards follow approved payments.')

    def payment_details(self):
        selected=self.payments_tree.selection()
        if selected:
            record=dict(self.payment_rows[selected[0]])
            proof=record.pop('proof','')
            self._show_text('Payment Submission',json.dumps(record,indent=2,default=str))
            if proof.startswith('data:image/'):
                import base64,io
                from PIL import Image,ImageTk
                window=tk.Toplevel(self)
                window.title('Payment proof • manual verification')
                window.geometry('750x650')
                with Image.open(io.BytesIO(base64.b64decode(proof.split(',',1)[1],validate=True))) as image:
                    image.thumbnail((700,560))
                    window._proof_image=ImageTk.PhotoImage(image.copy())
                ttk.Label(window,image=window._proof_image).pack(fill='both',expand=True)
                ttk.Button(window,text='Close',command=window.destroy).pack(pady=10)

    def review_payment(self,approve):
        selected=self.payments_tree.selection()
        if not selected:
            self.status.set('Select a payment submission first.')
            return
        if messagebox.askyesno('Review Payment',('Approve' if approve else 'Reject')+' this payment? Approval grants the configured plan duration once. Verify the proof independently before approving.',parent=self):
            note=simpledialog.askstring('Payment review','Review note (optional):',parent=self) or ''
            self._guard(lambda:self._backend().review_payment(int(selected[0]),approve,note=note))

    def retry_notification(self):
        selected=self.telegram_trees['Delivery Queue'].selection()
        if selected and messagebox.askyesno('Retry alert','Retry this failed alert? A previous timeout can mean Telegram already received it, so the message could repeat. No trade will be retried.',parent=self):
            from .client_notifications import retry_delivery
            self._guard(lambda:retry_delivery(self.delivery_rows[selected[0]]))

    def open_logs(self):
        if self.services:
            os.startfile(str(self.services.logs))

    def _show_text(self,title,text):
        window=tk.Toplevel(self)
        window.title(title)
        window.geometry('760x500')
        box=tk.Text(window,wrap='word',bg=ui.BG,fg=ui.TEXT,padx=20,pady=20)
        box.pack(fill='both',expand=True)
        box.insert('1.0',text)
        box.configure(state='disabled')
        ttk.Button(window,text='Close',command=window.destroy).pack(pady=10)

    def save_timezone(self):
        from zoneinfo import ZoneInfo
        def save():
            ZoneInfo(self.display_timezone.get())
            from .workspace_settings import save_settings
            save_settings(display_timezone=self.display_timezone.get())
            self.refresh()
        self._guard(save)

    def reconnect_settings(self):
        from .workspace_settings import load_settings,save_settings
        current=load_settings()
        ui.form_dialog(self,'Reconnect Settings',[('retry_interval','Initial retry seconds',current['retry_interval']),('retry_cap','Maximum retry seconds',current['retry_cap']),('retries_before_alert','Failures before alert',current['retries_before_alert']),('alert_cooldown','Alert cooldown seconds',current['alert_cooldown'])],lambda v:save_settings(**{key:float(value) for key,value in v.items()}))

    def reminder_settings(self):
        from .workspace_settings import load_settings,save_settings
        current=load_settings()
        ui.form_dialog(self,'Subscription Reminders',[('reminder_days','Days before expiry (comma separated)',','.join(str(x) for x in current['reminder_days']))],lambda v:save_settings(reminder_days=[int(x.strip()) for x in v['reminder_days'].split(',') if x.strip()]))

    def render_selected_card(self):
        selected=self.trades_tree.selection()
        if selected:
            from .pnl_cards import render_trade_card
            self._guard(lambda:self._open_card(render_trade_card(self.trade_rows[selected[0]],display_timezone=self.display_timezone.get())))

    def render_journal_card(self):
        self.refresh_journal()
        if getattr(self,'current_journal',None):
            from .pnl_cards import render_journal_card
            self._guard(lambda:self._open_card(render_journal_card(self.current_journal,display_timezone=self.display_timezone.get())))

    def _open_card(self,path):
        os.startfile(str(path))
        return 'Rendered copy: '+str(path)
