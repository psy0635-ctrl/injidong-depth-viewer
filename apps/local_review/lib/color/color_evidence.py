"""Fail closed on missing recorded depth-grid pairing. No new alignment is done."""
import numpy as np

def validate_color_record(metadata, calibration, row):
    m,c,r=metadata,calibration,row
    def require(ok,message):
        if not ok:raise ValueError(message)
    require(r['frame_id']==m['frame_id'] and r['session_id']==m['session_id'],'RGB frame/session mismatch')
    require(r['image_kind']=='aligned_rgb' and r['aligned_to_depth'] is True and r['alignment_method']=='pyrealsense2.align(stream.depth)',
            'Requires recorded SDK color-to-Depth alignment; no resize or original-RGB fallback')
    require(r['calibration_id']==m['intrinsics']['calibration_id'],'calibration ID mismatch')
    require(r['encoding']=='RGB8' and (r['height'],r['width'])==(m['depth']['height'],m['depth']['width']),'RGB grid mismatch')
    require(m['depth']['unit']=='m' and m['depth']['semantics']=='optical_axis_z' and m['intrinsics']['model']=='rectified_pinhole','unsupported saved Depth geometry')
    require(all(m['intrinsics'][a]==c['depth'][b] for a,b in [('width','width'),('height','height'),('fx','fx'),('fy','fy'),('cx','ppx'),('cy','ppy')]),'Depth calibration values differ')
    require(c['depth_scale_to_m']==m['provenance']['raw_scale_to_m'],'recorded raw scale differs')
    require(c['depth']['distortion']=='distortion.brown_conrady' and c['depth']['coeffs']==[0]*5,
            'This native-grid adapter requires the current zero-coefficient source profile; do not infer undocumented rectification')
    require(np.asarray(c['depth_to_color']['rotation']).shape==(9,) and np.asarray(c['depth_to_color']['translation_m']).shape==(3,),'missing recorded extrinsics')
    require(r['pair_status']=='verified' and isinstance(r['pair_evidence'],str) and bool(r['pair_evidence']),'no recorded frameset pairing')
    require(r['time']['clock_domain']==m['capture_time']['clock_domain'] and r['time']['origin']==m['capture_time']['origin']=='sensor','cross-clock pairing is not inferred')
    times=[r['time']['ns'],m['capture_time']['ns']]
    require(all(isinstance(t,str) and t.isdecimal() for t in times),'sensor ns must be decimal strings')
    delta=abs(int(times[0])-int(times[1]))
    require(delta<=10_000_000,'exceeds this recorded frameset criterion of10ms')
    return {'grid':'depth','delta_ns':str(delta),'depth_reprojection_applied':False,'RGB_alignment_applied_now':False,
            'status':'conditional_saved_RGB_association','alignment_accuracy_independently_verified':False}
