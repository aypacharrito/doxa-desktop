"""Pinned, checksummed local model download; never executes repository code."""
import hashlib
from pathlib import Path
import shutil
import urllib.request

NAME='Qwen3.5-9B-Q4_K_M.gguf'
SIZE=5680522464
SHA256='03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8'
URL='https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/3885219b6810b007914f3a7950a8d1b469d598a5/'+NAME

def verified(path):
    path=Path(path)
    if not path.is_file() or path.stat().st_size != SIZE:return False
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):digest.update(block)
    return digest.hexdigest()==SHA256

def obtain(folder,progress=lambda value:None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    target=folder/NAME
    if target.exists():
        if not verified(target):raise ValueError('An existing model has a different checksum; it was preserved.')
        return target
    partial=target.with_suffix('.gguf.download')
    offset=partial.stat().st_size if partial.exists() else 0
    if shutil.disk_usage(folder).free < SIZE-offset+1024**3:raise ValueError('Make room for the model before downloading.')
    request=urllib.request.Request(URL,headers={'Range':f'bytes={offset}-'} if offset else {})
    with urllib.request.urlopen(request,timeout=60) as response:
        if offset and response.status!=206:offset=0
        total=offset
        with partial.open('ab' if offset else 'wb') as output:
            for block in iter(lambda:response.read(4*1024*1024),b''):
                output.write(block);total+=len(block);progress(min(100,total/SIZE*100))
    if not verified(partial):raise ValueError('The download did not pass checksum verification. The original model is unchanged.')
    partial.replace(target)
    return target
