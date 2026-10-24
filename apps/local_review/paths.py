"""Local code, explicit external robot inputs; historical paths are identifiers only."""
from pathlib import Path, PureWindowsPath
import sys, json, os

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parents[1]
CODE = REPOSITORY
BASELINE = REPOSITORY
COLOR = ROOT / 'lib/color'


def required(path):
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError('필수 파일 누락: ' + str(path) + '; 외부 입력 묶음과 파일 무결성을 확인하세요.')
    return path


def _relative(root, value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError('input mapping requires a relative POSIX path')
    p = Path(value)
    if p.is_absolute() or '..' in p.parts:
        raise ValueError('input mapping escapes selected root')
    target = (root / p).resolve()
    if not target.is_relative_to(root):
        raise ValueError('input mapping escapes selected root')
    return target


def _key(p):
    return str(p).replace('\\', '/').casefold()


_selected = os.environ.get('INJIDONG_ROBOT_REVIEW_ROOT')
INPUT_ROOT = Path(_selected).expanduser().resolve() if _selected else None
CONFIG = json.loads(required(INPUT_ROOT / 'path_map.json').read_text(encoding='utf-8')) if INPUT_ROOT else {}
MAPPING = {_key(old): _relative(INPUT_ROOT, rel) for old, rel in CONFIG.get('original_to_package', {}).items()}
REVERSE = {str(p): old for old, rel in CONFIG.get('original_to_package', {}).items()
           for p in [_relative(INPUT_ROOT, rel)]}
_data = INPUT_ROOT or ROOT / 'unconfigured_robot_input'
INTAKE = _data / 'data/intake'
FLOOR = _data / 'evidence/floor'
PRIOR_REVIEW = _data / 'evidence/prior_review'
if INPUT_ROOT:
    for key in ('session_id', 'frame_id'):
        value = CONFIG[key]
        if not isinstance(value, str) or not value or value in ('.', '..') or any(c in value for c in '/\\:'):
            raise ValueError('single-component robot identity required: ' + key)
    candidates = {p.parent for p in MAPPING.values() if p.name == 'independent_planes.json' and p.is_relative_to(FLOOR)}
    if len(candidates) != 1:
        raise ValueError('one mapped saved robot plane run is required')
    FLOOR_RUN = candidates.pop()
else:
    FLOOR_RUN = FLOOR / 'unconfigured'
SESSION = INTAKE / 'partial_original/sessions' / CONFIG.get('session_id', 'unconfigured')
FRAME_ID = CONFIG.get('frame_id')


def require_robot_input():
    if INPUT_ROOT is None:
        raise ValueError('로봇 자료는 공개본에 없습니다. INJIDONG_ROBOT_REVIEW_ROOT에 승인된 로봇 검토 입력 묶음의 루트를 명시하세요. 모바일은 --mobile로 실행하세요.')


def resolve_recorded(value):
    mapped = MAPPING.get(_key(value))
    if mapped is not None:
        return required(mapped)
    p = Path(value).resolve()
    if INPUT_ROOT and p.is_relative_to(INPUT_ROOT) and str(p) in REVERSE:
        return required(p)
    raise ValueError('선택한 입력 경로표에 없는 참조(원본 PC fallback 금지)')


def recorded(value):
    p = Path(value).resolve()
    try:
        return REVERSE[str(p)]
    except KeyError as e:
        raise ValueError('unmapped provenance source') from e


def resolve_bundle_source(bundle, value):
    legacy = CONFIG.get('representative_legacy_sources', {}).get(value)
    if legacy is not None:
        return required(_relative(INPUT_ROOT, legacy))
    if PureWindowsPath(value).drive or Path(value).is_absolute():
        raise ValueError('relative bundle source required')
    p = (Path(bundle) / value).resolve()
    if INPUT_ROOT is None or not p.is_relative_to(INPUT_ROOT) or str(p) not in REVERSE:
        raise ValueError('선택한 입력 묶음에 없는 참조')
    return required(p)


def canonical_source_records(bundle, records):
    return sorted((str(resolve_bundle_source(bundle, r['path'])), r['sha256'], r['relative_to']) for r in records)


def load_contract():
    sys.path.insert(0, str(CODE / 'tools/stored_depth_analysis'))
    from _common import load_baseline
    return load_baseline(required(BASELINE))
