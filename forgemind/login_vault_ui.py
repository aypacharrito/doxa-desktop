"""Owner enters site credentials directly into a masked local panel, never chat."""
import tkinter as tk
from . import jarvis_ui as ui
from .login_vault import LoginVault


def open_vault(app):
    window, content = ui._panel(app, 'Login vault',
        'Saved with Windows Credential Manager for your Windows account. Doxa can fill an enabled account '
        'only on its exact HTTPS website. Programs running as your Windows user may also access it; this is not GPU isolation.', '680x650')
    vault = LoginVault()
    status = tk.StringVar()
    fields = {}
    for key, title in [('label', 'Account label'), ('url', 'Exact login website (https://…)'),
                       ('username', 'Username / email'), ('password', 'Password')]:
        tk.Label(content, text=title, bg=ui.BG, fg=ui.TEXT, anchor='w').pack(fill='x', pady=(10, 3))
        value = tk.StringVar()
        field = tk.Entry(content, textvariable=value, show='•' if key == 'password' else '',
                         bg=ui.SURFACE_2, fg=ui.TEXT, insertbackground=ui.TEXT, relief='flat')
        field.pack(fill='x', ipady=7)
        fields[key] = value
    enabled = tk.BooleanVar(value=False)
    tk.Checkbutton(content, text='Allow Doxa browser tasks to fill this login on this exact website',
                   variable=enabled, bg=ui.BG, fg=ui.TEXT, selectcolor=ui.SURFACE_2).pack(fill='x', pady=12)
    accounts = tk.Listbox(content, bg=ui.SURFACE_2, fg=ui.TEXT, height=6)
    labels = []
    def refresh():
        labels.clear(); accounts.delete(0, 'end')
        for row in vault.list():
            labels.append(row['label'])
            accounts.insert('end', f"{row['label']} · {row['origin']} · {'autofill on' if row['autofill'] else 'stored only'}")
    def save():
        try:
            vault.save(**{k: v.get() for k, v in fields.items()}, autofill=enabled.get())
            fields['password'].set('')
            status.set('Saved locally. Password cleared from the form.')
            refresh()
        except Exception:
            status.set('Could not save. Check the fields and Windows Credential Manager availability.')
    def remove():
        selected = accounts.curselection()
        if selected:
            vault.remove(labels[selected[0]]); refresh(); status.set('Saved login removed.')
    ui.button(content, 'Save login locally', save, active=True).pack(anchor='w')
    accounts.pack(fill='x', pady=12)
    ui.button(content, 'Remove selected login', remove, small=True).pack(anchor='w')
    tk.Label(content, textvariable=status, bg=ui.BG, fg=ui.MUTED, wraplength=580).pack(fill='x', pady=10)
    try:
        refresh()
    except Exception:
        status.set('Windows Credential Manager is unavailable.')
    return window
