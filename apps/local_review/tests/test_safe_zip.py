"""No real sensor input: ZIP structure/CRC limits and pinned core regression."""
import dataclasses
import io
import json
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
import warnings
import zipfile
from safe_zip import MobileInputError, ZipLimits, extract_checked, inspect_zip
from paths import ROOT, BASELINE, load_contract


class SafeZipTests(unittest.TestCase):
    def make(self, entries, compression=zipfile.ZIP_DEFLATED):
        blob = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(blob, 'w', compression=compression) as z:
                for name, body in entries:
                    if isinstance(name, str) and '\\' in name:
                        info = zipfile.ZipInfo(); info.filename = name; info.orig_filename = name; name = info
                    z.writestr(name, body)
        blob.seek(0)
        return blob

    def test_good_archive_extracts_to_new_exclusive_files(self):
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(self.make([('session/file.txt', b'synthetic')])) as z:
            extract_checked(z, Path(tmp), ZipLimits())
            self.assertEqual((Path(tmp)/'session/file.txt').read_bytes(), b'synthetic')
            with self.assertRaises(FileExistsError):
                extract_checked(z, Path(tmp), ZipLimits())

    def test_unsafe_alias_and_parent_paths(self):
        for name in ('../escape', '/absolute', 'X:/drive', 'folder\\file', 'con.txt', 'bad.', 'a//b', 'a:b', 'e\u0301.txt', 'LONGDI~1/a'):
            with self.subTest(name=name), zipfile.ZipFile(self.make([(name,b'x')])) as z:
                with self.assertRaises(MobileInputError): inspect_zip(z, ZipLimits())

    def test_duplicate_case_and_file_folder_collisions(self):
        for entries in ([('a',b'x'),('a',b'y')], [('dir/a',b'x'),('DIR/b',b'y')], [('a',b'x'),('a/b',b'y')]):
            with self.subTest(entries=entries), zipfile.ZipFile(self.make(entries)) as z:
                with self.assertRaises(MobileInputError): inspect_zip(z, ZipLimits())

    def test_links_special_and_reparse_entries(self):
        for mode, attr in ((stat.S_IFLNK,0), (stat.S_IFIFO,0), (stat.S_IFREG,0x400)):
            info=zipfile.ZipInfo('link'); info.external_attr=((mode|0o777)<<16)|attr
            with zipfile.ZipFile(self.make([(info,b'target')])) as z:
                with self.assertRaises(MobileInputError): inspect_zip(z, ZipLimits())

    def test_size_count_ratio_limits(self):
        for key,value in (('max_members',0),('max_member_bytes',0),('max_total_bytes',0),('max_ratio',1)):
            with self.subTest(limit=key), zipfile.ZipFile(self.make([('data',b'x'*2000)])) as z:
                with self.assertRaises(MobileInputError): inspect_zip(z, dataclasses.replace(ZipLimits(),**{key:value}))

    def test_unsupported_compression_and_encryption(self):
        for encrypted in (False,True):
            with zipfile.ZipFile(self.make([('data',b'x')], zipfile.ZIP_BZIP2 if not encrypted else zipfile.ZIP_STORED)) as z:
                if encrypted: z.infolist()[0].flag_bits|=1
                with self.assertRaises(MobileInputError): inspect_zip(z, ZipLimits())

    def test_corrupt_crc_rejected(self):
        blob=bytearray(self.make([('data',b'synthetic')],zipfile.ZIP_STORED).getvalue())
        blob[30+len('data')]^=1
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(io.BytesIO(blob)) as z:
            with self.assertRaises(zipfile.BadZipFile): extract_checked(z,Path(tmp),ZipLimits())

    def test_invalid_zip_loader_cleans_owner(self):
        from mobile_session import load_mobile_zip
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bad=root/'bad.zip'; bad.write_bytes(b'broken zip')
            with self.assertRaises(MobileInputError): load_mobile_zip(bad,root/'cache')
            self.assertEqual(list((root/'cache').iterdir()),[])


class PinnedCoreTests(unittest.TestCase):
    def test_byte_hash_guard_and_core_version(self):
        import hashlib
        expected=json.loads((BASELINE/'tools/mobile_session_intake/baseline_hashes.json').read_text())
        for relative,digest in expected.items():
            self.assertEqual(hashlib.sha256((BASELINE/relative).read_bytes()).hexdigest(),digest)
        load_contract()
        schema=json.loads((BASELINE/'schemas/frame.schema.json').read_text())
        self.assertEqual(schema['properties']['schema_version']['enum'],['1.0.0'])

    def test_altered_core_copy_is_rejected(self):
        load_contract()
        from _common import load_baseline, ComparisonFailure
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'baseline'; dest.mkdir(); shutil.copytree(BASELINE/'src',dest/'src'); shutil.copytree(BASELINE/'schemas',dest/'schemas')
            target=dest/'src/contract.py';target.write_bytes(target.read_bytes()+b'\n# changed\n')
            with self.assertRaisesRegex(ComparisonFailure,'baseline mismatch'):
                load_baseline(dest)
