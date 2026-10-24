"""Unit boundary tests (fake loader) are separate from real-ZIP integration tests."""
import hashlib
import io
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import zipfile

try:
    import verified_mobile_zip as verified
except ModuleNotFoundError as exc:
    if exc.name!='verified_mobile_zip':raise
    verified=None

REAL_TEMP_DIRECTORY=tempfile.TemporaryDirectory
SID='d405_1792497323680'
SIZE=3354368
SHA='72f3ebaff4c6fcb57675e702aca0854eeec162ce0de4f86b4b80de381cd07dff'
SAMPLE=Path(os.environ.get('MOBILE_TEST_ZIP',str(Path(__file__).with_name('external-sample-not-configured.zip'))))

def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

class FakeSession:
    """Fake loader result with real owned files, not a real mobile validation."""
    def __init__(self,cache,sid,data,archive):
        self.owner=REAL_TEMP_DIRECTORY(prefix='fake_session_',dir=cache)
        self.session_dir=Path(self.owner.name)
        (self.session_dir/'marker').write_bytes(b'owned session')
        self.session_id=sid;self.closed=False
        self.report=dict(zip_size_bytes=len(data),zip_sha256=hashlib.sha256(data).hexdigest(),
                         archive_path=str(archive))
    def close(self):
        self.owner.cleanup();self.closed=True

class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(verified,'expected-value wrapper is not implemented')
        self.temp=self.enterContext(REAL_TEMP_DIRECTORY())
        self.root=Path(self.temp);self.source=self.root/'private-original-name.zip'
        self.data=b'original bytes';self.source.write_bytes(self.data)
        self.cache=self.root/'cache';self.cache.mkdir()
        self.sentinel=self.cache/'keep.txt';self.sentinel.write_bytes(b'existing caller file')
        self.sha=hashlib.sha256(self.data).hexdigest()
        self.sessions=[]
        self.addCleanup(self.cleanup_sessions)
    def cleanup_sessions(self):
        for s in self.sessions:
            if not s.closed:s.close()
    def call(self,**changes):
        args=dict(archive_path=self.source,expected_session_id='session-A',
                  expected_size_bytes=len(self.data),expected_sha256=self.sha,cache_root=self.cache)
        args.update(changes)
        return verified.load_verified_mobile_zip(**args)
    def fake_load(self,path,cache,**kwargs):
        s=FakeSession(cache,'session-A',Path(path).read_bytes(),path)
        self.sessions.append(s);return s
    def assert_clean(self):
        self.assertEqual(list(self.cache.iterdir()),[self.sentinel])
        self.assertEqual(self.sentinel.read_bytes(),b'existing caller file')
    def test_invalid_expectations_stop_before_file_or_loader_access(self):
        cases=[dict(expected_session_id=x) for x in (None,0,False,'',' \t',[])]
        cases += [dict(expected_size_bytes=x) for x in (True,False,0,-1,1.0,'12',None)]
        cases += [dict(expected_sha256=x) for x in (None,123,'',self.sha.upper(),'a'*63,'g'*64,'a'*65)]
        with mock.patch.object(verified.mobile,'load_mobile_zip') as loader:
            for change in cases:
                with self.subTest(change=change):
                    with self.assertRaises(verified.VerifiedZipError) as ctx:
                        self.call(archive_path=self.root/'missing.zip',**change)
                    self.assertEqual(ctx.exception.code,'INVALID_EXPECTATION')
                    self.assertNotIn(str(self.root),str(ctx.exception))
            loader.assert_not_called()
        self.assert_clean()
    def test_no_new_session_id_regex_or_length_limit_in_expectation_gate(self):
        for sid in ('한글 세션_1','x'*201):
            def load(path,cache,**kwargs):
                s=self.fake_load(path,cache,**kwargs);s.session_id=sid;return s
            with self.subTest(sid=sid),mock.patch.object(verified.mobile,'load_mobile_zip',side_effect=load):
                session=self.call(expected_session_id=sid);session.close();self.assert_clean()
    def test_size_mismatch_stops_before_loader(self):
        with mock.patch.object(verified.mobile,'load_mobile_zip') as loader:
            for expected_size in (len(self.data)-1,len(self.data)+1):
                with self.subTest(size=expected_size):
                    with self.assertRaises(verified.VerifiedZipError) as ctx:self.call(expected_size_bytes=expected_size)
                    self.assertEqual(ctx.exception.code,'SIZE_MISMATCH');loader.assert_not_called()
                    self.assert_clean()
        self.assert_clean()
    def test_same_size_different_bytes_fail_hash_before_loader(self):
        self.source.write_bytes(b'X'+self.data[1:])
        with mock.patch.object(verified.mobile,'load_mobile_zip') as loader:
            with self.assertRaises(verified.VerifiedZipError) as ctx:self.call()
            self.assertEqual(ctx.exception.code,'HASH_MISMATCH');loader.assert_not_called()
        self.assert_clean()
    def test_missing_file_is_sanitized_access_failure(self):
        with mock.patch.object(verified.mobile,'load_mobile_zip') as loader:
            with self.assertRaises(verified.VerifiedZipError) as ctx:self.call(archive_path=self.root/'secret-name.zip')
            self.assertEqual(ctx.exception.code,'FILE_ACCESS');loader.assert_not_called()
            self.assertNotIn(str(self.root),str(ctx.exception));self.assertNotIn('secret-name',str(ctx.exception))
        self.assert_clean()
    def test_loader_rejection_keeps_code_without_internal_path(self):
        error=verified.mobile.MobileInputError('UNSAFE_ZIP','private path '+str(self.root))
        with mock.patch.object(verified.mobile,'load_mobile_zip',side_effect=error):
            with self.assertRaises(verified.VerifiedZipError) as ctx:self.call()
            self.assertEqual(ctx.exception.code,'LOADER_REJECTED')
            self.assertEqual(ctx.exception.loader_code,'UNSAFE_ZIP')
            self.assertNotIn(str(self.root),str(ctx.exception))
        self.assert_clean()
    def test_session_id_mismatch_closes_returned_session(self):
        with mock.patch.object(verified.mobile,'load_mobile_zip',side_effect=self.fake_load):
            with self.assertRaises(verified.VerifiedZipError) as ctx:self.call(expected_session_id='other-ID')
            self.assertEqual(ctx.exception.code,'SESSION_ID_MISMATCH')
        self.assertTrue(self.sessions[0].closed);self.assert_clean()
    def test_success_transfers_session_but_not_staging_copy(self):
        with mock.patch.object(verified.mobile,'load_mobile_zip',side_effect=self.fake_load) as loader:
            session=self.call()
        self.assertIs(session,self.sessions[0]);self.assertFalse(session.closed)
        checked_path=Path(loader.call_args.args[0])
        self.assertNotEqual(checked_path,self.source);self.assertFalse(checked_path.exists())
        self.assertTrue(session.session_dir.exists())
        session.close();self.assert_clean()
        self.assertEqual(self.source.read_bytes(),self.data)
    def test_original_path_change_after_validation_does_not_change_loader_input(self):
        def load(path,cache,**kwargs):
            self.source.write_bytes(b'replaced after validation')
            self.assertEqual(Path(path).read_bytes(),self.data)
            return self.fake_load(path,cache,**kwargs)
        with mock.patch.object(verified.mobile,'load_mobile_zip',side_effect=load):
            session=self.call();session.close()
        self.assert_clean()
    def test_hashing_reads_bounded_chunks(self):
        self.data=b'A'*(2*1024*1024+7);self.source.write_bytes(self.data)
        self.sha=hashlib.sha256(self.data).hexdigest();requests=[]
        real_open=Path.open
        class Reader:
            def __init__(inner,stream):inner.stream=stream
            def __enter__(inner):return inner
            def __exit__(inner,*args):inner.stream.close()
            def read(inner,size=-1):
                requests.append(size)
                self.assertGreater(size,0);self.assertLessEqual(size,1024*1024)
                return inner.stream.read(size)
        def open_path(path,*args,**kwargs):
            stream=real_open(path,*args,**kwargs)
            return Reader(stream) if path==self.source and args==('rb',) else stream
        with mock.patch.object(Path,'open',open_path),mock.patch.object(verified.mobile,'load_mobile_zip',side_effect=self.fake_load):
            session=self.call();session.close()
        self.assertGreaterEqual(len(requests),3);self.assert_clean()
    def test_loader_report_changed_bytes_are_not_accepted(self):
        for key,value,code in (('zip_size_bytes',99,'SIZE_MISMATCH'),('zip_sha256','0'*64,'HASH_MISMATCH')):
            def load(path,cache,**kwargs):
                s=self.fake_load(path,cache,**kwargs);s.report[key]=value;return s
            with self.subTest(key=key),mock.patch.object(verified.mobile,'load_mobile_zip',side_effect=load):
                with self.assertRaises(verified.VerifiedZipError) as ctx:self.call()
                self.assertEqual(ctx.exception.code,code)
            self.assertTrue(self.sessions[-1].closed);self.assert_clean()
    def test_cache_inside_code_is_rejected_without_writes(self):
        destination=Path(verified.mobile.ROOT)/'must_not_be_created'
        self.assertFalse(destination.exists())
        with self.assertRaises(verified.VerifiedZipError) as ctx:self.call(cache_root=destination)
        self.assertEqual(ctx.exception.code,'FILE_ACCESS');self.assertFalse(destination.exists())
        self.assert_clean()
    def test_copy_guard_reuses_loader_archive_limit(self):
        with mock.patch.object(verified.mobile,'load_mobile_zip') as loader:
            with self.assertRaises(verified.VerifiedZipError) as ctx:
                self.call(limits=verified.mobile.ZipLimits(max_archive_bytes=4))
            self.assertEqual(ctx.exception.code,'LOADER_REJECTED')
            self.assertEqual(ctx.exception.loader_code,'LIMIT_EXCEEDED');loader.assert_not_called()
        self.assert_clean()
    def test_staging_cleanup_failure_does_not_transfer_session(self):
        class FailingCleanup(REAL_TEMP_DIRECTORY):
            def __exit__(inner,*args):
                super().__exit__(*args)
                raise PermissionError('private cleanup path '+str(self.root))
        with mock.patch.object(verified.tempfile,'TemporaryDirectory',FailingCleanup),mock.patch.object(verified.mobile,'load_mobile_zip',side_effect=self.fake_load):
            with self.assertRaises(verified.VerifiedZipError) as ctx:self.call()
            self.assertEqual(ctx.exception.code,'FILE_ACCESS');self.assertNotIn(str(self.root),str(ctx.exception))
        self.assertTrue(self.sessions[0].closed);self.assert_clean()

@unittest.skipUnless(os.environ.get('MOBILE_TEST_ZIP'), 'external reference ZIP not supplied; real integration not run')
class RealZipTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(verified,'expected-value wrapper is not implemented')
        self.assertTrue(SAMPLE.is_file(),'real ZIP missing; no integration success may be claimed')
        self.assertEqual(SAMPLE.stat().st_size,SIZE);self.assertEqual(digest(SAMPLE),SHA)
        self.root=Path(self.enterContext(REAL_TEMP_DIRECTORY()))
        self.cache=self.root/'cache'
        self.addCleanup(self.assert_original_preserved)
    def assert_original_preserved(self):
        self.assertEqual(SAMPLE.stat().st_size,SIZE);self.assertEqual(digest(SAMPLE),SHA)
    def load(self,path=SAMPLE,sid=SID,size=SIZE,sha=SHA):
        return verified.load_verified_mobile_zip(path,sid,size,sha,self.cache)
    def assert_clean(self):self.assertFalse(self.cache.exists() and any(self.cache.iterdir()))
    def test_real_zip_passes_and_explicit_close_removes_owned_files(self):
        session=self.load()
        try:
            self.assertEqual(session.session_id,SID);self.assertEqual(len(session.frames),4)
            self.assertEqual(session.report['zip_size_bytes'],SIZE);self.assertEqual(session.report['zip_sha256'],SHA)
            self.assertEqual(session.report['counts'],dict(depth_frames=4,rgb_images=4,imu_samples=1117))
            self.assertFalse(session.report['physical_accuracy_verified'])
            self.assertEqual(len(session.report['rgb_format_warnings']),4)
            owned=session.session_dir;self.assertTrue(owned.exists())
            self.assertFalse(Path(session.report['archive_path']).exists())
        finally:session.close()
        self.assertFalse(owned.exists());self.assertEqual(session.frames,());self.assert_clean()
    def test_real_internal_session_id_mismatch_is_closed(self):
        real=verified.mobile.load_mobile_zip;sessions=[]
        def observe(*args,**kwargs):
            s=real(*args,**kwargs);sessions.append(s);return s
        with mock.patch.object(verified.mobile,'load_mobile_zip',side_effect=observe):
            with self.assertRaises(verified.VerifiedZipError) as ctx:self.load(sid='expected-other-ID')
            self.assertEqual(ctx.exception.code,'SESSION_ID_MISMATCH')
        self.assertEqual(sessions[0].frames,());self.assertFalse(sessions[0].session_dir.exists());self.assert_clean()
    def test_matching_outer_digest_does_not_bypass_existing_zip_checks(self):
        invalid=self.root/'corrupt.zip';invalid.write_bytes(b'not a ZIP')
        inappropriate=self.root/'no-session.zip'
        with zipfile.ZipFile(inappropriate,'w') as z:z.writestr('note.txt','not a mobile session')
        for path in (invalid,inappropriate):
            with self.subTest(path=path.name):
                with self.assertRaises(verified.VerifiedZipError) as ctx:
                    self.load(path=path,size=path.stat().st_size,sha=digest(path))
                self.assertEqual(ctx.exception.code,'LOADER_REJECTED')
                self.assertIn(ctx.exception.loader_code,('INVALID_ZIP','INVALID_SESSION'))
                self.assert_clean()
    def test_real_loader_uses_verified_copy_when_download_path_is_replaced(self):
        local=self.root/'download.zip';shutil.copyfile(SAMPLE,local)
        real=verified.mobile.load_mobile_zip
        def replace_then_load(path,*args,**kwargs):
            local.write_bytes(b'changed test download, never the source sample')
            return real(path,*args,**kwargs)
        with mock.patch.object(verified.mobile,'load_mobile_zip',side_effect=replace_then_load):
            session=self.load(path=local)
        try:self.assertEqual(session.session_id,SID);self.assertEqual(session.report['zip_sha256'],SHA)
        finally:session.close()
        self.assert_clean()

if __name__=='__main__':unittest.main()
