"""Load original single-frame RGB-D plus the saved full-precision object support plane."""
import hashlib,json,sys
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from PIL import Image
from paths import COLOR,FLOOR,FLOOR_RUN,recorded,resolve_recorded,require_robot_input
sys.path.insert(0,str(COLOR))
from paths import CODE,BASELINE,INTAKE,SESSION,FRAME_ID,load_contract
from color_data import build_color_cloud,select_display,zoom_limits
from color_evidence import validate_color_record
from projection import plane_basis,to_plane,from_plane

def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while b:=f.read(8*1024*1024):h.update(b)
    return h.hexdigest()
def write(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')

@dataclass(frozen=True)
class ReviewData:
    frame:object
    cloud:object
    basis:dict
    coordinates:np.ndarray
    support_full_rows:np.ndarray
    evidence:dict
    metrics:dict

def load_review(saved_basis=None):
    require_robot_input()
    contract=load_contract()
    from session_boundary import guard_read,relative_path
    guard_read(SESSION)
    entries=[json.loads(s) for s in (SESSION/'frames.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
    chosen=[e for e in entries if e['frame_id']==FRAME_ID]
    if len(chosen)!=1:raise ValueError('selected metadata entry missing/duplicated')
    metadata_path=relative_path(SESSION,chosen[0]['metadata_path']);frame=contract.load_frame(metadata_path)
    floor_hashes=read(FLOOR_RUN/'artifact_hashes.json')
    used=('independent_planes.json','selected_inputs.json','selected_support_points.npz','sensitivity.json','plane_comparison.json')
    for name in used:
        if sha(FLOOR_RUN/name)!=floor_hashes[name]:raise ValueError('saved support result hash mismatch: '+name)
    source=read(FLOOR_RUN/'selected_inputs.json')['object']
    if source['metadata']!=frame.metadata or resolve_recorded(source['metadata_path'])!=metadata_path:raise ValueError('support fit frame/metadata differs')
    previous_inputs=read(FLOOR_RUN/'source_hashes_before.json')
    for p in (metadata_path,metadata_path.parent/'arrays.npz',metadata_path.parent/'camera_calibration.json',metadata_path.parent/'aligned_rgb.png'):
        if sha(p)!=previous_inputs[recorded(p)]['sha256']:raise ValueError('support fit source bytes differ')
    rows=[json.loads(s) for s in (SESSION/'images.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
    matches=[r for r in rows if r['frame_id']==FRAME_ID and r['image_kind']=='aligned_rgb']
    if len(matches)!=1:raise ValueError('unique RGB reference required')
    image_row=matches[0];image_path=relative_path(SESSION,image_row['file'])
    if sha(image_path)!=image_row['sha256']:raise ValueError('RGB hash differs')
    calibration=read(metadata_path.parent/'camera_calibration.json')
    evidence=validate_color_record(frame.metadata,calibration,image_row)
    with Image.open(image_path) as im:
        im.load()
        if im.mode!='RGB':raise ValueError('RGB decoding mode differs')
        rgb=np.asarray(im).copy()
    cloud=build_color_cloud(frame,rgb)
    fitted=read(FLOOR_RUN/'independent_planes.json')['models']['object']
    plane=np.asarray(fitted['plane'],dtype=np.float64)
    if plane.shape!=(4,) or not np.isfinite(plane).all() or abs(np.linalg.norm(plane[:3])-1)>1e-10:raise ValueError('saved full-precision unit plane required')
    if saved_basis is None:
        basis=plane_basis(plane)
    else:
        import copy
        from roi_core import validate_basis
        validate_basis(saved_basis)
        basis=copy.deepcopy(saved_basis)
        if basis['source_full_precision_plane']!=plane.tolist():raise ValueError('saved basis source plane differs')
    coords=to_plane(cloud.points_m,basis)
    rebuilt=from_plane(coords,basis);delta=rebuilt-cloud.points_m.astype(np.float64);errors=np.linalg.norm(delta,axis=1)
    with np.load(FLOOR_RUN/'selected_support_points.npz',allow_pickle=False) as z:
        support_ids=z['object_pixel_id'];support_points=z['object_points']
    support_rows=np.searchsorted(cloud.pixel_id,support_ids)
    if np.any(support_rows>=len(cloud.pixel_id)) or not np.array_equal(cloud.pixel_id[support_rows],support_ids):raise ValueError('saved support pixel IDs absent')
    np.testing.assert_array_equal(cloud.points_m[support_rows].astype(np.float64),support_points)
    support_rows.flags.writeable=False
    basis.update({'source_file':recorded(FLOOR_RUN/'independent_planes.json'),'source_sha256':sha(FLOOR_RUN/'independent_planes.json'),
                  'source_model':'models.object','source_full_precision_plane':plane.tolist(),
                  'source_comparison_sign_rule':read(FLOOR_RUN/'independent_planes.json')['normal_sign'],
                  'comparison_vs_display_normal_dot':float(plane[:3]@np.asarray(basis['normal']))})
    metrics={'point_count':len(coords),'coordinate_dtype':str(coords.dtype),'coordinates_finite':bool(np.isfinite(coords).all()),
        'roundtrip_max_euclidean_error_m':float(errors.max()),'roundtrip_rmse_euclidean_error_m':float(np.sqrt(np.mean(errors**2))),
        'roundtrip_max_abs_per_axis_m':np.max(abs(delta),axis=0).tolist(),
        'basis_orthogonality_max_error':float(abs(np.column_stack([basis[k] for k in ('u_axis','v_axis','normal')]).T@np.column_stack([basis[k] for k in ('u_axis','v_axis','normal')])-np.eye(3)).max()),
        'prior_fit_evaluation':fitted['holdout_all'],'prior_evaluation_role':'historical holdout residual, not per-point error bound',
        'prior_ROI_sensitivity':read(FLOOR_RUN/'sensitivity.json')['leave_one_ROI_out'],
        'prior_sensitivity_role':'spatial/algorithmic sensitivity, not statistical confidence interval',
        'physical_accuracy_verified':False,'gravity_verified':False,'same_physical_pose_verified':False}
    evidence.update({'metadata_path':recorded(metadata_path),'metadata_sha256':sha(metadata_path),'session_id':frame.metadata['session_id'],'frame_id':FRAME_ID,
        'selected_single_frame_from_partial_extraction':True,'original_manifest_count':len(entries),'source_RGB':image_row,
        'input_files_sha256':{recorded(p):sha(p) for p in (metadata_path,metadata_path.parent/'arrays.npz',image_path,metadata_path.parent/'camera_calibration.json',SESSION/'frames.jsonl',SESSION/'images.jsonl')},
        'support_files_sha256':{recorded(FLOOR_RUN/n):sha(FLOOR_RUN/n) for n in used}})
    return ReviewData(frame,cloud,basis,coords,support_rows,evidence,metrics)
