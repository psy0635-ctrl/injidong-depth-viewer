"""Actual Windows file-sharing tests for atomic save publication; no mocked success."""
import os,ctypes,tempfile,threading,time,unittest
from pathlib import Path
import roi_core
class PublishTests(unittest.TestCase):
    def lock(self,path):
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        k.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p];k.CreateFileW.restype=ctypes.c_void_p
        k.CloseHandle.argtypes=[ctypes.c_void_p];k.CloseHandle.restype=ctypes.c_int
        handle=k.CreateFileW(str(path),0x80000000,1,None,3,0,None)
        if handle in (None,ctypes.c_void_p(-1).value):raise OSError(ctypes.get_last_error(),'CreateFileW')
        return lambda:k.CloseHandle(handle)
    @unittest.skipUnless(os.name=='nt','Windows sharing lock test')
    def test_short_sharing_lock_recovers_without_changing_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'.partial-test';src.mkdir();file=src/'payload.bin';file.write_bytes(b'preserved');release=self.lock(file)
            timer=threading.Timer(.1,release);timer.start()
            try:roi_core.publish_directory(src,Path(d)/'published')
            finally:timer.join()
            self.assertEqual((Path(d)/'published/payload.bin').read_bytes(),b'preserved');self.assertFalse(src.exists())
    @unittest.skipUnless(os.name=='nt','Windows sharing lock test')
    def test_persistent_lock_is_bounded_and_leaves_only_partial(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'.partial-test';src.mkdir();file=src/'payload.bin';file.write_bytes(b'preserved');release=self.lock(file)
            start=time.monotonic()
            try:
                with self.assertRaises(PermissionError):roi_core.publish_directory(src,Path(d)/'published',attempts=3,delay_s=.01)
            finally:release()
            self.assertLess(time.monotonic()-start,1);self.assertTrue(src.exists());self.assertFalse((Path(d)/'published').exists());self.assertEqual(file.read_bytes(),b'preserved')
    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'.partial-test';src.mkdir();dest=Path(d)/'published';dest.mkdir();(dest/'keep').write_bytes(b'old')
            with self.assertRaises(FileExistsError):roi_core.publish_directory(src,dest)
            self.assertEqual((dest/'keep').read_bytes(),b'old');self.assertTrue(src.exists())
