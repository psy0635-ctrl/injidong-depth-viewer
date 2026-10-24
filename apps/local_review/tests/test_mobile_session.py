"""ZIP trust boundary and real saved-array equivalence, not sensor accuracy."""
import dataclasses
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

import numpy as np
try:
    import mobile_session as mobile
except ImportError:
    mobile = None

SAMPLE = Path(os.environ.get('MOBILE_TEST_ZIP',str(Path(__file__).with_name('external-sample-not-configured.zip'))))
SID = 'd405_1792497323680'
EXPECTED = {'d405_0000000001':207104, 'd405_0000000017':210516,
            'd405_0000000040':213661, 'd405_0000000056':172196}


@unittest.skipUnless(os.environ.get('MOBILE_TEST_ZIP'), 'external reference ZIP not supplied; real integration not run')
class MobileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with zipfile.ZipFile(SAMPLE) as z:
            cls.members = {i.filename:z.read(i) for i in z.infolist() if not i.is_dir()}

    def setUp(self):
        self.assertIsNotNone(mobile, 'mobile ZIP loader has not been implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def archive(self, changes=None, extra=(), compression=zipfile.ZIP_DEFLATED):
        p = self.root/'candidate.zip'
        with zipfile.ZipFile(p,'w',compression=compression) as z:
            for name,data in self.members.items():
                if changes and name in changes:
                    data=changes[name]
                if data is not None:z.writestr(name,data)
            for name,data in extra:
                if isinstance(name,str) and '\\' in name:
                    # ZipInfo.__init__ normalizes Windows separators; preserve a hostile on-disk name.
                    info=zipfile.ZipInfo();info.filename=name;info.orig_filename=name;name=info
                z.writestr(name,data)
        return p

    def change_json(self,name,mutate):
        value=json.loads(self.members[SID+'/'+name]);mutate(value)
        return {SID+'/'+name:json.dumps(value).encode()}

    def reject(self,p,code=None,limits=None):
        cache=self.root/'cache';cache.mkdir(exist_ok=True)
        with self.assertRaises(mobile.MobileInputError) as ctx:
            mobile.load_mobile_zip(p,cache,limits=limits)
        if code:self.assertEqual(ctx.exception.code,code)
        self.assertEqual(list(cache.iterdir()),[], 'failed input leaked an exposed session')

    def test_real_four_frames_match_existing_core_and_preserve_original(self):
        before=hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
        self.assertEqual(SAMPLE.stat().st_size,3354368)
        self.assertEqual(before,'72f3ebaff4c6fcb57675e702aca0854eeec162ce0de4f86b4b80de381cd07dff')
        session=mobile.load_mobile_zip(SAMPLE,self.root/'cache');self.addCleanup(session.close)
        self.assertEqual(session.session_id,SID)
        self.assertEqual(session.frame_ids,list(EXPECTED))
        self.assertEqual(session.report['counts'],{'depth_frames':4,'rgb_images':4,'imu_samples':1117})
        self.assertFalse(session.report['common_contract_fully_validated'])
        self.assertEqual(len(session.report['rgb_format_warnings']),4)
        contract=mobile.load_contract()
        for index,(fid,count) in enumerate(EXPECTED.items()):
            with self.subTest(frame=fid):
                view=session.select(index,display_limit=1234)
                original=contract.load_frame(session.session_dir/fid/'metadata.json')
                np.testing.assert_array_equal(view.frame.depth_m,original.depth_m)
                np.testing.assert_array_equal(view.frame.valid_mask,original.valid_mask)
                np.testing.assert_array_equal(view.points_m,contract.point_cloud_camera(original))
                self.assertEqual(view.frame.metadata,original.metadata)
                self.assertEqual(len(view.points_m),count)
                self.assertEqual(len(view.display_points_m),1234)
                self.assertFalse(view.frame.depth_m.flags.writeable)
                with zipfile.ZipFile(SAMPLE) as z:
                    with np.load(io.BytesIO(z.read(SID+'/'+fid+'/arrays.npz')),allow_pickle=False) as a:
                        np.testing.assert_array_equal(view.frame.depth_m,a['depth_m'])
                self.assertTrue(view.frame.valid_mask[view.frame.depth_m>6.5].all())
        self.assertEqual(hashlib.sha256(SAMPLE.read_bytes()).hexdigest(),before)
        self.assertEqual(session.file_inventory(),session.report['file_sha256'])

    def test_unsafe_windows_paths_and_parent_collisions_are_rejected(self):
        for name in ('../escape','/absolute','C:/drive','dir\\file','con.txt','bad.','a//b',
                     SID+'/FRAMES.JSONL',SID+'/frames.jsonl/child',SID+'/x/../../bad',
                     SID+'/COM1.txt',SID+'/a:b','e\u0301.txt',SID+'/LONGDI~1/a.txt'):
            with self.subTest(name=name):self.reject(self.archive(extra=[(name,b'x')]),'UNSAFE_ZIP')

    def test_duplicate_entry_is_rejected_before_extract(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            p=self.archive(extra=[(SID+'/frames.jsonl',b'bad')])
        self.reject(p,'UNSAFE_ZIP')

    def test_links_are_rejected(self):
        for mode in (stat.S_IFLNK,stat.S_IFIFO):
            info=zipfile.ZipInfo('link');info.create_system=3;info.external_attr=(mode|0o777)<<16
            self.reject(self.archive(extra=[(info,b'../elsewhere')]),'UNSAFE_ZIP')

    def test_corrupt_truncated_and_encrypted_archive(self):
        p=self.root/'broken.zip';p.write_bytes(SAMPLE.read_bytes()[:200]);self.reject(p,'INVALID_ZIP')
        p=self.archive(compression=zipfile.ZIP_STORED)
        data=bytearray(p.read_bytes())
        with zipfile.ZipFile(p) as z: i=z.getinfo(SID+'/frames.jsonl')
        off=i.header_offset+30+len(i.filename.encode())
        data[off]^=1;p.write_bytes(data);self.reject(p,'INVALID_ZIP')
        data=bytearray(SAMPLE.read_bytes())
        import struct
        pos=0
        while True:
            pos=data.find(b'PK\x01\x02',pos)
            if pos<0:break
            struct.pack_into('<H',data,pos+8,struct.unpack_from('<H',data,pos+8)[0]|1);pos+=4
        p.write_bytes(data);self.reject(p,'UNSUPPORTED_ZIP')

    def test_resource_limits_apply_before_extraction(self):
        defaults=mobile.ZipLimits()
        for field,value in [('max_archive_bytes',100),('max_members',5),('max_member_bytes',500),
                            ('max_total_bytes',1000),('max_ratio',1.01),('max_frames',2),
                            ('max_pixels',100),('max_total_pixels',500000)]:
            with self.subTest(limit=field):
                self.reject(SAMPLE,'LIMIT_EXCEEDED',dataclasses.replace(defaults,**{field:value}))

    def test_hash_id_missing_file_and_index_pairing_errors(self):
        fid=next(iter(EXPECTED))
        cases=[self.change_json(fid+'/metadata.json',lambda m:m['storage'].update(sha256='0'*64)),
               self.change_json(fid+'/metadata.json',lambda m:m['provenance'].update(raw_sha256='0'*64)),
               self.change_json(fid+'/metadata.json',lambda m:m.update(session_id='wrong')),
               self.change_json('session.json',lambda s:s['counts'].update(depth_frames=5)),
               self.change_json('session.json',lambda s:s['files'].update(images_index='rgb_index.jsonl')),
               self.change_json('session.json',lambda s:s['files'].update(phone_rgb_index='rgb_index.jsonl')),
               {SID+'/'+fid+'/arrays.npz':None},
               {SID+'/frames.jsonl':self.members[SID+'/frames.jsonl']*2}]
        for changes in cases:
            with self.subTest(changes=list(changes)):self.reject(self.archive(changes))
        self.reject(self.archive(extra=[(SID+'/rgb_index.jsonl',self.members[SID+'/images.jsonl'])]))

    def test_all_metadata_index_and_raw_evidence_refs_are_confined(self):
        fid=next(iter(EXPECTED))
        cases=[self.change_json(fid+'/metadata.json',lambda m:m['storage'].update(file='../arrays.npz')),
               self.change_json(fid+'/metadata.json',lambda m:m['provenance'].update(raw_file='../outside.bin')),
               self.change_json(fid+'/raw_capture.json',lambda r:r.update(metadata_file='../metadata.json'))]
        row=json.loads(self.members[SID+'/images.jsonl'].splitlines()[0]);row['file']='../outside.png'
        cases.append({SID+'/images.jsonl':json.dumps(row).encode()})
        for change in cases:
            with self.subTest(change=list(change)):self.reject(self.archive(change))

    def test_nested_npz_object_huge_shape_and_duplicates_rejected_without_allocation(self):
        fid=next(iter(EXPECTED));name=SID+'/'+fid+'/arrays.npz'
        obj=io.BytesIO();np.savez(obj,depth_m=np.array([object()],dtype=object),valid_mask=np.array([True]))
        header=io.BytesIO();np.lib.format.write_array_header_1_0(header,{'descr':'<f4','fortran_order':False,'shape':(2**32,2**32)})
        huge=io.BytesIO()
        with zipfile.ZipFile(huge,'w') as z:
            z.writestr('depth_m.npy',header.getvalue());z.writestr('valid_mask.npy',b'bad')
        for blob in (obj.getvalue(),huge.getvalue()):
            changes={name:blob};changes.update(self.change_json(fid+'/metadata.json',lambda m:m['storage'].update(sha256=hashlib.sha256(blob).hexdigest())))
            self.reject(self.archive(changes))

    def test_legacy_phone_index_pair_is_still_supported(self):
        # Same Depth bytes, explicit alternate phone manifest; never a claim of actual phone capture.
        manifest=json.loads(self.members[SID+'/session.json'])
        manifest['sources']['rgb']='android_phone_back_camera'
        manifest['files']['phone_rgb_index']=manifest['files'].pop('images_index')
        manifest['files']['phone_rgb_index']='rgb_index.jsonl'
        manifest['files']['phone_rgb_images']=manifest['files'].pop('rgb_images')
        manifest['counts']['phone_rgb_images']=manifest['counts'].pop('rgb_images')
        changes={SID+'/session.json':json.dumps(manifest).encode(),SID+'/images.jsonl':None}
        p=self.archive(changes,[(SID+'/rgb_index.jsonl',self.members[SID+'/images.jsonl'])])
        session=mobile.load_mobile_zip(p,self.root/'cache');self.addCleanup(session.close)
        self.assertEqual(session.frame_ids,list(EXPECTED))
        self.assertEqual(session.report['rgb_index']['selected_key'],'phone_rgb_index')

    def test_failed_load_and_stale_completion_clear_previous_state(self):
        from mobile_viewer import MobileController
        state=MobileController()
        old=state.begin_load();first=mobile.load_mobile_zip(SAMPLE,self.root/'one')
        self.assertTrue(state.accept(old,first));state.select(0)
        token=state.begin_load()
        self.assertIsNone(state.current);self.assertIsNone(state.session)
        self.assertFalse(first.session_dir.exists())
        state.fail(token,'broken ZIP')
        self.assertEqual(state.frame_ids,[]);self.assertIsNone(state.current)
        stale=mobile.load_mobile_zip(SAMPLE,self.root/'two')
        self.assertFalse(state.accept(old,stale));self.assertFalse(stale.session_dir.exists())


if __name__=='__main__':unittest.main()
