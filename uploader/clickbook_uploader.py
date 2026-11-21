#!/usr/bin/env python3
"""Clickbook DSLR/tethered-camera JPEG auto-uploader.

Use your camera maker's tethering software to save JPEG images into a local folder,
then let this tool monitor that folder and upload stable files to Clickbook.

No third-party Python packages required. Credentials are never written to disk.
"""
import argparse
import getpass
import hashlib
import json
import mimetypes
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

EXTS={'.jpg','.jpeg','.png','.webp'}

def request_json(url,body,headers=None):
    data=json.dumps(body).encode('utf-8')
    req=Request(url,data=data,headers={'Content-Type':'application/json',**(headers or {})},method='POST')
    try:
        with urlopen(req,timeout=30) as res:return json.load(res)
    except HTTPError as e:
        try: detail=json.load(e).get('detail',e.reason)
        except Exception:detail=e.reason
        raise RuntimeError(f'HTTP {e.code}: {detail}') from e

def upload_file(url,token,path):
    boundary='----clickbook'+uuid.uuid4().hex
    mime=mimetypes.guess_type(path.name)[0] or 'image/jpeg'
    data=path.read_bytes()
    if len(data)>25*1024*1024:raise RuntimeError('File larger than 25 MB upload limit')
    pre=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\nContent-Type: {mime}\r\n\r\n').encode()
    post=(f'\r\n--{boundary}--\r\n').encode()
    payload=pre+data+post
    req=Request(url,data=payload,headers={'Content-Type':f'multipart/form-data; boundary={boundary}','Authorization':f'Bearer {token}'},method='POST')
    try:
        with urlopen(req,timeout=120) as res:return json.load(res)
    except HTTPError as e:
        try:detail=json.load(e).get('detail',e.reason)
        except Exception:detail=e.reason
        raise RuntimeError(f'HTTP {e.code}: {detail}') from e

def run():
    parser=argparse.ArgumentParser(description='Automatically upload DSLR/tethered images into a Clickbook event')
    parser.add_argument('--api',default=os.environ.get('CLICKBOOK_API_URL','http://127.0.0.1:8000'),help='Public site URL or local backend URL')
    parser.add_argument('--event',required=True,help='Event ID from the Clickbook workspace')
    parser.add_argument('--folder',required=True,help='Folder your tethered DSLR saves photos into')
    parser.add_argument('--email',default=os.environ.get('CLICKBOOK_EMAIL',''),help='Photographer login email; password prompted')
    parser.add_argument('--once',action='store_true',help='Check existing stable photos once and exit')
    parser.add_argument('--interval',type=float,default=3,help='Scan interval in seconds (default: 3)')
    args=parser.parse_args()
    folder=Path(args.folder).expanduser().resolve()
    if not folder.is_dir():parser.error(f'Folder does not exist: {folder}')
    root=args.api.rstrip('/')
    token=os.environ.get('CLICKBOOK_TOKEN','')
    if not token:
        if not args.email:parser.error('Specify --email or CLICKBOOK_TOKEN environment variable')
        password=getpass.getpass('Clickbook password: ')
        token=request_json(root+'/api/auth/login',{'email':args.email,'password':password})['token']
    print('Watching:',folder)
    print('Event ID:',args.event)
    print('Allowed images:',', '.join(sorted(EXTS)))
    state_path=folder/'.clickbook-upload-state.json'
    try:state=json.loads(state_path.read_text()) if state_path.exists() else {}
    except Exception:state={}
    # State is per event because one camera folder could be used for multiple events.
    done=state.get(args.event,{})
    observed={}
    def scan():
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.suffix.lower() not in EXTS:continue
            try:info=path.stat()
            except OSError:continue
            signature=f'{info.st_size}:{info.st_mtime_ns}'
            if done.get(path.name)==signature:continue
            if info.st_size==0:continue
            if observed.get(path.name)!=signature:
                observed[path.name]=signature
                continue  # allow another scan to confirm the tethering software finished writing
            try:
                result=upload_file(root+f'/api/events/{args.event}/photos',token,path)
                done[path.name]=signature;state[args.event]=done
                tmp=state_path.with_suffix('.tmp')
                tmp.write_text(json.dumps(state,indent=2));tmp.replace(state_path)
                label='already present' if result.get('duplicate') else 'uploaded'
                print(f'[{time.strftime("%H:%M:%S")}] {label}: {path.name}',flush=True)
            except Exception as exc:
                print(f'[{time.strftime("%H:%M:%S")}] failed: {path.name}: {exc}',file=sys.stderr,flush=True)
                time.sleep(min(3,args.interval))
    try:
        while True:
            scan()
            if args.once:
                # In --once mode, allow one extra pass for the stabilization check.
                time.sleep(1);scan();break
            time.sleep(max(1,args.interval))
    except KeyboardInterrupt:
        print('\nUploader stopped.')

if __name__=='__main__':run()
