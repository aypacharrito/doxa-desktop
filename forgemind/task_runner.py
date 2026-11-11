"""Local-only draft execution; never dispatch model text as actions."""
import json
import threading
from dataclasses import replace
from .task_tools import calculate


def run_selected(queue, identifier, engine, memory, settings, stop, timeout=240):
    if not 0 < timeout <= 240:
        raise ValueError('Task timeout must be at most four minutes')
    job = queue.claim_selected(identifier)
    if not job:
        raise ValueError('Select a queued task')
    timer = threading.Timer(timeout, stop.set)
    timer.daemon = True
    timer.start()
    try:
        payload = json.loads(job['payload'])
        if job['tool'] == 'calculate':
            result = calculate(payload)
        elif job['tool'] in ('local_draft', 'cloud_draft'):
            prompt = payload.get('prompt') if isinstance(payload,dict) else None
            if not isinstance(prompt,str) or not 1 <= len(prompt.strip()) <= 8000:
                raise ValueError('Draft instructions must contain 1–8000 characters')
            if not engine.loaded:
                raise ValueError('Connect OpenAI in Autopilot first' if job['tool']=='cloud_draft' else 'Load your local model before running a draft')
            memories = memory.retrieve(prompt) if job['tool']=='local_draft' else []
            instruction = ('Prepare the requested draft or analysis for owner review. Follow the requested '
                           'output format exactly. If asked for only a draft, output only that draft, without '
                           'an introduction, quotation marks or a missing-information checklist. '
                           'Use the task instructions as the factual source for this draft. Background memory '
                           'may guide tone but must not add claims about the author or recipient. '
                           'Do not invent teams, ownership, credentials, names, dates, prices or promises. '
                           'Omit unnecessary unknown details; ask a concise question only when an unknown '
                           'prevents a useful answer. Do not claim you sent, saved, booked, quoted or performed '
                           'an external action. No web access is available for this task.\n\nTASK:\n'+prompt)
            chunks=[];size=0
            for chunk in engine.stream([],instruction,replace(settings,auto_research=False),memories,[],stop_event=stop):
                if stop.is_set():
                    break
                chunks.append(chunk)
                size+=len(chunk)
                if size > 10000:
                    raise ValueError('Draft exceeded the output limit; shorten the instructions')
            answer=''.join(chunks).strip()
            if not answer and not stop.is_set():
                raise ValueError('The model returned an empty draft')
            result={'draft':answer,'model':engine.model_name,'review_required':True}
        else:
            raise ValueError('This tool is not available in desktop Tasks')
        if stop.is_set():
            queue.cancel(identifier)
        else:
            queue.finish(identifier,job['lease'],result=result)
    except Exception as exc:
        if queue.get(identifier)['state']=='running':
            try:
                if stop.is_set():queue.cancel(identifier)
                else:queue.finish(identifier,job['lease'],error=str(exc))
            except ValueError:
                queue.recover_expired()
    finally:
        timer.cancel()
    return queue.get(identifier)
