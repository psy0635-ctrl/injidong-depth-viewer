"""Compare a selected stored depth frame; no SDK/physical processing approval."""
import argparse
from datetime import datetime,timezone,timedelta
import hashlib,json,platform,sys,traceback
from pathlib import Path
import numpy as np
from _common import (ComparisonFailure, require, file_record, write_json_new, TrackedReads,
                     reserve_output, load_baseline, select_metadata, read_depth, raw_source, FLAGS)
KST=timezone(timedelta(hours=9))
TOLERANCE = {
    'rule': 'abs(actual_float32_as_float64 - reference_float64) <= 0.5 * abs(spacing(reference_float64.astype(float32))).astype(float64)',
    'rtol': 0, 'automatic_widening': False,
    'reason': 'int64 pixel minus Python float, times float32 Z, divided by Python float all produce float64 intermediates; final cast is float32. Independent scalar float64 uses subtraction then multiplication then division. Half a float32 ULP bounds this final rounding.',
    'exact_float32_cast_comparison': 'separate array_equal against reference64.astype(float32)',
}

def independent_reference(depth, mask, intrinsics):
    """Separate scalar row traversal; never calls contract or a shared cloud helper."""
    require(depth.ndim==2 and mask.shape==depth.shape and mask.dtype==np.bool_, 'invalid reference input')
    fx,fy,cx,cy = (np.float64(intrinsics[k]) for k in ('fx','fy','cx','cy'))
    require(np.isfinite([fx,fy,cx,cy]).all() and fx>0 and fy>0,'invalid reference intrinsics')
    count = int(np.count_nonzero(mask))
    points = np.empty((count,3),dtype=np.float64)
    pixels = np.empty((count,2),dtype=np.int64)
    row = 0
    for v in range(depth.shape[0]):
        for u in range(depth.shape[1]):
            if bool(mask[v,u]):
                z = np.float64(depth[v,u])
                points[row,0] = ((np.float64(u)-cx)*z)/fx
                points[row,1] = ((np.float64(v)-cy)*z)/fy
                points[row,2] = z
                pixels[row] = (v,u)
                row += 1
    return points,pixels

def compare_coordinates(points, pixel_vu, depth, mask, intrinsics):
    count = int(np.count_nonzero(mask))
    require(points.dtype==np.float32 and points.shape==(count,3),'cloud must be float32 valid_count x 3')
    require(np.isfinite(points).all(),'nonfinite cloud coordinate')
    require(pixel_vu.dtype==np.int64 and pixel_vu.shape==(count,2),'pixels must be int64 valid_count x 2')
    require(count>0,'empty comparison')
    reference,pixels = independent_reference(depth,mask,intrinsics)
    reference32 = reference.astype(np.float32)
    require(np.isfinite(reference).all() and np.isfinite(reference32).all(),'nonfinite reference')
    # Fixed before the real run. Convert spacing to float64 BEFORE half multiplication.
    limits = np.abs(np.spacing(reference32).astype(np.float64))*np.float64(.5)
    errors = np.abs(points.astype(np.float64)-reference)
    exceeded = errors>limits
    exact32 = bool(np.array_equal(points,reference32))
    pixel_order = bool(np.array_equal(pixel_vu,pixels))
    source_z = depth[pixels[:,0],pixels[:,1]]
    z_match = bool(np.array_equal(points[:,2],source_z))
    details = {
        'point_count':count, 'coordinate_count':int(points.size),
        'shape':list(points.shape),'dtype':str(points.dtype),'finite':True,
        'pixel_shape':list(pixel_vu.shape),'pixel_dtype':str(pixel_vu.dtype),
        'pixel_row_major_exact_match':pixel_order,'source_Z_exact_match':z_match,
        'max_abs_error_m_xyz':errors.max(axis=0).tolist(),
        'max_abs_error_m':float(errors.max()),
        'exceeding_coordinate_count_xyz':np.count_nonzero(exceeded,axis=0).tolist(),
        'exceeding_coordinate_count':int(np.count_nonzero(exceeded)),
        'exceeding_point_count':int(np.count_nonzero(np.any(exceeded,axis=1))),
        'max_allowed_error_m_xyz':limits.max(axis=0).tolist(),
        'min_allowed_error_m_xyz':limits.min(axis=0).tolist(),
        'exact_float32_cast_match':exact32,
        'exact_float64_value_match':bool(np.array_equal(points.astype(np.float64),reference)),
        'within_fixed_tolerance':not bool(exceeded.any()),
        'independent_reference':'nested v-then-u loops, scalar float64, no point_cloud_camera/shared helper',
        'tolerance':TOLERANCE,
    }
    require(pixel_order and z_match and exact32 and not exceeded.any(),
            'coordinate or pixel correspondence/order mismatch',details)
    return details

def save_analysis_npz(path, points, pixels):
    path = Path(path)
    with path.open('xb') as stream:
        np.savez_compressed(stream,points_m=points,pixel_vu=pixels)
    before_reload = file_record(path)
    with np.load(path,allow_pickle=False) as saved:
        require(set(saved.files)=={'points_m','pixel_vu'},'unexpected analysis NPZ keys')
        p,q = saved['points_m'],saved['pixel_vu']
        p_ok = p.dtype==points.dtype and p.shape==points.shape and np.array_equal(p,points)
        q_ok = q.dtype==pixels.dtype and q.shape==pixels.shape and np.array_equal(q,pixels)
        require(p_ok and q_ok,'NPZ exact roundtrip mismatch')
    require(file_record(path)==before_reload,'NPZ bytes changed during reload')
    return {'path':str(path.resolve()),**before_reload,'allow_pickle':False,
            'points_exact_after_reload':bool(p_ok),'pixels_exact_after_reload':bool(q_ok),
            'unit':'m','coordinate_frame':'camera','pixel_order':'v ascending then u ascending; valid pixels only',
            'arrays':{'points_m':{'dtype':str(points.dtype),'shape':list(points.shape)},
                      'pixel_vu':{'dtype':str(pixels.dtype),'shape':list(pixels.shape),'columns':['v','u']}}}


def raw_65535_correspondence(session, metadata_path, frame, points, pixels, tracked, expected_count):
    raw,side,path = raw_source(session,metadata_path,frame.metadata,tracked)
    raw_pixels = np.argwhere(raw==65535).astype(np.int64)
    require(len(raw_pixels)==expected_count, 'raw 65535 count differs from declared expectation')
    scale = frame.metadata['provenance']['raw_scale_to_m']
    require(np.isfinite(scale) and scale>0, 'invalid recorded raw scale')
    scaled = (raw.astype(np.float64)*np.float64(scale)).astype(np.float32)
    unmatched = int(np.count_nonzero(scaled!=frame.depth_m))
    require(unmatched==0, 'same-index raw-to-stored relation not established; remap evidence required')
    rv,ru = raw_pixels.T
    require(frame.valid_mask[rv,ru].all(), 'raw 65535 source pixels are not all valid')
    width = frame.depth_m.shape[1]
    rows = np.searchsorted(pixels[:,0]*width+pixels[:,1],rv*width+ru)
    require((rows<len(pixels)).all() and np.array_equal(pixels[rows],raw_pixels), 'raw 65535 point mapping mismatch')
    require(np.array_equal(points[rows,2],frame.depth_m[rv,ru]), 'raw 65535 Z not preserved')
    return {'raw_path':str(path),'raw_sha256':file_record(path)['sha256'],
        'raw_dtype':'<u2','stride_bytes':side['raw_stride_bytes'],
        'byte_order_source':side['raw_byte_order_source'],'source_raw_65535_count':len(raw_pixels),
        'valid_count':int(frame.valid_mask[rv,ru].sum()),'included_result_count':len(rows),
        'stored_depth_values_m':np.unique(frame.depth_m[rv,ru]).tolist(),
        'raw_scaled_to_stored_mismatching_pixel_count':unmatched,
        'correspondences':[{'v':int(v),'u':int(u),'point_row':int(row)} for (v,u),row in zip(raw_pixels,rows)],
        'physical_meaning':'unconfirmed; preserved-array inclusion is not validity approval',
        'filtered':False,'clipped':False,'invalidated':False,'remapping_performed':False}

def run(args):
    baseline,session = Path(args.baseline).resolve(),Path(args.session).resolve()
    output = reserve_output(args.output,[baseline,session])
    tracked = TrackedReads()
    report = {'artifact_type':'stored_array_camera_pointcloud_analysis_v1',
        'analysis_status':'stored_array_pointcloud_comparison_failed','frame_id':args.frame_id,
        'session':str(session),'baseline':str(baseline),'argv':sys.argv,
        'started_at_kst':datetime.now(KST).isoformat(),'expected_valid_count':args.expected_valid_count,
        'expected_raw_65535_count':args.expected_raw65535_count,'tolerance_declared_before_execution':TOLERANCE,
        'environment':{'python':sys.version,'executable':sys.executable,'numpy':np.__version__,'platform':platform.platform()},
        **FLAGS,'errors':[]}
    try:
        contract=load_baseline(baseline,tracked)
        report['module_paths']={name:str(Path(sys.modules[name].__file__).resolve()) for name in ('contract','session_boundary')}
        path,entry,metadata=select_metadata(session,args.frame_id,tracked)
        depth,valid=read_depth(path,metadata,tracked)
        frame=contract.load_frame(path);contract.validate_frame(frame)
        require(int(valid.sum())==args.expected_valid_count, 'valid count differs from declared expectation')
        points=contract.point_cloud_camera(frame)
        pixels=np.column_stack(np.nonzero(valid)).astype(np.int64)
        report['selected_manifest_entry']=entry
        report['comparison']=compare_coordinates(points,pixels,depth,valid,metadata['intrinsics'])
        report['raw_65535_preservation']=raw_65535_correspondence(session,path,frame,points,pixels,tracked,args.expected_raw65535_count)
        report['saved_analysis_npz']=save_analysis_npz(output/'analysis_points.npz',points,pixels)
    except Exception as error:
        report['errors'].append({'type':type(error).__name__,'message':str(error),'details':getattr(error,'details',{}),'traceback':traceback.format_exc()})
    finally:
        try:report.update(tracked.finish())
        except Exception as error:report['errors'].append({'type':type(error).__name__,'message':str(error)})
        report['finished_at_kst']=datetime.now(KST).isoformat()
    if not report['errors']:report['analysis_status']='stored_array_pointcloud_comparison_passed'
    write_json_new(output/'stored_array_comparison.json',report)
    print(json.dumps({'analysis_status':report['analysis_status'],'report':str(output/'stored_array_comparison.json'),'errors':report['errors']},ensure_ascii=False))
    return 0 if not report['errors'] else 1

def nonnegative(text):
    value=int(text)
    if value<0:raise argparse.ArgumentTypeError('nonnegative integer required')
    return value

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('baseline','session','output'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--frame-id',required=True)
    parser.add_argument('--expected-valid-count',required=True,type=nonnegative)
    parser.add_argument('--expected-raw65535-count',required=True,type=nonnegative)
    args=parser.parse_args()
    try:return run(args)
    except Exception:
        traceback.print_exc();return 1
if __name__=='__main__':raise SystemExit(main())
