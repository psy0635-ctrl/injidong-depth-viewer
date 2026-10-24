"""Read-only 2026-10-13 RGB/annotation boundary checks; no IMU logger/trainer.

Field inventory follows the final document. Package 0.2.0 enum compatibility
remains to be checked on receipt; these guards do not certify physical alignment.
"""
import copy
import json
from pathlib import Path

import numpy as np

from contract import FramePacket, _schema_check, _timestamp, fail, validate_frame, ROOT
from depth_preflight import check_hash, digest
from session_pipeline import relative_file

IMAGE_FIELDS = set('frame_id session_id file sha256 width height encoding image_kind time pair_status pair_evidence aligned_to_depth alignment_method calibration_id provenance_kind'.split())
ANNOTATION_FIELDS = set('schema_version session_id frame_id specimen_id mask_file mask_key sha256 width height class_name source version purpose provenance_kind'.split())


def rows(path):
    if not path.exists():
        return []
    def reject(value):
        fail('INPUT_CORRUPT', f'nonfinite JSON token: {value}')
    return [json.loads(line, parse_constant=reject) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def frame_for(row, frames, fields):
    if not isinstance(row, dict) or set(row) != fields:
        fail('AUXILIARY_INVALID', 'missing/extra auxiliary fields')
    if any(not isinstance(row[k], str) or not row[k].strip() for k in ('session_id', 'frame_id')):
        fail('FRAME_MAPPING_INVALID', 'nonempty string session/frame IDs required')
    key = (row['session_id'], row['frame_id'])
    if key not in frames:
        fail('FRAME_MAPPING_INVALID', 'auxiliary session/frame not found')
    frame = frames[key]
    if row['provenance_kind'] != frame.metadata['provenance']['kind']:
        fail('PROVENANCE_INVALID', 'auxiliary real/synthetic mismatch')
    if type(row['width']) is not int or type(row['height']) is not int or min(row['width'], row['height']) <= 0:
        fail('AUXILIARY_INVALID', 'positive integer dimensions required')
    return frame


def check_auxiliary(session, frame_list):
    session = Path(session)
    frames = {(f.metadata['session_id'], f.metadata['frame_id']): f for f in frame_list}
    report = {'images': [], 'annotations': [], 'physical_alignment_verified': False}
    seen = set()
    stamp_schema = json.loads((ROOT / 'schemas/frame.schema.json').read_text(encoding='utf-8'))
    for row in rows(relative_file(session, 'images.jsonl')):
        frame = frame_for(row, frames, IMAGE_FIELDS)
        path = relative_file(session, row['file'])
        if row['file'] in seen:
            fail('AUXILIARY_INVALID', 'duplicate image file')
        seen.add(row['file'])
        check_hash(digest(path), row['sha256'], 'image')
        if row['encoding'] != 'RGB8' or row['image_kind'] not in ('aligned_rgb', 'depth_preview', 'original_rgb'):
            fail('AUXILIARY_INVALID', 'RGB8 and documented image kind required')
        from PIL import Image
        with Image.open(path) as image:
            pixels = np.asarray(image)
            if image.format != 'PNG' or image.mode != 'RGB' or pixels.dtype != np.uint8 or pixels.shape != (row['height'], row['width'], 3):
                fail('AUXILIARY_INVALID', 'decoded RGB PNG HxWx3 uint8 required')
        _schema_check(row['time'], stamp_schema['$defs']['stamp'], stamp_schema)
        _timestamp(row['time'])
        if type(row['aligned_to_depth']) is not bool or not isinstance(row['pair_status'], str) or not row['pair_status']:
            fail('AUXILIARY_INVALID', 'alignment bool and explicit pair status required')
        if row['pair_status'] == 'verified':
            if (not isinstance(row['pair_evidence'], str) or not row['pair_evidence'].strip()
                    or row['time']['ns'] is None or frame.metadata['capture_time']['ns'] is None):
                fail('EVIDENCE_REQUIRED', 'verified pairing requires original times and descriptive evidence')
        if row['aligned_to_depth']:
            if ((row['height'], row['width']) != frame.depth_m.shape
                    or not isinstance(row['alignment_method'], str) or not row['alignment_method'].strip()
                    or row['alignment_method'].lower() in ('resize', 'resized', 'stretch')
                    or row['calibration_id'] != frame.metadata['intrinsics']['calibration_id']):
                fail('ALIGNMENT_UNCONFIRMED', 'dimensions alone do not establish depth alignment')
        elif row['alignment_method'] is not None or row['calibration_id'] is not None:
            fail('ALIGNMENT_UNCONFIRMED', 'unconfirmed alignment must keep null evidence')
        if row['image_kind'] in ('aligned_rgb', 'depth_preview') and not row['aligned_to_depth']:
            fail('ALIGNMENT_UNCONFIRMED', 'depth-coordinate image requires alignment record')
        report['images'].append({'file': row['file'], 'frame_id': row['frame_id'],
                                 'usable_for_depth_label_review': row['aligned_to_depth'] and row['pair_status'] == 'verified'})
    seen, identities = set(), set()
    for row in rows(relative_file(session, 'annotations.jsonl')):
        frame = frame_for(row, frames, ANNOTATION_FIELDS)
        if (row['schema_version'] != '1.0.0' or row['specimen_id'] != frame.metadata['specimen_id']
                or row['mask_key'] != 'target_mask' or row['class_name'] != 'clay'
                or row['purpose'] not in ('manual_ground_truth', 'model_output')
                or not isinstance(row['source'], str) or not row['source'].strip()
                or not isinstance(row['version'], str) or not row['version'].strip()):
            fail('TARGET_INVALID', 'annotation identity/class/source/version/purpose invalid')
        if row['mask_file'] in seen:
            fail('TARGET_INVALID', 'manual/model outputs must use separate files')
        seen.add(row['mask_file'])
        identity = (row['session_id'], row['frame_id'], row['purpose'], row['version'])
        if identity in identities:
            fail('TARGET_INVALID', 'ambiguous duplicate annotation frame/purpose/version')
        identities.add(identity)
        path = relative_file(session, row['mask_file'])
        check_hash(digest(path), row['sha256'], 'annotation mask')
        with np.load(path, allow_pickle=False) as arrays:
            if arrays.files != ['target_mask']:
                fail('TARGET_INVALID', 'annotation NPZ key must be target_mask only')
            target = arrays['target_mask'].copy()
        if target.dtype != np.bool_ or target.shape != frame.depth_m.shape or target.shape != (row['height'], row['width']):
            fail('TARGET_INVALID', 'depth-coordinate HxW bool mask required')
        if frame.metadata['target_mask_info'] == {'source': row['source'], 'version': row['version']}:
            if frame.target_mask is None or not np.array_equal(target, frame.target_mask):
                fail('TARGET_INVALID', 'annotation matching core target source/version has different full mask')
        report['annotations'].append({'frame_id': row['frame_id'], 'mask_file': row['mask_file'],
                                      'purpose': row['purpose'], 'version': row['version'],
                                      'target_missing_depth_count': int(np.count_nonzero(target & ~frame.valid_mask))})
    report['rgb_status'] = 'not_collected' if not report['images'] else 'file_records_checked'
    return report


def attach_target(frame, target_mask, source, version, *, receipt=None, evidence_base=None):
    """After external depth alignment verification; retain ALL target pixels incl. missing depth."""
    validate_frame(frame)
    if any(not isinstance(value, str) or not value.strip() for value in (source, version)):
        fail('TARGET_INVALID', 'nonempty target source/version required')
    if frame.metadata['provenance']['kind'] == 'real' and receipt is None:
        fail('EVIDENCE_REQUIRED', 'real mask attachment requires a frame-bound target receipt')
    if receipt is not None:
        if evidence_base is None:
            fail('EVIDENCE_REQUIRED', 'target receipt base required')
        for key in ('frame_id', 'session_id', 'specimen_id'):
            if key not in receipt or receipt[key] != frame.metadata[key]:
                fail('TARGET_INVALID', f'target receipt {key} differs from packet')
        if receipt.get('source') != source or receipt.get('version') != version:
            fail('TARGET_INVALID', 'target receipt source/version differs')
        base = Path(evidence_base)
        path = relative_file(base, receipt['file'])
        check_hash(digest(path), receipt['sha256'], 'attached target')
        with np.load(path, allow_pickle=False) as arrays:
            if arrays.files != ['target_mask'] or arrays['target_mask'].dtype != target_mask.dtype or not np.array_equal(arrays['target_mask'], target_mask):
                fail('TARGET_INVALID', 'target receipt array differs')
        alignment = receipt['depth_alignment_evidence']
        check_hash(digest(relative_file(base, alignment['file'])), alignment['sha256'], 'target depth alignment')
    metadata = copy.deepcopy(frame.metadata)
    metadata['storage']['target_mask_key'] = 'target_mask'
    metadata['target_mask_info'] = {'source': source, 'version': version}
    result = FramePacket(metadata, frame.depth_m.copy(), frame.valid_mask.copy(), target_mask.copy())
    if hasattr(frame, '_ade71_metadata_path'):
        result._ade71_metadata_path = frame._ade71_metadata_path
    return validate_frame(result)
