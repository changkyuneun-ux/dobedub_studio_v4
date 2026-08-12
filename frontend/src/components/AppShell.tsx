import React from "react";
import { User, canUse } from "../auth";
import { HealthResponse } from "../api/client";
import { StudioRoute } from "../router";
import { serviceStatusLabel, qwenStatusLabel } from "../helpers/format";
import { canUseAdminConsole } from "../helpers/adminForms";

// 구버전 상단 TopBar(브랜드 + 네비 메뉴 + 서비스 상태 + 유저/로그아웃)를 제거하면서,
// 그중 사이드바 나열 메뉴와 중복되지 않는 것들(서비스 상태·유저/로그아웃·영역 전환·
// Manual/Status/Metadata 접근)을 AppShell 사이드바로 옮긴다. 22개 화면 호출부를 모두
// 고치지 않도록, App(main.tsx)이 이 값을 Context로 한 번만 내려준다.
export type AppShellChrome = {
  health: HealthResponse | null;
  healthError: string;
  onLogout: () => void;
  onNavigateRoute: (route: StudioRoute) => void;
};

export const AppShellChromeContext = React.createContext<AppShellChrome | null>(null);

// E-01: 공통 레이아웃 컴포넌트. design_handoff_dobedub_v3의 모든 화면(2a~7c)이
// 공유하는 골격 — 사이드바 212px + 헤더 + 본문 그리드 + 우측 패널(선택) — 을 화면마다
// 새로 짜지 않고 이 컴포넌트 하나가 그린다. README "공통 골격은... 레이아웃
// 컴포넌트로 한 번 만들어 전 화면이 공유하게 하십시오" 지시를 따른다.
//
// 화면 자체(2a~2f, 3a~3f, 4a~7c)는 아직 이 컴포넌트를 사용하지 않는다(E-02~E-05에서
// 순서대로 이관). 지금은 신규 화면을 지을 때 쓸 재사용 가능한 뼈대만 갖춘 상태다.
//
// 사이드바 상단 고정 메뉴는 두 가지 영역(area)으로 나뉜다 - design_handoff의
// "2 Create.dc.html" "3 Review.dc.html"은 GENERATE 영역(Workspace / Prompt Library /
// Task History / Assets)을, "4 Admin.dc.html"은 ADMIN 영역(역할 & 권한 / 사용자 /
// 프롬프트 카탈로그 / 워크플로 정의 / Sandbox Pod / 감사 로그)을 공통으로 반복한다.
// 각 화면이 다르게 그리는 부분(스텝 트래커, 필터, 카탈로그 트리 등)은 sidebarExtra로,
// 화면 하단 고정 정보(서비스 상태, 보관 기한 안내 등)는 sidebarFooter로 화면이 채운다.
//
// 권한이 없는 메뉴 항목은 숨긴다(README "권한이 없는 메뉴는 사이드바에서 숨깁니다").
// 권한은 있으나 기능이 아직 없는 항목은 숨기지 않고 `미구현` 배지와 함께 비활성
// 상태로 보여준다(design_handoff의 표시 방식과 동일) - "감사 로그"는 A-04에서
// 구현이 끝나 더 이상 이 처리 대상이 아니다.

export type AppShellArea = "generate" | "admin";

type NavItem = {
  key: string;
  label: string;
  /** 없으면 항상 노출(예: Workspace) */
  permission?: string;
  /** 권한은 있지만 백엔드 기능이 아직 없는 항목 - 숨기지 않고 배지와 함께 비활성 처리 */
  unimplemented?: boolean;
};

// GENERATE 영역: design_handoff "2 Create.dc.html" / "3 Review.dc.html" 사이드바 공통 상단.
// 2026-08-11: Task History를 Prompt Library보다 위로 이동(사용자 요청) - 작업
// 이력 확인이 더 빈번한 진입점이라는 판단.
const GENERATE_NAV_ITEMS: NavItem[] = [
  { key: "workspace", label: "Workspace" },
  { key: "taskHistory", label: "Task History", permission: "history:read" },
  { key: "promptLibrary", label: "Prompt Library", permission: "prompts:reuse" },
  // 2026-08-11: 사용자 요청으로 Assets(5a)·Collections(5c)를 "Asset 관리" 한
  // 화면으로 통합 - 사이드바 메뉴도 Assets 하나로 줄었다(컬렉션은 그 화면
  // 안의 필터로 이동).
  { key: "assets", label: "Assets", permission: "history:read" }
];

// ADMIN 영역: design_handoff "4 Admin.dc.html" 사이드바 공통 상단.
// 2026-08-12: adminStatus(6c)·adminMetadata(6d)는 design_handoff에서도 원래 이
// 6항목 사이드바가 아니라 별도 상단 nav(HELP) 소속이었다(README/Screen Map).
// AppShell이 area를 generate/admin 두 가지만 지원하던 시절엔 임시로 ADMIN 영역에
// 편입했었지만, 그 결과 스튜디오 HELP 메뉴에서 System Status/Metadata를 눌러도
// 화면이 통째로 ADMIN 콘솔 쉘(전체 ADMIN 메뉴 + "← 스튜디오" 전환 버튼)로 바뀌는
// 혼란스러운 현상이 있었다(사용자 리포트) - 두 항목을 여기서 제거하고 Create6c/
// 6dScreen을 area="generate"로 되돌려 design_handoff 원래 소속(HELP 그룹, 아래
// helpItems)으로 되돌린다. 화면 자체의 내용·권한은 변경 없음.
const ADMIN_NAV_ITEMS: NavItem[] = [
  { key: "adminRoles", label: "역할 & 권한", permission: "roles:read" },
  { key: "adminUsers", label: "사용자", permission: "users:read" },
  { key: "adminCatalog", label: "프롬프트 카탈로그", permission: "prompt-catalog:read" },
  { key: "adminWorkflows", label: "워크플로 정의", permission: "workflows:read" },
  { key: "adminSandbox", label: "Sandbox Pod", permission: "sandbox:read" },
  { key: "adminAuditLog", label: "감사 로그", permission: "roles:read" }
];

export type AppShellProps = {
  user: User | null;
  area: AppShellArea;
  /** 현재 활성화된 1차 메뉴 key (GENERATE_NAV_ITEMS/ADMIN_NAV_ITEMS의 key) */
  activeItem: string;
  /** 1차 메뉴 클릭 시 호출. 실제 라우팅 연결은 화면 이관 시점(E-02+)에 결정 */
  onNavigate: (key: string) => void;
  headerEyebrow?: React.ReactNode;
  headerTitle: React.ReactNode;
  headerActions?: React.ReactNode;
  /** 사이드바 1차 메뉴 아래, 화면별 보조 영역(스텝 트래커 · 필터 · 카탈로그 트리 등) */
  sidebarExtra?: React.ReactNode;
  /** 사이드바 최하단 고정 영역(서비스 상태 · 보관 기한 안내 등) */
  sidebarFooter?: React.ReactNode;
  /** 우측 340px 패널(Run Summary 등). 생략하면 본문이 전체 폭을 차지 */
  rightPanel?: React.ReactNode;
  children: React.ReactNode;
};

export function AppShell({
  user,
  area,
  activeItem,
  onNavigate,
  headerEyebrow,
  headerTitle,
  headerActions,
  sidebarExtra,
  sidebarFooter,
  rightPanel,
  children
}: AppShellProps) {
  const navItems = area === "admin" ? ADMIN_NAV_ITEMS : GENERATE_NAV_ITEMS;
  const groupLabel = area === "admin" ? "ADMIN" : "GENERATE";
  const visibleNavItems = navItems.filter((item) => !item.permission || canUse(user, item.permission));
  const chrome = React.useContext(AppShellChromeContext);

  // HELP 그룹: design_handoff 6b의 사이드바가 GENERATE 그룹 아래 두는 HELP 묶음
  // (User Manual / System Status / Metadata). 구버전 TopBar가 담당하던 접근을 이관.
  const helpItems: { route: StudioRoute; label: string; permission: string }[] = [
    { route: "access.manual", label: "User Manual", permission: "manual:read" },
    { route: "admin.status", label: "System Status", permission: "system:read" },
    { route: "admin.metadata", label: "Metadata", permission: "metadata:read" },
  ];
  const visibleHelpItems = helpItems.filter((item) => canUse(user, item.permission));

  const system = chrome?.health?.system || chrome?.health?.legacy;
  const comfyStatus = serviceStatusLabel(Boolean(system?.runpod?.configured), chrome?.healthError || "", system?.dryRun ? "DRY-RUN" : undefined);
  const qwenStatus = qwenStatusLabel(system?.promptLlm, chrome?.healthError || "");

  return (
    <div className="v3-shell">
      <nav className="v3-sidebar" aria-label="주 메뉴">
        <div className="v3-sidebar-brand">
          <img className="v3-sidebar-brand-mark" src="/studio/favicon.png" alt="" aria-hidden="true" />
          <div className="v3-sidebar-brand-name">DOBEDUB</div>
        </div>

        {/* 2026-08-12: 사용자 요청 - 관리자 콘솔/스튜디오 전환 버튼이 사이드바
            최하단(서비스 상태 아래)에 묻혀 있어 눈에 잘 안 띄었다. 로고 바로
            아래·GENERATE/ADMIN 메뉴 라벨 바로 위로 옮겨 영역 전환이라는 중요한
            동작을 더 눈에 띄게 한다. */}
        {chrome && area === "generate" && canUseAdminConsole(user) ? (
          <div className="v3-sidebar-switch-top">
            <button className="v3-sidebar-switch" type="button" onClick={() => chrome.onNavigateRoute("admin.roles")}>관리자 콘솔 →</button>
          </div>
        ) : null}
        {chrome && area === "admin" ? (
          <div className="v3-sidebar-switch-top">
            <button className="v3-sidebar-switch" type="button" onClick={() => chrome.onNavigateRoute("create.load")}>← 스튜디오</button>
          </div>
        ) : null}

        <div className="v3-sidebar-group-label">{groupLabel}</div>
        <div className="v3-sidebar-nav">
          {visibleNavItems.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`v3-sidebar-nav-item${item.key === activeItem ? " is-active" : ""}`}
              disabled={item.unimplemented}
              aria-current={item.key === activeItem ? "page" : undefined}
              onClick={() => {
                if (!item.unimplemented) {
                  onNavigate(item.key);
                }
              }}
            >
              <span>{item.label}</span>
              {item.unimplemented ? <span className="v3-sidebar-nav-item-badge">미구현</span> : null}
            </button>
          ))}
        </div>

        {/* HELP 그룹(GENERATE 영역에서만). ADMIN 영역은 자체 nav에 Status/Metadata를 이미 둔다. */}
        {area === "generate" && chrome && visibleHelpItems.length ? (
          <>
            <div className="v3-sidebar-group-label">HELP</div>
            <div className="v3-sidebar-nav">
              {visibleHelpItems.map((item) => (
                <button
                  key={item.route}
                  type="button"
                  className="v3-sidebar-nav-item"
                  onClick={() => chrome.onNavigateRoute(item.route)}
                >
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          </>
        ) : null}

        {sidebarExtra ? <div className="v3-sidebar-extra">{sidebarExtra}</div> : null}
        {sidebarFooter ? <div className="v3-sidebar-footer">{sidebarFooter}</div> : null}

        {/* 계정·상태 블록: 구버전 TopBar의 서비스 상태 + 유저/로그아웃 + 영역 전환을 이관.
            사이드바 최하단에 고정한다. */}
        {chrome ? (
          <div className="v3-sidebar-account">
            <div className="v3-sidebar-status">
              <span className={`v3-status-dot is-${comfyStatus.toLowerCase()}`} aria-hidden="true" />ComfyUI · {comfyStatus}
            </div>
            <div className="v3-sidebar-status">
              <span className={`v3-status-dot is-${qwenStatus.toLowerCase()}`} aria-hidden="true" />Qwen · {qwenStatus}
            </div>
            <div className="v3-sidebar-user">
              <span className="v3-sidebar-user-name">{user?.name || user?.id}<span className="v3-sidebar-user-role">{user?.role || ""}</span></span>
              <button className="v3-sidebar-logout" type="button" onClick={chrome.onLogout}>로그아웃</button>
            </div>
          </div>
        ) : null}
      </nav>

      <div className="v3-main">
        <header className="v3-header">
          <div>
            {headerEyebrow ? <div className="v3-header-eyebrow">{headerEyebrow}</div> : null}
            <div className="v3-header-title">{headerTitle}</div>
          </div>
          {headerActions ? <div className="v3-header-actions">{headerActions}</div> : null}
        </header>

        <div className={`v3-body${rightPanel ? " has-right-panel" : ""}`}>
          <div className="v3-content">{children}</div>
          {rightPanel ? <aside className="v3-right-panel">{rightPanel}</aside> : null}
        </div>
      </div>
    </div>
  );
}
