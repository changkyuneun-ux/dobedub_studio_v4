# 체크리스트

> **갱신: 2026-08-10 (Cowork 세션 대조).** 아래는 실제 커밋 상태와 대조해 갱신한 결과입니다. 문구를 글자 그대로 충족하지 못했지만 취지는 충족된 항목은 각주로 이유를 남겼습니다.

## 착수 전

- [x] `Screen Map.dc.html`을 열어 전체 구조를 파악했다 — *진입(1)→생성 준비(2)→세그먼트 설정(3)→실행(4)→결과 확인(5)→이력·자산(6)→운영·관리(7) 7단계 26개 화면 흐름을 재확인. E 절 구현이 이 순서(2a~2d→3a~5a→4 Admin)를 그대로 따랐음을 대조 완료.*
- [x] `5 API-DB Gap.dc.html`을 읽고 A/B/C/D 분류를 이해했다 — *TASKS.md의 A(신규 개발)/B(기존 코드 수정)/C(화면만 구현)/D(결정 완료) 절이 이 문서의 분류·항목과 1:1로 대응함을 재확인(자산 5a/5c, 컬렉션 5c, 알림 6e, 감사 로그, 접근 이력, 세션 연장이 A절; 페이지 크기·평가 이중 저장·피드백 권한·실행 모드·삭제 방식·카탈로그 이중 구조·SYSTEM 그룹·지시문 버전이 B절 등).*
- [x] D-01 · D-02 · D-03 결정 완료 — TASKS.md의 D 절 참조 (재론 불필요) — *셋 다 코드 반영까지 완료(D-01 `b82a9c7`, D-03 `2d8705f`, D-02는 재점검 결과 조치 불필요로 확정).*
- [x] B-06 카탈로그 신형 일원화 4단계를 읽고 착수 순서를 이해했다 — *읽는 데 그치지 않고 1~3단계 및 4단계 컬럼 정리까지 코드로 완료됨(TASKS.md B-06 참조). 4단계의 구형 테이블 드롭만 의도적으로 이연.*
- [x] 저장소 재점검 완료 — *이 항목의 원문("2026-08-10, commit `a27ced5089db` — 마이그레이션 최신 `0011`, 8/9 이후 변경 없음")은 이제 사실과 다름. 그 시점 이후 마이그레이션 `0012`·`0013`이 추가되고 S-01·B-01~B-04·B-06·C-01·D-01·D-03이 커밋됨(로컬 15개 커밋, origin 미push). 아래 각 절의 체크 상태가 최신 재점검 결과임.*
- [x] 프론트 라우팅·권한 가드가 어디서 판정하는지 확인했다 — *`router.ts`의 `routeFromLocation()`이 경로→라우트를, `main.tsx`의 `ROUTE_REQUIRED_PERMISSION`/`routeAccessGranted()`가 라우트별 권한 판정을 담당. 이 과정에서 history/status/metadata/manual/admin 라우트가 가드를 우회하던 기존 버그를 발견해 함께 수정.*

## 화면 구현 중

**E-00~E-04 완료(`5c`만 A-02 대기로 제외).** `frontend/src/components/AppShell.tsx`가 공통 골격을 담당하고, `frontend/src/main.tsx`에 `Create2aScreen`~`Create2dScreen`(2a~2d), `Create3aScreen`, `Create4cScreen`, `Create5aScreen`, `Create7aScreen`, `Create6cScreen`, `Create6dScreen`, `Create5bScreen`, `Create3bScreen`, `Create7bScreen`, `Create4aScreen`, `Create4dScreen`, `PromptCatalogAdminPanelV3`(4e/3d/4b 통합, `focus` prop으로 구분), `Create3eScreen`(사용자 목록)·`Create7cScreen`(사용자 상세, `resetAdminUserPassword`/`deactivateAdminUser` 최초 연결)가 구현됨. `5c`(컬렉션)는 A-02(컬렉션 테이블·API)가 저장소에 전혀 없어 가짜 데이터 없이는 만들 수 없다는 판단으로 보류. E-06 완료(구버전 컴포넌트·모달 삭제 + 파일 분리). `main.tsx`는 9804줄 → 260줄(App/TopBar/LoginView/entry만)까지 줄었고, 나머지는 `StudioShell.tsx`·`screens/*.tsx`(create/review/admin/카탈로그 관리)·`components/*.tsx`·`helpers/*.ts`·`auth-session.ts`로 분리됨. `AdminConsoleModal`/`StatusModal`/`MetadataModal`/`HistoryModal`/`PromptBuilderModal`/`PromptReuseModal`/`PromptCatalogAdminModal`/구버전 `create.workspace` 폴백 등은 삭제됨. B-01·B-02·B-03·B-04·C-01의 로직은 신규 화면에서 재사용됨. **2026-08-11:** 독립 화면이던 `3f`/`3c` Run 상세(`Create3RunDetailScreen`)를 사용자 요청으로 폐지하고 `Create3aScreen` 우측 패널의 Overview/Assets/Node Config/Prompt Review 아코디언으로 흡수(`review.runDetail` 라우트 제거, `V3PromptReviewGroup`은 그대로 재사용).

- [x] 이 작업이 전면 재구축임을 이해했다 — 기존 화면을 고쳐 설계에 맞추는 방식으로 진행하지 않았다 — *2a~2d, 3a, 3f/3c, 4c 모두 신규 컴포넌트로 새로 작성. 구버전 `create.workspace`(옛 인라인 워크스페이스)는 아직 코드에 남아 있으나 더 이상 랜딩 지점이 아니며 E-06 제거 대상.*
- [x] 공통 골격(사이드바·헤더·본문 그리드·우측 패널)을 레이아웃 컴포넌트 하나로 만들어 전 화면이 공유한다 — *`AppShell`. 사이드바 1차 메뉴 클릭은 `shellNavigate()`가 실제 라우트로 매핑.*
- [x] 재사용한 것은 로직뿐이고, 구버전의 화면 구조나 스타일을 끌고 오지 않았다 — *워크플로/키프레임/세그먼트/프롬프트 빌더/잡 상태는 `StudioShell`의 기존 state를 그대로 재사용, UI는 전부 `.v3-*` 신규 클래스로 재작성.*
- [x] 설계에 없는 기존 UI 요소를 임의로 남기지 않았다
- [x] 설계 파일의 마크업을 복사하지 않고, 코드베이스의 기존 패턴으로 다시 만들었다
- [x] 색·간격·폰트는 README의 Design Tokens 값을 따르거나, 코드베이스에 동등한 토큰이 있으면 그쪽을 썼다 — *`--v3-*` 토큰만 사용.*
- [x] 화면에 `미구현` 배지가 있던 영역을 임의 데이터로 채우지 않았다 — *3c의 에러 트레이스·GPU 재시도, 4c 이외의 재사용 UI 등 대응 API 없는 항목은 코드 주석으로 사유를 남기고 생략.*
- [x] 권한이 없는 메뉴는 숨기고, 직접 진입만 403 화면에 도달하게 했다 — *`AppShell`이 `canUse()`로 사이드바 항목을 필터링, 직접 URL 진입은 `AccessDeniedModal`(임시, `7g` 정식 화면은 E-05 대상)로 처리.*
- [x] 예시 데이터(이름·프롬프트·수치)를 전부 실제 응답으로 교체했다
- [x] 목록 화면에 빈 상태와 로딩 상태를 만들었다 — 설계에는 데이터가 찬 상태만 그려져 있다 — *로딩·빈 상태 둘 다 있음: `3a`(작업 이력) · `5a`(자산) · `7b`(리소스 매핑) · `3e`(사용자 목록). 빈 상태 + 즉시 안내로 로딩 겸용: `4a`(워크플로) · `4c`(재사용, 검색 버튼 "Searching..."). 2026-08-11 나머지 갭 처리: `3b`(역할×권한)에 `loading && !governance` 로딩 문구 + 진짜 빈 상태(등록된 Role 없음) 문구를 구분 추가, `PromptCatalogAdminPanelV3`(4e/3d/4b) 카탈로그 트리에 로딩 문구 + 빈 상태(negativeDefaults는 "NEGATIVE 카탈로그 없음") 문구 추가. 전 화면 로딩·빈 상태 충족.*
- [~] 오류 표시를 규칙대로 배치했다 (동작 오류는 버튼 근처, 조회 실패는 본문) — **핵심 화면 타깃 적용 완료, 나머지는 추후 확장(2026-08-11 사용자 결정).** 새 패턴 `.v3-inline-error`(danger 톤 + 옅은 배경, 조회 실패용 상단 `.v3-inline-notice`와 구분)를 도입하고 우선 두 화면에 적용: (1) `3a` 삭제 - 삭제 실패를 삭제 모달의 버튼 근처에 표시. 이전엔 `modalNotice`가 **어디에도 렌더되지 않아 삭제 실패가 전혀 안 보이던 버그**였음(위치 오류를 넘어 미표시). (2) `7c` 사용자 상세 - 저장·비번 재설정·비활성화 실패를 전용 `adminUsersError` 상태로 분리해 Save User 버튼 근처에 표시, 성공 안내만 상단 notice로 남김. 나머지 화면(2b 생성·2f 실행·카탈로그 저장 등)은 현재 공통 notice 슬롯을 유지하며 같은 패턴으로 순차 확장 예정 - 2f는 실패 시 2c 진행 화면의 실패 상태 + A-03 토스트로 이미 노출됨.

## 카탈로그 이관 (B-06) 중

**완료.** (커밋 `cf7ec5a` 이관 마이그레이션 → `f05f89e` 읽기 전환 → `bfad428` 쓰기 전환 → `5d111ae`/`7d3029d` 정리)

- [x] 이관 마이그레이션에서 미대응 용어를 `기타` 서브카테고리로 수용해 유실을 막았다
- [x] 이관 건수와 미대응 건수를 로그로 남겼다
- [x] 읽기 경로 전환 후 `2b` 프롬프트 생성이 동일한 용어 목록을 반환한다 — *백엔드 응답 기준 확인. `2b` 화면 자체는 아직 구버전이라 화면 단 재확인은 E-02에서.*
- [x] 쓰기 경로 전환 후 구형 `prompt_terms`에 신규 행이 생기지 않는다
- [x] `used_term_ids`가 term id인지 keyword id인지 확정하고 문서에 적었다 — *`PromptTerm.id`로 확정, `prompt_builder_service.py` 코드 주석에 명시.*
- [x] `sync_prompt_catalog_hierarchy()` 자동 동기화가 이관과 충돌하지 않는지 확인했다 — *4단계에서 이 함수의 모든 호출부를 제거해 충돌 자체가 사라짐.*

## API 작업 중

- [x] 새 엔드포인트에 `require_permission`을 붙였다 — *A-01에서 추가된 `GET /api/assets`가 `require_permission("history:read")`로 보호됨을 재확인(`backend/app/api/v1/assets.py:22`).*
- [x] 새 엔드포인트를 `ui_permission_resources` 시드(`permission_service.py`의 `RESOURCE_CATALOG`) 등록했다 — 등록하지 않으면 `7b` 매핑 화면에 나타나지 않는다 — *2026-08-11 처리: A-01의 `GET /api/assets`를 `RESOURCE_CATALOG`에 등록 - API 행 `api.assets`(history:read, sort 342)와 5a 화면 MENU 행 `top.assets`(history:read, sort 11) 추가. `ensure_permission_resource_catalog()`가 매 요청 upsert하므로 마이그레이션 불필요. 이제 `7b` 기능 리소스 매핑 화면에 노출됨.*
- [x] 마이그레이션을 `backend/app/db/migrations/versions/`에 순번대로 추가했다 (최신 `0013`) — *2026-08-10 재확인, 최신 파일은 여전히 `20260810_0013_cleanup_legacy_category_coupling.py`(B-06 이관 `0012`, 정리 `0013`). 그 이후 추가된 마이그레이션 없음.*
- [x] `models.py`와 마이그레이션이 일치한다 — *2026-08-11 해소: 드리프트로 잡히던 인덱스 3개를 `models.py`에 선언 - `PromptCategoryGroup.scope_id`·`PromptSubcategory.category_group_id`는 `index=True`(각각 `ix_prompt_category_groups_scope_id`·`ix_prompt_subcategories_category_group_id` 자동 생성), `PromptSubcategoryKeyword`의 `subcategory_id`+`sort_order` 복합 인덱스는 `Index("ix_prompt_subcategory_keywords_subcategory_order", …)`로 선언(20260803_0004가 만든 이름과 동일). 임시 sqlite에 전체 마이그레이션(`0001`~`0014`) 적용 후 `alembic revision --autogenerate` 재실행 - 세 인덱스가 더 이상 드리프트로 나타나지 않고 `upgrade()` 본문이 비어 있음(드리프트 0) 확인, 점검용 파일·임시 DB 삭제.*
- [x] 감사 로그 기록이 본 동작을 막지 않는다 — *A-04 구현 완료. `audit_log_service.record_audit_log()`가 `except Exception: session.rollback()`으로 예외를 삼키는 `job_service.py:305-312`와 동일한 패턴을 따름. 세션 자체가 깨지는 상황을 흉내낸 스모크 테스트로 확인.*
- [x] 이력 관련 경로가 `db_adapter`만 사용한다 (D-03)
- [x] 미연결로 유지하기로 한 API(reports·configs)를 삭제하지 않았고, 프론트 호출도 없다 (D-01)

## 종료 전

*아래는 화면 재구축(E 절) 완료 후 최종 확인 항목입니다. 현재는 대부분 미착수 상태이며, 로직 차원에서 이미 충족된 항목만 체크했습니다.*

- [ ] 역할 4종(`SUPER_ADMIN` `ADMIN` `OPERATOR` `VIEWER`)으로 각각 로그인해 메뉴 노출과 403 동작을 확인했다 — *2026-08-10 코드 레벨 정합성 검증(실제 로그인 QA는 미실시라 미체크 유지): `ROUTE_REQUIRED_PERMISSION`(`StudioShell.tsx`)·`AppShell.tsx`의 `GENERATE_NAV_ITEMS`/`ADMIN_NAV_ITEMS` 권한 문자열 전부를 백엔드 `permissions` 시드(`0009`+`0011`, `admin:*` 포함 23개)와 대조 - 오탈자·존재하지 않는 권한 코드 없음. `SUPER_ADMIN`(`admin:*` 와일드카드, `canUse()`가 전체 허용)·`ADMIN`(users/roles/workflows/catalog 전체 + history/metadata/system/manual, sandbox 제외 - 기본 시드에 sandbox:read/control이 어떤 역할에도 배정돼 있지 않음, 3b 화면에서 배정 가능)·`OPERATOR`(workflows:read + jobs + prompts:build/reuse/review + history/metadata/system/manual, 사용자·역할·워크플로 쓰기·카탈로그 관리 제외)·`VIEWER`(workflows/history/metadata/system/manual 읽기만, `jobs:run` 없어 Generate 버튼은 비활성)까지 4개 역할의 기본 권한 집합과 라우트 가드가 논리적으로 어긋나지 않음을 확인. 다만 이는 정적 대조이고 실제 4개 계정으로 로그인해 사이드바 노출·403 화면 도달을 눈으로 확인하는 절차는 아니라 체크는 보류.*
- [x] 이력 페이지 크기가 백엔드·프론트·화면에서 모두 20으로 일치한다 — *신규 `3a`(`Create3aScreen`, E-03) 화면 기준으로 재확인 완료.*
- [x] 프롬프트 평가가 한 곳에서만 저장되고 이중 기록이 없다 — *신규 `3f`/`3c` 통합 화면(`Create3RunDetailScreen`, E-03) 기준으로 재확인 완료. 세그먼트 편집 화면(2e)에는 평가 UI 없음. 2026-08-11: `Create3RunDetailScreen` 폐지, 평가는 `Create3aScreen` 우측 패널 Prompt Review 아코디언 한 곳으로 이동 — 저장 API·역할 분리(B-02)는 동일하게 유지되어 "한 곳에서만" 원칙은 그대로 충족.*
- [x] 취소 요청 후 UI 잠금과 실패 시 복구가 동작한다 — *2026-08-10 코드 확인: `StudioShell.tsx`의 `cancelGeneration()`(`cancelRequested`를 즉시 `true`로 세팅해 재클릭 잠금) - 실패 시 `catch` 블록에서 `setCancelRequested(false)`로 복구하고 에러 메시지를 표시함(`StudioShell.tsx:1501-1515`). 로직은 명확하나 실제 실행 취소를 트리거하는 런타임 QA는 미실시.*
- [x] 진행 중 작업의 삭제 버튼이 비활성이다 — *2026-08-10 발견 즉시 수정. 프론트: `helpers/format.ts`에 `isTerminalHistoryStatus()`(백엔드 `TERMINAL_STATES`와 값 일치: completed/success/failed/cancelled/timed_out) 추가 - `reviewScreens.tsx`의 3a 목록 삭제 버튼을 `canDelete && isTerminalHistoryStatus(item.status)`로 가드하고, 삭제 확인 모달(당시엔 embedded/`components/Modals.tsx`의 `ConfirmDeleteModal` 둘 다 존재해 양쪽 다 가드)의 확인 버튼도 동일 조건으로 비활성화. 백엔드: `db_adapter.py`의 `delete_history_item`이 `task.status`가 `task_tracking_service.TERMINAL_STATES`에 없으면 `ValueError`를 던지도록 가드 추가, `history.py` 라우트가 이를 409로 매핑(API 직접 호출 방어). sqlite로 실제 seed 데이터(running/queued/completed 상태)를 만들어 리포지토리 레벨 + `TestClient` HTTP 레벨 모두 검증 - 진행 중 작업은 409/`ValueError`로 차단, 완료 작업은 정상 삭제, 존재하지 않는 작업은 기존대로 404 유지. `tsc -b`/`vite build` 클린.*
  - *2026-08-11 추가 수정: "3a 삭제 기능·확인창 구현 필요"라는 사용자 요청을 받고 `3 Review.dc.html`(209~230번째 줄) 원본과 대조한 결과, 확인창 자체는 스펙대로(HISTORY:DELETE 라벨·작업/실행/결과물 요약 카드·"되돌릴 수 없습니다" 경고 스트립·하단 안내문) `Create3aScreen`에 이미 구현돼 있었으나(`reviewScreens.tsx:213-243`), `StudioShell.tsx`가 같은 `deleteTarget` 상태를 보고 위 항목에서 언급한 구버전 `ConfirmDeleteModal`(`.modal-layer` 스타일)까지 전역으로 함께 렌더링하고 있어 3a에서 삭제 버튼을 누르면 확인창이 두 개 겹쳐 뜨는 버그였다(둘 다 같은 `deleteTarget`/`onCancel`/`onConfirm`을 공유해 기능적으로는 어느 쪽을 눌러도 정상 동작했지만, 화면엔 스펙에 없는 중복 다이얼로그가 표시됨). `deleteTarget`을 세팅하는 곳이 3a 목록의 삭제 버튼 하나뿐임을 grep으로 확인한 뒤, 구버전 `ConfirmDeleteModal`(`components/Modals.tsx`)과 `StudioShell.tsx`의 렌더 지점을 제거 - `Create3aScreen` 내장 v3 모달 하나만 남는다. `tsc -b`/`vite build` 클린 확인.*
- [x] `npm audit --omit=dev` 취약점 0개 (기존 체크리스트 기준 유지) — *2026-08-11 `npm audit fix`로 `nanoid` high 1건 해결(transitive, non-breaking). `npm audit --omit=dev` = 0 vulnerabilities, `vite build` 클린 재확인.*
- [x] 프론트에 `admin/prompt-catalog` 문자열이 남아 있지 않다 (D-02 · 백엔드에는 원래 없는 엔드포인트) — *grep 결과 없음.*
- [x] 이력 화면의 어떤 동작도 JSON 파일을 읽거나 쓰지 않는다 (D-03) — *백엔드 경로 기준 확인(스모크 테스트 통과, 커밋 `2d8705f` 참조). 신규 `3a` 화면(E-03) 완성 후 최종 재확인 완료.*
- [x] 대체된 구버전 화면·컴포넌트를 실제로 제거했다 (죽은 코드로 남기지 않았다) — *E-06(금번 세션)에서 완료. `AdminConsoleModal`/`StatusModal`/`MetadataModal`/`HistoryModal`/`PromptBuilderModal`/`PromptReuseModal`/`PromptCatalogAdminModal`/구버전 `create.workspace` 폴백 및 그 배후 고아 컴포넌트 모두 삭제, `tsc -b`/`vite build` 클린 확인.*
- [x] 전 화면을 나란히 열어 사이드바 폭·헤더 높이·색·간격이 일관된다 — *2026-08-10 코드 레벨 확인(시각적 스크린샷 대조는 아님): `<AppShell` 사용처 22곳(모든 `Create*Screen`/`PromptCatalogAdminPanelV3`) 전부 `style` prop 없이 호출되고, `.v3-sidebar`/`.v3-header`는 `styles.css`에 각각 단 한 번만 정의되며 화면별 override 클래스가 없음. 사이드바 폭은 `--v3-sidebar-width: 212px` 변수 하나로 `grid-template-columns`에 적용됨(README 212px 스펙과 일치). 구조상 모든 화면이 동일한 골격을 강제로 공유하므로 일관성이 코드로 보장됨 - 다만 실제 화면을 나란히 띄워 눈으로 보는 절차는 아니라 참고용으로 체크.*
- [x] 설계와 달라진 부분이 있으면 이 번들이 아니라 저장소 문서에 기록했다 — *`git log --follow -- 'design_handoff_dobedub_v3/*.dc.html'`로 확인 - 최초 추가 커밋(`60ebdb0`) 이후 단 한 번도 수정되지 않음(mockup 파일 자체는 읽기 전용으로 유지됨). 모든 편차·결정 사항은 이번 세션 내내 `TASKS.md`/`CHECKLIST.md`의 각주와 코드 주석으로만 기록함.*
