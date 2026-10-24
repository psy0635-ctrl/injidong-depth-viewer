"""PC GET client for draft section 7 wire shape; no upload or server storage.

Explicit configuration, bounded identity-byte transfers, no redirects/proxies/
retries/resume. Returned NetworkSession owns its temporary download and loader.
"""
import contextlib,dataclasses,datetime,hashlib,http.client,ipaddress,json,math,re,socket,ssl,tempfile,threading,time
from pathlib import Path
from urllib.parse import quote,urlencode,urlsplit
from safe_zip import ZipLimits
from verified_mobile_zip import VerifiedZipError,load_verified_mobile_zip
import mobile_session as mobile

CHUNK=65536
MESSAGES={'CONFIG':'PC 연결 설정이 올바르지 않습니다.','INVALID_JSON':'응답 JSON 형식이 올바르지 않습니다.',
 'INVALID_RESPONSE':'목록 응답의 필수값·자료형·상태·정렬이 올바르지 않습니다.','CONNECTION_FAILED':'서버 연결 또는 전송에 실패했습니다.',
 'TIMEOUT':'PC 요청 제한 시간을 초과했습니다.','CANCELLED':'요청을 취소했습니다.','UNAUTHORIZED':'인증이 필요합니다(401).',
 'FORBIDDEN':'접근이 거부됐습니다(403).','NOT_FOUND':'대상이 없습니다(404).','SERVER_ERROR':'서버 오류입니다.',
 'HTTP_ERROR':'HTTP 요청이 거부됐습니다.','REDIRECT_REJECTED':'리다이렉트를 허용하지 않습니다.',
 'HEADER_MISMATCH':'다운로드 헤더와 선택한 목록 기대값이 다르거나 필수 헤더가 없습니다.',
 'REPRESENTATION_REJECTED':'원본 ZIP 바이트 표현/Content-Type/전송 framing이 맞지 않습니다.',
 'INCOMPLETE_TRANSFER':'다운로드가 완전한 길이에 도달하지 못했습니다.','LIMIT_EXCEEDED':'현재 PC의 수신 한도를 초과했습니다.',
 'HASH_MISMATCH':'수신 ZIP의 SHA-256이 목록 기대값과 다릅니다.','SIZE_MISMATCH':'수신 ZIP 크기가 목록 기대값과 다릅니다.',
 'ZIP_REJECTED':'기존 ZIP 기대값/내부 파일/세션 검사를 통과하지 못했습니다.','FILE_ACCESS':'PC 임시 파일 접근 또는 정리에 실패했습니다.',
 'TLS_ERROR':'TLS 인증서 또는 보안 연결 검증에 실패했습니다.','INTERNAL_ERROR':'예상하지 못한 PC 내부 오류입니다.'}

class PCHttpError(ValueError):
    def __init__(self,code,*,status=None,api_code=None,verification_code=None):
        self.code=code;self.status=status;self.api_code=api_code;self.verification_code=verification_code
        super().__init__(code+': '+MESSAGES[code])  # Never echo URL, token, response body, or raw exception.

def _fail(code):raise PCHttpError(code)
def _cancel(cancel):
    if cancel.is_set():_fail('CANCELLED')
def archive_path(session_id):
    if not isinstance(session_id,str) or not session_id.strip() or any(c in session_id for c in '\r\n'):_fail('INVALID_RESPONSE')
    segment=quote(session_id,safe='')
    if session_id in ('.','..'):segment=segment.replace('.','%2E')
    return '/api/v1/sessions/'+segment+'/archive'

@dataclasses.dataclass(frozen=True)
class ClientConfig:
    base_url:str
    bearer_token:str|None=dataclasses.field(default=None,repr=False)
    allow_dev_http:bool=False
    io_timeout_s:float=3.0
    total_timeout_s:float=120.0
    max_json_bytes:int=1024*1024
    max_archive_bytes:int=ZipLimits().max_archive_bytes
    def __post_init__(self):
        try:
            u=urlsplit(self.base_url)
            if u.scheme not in ('http','https') or not u.hostname or u.username is not None or u.password is not None or u.query or u.fragment or u.path not in ('','/') or any(ord(c)<33 for c in self.base_url):_fail('CONFIG')
            port=u.port
            if port is not None and not 1<=port<=65535:_fail('CONFIG')
            try:loopback=ipaddress.ip_address(u.hostname).is_loopback
            except ValueError:loopback=u.hostname.lower()=='localhost'
            if u.scheme=='http' and not loopback and not self.allow_dev_http:_fail('CONFIG')
            if type(self.allow_dev_http) is not bool:_fail('CONFIG')
            for v in (self.io_timeout_s,self.total_timeout_s):
                if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0:_fail('CONFIG')
            for v in (self.max_json_bytes,self.max_archive_bytes):
                if type(v) is not int or v<=0:_fail('CONFIG')
            if self.max_archive_bytes>ZipLimits().max_archive_bytes:_fail('CONFIG')
            if self.bearer_token is not None and (not isinstance(self.bearer_token,str) or not self.bearer_token or any(ord(c)<33 or ord(c)>126 for c in self.bearer_token)):_fail('CONFIG')
        except (TypeError,ValueError) as exc:
            if isinstance(exc,PCHttpError):raise
            raise PCHttpError('CONFIG') from None
        object.__setattr__(self,'base_url',self.base_url.rstrip('/'))

@dataclasses.dataclass(frozen=True)
class SessionRecord:
    session_id:str
    storage_status:str
    zip_size_bytes:int
    zip_sha256:str
    stored_at:str
    download_path:str
    warnings:tuple
    def wire(self):
        return {**{k:getattr(self,k) for k in ('session_id','storage_status','zip_size_bytes','zip_sha256','stored_at','download_path')},
                'warnings':[{'code':c,**({'count':n} if n is not None else {})} for c,n in self.warnings]}
@dataclasses.dataclass(frozen=True)
class SessionPage:
    items:tuple
    next_cursor:str|None

def _timestamp(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|\+00:00)',value):_fail('INVALID_RESPONSE')
    try:return datetime.datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:raise PCHttpError('INVALID_RESPONSE') from None
def parse_record(row):
    try:
        if not isinstance(row,dict):_fail('INVALID_RESPONSE')
        sid=row['session_id'];path=archive_path(sid)
        if row['storage_status']!='stored' or type(row['zip_size_bytes']) is not int or row['zip_size_bytes']<=0:_fail('INVALID_RESPONSE')
        if not isinstance(row['zip_sha256'],str) or re.fullmatch('[0-9a-f]{64}',row['zip_sha256']) is None:_fail('INVALID_RESPONSE')
        _timestamp(row['stored_at'])
        if row['download_path']!=path:_fail('INVALID_RESPONSE')
        warnings=row.get('warnings',[])
        if not isinstance(warnings,list):_fail('INVALID_RESPONSE')
        for w in warnings:
            if not isinstance(w,dict) or not isinstance(w.get('code'),str) or not w['code'] or ('count' in w and (type(w['count']) is not int or w['count']<0)):_fail('INVALID_RESPONSE')
        return SessionRecord(sid,'stored',row['zip_size_bytes'],row['zip_sha256'],row['stored_at'],path,tuple((w['code'],w.get('count')) for w in warnings))
    except (KeyError,TypeError):raise PCHttpError('INVALID_RESPONSE') from None
def _json(raw):
    def pairs(items):
        d={}
        for k,v in items:
            if k in d:_fail('INVALID_JSON')
            d[k]=v
        return d
    try:return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=lambda x:_fail('INVALID_JSON'))
    except (ValueError,UnicodeError,RecursionError) as exc:
        if isinstance(exc,PCHttpError):raise
        raise PCHttpError('INVALID_JSON') from None

def _read_chunk(response):return response.read1(CHUNK)
def _bounded_json_bytes(response,config,cancel):
    chunks=[];total=0
    while True:
        _cancel(cancel);chunk=_read_chunk(response)
        if not chunk:break
        total+=len(chunk)
        if total>config.max_json_bytes:_fail('LIMIT_EXCEEDED')
        chunks.append(chunk)
    return b''.join(chunks)
def _one_header(response,name):
    values=response.headers.get_all(name,[])
    if len(values)!=1:_fail('HEADER_MISMATCH')
    return values[0]
def _identity(response):
    enc=response.headers.get_all('Content-Encoding',[])
    if len(enc)>1 or (enc and enc[0].strip().lower()!='identity'):_fail('REPRESENTATION_REJECTED')

@contextlib.contextmanager
def _exchange(config,path,accept,cancel):
    """A worker-owned connection with cancellation/deadline socket shutdown.

    DNS resolution remains subject to the OS resolver; literal loopback tests
    do not use DNS. No redirect following or environment proxy support.
    """
    _cancel(cancel);u=urlsplit(config.base_url);deadline=time.monotonic()+config.total_timeout_s
    connection=(http.client.HTTPSConnection(u.hostname,u.port,timeout=min(config.io_timeout_s,config.total_timeout_s),context=ssl.create_default_context())
                if u.scheme=='https' else http.client.HTTPConnection(u.hostname,u.port,timeout=min(config.io_timeout_s,config.total_timeout_s)))
    done=threading.Event();expired=threading.Event();transport=[None];response=None
    def monitor():
        while not done.wait(.025):
            if cancel.is_set() or time.monotonic()>=deadline:
                if not cancel.is_set():expired.set()
                if transport[0] is not None:
                    try:transport[0].shutdown(socket.SHUT_RDWR)
                    except OSError:pass  # Connection may have already closed during this cleanup race.
                return
    watcher=threading.Thread(target=monitor,name='PC HTTP deadline');watcher.start()
    try:
        connection.connect();transport[0]=connection.sock;_cancel(cancel)
        headers={'Accept':accept,'Accept-Encoding':'identity','Connection':'close'}
        if config.bearer_token is not None:headers['Authorization']='Bearer '+config.bearer_token
        connection.request('GET',path,headers=headers);response=connection.getresponse()
        if response.status!=200:
            if 300<=response.status<400:_fail('REDIRECT_REJECTED')
            code={401:'UNAUTHORIZED',403:'FORBIDDEN',404:'NOT_FOUND'}.get(response.status,'SERVER_ERROR' if response.status>=500 else 'HTTP_ERROR')
            api_code=None
            try:
                obj=_json(_bounded_json_bytes(response,config,cancel));err=obj['error']
                if isinstance(err,dict) and isinstance(err.get('code'),str) and re.fullmatch('[A-Z0-9_]{1,64}',err['code']) and isinstance(err.get('message'),str) and ('details' not in err or isinstance(err['details'],dict)) and ('request_id' not in obj or isinstance(obj['request_id'],str)):api_code=err['code']
            except (PCHttpError,KeyError,TypeError):_cancel(cancel)
            raise PCHttpError(code,status=response.status,api_code=api_code)
        _identity(response);yield response
        _cancel(cancel)
        if expired.is_set():_fail('TIMEOUT')
    except PCHttpError:
        _cancel(cancel)
        if expired.is_set():raise PCHttpError('TIMEOUT') from None
        raise
    except (OSError,http.client.HTTPException) as exc:
        _cancel(cancel)
        if expired.is_set() or isinstance(exc,(TimeoutError,socket.timeout)):raise PCHttpError('TIMEOUT') from None
        if isinstance(exc,ssl.SSLError):raise PCHttpError('TLS_ERROR') from None
        raise PCHttpError('CONNECTION_FAILED') from None
    finally:
        done.set()
        if response is not None:response.close()
        connection.close();watcher.join(.2)

def list_sessions(config,*,limit=50,cursor=None,cancel=None):
    cancel=cancel if cancel is not None else threading.Event()
    if type(limit) is not int or not 1<=limit<=200 or (cursor is not None and not isinstance(cursor,str)):_fail('CONFIG')
    query={'limit':limit}
    if cursor is not None:query['cursor']=cursor
    with _exchange(config,'/api/v1/sessions?'+urlencode(query),'application/json',cancel) as response:
        if response.headers.get_content_type()!='application/json':_fail('INVALID_RESPONSE')
        obj=_json(_bounded_json_bytes(response,config,cancel))
    try:
        if not isinstance(obj,dict) or not isinstance(obj['items'],list) or len(obj['items'])>limit or (obj['next_cursor'] is not None and not isinstance(obj['next_cursor'],str)):_fail('INVALID_RESPONSE')
        items=tuple(parse_record(r) for r in obj['items'])
    except (KeyError,TypeError):raise PCHttpError('INVALID_RESPONSE') from None
    if len({r.session_id for r in items})!=len(items):_fail('INVALID_RESPONSE')
    for before,after in zip(items,items[1:]):
        b,a=_timestamp(before.stored_at),_timestamp(after.stored_at)
        if b<a or (b==a and before.session_id>after.session_id):_fail('INVALID_RESPONSE')
    return SessionPage(items,obj['next_cursor'])

def _copy_archive(response,path,expected_size,maximum,expected_sha,cancel,progress):
    total=0;hasher=hashlib.sha256()
    try:stream=Path(path).open('xb')
    except OSError:raise PCHttpError('FILE_ACCESS') from None
    try:
        while True:
            _cancel(cancel)
            try:chunk=_read_chunk(response)
            except (http.client.IncompleteRead,ConnectionResetError):raise PCHttpError('INCOMPLETE_TRANSFER') from None
            if not chunk:break
            total+=len(chunk)
            if total>maximum:_fail('LIMIT_EXCEEDED')
            if total>expected_size:_fail('SIZE_MISMATCH')
            try:stream.write(chunk)
            except OSError:raise PCHttpError('FILE_ACCESS') from None
            hasher.update(chunk);progress(f'다운로드 {total:,} / {expected_size:,} bytes')
    finally:
        try:stream.close()
        except OSError:raise PCHttpError('FILE_ACCESS') from None
    if total!=expected_size:_fail('INCOMPLETE_TRANSFER')
    if hasher.hexdigest()!=expected_sha:_fail('HASH_MISMATCH')

class NetworkSession:
    """Borrowed loader API; close removes BOTH independent loader files and download."""
    def __init__(self,session,owner,path,record):
        self._session=session;self._download_owner=owner;self.download_path=path;self.server_record=record
    def __getattr__(self,name):return getattr(self._session,name)
    def close(self):
        try:self._session.close()
        finally:self._download_owner.cleanup()

def download_session(config,record,scratch,*,cancel=None,progress=lambda message:None):
    cancel=cancel if cancel is not None else threading.Event();_cancel(cancel)
    record=parse_record(record.wire())
    if record.zip_size_bytes>config.max_archive_bytes:_fail('LIMIT_EXCEEDED')
    scratch=Path(scratch).absolute()
    try:
        if scratch.resolve().is_relative_to(mobile.ROOT):_fail('CONFIG')
        scratch.mkdir(parents=True,exist_ok=True);mobile.compat.require_unlinked(scratch)
        owner=tempfile.TemporaryDirectory(prefix='http_download_',dir=scratch)
    except (OSError,ValueError) as exc:
        if isinstance(exc,PCHttpError):raise
        raise PCHttpError('FILE_ACCESS') from None
    session=None;transferred=False
    try:
        part=Path(owner.name)/'archive.part'
        with _exchange(config,archive_path(record.session_id),'application/zip',cancel) as response:
            if response.headers.get_content_type()!='application/zip' or response.headers.get_all('Transfer-Encoding',[]):_fail('REPRESENTATION_REJECTED')
            sid=_one_header(response,'X-Session-ID');sha=_one_header(response,'X-Archive-SHA256');length=_one_header(response,'Content-Length')
            if re.fullmatch('[0-9]{1,20}',length) is None or sid!=record.session_id or sha!=record.zip_sha256 or int(length)!=record.zip_size_bytes:_fail('HEADER_MISMATCH')
            _copy_archive(response,part,record.zip_size_bytes,config.max_archive_bytes,record.zip_sha256,cancel,progress)
        def checking(message):_cancel(cancel);progress('ZIP 검증 · '+message)
        _cancel(cancel);progress('외부 목록 기대값으로 기존 ZIP 검증 중')
        try:session=load_verified_mobile_zip(part,record.session_id,record.zip_size_bytes,record.zip_sha256,scratch,progress=checking)
        except VerifiedZipError as exc:raise PCHttpError('ZIP_REJECTED',verification_code=exc.code) from None
        _cancel(cancel)
        final=Path(owner.name)/'archive.zip';part.rename(final)
        result=NetworkSession(session,owner,final,record);transferred=True;return result
    except OSError:raise PCHttpError('FILE_ACCESS') from None
    finally:
        if not transferred:
            try:
                try:
                    if session is not None:session.close()
                finally:owner.cleanup()
            except OSError:raise PCHttpError('FILE_ACCESS') from None
