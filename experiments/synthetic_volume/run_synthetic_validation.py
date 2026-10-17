"""Generate, persist and validate eight synthetic-only height-integration cases."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import copy
import json
import platform
import sys
import traceback
import numpy as np
import synthetic_volume as tool
from synthetic_fixtures import cuboid
from _boundary import TrackedReads, reserve_output, newjson, record, require, import_paths

ROOT = Path(__file__).resolve().parent
UNITS = {'distance': 'm', 'area': 'm^2', 'volume': 'm^3'}
TOLERANCE = {'volume_atol_m3': 1e-15, 'volume_rtol': 0,
             'geometry_atol': 1e-12, 'grid_ratio_atol': 1e-10,
             'automatic_widening': False,
             'reason': 'Unchanged float64 projection/max and math.fsum; six 0.01m square cells, 1m plane offset and 0.01m height; tolerance exceeds rounding but is far below a missing cell (1e-6m3).'}

def cases(contract):
    # Independent oracle is a product of dimensions, never an integration output.
    expected = .02 * .03 * .01
    base = cuboid(contract)
    values = {'A_known_cuboid': (copy.deepcopy(base), 'success', expected, None)}
    f, p, x, a = copy.deepcopy(base)
    order = np.array([5, 1, 0, 4, 2, 3, 0, 0, 5, 4, 2], dtype=np.int64)
    values['B_duplicates_reordered'] = ((f, p[order], x[order], a), 'success', expected, None)
    f, p, x, a = copy.deepcopy(base)
    values['C_missing_cell'] = ((f, p[1:], x[1:], a), 'failure', None, 'COVERAGE_INSUFFICIENT')
    f, p, x, a = copy.deepcopy(base)
    f.depth_m[0, 0] = 0; f.valid_mask[0, 0] = False
    values['C_invalid_target'] = ((f, p, x, a), 'failure', None, 'COVERAGE_INSUFFICIENT')
    f, p, x, a = copy.deepcopy(base)
    f.metadata['support_plane']['normal'] = [0., 0., -2.]
    values['D_bad_plane'] = ((f, p, x, a), 'failure', None, 'PLANE_INVALID')
    f, p, x, a = copy.deepcopy(base)
    f.metadata['volume_request']['plane_basis']['v_axis'] = [0., 1., 0.]
    values['D_bad_basis'] = ((f, p, x, a), 'failure', None, 'PLANE_BASIS_INVALID')
    f, p, x, a = copy.deepcopy(base)
    f.metadata['volume_request']['assumptions_confirmed'] = False
    values['D_unconfirmed'] = ((f, p, x, a), 'failure', None, 'VOLUME_ASSUMPTION_REQUIRED')
    f, p, x, a = copy.deepcopy(base); p[0, 0] = 0
    values['E_cell_boundary_unsupported'] = ((f, p, x, a), 'failure', None, 'CONFIG_INVALID')
    return values

def save_reload_fixture(folder, data, contract, expected_status, expected_code, tracked):
    folder.mkdir(parents=True, exist_ok=False)
    frame, points, pixels, assumptions = data
    arrays = folder / 'arrays.npz'
    with arrays.open('xb') as stream:
        np.savez_compressed(stream, depth_m=frame.depth_m, valid_mask=frame.valid_mask, target_mask=frame.target_mask)
    frame.metadata['storage'].update(file=arrays.name, sha256=record(arrays)['sha256'])
    newjson(folder / 'metadata.json', frame.metadata)
    with (folder / 'analytic_top_samples.npz').open('xb') as stream:
        np.savez_compressed(stream, points_m=points, pixel_vu=pixels)
    newjson(folder / 'synthetic_assumptions.json', assumptions)
    for path in sorted(folder.iterdir()): tracked.read(path)
    load_info = {'loader': 'contract.load_frame', 'rejected_error': None}
    try:
        loaded = contract.load_frame(folder / 'metadata.json')
    except contract.ContractError as error:
        # Bad-plane fixture must remain invalid. Do not weaken the loader or hide rejection.
        require(expected_status == 'failure' and error.code == expected_code,
                'unexpected persisted fixture loader rejection')
        metadata = tracked.json(folder / 'metadata.json')
        require(record(arrays)['sha256'] == metadata['storage']['sha256'], 'fixture NPZ hash mismatch')
        with np.load(arrays, allow_pickle=False) as saved:
            require(set(saved.files) == {'depth_m', 'valid_mask', 'target_mask'}, 'fixture NPZ keys differ')
            loaded = contract.FramePacket(metadata, saved['depth_m'], saved['valid_mask'], saved['target_mask'])
        load_info.update(loader='disk FramePacket after expected load_frame rejection; analyze reuses volume_preflight', rejected_error=error.code)
    with np.load(folder / 'analytic_top_samples.npz', allow_pickle=False) as saved:
        require(set(saved.files) == {'points_m', 'pixel_vu'}, 'sample NPZ keys differ')
        p, x = saved['points_m'], saved['pixel_vu']
    for actual, original in ((loaded.depth_m, frame.depth_m), (loaded.valid_mask, frame.valid_mask),
                             (loaded.target_mask, frame.target_mask), (p, points), (x, pixels)):
        require(actual.dtype == original.dtype and actual.shape == original.shape and np.array_equal(actual, original),
                'synthetic input exact save/reload mismatch')
    require(loaded.metadata == frame.metadata, 'saved metadata differs')
    saved_assumptions = tracked.json(folder / 'synthetic_assumptions.json')
    require(saved_assumptions == assumptions, 'saved assumptions differ')
    return (loaded, p, x, saved_assumptions), load_info

def run(args):
    baseline = Path(args.baseline).resolve()
    dest = reserve_output(args.output_root, [baseline])
    tracked = TrackedReads()
    audit = {'artifact_type': 'synthetic_height_integration_validation_v1', 'validation_status': 'failed',
             'data_source': 'synthetic', 'argv': sys.argv, 'started_at_utc': datetime.now(timezone.utc).isoformat(),
             'environment': {'python': sys.version, 'executable': sys.executable, 'numpy': np.__version__, 'platform': platform.platform()},
             'tolerances_declared_before_execution': TOLERANCE, 'units': UNITS, 'cases': {}, 'errors': [],
             'real_capture_inputs_read': False, 'team_approval': False, 'physical_accuracy_verified': False, **tool.FLAGS}
    try:
        for path in sorted(ROOT.glob('*.py')): tracked.read(path)
        contract = tool.load_contract(baseline, tracked)
        audit['import_paths'] = import_paths()
        audit['reused_functions'] = ['contract.FramePacket', 'contract.volume_preflight', 'contract.validate_json', 'contract.load_frame (generated synthetic files only)']
        for name, (data, status, expected, code) in cases(contract).items():
            folder = dest / 'inputs' / name
            loaded, load_info = save_reload_fixture(folder, data, contract, status, code, tracked)
            value = tool.analyze(*loaded)
            value['data_source'] = 'synthetic'; value['units'] = UNITS
            result_path = dest / (name + '.json'); newjson(result_path, value)
            saved = tracked.json(result_path)
            require(saved == value, 'saved result JSON differs')
            actual = saved['processing_result']; contract.validate_json(actual, 'processing')
            error = None if expected is None or actual['volume_m3'] is None else abs(actual['volume_m3'] - expected)
            passed = actual['status'] == status and actual['provenance_kind'] == 'synthetic'
            if status == 'success':
                passed = passed and error is not None and error <= TOLERANCE['volume_atol_m3'] and actual['volume_method'] is not None
            else:
                passed = passed and actual['volume_m3'] is None and actual['volume_method'] is None and actual['errors'][0]['code'] == code
            audit['cases'][name] = {'expected_status': status, 'actual_status': actual['status'],
                'expected_volume_m3': expected, 'actual_volume_m3': actual['volume_m3'], 'abs_error_m3': error,
                'expected_error': code, 'actual_errors': actual['errors'], 'matched_expectation': bool(passed),
                'input_files': {str(p): record(p) for p in sorted(folder.iterdir())}, 'result': str(result_path),
                'units': UNITS, 'exact_input_roundtrip': True, 'result_json_reloaded_and_validated': True, 'input_load': load_info}
            require(passed, 'case mismatch: ' + name)
        require(audit['cases']['A_known_cuboid']['actual_volume_m3'] == audit['cases']['B_duplicates_reordered']['actual_volume_m3'],
                'duplicated/reordered samples changed volume')
        require(not any(name in sys.modules for name in ('session_pipeline', 'viewer', 'viewer_data')),
                'unintended processing/viewer module imported')
    except Exception as error:
        audit['errors'].append({'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()})
    finally:
        try: audit.update(tracked.finish())
        except Exception as error: audit['errors'].append({'type': type(error).__name__, 'message': str(error)})
        audit['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    if not audit['errors']: audit['validation_status'] = 'passed_synthetic_height_integration_validation'
    newjson(dest / 'validation_summary.json', audit)
    print(json.dumps({'status': audit['validation_status'], 'cases': len(audit['cases']), 'errors': audit['errors']}, ensure_ascii=False))
    return 0 if not audit['errors'] else 1

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--output-root', required=True, type=Path)
    args = parser.parse_args()
    try: return run(args)
    except Exception:
        traceback.print_exc()
        return 1

if __name__ == '__main__': raise SystemExit(main())
