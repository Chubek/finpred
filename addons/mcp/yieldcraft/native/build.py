#!/usr/bin/env python3
"""Build the opt-in On1x bridge using FinPRED's existing GrammarEmbed flags."""
import argparse, hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();root=a.root.resolve()
    sdk=Path(os.getenv('MULIB_ROOT',str(root/'third_party/mulib'))).resolve();cc=Path(os.getenv('ON1XC',str(root/'build/mulib/on1x/on1xc'))).resolve()
    sys.path.insert(0,str(root/'tests')); from ottomat_build import flags
    dest=root/'build/dev';dest.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='yc-mcp-',dir=root/'build') as td:
        work=Path(td);exe=work/'finpred-ottomat-mcp'
        subprocess.run([sys.executable,str(sdk/'on1x/tools/on1x-build.py'),str(Path(__file__).with_name('bridge.on1x').resolve()),'--backend','c11','--on1xc',str(cc),'--mulib-root',str(sdk),*flags(cc,sdk,work),'-I',str(root/'source'),'-I',str(root/'strategies'),'-I',str(root),'-o',str(exe)],cwd=work,check=True)
        meta={'compiler_identity':'sha256:'+sha(cc),'bridge_sha256':sha(exe),'source_sha256':sha(Path(__file__).with_name('bridge.on1x'))}
        (work/'finpred-ottomat-mcp.json').write_text(json.dumps(meta)+'\n');os.replace(exe,dest/exe.name);os.replace(work/'finpred-ottomat-mcp.json',dest/'finpred-ottomat-mcp.json')
if __name__=='__main__': main()
