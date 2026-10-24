"""ADE-95 data/state/export layer; contract loading and coordinates stay upstream."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np

from contract import ContractError, FramePacket, fail, iter_frames, point_cloud_camera, validate_frame, validate_json
from session_boundary import guard_read


@dataclass
class FrameView:
    frame: FramePacket
    points_m: np.ndarray
    display_points_m: np.ndarray

    @property
    def valid_ratio(self):
        return float(np.count_nonzero(self.frame.valid_mask) / self.frame.valid_mask.size)


def read_session(session):
    """Supplement missing manifest type/relative-path guards, then use the original iterator."""
    try:
        guard_read(session)
        manifest = (session / 'frames.jsonl').read_text(encoding='utf-8')
        for line in manifest.splitlines():
            if not line.strip():
                continue
            def reject_constant(value):
                fail('MANIFEST_INVALID', f'JSON constant is forbidden: {value}')
            entry = json.loads(line, parse_constant=reject_constant)
            if (not isinstance(entry, dict) or set(entry) != {'frame_id','metadata_path'}
                    or not isinstance(entry['frame_id'], str) or not entry['frame_id']
                    or not isinstance(entry['metadata_path'], str) or not entry['metadata_path']):
                fail('MANIFEST_INVALID', 'frame_id and metadata_path must be nonempty strings')
            path = Path(entry['metadata_path'])
            if path.is_absolute() or path.drive or path.root:
                fail('PATH_INVALID', 'metadata_path must be session-relative')
        frames = list(iter_frames(session))
    except ContractError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile, EOFError) as error:
        fail('INPUT_CORRUPT', f'{type(error).__name__}: {error}')
    if not frames:
        fail('MANIFEST_INVALID', 'frames.jsonl contains no frames')
    return frames


class ViewerSession:
    """Validate the complete session on open/move; a failed move invalidates current output."""
    def __init__(self, session, max_display_points=50000):
        if type(max_display_points) is not int or max_display_points < 1:
            raise ValueError('max_display_points must be positive')
        self.session = Path(session).resolve()
        self.max_display_points = max_display_points
        frames = read_session(self.session)
        self.frame_ids = [f.metadata['frame_id'] for f in frames]
        self.index = 0
        self.current = self._view(frames[0])

    def _view(self, frame):
        points = point_cloud_camera(frame)
        if len(points) > self.max_display_points:
            indices = np.linspace(0, len(points)-1, self.max_display_points, dtype=np.int64)
            display = points[indices].copy()
        else:
            display = points.copy()
        return FrameView(frame, points, display)

    def select(self, index):
        self.index = max(0, min(int(index), len(self.frame_ids)-1))
        self.current = None
        frames = read_session(self.session)
        if [f.metadata['frame_id'] for f in frames] != self.frame_ids:
            fail('MANIFEST_INVALID', 'session frame IDs/order changed; reopen the viewer')
        self.current = self._view(frames[self.index])
        return self.current


def depth_preview(frame):
    validate_frame(frame)
    values = frame.depth_m[frame.valid_mask]
    lower, upper = float(values.min()), float(values.max())
    if lower == upper:
        margin = max(abs(lower)*.01, 1e-6)
        lower, upper = max(0.0, lower-margin), upper+margin
    return np.ma.array(frame.depth_m.copy(), mask=~frame.valid_mask.copy()), (lower, upper)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_frame(view, session, destination):
    """Exclusive new bundle directory: preview, FULL points, schema result, separate audit."""
    if view is None:
        fail('RESULT_INVALID', 'no validated current frame to save')
    destination = Path(destination).resolve()
    session = Path(session).resolve()
    if destination.is_relative_to(session) or destination.exists():
        fail('PATH_INVALID', 'output must be a NEW directory outside the input session')
    validate_frame(view.frame)
    # Use the full reference computation even if a caller modified display data.
    points = point_cloud_camera(view.frame)
    created = []
    owns_directory = False
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            destination.mkdir()
        except FileExistsError:
            fail('PATH_INVALID', 'output already exists')
        owns_directory = True
        cloud_path = destination / 'points.npz'
        with cloud_path.open('xb') as stream:
            created.append(cloud_path)
            np.savez(stream, points_m=points)
        result = {
            'schema_version':'1.0.0', 'frame_id':view.frame.metadata['frame_id'],
            'status':'success', 'stage':'point_cloud',
            'point_cloud':{'file':'points.npz', 'key':'points_m', 'sha256':sha256(cloud_path),
                           'unit':'m', 'frame':'camera', 'point_count':len(points)},
            'volume_m3':None, 'volume_method':None, 'assumptions':[],
            'valid_depth_ratio':view.valid_ratio, 'provenance_kind':view.frame.metadata['provenance']['kind'],
            'config_version':'ade95-viewer-v1', 'errors':[],
            'warnings':['Volume and weight have not been computed.'],
        }
        validate_json(result, 'processing')
        from viewer_render import render_preview
        preview = destination / 'preview.png'
        with preview.open('xb') as stream:
            created.append(preview)
            render_preview(view, stream)
        record = {'tool_version':'ade95-viewer-v1', 'input_session':str(session),
                  'input_metadata':view.frame.metadata,
                  'display_point_count':len(view.display_points_m), 'full_point_count':len(points),
                  'display_sampling':'evenly spaced row-order indices; export is full cloud',
                  'depth_range_m':list(depth_preview(view.frame)[1]),
                  'preview':'preview.png', 'output_sha256':{}}
        processing = destination / 'processing.json'
        with processing.open('x', encoding='utf-8') as stream:
            created.append(processing)
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
        record['output_sha256'] = {p.name:sha256(p) for p in created}
        audit = destination / 'viewer_export.json'
        with audit.open('x', encoding='utf-8') as stream:
            created.append(audit)
            json.dump(record, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
    except Exception as error:
        # Only our exclusively created files are removed; never recursive-delete user paths.
        for path in reversed(created):
            path.unlink(missing_ok=True)
        if owns_directory:
            destination.rmdir()
        if isinstance(error, ContractError):
            raise
        if isinstance(error, OSError):
            fail('RESULT_INVALID', f'export failed: {error}')
        raise
    return destination
