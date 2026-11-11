"""Read-only app evidence. No credentials, customer records, or write actions."""
import json
import os
import time
import threading
from pathlib import Path
from datetime import datetime, timezone
import requests


def vyra_report():
    path=Path(os.environ.get('LOCALAPPDATA',''))/'Programs/VYRA/clips-worker/.local/growth-latest.json'
    if not path.is_file():return {'connected':False,'reason':'Open VYRA and enable Growth reviews.'}
    if path.stat().st_size>500000:raise ValueError('VYRA report is too large.')
    report=json.loads(path.read_text('utf-8'))
    age=time.time()-datetime.fromisoformat(report['created_at']).timestamp()
    return {'connected':0<=age<=36*3600,'measured_at':report['created_at'],'age_hours':round(age/3600,1),
            'channels':list(report.get('channels',{})),'issues':report.get('issues',[])[:6],
            'mode':'Public performance reports only; source approval stays in VYRA.'}


class BusinessConnections:
    def __init__(self,root):
        self.root=Path(root);self.active=False;self.last_attempt=0;self.stop=threading.Event()

    def snapshot(self):
        path=self.root/'business-status.json'
        try:return json.loads(path.read_text('utf-8'))
        except (OSError,ValueError):return {'notice':'Connection checks have not run yet.'}

    def refresh(self):
        result={'checked_at':datetime.now(timezone.utc).isoformat()}
        try:result['vyra']=vyra_report()
        except Exception:result['vyra']={'connected':False,'reason':'VYRA report could not be read.'}
        try:
            response=requests.get('https://crm.example.com/api/health',timeout=(5,10),allow_redirects=False)
            response.raise_for_status();data=response.json()
            result['pacifica']={'service_reachable':bool(data.get('ready')),'workspace_connected':False,
                'mode':'Service health only. Customer workspace access has not been authorized in Doxa.',
                'background':data.get('background',{}),'a2p_approved':data.get('checks',{}).get('a2pApproved')}
        except Exception:result['pacifica']={'service_reachable':False,'workspace_connected':False,'mode':'Service check failed; no customer data was requested.'}
        workspace=self.root/'pacifica-summary.json'
        if workspace.is_file():
            try:
                summary=json.loads(workspace.read_text('utf-8'))
                age=time.time()-datetime.fromisoformat(summary['checked_at']).timestamp()
                result['pacifica'].update(workspace_connected=0<=age<36*3600,summary=summary,
                    mode='Read-only workspace summary; no texts, calls or customer updates are dispatched.')
            except (ValueError,KeyError,OSError):pass
        temp=self.root/'business-status.tmp';temp.write_text(json.dumps(result,indent=2),'utf-8');temp.replace(self.root/'business-status.json')
        return result

    def tick(self):
        if self.active or time.monotonic()-self.last_attempt<3600:return
        self.active=True;self.last_attempt=time.monotonic()
        def work():
            try:self.refresh()
            finally:self.active=False
        threading.Thread(target=work,daemon=True).start()

    def connect_pacifica(self):
        """Owner signs in directly. The app only GETs its own fixed workspace endpoint."""
        from .browser_agent import BrowserSession
        session=BrowserSession(self.root/'pacifica-browser')
        try:
            session.open();session.goto('https://crm.example.com')
            deadline=time.monotonic()+600
            while time.monotonic()<deadline and not self.stop.wait(5):
                if not session.page.url.startswith('https://crm.example.com/'):continue
                try:
                    data=session.page.evaluate('''async () => {
                  const r=await fetch('/api/crm/workspace',{method:'GET',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(10000)});
                  if(!r.ok)return null;
                  const w=await r.json();if(!w.found)return null;
                  const leads=Array.isArray(w.leads)?w.leads:[];
                  const active=leads.filter(l=>!l.deletedAt);
                  return {contacts:active.length,do_not_call:active.filter(l=>l.doNotCall).length,
                          call_records:Array.isArray(w.callLogs)?w.callLogs.length:0};
                    }''')
                except Exception:
                    # Login navigations can destroy the page context while a read
                    # is in flight. Keep waiting for the owner's existing session.
                    if session.page.is_closed():
                        pages=[p for p in session.context.pages if not p.is_closed()]
                        if not pages:break
                        session.page=pages[-1]
                    continue
                if data:
                    data['checked_at']=datetime.now(timezone.utc).isoformat()
                    path=self.root/'pacifica-summary.json';temp=path.with_suffix('.tmp')
                    temp.write_text(json.dumps(data),'utf-8');temp.replace(path)
                    return data
            raise ValueError('Pacifica sign-in was not completed. Open Connect Pacifica to try again.')
        finally:session.close()


def status_text(data):
    vyra=data.get('vyra',{});crm=data.get('pacifica',{})
    return ('VYRA: '+('fresh performance report connected' if vyra.get('connected') else 'report missing or stale')+
            '\nPacifica: '+('read-only workspace connected' if crm.get('workspace_connected') else
                              'website reachable; workspace not connected' if crm.get('service_reachable') else 'service not verified')+
            ('\nPacifica automation heartbeat: not verified.' if crm.get('background',{}).get('lastRunAt') is None else '')+
            '\nChecks: '+data.get('checked_at','not run'))


def business_reply(app,text):
    """Small explicit read commands, available on desktop and the authenticated phone."""
    command=text.strip().lower().rstrip('.!?')
    if command in ("today's experiment", "what should i test today", "daily experiment"):
        from datetime import date
        from .experiments import daily_test
        return daily_test(date.today())
    if 'quote' in command and ('alibaba' in command or 'supplier' in command):
        import re
        from .experiments import quote_check, quote_summary
        labels = ('unit', 'shipping', 'duty', 'sell', 'ads')
        amounts = []
        for label in labels:
            matches = re.findall(r'\b' + label + r'\s*(?:=|:)\s*\$?(\d+(?:\.\d+)?)%?(?=\s|,|$)', text.lower())
            if len(matches) != 1:
                return 'To compare a supplier quote, send: Alibaba quote unit=8 shipping=5 duty=0 sell=24 ads=0. Use USD per item and duty as a percentage.'
            amounts.append(matches[0])
        try:
            return quote_summary(quote_check(*amounts)) + ' Estimate assumes 2.9% + $0.30 processing and a 5% returns allowance, before labor and taxes.'
        except ValueError as error:
            return str(error)
    if command in ('connections','business status','app connections','doxa status'):
        return status_text(app.business_connections.snapshot())
    if command in ('vyra report','growth report','meme report'):
        with app.task_queue.connection() as db:
            row=db.execute("SELECT j.result,s.slot FROM jobs j JOIN autopilot_slots s ON s.job_id=j.id WHERE s.slot LIKE '%:growth' AND j.state='succeeded' ORDER BY j.created DESC LIMIT 1").fetchone()
        if row:return 'Saved review · '+row['slot'].split(':')[0]+'\n\n'+json.loads(row['result']).get('draft','No draft text.')+'\n\nDraft ideas only. No new posts or promotions were published by this review.'
        return 'No completed VYRA review yet. Check Autopilot and open VYRA for a fresh measurement report.'
    return None
