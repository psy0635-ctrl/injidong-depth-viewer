"""Static PNGs from an existing comparison NPZ; never recomputes a cloud."""
import argparse,hashlib,json,os,sys,traceback
from pathlib import Path
from datetime import datetime,timezone,timedelta
import numpy as np
from PIL import Image
from _common import (require as need, file_record as record, write_json_new, TrackedReads,
    reserve_output, select_metadata, read_depth, raw_source, FLAGS)
NOTICE='저장 배열·기록된 내참수 기준 / 보정·물리 정확도 미검증'
KST=timezone(timedelta(hours=9))

def render(output, frame_id, depth, valid, points, pixels, rawpixels, sentinelrows, side, rawpath, npz, max_display_points, font_family, audit):
    os.environ['MPLCONFIGDIR']=str(output/'.matplotlib_cache')
    os.environ['MPLBACKEND']='Agg'
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt, colors, font_manager
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    font=font_manager.findfont(font_manager.FontProperties(family=font_family),fallback_to_default=False)
    plt.rcParams.update({'font.family':font_family,'axes.unicode_minus':False,'font.size':11,'axes.titlesize':13,'axes.labelsize':12,'figure.titlesize':18,'savefig.facecolor':'white'})
    audit['environment'].update(matplotlib=matplotlib.__version__,backend=matplotlib.get_backend(),font_path=font)
    W=output
    stride=side['raw_stride_bytes']
    def finish_figure(fig,name):
        fig.text(.5,.025,NOTICE,ha='center',fontsize=12,color='#9c2d29')
        path=output/name
        need(not path.exists(),'PNG already exists')
        with path.open('xb') as stream:
            fig.savefig(stream,format='png',dpi=160,facecolor='white',metadata={'Description':NOTICE,'Software':'Matplotlib Agg; stored data visualization only'})
        plt.close(fig)
        return path
    maskdepth=np.ma.array(depth,mask=~valid)
    vals=depth[valid]; fullmin,fullmax=float(vals.min()),float(vals.max())
    auxmax=float(np.percentile(vals.astype(np.float64),98))
    if fullmax==fullmin:fullmax=fullmin+max(abs(fullmin)*.01,1e-6)
    if auxmax==fullmin:auxmax=fullmax
    cmap=plt.get_cmap('viridis').copy(); cmap.set_bad('#ced4dc')
    height,width=depth.shape
    extent=(-.5,width-.5,height-.5,-.5)
    def depth_panel(ax,lo,hi,title):
        im=ax.imshow(maskdepth,cmap=cmap,norm=colors.Normalize(lo,hi),origin='upper',extent=extent,interpolation='nearest')
        ax.set(xlabel='u · 가로 픽셀',ylabel='v · 세로 픽셀 (아래 증가)',title=title,xlim=(-.5,width-.5),ylim=(height-.5,-.5))
        ax.set_aspect('equal'); ax.set_xticks(np.unique(np.linspace(0,width-1,5,dtype=int))); ax.set_yticks(np.unique(np.linspace(0,height-1,5,dtype=int)))
        ax.grid(False)
        return im
    fig,axs=plt.subplots(1,2,figsize=(14,6.6))
    fig.subplots_adjust(left=.06,right=.95,bottom=.16,top=.79,wspace=.3)
    fig.suptitle(f'저장 Depth · {frame_id}',y=.96)
    fig.text(.5,.885,f'원본 {width} × {height} | valid {len(points):,} / invalid {int((~valid).sum()):,} | 회색 = invalid',ha='center',fontsize=11)
    im=depth_panel(axs[0],fullmin,fullmax,f'기본 · 유효값 전체 범위\n[{fullmin:.6f}, {fullmax:.6f}] m')
    fig.colorbar(im,ax=axs[0],fraction=.045,pad=.025,label='저장 깊이 (m)')
    im2=depth_panel(axs[1],fullmin,auxmax,f'보조 · 98백분위까지 색상 표시\n[{fullmin:.6f}, {auxmax:.6f}] m')
    fig.colorbar(im2,ax=axs[1],fraction=.045,pad=.025,label='저장 깊이 (m) · 상한 초과 색상 포화')
    fig.text(.5,.095,'보조 표시의 색상 포화는 원본 배열의 클리핑·제거가 아닙니다.',ha='center',fontsize=11)
    path=finish_figure(fig,'depth.png')
    audit['images'][path.name]={'path':str(path),'full_valid_color_range_m':[fullmin,fullmax],'auxiliary_color_range_m':[fullmin,auxmax],'auxiliary_rule':'upper color limit = 98th percentile of valid stored depth; visual saturation only','original_arrays_modified':False,'invalid_color':'#ced4dc','pixel_extent':list(extent)}
    fig,ax=plt.subplots(figsize=(11,8.7))
    fig.subplots_adjust(left=.1,right=.88,bottom=.18,top=.82)
    fig.suptitle('raw 65535 위치 · 의미 미확정',y=.965)
    fig.text(.5,.90,f'{frame_id} | raw == 65535: {len(rawpixels)}픽셀 | 해당 valid_mask=true: {len(rawpixels)}픽셀',ha='center',fontsize=12)
    im=depth_panel(ax,fullmin,fullmax,'전체 유효 깊이 범위 위에 raw의 동일 인덱스 위치 표시')
    fig.colorbar(im,ax=ax,fraction=.045,pad=.035,label='저장 깊이 (m)')
    ax.scatter(rawpixels[:,1],rawpixels[:,0],s=27,facecolors='none',edgecolors='white',linewidths=2.5,zorder=4)
    ax.scatter(rawpixels[:,1],rawpixels[:,0],s=27,facecolors='none',edgecolors='#e5007d',linewidths=1.35,zorder=5)
    handles=[Line2D([],[],marker='o',linestyle='none',markerfacecolor='none',markeredgecolor='#e5007d',label=f'raw 65535 · {len(rawpixels)}개 전부 표시',markersize=8),Patch(facecolor='#ced4dc',label='invalid 영역')]
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.49,.09),ncol=2,frameon=False)
    fig.text(.5,.065,'정상 거리·오류 판정 아님 | 인접 표시 기호는 겹칠 수 있음',ha='center',fontsize=10)
    path=finish_figure(fig,'raw65535_locations.png')
    audit['images'][path.name]={'path':str(path),'raw_65535_pixels':len(rawpixels),'valid_true_count':len(rawpixels),'marker':'magenta hollow circles with white outline; all pixels; overlap possible','raw_interpretation':{'path':str(rawpath),'dtype':'<u2','shape':[height,width],'stride_bytes':stride,'byte_order_source':side['raw_byte_order_source']},'full_valid_color_range_m':[fullmin,fullmax]}
    # Deterministic stored row subsample; force all 119 sentinel rows into displayed data.
    base=np.linspace(0,len(points)-1,min(max_display_points,len(points)),dtype=np.int64)
    shown=np.union1d(base,sentinelrows)
    normalrows=np.setdiff1d(shown,sentinelrows,assume_unique=True)
    need(np.isin(sentinelrows,shown).all(),'sentinel row missing from display')
    bounds=np.stack((points.min(axis=0),points.max(axis=0))).astype(np.float64)
    spans=bounds[1]-bounds[0]; pad=np.maximum(spans*.05,.001)
    limits=np.stack((bounds[0]-pad,bounds[1]+pad))
    fig=plt.figure(figsize=(12,10.5)); ax=fig.add_subplot(111,projection='3d')
    fig.subplots_adjust(left=.035,right=.82,bottom=.16,top=.86)
    fig.suptitle(f'저장 Point Cloud · {frame_id}',y=.97)
    fig.text(.5,.915,f'전체 {len(points):,}점 | 표시 {len(shown):,}점 | raw 65535 대응 {len(sentinelrows)}점 전부 표시',ha='center',fontsize=12)
    # Display layout only: horizontal X, depth Z, vertical Y increasing downward.
    p=points[normalrows]; sc=ax.scatter(p[:,0],p[:,2],p[:,1],c=p[:,2],cmap='viridis',vmin=fullmin,vmax=fullmax,s=1.3,alpha=.62,linewidths=0,depthshade=False)
    q=points[sentinelrows]; ax.scatter(q[:,0],q[:,2],q[:,1],c='#e5007d',s=19,edgecolors='white',linewidths=.3,depthshade=False,label=f'raw 65535 대응 · {len(sentinelrows)}점')
    ax.set_xlabel('X · 오른쪽 (m)',labelpad=10); ax.set_ylabel('Z · 전방 (m)',labelpad=10); ax.set_zlabel('Y · 아래 (m)',labelpad=10)
    ax.set_xlim(*limits[:,0]); ax.set_ylim(*limits[:,2]); ax.set_zlim(limits[1,1],limits[0,1])
    ax.set_box_aspect((limits[1]-limits[0])[[0,2,1]])
    ax.set_proj_type('ortho'); ax.view_init(elev=18,azim=-68,roll=0)
    ax.tick_params(labelsize=9)
    cax=fig.add_axes([.87,.29,.018,.42]); fig.colorbar(sc,cax=cax,label='저장 Z (m) · RGB 색상 아님')
    fig.legend(handles=[Line2D([],[],marker='o',linestyle='none',markerfacecolor='#e5007d',markeredgecolor='white',markersize=8,label='raw 65535 대응 · 의미 미확정')],loc='lower center',bbox_to_anchor=(.5,.105),frameon=False)
    fig.text(.5,.075,'표시 축 배치: 수평 X / 깊이 Z / 수직 Y(아래 증가) · 정사영 · 축 1 m 동일 축척',ha='center',fontsize=10)
    fig.text(.5,.052,'기존 저장 points_m 사용 · 결정적 행 샘플 · RGB 정렬·world 변환 없음',ha='center',fontsize=10)
    path=finish_figure(fig,'pointcloud.png')
    audit['images'][path.name]={'path':str(path),'source_points':str(npz),'total_point_count':len(points),'displayed_point_count':len(shown),'ordinary_displayed_count':len(normalrows),'raw_65535_displayed_count':len(sentinelrows),'sampling':f'union1d(linspace(0,N-1,min({max_display_points},N),dtype=int64), all raw-corresponding point rows); sorted unique; no random sampling','source_coordinate_bbox_xyz_m':bounds.tolist(),'axis_limits_xyz_m':{'X':limits[:,0].tolist(),'Y':limits[:,1].tolist(),'Z':limits[:,2].tolist()},'display_axes':'matplotlib (horizontal X, depth Z, vertical Y); vertical Y inverted only for display','projection':'orthographic','view_degrees':{'elevation':18,'azimuth':-68,'roll':0},'equal_metric_scale':True,'box_aspect_display_XZY':(limits[1]-limits[0])[[0,2,1]].tolist(),'color':'stored Z only; not RGB','occlusion_notice':'3D projection overlaps and subsampling can hide shape details; markers for all raw-corresponding rows are submitted'}
    audit['existing_arrays']={'points_m':{'dtype':str(points.dtype),'shape':list(points.shape)},'pixel_vu':{'dtype':str(pixels.dtype),'shape':list(pixels.shape),'columns':['v','u'],'unique_valid_row_major':True},'depth_m':{'dtype':str(depth.dtype),'shape':list(depth.shape)},'valid_mask':{'dtype':str(valid.dtype),'shape':list(valid.shape)}}
    audit['frame_id']=frame_id; audit['png_checks']={}
    for name,info in audit['images'].items():
        p=Path(info['path'])
        with Image.open(p) as img: img.verify()
        with Image.open(p) as img:
            img.load(); rgb=np.asarray(img.convert('RGB'))
            nonwhite=int(np.count_nonzero(np.any(rgb<245,axis=2)))
            need(img.format=='PNG' and img.width>=1000 and img.height>=900 and nonwhite>10000,'corrupt/small/empty PNG')
            audit['png_checks'][name]={'format':'PNG','size_pixels':list(img.size),'mode':img.mode,'nonwhite_pixels':nonwhite,'channel_std':rgb.std(axis=(0,1)).tolist(),'decode_ok':True,**record(p)}

def run(args):
    session=Path(args.session).resolve();npz=Path(args.pointcloud).resolve();report_path=Path(args.comparison_report).resolve()
    tracked=TrackedReads();prior=tracked.json(report_path)
    need(prior['analysis_status']=='stored_array_pointcloud_comparison_passed' and prior['frame_id']==args.frame_id, 'comparison report failed or wrong frame')
    need(Path(prior['session']).resolve()==session, 'comparison report session differs from explicit session')
    output=reserve_output(args.output,[session,Path(prior['baseline']),npz.parent,report_path.parent])
    audit={'artifact_type':'stored_depth_static_visualization_v1','visualization_status':'failed','frame_id':args.frame_id,
      'started_at_kst':datetime.now(KST).isoformat(),'argv':sys.argv,'environment':{'python':sys.version,'executable':sys.executable,'numpy':np.__version__,'pillow':Image.__version__},
      'pointcloud_recomputed':False,'remapping_performed':False,**FLAGS,'errors':[],'images':{}}
    try:
        # Bind the exact output bytes and corresponding metadata/depth/raw files; no XYZ recomputation.
        tracked.read(npz)
        need(record(npz)['sha256']==prior['saved_analysis_npz']['sha256'], 'saved pointcloud hash differs from comparison report')
        for name,expected in prior['files_before'].items():
            path=Path(name)
            if path.is_relative_to(session):
                tracked.read(path);need(record(path)==expected,'session input differs from comparison report')
        mp,entry,m=select_metadata(session,args.frame_id,tracked)
        depth,valid=read_depth(mp,m,tracked)
        with np.load(npz,allow_pickle=False) as a:
            need(set(a.files)=={'points_m','pixel_vu'},'unexpected pointcloud NPZ keys')
            points,pixels=a['points_m'],a['pixel_vu']
        count=prior['comparison']['point_count'];h,w=depth.shape
        need(points.dtype==np.float32 and points.shape==(count,3) and np.isfinite(points).all(),'saved cloud dtype/shape/finite mismatch')
        need(pixels.dtype==np.int64 and pixels.shape==(count,2) and int(valid.sum())==count,'saved pixels dtype/shape/count mismatch')
        v,u=pixels.T
        need(((v>=0)&(v<h)&(u>=0)&(u<w)).all() and valid[v,u].all() and (np.diff(v*w+u)>0).all(),'saved pixel map is not unique valid row-major')
        raw,side,rawpath=raw_source(session,mp,m,tracked)
        rawpixels=np.argwhere(raw==65535).astype(np.int64)
        pairs=prior['raw_65535_preservation']['correspondences']
        expected_pixels=np.array([[c['v'],c['u']] for c in pairs],dtype=np.int64).reshape(-1,2)
        sentinelrows=np.array([c['point_row'] for c in pairs],dtype=np.int64)
        need(np.array_equal(rawpixels,expected_pixels) and valid[rawpixels[:,0],rawpixels[:,1]].all(), 'raw 65535 pixels/valid state differ from report')
        need(((sentinelrows>=0)&(sentinelrows<count)).all() and np.array_equal(pixels[sentinelrows],rawpixels),'raw 65535 point rows differ')
        render(output,args.frame_id,depth,valid,points,pixels,rawpixels,sentinelrows,side,rawpath,npz,args.max_display_points,args.font_family,audit)
    except Exception as error:
        audit['errors'].append({'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()})
    finally:
        try:audit.update(tracked.finish())
        except Exception as error:audit['errors'].append({'type':type(error).__name__,'message':str(error)})
        audit['finished_at_kst']=datetime.now(KST).isoformat()
    if not audit['errors']:audit['visualization_status']='static_visualization_generated'
    write_json_new(output/'visualization_results.json',audit)
    print(json.dumps({'status':audit['visualization_status'],'report':str(output/'visualization_results.json'),'errors':audit['errors']},ensure_ascii=False))
    return 0 if not audit['errors'] else 1

def positive(value):
    count=int(value)
    if count<1:raise argparse.ArgumentTypeError('positive count required')
    return count

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('session','pointcloud','comparison-report','output'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--frame-id',required=True)
    parser.add_argument('--max-display-points',type=positive,default=50000)
    parser.add_argument('--font-family',default='Malgun Gothic',help='installed font with Korean glyphs; no download/fallback')
    args=parser.parse_args()
    try:return run(args)
    except Exception:
        traceback.print_exc();return 1
if __name__=='__main__':raise SystemExit(main())
