"""Development-only synthetic height integration; never accepts real provenance."""
import math
import numpy as np

GEOMETRY_ATOL=1e-12
GRID_RATIO_ATOL=1e-10
VOLUME_ATOL_M3=1e-15
_CONTRACT=None
FLAGS=dict.fromkeys(('geometry_verified','processing_ready','viewer_launched','sdk_values_independently_verified','common_framepacket_fully_validated'),False)
ASSUMPTIONS=('known_footprint','entire_top_observed','solid_single_valued_columns','no_cavities_or_overhangs')
POLICY={
 'policy_id':'synthetic-rect-center-max-dev-v1','team_approved':False,
 'supported_footprint':'exact four-corner CCW axis-aligned rectangle in supplied plane u/v; lower-left first; no repeated closing vertex',
 'grid':'square cells, explicit positive pitch; rectangle spans integer cell counts; max 10000 cells',
 'boundary':'half-open [umin,umax) x [vmin,vmax); floor to cell index; only points within 1e-12m of cell centers supported; all edges/noncenter/outside samples rejected',
 'cell_height':'maximum signed normal height of all supplied samples in a cell; duplicates/order do not change maximum',
 'coverage':'every footprint cell needs >=1 valid target sample AND every target pixel must be represented; no fill/interpolation',
 'height':'strictly positive finite heights only; no negative clipping; nonpositive total is failure, not zero substitute',
 'geometry_atol':GEOMETRY_ATOL,'grid_ratio_atol':GRID_RATIO_ATOL,'volume_check_atol_m3':VOLUME_ATOL_M3,'volume_check_rtol':0,
 'input':'float64 analytical camera-coordinate samples plus int64 source pixel map and synthetic FramePacket; not an SDK adapter',
}

def load_contract(root, tracked=None):
    global _CONTRACT
    from _boundary import load_contract as load_pinned_contract
    _CONTRACT = load_pinned_contract(root, tracked)
    return _CONTRACT

def analyze(frame,points_m,pixel_vu,synthetic_assumptions):
    c=_CONTRACT
    if c is None:raise RuntimeError('load_contract must be called explicitly first')
    result={'schema_version':'1.0.0','frame_id':frame.metadata['frame_id'],
      'status':'failure','stage':'volume','point_cloud':None,'volume_m3':None,'volume_method':None,
      'assumptions':['development-only synthetic rectangle/grid policy; not team approved'],
      'valid_depth_ratio':float(frame.valid_mask.mean()),'provenance_kind':frame.metadata['provenance']['kind'],
      'config_version':POLICY['policy_id'],'errors':[],'warnings':['Ideal synthetic height integration; no camera/physical/weight validation.']}
    diagnostic={}
    def require(condition,code,message):
        if not condition:c.fail(code,message)
    try:
        require(frame.metadata['provenance']['kind']=='synthetic' and frame.metadata['capture_source']=='synthetic',
                'PROVENANCE_INVALID','this development calculator refuses real data')
        c.volume_preflight(frame)
        require(isinstance(synthetic_assumptions,dict) and set(synthetic_assumptions)==set(ASSUMPTIONS)
            and all(synthetic_assumptions[k] is True for k in ASSUMPTIONS),
            'VOLUME_ASSUMPTION_REQUIRED','explicit synthetic footprint/full-top/solid/no-overhang assumptions required')
        request=frame.metadata['volume_request'];plane=frame.metadata['support_plane'];basis=request['plane_basis']
        n=np.array(plane['normal'],dtype=np.float64);origin=np.array(basis['origin_m'],dtype=np.float64)
        a=np.array(basis['u_axis'],dtype=np.float64);b=np.array(basis['v_axis'],dtype=np.float64)
        require(abs(np.linalg.norm(n)-1)<=GEOMETRY_ATOL,'PLANE_INVALID','normal must be unit within fixed float64 tolerance')
        require(abs(np.linalg.norm(a)-1)<=GEOMETRY_ATOL and abs(np.linalg.norm(b)-1)<=GEOMETRY_ATOL
          and abs(a@b)<=GEOMETRY_ATOL and np.allclose(np.cross(a,b),n,rtol=0,atol=GEOMETRY_ATOL)
          and abs(n@origin+plane['offset_m'])<=GEOMETRY_ATOL,
          'PLANE_BASIS_INVALID','orthonormal right-handed basis and origin on supplied plane required')
        polygon=np.array(request['footprint_polygon_uv_m'],dtype=np.float64)
        require(polygon.shape==(4,2),'CONFIG_INVALID','only a four-corner rectangular footprint is supported')
        lo=polygon.min(axis=0);hi=polygon.max(axis=0)
        canonical=np.array([[lo[0],lo[1]],[hi[0],lo[1]],[hi[0],hi[1]],[lo[0],hi[1]]])
        require(np.array_equal(polygon,canonical) and (hi>lo).all(),'CONFIG_INVALID','canonical CCW axis-aligned rectangle required; no polygon approximation')
        pitch=np.float64(request['grid_pitch_m']);ratio=(hi-lo)/pitch
        require(np.isfinite(ratio).all() and (ratio>=1).all() and (ratio<=10000).all(),'CONFIG_INVALID','unsupported grid extent')
        counts=np.rint(ratio).astype(np.int64)
        require(np.all(np.abs(ratio-counts)<=GRID_RATIO_ATOL) and int(counts[0])*int(counts[1])<=10000,
                'CONFIG_INVALID','footprint must have an integer number of full square cells; no partial-cell approximation')
        require(isinstance(points_m,np.ndarray) and points_m.dtype==np.float64 and points_m.ndim==2 and points_m.shape[1]==3
                and len(points_m)>0 and np.isfinite(points_m).all(),'INPUT_CORRUPT','nonempty finite float64 Nx3 samples required')
        require(isinstance(pixel_vu,np.ndarray) and pixel_vu.dtype==np.int64 and pixel_vu.shape==(len(points_m),2),
                'INPUT_CORRUPT','matching int64 Nx2 sample-to-source pixel map required')
        v,u=pixel_vu.T;h,w=frame.depth_m.shape
        require(((v>=0)&(v<h)&(u>=0)&(u<w)).all(),'TARGET_INVALID','sample pixel outside source frame')
        require((frame.target_mask[v,u]&frame.valid_mask[v,u]).all(),'COVERAGE_INSUFFICIENT','sample must map to valid target; never drop invalid samples')
        relative=points_m-origin
        uv=np.column_stack((relative@a,relative@b))
        heights=relative@n
        require(np.isfinite(uv).all() and np.isfinite(heights).all(),'RESULT_INVALID','nonfinite projection or height')
        require((heights>0).all(),'RESULT_INVALID','nonpositive height unsupported; no zero/negative clipping')
        require(((uv>=lo)&(uv<hi)).all(),'CONFIG_INVALID','sample outside half-open footprint; boundary/outside is not silently ignored')
        cell=np.floor((uv-lo)/pitch).astype(np.int64)
        centers=lo+(cell+.5)*pitch
        require(np.all(np.abs(uv-centers)<=GEOMETRY_ATOL),'CONFIG_INVALID','only synthetic cell-center samples supported; cell edges rejected')
        nu,nv=map(int,counts);total=nu*nv
        cell_ids=cell[:,1]*nu+cell[:,0]
        maxima=np.full(total,np.nan,dtype=np.float64);occupancy=np.zeros(total,dtype=np.int64)
        for index,height in zip(cell_ids,heights):
            maxima[index]=height if occupancy[index]==0 else max(maxima[index],height)
            occupancy[index]+=1
        source_ids=np.unique(v*w+u);target_ids=np.flatnonzero(frame.target_mask.ravel())
        represented=np.array_equal(source_ids,target_ids)
        missing=np.flatnonzero(occupancy==0)
        diagnostic.update(grid_shape_vu=[nv,nu],expected_cells=total,covered_cells=int(np.count_nonzero(occupancy)),
          missing_cell_indices_vu=[[int(i//nu),int(i%nu)] for i in missing],input_sample_count=len(points_m),
          unique_source_pixel_count=len(source_ids),all_target_pixels_represented=bool(represented),
          cell_sample_counts=occupancy.reshape(nv,nu).tolist(),cell_area_m2=float(pitch*pitch))
        require(len(missing)==0 and represented,'COVERAGE_INSUFFICIENT','missing footprint cells or source target pixels; no zero fill')
        area=float(pitch*pitch)
        volume=math.fsum(float(height)*area for height in maxima)
        require(math.isfinite(volume) and volume>0,'RESULT_INVALID','finite positive volume required; failed volume stays null')
        diagnostic.update(cell_heights_m=maxima.reshape(nv,nu).tolist(),footprint_area_m2=float(total*area),
                          integration='float64 plane projections and per-cell max; math.fsum(height * pitch^2)')
        result.update(status='success',volume_m3=volume,volume_method='height_integration_synthetic_rect_grid_max_v1',
                      assumptions=result['assumptions']+list(ASSUMPTIONS))
    except c.ContractError as error:
        result['errors']=[{'code':error.code,'message':str(error)}]
    except (ValueError,TypeError,KeyError,OverflowError) as error:
        result['errors']=[{'code':'INPUT_CORRUPT','message':str(error)}]
    c.validate_json(result,'processing')
    return {'artifact_type':'synthetic_height_integration_development_v1','analysis_status':
            'synthetic_volume_calculated' if result['status']=='success' else 'synthetic_volume_rejected',
            'processing_result':result,'diagnostics':diagnostic,'development_policy':POLICY,
            'team_approval':False,'physical_accuracy_verified':False,**FLAGS}
