from __future__ import annotations
import hashlib, json, os, re, secrets, stat, threading
from contextlib import contextmanager
from pathlib import Path
from .auth import PROJECT
ID=re.compile(r'[0-9a-f]{64}\Z')
PROJECT_DIRS=('objects','runs','cube','forecast','tmp')
NATIVE_ENTRIES={'artifacts':re.compile(r'blake3-[0-9a-f]{64}\.txt\Z'),
                'runs':re.compile(r'[0-9a-f]{64}\.txt\Z')}

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

@contextmanager
def private_directory(name, parent=None, *, create=False, mask=0o077):
    """Open one directory component without following aliases."""
    try:
        if create:
            try: os.mkdir(name,0o700,dir_fd=parent)
            except FileExistsError: pass
        fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
    except FileNotFoundError:
        raise FileNotFoundError('state directory missing') from None
    except OSError:
        raise ValueError('private state directory required') from None
    try:
        info=os.fstat(fd)
        if info.st_uid!=os.geteuid() or info.st_mode&mask:
            raise ValueError('private state directory required')
        yield fd
    finally:
        os.close(fd)

def private_regular(info,mask=0o077):
    return (stat.S_ISREG(info.st_mode) and info.st_uid==os.geteuid()
            and info.st_nlink==1 and not info.st_mode&mask)

class Store:
    """Private cooperative service-owned store with no linked project entries."""
    def __init__(self,root:Path,maximum:int,quota:int):
        self.root=root; self.maximum=maximum; self.quota=quota; self.lock=threading.RLock()
        try: root.mkdir(mode=0o700,parents=True,exist_ok=True)
        except OSError: raise ValueError('private state directory required') from None
        with private_directory(root): pass
    @contextmanager
    def _project(self,name):
        if not isinstance(name,str) or not PROJECT.fullmatch(name): raise ValueError('invalid project')
        with private_directory(self.root) as root, private_directory(name,root,create=True) as project:
            yield project
    @contextmanager
    def _objects(self,project):
        with self._project(project) as p, private_directory('objects',p,create=True) as folder:
            yield folder
    def project(self,name):
        with self._project(name) as p:
            for child in PROJECT_DIRS:
                with private_directory(child,p,create=True): pass
        return self.root/name
    def check_native_home(self,project,name):
        # The launcher consumes paths, not directory descriptors. Check the
        # actual flat native store layout before handing it to a trusted worker.
        with self._project(project) as p, private_directory(name,p,create=True) as home:
            for role,pattern in NATIVE_ENTRIES.items():
                try:
                    with private_directory(role,home,mask=0o022) as folder:
                        for key in os.listdir(folder):
                            if not pattern.fullmatch(key): continue
                            try: info=os.stat(key,dir_fd=folder,follow_symlinks=False)
                            except OSError: raise ValueError('unsafe native store entry') from None
                            if not private_regular(info,mask=0o022): raise ValueError('unsafe native store entry')
                except FileNotFoundError:
                    # The native writer creates missing archive directories.
                    pass
    def put(self,project,data:bytes):
        if len(data)>self.maximum: raise ValueError('artifact too large')
        d=hashlib.sha256(data).hexdigest()
        with self.lock, self._objects(project) as folder:
            try:
                if self._read(folder,d)!=data: raise ValueError('artifact conflict')
            except FileNotFoundError: pass
            else: return d
            total=len(data)
            for key in os.listdir(folder):
                if ID.fullmatch(key):
                    info=os.stat(key,dir_fd=folder,follow_symlinks=False)
                    if not private_regular(info): raise ValueError('unsafe artifact object')
                    total+=info.st_size
            if total>self.quota: raise ValueError('artifact quota exceeded')
            tmp='.stage-'+secrets.token_hex(16)
            fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600,dir_fd=folder)
            try:
                with os.fdopen(fd,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
                try: os.link(tmp,d,src_dir_fd=folder,dst_dir_fd=folder,follow_symlinks=False)
                except FileExistsError:
                    if self._read(folder,d)!=data: raise ValueError('artifact conflict')
            finally: os.unlink(tmp,dir_fd=folder)
            os.fsync(folder)
            return d
    def _read(self,folder,digest):
        try:
            info=os.stat(digest,dir_fd=folder,follow_symlinks=False)
            if not private_regular(info): raise ValueError('unsafe artifact object')
            fd=os.open(digest,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=folder)
        except FileNotFoundError: raise FileNotFoundError('artifact not found') from None
        except OSError: raise ValueError('unsafe artifact object') from None
        if not private_regular(os.fstat(fd)):
            os.close(fd)
            raise ValueError('unsafe artifact object')
        with os.fdopen(fd,'rb') as f:
            data=f.read(self.maximum+1)
        if len(data)>self.maximum or hashlib.sha256(data).hexdigest()!=digest: raise ValueError('artifact integrity failure')
        return data
    def read(self,project,digest):
        identifier(digest)
        with self.lock, self._objects(project) as folder:
            return self._read(folder,digest)
    def list(self,project,limit=100):
        with self.lock, self._objects(project) as folder:
            return sorted(key for key in os.listdir(folder) if ID.fullmatch(key) and private_regular(
                os.stat(key,dir_fd=folder,follow_symlinks=False)
            ))[:min(100,max(1,limit))]
