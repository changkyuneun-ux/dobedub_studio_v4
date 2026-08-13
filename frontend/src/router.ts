// E-01 후속: design_handoff_dobedub_v3의 업무 흐름(1 Access · 2 Create[S1~S5] ·
// 3 Review · 4 Admin) 기준으로 라우트를 재설계했다. 이전에는 기능 이름을 그대로 쓴
// 평평한 목록(login/studio/history/status/metadata/manual/admin)이었고, 화면
// README의 흐름 구분(예: status·metadata가 실은 "4 Admin.dc.html" 소속, manual이
// "1 Access.dc.html" 소속)과 코드가 어긋나 있었다. 문자열 리터럴 하나로 남긴 이유는
// main.tsx 전역에 `route === "..."` 비교가 많아, flow/screen을 객체로 쪼개면 변경
// 범위가 라우팅과 무관한 곳까지 커지기 때문이다 - 대신 "flow.screen" 접두 규칙으로
// 흐름을 표현한다.
//
// design_handoff 화면 id 대응:
//   access.login      — 6a 로그인
//   access.manual     — 6b 사용자 매뉴얼 ("1 Access.dc.html" 소속)
//   create.load       — 2a · S1 이미지 로드 (신규 구현, E-02)
//   create.prompt     — 2b+2e 병합 · S2 세그먼트 설정 · 프롬프트 + 노드 컨피그
//                        (2026-08-11: 두 화면을 하나로 병합, 좌우 분할 레이아웃)
//   create.confirm    — 2f · S4 실행 전 전체 구성 확인 & Run (신규 구현, E-02)
//   create.progress/create.result — 멀티 Task 전환 후 retired. 진행/결과/취소/재작업은
//                                   review.history의 목록과 우측 상세 패널이 담당한다.
//   create.workspace  — E-02 완료 후 제거 예정이던 임시 다리였다. 2a~2d가 모두
//                       구현되며 더 이상 랜딩 지점으로 쓰이지 않게 됐고, 다른
//                       화면에서 참조하던 구버전 인라인 워크스페이스 JSX도
//                       E-06에서 삭제됐다 - 이 라우트 자체가 도달 불가능해져
//                       StudioRoute에서 제거했다(옛 /studio/studio 북마크는
//                       LEGACY_LAST_SEGMENT_ROUTE로 create.load로 보낸다).
//   review.history    — 3a 작업 이력 ("3 Review.dc.html" 소속). 2026-08-11: 별도
//                       화면이던 review.runDetail(3f/3c Run 상세)을 폐지하고 그
//                       내용을 이 화면 우측 패널 아코디언으로 흡수했다(사용자 요청).
//   review.reuse      — 4c 프롬프트 재사용 (신규 구현, E-03)
//   review.assets     — 5a+5c "Asset 관리" (신규 구현, E-03. 2026-08-11: 원래
//                       별개 화면이던 5a 자산 목록·5c 컬렉션을 사용자 요청으로
//                       통합 - 자산은 output 기준으로 관리되고 input 이미지는
//                       그 출력에 종속, 컬렉션은 사이드바 필터 겸 각 자산 행의
//                       칩으로 표시. `review.collections` 라우트는 폐지됨.
//   admin.systemPrompt — 7a 시스템 프롬프트 (신규 구현, E-04). "프롬프트 카탈로그"
//                       Admin 사이드바 그룹 소속.
//   admin.sandbox      — 5b Sandbox Pod (신규 구현, E-04). "Sandbox Pod" Admin
//                       사이드바 그룹 소속.
//   admin.taskPolicy   — Serverless 동시 Task 제출 정책. Sandbox Pod 바로 아래의
//                       독립 Admin 메뉴이며 Pod 제어 상태와는 분리된다.
//   admin.roles        — 3b 역할×권한 매트릭스 (신규 구현, E-04). "역할 & 권한"
//                       Admin 사이드바 그룹 소속.
//   admin.resourceMap  — 7b 기능 리소스 매핑 (신규 구현, E-04). 3b와 같은
//                       PermissionGovernance 데이터를 공유하지만, 원본 구버전
//                       탭 안에 같이 있던 것을 설계 문서 화면 구분대로 분리했다.
//   admin.users        — 3e 사용자 목록 (신규 구현, E-04). "사용자" Admin
//                       사이드바 그룹 소속.
//   admin.userDetail   — 7c 사용자 상세/등록 (신규 구현, E-04). 3e 목록에서
//                       행을 클릭하거나 New User를 누르면 이 화면으로 이동한다.
//                       구버전 AdminConsoleModal Users 탭은 목록·상세를 한
//                       화면에 같이 그렸지만, design_handoff가 3e/7c로 화면
//                       id를 분리하므로 4a/4d와 같은 방식(목록/상세 분리, 상태는
//                       StudioShell에 유지)으로 나눴다.
//   admin.workflows      — 4a 워크플로 정의 목록/조회/활성화 (신규 구현, E-04).
//   admin.workflowRegister — 4d 워크플로 등록/갱신 단일 저장 폼 (신규 구현, E-04).
//                       "워크플로 정의" Admin 사이드바 그룹 소속.
//   admin.catalogHierarchy — 4e 카탈로그 계층 (신규 구현, E-04).
//   admin.catalogTerms     — 3d 용어 관리 (신규 구현, E-04). 4e와 완전히 같은
//                       트리+상세 패널 컴포넌트를 함께 쓴다 - 구버전부터 스코프→
//                       그룹→서브카테고리→용어가 하나의 연결된 트리 탐색으로
//                       설계돼 있어(PromptCatalogAdminContent), 화면을 억지로
//                       둘로 쪼개면 같은 트리를 두 번 그리게 된다. 3f/3c를 하나의
//                       컴포넌트로 합친 것과 같은 이유(E-03 참조).
//   admin.negativeDefaults — 4b Negative 기본값 (신규 구현, E-04). 별도 데이터가
//                       아니라 위 트리를 NEGATIVE scope로 필터링한 같은 화면이다
//                       (design_handoff 4b 원본: 모든 Run에 적용되는 네거티브는
//                       워크플로 JSON에 내장돼 읽기 전용이고, 이 화면은 그 위에
//                       "추가"할 선택 용어만 다룸).
//   admin.console      — 4 Admin의 users/roles/catalog/workflows/sandbox 통합 콘솔이던
//                       구버전 AdminConsoleModal 라우트. E-04에서 그 탭들이 모두
//                       3b/3e/7c/4a/4d/admin.catalog*/5b 같은 신규 화면으로 이관됐고,
//                       사이드바 어디에서도 이 라우트로 보내지 않게 되며 도달
//                       불가능해졌다 - E-06에서 AdminConsoleModal과 함께 제거했다
//                       (옛 /studio/admin 북마크는 LEGACY_LAST_SEGMENT_ROUTE로
//                       admin.roles로 보낸다).
//   admin.status       — 6c 시스템 상태 ("4 Admin.dc.html" 소속, 구버전엔 독립 라우트였음)
//   admin.metadata     — 6d 메타데이터 ("4 Admin.dc.html" 소속, 구버전엔 독립 라우트였음)
//   admin.auditLog     — 감사 로그 (신규 구현, A-04)
export type StudioRoute =
  | "access.login"
  | "access.manual"
  | "create.load"
  | "create.prompt"
  | "create.confirm"
  | "review.history"
  | "review.reuse"
  | "review.assets"
  | "admin.systemPrompt"
  | "admin.sandbox"
  | "admin.taskPolicy"
  | "admin.roles"
  | "admin.resourceMap"
  | "admin.users"
  | "admin.userDetail"
  | "admin.workflows"
  | "admin.workflowRegister"
  | "admin.catalogHierarchy"
  | "admin.catalogTerms"
  | "admin.negativeDefaults"
  | "admin.status"
  | "admin.metadata"
  | "admin.auditLog";

// 구버전 경로(/studio/history 등)로 온 북마크·외부 링크가 깨지지 않도록 옛 경로
// 마지막 세그먼트 → 신규 StudioRoute로 매핑. 신규 경로는 routePath()가 만드는
// flow/screen 2단 경로(/studio/admin/status 등)를 기준으로 한다.
const LEGACY_LAST_SEGMENT_ROUTE: Record<string, StudioRoute> = {
  login: "access.login",
  manual: "access.manual",
  // E-06: create.workspace/admin.console 둘 다 라우트 자체가 제거됐으므로, 옛
  // 북마크는 각 흐름의 실제 첫 화면(2a/3b)으로 보낸다.
  studio: "create.load",
  history: "review.history",
  admin: "admin.roles",
  status: "admin.status",
  metadata: "admin.metadata"
};

const ROUTE_PATH: Record<StudioRoute, string> = {
  "access.login": "/studio/access/login",
  "access.manual": "/studio/access/manual",
  "create.load": "/studio/create/load",
  "create.prompt": "/studio/create/prompt",
  "create.confirm": "/studio/create/confirm",
  "review.history": "/studio/review/history",
  "review.reuse": "/studio/review/reuse",
  "review.assets": "/studio/review/assets",
  "admin.systemPrompt": "/studio/admin/system-prompt",
  "admin.sandbox": "/studio/admin/sandbox",
  "admin.taskPolicy": "/studio/admin/task-policy",
  "admin.roles": "/studio/admin/roles",
  "admin.resourceMap": "/studio/admin/resource-map",
  "admin.users": "/studio/admin/users",
  "admin.userDetail": "/studio/admin/users/detail",
  "admin.workflows": "/studio/admin/workflows",
  "admin.workflowRegister": "/studio/admin/workflows/register",
  "admin.catalogHierarchy": "/studio/admin/catalog/hierarchy",
  "admin.catalogTerms": "/studio/admin/catalog/terms",
  "admin.negativeDefaults": "/studio/admin/catalog/negative-defaults",
  "admin.status": "/studio/admin/status",
  "admin.metadata": "/studio/admin/metadata",
  "admin.auditLog": "/studio/admin/audit-log"
};

const PATH_TO_ROUTE: Record<string, StudioRoute> = Object.fromEntries(
  Object.entries(ROUTE_PATH).map(([route, path]) => [path, route as StudioRoute])
) as Record<string, StudioRoute>;

const RETIRED_CREATE_ROUTE_REDIRECTS: Record<string, StudioRoute> = {
  "/studio/create/progress": "review.history",
  "/studio/create/result": "review.history"
};

export function isRetiredCreateRoutePath(pathname: string): boolean {
  return Boolean(RETIRED_CREATE_ROUTE_REDIRECTS[pathname]);
}

export function routeFromLocation(pathname: string, hasUser: boolean): StudioRoute {
  if (!hasUser) {
    return "access.login";
  }
  const retiredRoute = RETIRED_CREATE_ROUTE_REDIRECTS[pathname];
  if (retiredRoute) {
    return retiredRoute;
  }
  const exact = PATH_TO_ROUTE[pathname];
  if (exact) {
    return exact;
  }
  const lastSegment = pathname.split("/").filter(Boolean).pop() || "";
  const legacy = LEGACY_LAST_SEGMENT_ROUTE[lastSegment];
  if (legacy) {
    return legacy;
  }
  // E-06: create.workspace(옛 catch-all 타깃)가 라우트에서 제거됐으므로, 알 수
  // 없는 경로는 create 흐름의 실제 첫 화면(2a)으로 보낸다.
  return "create.load";
}

export function routePath(route: StudioRoute): string {
  return ROUTE_PATH[route];
}
