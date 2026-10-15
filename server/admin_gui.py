from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from server.store import (
    create_client,
    list_clients,
    list_hosted_accounts,
    news_lock_enabled,
    set_client_risk,
    set_news_lock,
    set_status,
)


class GoldAIAdmin(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GOLD_AI Admin")
        self.geometry("1050x620")
        self.minsize(980, 560)
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

        cols = ("name", "status", "mt5", "server", "telegram", "risk", "open", "daily")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", height=18)
        headings = {
            "name":"Client","status":"Status","mt5":"MT5 Login","server":"MT5 Server",
            "telegram":"Telegram","risk":"Risk/Trade","open":"Max Open","daily":"Daily Loss"
        }
        widths = {"name":130,"status":90,"mt5":100,"server":160,"telegram":120,"risk":85,"open":85,"daily":85}
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
        ttk.Button(buttons, text="Refresh", command=self.refresh).pack(side="right")

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
        ttk.Button(risk, text="Save Risk Settings", command=self.save_risk).pack(side="left", padx=10, pady=(18,0))

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(body, textvariable=self.status).pack(anchor="w", pady=(10,0))

    def refresh(self):
        current = self.selected_name
        for item in self.tree.get_children():
            self.tree.delete(item)
        selected_item = None
        for c in list_clients():
            item = self.tree.insert("", "end", values=(
                c.name, c.status, c.mt5_login or "-", c.mt5_server or "-",
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
        window.title("Hosted MT5 Requests")
        window.geometry("760x360")

        cols = ("client", "login", "server", "status", "updated")
        tree = ttk.Treeview(window, columns=cols, show="headings")
        headings = {
            "client": "Client",
            "login": "MT5 Login",
            "server": "MT5 Server",
            "status": "Status",
            "updated": "Updated UTC",
        }
        widths = {"client": 140, "login": 110, "server": 180, "status": 110, "updated": 180}
        for col in cols:
            tree.heading(col, text=headings[col])
            tree.column(col, width=widths[col], anchor="center")
        tree.pack(fill="both", expand=True, padx=12, pady=12)

        rows = list_hosted_accounts()
        for row in rows:
            tree.insert(
                "",
                "end",
                values=(
                    row["client_name"],
                    row["mt5_login"],
                    row["mt5_server"],
                    row["status"],
                    row["updated_utc"],
                ),
            )

        footer = ttk.Frame(window, padding=(12, 0, 12, 12))
        footer.pack(fill="x")
        ttk.Label(
            footer,
            text="Trading passwords are encrypted and are not displayed in the Admin app.",
        ).pack(side="left")
        ttk.Button(footer, text="Close", command=window.destroy).pack(side="right")

    def toggle_news_lock(self):
        set_news_lock(bool(self.news_var.get()))
        self.status.set("NEWS LOCK ON — new entries blocked." if self.news_var.get() else "NEWS LOCK OFF.")


if __name__ == "__main__":
    GoldAIAdmin().mainloop()
