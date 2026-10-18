from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from server.hosted_manager import provision_instance, start_worker, stop_worker, worker_log_path
from server.store import (
    create_client,
    list_clients,
    list_hosted_accounts,
    news_lock_enabled,
    set_client_risk,
    set_execution_mode,
    set_hosted_account_status,
    set_news_lock,
    set_status,
)



def apply_theme(root):
    """Task Harbor palette; presentation only, no execution state."""
    root.configure(background="#F4F7F6")
    root.option_add("*Font", ("Segoe UI", 10))
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background="#F4F7F6", foreground="#172D35", font=("Segoe UI", 10))
    style.configure("TFrame", background="#F4F7F6")
    style.configure("TLabel", background="#F4F7F6", foreground="#172D35")
    style.configure("Muted.TLabel", foreground="#60746B")
    style.configure("Hero.TLabel", font=("Segoe UI", 27, "bold"), foreground="#176B53")
    style.configure("Card.TFrame", background="#FFFFFF")
    style.configure("Card.TLabel", background="#FFFFFF", foreground="#172D35")
    style.configure("TButton", padding=(12, 9), background="#E3ECE7", foreground="#254D3F", borderwidth=0)
    style.map("TButton", background=[("active", "#D2E5DC")], foreground=[("disabled", "#73837B")])
    style.configure("Accent.TButton", background="#176B53", foreground="#FFFFFF")
    style.map("Accent.TButton", background=[("active", "#11533F"), ("disabled", "#CBD7D0")])
    style.configure("Danger.TButton", foreground="#9B2525", background="#FBE9E7")
    style.configure("TEntry", fieldbackground="#FFFFFF", padding=7)
    style.configure("TLabelframe", background="#F4F7F6", bordercolor="#DCE5E1")
    style.configure("TLabelframe.Label", foreground="#176B53", font=("Segoe UI", 11, "bold"))
    style.configure("Treeview", background="#FFFFFF", fieldbackground="#FFFFFF", rowheight=36, borderwidth=0)
    style.configure("Treeview.Heading", background="#E3ECE7", foreground="#254D3F", padding=9, font=("Segoe UI", 10, "bold"))
    style.map("Treeview", background=[("selected", "#176B53")], foreground=[("selected", "#FFFFFF")])
    style.configure("TCheckbutton", background="#F4F7F6", padding=6)

class GoldAIAdmin(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GOLD_AI Admin")
        self.geometry("1280x860")
        self.minsize(1280, 860)
        self.selected_name = ""
        apply_theme(self)
        self._build()
        self.refresh()

    def _build(self):
        top = ttk.Frame(self, padding=14)
        top.pack(fill="x")
        ttk.Label(top, text="GOLD_AI  /  Owner workspace", style="Hero.TLabel").pack(side="left")
        self.news_var = tk.BooleanVar(value=news_lock_enabled())
        ttk.Checkbutton(
            top,
            text="NEWS LOCK — BLOCK NEW ENTRIES",
            variable=self.news_var,
            command=self.toggle_news_lock,
        ).pack(side="right")

        ttk.Label(self, text="Your clients, execution and risk — one clear workspace.", style="Muted.TLabel").pack(anchor="w", padx=18, pady=(0, 12))
        summary = ttk.Frame(self, padding=(18, 0, 18, 14))
        summary.pack(fill="x")
        self.summary_vars = []
        for title in ("CLIENTS", "ACTIVE ACCESS", "HOSTED MODE"):
            card = ttk.Frame(summary, style="Card.TFrame", padding=16)
            card.pack(side="left", fill="x", expand=True, padx=(0, 12))
            ttk.Label(card, text=title, style="Card.TLabel").pack(anchor="w")
            value = tk.StringVar(value="—")
            self.summary_vars.append(value)
            ttk.Label(card, textvariable=value, style="Card.TLabel", font=("Segoe UI", 24, "bold")).pack(anchor="w")

        body = ttk.Frame(self, padding=(14, 0, 14, 14))
        body.pack(fill="both", expand=True)

        cols = ("name", "status", "mode", "mt5", "server", "telegram", "risk", "open", "daily")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", height=8)
        headings = {
            "name":"Client","status":"Status","mode":"Execution","mt5":"MT5 Login","server":"MT5 Server",
            "telegram":"Telegram","risk":"Risk/Trade","open":"Max Open","daily":"Daily Loss"
        }
        widths = {"name":120,"status":85,"mode":90,"mt5":100,"server":145,"telegram":115,"risk":80,"open":80,"daily":80}
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 6))
        actions = (
            ("+ Add Client", self.add_client, "Accent.TButton"),
            ("Activate", lambda: self.change_status("ACTIVE"), "TButton"),
            ("Pause", lambda: self.change_status("PAUSED"), "TButton"),
            ("Revoke", lambda: self.change_status("REVOKED"), "Danger.TButton"),
            ("Expire", lambda: self.change_status("EXPIRED"), "TButton"),
            ("Copy Pairing Code", self.copy_pairing, "TButton"),
            ("Hosted MT5 Requests", self.show_hosted_requests, "TButton"),
            ("Use PC Client", self.use_pc_mode, "TButton"),
            ("Refresh", self.refresh, "TButton"),
        )
        for index, (label, command, style) in enumerate(actions):
            ttk.Button(buttons, text=label, command=command, style=style).grid(
                row=index // 5, column=index % 5, sticky="ew", padx=4, pady=4,
            )
        for column in range(5):
            buttons.columnconfigure(column, weight=1)

        risk = ttk.LabelFrame(body, text="Selected Client Risk Limits", padding=10)
        risk.pack(fill="x", pady=(6,0))

        self.risk_trade = tk.StringVar(value="0.9")
        self.risk_open = tk.StringVar(value="40")
        self.risk_daily = tk.StringVar(value="5")

        for label, var in (
            ("Risk / trade (0.1–2%)", self.risk_trade),
            ("Max overall open risk (5–40%)", self.risk_open),
            ("Max daily loss (2–10%)", self.risk_daily),
        ):
            box = ttk.Frame(risk)
            box.pack(side="left", padx=(0,18))
            ttk.Label(box, text=label).pack(anchor="w")
            ttk.Entry(box, textvariable=var, width=12).pack(anchor="w")
        ttk.Button(risk, text="Save Risk Settings", style="Accent.TButton", command=self.save_risk).pack(side="left", padx=10, pady=(18,0))

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(body, textvariable=self.status).pack(anchor="w", pady=(10,0))

    def refresh(self):
        current = self.selected_name
        for item in self.tree.get_children():
            self.tree.delete(item)
        selected_item = None
        clients = list_clients()
        for var, value in zip(self.summary_vars, (len(clients), sum(c.status == "ACTIVE" for c in clients), sum(c.execution_mode == "HOSTED" for c in clients))):
            var.set(str(value))
        self.tree.tag_configure("ACTIVE", foreground="#176B53")
        self.tree.tag_configure("PAUSED", foreground="#8A5B0A")
        self.tree.tag_configure("REVOKED", foreground="#9B2525")
        self.tree.tag_configure("EXPIRED", foreground="#9B2525")
        for c in clients:
            item = self.tree.insert("", "end", tags=(c.status,), values=(
                c.name, c.status, c.execution_mode, c.mt5_login or "-", c.mt5_server or "-",
                f"@{c.telegram_username}" if c.telegram_username else "-",
                f"{c.risk_per_trade_pct:.2f}%",
                f"{c.max_open_risk_pct:.1f}%",
                f"{c.max_daily_loss_pct:.1f}%",
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
            )
            self.status.set(f"{self.selected_name} risk settings saved.")
            self.refresh()
        except Exception as exc:
            messagebox.showerror("Risk Settings", str(exc))

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
