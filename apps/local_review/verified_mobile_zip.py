"""Offline expected-value gate; no HTTP schema, GUI, or loader policy changes.

A successful return transfers a LoadedMobileSession to the caller, who must
close() it. The short-lived verification ZIP is removed before returning.
"""
import hashlib
from pathlib import Path
import re
import tempfile

import mobile_session as mobile

_CHUNK_BYTES=1024*1024


class VerifiedZipError(ValueError):
    """Stable local error code; optional existing loader code, no path/data detail."""
    def __init__(self,code,message,*,loader_code=None):
        self.code=code
        self.loader_code=loader_code
        super().__init__(f'{code}: {message}')


def _check_expectations(session_id,size_bytes,sha256):
    if not isinstance(session_id,str) or not session_id.strip():
        raise VerifiedZipError('INVALID_EXPECTATION','기대 세션 ID는 비어 있지 않은 문자열이어야 합니다.')
    if type(size_bytes) is not int or size_bytes<=0:
        raise VerifiedZipError('INVALID_EXPECTATION','기대 ZIP 크기는 양의 정수여야 합니다.')
    if not isinstance(sha256,str) or re.fullmatch(r'[0-9a-f]{64}',sha256) is None:
        raise VerifiedZipError('INVALID_EXPECTATION','기대 SHA-256은 소문자 16진수 64자리여야 합니다.')


def load_verified_mobile_zip(archive_path,expected_session_id,expected_size_bytes,
                             expected_sha256,cache_root,*,limits=None,
                             progress=lambda message:None):
    """Match expected ID/size/SHA and run the unchanged current mobile loader.

    cache_root is an application-configured scratch directory outside app code;
    it is not an ID/filename from a remote response. Existing cache files and the
    input ZIP are never overwritten. limits/progress have the loader's meanings.

    The returned session owns the loader's independent extraction directory.
    Its report['archive_path'] is the historical staging ZIP path (already
    removed), not a guarantee about bytes now present at the input pathname.
    """
    _check_expectations(expected_session_id,expected_size_bytes,expected_sha256)
    active_limits=limits or mobile.ZipLimits()
    try:
        source=Path(archive_path)
        mobile.compat.require_unlinked(source)
        if not source.is_file():raise ValueError('not a regular input file')
        cache=Path(cache_root).absolute()
        if cache.resolve().is_relative_to(mobile.ROOT):
            raise ValueError('cache overlaps application input')
        cache.mkdir(parents=True,exist_ok=True)
        mobile.compat.require_unlinked(cache)
    except (OSError,ValueError,TypeError):
        raise VerifiedZipError('FILE_ACCESS','입력 파일 또는 검사 캐시에 접근할 수 없습니다.') from None

    session=None
    transferred=False
    try:
        with tempfile.TemporaryDirectory(prefix='verified_zip_',dir=cache) as staging:
            # All destination components are locally generated, never caller IDs.
            snapshot=Path(staging)/'archive.zip'
            size=0;digest=hashlib.sha256()
            with source.open('rb') as src,snapshot.open('xb') as dst:
                while chunk:=src.read(_CHUNK_BYTES):
                    size+=len(chunk)
                    if size>expected_size_bytes:
                        raise VerifiedZipError('SIZE_MISMATCH','ZIP 크기가 기대값과 다릅니다.')
                    # Reuse the existing loader limit, before an oversized disk copy.
                    if size>active_limits.max_archive_bytes:
                        raise VerifiedZipError('LOADER_REJECTED','현재 로더의 ZIP 크기 제한을 초과했습니다.',
                                               loader_code='LIMIT_EXCEEDED')
                    digest.update(chunk);dst.write(chunk)
            if size!=expected_size_bytes:
                raise VerifiedZipError('SIZE_MISMATCH','ZIP 크기가 기대값과 다릅니다.')
            if digest.hexdigest()!=expected_sha256:
                raise VerifiedZipError('HASH_MISMATCH','ZIP SHA-256이 기대값과 다릅니다.')
            try:
                session=mobile.load_mobile_zip(snapshot,cache,limits=active_limits,progress=progress)
            except mobile.MobileInputError as exc:
                raise VerifiedZipError('LOADER_REJECTED','기존 모바일 로더의 파일 검사를 통과하지 못했습니다.',
                                       loader_code=exc.code) from None
            # The loader reports the bytes it actually read. Check before exposure.
            if session.report['zip_size_bytes']!=expected_size_bytes:
                raise VerifiedZipError('SIZE_MISMATCH','로더가 읽은 ZIP 크기가 기대값과 다릅니다.')
            if session.report['zip_sha256']!=expected_sha256:
                raise VerifiedZipError('HASH_MISMATCH','로더가 읽은 ZIP SHA-256이 기대값과 다릅니다.')
            if session.session_id!=expected_session_id:
                raise VerifiedZipError('SESSION_ID_MISMATCH','ZIP 내부 세션 ID가 기대값과 다릅니다.')
        # Transfer only after staging cleanup succeeded.
        transferred=True
        return session
    except OSError:
        raise VerifiedZipError('FILE_ACCESS','검사 작업 파일의 읽기·쓰기 또는 정리에 실패했습니다.') from None
    finally:
        if session is not None and not transferred:
            try:session.close()
            except OSError:
                raise VerifiedZipError('FILE_ACCESS','실패한 세션의 임시 파일 정리에 실패했습니다.') from None
