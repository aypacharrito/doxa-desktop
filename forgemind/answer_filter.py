"""Keep reasoning-model scratch output out of displayed and spoken answers."""
class AnswerFilter:
    def __init__(self, thinking=False):
        self.thinking=thinking
        self.buffer=''

    def feed(self,text):
        self.buffer+=text
        answer=''
        while self.buffer:
            if self.thinking:
                index=self.buffer.find('</think>')
                if index<0:
                    self.buffer=self.buffer[-7:]
                    return answer
                self.buffer=self.buffer[index+8:]
                self.thinking=False
            else:
                tags=[(self.buffer.find(tag),tag) for tag in ('<think>','</think>') if tag in self.buffer]
                if tags:
                    index,tag=min(tags)
                    answer+=self.buffer[:index]
                    self.buffer=self.buffer[index+len(tag):]
                    self.thinking=tag=='<think>'
                    continue
                keep=max((n for tag in ('<think>','</think>') for n in range(1,len(tag))
                          if self.buffer.endswith(tag[:n])),default=0)
                answer+=self.buffer[:-keep] if keep else self.buffer
                self.buffer=self.buffer[-keep:] if keep else ''
                return answer
        return answer

    def finish(self):
        if self.thinking:
            raise ValueError('The reasoning budget ended before a final answer. Try a shorter question.')
        value=self.buffer
        self.buffer=''
        return value
