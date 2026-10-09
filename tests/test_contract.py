import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from contract import (ROOT, ContractError, load_frame, iter_frames, validate_frame,
                      validate_json, normalize_depth, point_cloud_camera,
                      volume_preflight, model_not_ready)

class ContractTests(unittest.TestCase):
    def setUp(self):
        self.f=load_frame(ROOT/'examples/synthetic/frame_000001/metadata.json')
    def error(self,code,fn):
        with self.assertRaises(ContractError) as context: fn()
        self.assertEqual(context.exception.code,code)
    def test_mm_conversion_and_expected_cloud(self):
        d,m=normalize_depth(np.array([[1000,1000],[1000,0]],dtype=np.uint16),0.001)
        np.testing.assert_array_equal(d,self.f.depth_m)
        np.testing.assert_array_equal(m,self.f.valid_mask)
        np.testing.assert_allclose(point_cloud_camera(self.f),[[0,0,1],[.01,0,1],[0,.01,1]],atol=1e-7)
    def test_nan_negative_zero_invalid_canonical(self):
        d,m=normalize_depth([[1,np.nan],[0,-1]],1)
        np.testing.assert_array_equal(d,[[1,0],[0,0]])
        np.testing.assert_array_equal(m,[[True,False],[False,False]])
    def test_dtype_does_not_imply_scale(self):
        self.error('UNIT_UNKNOWN',lambda:normalize_depth([[1000]],None))
    def test_ray_distance_not_accepted_as_z(self):
        self.error('SEMANTICS_UNSUPPORTED',lambda:normalize_depth([[1]],1,'ray_distance'))
    def test_shape_rejected(self):
        self.f.valid_mask=self.f.valid_mask[:1]
        self.error('DEPTH_SHAPE_INVALID',lambda:validate_frame(self.f))
    def test_dtype_rejected(self):
        self.f.depth_m=self.f.depth_m.astype(np.float64)
        self.error('DEPTH_DTYPE_INVALID',lambda:validate_frame(self.f))
    def test_invalid_depth_not_silently_used(self):
        self.f.depth_m[1,1]=2
        self.error('DEPTH_VALUES_INVALID',lambda:validate_frame(self.f))
    def test_all_invalid_rejected(self):
        self.f.depth_m[:]=0; self.f.valid_mask[:]=False
        self.error('NO_VALID_DEPTH',lambda:validate_frame(self.f))
    def test_intrinsics_matches_depth_not_rgb(self):
        self.f.metadata['intrinsics']['width']=4
        self.error('INTRINSICS_INVALID',lambda:validate_frame(self.f))
    def test_invalid_focal_rejected(self):
        self.f.metadata['intrinsics']['fx']=0
        self.error('SCHEMA_INVALID',lambda:validate_frame(self.f))
    def test_pose_null_standalone_allowed_world_rejected(self):
        validate_frame(self.f)
        self.error('POSE_REQUIRED',lambda:validate_frame(self.f,require_world_pose=True))
    def test_replay_preserves_original_time(self):
        original=copy.deepcopy(self.f.metadata['capture_time'])
        self.f.metadata['replay_time']={'ns':'1770000000000000000','clock_domain':'pc_monotonic','origin':'replay_host'}
        validate_frame(self.f)
        self.assertEqual(original,self.f.metadata['capture_time'])
    def test_timestamp_partial_null_rejected(self):
        self.f.metadata['capture_time']['clock_domain']=None
        self.error('TIMESTAMP_INVALID',lambda:validate_frame(self.f))
    def test_verified_sync_requires_evidence(self):
        self.f.metadata['sync']['status']='verified'
        self.error('SYNC_UNVERIFIED',lambda:validate_frame(self.f))
    def test_world_sync_guard(self):
        self.f.metadata['pose']={'from_frame':'camera','to_frame':'world','translation_m':[0,0,0],'quaternion_xyzw':[0,0,0,1],'time':copy.deepcopy(self.f.metadata['capture_time']),'calibration_id':'synthetic-test'}
        self.error('SYNC_UNVERIFIED',lambda:validate_frame(self.f,require_world_pose=True))
        self.f.metadata['sync']={'status':'verified','offset_ns':'0','uncertainty_ns':'100','tolerance_ns':'1000','evidence':'synthetic clock equality fixture, not real calibration'}
        validate_frame(self.f,require_world_pose=True)
        self.f.metadata['sync']['offset_ns']='1000'
        self.error('SYNC_UNVERIFIED',lambda:validate_frame(self.f))
    def test_volume_missing_target_is_failure(self):
        self.error('TARGET_UNAVAILABLE',lambda:volume_preflight(self.f))
    def test_labels_cannot_leak_into_features(self):
        feature=json.loads((ROOT/'examples/results/features_synthetic.json').read_text())
        feature['ground_truth_weight_g']=100
        self.error('SCHEMA_INVALID',lambda:validate_json(feature,'features'))
    def test_model_missing_is_not_zero_grams(self):
        feature=json.loads((ROOT/'examples/results/features_synthetic.json').read_text())
        r=model_not_ready(feature)
        self.assertEqual(r['status'],'not_ready'); self.assertIsNone(r['predicted_weight_g'])
        r['predicted_weight_g']=0
        self.error('RESULT_INVALID',lambda:validate_json(r,'prediction'))
    def test_result_fixtures(self):
        for file,name in [('volume_unavailable','processing'),('point_cloud_success','processing'),('prediction_not_ready','prediction'),('prediction_success_synthetic','prediction'),('features_synthetic','features'),('label_synthetic','label')]:
            validate_json(json.loads((ROOT/'examples/results'/f'{file}.json').read_text()),name)
    def test_quaternion_not_normalized_rejected(self):
        self.f.metadata['pose']={'from_frame':'camera','to_frame':'world','translation_m':[0,0,0],'quaternion_xyzw':[0,0,0,2],'time':copy.deepcopy(self.f.metadata['capture_time']),'calibration_id':'synthetic-test'}
        self.error('POSE_INVALID',lambda:validate_frame(self.f))
    def test_target_shape_rejected(self):
        self.f.metadata['storage']['target_mask_key']='target_mask'
        self.f.metadata['target_mask_info']={'source':'synthetic fixture','version':'1'}
        self.f.target_mask=np.ones((1,2),dtype=bool)
        self.error('TARGET_INVALID',lambda:validate_frame(self.f))
    def test_volume_basis_and_coverage(self):
        self.f.metadata['storage']['target_mask_key']='target_mask'
        self.f.metadata['target_mask_info']={'source':'synthetic fixture','version':'1'}
        self.f.target_mask=self.f.valid_mask.copy()
        self.error('SUPPORT_PLANE_REQUIRED',lambda:volume_preflight(self.f))
        self.f.metadata['support_plane']={'frame':'camera','normal':[0,0,-1],'offset_m':1.1,'method':'synthetic','evidence':'fixture'}
        self.f.metadata['volume_request']={'method':'height_integration','assumptions_confirmed':True,'assumption_evidence':'synthetic known footprint and top only; not hardware verification','plane_basis':{'origin_m':[0,0,1.1],'u_axis':[1,0,0],'v_axis':[0,-1,0]},'footprint_polygon_uv_m':[[0,0],[.01,0],[.01,-.01]],'grid_pitch_m':.01}
        self.assertTrue(volume_preflight(self.f))
        self.f.metadata['volume_request']['plane_basis']['v_axis']=[0,1,0]
        self.error('PLANE_BASIS_INVALID',lambda:volume_preflight(self.f))
        self.f.metadata['volume_request']['plane_basis']['v_axis']=[0,-1,0]
        self.f.target_mask[1,1]=True
        self.error('COVERAGE_INSUFFICIENT',lambda:volume_preflight(self.f))
    def test_success_does_not_imply_quality_pass(self):
        r=json.loads((ROOT/'examples/results/prediction_success_synthetic.json').read_text())
        self.assertEqual(r['quality'],'unknown')
        r['quality']='pass'
        self.error('RESULT_INVALID',lambda:validate_json(r,'prediction'))
    def test_pose_model_requires_pose_features(self):
        f=json.loads((ROOT/'examples/results/features_synthetic.json').read_text())
        f['feature_version']='volume_pose_v1'
        self.error('POSE_REQUIRED',lambda:validate_json(f,'features'))
    def test_real_data_cannot_relabel_synthetic_fixture(self):
        self.f.metadata['provenance']['kind']='real'
        self.error('PROVENANCE_INVALID',lambda:validate_frame(self.f))
    def test_checksum_catches_changed_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); m=copy.deepcopy(self.f.metadata)
            (p/'metadata.json').write_text(json.dumps(m))
            (p/'arrays.npz').write_bytes(b'corrupted')
            self.error('INPUT_CORRUPT',lambda:load_frame(p/'metadata.json'))
    def test_iter_manifest_roundtrip(self):
        frames=list(iter_frames(ROOT/'examples/synthetic'))
        self.assertEqual(len(frames),1)
        self.assertEqual(frames[0].metadata['frame_id'],'synthetic_000001')
    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'frames.jsonl').write_text(json.dumps({'frame_id':'x','metadata_path':'../outside.json'})+'\n')
            self.error('PATH_INVALID',lambda:list(iter_frames(tmp)))

if __name__=='__main__': unittest.main()
