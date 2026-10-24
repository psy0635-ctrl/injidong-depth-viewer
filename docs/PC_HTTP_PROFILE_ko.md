# PC HTTP 임시 호환 프로필

2026-10-24. 기존 합의안 §7을 소비하는 **PC GET 클라이언트**의 현재 동작이다. 실제 이가영 서버의 응답/OpenAPI·origin·인증·적용 한도·공동 시험 자료를 대조하지 못했다. Android 업로드·서버 저장/복구를 구현한 문서가 아니다.

| 경계 | 현재 동작 |
|---|---|
| 목록 | GET /api/v1/sessions?limit=50. items 배열·next_cursor(string/null) 외피 |
| 레코드 | session_id, storage_status=stored, zip_size_bytes 양의 정수, zip_sha256 소문자hex64, stored_at UTC RFC3339, 동일 origin의 상대 download_path |
| 페이지 | 기본50·최대200, stored_at 내림차순/session_id 오름차순. opaque next_cursor를 다음 클릭 때 한 번 전달 |
| 다운로드 | GET /api/v1/sessions/{URL-encoded session_id}/archive |
| 필수 헤더 | X-Session-ID·X-Archive-SHA256·Content-Length 각각1개. 목록 기대값·실제 ZIP 바이트와 일치 |
| 전송 표현 | Accept-Encoding: identity, application/zip. redirect·Content-Encoding 변환·Transfer-Encoding·부분 응답을 거부 |
| 검증 연결 | 목록 기대값 → 헤더 → 실제 크기/SHA → 외부 기대값 wrapper → 기존 ZIP/배열/session 검사 → GUI 채택 |
| 오류 | HTTP 상태와 제한된 오류code로 분류. 응답 본문·인증 헤더·내부 경로를 그대로 표시/기록하지 않음 |
| 인증 | 기본없음, 선택적 Bearer 입력은 GUI 메모리만. 최종 서버 인증 계약 확정 아님 |
| 수명 | 실패/취소/늦은 결과 정리, 기존 정상 세션·미저장 ROI 유지. 새 성공 로드는 기존 편집을 교체. close()는 소유 다운로드·해제 캐시 정리 |

PC 개발 기본 설정은 I/O3초·HTTP 요청120초, JSON1MiB, ZIP128MiB다. 로더는 ZIP4096항목, 개별32MiB/총256MiB 해제, 최대128프레임·프레임당400만/세션1600만 픽셀 제한을 사용한다. 이는 실제 서버 적용값이나 전체 CPU/디스크 처리시간 보장이 아니다. 환경 설정은 INJIDONG_HTTP_IO_TIMEOUT_S / TOTAL_TIMEOUT_S / MAX_JSON_BYTES / MAX_ARCHIVE_BYTES이며 archive 상한을 로더보다 키우지 않는다.

loopback 시험 fixture는 127.0.0.1의 OS 배정 포트만 사용한다. X-Test-Fixture·TEST_HTTP_ERROR·고정 시험 stored_at/cursor는 시험용이며 실제 서비스 요구사항이 아니다. 실제 후보 주소·이웃 포트를 탐색하지 않는다. 비loopback HTTP에는 명시적 개발 허용이 필요하며 HTTPS 인증서 검증을 끄지 않는다.

업로드 multipart 및 created/existing·storage_status·최초 stored_at 보존은 기존 서버/Android 협의 범위다. 이 클라이언트는 POST를 구현하지 않는다. 실제 연결 전에 응답/OpenAPI·확정 origin/네트워크·인증 전달 방식·서버한도·시험session/ZIP크기/SHA·공동시각을 확보하고 adapter 차이만 최소 조정한다. 검증을 느슨하게 맞추지 않는다.
