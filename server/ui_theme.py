"""AZT desktop surfaces. Normal Tk controls keep keyboard/accessibility support."""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk

BG = '#08131f'
PANEL = '#101f2c'
EDGE = '#293e48'
GOLD = '#e8bd67'
TEXT = '#edf3ee'
MUTED = '#9eaea9'
GREEN = '#6ed6ac'
RED = '#fa8586'


def asset_path(relative):
    bundled = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])) / relative
    return bundled


def apply_theme(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background=PANEL, foreground=TEXT, font=('Segoe UI', 10))
    style.configure('TFrame', background=PANEL)
    style.configure('TLabel', background=PANEL, foreground=TEXT)
    style.configure('Muted.TLabel', foreground=MUTED)
    style.configure('Title.TLabel', font=('Segoe UI Semibold', 24), foreground=GOLD)
    style.configure('Heading.TLabel', font=('Segoe UI Semibold', 15))
    style.configure('TButton', background='#203744', foreground=TEXT, padding=(13, 8), borderwidth=0)
    style.map('TButton', background=[('active', '#345052'), ('disabled', '#182831')], foreground=[('disabled', '#71848b')])
    style.configure('Accent.TButton', background=GOLD, foreground=BG)
    style.map('Accent.TButton', background=[('active', '#ffda8a')])
    style.configure('Danger.TButton', foreground=RED)
    style.configure('Nav.TButton', background=BG, foreground=MUTED, anchor='w', padding=(16, 12))
    style.configure('Selected.Nav.TButton', background='#263a3e', foreground=GOLD, anchor='w', padding=(16, 12))
    style.configure('TEntry', fieldbackground=BG, foreground=TEXT, insertcolor=TEXT, padding=6)
    style.configure('TCombobox', fieldbackground=BG, background=EDGE, foreground=TEXT, padding=5)
    style.map('TCombobox', fieldbackground=[('readonly', BG)], foreground=[('readonly', TEXT)])
    style.configure('TLabelframe', background=PANEL, bordercolor=EDGE, relief='solid')
    style.configure('TLabelframe.Label', foreground=GOLD, background=PANEL)
    style.configure('Treeview', background=BG, fieldbackground=BG, foreground=TEXT, rowheight=32, borderwidth=0)
    style.configure('Treeview.Heading', background='#203440', foreground=GOLD, padding=(7, 9))
    style.map('Treeview', background=[('selected', '#335650')], foreground=[('selected', '#ffffff')])
    style.configure('TNotebook', background=PANEL, borderwidth=0)
    style.configure('TNotebook.Tab', padding=(15, 9), background=BG)
    style.map('TNotebook.Tab', background=[('selected', EDGE)], foreground=[('selected', GOLD)])
    root.option_add('*TCombobox*Listbox.background', BG)
    root.option_add('*TCombobox*Listbox.foreground', TEXT)
    root.option_add('*Text.background', BG)
    root.option_add('*Text.foreground', TEXT)
    return style


class ScrollPage(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=PANEL, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.scrollbar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.scrollbar.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.body = ttk.Frame(self.canvas, padding=22)
        self.window = self.canvas.create_window(0, 0, window=self.body, anchor='nw')
        self.body.bind('<Configure>', self._contents)
        self.canvas.bind('<Configure>', self._width)
        self.bind_all('<MouseWheel>', self._wheel, add='+')

    def _contents(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def _width(self, event):
        self.canvas.itemconfigure(self.window, width=max(200, event.width))

    def _wheel(self, event):
        widget = event.widget
        while widget is not None and widget is not self:
            widget = getattr(widget, 'master', None)
        if widget is self:
            self.canvas.yview_scroll(-int(event.delta / 120), 'units')


class FlowBar(ttk.Frame):
    """Wrap actions instead of clipping a long horizontal button strip."""
    def __init__(self, parent):
        super().__init__(parent)
        self.items = []
        self.bind('<Configure>', self._layout)

    def add(self, text, command, style='TButton'):
        button = ttk.Button(self, text=text, command=command, style=style)
        self.items.append(button)
        self.after_idle(self._layout)
        return button

    def _layout(self, _event=None):
        available = max(250, self.winfo_width())
        x = y = 0
        height = 38
        for button in self.items:
            width = min(available, max(90, button.winfo_reqwidth()))
            if x and x + width > available:
                x = 0
                y += height + 6
            button.place(x=x, y=y, width=width, height=height)
            x += width + 7
        self.configure(height=y + height + 4)


def make_table(parent, columns, height=10):
    frame = ttk.Frame(parent)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    tree = ttk.Treeview(frame, columns=[col[0] for col in columns], show='headings', height=height)
    for key, label, width in columns:
        tree.heading(key, text=label)
        tree.column(key, width=width, minwidth=75, anchor='w', stretch=False)
    tree.grid(row=0, column=0, sticky='nsew')
    ttk.Scrollbar(frame, orient='vertical', command=tree.yview).grid(row=0, column=1, sticky='ns')
    horizontal = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
    horizontal.grid(row=1, column=0, sticky='ew')
    tree.configure(yscrollcommand=lambda a, b: frame.grid_slaves(row=0, column=1)[0].set(a, b), xscrollcommand=horizontal.set)
    frame.pack(fill='both', expand=True, pady=(8, 15))
    tree.tag_configure('positive', foreground=GREEN)
    tree.tag_configure('negative', foreground=RED)
    return tree


def set_rows(tree, rows):
    selected = tree.selection()
    for item in tree.get_children():
        tree.delete(item)
    for key, values in rows:
        tree.insert('', 'end', iid=str(key), values=values)
    for key in selected:
        if tree.exists(key):
            tree.selection_add(key)


def form_dialog(parent, title, fields, on_save, description=''):
    window = tk.Toplevel(parent)
    window.title(title)
    window.configure(bg=BG)
    window.geometry('690x600')
    window.minsize(460, 420)
    window.rowconfigure(0, weight=1)
    window.columnconfigure(0, weight=1)
    page = ScrollPage(window)
    page.grid(row=0, column=0, sticky='nsew')
    ttk.Label(page.body, text=title, style='Heading.TLabel').pack(anchor='w', pady=(0, 12))
    if description:
        ttk.Label(page.body, text=description, wraplength=570, style='Muted.TLabel').pack(anchor='w', pady=(0, 12))
    values = {}
    for key, label, initial, *options in fields:
        ttk.Label(page.body, text=label).pack(anchor='w', pady=(9, 3))
        var = tk.StringVar(value='' if initial is None else str(initial))
        values[key] = var
        if options:
            ttk.Combobox(page.body, textvariable=var, values=options[0], state='readonly').pack(fill='x')
        else:
            ttk.Entry(page.body, textvariable=var).pack(fill='x')
    footer = ttk.Frame(window, padding=12)
    footer.grid(row=1, column=0, sticky='ew')
    def save():
        from tkinter import messagebox
        try:
            on_save({key: value.get().strip() for key, value in values.items()})
        except Exception as exc:
            messagebox.showerror(title, str(exc), parent=window)
        else:
            window.destroy()
    ttk.Button(footer, text='Save', command=save, style='Accent.TButton').pack(side='right', padx=6)
    ttk.Button(footer, text='Cancel', command=window.destroy).pack(side='right')
    return window, values
