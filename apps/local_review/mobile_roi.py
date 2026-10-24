"""Mobile adapter for the existing floor-inclusive auxiliary ROI contract.

Depth candidate selection estimates a local plane, never gravity or a world pose.
Reopening requires an explicitly supplied, independently checked mobile ZIP session.
"""
import argparse,copy,hashlib,json,os
from pathlib import Path
import numpy as np
from mobile_session import load_contract,load_mobile_zip,digest
from plane_math import fit_robust,residual_stats
from projection import plane_basis,to_plane
from roi_core import validate_basis,id_hash,save_bundle,load_bundle
from review_data import ReviewData
from color_data import ColorCloud

SETTINGS={'threshold_m':.002,'seed':71020,'trials':800,'max_scoring_points':6000}
METHOD='Depth rectangle candidates / existing RANSAC then orthogonal TLS; exploratory 2mm, not accuracy acceptance'

def _cloud(session,index):
    view=session.select(index)
    frame=view.frame;v,u=np.nonzero(frame.valid_mask)
    arrays=[view.points_m,np.column_stack((v,u)).astype(np.int64),(v*frame.depth_m.shape[1]+u).astype(np.int64),
            np.zeros((len(v),3),dtype=np.uint8),np.zeros(len(v),dtype=np.bool_)]
    for a in arrays:a.flags.writeable=False
    return frame,ColorCloud(*arrays)

def prepare_review(session,index,bounds=None,*,saved_basis=None):
    frame,cloud=_cloud(session,index);h,w=frame.depth_m.shape
    if saved_basis is None:
        if not isinstance(bounds,(list,tuple)) or len(bounds)!=4 or any(type(x) is not int for x in bounds):raise ValueError('Depth candidate rectangle required; no support-plane fallback')
        x0,y0,x1,y1=bounds
        if not (0<=x0<x1<=w and 0<=y0<y1<=h):raise ValueError('candidate rectangle outside Depth grid')
        v,u=cloud.pixel_vu.T;rows=np.flatnonzero((u>=x0)&(u<x1)&(v>=y0)&(v<y1)).astype(np.int64)
        if len(rows)<6:raise ValueError('insufficient valid Depth support candidates')
        model=fit_robust(cloud.points_m[rows],**SETTINGS)
        basis=plane_basis(model['plane'])
        basis['source_full_precision_plane']=model['plane']
        basis['mobile_support']={'format':'mobile_depth_candidate_plane_v1','session_id':session.session_id,'frame_id':frame.metadata['frame_id'],
            'candidate_bounds_depth_px':list(bounds),'pixel_bounds_rule':'[u0,v0,u1,v1), zero-based half-open',
            'candidate_pixel_id':cloud.pixel_id[rows].tolist(),'candidate_id_sha256':id_hash(cloud.pixel_id[rows]),
            'candidate_xyz_sha256':hashlib.sha256(cloud.points_m[rows].tobytes()).hexdigest(),
            'method':METHOD,'algorithm_sha256':digest(Path(__file__).with_name('plane_math.py')),'settings':SETTINGS.copy(),'fit_result':model,
            'support_identity_verified':False,'gravity_verified':False,'coordinate_frame':'original Depth camera X right/Y down/Z forward, m'}
    else:
        basis=copy.deepcopy(saved_basis)
    validate_basis(basis)
    try:
        support=basis['mobile_support'];model=support['fit_result'];raw=support['candidate_pixel_id']
        if support['session_id']!=session.session_id or support['frame_id']!=frame.metadata['frame_id']:raise ValueError('support frame identity differs')
        if support['format']!='mobile_depth_candidate_plane_v1' or support['method']!=METHOD or support['settings']!=SETTINGS or support['algorithm_sha256']!=digest(Path(__file__).with_name('plane_math.py')):raise ValueError('support method differs')
        if support['support_identity_verified'] is not False or support['gravity_verified'] is not False:raise ValueError('unverified support status required')
        if not isinstance(raw,list) or len(raw)<6 or any(type(i) is not int or i<0 or i>=h*w for i in raw):raise ValueError('bad support pixel IDs')
        ids=np.array(raw,dtype=np.int64);rows=np.searchsorted(cloud.pixel_id,ids)
        if np.any(rows>=len(cloud.pixel_id)) or not np.array_equal(cloud.pixel_id[rows],ids) or np.any(np.diff(ids)<=0):raise ValueError('support IDs absent or unordered')
        x0,y0,x1,y1=support['candidate_bounds_depth_px']
        if any(type(x) is not int for x in (x0,y0,x1,y1)) or not (0<=x0<x1<=w and 0<=y0<y1<=h):raise ValueError('bad saved support bounds')
        v,u=cloud.pixel_vu.T
        expected=cloud.pixel_id[(u>=x0)&(u<x1)&(v>=y0)&(v<y1)]
        if not np.array_equal(ids,expected) or id_hash(ids)!=support['candidate_id_sha256'] or hashlib.sha256(cloud.points_m[rows].tobytes()).hexdigest()!=support['candidate_xyz_sha256']:raise ValueError('support correspondence differs')
        plane=np.asarray(model['plane'],dtype=np.float64)
        if basis['source_full_precision_plane']!=model['plane'] or plane.shape!=(4,) or abs(np.linalg.norm(plane[:3])-1)>1e-10:raise ValueError('support source plane differs')
        residual=cloud.points_m[rows].astype(np.float64)@plane[:3]+plane[3]
        if model['fit_point_count']!=len(rows) or model['inlier_count']!=int((abs(residual)<=SETTINGS['threshold_m']).sum()) or model['inlier_count']<max(6,len(rows)*.5):raise ValueError('saved support residuals differ')
    except (KeyError,TypeError,OverflowError) as e:raise ValueError('invalid mobile support evidence') from e
    rows.flags.writeable=False
    coords=to_plane(cloud.points_m,basis)
    evidence={'input_kind':'mobile_zip','session_id':session.session_id,'frame_id':frame.metadata['frame_id'],
        'zip_size_bytes':session.report['zip_size_bytes'],'zip_sha256':session.report['zip_sha256'],
        'rgb_used':False,'color_mode':'monochrome grey; zero RGB arrays are auxiliary placeholders, not sampled RGB',
        'physical_accuracy_verified':False,'gravity_verified':False,'support_identity_verified':False,
        'basis_role':'estimated candidate surface projection, not a verified floor/world frame','core_metadata_modified':False}
    return ReviewData(frame,cloud,basis,coords,rows,evidence,{'point_count':len(coords),'physical_accuracy_verified':False,'gravity_verified':False})

class MobileROI:
    def __init__(self,session,index):
        self.session=session;self.index=index;session.select(index,1)
        self.input_session=session.session_dir
    def sources(self,data,destination):
        if not self.session.frames or data.frame is not self.session.frames[self.index]:raise ValueError('closed or different frame session')
        return self._records()
    def _records(self):
        return [{'relative_to':'explicitly_supplied_mobile_zip','path':'.','sha256':self.session.report['zip_sha256'],
                 'size_bytes':self.session.report['zip_size_bytes'],'session_id':self.session.session_id,
                 'frame_id':self.session.frame_ids[self.index],'files_sha256':self.session.report['file_sha256']}]
    def validate_sources(self,records):
        if records!=self._records():raise ValueError('mobile archive/frame identity or source hashes differ')
    def load_data(self,label):
        if label['session_id']!=self.session.session_id or label['frame_id']!=self.session.frame_ids[self.index]:raise ValueError('mobile session/frame differs')
        return prepare_review(self.session,self.index,saved_basis=label['basis'])
    def save(self,destination,data,box,rows,figure=None):
        from paths import ROOT
        dest=Path(destination).resolve()
        if dest.is_relative_to(ROOT) or dest.is_relative_to(Path(self.session.owner.name).parent):raise ValueError('ROI output must be outside app and loader temporary cache')
        self.sources(data,dest)
        return save_bundle(dest,data,box,rows,figure,adapter=self)
    def open(self,path):return load_bundle(path,adapter=self)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',type=Path,required=True);p.add_argument('--bundle',type=Path,required=True);p.add_argument('--cache',type=Path,required=True)
    a=p.parse_args();session=load_mobile_zip(a.archive,a.cache)
    try:
        from roi_core import strict_read
        label=strict_read(a.bundle/'roi.json');fid=label['frame_id']
        if fid not in session.frame_ids:raise ValueError('saved frame absent in supplied ZIP')
        data,label=MobileROI(session,session.frame_ids.index(fid)).open(a.bundle)
        result={'pid':os.getpid(),'session_id':session.session_id,'frame_id':fid,'selected_count':label['selected_count'],
                'id_sha256':label['id_sha256'],'basis':data.basis,'source_zip_sha256':session.report['zip_sha256']}
    finally:session.close()
    result['cache_clean']=not any(a.cache.iterdir())
    print(json.dumps(result,ensure_ascii=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
