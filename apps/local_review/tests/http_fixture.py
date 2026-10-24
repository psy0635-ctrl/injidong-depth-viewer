"""TEST ONLY, loopback ephemeral port. No production storage/upload implementation.

Uses the draft section 7 items/next_cursor shape; X-Test-Fixture marks responses.
Never logs request headers, credentials, or error bodies.
"""
import hashlib,json,os,subprocess,sys,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,quote,urlsplit

SID='d405_1792497323680'
SHA='72f3ebaff4c6fcb57675e702aca0854eeec162ce0de4f86b4b80de381cd07dff'
CURSOR='opaque /+?=&한글'
SAMPLE=Path(os.environ.get('MOBILE_TEST_ZIP',str(Path(__file__).with_name('external-sample-not-configured.zip'))))

class FixtureServer:
    def __init__(self,root,archive=None,session_id=SID):
        self.root=Path(root);self.archive=Path(archive) if archive else SAMPLE;self.session_id=session_id
    def __enter__(self):
        self.root.mkdir(parents=True,exist_ok=True);self.mode('good')
        self.process=subprocess.Popen([sys.executable,'-B','-X','utf8',str(Path(__file__)),'--serve',str(self.root),'--archive',str(self.archive),'--session-id',self.session_id],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
        end=time.monotonic()+8
        while not (self.root/'ready.json').exists():
            if self.process.poll() is not None:raise RuntimeError('fixture failed to start')
            if time.monotonic()>end:raise TimeoutError('fixture startup')
            time.sleep(.01)
        self.info=json.loads((self.root/'ready.json').read_text());self.base=self.info['base_url'];return self
    def mode(self,name,**values):
        self.root.mkdir(parents=True,exist_ok=True)
        (self.root/'release').unlink(missing_ok=True)
        (self.root/'mode.json').write_text(json.dumps({'mode':name,**values}),encoding='utf-8')
    def events(self):
        p=self.root/'events.jsonl'
        return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()] if p.exists() else []
    def release(self):(self.root/'release').touch()
    def __exit__(self,*args):
        self.release();out,err=self.process.communicate('\n',timeout=8)
        (self.root/'server.stdout.txt').write_text(out,encoding='utf-8');(self.root/'server.stderr.txt').write_text(err,encoding='utf-8')
        (self.root/'server.exit.txt').write_text(str(self.process.returncode))
        assert self.process.returncode==0 and err=='' and out=='','fixture process diagnostics'

def serve(root,archive,session_id=SID):
    stop=threading.Event();lock=threading.Lock()
    raw=archive.read_bytes()
    if session_id==SID:
        assert len(raw)==3354368 and hashlib.sha256(raw).hexdigest()==SHA
    def event(name,**values):
        with lock,(root/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'event':name,'pid':os.getpid(),**values},ensure_ascii=False)+'\n')
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.0'
        def log_message(self,*args):pass  # No access/header logging in this test fixture.
        def send(self,status,body,headers):
            self.send_response(status)
            for k,v in headers.items():self.send_header(k,str(v))
            self.send_header('X-Test-Fixture','loopback-only-draft-profile');self.end_headers()
            self.wfile.write(body);self.wfile.flush()
        def json(self,status,obj):
            body=json.dumps(obj,ensure_ascii=False).encode();self.send(status,body,{'Content-Type':'application/json','Content-Length':len(body)})
        def gate(self,phase):
            event('gate',phase=phase)
            end=time.monotonic()+12
            while not (root/'release').exists() and not stop.is_set():
                if time.monotonic()>end:raise TimeoutError('fixture gate not released')
                stop.wait(.01)
        def do_GET(self):
            try:self.get()
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):event('client_disconnected')
        def get(self):
            cfg=json.loads((root/'mode.json').read_text(encoding='utf-8'));mode=cfg['mode'];url=urlsplit(self.path)
            event('request',path=self.path,authorization_present=bool(self.headers.get('Authorization')),identity_requested=self.headers.get('Accept-Encoding')=='identity')
            if mode=='gate_headers':self.gate('headers')
            if mode=='http_error':self.json(cfg.get('status',500),{'error':{'code':'TEST_HTTP_ERROR','message':'test fixture only'}});return
            if mode=='bad_error':self.send(401,b'not JSON',{'Content-Type':'text/plain','Content-Length':8});return
            if mode=='redirect':self.send(302,b'',{'Location':'http://127.0.0.1:9/forbidden-target','Content-Length':0});return
            payload=b'not a ZIP' if mode=='damaged' else raw
            sid='other_session' if mode=='internal_id' else cfg.get('session_id',session_id)
            record={'session_id':sid,'storage_status':'stored','zip_size_bytes':len(payload),
                'zip_sha256':hashlib.sha256(payload).hexdigest(),'stored_at':'2026-10-22T10:00:00Z',
                'download_path':'/api/v1/sessions/'+quote(sid,safe='')+'/archive',
                'warnings':([{'code':'RGB_ENCODING_CHANNEL_MISMATCH','count':4}] if session_id==SID else [])}
            if url.path=='/api/v1/sessions':
                query=parse_qs(url.query,keep_blank_values=True)
                if mode=='bad_json':self.send(200,b'{"items":',{'Content-Type':'application/json','Content-Length':9});return
                if mode=='duplicate_json':self.send(200,b'{"items":[],"items":[],"next_cursor":null}',{'Content-Type':'application/json','Content-Length':41});return
                if mode=='missing':record.pop(cfg.get('field','zip_sha256'))
                if mode=='not_stored':record['storage_status']='processing'
                if mode=='invalid_record':record[cfg['field']]=cfg['value']
                if 'cursor' in query:
                    if query['cursor']!=[CURSOR]:self.json(400,{'error':{'code':'INVALID_PAGINATION','message':'test opaque cursor mismatch'}});return
                    self.json(200,{'items':[],'next_cursor':None});return
                if mode=='unordered':
                    second=dict(record,session_id='aaaa',download_path='/api/v1/sessions/aaaa/archive')
                    self.json(200,{'items':[record,second],'next_cursor':None});return
                self.json(200,{'items':[record],'next_cursor':CURSOR});return
            if url.path!=record['download_path']:self.json(404,{'error':{'code':'SESSION_NOT_FOUND','message':'test fixture'}});return
            if mode=='body_hash':payload=payload[:100]+bytes([payload[100]^1])+payload[101:]
            headers={'Content-Type':'application/zip','Content-Length':len(payload),'X-Session-ID':sid,'X-Archive-SHA256':record['zip_sha256']}
            if mode=='id_header':headers['X-Session-ID']='wrong_id'
            if mode=='sha_header':headers['X-Archive-SHA256']='0'*64
            if mode=='size_header':headers['Content-Length']=len(payload)+1
            if mode=='encoding':headers['Content-Encoding']='gzip'
            if mode=='transfer_encoding':headers['Transfer-Encoding']='chunked'
            if mode=='wrong_type':headers['Content-Type']='application/json'
            if mode=='no_length':headers.pop('Content-Length')
            self.send_response(200)
            for k,v in headers.items():self.send_header(k,str(v))
            self.send_header('X-Test-Fixture','loopback-only-draft-profile');self.end_headers()
            if mode=='short':self.wfile.write(payload[:1024]);self.wfile.flush();return
            if mode=='gate_body':
                self.wfile.write(payload[:1024]);self.wfile.flush();self.gate('body');payload=payload[1024:]
            for start in range(0,len(payload),65536):self.wfile.write(payload[start:start+65536])
            self.wfile.flush();event('archive_sent',size=len(payload))
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever);thread.start()
    (root/'ready.json').write_text(json.dumps({'base_url':f'http://127.0.0.1:{server.server_port}','pid':os.getpid(),'test_only':True}))
    sys.stdin.readline();stop.set();server.shutdown();server.server_close();thread.join(2)
    assert not thread.is_alive();event('server_stopped')

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--serve',type=Path,required=True);p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--session-id',default=SID,help='explicit fixture identity; original reference sample remains pinned')
    a=p.parse_args();serve(a.serve,a.archive,a.session_id)
