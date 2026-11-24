from __future__ import annotations
import hashlib, json, os, re, tempfile, stat, threading
from pathlib import Path
from .auth import PROJECT
ID=re.compile(r'[0-9a-f]{64}\Z')
def identifier(v):
    if not isinstance(v,str) or not ID.fullmatch(v): raise ValueError('expected 64 lowercase hex characters')
    return v

def canonical_json(v): return json.dumps(v,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode()+b'\n'
def safe_json(raw):
    def pairs(items):
        out={}
        for k,v in items:
            if k in out: raise ValueError('duplicate JSON key')
            out[k]=v
        return out
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON')))

def js_safe(v):
    if isinstance(v,bool): return v
    if isinstance(v,int) and abs(v)>2**53-1: return str(v)
    if isinstance(v,dict): return {k:js_safe(x) for k,x in v.items()}
    if isinstance(v,list): return [js_safe(x) for x in v]
    return v

class Store:
    """Private cooperative service-owned store; not a hostile filesystem boundary."""
    def __init__(self,root:Path,maximum:int,quota:int):
        self.root=root; self.maximum=maximum; self.quota=quota; self.lock=threading.RLock()
        root.mkdir(mode=0o700,parents=True,exist_ok=True)
        if root.is_symlink() or root.stat().st_mode&0o077: raise ValueError('private state directory required')
    def project(self,name):
        if not PROJECT.fullmatch(name): raise ValueError('invalid project')
        p=self.root/name; p.mkdir(mode=0o700,exist_ok=True)
        for child in ['objects','runs','cube','forecast','tmp']:
            (p/child).mkdir(mode=0o700,exist_ok=True)
        return p
    def put(self,project,data:bytes):
        with self.lock: return self._put(project,data)
    def _put(self,project,data:bytes):
        if len(data)>self.maximum: raise ValueError('artifact too large')
        d=hashlib.sha256(data).hexdigest(); folder=self.project(project)/'objects'; path=folder/d
        if path.exists():
            if self.read(project,d)!=data: raise ValueError('artifact conflict')
            return d
        # Synchronous operations are serialized within one event-loop process.
        if sum(p.stat().st_size for p in folder.iterdir() if ID.fullmatch(p.name))+len(data)>self.quota: raise ValueError('artifact quota exceeded')
        fd,tmp=tempfile.mkstemp(prefix='.stage-',dir=folder)
        try:
            with os.fdopen(fd,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
            try: os.link(tmp,path)
            except FileExistsError:
                if self.read(project,d)!=data: raise ValueError('artifact conflict')
            dirfd=os.open(folder,os.O_RDONLY|os.O_DIRECTORY)
            try: os.fsync(dirfd)
            finally: os.close(dirfd)
        finally: os.unlink(tmp)
        return d
    def read(self,project,digest):
        path=self.project(project)/'objects'/identifier(digest)
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode): raise ValueError('not a regular artifact')
            data=f.read(self.maximum+1)
        if len(data)>self.maximum or hashlib.sha256(data).hexdigest()!=digest: raise ValueError('artifact integrity failure')
        return data
    def list(self,project,limit=100):
        return sorted(p.name for p in (self.project(project)/'objects').iterdir() if ID.fullmatch(p.name))[:min(100,max(1,limit))]
