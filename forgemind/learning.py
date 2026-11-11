"""Background model experiments with visible state and a durable pause control."""
from .research_lab import LabSession

def when_ready(app):
    if app._closing:return
    if app.busy:
        app.after(2000,lambda:when_ready(app))
        return
    start(app)


def start(app):
    if app._research_session is not None:
        app.learning_label.configure(text='An experiment session is already running')
        return
    try:
        digest=app.research_lab.corpus()
        paused=next((r for r in app.research_lab.runs() if r['corpus']==digest and r['status']=='paused'
                     and (app.research_lab.run_dir(r['id'])/'weights.pt').is_file()),None)
        session=LabSession(app.research_lab,digest,continuous=True,steps=300,seconds=30,
                           device='cpu',background=True,cooldown_seconds=60,
                           resume_id=paused['id'] if paused else None)
        app._research_session=session
        app.settings_data.local_learning_enabled=True
        app.settings_data.save()
        app.learning_label.configure(text='Learning · starting CPU experiment')
    except Exception as exc:
        app.settings_data.local_learning_enabled=False
        app.settings_data.save()
        app.learning_label.configure(text='Learning paused · '+str(exc))


def pause(app):
    app.settings_data.local_learning_enabled=False
    app.settings_data.save()
    if app._research_session is not None:
        app._research_session.stop()
    app.learning_label.configure(text='Learning · saving and pausing')
