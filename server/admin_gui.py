from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from server.client_telegram import send_client_message
from server.hosted_manager import provision_instance, start_worker, stop_worker, worker_log_path
from server.store import (
    create_client,
    get_global_risk_policy,
    list_clients,
    list_hosted_accounts,
    news_lock_enabled,
    set_client_risk,
    set_subscription,
    subscription_access,
    subscription_for_client,
    set_execution_mode,
    set_global_risk_policy,
    set_hosted_account_status,
    set_news_lock,
    set_status,
)


class GoldAIAdmin(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GOLD_AI Admin • Risk, Clients & Subscriptions")
        self.geometry("1180x760")
        self.minsize(1080, 680)
        self.selected_name = ""
        self._build()
        self.refresh()

    def _build(self):
        top = ttk.Frame(self, padding=14)
        top.pack(fill="x")
        ttk.Label(top, text="GOLD_AI ADMIN", font=("Segoe UI", 20, "bold")).pack(side="left")
        self.news_var = tk.BooleanVar(value=news_lock_enabled())
        ttk.Checkbutton(
            top,
            text="NEWS LOCK — BLOCK NEW ENTRIES",
            variable=self.news_var,
            command=self.toggle_news_lock,
        ).pack(side="right")

        body = ttk.Frame(self, padding=(14, 0, 14, 14))
        body.pack(fill="both", expand=True)

        cols = ("name", "status", "subscription", "mode", "mt5", "server", "telegram", "risk", "open", "daily", "profit")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", height=18)
        headings = {
            "name":"Client","status":"Status","subscription":"Subscription","mode":"Execution","mt5":"MT5 Login","server":"MT5 Server",
            "telegram":"Telegram","risk":"Risk/Trade","open":"Max Open","daily":"Daily Loss","profit":"Daily Target"
        }
        widths = {"name":115,"status":80,"subscription":95,"mode":90,"mt5":95,"server":135,"telegram":105,"risk":75,"open":75,"daily":75,"profit":80}
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 6))
        ttk.Button(buttons, text="Add Client", command=self.add_client).pack(side="left")
        ttk.Button(buttons, text="Activate", command=lambda:self.change_status("ACTIVE")).pack(side="left", padx=4)
        ttk.Button(buttons, text="Pause", command=lambda:self.change_status("PAUSED")).pack(side="left", padx=4)
        ttk.Button(buttons, text="Revoke", command=lambda:self.change_status("REVOKED")).pack(side="left", padx=4)
        ttk.Button(buttons, text="Expire", command=lambda:self.change_status("EXPIRED")).pack(side="left", padx=4)
        ttk.Button(buttons, text="Copy Pairing Code", command=self.copy_pairing).pack(side="left", padx=(16,4))
        ttk.Button(buttons, text="Hosted MT5 Requests", command=self.show_hosted_requests).pack(side="left", padx=(16,4))
        ttk.Button(buttons, text="Global Risk Control", command=self.show_global_risk_control).pack(side="left", padx=4)
        ttk.Button(buttons, text="Message Client", command=self.message_client).pack(side="left", padx=4)
        ttk.Button(buttons, text="Subscription", command=self.manage_subscription).pack(side="left", padx=4)
        ttk.Button(
            buttons,
            text="Use PC Client",
            command=self.use_pc_mode,
        ).pack(side="right", padx=4)
        ttk.Button(buttons, text="Refresh", command=self.refresh).pack(side="right")

        risk = ttk.LabelFrame(body, text="Selected Client Risk Control", padding=10)
        risk.pack(fill="x", pady=(6,0))

        self.risk_trade = tk.StringVar(value="0.9")
        self.risk_open = tk.StringVar(value="40")
        self.risk_daily = tk.StringVar(value="5")
        self.profit_daily = tk.StringVar(value="3")
        self.risk_trade_enabled = tk.BooleanVar(value=True)
        self.risk_open_enabled = tk.BooleanVar(value=True)
        self.risk_daily_enabled = tk.BooleanVar(value=True)
        self.profit_daily_enabled = tk.BooleanVar(value=False)

        controls = (
            ("Risk / trade %", self.risk_trade, self.risk_trade_enabled),
            ("Max open risk %", self.risk_open, self.risk_open_enabled),
            ("Max daily loss %", self.risk_daily, self.risk_daily_enabled),
            ("Daily profit target %", self.profit_daily, self.profit_daily_enabled),
        )
        for label, var, enabled_var in controls:
            box = ttk.Frame(risk)
            box.pack(side="left", padx=(0,14))
            ttk.Checkbutton(box, text=label, variable=enabled_var).pack(anchor="w")
            ttk.Entry(box, textvariable=var, width=12).pack(anchor="w", pady=(3,0))

        ttk.Button(
            risk,
            text="Save Client Policy",
            command=self.save_risk,
        ).pack(side="left", padx=10, pady=(18,0))

        ttk.Label(
            risk,
            text="Unchecked = inherit owner/global policy. Hard safety ceilings still apply.",
        ).pack(side="left", padx=(12,0), pady=(18,0))

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(body, textvariable=self.status).pack(anchor="w", pady=(10,0))

    def refresh(self):
        current = self.selected_name
        for item in self.tree.get_children():
            self.tree.delete(item)
        selected_item = None
        for c in list_clients():
            sub_state = subscription_access(c.id)
            sub = sub_state["subscription"]
            item = self.tree.insert("", "end", values=(
                c.name,
                c.status,
                f"{sub.get('plan_code','STARTER')} / {sub.get('status','TRIAL')}",
                c.execution_mode,
                c.mt5_login or "-",
                c.mt5_server or "-",
                f"@{c.telegram_username}" if c.telegram_username else "-",
                f"{c.risk_per_trade_pct:.2f}%",
                f"{c.max_open_risk_pct:.1f}%",
                f"{c.max_daily_loss_pct:.1f}%",
                f"{c.daily_profit_target_pct:.1f}%" if c.daily_profit_target_enabled else "OFF",
            ))
            if c.name == current:
                selected_item = item
        if selected_item:
            self.tree.selection_set(selected_item)
            self.tree.focus(selected_item)
        self.news_var.set(news_lock_enabled())

    def on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        self.selected_name = str(vals[0])
        for c in list_clients():
            if c.name == self.selected_name:
                self.risk_trade.set(str(c.risk_per_trade_pct))
                self.risk_open.set(str(c.max_open_risk_pct))
                self.risk_daily.set(str(c.max_daily_loss_pct))
                self.profit_daily.set(str(c.daily_profit_target_pct))
                self.risk_trade_enabled.set(bool(c.risk_per_trade_enabled))
                self.risk_open_enabled.set(bool(c.max_open_risk_enabled))
                self.risk_daily_enabled.set(bool(c.max_daily_loss_enabled))
                self.profit_daily_enabled.set(bool(c.daily_profit_target_enabled))
                break

    def add_client(self):
        name = simpledialog.askstring("Add Client", "Friendly client name:", parent=self)
        if not name:
            return
        try:
            client, code = create_client(name.strip())
            self.selected_name = client.name
            self.clipboard_clear()
            self.clipboard_append(code)
            self.status.set(f"{client.name} created. Pairing code copied to clipboard.")
            messagebox.showinfo("Client Created", f"Client: {client.name}\nPairing code: {code}\n\nCode copied.")
            self.refresh()
        except Exception as exc:
            messagebox.showerror("GOLD_AI Admin", str(exc))

    def change_status(self, status):
        if not self.selected_name:
            messagebox.showwarning("GOLD_AI Admin", "Select a client first.")
            return
        try:
            set_status(self.selected_name, status)
            self.status.set(f"{self.selected_name} → {status}")
            self.refresh()
        except Exception as exc:
            messagebox.showerror("GOLD_AI Admin", str(exc))

    def use_pc_mode(self):
        if not self.selected_name:
            messagebox.showwarning("GOLD_AI Admin", "Select a client first.")
            return
        for c in list_clients():
            if c.name == self.selected_name:
                try:
                    set_execution_mode(c.id, "CLIENT_PC")
                    self.status.set(f"{c.name} execution mode → CLIENT_PC")
                    self.refresh()
                except Exception as exc:
                    messagebox.showerror("GOLD_AI Admin", str(exc))
                return

    def copy_pairing(self):
        if not self.selected_name:
            messagebox.showwarning("GOLD_AI Admin", "Select a client first.")
            return
        for c in list_clients():
            if c.name == self.selected_name:
                self.clipboard_clear()
                self.clipboard_append(c.pairing_code)
                self.status.set(f"{c.name} pairing code copied.")
                return

    def save_risk(self):
        if not self.selected_name:
            messagebox.showwarning("GOLD_AI Admin", "Select a client first.")
            return
        try:
            set_client_risk(
                self.selected_name,
                float(self.risk_trade.get()),
                float(self.risk_open.get()),
                float(self.risk_daily.get()),
                risk_per_trade_enabled=bool(self.risk_trade_enabled.get()),
                max_open_risk_enabled=bool(self.risk_open_enabled.get()),
                max_daily_loss_enabled=bool(self.risk_daily_enabled.get()),
                daily_profit_target_enabled=bool(self.profit_daily_enabled.get()),
                daily_profit_target_pct=float(self.profit_daily.get()),
            )
            self.status.set(f"{self.selected_name} risk settings saved.")
            self.refresh()
        except Exception as exc:
            messagebox.showerror("Risk Settings", str(exc))

    def _selected_client_record(self):
        if not self.selected_name:
            messagebox.showwarning("GOLD_AI Admin", "Select a client first.")
            return None
        for client in list_clients():
            if client.name == self.selected_name:
                return client
        messagebox.showwarning("GOLD_AI Admin", "Selected client no longer exists.")
        return None

    def message_client(self):
        client = self._selected_client_record()
        if client is None:
            return
        if not client.telegram_chat_id:
            messagebox.showwarning(
                "Client Messaging",
                "This client has not linked Telegram yet. Ask them to use /link PAIRING_CODE.",
            )
            return

        text = simpledialog.askstring(
            "Message Client",
            f"Message to {client.name}:",
            parent=self,
        )
        if not text:
            return
        try:
            send_client_message(int(client.telegram_chat_id), text.strip())
            self.status.set(f"Telegram message sent to {client.name}.")
        except Exception as exc:
            messagebox.showerror("Client Messaging", str(exc))

    def manage_subscription(self):
        client = self._selected_client_record()
        if client is None:
            return

        sub = subscription_for_client(client.id)
        window = tk.Toplevel(self)
        window.title(f"Subscription — {client.name}")
        window.geometry("560x420")
        window.resizable(False, False)

        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text=f"{client.name} — Subscription",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w", pady=(0, 14))

        plan = tk.StringVar(value=sub.get("plan_code", "STARTER"))
        status = tk.StringVar(value=sub.get("status", "TRIAL"))
        starts = tk.StringVar(value=sub.get("starts_utc", ""))
        expires = tk.StringVar(value=sub.get("expires_utc", ""))
        auto_renew = tk.BooleanVar(value=bool(sub.get("auto_renew", 0)))

        rows = (
            ("Plan", plan),
            ("Status", status),
            ("Starts UTC", starts),
            ("Expires UTC", expires),
        )
        for label, var in rows:
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=7)
            ttk.Label(row, text=label, width=18).pack(side="left")
            ttk.Entry(row, textvariable=var, width=38).pack(side="left", fill="x", expand=True)

        ttk.Checkbutton(
            frame,
            text="Auto-renew enabled",
            variable=auto_renew,
        ).pack(anchor="w", pady=(12, 8))

        ttk.Label(
            frame,
            text=(
                "Suggested statuses: TRIAL, ACTIVE, PAST_DUE, EXPIRED, CANCELLED. "
                "Dates should use ISO format, e.g. 2026-11-23T00:00:00+00:00."
            ),
            wraplength=500,
        ).pack(anchor="w", pady=(0, 16))

        def save_subscription():
            try:
                saved = set_subscription(
                    client.id,
                    plan_code=plan.get(),
                    status=status.get(),
                    starts_utc=starts.get().strip(),
                    expires_utc=expires.get().strip(),
                    auto_renew=bool(auto_renew.get()),
                )
                self.status.set(
                    f"{client.name} subscription → {saved['plan_code']} / {saved['status']}"
                )
                messagebox.showinfo(
                    "Subscription",
                    "Subscription saved.",
                    parent=window,
                )
            except Exception as exc:
                messagebox.showerror("Subscription", str(exc), parent=window)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Save Subscription", command=save_subscription).pack(side="left")
        ttk.Button(buttons, text="Close", command=window.destroy).pack(side="right")

    def show_global_risk_control(self):
        policy = get_global_risk_policy()

        window = tk.Toplevel(self)
        window.title("GOLD_AI Global Risk Control")
        window.geometry("620x430")
        window.resizable(False, False)

        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="GLOBAL OWNER RISK POLICY",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text=(
                "These limits apply across all clients. A client's enabled custom value "
                "can only make the policy stricter, never exceed the hard GOLD_AI ceiling."
            ),
            wraplength=560,
        ).pack(anchor="w", pady=(4,14))

        vars_enabled = {
            "risk": tk.BooleanVar(value=policy["risk_per_trade_enabled"]),
            "open": tk.BooleanVar(value=policy["max_open_risk_enabled"]),
            "loss": tk.BooleanVar(value=policy["max_daily_loss_enabled"]),
            "profit": tk.BooleanVar(value=policy["daily_profit_target_enabled"]),
        }
        vars_value = {
            "risk": tk.StringVar(value=str(policy["risk_per_trade_pct"])),
            "open": tk.StringVar(value=str(policy["max_open_risk_pct"])),
            "loss": tk.StringVar(value=str(policy["max_daily_loss_pct"])),
            "profit": tk.StringVar(value=str(policy["daily_profit_target_pct"])),
        }

        rows = (
            ("risk", "Maximum risk per trade", "Hard ceiling: 2%"),
            ("open", "Maximum overall/open risk", "Hard ceiling: 40%"),
            ("loss", "Maximum daily loss", "Hard ceiling: 10%"),
            ("profit", "Daily profit target", "Stops new entries after target"),
        )
        for key, label, note in rows:
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=7)
            ttk.Checkbutton(row, text=label, variable=vars_enabled[key]).pack(side="left")
            ttk.Entry(row, textvariable=vars_value[key], width=12).pack(side="left", padx=12)
            ttk.Label(row, text=f"%   {note}").pack(side="left")

        def save_global():
            try:
                set_global_risk_policy(
                    risk_per_trade_enabled=bool(vars_enabled["risk"].get()),
                    risk_per_trade_pct=float(vars_value["risk"].get()),
                    max_open_risk_enabled=bool(vars_enabled["open"].get()),
                    max_open_risk_pct=float(vars_value["open"].get()),
                    max_daily_loss_enabled=bool(vars_enabled["loss"].get()),
                    max_daily_loss_pct=float(vars_value["loss"].get()),
                    daily_profit_target_enabled=bool(vars_enabled["profit"].get()),
                    daily_profit_target_pct=float(vars_value["profit"].get()),
                )
                self.status.set("Global risk policy saved.")
                messagebox.showinfo(
                    "GOLD_AI Risk Control",
                    "Global owner risk policy saved.",
                    parent=window,
                )
            except Exception as exc:
                messagebox.showerror("Risk Control", str(exc), parent=window)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(20,0))
        ttk.Button(buttons, text="Save Global Policy", command=save_global).pack(side="left")
        ttk.Button(buttons, text="Close", command=window.destroy).pack(side="right")

    def show_hosted_requests(self):
        window = tk.Toplevel(self)
        window.title("Hosted MT5 Manager")
        window.geometry("1180x520")
        window.minsize(980, 430)

        cols = (
            "client", "login", "server", "status", "pid",
            "balance", "equity", "seen", "error",
        )
        tree = ttk.Treeview(window, columns=cols, show="headings")
        headings = {
            "client": "Client",
            "login": "MT5 Login",
            "server": "MT5 Server",
            "status": "Status",
            "pid": "Worker PID",
            "balance": "Balance",
            "equity": "Equity",
            "seen": "Last Seen UTC",
            "error": "Last Error",
        }
        widths = {
            "client": 120,
            "login": 105,
            "server": 150,
            "status": 95,
            "pid": 90,
            "balance": 90,
            "equity": 90,
            "seen": 180,
            "error": 250,
        }
        for col in cols:
            tree.heading(col, text=headings[col])
            tree.column(col, width=widths[col], anchor="center")
        tree.pack(fill="both", expand=True, padx=12, pady=(12, 6))

        item_to_client_id = {}
        selected_client_id_value = {"id": None}

        def load_rows():
            previous_client_id = selected_client_id_value["id"]
            for item in tree.get_children():
                tree.delete(item)
            item_to_client_id.clear()
            preferred_item = None
            for row in list_hosted_accounts():
                item = tree.insert(
                    "",
                    "end",
                    values=(
                        row["client_name"],
                        row["mt5_login"],
                        row["mt5_server"],
                        row["status"],
                        row.get("worker_pid") or "-",
                        (
                            f'{float(row["account_balance"]):.2f}'
                            if row.get("account_balance") is not None else "-"
                        ),
                        (
                            f'{float(row["account_equity"]):.2f}'
                            if row.get("account_equity") is not None else "-"
                        ),
                        row.get("last_seen_utc") or "-",
                        row.get("last_error") or "-",
                    ),
                )
                client_id = int(row["client_id"])
                item_to_client_id[item] = client_id
                if previous_client_id == client_id:
                    preferred_item = item

            if preferred_item is None:
                children = tree.get_children()
                if children:
                    preferred_item = children[0]

            if preferred_item is not None:
                tree.selection_set(preferred_item)
                tree.focus(preferred_item)
                selected_client_id_value["id"] = item_to_client_id.get(preferred_item)

        def remember_selection(_event=None):
            selection = tree.selection()
            if selection:
                selected_client_id_value["id"] = item_to_client_id.get(selection[0])

        tree.bind("<<TreeviewSelect>>", remember_selection)

        def selected_client_id():
            selection = tree.selection()
            if not selection:
                messagebox.showwarning(
                    "Hosted MT5",
                    "Select a hosted MT5 request first.",
                    parent=window,
                )
                return None
            return item_to_client_id.get(selection[0])

        def change_hosted_status(status):
            client_id = selected_client_id()
            if client_id is None:
                return
            try:
                if status == "APPROVED":
                    set_execution_mode(client_id, "HOSTED")
                if status == "DISABLED":
                    try:
                        stop_worker(client_id)
                    except Exception:
                        pass
                    set_execution_mode(client_id, "CLIENT_PC")
                set_hosted_account_status(client_id, status)
                self.status.set(f"Hosted MT5 request → {status}")
                load_rows()
            except Exception as exc:
                messagebox.showerror("Hosted MT5", str(exc), parent=window)

        def provision_and_start():
            client_id = selected_client_id()
            if client_id is None:
                return

            terminal = filedialog.askopenfilename(
                parent=window,
                title="Select the MT5 terminal executable to clone",
                filetypes=[
                    ("MetaTrader 5 terminal", "terminal64.exe"),
                    ("Executable files", "*.exe"),
                    ("All files", "*.*"),
                ],
            )
            if not terminal:
                return

            try:
                path = provision_instance(client_id, terminal)
                pid = start_worker(client_id)
                self.status.set(
                    f"Hosted MT5 provisioned and worker started • PID {pid}"
                )
                messagebox.showinfo(
                    "Hosted MT5",
                    "Provisioning started successfully.\n\n"
                    f"Terminal: {path}\n"
                    f"Worker PID: {pid}\n\n"
                    "Status will become ACTIVE after MT5 login succeeds.",
                    parent=window,
                )
                window.after(2000, load_rows)
            except Exception as exc:
                messagebox.showerror("Hosted MT5", str(exc), parent=window)
                load_rows()

        def start_selected():
            client_id = selected_client_id()
            if client_id is None:
                return
            try:
                pid = start_worker(client_id)
                self.status.set(f"Hosted MT5 worker started • PID {pid}")
                window.after(1500, load_rows)
            except Exception as exc:
                messagebox.showerror("Hosted MT5", str(exc), parent=window)
                load_rows()

        def stop_selected():
            client_id = selected_client_id()
            if client_id is None:
                return
            try:
                stop_worker(client_id)
                self.status.set("Hosted MT5 worker stopped.")
                load_rows()
            except Exception as exc:
                messagebox.showerror("Hosted MT5", str(exc), parent=window)

        def restart_selected():
            client_id = selected_client_id()
            if client_id is None:
                return
            try:
                stop_worker(client_id)
                pid = start_worker(client_id)
                self.status.set(f"Hosted MT5 worker restarted • PID {pid}")
                window.after(1500, load_rows)
            except Exception as exc:
                messagebox.showerror("Hosted MT5", str(exc), parent=window)
                load_rows()

        def open_log():
            client_id = selected_client_id()
            if client_id is None:
                return
            path = worker_log_path(client_id)
            if not path.exists():
                messagebox.showinfo(
                    "Hosted MT5",
                    "No worker log exists yet for this client.",
                    parent=window,
                )
                return
            import os
            os.startfile(str(path))

        load_rows()

        def auto_refresh():
            if not window.winfo_exists():
                return
            load_rows()
            window.after(2000, auto_refresh)

        window.after(2000, auto_refresh)

        actions = ttk.Frame(window, padding=(12, 4, 12, 6))
        actions.pack(fill="x")
        ttk.Button(
            actions,
            text="1. Approve",
            command=lambda: change_hosted_status("APPROVED"),
        ).pack(side="left", padx=4)
        ttk.Button(
            actions,
            text="2. Provision + Start",
            command=provision_and_start,
        ).pack(side="left", padx=4)
        ttk.Button(
            actions,
            text="Start",
            command=start_selected,
        ).pack(side="left", padx=4)
        ttk.Button(
            actions,
            text="Restart",
            command=restart_selected,
        ).pack(side="left", padx=4)
        ttk.Button(
            actions,
            text="Stop",
            command=stop_selected,
        ).pack(side="left", padx=4)
        ttk.Button(
            actions,
            text="Open Log",
            command=open_log,
        ).pack(side="left", padx=4)
        ttk.Button(
            actions,
            text="Reject / Disable",
            command=lambda: change_hosted_status("DISABLED"),
        ).pack(side="left", padx=(18, 4))
        ttk.Button(actions, text="Refresh", command=load_rows).pack(side="right", padx=4)
        ttk.Button(actions, text="Close", command=window.destroy).pack(side="right", padx=4)

        ttk.Label(
            window,
            padding=(12, 0, 12, 12),
            text=(
                "Flow: APPROVE → PROVISION + START → ACTIVE. "
                "Passwords remain encrypted and are decrypted only inside the local hosted worker."
            ),
        ).pack(anchor="w")

    def toggle_news_lock(self):
        set_news_lock(bool(self.news_var.get()))
        self.status.set("NEWS LOCK ON — new entries blocked." if self.news_var.get() else "NEWS LOCK OFF.")


if __name__ == "__main__":
    GoldAIAdmin().mainloop()
