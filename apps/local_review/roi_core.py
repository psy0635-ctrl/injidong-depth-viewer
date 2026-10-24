"""Local auxiliary rectangle labels; never a core target mask or volume footprint."""
import hashlib,json,os,uuid,sys,copy,time
from pathlib import Path,PureWindowsPath
import numpy as np
from projection import to_plane,_matrix,painter_rows,save_review_arrays
from paths import resolve_recorded,resolve_bundle_source,canonical_source_records,PRIOR_REVIEW

FORMAT='injidong_local_rectangle_roi'
VERSION='1.0.0'
NOTICE='검토용 사각형 ROI이며 물체와 주변 바닥을 함께 포함할 수 있습니다.\nclay 정답 마스크나 부피 footprint가 아닙니다.\n높이 제한은 적용하지 않습니다.'
SERIALIZATION='signed int64 little-endian, C contiguous bytes, original full-cloud row order; no header'

def normalize_roi(box):
    if box is None:return None
    a=np.asarray(box,dtype=np.float64)
    if a.shape!=(4,) or not np.isfinite(a).all():raise ValueError('ROI must have four finite bounds')
    u0,u1=sorted(a[:2]);v0,v1=sorted(a[2:])
    if u0==u1 or v0==v1:raise ValueError('ROI area must be positive; clear uses null')
    return [float(u0),float(u1),float(v0),float(v1)]

def select_mask(coordinates,box):
    q=np.asarray(coordinates)
    if q.ndim!=2 or q.shape[1]!=3:raise ValueError('Nx3 plane coordinates required')
    b=normalize_roi(box)
    if b is None:return np.zeros(len(q),dtype=bool)
    u0,u1,v0,v1=b
    return np.isfinite(q[:,:2]).all(axis=1)&(q[:,0]>=u0)&(q[:,0]<=u1)&(q[:,1]>=v0)&(q[:,1]<=v1)

def id_hash(ids):
    a=np.asarray(ids)
    if a.ndim!=1 or a.dtype.kind!='i' or a.dtype.itemsize!=8:raise ValueError('signed int64 IDs required')
    return hashlib.sha256(a.astype('<i8',copy=False).tobytes(order='C')).hexdigest()

def validate_basis(b):
    try:
        o,a=_matrix(b);p=np.asarray(b['oriented_plane_n_d_m'],dtype=np.float64)
        if p.shape!=(4,) or not np.isfinite(p).all() or not np.allclose(p[:3],a[:,2],atol=1e-12,rtol=0) or abs(o@p[:3]+p[3])>1e-12:raise ValueError('plane, origin and normal inconsistent')
        if b['unit']!='m':raise ValueError('basis unit must be m')
        if 'source_full_precision_plane' in b:
            s=np.asarray(b['source_full_precision_plane'],dtype=float)
            if s.shape!=(4,) or not np.isfinite(s).all() or not (np.allclose(s,p,atol=1e-12,rtol=0) or np.allclose(-s,p,atol=1e-12,rtol=0)):raise ValueError('source plane inconsistent')
    except (KeyError,TypeError) as e:raise ValueError('invalid saved basis') from e

def strict_read(p):
    def pairs(items):
        d={}
        for k,v in items:
            if k in d:raise ValueError('duplicate JSON key')
            d[k]=v
        return d
    def bad(v):raise ValueError('nonfinite JSON token: '+v)
    return json.loads(Path(p).read_text(encoding='utf-8'),object_pairs_hook=pairs,parse_constant=bad)

def sources(data,destination):
    from review_data import sha,FLOOR_RUN
    paths={}
    for kind in ('input_files_sha256','support_files_sha256'):
        paths.update(data.evidence[kind])
    # Pin original saved full-precision basis, and a representative prior review result.
    paths[str(FLOOR_RUN/'artifact_hashes.json')]=sha(FLOOR_RUN/'artifact_hashes.json')
    prior=PRIOR_REVIEW
    for n in ('review_basis.json','review_sidecar.json','review_arrays.npz'):
        paths[str(prior/n)]=sha(prior/n)
    return [{'relative_to':'bundle_directory','path':Path(os.path.relpath(resolve_recorded(p),destination)).as_posix(),'sha256':digest} for p,digest in sorted(paths.items())]

def full_arrays(data,rows):
    return {**{k:getattr(data.cloud,k) for k in ('points_m','pixel_id','pixel_vu','rgb_u8','color_candidate')},'plane_coordinates_m':data.coordinates,'display_full_rows':rows,'draw_order_full_rows':painter_rows(data.coordinates,data.cloud.pixel_id,rows)}

def publish_directory(partial,destination,attempts=10,delay_s=.05):
    """Bounded Windows WinError5 sharing recovery; publication stays one atomic rename."""
    partial,destination=Path(partial),Path(destination)
    if type(attempts) is not int or attempts<1 or delay_s<0:raise ValueError('invalid publication retry bounds')
    for attempt in range(attempts):
        if destination.exists():raise FileExistsError(str(destination))
        try:
            os.rename(partial,destination)
            return
        except PermissionError as e:
            if os.name!='nt' or getattr(e,'winerror',None)!=5 or attempt==attempts-1:raise
            time.sleep(delay_s)

def save_bundle(destination,data,box,rows,figure=None,*,adapter=None):
    from review_data import sha,write,load_contract,CODE,SESSION
    destination=Path(destination).resolve()
    if destination.exists():raise FileExistsError(str(destination))
    box=normalize_roi(box);validate_basis(data.basis)
    ids=data.cloud.pixel_id[select_mask(data.coordinates,box)]
    label={'format':FORMAT,'format_version':VERSION,'schema_version':'1.0.0','session_id':data.frame.metadata['session_id'],'frame_id':data.frame.metadata['frame_id'],
        'sources':(sources(data,destination) if adapter is None else adapter.sources(data,destination)),'full_point_count':len(data.cloud.pixel_id),'basis':data.basis,'roi_uv_m':box,'unit':'m','boundary_rule':'u_min <= u <= u_max AND v_min <= v <= v_max','height_limit':None,
        'selected_pixel_id':ids.tolist(),'selected_count':len(ids),'id_serialization':SERIALIZATION,'id_sha256':id_hash(ids),'purpose':'local review auxiliary only','notice':NOTICE}
    load_contract();sys.path.insert(0,str(CODE/'src'))
    from viewer_data import FrameView,export_frame
    # Failed writes remain named .partial-* and have no valid completion contract.
    partial=destination.with_name('.partial-'+uuid.uuid4().hex)
    export_frame(FrameView(data.frame,data.cloud.points_m,data.cloud.points_m[rows]),SESSION if adapter is None else adapter.input_session,partial)
    arrays=full_arrays(data,rows);save_review_arrays(partial/'review_arrays.npz',**arrays)
    write(partial/'review_basis.json',data.basis);write(partial/'roi.json',label)
    hashes={k:hashlib.sha256(v.tobytes()).hexdigest() for k,v in arrays.items() if k not in ('display_full_rows','draw_order_full_rows')}
    if figure is not None:
        with (partial/'review_screen.png').open('xb') as f:figure.savefig(f,format='png')
    write(partial/'review_sidecar.json',{'format':'ade71_local_support_orthographic_review_v1','role':'LOCAL REVIEW AUXILIARY, not core schema or geometry approval','source':data.evidence,'basis':data.basis,'metrics':data.metrics,'full_hashes':hashes,'core_metadata_modified':False,'geometry_verified_promoted':False,'processing_ready_promoted':False,'roi_auxiliary':'roi.json'})
    write(partial/'manifest.json',{p.name:sha(p) for p in partial.iterdir() if p.is_file()})
    write(partial/'COMPLETE.json',{'format':FORMAT,'manifest_sha256':sha(partial/'manifest.json')})
    # Flush all completed files before publishing the exclusive directory name.
    for p in partial.iterdir():
        with p.open('r+b') as f:f.flush();os.fsync(f.fileno())
    publish_directory(partial,destination) # Windows refuses an existing destination.
    return destination

def load_bundle(path,*,adapter=None):
    from review_data import sha,load_review
    p=Path(path).resolve()
    if p.name.startswith('.partial-'):raise ValueError('incomplete temporary save')
    if not (p/'COMPLETE.json').exists() and not (p/'roi.json').exists() and (p/'review_sidecar.json').exists():
        if adapter is not None:raise ValueError('mobile reopen requires a completed mobile ROI bundle')
        return load_legacy_review(p)
    try:
        complete=strict_read(p/'COMPLETE.json');manifest=strict_read(p/'manifest.json')
        if complete!={'format':FORMAT,'manifest_sha256':sha(p/'manifest.json')}:raise ValueError('completion manifest mismatch')
        if not {'roi.json','review_basis.json','review_arrays.npz','review_sidecar.json','viewer_export.json','processing.json','points.npz','preview.png'}.issubset(manifest):raise ValueError('incomplete bundle files')
        actual={f.name for f in p.iterdir() if f.is_file()}-{'COMPLETE.json','manifest.json'}
        if actual!=set(manifest):raise ValueError('bundle file inventory mismatch')
        for name,digest in manifest.items():
            if Path(name).name!=name or PureWindowsPath(name).drive or (p/name).is_symlink() or sha(p/name)!=digest:raise ValueError('bundle file hash mismatch: '+name)
        a=strict_read(p/'roi.json')
        if a['format']!=FORMAT or a['format_version']!=VERSION or a['schema_version']!='1.0.0':raise ValueError('unsupported ROI format')
        if a['height_limit'] is not None or a['unit']!='m' or a['boundary_rule']!='u_min <= u <= u_max AND v_min <= v <= v_max' or a['id_serialization']!=SERIALIZATION:raise ValueError('ROI semantics differ')
        validate_basis(a['basis'])
        if strict_read(p/'review_basis.json')!=a['basis']:raise ValueError('saved basis files differ')
        if a['roi_uv_m']!=normalize_roi(a['roi_uv_m']):raise ValueError('noncanonical ROI')
        if adapter is None:
            for r in a['sources']:
                if r['relative_to']!='bundle_directory' or PureWindowsPath(r['path']).drive or Path(r['path']).is_absolute():raise ValueError('relative source path required')
                if sha(resolve_bundle_source(p,r['path']))!=r['sha256']:raise ValueError('input/reference hash mismatch: '+r['path'])
        else:adapter.validate_sources(a['sources'])
        # Saved axes are supplied directly; no call to plane_basis on restoration.
        data=load_review(saved_basis=a['basis']) if adapter is None else adapter.load_data(a)
        if adapter is None:
            if canonical_source_records(p,sources(data,p))!=canonical_source_records(p,a['sources']):raise ValueError('source references missing or substituted')
        elif adapter.sources(data,p)!=a['sources']:raise ValueError('mobile source references differ')
        if a['session_id']!=data.frame.metadata['session_id'] or a['frame_id']!=data.frame.metadata['frame_id'] or type(a['full_point_count']) is not int or a['full_point_count']!=len(data.cloud.pixel_id):raise ValueError('identity/count mismatch')
        raw=a['selected_pixel_id']
        if not isinstance(raw,list) or any(type(i) is not int or i<0 or i>np.iinfo(np.int64).max for i in raw):raise ValueError('IDs must be nonnegative signed int64 integers')
        ids=np.array(raw,dtype=np.int64)
        if len(np.unique(ids))!=len(ids) or not np.isin(ids,data.cloud.pixel_id).all():raise ValueError('duplicate or unknown ID')
        if type(a['selected_count']) is not int or a['selected_count']!=len(ids) or id_hash(ids)!=a['id_sha256']:raise ValueError('ID count/hash mismatch')
        expected=data.cloud.pixel_id[select_mask(data.coordinates,a['roi_uv_m'])]
        if not np.array_equal(expected,ids):raise ValueError('recomputed full selection differs')
        with np.load(p/'review_arrays.npz',allow_pickle=False) as z:
            if set(z.files)!=set(full_arrays(data,np.empty(0,dtype=np.int64))):raise ValueError('saved array keys differ')
            rows=z['display_full_rows'];saved={k:z[k] for k in z.files}
        for k,arr in full_arrays(data,rows).items():
            if saved[k].dtype!=arr.dtype or not np.array_equal(saved[k],arr):raise ValueError('saved full correspondence differs: '+k)
        with np.load(p/'points.npz',allow_pickle=False) as z:
            if not np.array_equal(z['points_m'],data.cloud.points_m):raise ValueError('core points differ')
        if strict_read(p/'viewer_export.json')['input_metadata']!=data.frame.metadata:raise ValueError('core metadata differs')
        return data,a
    except (KeyError,TypeError,OverflowError) as e:raise ValueError('malformed ROI bundle') from e

def load_legacy_review(p):
    """Read the established prior review; missing ROI completion is never accepted as legacy."""
    from review_data import sha,load_review,load_contract
    try:
        side=strict_read(p/'review_sidecar.json')
        if side['format']!='ade71_local_support_orthographic_review_v1' or 'roi_auxiliary' in side:raise ValueError('not a complete legacy review')
        b=strict_read(p/'review_basis.json');validate_basis(b)
        if side['basis']!=b:raise ValueError('legacy saved bases differ')
        for name,digest in side['files_sha256'].items():
            if Path(name).name!=name or PureWindowsPath(name).drive or sha(p/name)!=digest:raise ValueError('legacy artifact hash mismatch')
        data=load_review(saved_basis=b)
        if side['source']!=data.evidence:raise ValueError('legacy source differs')
        for kind in ('input_files_sha256','support_files_sha256'):
            for name,digest in side['source'][kind].items():
                if sha(resolve_recorded(name))!=digest:raise ValueError('legacy source hash differs')
        with np.load(p/'review_arrays.npz',allow_pickle=False) as z:
            saved={k:z[k] for k in z.files}
        expected=full_arrays(data,saved['display_full_rows'])
        if set(saved)!=set(expected):raise ValueError('legacy arrays differ')
        for k,v in expected.items():
            if v.dtype!=saved[k].dtype or not np.array_equal(v,saved[k]):raise ValueError('legacy correspondence differs: '+k)
        for k,digest in side['full_hashes'].items():
            if hashlib.sha256(saved[k].tobytes()).hexdigest()!=digest:raise ValueError('legacy full array hash differs')
        if strict_read(p/'viewer_export.json')['input_metadata']!=data.frame.metadata:raise ValueError('legacy metadata differs')
        contract=load_contract();processing=strict_read(p/'processing.json');contract.validate_json(processing,'processing')
        if processing['volume_m3'] is not None:raise ValueError('legacy review must not claim volume')
        with np.load(p/'points.npz',allow_pickle=False) as z:
            if not np.array_equal(z['points_m'],data.cloud.points_m):raise ValueError('legacy core points differ')
        return data,{'roi_uv_m':None,'selected_pixel_id':[],'selected_count':0,'id_sha256':id_hash(np.empty(0,dtype=np.int64)),'basis':b,'legacy_review_import':True}
    except (KeyError,TypeError) as e:raise ValueError('malformed legacy review') from e
