"""Small real device capabilities; no model guess or internet lookup is required."""
from datetime import datetime
import re


def clock_reply(text, now=None):
    question=' '.join(text.lower().strip(' .?!').split())
    question=re.sub(r'^(?:hey )?(?:doxa|jarvis)[, ]*','',question)
    instant=now or datetime.now().astimezone()
    if question in {'what time is it','what time is it right now','what is the time','whats the time',
                    "what's the time",'tell me the time','current time','time now'}:
        hour=instant.hour%12 or 12
        return f"It’s {hour}:{instant.minute:02d} {instant.strftime('%p')} on your computer."
    if question in {'what is the date','what is todays date',"what is today's date",'what day is it',
                    'what is the date today','what day is today','tell me the date'}:
        return f"Today is {instant.strftime('%A, %B')} {instant.day}, {instant.year}."
    return None
