"""Small behavioral checks: asymmetry/invalid pixels, coordinate damage, row damage."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

class StoredArrayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / 'compare_stored_depth.py'
        if path.exists():
            import compare_stored_depth
            cls.tool = compare_stored_depth
        else:
            cls.tool = None

    def fixture(self):
        self.assertIsNotNone(self.tool, 'analysis comparison implementation is not present yet')
        baseline = BASELINE
        contract = self.tool.load_baseline(baseline)
        metadata = json.loads((baseline/'examples/synthetic/frame_000001/metadata.json').read_text(encoding='utf-8'))
        metadata = copy.deepcopy(metadata)
        metadata['depth'].update(height=2, width=3)
        metadata['intrinsics'].update(height=2,width=3,fx=2.0,fy=4.0,cx=0.5,cy=0.25)
        depth = np.array([[1,0,2],[4,5,0]], dtype=np.float32)
        packet = contract.FramePacket(metadata, depth, depth>0)
        contract.validate_frame(packet)
        return contract, packet

    def test_asymmetric_intrinsics_and_invalid_pixels_have_known_rows_and_roundtrip(self):
        # Catches swapped fx/fy or u/v, ignored invalid mask, or lossy saved mapping.
        contract, frame = self.fixture()
        points = contract.point_cloud_camera(frame)
        pixels = np.array([[0,0],[0,2],[1,0],[1,1]], dtype=np.int64)
        expected = np.array([[-.25,-.0625,1],[1.5,-.125,2],[-1,.75,4],[1.25,.9375,5]], dtype=np.float64)
        reference, independently_ordered = self.tool.independent_reference(frame.depth_m, frame.valid_mask, frame.metadata['intrinsics'])
        np.testing.assert_array_equal(reference, expected)
        np.testing.assert_array_equal(independently_ordered, pixels)
        stats = self.tool.compare_coordinates(points, pixels, frame.depth_m, frame.valid_mask, frame.metadata['intrinsics'])
        self.assertEqual(stats['point_count'], 4)
        self.assertTrue(stats['exact_float32_cast_match'])
        self.assertTrue(stats['exact_float64_value_match'])
        # Each test run gets its own local fixture output; no temp folder outside this workspace.
        import uuid
        destination = OUTPUT/('fixture_'+uuid.uuid4().hex+'.npz')
        saved = self.tool.save_analysis_npz(destination, points, pixels)
        self.assertTrue(saved['points_exact_after_reload'])
        self.assertTrue(saved['pixels_exact_after_reload'])

    def test_modified_coordinate_is_rejected(self):
        # Catches a comparator that records errors but returns success.
        contract, frame = self.fixture()
        points = contract.point_cloud_camera(frame)
        pixels = np.array([[0,0],[0,2],[1,0],[1,1]], dtype=np.int64)
        points[0,0] += np.float32(.01)
        with self.assertRaises(self.tool.ComparisonFailure):
            self.tool.compare_coordinates(points,pixels,frame.depth_m,frame.valid_mask,frame.metadata['intrinsics'])

    def test_point_or_pixel_order_damage_is_rejected(self):
        # Catches comparison as a set or sorting away a wrong producer row order.
        contract, frame = self.fixture()
        points = contract.point_cloud_camera(frame)
        pixels = np.array([[0,0],[0,2],[1,0],[1,1]], dtype=np.int64)
        for bad_points,bad_pixels in [(points[::-1].copy(),pixels),(points,pixels[::-1].copy()),(points[::-1].copy(),pixels[::-1].copy())]:
            with self.subTest(points_reversed=not np.array_equal(points,bad_points),pixels_reversed=not np.array_equal(pixels,bad_pixels)):
                with self.assertRaises(self.tool.ComparisonFailure):
                    self.tool.compare_coordinates(bad_points,bad_pixels,frame.depth_m,frame.valid_mask,frame.metadata['intrinsics'])


import argparse,hashlib,os,subprocess,types
from unittest import mock
from _common import reserve_output, ComparisonFailure, BASELINE_HASHES
import compare_stored_depth as tool


def synthetic_session(root):
    root.mkdir(); folder=root/'not_the_frame_id';folder.mkdir();(root/'raw').mkdir()
    metadata=json.loads((BASELINE/'examples/synthetic/frame_000001/metadata.json').read_text(encoding='utf-8'))
    metadata.update(frame_id='synthetic_review',session_id='synthetic_review_session')
    metadata['depth'].update(height=2,width=3)
    metadata['intrinsics'].update(height=2,width=3,fx=2.,fy=4.,cx=.5,cy=.25)
    raw=np.array([[10000,0,20000],[40000,65535,0]],dtype='<u2')
    rawfile=root/'raw/source.bin';rawfile.write_bytes(raw.tobytes())
    scale=.0001;depth=(raw.astype(np.float64)*scale).astype(np.float32);valid=raw>0
    metadata['provenance'].update(raw_file='raw/source.bin',raw_sha256=hashlib.sha256(rawfile.read_bytes()).hexdigest(),raw_unit='synthetic_Z16',raw_scale_to_m=scale,synthetic_config='generated synthetic strided-raw fixture; no physical measurements')
    arrays=folder/'arrays.npz'
    with arrays.open('xb') as stream:np.savez_compressed(stream,depth_m=depth,valid_mask=valid)
    metadata['storage']['sha256']=hashlib.sha256(arrays.read_bytes()).hexdigest()
    mp=folder/'metadata.json';mp.write_text(json.dumps(metadata),encoding='utf-8')
    side={'frame_id':metadata['frame_id'],'session_id':metadata['session_id'],'paths_relative_to':'session_root',
      'metadata_file':'not_the_frame_id/metadata.json','metadata_sha256':hashlib.sha256(mp.read_bytes()).hexdigest(),
      'raw_file':'raw/source.bin','raw_sha256':metadata['provenance']['raw_sha256'],
      'raw_width':3,'raw_height':2,'raw_stride_bytes':6,'raw_bytes_per_pixel':2,'raw_byte_order':'little_endian',
      'raw_byte_order_source':'synthetic_fixture_convention','raw_data_size_bytes':len(raw.tobytes())}
    (folder/'raw_capture.json').write_text(json.dumps(side),encoding='utf-8')
    (root/'frames.jsonl').write_text(json.dumps({'frame_id':metadata['frame_id'],'metadata_path':'not_the_frame_id/metadata.json'})+'\n',encoding='utf-8')
    return root

class MovedBoundaryTests(unittest.TestCase):
    def setUp(self):
        import uuid
        self.root=OUTPUT/uuid.uuid4().hex;self.root.mkdir()
    def compare_args(self,session,output,count=4):
        return ['--baseline',str(BASELINE),'--session',str(session),'--frame-id','synthetic_review',
                '--expected-valid-count',str(count),'--expected-raw65535-count','1','--output',str(output)]
    def cli(self,name,args):
        env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
        process=subprocess.run([sys.executable,'-B','-X','utf8',str(ROOT/name),*args],cwd=self.root,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        import uuid
        (self.root/(name+'_'+uuid.uuid4().hex+'.log')).write_bytes(process.stdout+process.stderr)
        return process
    def test_synthetic_cli_comparison_then_static_pngs(self):
        session=synthetic_session(self.root/'session');out=self.root/'comparison'
        p=self.cli('compare_stored_depth.py',self.compare_args(session,out));self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        report=json.loads((out/'stored_array_comparison.json').read_text(encoding='utf-8'))
        self.assertEqual(report['raw_65535_preservation']['included_result_count'],1)
        self.assertTrue(report['read_files_preserved'])
        png=self.root/'pngs'
        p=self.cli('make_static_figures.py',['--session',str(session),'--frame-id','synthetic_review','--pointcloud',str(out/'analysis_points.npz'),'--comparison-report',str(out/'stored_array_comparison.json'),'--output',str(png)])
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        view=json.loads((png/'visualization_results.json').read_text(encoding='utf-8'))
        self.assertFalse(view['pointcloud_recomputed'])
        self.assertEqual(view['images']['pointcloud.png']['raw_65535_displayed_count'],1)
        self.assertEqual(len(view['png_checks']),3)
    def test_expected_count_failure_never_publishes_success(self):
        session=synthetic_session(self.root/'session');out=self.root/'wrong_count'
        p=self.cli('compare_stored_depth.py',self.compare_args(session,out,count=5));self.assertEqual(p.returncode,1)
        report=json.loads((out/'stored_array_comparison.json').read_text(encoding='utf-8'))
        self.assertEqual(report['analysis_status'],'stored_array_pointcloud_comparison_failed')
        self.assertNotIn('saved_analysis_npz',report)
        self.assertTrue(all(report[k] is False for k in tool.FLAGS))
    def test_output_overlap_existing_and_code_are_rejected(self):
        protected=self.root/'input';protected.mkdir()
        for output in (protected,protected/'child',self.root,ROOT/'cannot_write_here'):
            with self.subTest(output=output),self.assertRaises(ComparisonFailure):reserve_output(output,[protected])
    def test_windows_junction_parent_alias_is_rejected(self):
        if os.name!='nt':self.skipTest('requires Windows junction')
        protected=self.root/'input';protected.mkdir();alias=self.root/'alias'
        p=subprocess.run(['cmd','/c','mklink','/J',str(alias),str(protected)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if p.returncode:self.skipTest('junction creation unavailable')
        with self.assertRaises(ComparisonFailure):reserve_output(alias/'child',[protected])
    def test_pinned_baseline_mismatch_and_loaded_module_conflict_rejected(self):
        bad=self.root/'bad_baseline'
        for relative in json.loads(BASELINE_HASHES.read_text(encoding='utf-8')):
            dst=bad/relative;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes((BASELINE/relative).read_bytes())
        with (bad/'src/contract.py').open('ab') as stream:stream.write(b'\n# tampered synthetic copy\n')
        with self.assertRaises(ComparisonFailure):tool.load_baseline(bad)
        fake=types.ModuleType('contract');fake.__file__=str(self.root/'different_contract.py')
        with mock.patch.dict(sys.modules,{'contract':fake}):
            with self.assertRaises(ComparisonFailure):tool.load_baseline(BASELINE)
    def test_cli_missing_required_arguments_returns_usage_error(self):
        for name in ('compare_stored_depth.py','make_static_figures.py'):
            with self.subTest(name=name):self.assertEqual(self.cli(name,[]).returncode,2)
    def test_visualization_rejects_cloud_hash_mismatch(self):
        session=synthetic_session(self.root/'session');out=self.root/'comparison'
        self.assertEqual(self.cli('compare_stored_depth.py',self.compare_args(session,out)).returncode,0)
        bad_dir=self.root/'wrong_cloud';bad_dir.mkdir()
        bad=bad_dir/'wrong.npz';bad.write_bytes(b'not the compared cloud')
        png=self.root/'pngs'
        p=self.cli('make_static_figures.py',['--session',str(session),'--frame-id','synthetic_review','--pointcloud',str(bad),'--comparison-report',str(out/'stored_array_comparison.json'),'--output',str(png)])
        self.assertEqual(p.returncode,1)
        value=json.loads((png/'visualization_results.json').read_text(encoding='utf-8'))
        self.assertEqual(value['visualization_status'],'failed');self.assertEqual(list(png.glob('*.png')),[])

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',required=True,type=Path)
    parser.add_argument('--output-root',required=True,type=Path)
    args=parser.parse_args();BASELINE=args.baseline.resolve()
    OUTPUT=reserve_output(args.output_root,[BASELINE])
    outcome=unittest.main(argv=[sys.argv[0]],verbosity=2,exit=False).result
    raise SystemExit(0 if outcome.wasSuccessful() else 1)
