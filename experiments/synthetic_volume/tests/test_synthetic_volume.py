"""Only the new synthetic volume boundary; no legacy suite is discovered."""
from pathlib import Path
import copy,json,sys,unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from synthetic_fixtures import cuboid

class SyntheticVolumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if (ROOT/'synthetic_volume.py').exists():
            import synthetic_volume
            cls.tool=synthetic_volume
        else: cls.tool=None
    def fixture(self):
        self.assertIsNotNone(self.tool,'height integration implementation not present yet')
        c=self.tool.load_contract(BASELINE)
        return c,cuboid(c)
    def call(self,data):return self.tool.analyze(*data)
    def assert_failure(self,data,code):
        result=self.call(data);p=result['processing_result']
        self.assertEqual(p['status'],'failure');self.assertIsNone(p['volume_m3']);self.assertIsNone(p['volume_method'])
        self.assertEqual(p['errors'][0]['code'],code)
    def test_known_cuboid_integrates_cell_area_times_height(self):
        # Fails if volume is point count, wrong area, missing cell, or wrong normal sign.
        c,data=self.fixture();r=self.call(data);p=r['processing_result']
        expected=.02*.03*.01
        self.assertEqual(p['status'],'success');self.assertEqual(p['provenance_kind'],'synthetic')
        self.assertLessEqual(abs(p['volume_m3']-expected),1e-15)
        self.assertEqual(r['diagnostics']['covered_cells'],6)
        self.assertEqual(r['diagnostics']['grid_shape_vu'],[3,2])
        self.assertTrue(r['diagnostics']['all_target_pixels_represented'])
    def test_duplicates_and_reordering_do_not_increase_volume(self):
        c,(f,p,x,a)=self.fixture();base=self.call((f,p,x,a))['processing_result']['volume_m3']
        order=np.array([5,1,0,4,2,3,0,0,5,4,2],dtype=np.int64)
        result=self.call((f,p[order],x[order],a))
        self.assertEqual(result['processing_result']['status'],'success')
        self.assertEqual(result['processing_result']['volume_m3'],base)
        self.assertEqual(result['diagnostics']['covered_cells'],6)
    def test_missing_cell_and_invalid_target_are_failures_not_zero_fill(self):
        c,(f,p,x,a)=self.fixture()
        self.assert_failure((f,p[1:],x[1:],a),'COVERAGE_INSUFFICIENT')
        f=copy.deepcopy(f);f.depth_m[0,0]=0;f.valid_mask[0,0]=False
        self.assert_failure((f,p,x,a),'COVERAGE_INSUFFICIENT')
    def test_bad_plane_basis_or_unconfirmed_assumptions_rejected(self):
        c,data=self.fixture()
        cases=[('normal','PLANE_INVALID'),('basis','PLANE_BASIS_INVALID'),('origin','PLANE_BASIS_INVALID'),('no_plane','SUPPORT_PLANE_REQUIRED'),('unconfirmed','VOLUME_ASSUMPTION_REQUIRED'),('local_assumption','VOLUME_ASSUMPTION_REQUIRED')]
        for kind,code in cases:
            with self.subTest(kind=kind):
                f,p,x,a=copy.deepcopy(data)
                if kind=='normal':f.metadata['support_plane']['normal']=[0.,0.,-2.]
                if kind=='basis':f.metadata['volume_request']['plane_basis']['v_axis']=[0.,1.,0.]
                if kind=='origin':f.metadata['volume_request']['plane_basis']['origin_m'][2]=1.02
                if kind=='no_plane':f.metadata['support_plane']=None
                if kind=='unconfirmed':f.metadata['volume_request']['assumptions_confirmed']=False
                if kind=='local_assumption':a['entire_top_observed']=False
                self.assert_failure((f,p,x,a),code)
    def test_unsupported_polygon_grid_boundary_and_nonfinite_rejected(self):
        c,data=self.fixture()
        for kind,code in [('triangle','CONFIG_INVALID'),('partial_cells','CONFIG_INVALID'),('boundary','CONFIG_INVALID'),('outside','CONFIG_INVALID'),('nan','INPUT_CORRUPT'),('negative_height','RESULT_INVALID')]:
            with self.subTest(kind=kind):
                f,p,x,a=copy.deepcopy(data)
                if kind=='triangle':f.metadata['volume_request']['footprint_polygon_uv_m'].pop()
                if kind=='partial_cells':f.metadata['volume_request']['grid_pitch_m']=.008
                if kind=='boundary':p[0,0]=0.
                if kind=='outside':p[0,0]=-.001
                if kind=='nan':p[0,0]=np.nan
                if kind=='negative_height':p[0,2]=1.02
                self.assert_failure((f,p,x,a),code)
    def test_translated_rotated_plane_uses_normal_height_not_camera_Z(self):
        c,(f,p,x,a)=self.fixture()
        theta=.3;R=np.array([[1.,0.,0.],[0.,np.cos(theta),-np.sin(theta)],[0.,np.sin(theta),np.cos(theta)]])
        shift=np.array([.2,.1,1.])
        b=f.metadata['volume_request']['plane_basis'];normal=R@np.array(f.metadata['support_plane']['normal'])
        origin=R@np.array(b['origin_m'])+shift
        b['origin_m']=origin.tolist();b['u_axis']=(R@np.array(b['u_axis'])).tolist();b['v_axis']=(R@np.array(b['v_axis'])).tolist()
        f.metadata['support_plane']['normal']=normal.tolist();f.metadata['support_plane']['offset_m']=-float(normal@origin)
        p=p@R.T+shift;f.depth_m=p[:,2].reshape(3,2).astype(np.float32)
        result=self.call((f,p,x,a));self.assertEqual(result['processing_result']['status'],'success')
        self.assertLessEqual(abs(result['processing_result']['volume_m3']-(.02*.03*.01)),1e-15)

class MigrationBoundaryTests(unittest.TestCase):
    def setUp(self):
        import uuid
        self.root=OUTPUT/uuid.uuid4().hex;self.root.mkdir()
    def cli(self,args):
        import os,subprocess,uuid
        env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
        p=subprocess.run([sys.executable,'-B','-X','utf8',str(ROOT/'run_synthetic_validation.py'),*args],
                         cwd=self.root,env=env,capture_output=True)
        name=uuid.uuid4().hex
        (self.root/(name+'.stdout.txt')).write_bytes(p.stdout)
        (self.root/(name+'.stderr.txt')).write_bytes(p.stderr)
        return p
    def test_saved_cli_eight_cases_units_imports_and_failure_nulls(self):
        import synthetic_volume as tool
        out=self.root/'validation'
        p=self.cli(['--baseline',str(BASELINE),'--output-root',str(out)])
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        summary=json.loads((out/'validation_summary.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['validation_status'],'passed_synthetic_height_integration_validation')
        self.assertEqual(len(summary['cases']),8)
        self.assertTrue(summary['read_files_preserved'])
        self.assertEqual(Path(summary['import_paths']['contract']).resolve(),BASELINE/'src/contract.py')
        for case in summary['cases'].values():
            self.assertTrue(case['matched_expectation'])
            self.assertTrue(case['exact_input_roundtrip'])
            self.assertTrue(case['result_json_reloaded_and_validated'])
            result=json.loads(Path(case['result']).read_text(encoding='utf-8'))
            self.assertEqual(result['units'],{'distance':'m','area':'m^2','volume':'m^3'})
            self.assertTrue(all(result[k] is False for k in tool.FLAGS))
            actual=result['processing_result']
            if case['expected_status']=='success':self.assertLessEqual(abs(actual['volume_m3']-(.02*.03*.01)),1e-15)
            else:
                self.assertIsNone(actual['volume_m3']);self.assertIsNone(actual['volume_method'])
                self.assertEqual(actual['errors'][0]['code'],case['expected_error'])
        a=summary['cases']['A_known_cuboid']['actual_volume_m3']
        self.assertEqual(a,summary['cases']['B_duplicates_reordered']['actual_volume_m3'])
        self.assertEqual(summary['cases']['D_bad_plane']['input_load']['rejected_error'],'PLANE_INVALID')
    def test_existing_overlapping_and_junction_output_rejected(self):
        import os,subprocess
        from _boundary import reserve_output, common
        protected=self.root/'input';protected.mkdir()
        marker=protected/'keep.txt';marker.write_bytes(b'unchanged')
        for output in (protected,protected/'child',self.root,ROOT/'not_an_output',BASELINE/'not_an_output'):
            with self.subTest(output=output),self.assertRaises(common.ComparisonFailure):reserve_output(output,[protected,BASELINE])
        self.assertEqual(marker.read_bytes(),b'unchanged')
        if os.name=='nt':
            alias=self.root/'alias'
            p=subprocess.run(['cmd','/c','mklink','/J',str(alias),str(protected)],capture_output=True)
            if p.returncode:self.skipTest('Windows junction creation unavailable')
            with self.assertRaises(common.ComparisonFailure):reserve_output(alias/'child',[protected])
    def test_extra_baseline_pins_and_conflicting_import_rejected(self):
        import types
        from unittest import mock
        import synthetic_volume as tool
        from _boundary import EXTRA_BASELINE_HASHES,common
        for relative in EXTRA_BASELINE_HASHES:
            bad=self.root/('bad_'+Path(relative).parent.name)
            for name in EXTRA_BASELINE_HASHES:
                dst=bad/name;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes((BASELINE/name).read_bytes())
            with (bad/relative).open('ab') as stream:stream.write(b'\n ')
            with self.subTest(pin=relative),self.assertRaises(common.ComparisonFailure):tool.load_contract(bad)
        fake=types.ModuleType('contract');fake.__file__=str(self.root/'wrong_contract.py')
        with mock.patch.dict(sys.modules,{'contract':fake}):
            with self.assertRaises(common.ComparisonFailure):tool.load_contract(BASELINE)
    def test_missing_arguments_and_bad_baseline_never_report_success(self):
        self.assertEqual(self.cli([]).returncode,2)
        out=self.root/'failed'
        p=self.cli(['--baseline',str(self.root/'absent_baseline'),'--output-root',str(out)])
        self.assertEqual(p.returncode,1)
        report=json.loads((out/'validation_summary.json').read_text(encoding='utf-8'))
        self.assertEqual(report['validation_status'],'failed');self.assertTrue(report['errors'])
    def test_synthetic_packet_marked_real_is_rejected(self):
        import synthetic_volume as tool
        c=tool.load_contract(BASELINE);f,p,x,a=cuboid(c)
        f.metadata['provenance']['kind']='real'
        result=tool.analyze(f,p,x,a)['processing_result']
        self.assertEqual(result['status'],'failure');self.assertIsNone(result['volume_m3'])
        self.assertEqual(result['errors'][0]['code'],'PROVENANCE_INVALID')

if __name__=='__main__':
    import argparse
    from _boundary import reserve_output
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',required=True,type=Path)
    parser.add_argument('--output-root',required=True,type=Path)
    args=parser.parse_args();BASELINE=args.baseline.resolve()
    OUTPUT=reserve_output(args.output_root,[BASELINE])
    result=unittest.main(argv=[sys.argv[0]],verbosity=2,exit=False).result
    raise SystemExit(0 if result.wasSuccessful() else 1)
