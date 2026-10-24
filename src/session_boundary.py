"""Project publication/path guards outside the unchanged core 1.0.0 schemas.

Legacy external sessions remain readable. New managed sessions require a final
completion sidecar. Only the producer's private staging context can read pending
files; a public config flag cannot disable this guard. This is a filesystem
completion protocol, not authentication or physical/team approval.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path, PureWindowsPath

RUN_MARKER = '.ade71-run.json'
SESSION_MARKER = '.ade71-session.json'
COMPLETION = '.ade71-complete.json'
FORMAT = 'ade71-publication-v1'
_staging_run = ContextVar('ade71_private_staging_run', default=None)


def _fail(code, message):
    from contract import fail
    fail(code, message)


def _json(path):
    def reject(value):
        _fail('SESSION_UNCOMMITTED', f'nonfinite completion token: {value}')
    try:
        value = path.read_text(encoding='utf-8')
        return json.loads(value, parse_constant=reject)
    except (OSError, ValueError, UnicodeError) as error:
        _fail('SESSION_UNCOMMITTED', f'completion record unreadable: {error}')


def _digest(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        _fail('SESSION_UNCOMMITTED', f'completion dependency unreadable: {error}')


def relative_path(base, value):
    """Reject absolute syntax even when it resolves inside base; resolve aliases."""
    if isinstance(value, Path):
        value = value.as_posix()
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        _fail('PATH_INVALID', 'nonempty relative POSIX path required')
    path = Path(value)
    win = PureWindowsPath(value)
    if path.is_absolute() or win.drive or win.root or '..' in path.parts:
        _fail('PATH_INVALID', 'relative path required, no parent traversal')
    base = Path(base).resolve()
    resolved = (base / path).resolve()
    if not resolved.is_relative_to(base):
        _fail('PATH_INVALID', 'resolved path escapes its input directory')
    return resolved


def disjoint_output(output, inputs):
    """Resolve existing symlink/junction ancestors, reject nesting both ways."""
    destination = Path(output).resolve()
    for item in inputs:
        source = Path(item).resolve()
        if destination.is_relative_to(source) or source.is_relative_to(destination):
            _fail('PATH_INVALID', 'output and input directories must be disjoint in both directions')
    return destination


@contextmanager
def _staging(run):
    """Producer-internal capability; never exposed as a CLI or config option."""
    token = _staging_run.set(Path(run).resolve())
    try:
        yield
    finally:
        _staging_run.reset(token)


def guard_read(path):
    """Public loaders reject every managed artifact without its final commit."""
    path = Path(path).resolve()
    run = None
    for folder in (path, *path.parents):
        if (folder / SESSION_MARKER).is_file():
            marker = _json(folder / SESSION_MARKER)
            if marker != {'format': FORMAT, 'completion_required': True}:
                _fail('SESSION_UNCOMMITTED', 'invalid managed session marker')
            if not (folder.parent / RUN_MARKER).is_file():
                _fail('SESSION_UNCOMMITTED', 'managed session detached from its completion record')
        if (folder / RUN_MARKER).is_file():
            run = folder
            break
    if run is None:
        return  # External/legacy contract sessions are not this producer's output.
    if _json(run / RUN_MARKER) != {'format': FORMAT, 'completion_required': True}:
        _fail('SESSION_UNCOMMITTED', 'invalid managed run marker')
    if _staging_run.get() == run:
        return
    record = _json(run / COMPLETION)
    if (not isinstance(record, dict) or set(record) != {'format', 'validation_sha256', 'manifest_sha256', 'processing_sha256'}
            or record['format'] != FORMAT or not isinstance(record['processing_sha256'], dict)
            or not record['processing_sha256']):
        _fail('SESSION_UNCOMMITTED', 'invalid final completion record')
    if _digest(run / 'validation.json') != record['validation_sha256']:
        _fail('SESSION_UNCOMMITTED', 'final validation checksum mismatch')
    report = _json(run / 'validation.json')
    if (report.get('status') != 'passed_file_boundary_validation' or report.get('errors')
            or report.get('completed_repeats') != report.get('requested_repeats')):
        _fail('SESSION_UNCOMMITTED', 'run did not finish verification')
    if _digest(run / 'session/frames.jsonl') != record['manifest_sha256']:
        _fail('SESSION_UNCOMMITTED', 'committed manifest mismatch')
    for name, value in record['processing_sha256'].items():
        result_path = relative_path(run, name)
        if _digest(result_path) != value or _json(result_path).get('status') != 'success':
            _fail('SESSION_UNCOMMITTED', 'committed processing result mismatch')
    # A completed sibling session cannot authorize abandoned staging files.
    if path.is_relative_to(run / 'pending_session') or path.is_relative_to(run / 'pending_results'):
        _fail('SESSION_UNCOMMITTED', 'staging output is never a published input')


def remember_origin(frame, metadata_path):
    # Runtime-only source context. No extra core metadata/dataclass field.
    frame._ade71_metadata_path = Path(metadata_path).resolve()
    return frame


def guard_packet(frame):
    source = getattr(frame, '_ade71_metadata_path', None)
    if source is not None:
        guard_read(source)


def packet_input_dirs(frame):
    source = getattr(frame, '_ade71_metadata_path', None)
    if source is None:
        return []
    source = Path(source).resolve()
    for folder in source.parents:
        if (folder / SESSION_MARKER).exists() or (folder / 'frames.jsonl').exists():
            return [folder]
    return [source.parent]


def load_processing_result(path):
    """Supported on-disk ProcessingResult reader; checks completion then core."""
    path = Path(path).resolve()
    guard_read(path)
    if path.name != 'processing.json':
        _fail('SESSION_UNCOMMITTED', 'pending/uncommitted result is not a public result')
    result = _json(path)
    from contract import validate_json
    validate_json(result, 'processing')
    return result
