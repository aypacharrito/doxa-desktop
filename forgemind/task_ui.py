"""Visible, owner-started persistent drafts and calculations."""
import json
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from . import jarvis_ui as ui
from .config import Settings
from .task_runner import run_selected


def editor(parent, height):
    frame=tk.Frame(parent,bg=ui.BG)
    frame.pack(fill='both',expand=height>4,pady=(6,10))
    view=tk.Text(frame,height=height,bg=ui.SURFACE,fg=ui.TEXT,insertbackground=ui.BLUE,
                 relief='flat',borderwidth=0,highlightthickness=0,padx=10,pady=8,
                 wrap='word',font=('Segoe UI',10))
    scroll=ui.ThinScroll(frame,command=view.yview)
    scroll.pack(side='right',fill='y');view.configure(yscrollcommand=scroll.set)
    view.pack(side='left',fill='both',expand=True)
    return view


class TaskPanel:
    def __init__(self, app):
        from .workspace_ui import window, note
        self.app=app
        self.window,body=window(app,'Tasks','840x900')
        self.window.minsize(760,780)
        style=ttk.Style(self.window)
        style.configure('Tasks.Treeview',background=ui.BG,fieldbackground=ui.BG,foreground=ui.TEXT,rowheight=30,borderwidth=0)
        style.map('Tasks.Treeview',background=[('selected',ui.SELECT)],foreground=[('selected',ui.BLUE)])
        style.configure('Tasks.Treeview.Heading',background=ui.SURFACE,foreground=ui.MUTED,relief='flat')
        style.map('Tasks.Treeview.Heading',background=[('active',ui.SURFACE)])
        style.configure('Tasks.TCombobox',fieldbackground=ui.SURFACE,background=ui.SURFACE,foreground=ui.TEXT,arrowcolor=ui.BLUE)
        style.map('Tasks.TCombobox',fieldbackground=[('readonly',ui.SURFACE)],foreground=[('readonly',ui.TEXT)])
        self.active=False
        self.events=queue.Queue()
        self.worker=None
        note(body,'Local drafts and calculations. Save, run, then review.')
        self.kind=tk.StringVar(value='Local draft')
        ttk.Combobox(body,textvariable=self.kind,values=['Local draft','Calculate'],state='readonly',style='Tasks.TCombobox').pack(anchor='w')
        self.prompt=editor(body,height=3)
        self.prompt.pack_configure(expand=False)
        ui.button(body,'Save task',self.add,small=True).pack(anchor='w',pady=(0,10))
        self.list=ttk.Treeview(body,columns=('task','state'),show='headings',height=3,selectmode='browse',style='Tasks.Treeview')
        self.list.heading('task',text='Task');self.list.heading('state',text='Status')
        self.list.column('task',width=480);self.list.column('state',width=140)
        self.list.pack(fill='x')
        self.list.bind('<<TreeviewSelect>>',lambda _:self.preview())
        buttons=tk.Frame(body,bg=ui.BG);buttons.pack(fill='x',pady=10)
        for index,(label,action) in enumerate([('Run selected',self.run),('Stop',self.stop),('Retry',self.retry),('Cancel task',self.cancel),('Refresh',self.refresh)]):
            ui.button(buttons,label,action,small=True).grid(row=0,column=index,sticky='w',padx=(0,5))
        self.status=tk.StringVar(value='Nothing runs until you choose Run selected.')
        ttk.Label(body,textvariable=self.status,wraplength=720).pack(fill='x')
        ui.button(body,'Copy result',self.copy,small=True).pack(side='bottom',anchor='w')
        self.output=editor(body,height=7);self.output.configure(state='disabled')
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.refresh();self.poll_id=self.window.after(100,self.poll)

    def selected(self):
        selected=self.list.selection()
        return selected[0] if selected else None

    def refresh(self):
        selected=self.selected()
        self.app.task_queue.recover_expired()
        self.list.delete(*self.list.get_children())
        for row in self.app.task_queue.recent(100):
            job=self.app.task_queue.get(row['id'])
            payload=json.loads(job['payload'])
            title=(payload.get('prompt') or payload.get('expression') or row['tool']) if isinstance(payload,dict) else row['tool']
            self.list.insert('','end',iid=row['id'],values=(' '.join(str(title).split())[:90],row['state'].replace('_',' ')))
        if selected and self.list.exists(selected):self.list.selection_set(selected)
        self.preview()

    def preview(self):
        row=self.app.task_queue.get(self.selected()) if self.selected() else None
        text='Select a task to see its instructions and result.'
        if row:
            payload=json.loads(row['payload'])
            result=json.loads(row['result']) if row['result'] else None
            text=(payload.get('prompt') or payload.get('expression') or str(payload)) if isinstance(payload,dict) else str(payload)
            outcome=('REVIEW DRAFT\n'+result['draft'] if isinstance(result,dict) and 'draft' in result else json.dumps(result,indent=2) if result else row['error'] or 'No result yet.')
            text=outcome+'\n\nINSTRUCTIONS\n'+text
        self.output.configure(state='normal');self.output.delete('1.0','end');self.output.insert('1.0',text);self.output.configure(state='disabled')

    def add(self):
        value=self.prompt.get('1.0','end').strip()
        if not value or len(value)>8000:
            self.status.set('Enter up to 8,000 characters.');return
        tool='local_draft' if self.kind.get()=='Local draft' else 'calculate'
        identifier=self.app.task_queue.submit(tool,{'prompt' if tool=='local_draft' else 'expression':value})
        self.prompt.delete('1.0','end');self.refresh();self.list.selection_set(identifier);self.preview()
        self.status.set('Saved locally. Ready when you are.')

    def run(self):
        identifier=self.selected()
        if not identifier:return
        if self.active or self.app.busy or self.app._upload_running or self.app._creator_operations:
            self.status.set('Finish or stop the current Doxa task first.');return
        job=self.app.task_queue.get(identifier)
        if job['state']!='queued':self.status.set('Choose a queued task, or review and retry a failed task.');return
        if job['tool']=='local_draft' and not self.app.engine.loaded:
            self.status.set('Load your local model in Settings first.');return
        self.active=True;self.app.busy=True;self.app._cancel_answer.clear()
        self.app.send_button.configure(state='disabled')
        settings=Settings(**self.app.settings_data.__dict__)
        self.status.set('Preparing an OpenAI review within your $5 allowance.' if job['tool']=='cloud_draft' else 'Working locally. Stop cancels this draft.')
        def work():
            try:
                engine=self.app.cloud if job['tool']=='cloud_draft' else self.app.inference
                result=run_selected(self.app.task_queue,identifier,engine,self.app.db,settings,self.app._cancel_answer)
                self.events.put(result['state'].replace('_',' '))
            except Exception as exc:self.events.put(str(exc))
        self.worker=threading.Thread(target=work,daemon=True);self.worker.start()

    def stop(self):
        if self.active:self.app._cancel_answer.set();self.status.set('Stopping after the current model step…')

    def retry(self):
        identifier=self.selected()
        if not identifier:return
        if not messagebox.askyesno('Retry task','Queue this task again after reviewing its previous outcome?',parent=self.window):return
        try:self.app.task_queue.retry(identifier);self.status.set('Queued. Choose Run selected when ready.')
        except ValueError as exc:self.status.set(str(exc))
        self.refresh()

    def cancel(self):
        identifier=self.selected()
        if not identifier:return
        row=self.app.task_queue.get(identifier)
        if row['state']=='running':
            self.status.set('Use Stop to cancel the running task.');return
        try:self.app.task_queue.cancel(identifier)
        except ValueError as exc:self.status.set(str(exc))
        self.refresh()

    def copy(self):
        row=self.app.task_queue.get(self.selected()) if self.selected() else None
        if not row or not row['result']:return
        result=json.loads(row['result'])
        text=result.get('draft') if isinstance(result,dict) else None
        self.window.clipboard_clear();self.window.clipboard_append(text or json.dumps(result,indent=2))
        self.status.set('Result copied. Review it before using it.')

    def poll(self):
        try:
            message=self.events.get_nowait()
            self.active=False;self.app.busy=False
            self.app.send_button.configure(state='normal')
            self.status.set('Task '+message);self.refresh()
        except queue.Empty:pass
        self.poll_id=self.window.after(100,self.poll)

    def close(self):
        if self.active:self.stop();return
        self.window.after_cancel(self.poll_id)
        self.app._task_panel=None;self.window.destroy()


def open_tasks(app):
    existing=getattr(app,'_task_panel',None)
    if existing and existing.window.winfo_exists():existing.window.lift();return existing
    app._task_panel=TaskPanel(app)
    return app._task_panel
