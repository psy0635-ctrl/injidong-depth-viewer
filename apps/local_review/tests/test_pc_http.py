"""Real loopback fixture process and original ZIP; no real team server calls."""
import dataclasses,importlib,json,os,secrets,socket,tempfile,threading,time,unittest
from pathlib import Path
from http_fixture import FixtureServer,SAMPLE,SID,SHA,CURSOR
from mobile_session import digest

@unittest.skipUnless(os.environ.get('MOBILE_TEST_ZIP'), 'external reference ZIP not supplied; real integration not run')
class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.server=FixtureServer(cls.root/'server').__enter__();cls.original=digest(SAMPLE)
    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__();assert digest(SAMPLE)==cls.original
        evidence=os.environ.get('PC_HTTP_EVIDENCE')
        if evidence:
            import shutil
            target=Path(evidence)/'client_fixture';shutil.copytree(cls.root/'server',target)
        cls.temp.cleanup()
    def setUp(self):
        try:self.api=importlib.import_module('pc_http')
        except ModuleNotFoundError:self.fail('PC list/download client is not implemented')
        self.server.mode('good');self.cancel=threading.Event()
        self.work=tempfile.TemporaryDirectory();self.path=Path(self.work.name)
        self.config=self.api.ClientConfig(self.server.base,io_timeout_s=1,total_timeout_s=5)
    def tearDown(self):
        if hasattr(self,'work'):
            self.assertFalse(any(self.path.iterdir()),'download/session staging leaked');self.work.cleanup()
    def page(self):return self.api.list_sessions(self.config,cancel=self.cancel)
    def download(self,record,config=None,progress=lambda s:None):
        return self.api.download_session(config or self.config,record,self.path,cancel=self.cancel,progress=progress)
    def expect(self,code,call):
        with self.assertRaises(self.api.PCHttpError) as c:call()
        self.assertEqual(c.exception.code,code)
    def test_list_next_cursor_and_record_validation(self):
        page=self.page();self.assertEqual(page.items[0].session_id,SID);self.assertEqual(page.next_cursor,CURSOR)
        second=self.api.list_sessions(self.config,cursor=page.next_cursor,cancel=self.cancel)
        self.assertEqual(second.items,());self.assertIsNone(second.next_cursor)
        requests=[r for r in self.server.events() if r['event']=='request']
        self.assertIn('limit=50',requests[-1]['path']);self.assertIn('cursor=',requests[-1]['path'])
        for limit in (False,0,201):self.expect('CONFIG',lambda:self.api.list_sessions(self.config,limit=limit,cancel=self.cancel))
    def test_good_download_external_expectations_real_loader_close(self):
        from unittest.mock import patch
        record=self.page().items[0]
        with patch.object(self.api,'load_verified_mobile_zip',wraps=self.api.load_verified_mobile_zip) as gate:
            s=self.download(record)
            self.assertEqual(gate.call_args.args[1:4],(SID,3354368,SHA))
        try:
            self.assertEqual(s.session_id,SID);self.assertEqual(len(s.frames),4)
            self.assertEqual(s.report['zip_sha256'],SHA);self.assertTrue(s.download_path.is_file())
            self.assertFalse(Path(s.report['archive_path']).exists())
            self.assertEqual(len(s.select(0,100).points_m),207104)
        finally:s.close()
    def test_invalid_json_missing_fields_status_and_sort(self):
        for mode in ('bad_json','duplicate_json'):
            self.server.mode(mode);self.expect('INVALID_JSON',self.page)
        for field in ('session_id','storage_status','zip_size_bytes','zip_sha256','stored_at','download_path'):
            self.server.mode('missing',field=field);self.expect('INVALID_RESPONSE',self.page)
        for mode in ('not_stored','unordered'):
            self.server.mode(mode);self.expect('INVALID_RESPONSE',self.page)
        for field,value in (('zip_size_bytes',True),('zip_size_bytes',1.2),('zip_sha256',SHA.upper()),('stored_at','2026-10-22'),('download_path','https://elsewhere.invalid/archive'),('warnings',[{'code':'X','count':True}])):
            self.server.mode('invalid_record',field=field,value=value);self.expect('INVALID_RESPONSE',self.page)
    def test_header_identity_size_and_sha_mismatches(self):
        record=self.page().items[0]
        for mode in ('id_header','sha_header','size_header','no_length'):
            self.server.mode(mode);self.expect('HEADER_MISMATCH',lambda:self.download(record))
    def test_actual_hash_and_incomplete_transfer(self):
        record=self.page().items[0]
        for mode,code in (('body_hash','HASH_MISMATCH'),('short','INCOMPLETE_TRANSFER')):
            self.server.mode(mode);self.expect(code,lambda:self.download(record))
    def test_damaged_zip_and_internal_session_mismatch(self):
        for mode,verification_code in (('damaged','LOADER_REJECTED'),('internal_id','SESSION_ID_MISMATCH')):
            self.server.mode(mode);record=self.page().items[0]
            with self.assertRaises(self.api.PCHttpError) as c:self.download(record)
            self.assertEqual(c.exception.code,'ZIP_REJECTED');self.assertEqual(c.exception.verification_code,verification_code)
    def test_encoding_transfer_framing_and_content_type(self):
        record=self.page().items[0]
        for mode in ('encoding','transfer_encoding','wrong_type'):
            self.server.mode(mode);self.expect('REPRESENTATION_REJECTED',lambda:self.download(record))
    def test_limit_before_request_and_bounded_stream_guard(self):
        record=self.page().items[0];config=dataclasses.replace(self.config,max_archive_bytes=1000)
        before=len(self.server.events());self.expect('LIMIT_EXCEEDED',lambda:self.download(record,config))
        self.assertEqual(len(self.server.events()),before)
        from unittest.mock import patch
        class Overrun:
            def read1(self,n):return b'x'*(n+1)
        # Hostile stream boundary test, separate from real HTTP framing tests.
        with patch.object(self.api,'_read_chunk',return_value=b'x'*65537):
            self.expect('LIMIT_EXCEEDED',lambda:self.api._copy_archive(Overrun(),self.path/'part',1,1,'0'*64,self.cancel,lambda s:None))
        (self.path/'part').unlink(missing_ok=True)
    def test_http_statuses_and_bad_error_body_never_loaded(self):
        record=self.page().items[0]
        for status,code in ((401,'UNAUTHORIZED'),(403,'FORBIDDEN'),(404,'NOT_FOUND'),(500,'SERVER_ERROR'),(400,'HTTP_ERROR')):
            self.server.mode('http_error',status=status)
            self.expect(code,self.page);self.expect(code,lambda:self.download(record))
        self.server.mode('bad_error');self.expect('UNAUTHORIZED',lambda:self.download(record))
    def test_connection_timeout_cancellation_and_redirect(self):
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        cfg=self.api.ClientConfig(f'http://127.0.0.1:{port}',io_timeout_s=3,total_timeout_s=4)
        self.expect('CONNECTION_FAILED',lambda:self.api.list_sessions(cfg,cancel=self.cancel))
        for io,total in ((.2,.4),(2,.2)):
            self.server.mode('gate_headers')
            cfg=dataclasses.replace(self.config,io_timeout_s=io,total_timeout_s=total)
            try:self.expect('TIMEOUT',lambda:self.api.list_sessions(cfg,cancel=self.cancel))
            finally:self.server.release()
        self.cancel.set();self.expect('CANCELLED',self.page);self.cancel.clear()
        self.server.mode('redirect');self.expect('REDIRECT_REJECTED',self.page)
    def test_id_safe_encoding_and_transient_bearer(self):
        special='space / 한글?=#';self.server.mode('good',session_id=special)
        r=self.page().items[0]
        # Non-ASCII response-header representation still needs server agreement.
        from urllib.parse import quote
        self.assertEqual(self.api.archive_path(special),'/api/v1/sessions/'+quote(special,safe='')+'/archive')
        ascii_id='space / ?=#';self.server.mode('good',session_id=ascii_id)
        record=self.page().items[0]
        with self.assertRaises(self.api.PCHttpError) as mismatch:self.download(record)
        self.assertEqual(mismatch.exception.verification_code,'SESSION_ID_MISMATCH')
        requests=[e['path'] for e in self.server.events() if e['event']=='request']
        self.assertEqual(requests[-1],self.api.archive_path(ascii_id))
        token=secrets.token_urlsafe(24);cfg=dataclasses.replace(self.config,bearer_token=token)
        self.server.mode('good');self.api.list_sessions(cfg,cancel=self.cancel)
        self.assertTrue(token not in repr(cfg),'token repr must be redacted')
        self.assertTrue(all(token not in json.dumps(e) for e in self.server.events()),'fixture must not record tokens')
    def test_config_rejects_unsafe_url_and_unapproved_http(self):
        for url in ('http://192.168.0.30:8000','http://user:password@127.0.0.1','http://127.0.0.1/?token=value','file:///tmp','http://127.0.0.1/path'):
            self.expect('CONFIG',lambda:self.api.ClientConfig(url))
        # Construction only; never request the proposed private address.
        self.api.ClientConfig('https://example.invalid')
        from unittest.mock import patch
        import ssl
        # Context/error boundary only, NOT an actual TLS server/certificate test.
        with patch.object(self.api.http.client,'HTTPSConnection') as https:
            https.return_value.connect.side_effect=ssl.SSLCertVerificationError('test fixture certificate rejection')
            self.expect('TLS_ERROR',lambda:self.api.list_sessions(self.api.ClientConfig('https://example.invalid'),cancel=self.cancel))
            context=https.call_args.kwargs['context']
            self.assertTrue(context.check_hostname);self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)

if __name__=='__main__':unittest.main()
