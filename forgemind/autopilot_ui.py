import tkinter as tk
import threading
import queue
from tkinter import ttk
from . import jarvis_ui as ui
from .windows_credentials import windows_key
from .business_connections import status_text


def open_autopilot(app):
    from .workspace_ui import window,note
    win,body=window(app,'Autopilot','820x900')
    note(body,'Daily reviews run while Doxa is open and this computer is awake. Results appear in Tasks. Source approval stays in VYRA.')
    connection=tk.StringVar(value=status_text(app.business_connections.snapshot()))
    ttk.Label(body,textvariable=connection,wraplength=720).pack(fill='x',pady=6)
    results=queue.Queue();working=[False]
    def connect_crm():
        if working[0]:return
        working[0]=True;app.business_connections.stop.clear()
        connection.set('Sign into Pacifica in the separate browser window. Doxa will read only contact/call totals, then close it.')
        def work():
            try:app.business_connections.connect_pacifica();results.put(status_text(app.business_connections.refresh()))
            except Exception:results.put('Pacifica is not connected. Complete sign-in in its connection window and try again.')
        threading.Thread(target=work,daemon=True).start()
    ui.button(body,'Connect Pacifica · read only',connect_crm,small=True).pack(anchor='w')
    def poll():
        if not win.winfo_exists():app.business_connections.stop.set();return
        try:connection.set(results.get_nowait());working[0]=False
        except queue.Empty:pass
        win.after(500,poll)
    win.after(500,poll)
    config=app.autopilot.settings()
    enabled=tk.BooleanVar(value=config['enabled']);cloud=tk.BooleanVar(value=config['cloud_growth'])
    ttk.Checkbutton(body,text='Run my daily reviews automatically',variable=enabled).pack(anchor='w',pady=8)
    fields={}
    for key,label in [('morning','Morning plan'),('growth','VYRA performance review'),('evening','Evening summary'),('timezone','Time zone')]:
        row=tk.Frame(body,bg=ui.BG);row.pack(fill='x',pady=6)
        tk.Label(row,text=label,bg=ui.BG,fg=ui.TEXT,width=25,anchor='w').pack(side='left')
        fields[key]=tk.StringVar(value=config[key]);ttk.Entry(row,textvariable=fields[key],width=28).pack(side='left')
    ttk.Checkbutton(body,text='Use OpenAI for the daily public VYRA report',variable=cloud).pack(anchor='w',pady=12)
    note(body,'OpenAI receives public VYRA measurements, never CRM records or private memory. Doxa reserves $0.05 per attempt and stops at $5 per UTC month. Other apps’ API usage is separate.')
    status=tk.StringVar()
    ttk.Label(body,textvariable=status,wraplength=720).pack(fill='x',pady=10)
    def refresh():
        budget=app.cloud.budget.summary()
        status.set(('OpenAI connected. ' if app.cloud.loaded else 'OpenAI not connected. ')+f"Reserved ${budget['reserved_cents']/100:.2f} / ${budget['limit_cents']/100:.0f} this month.\n"+app.autopilot.last)
    def save():
        try:
            app.autopilot.configure({**{k:v.get().strip() for k,v in fields.items()},'enabled':enabled.get(),'cloud_growth':cloud.get()})
            if not enabled.get() and app.autopilot.active:app._cancel_answer.set()
            refresh()
        except ValueError as e:status.set(str(e))
    ui.button(body,'Save schedule',save,active=True,small=True).pack(anchor='w')
    note(body,'Optional OpenAI key · stored using Windows account encryption')
    key=ttk.Entry(body,show='•',width=50);key.pack(fill='x',pady=5)
    def connect():
        value=key.get().strip()
        if not value.startswith('sk-') or not 20<=len(value)<=8192:status.set('Enter a valid OpenAI API key.');return
        try:
            target=app.cloud.root/'openai-key.dpapi';temp=target.with_suffix('.tmp')
            temp.write_bytes(windows_key(value.encode(),True));temp.replace(target);key.delete(0,'end');refresh()
        except Exception:status.set('Windows could not save this connection.')
    ui.button(body,'Save private connection',connect,small=True).pack(anchor='w')
    ui.button(body,'Open saved results',app.show_tasks,small=True).pack(anchor='w')
    refresh()
