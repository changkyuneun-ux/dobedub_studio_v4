import { StudioRoute } from "../router";

// E-02/E-03: AppShell(E-01)의 사이드바 1차 메뉴(workspace/promptLibrary/taskHistory/
// assets)는 화면마다 반복되는 공통 골격이라 각 Create*Screen이 받는 onGoTo(실제
// StudioRoute 이동)를 통해 여기서 한 곳에서만 매핑한다.
export function shellNavigate(key: string, onGoTo: (route: StudioRoute) => void) {
  if (key === "workspace") {
    onGoTo("create.load");
  } else if (key === "taskHistory") {
    onGoTo("review.history");
  } else if (key === "promptLibrary") {
    onGoTo("review.reuse");
  } else if (key === "assets") {
    onGoTo("review.assets");
  }
}

// E-04: Admin 영역 AppShell의 사이드바 1차 메뉴(adminRoles/adminUsers/adminCatalog/
// adminWorkflows/adminSandbox)도 GENERATE 영역과 같은 방식으로 한 곳에서 매핑한다.
// E-04가 끝나면서 모든 그룹이 신규 화면으로 이관됐다. E-06: admin.console(구버전
// AdminConsoleModal)이 제거되며 더 이상 폴백 대상이 아니라, 알 수 없는 key는 3b
// (역할 & 권한)로 보낸다. A-04: adminAuditLog(감사 로그)도 같은 방식으로 추가했다.
export function shellNavigateAdmin(key: string, onGoTo: (route: StudioRoute) => void) {
  if (key === "adminCatalog") {
    onGoTo("admin.catalogHierarchy");
  } else if (key === "adminStatus") {
    onGoTo("admin.status");
  } else if (key === "adminMetadata") {
    onGoTo("admin.metadata");
  } else if (key === "adminSandbox") {
    onGoTo("admin.sandbox");
  } else if (key === "adminRoles") {
    onGoTo("admin.roles");
  } else if (key === "adminUsers") {
    onGoTo("admin.users");
  } else if (key === "adminWorkflows") {
    onGoTo("admin.workflows");
  } else if (key === "adminAuditLog") {
    onGoTo("admin.auditLog");
  } else {
    onGoTo("admin.roles");
  }
}
