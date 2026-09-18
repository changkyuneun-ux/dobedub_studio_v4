import React from "react";
import { User, canUse } from "../auth";
import { HealthResponse } from "../api/client";
import { StudioRoute } from "../router";
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
// "2 Create.dc.html" "3 Review.dc.html"은 GENERATE 영역(작업 이력 /
// Batch 처리 / 단위 작업 / Collection 관리)을, "4 Admin.dc.html"은 ADMIN 영역(역할 & 권한 / 사용자 /
// 프롬프트 카탈로그 / 워크플로 정의 / Sandbox Pod / 감사 로그)을 공통으로 반복한다.
// 각 화면이 다르게 그리는 부분(스텝 트래커, 필터, 카탈로그 트리 등)은 sidebarExtra로,
// 화면 하단 고정 정보(서비스 상태, 보관 기한 안내 등)는 sidebarFooter로 화면이 채운다.
//
// 권한이 없는 메뉴 항목은 숨긴다(README "권한이 없는 메뉴는 사이드바에서 숨깁니다").
// 권한은 있으나 기능이 아직 없는 항목은 숨기지 않고 `미구현` 배지와 함께 비활성
// 상태로 보여준다(design_handoff의 표시 방식과 동일) - "감사 로그"는 A-04에서
// 구현이 끝나 더 이상 이 처리 대상이 아니다.

export type AppShellArea = "local" | "generate" | "admin";

type NavItem = {
  key: string;
  label: string;
  /** 없으면 항상 노출(예: Workspace) */
  permission?: string;
  permissions?: string[];
  /** 권한은 있지만 백엔드 기능이 아직 없는 항목 - 숨기지 않고 배지와 함께 비활성 처리 */
  unimplemented?: boolean;
};

// GENERATE 영역: design_handoff "2 Create.dc.html" / "3 Review.dc.html" 사이드바 공통 상단.
const GENERATE_NAV_ITEMS: NavItem[] = [
  { key: "taskHistory", label: "작업 이력", permission: "history:read" },
  { key: "batchJobs", label: "Batch 처리" },
  { key: "promptManagement", label: "Grok 프롬프트 생성", permission: "prompts:build" },
  { key: "runpodRequests", label: "Runpod ComfyUI 요청", permission: "jobs:run" },
  // 2026-08-11: 사용자 요청으로 Assets(5a)·Collections(5c)를 "컬렉션 관리" 한
  // 화면으로 통합 - 사이드바 메뉴도 컬렉션 관리 하나로 줄었다(컬렉션은 그 화면
  // 안의 필터로 이동).
  { key: "assets", label: "Collection 관리", permission: "history:read" }
];

// 2026-09-13: 로그인 랜딩 대시보드. 전역 정책 — permission 없음(로그인한 모든 사용자에게
// 표시)이며 local/generate/admin 모든 영역에서 최상단 HOME 그룹으로 그린다.
const HOME_NAV_ITEMS: NavItem[] = [
  { key: "dashboard", label: "대시보드" }
];

const LOCAL_NAV_ITEMS: NavItem[] = [
  { key: "webtoonCutSplit", label: "컷 분할 처리", permission: "jobs:run" },
  { key: "webtoonCutHistory", label: "컷 분할 이력", permission: "jobs:run" }
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
// 2026-09-13: 사용자 요청으로 순서 재정렬(운영 빈도순: Sandbox Pod → 워크플로 → 프롬프트 →
// 사용자/권한 → Runpod Worker 설정 → 감사 로그). "Task Policy"는 "Runpod Worker 설정"으로
// 라벨만 변경(route key·권한·화면 내용은 동일).
const ADMIN_NAV_ITEMS: NavItem[] = [
  { key: "adminSandbox", label: "Sandbox Pod", permission: "sandbox:read" },
  { key: "adminWorkflows", label: "워크플로 정의", permission: "workflows:read" },
  { key: "adminGrokInstructions", label: "프롬프트 지시 관리", permission: "prompt-catalog:read" },
  { key: "adminCatalog", label: "프롬프트 카탈로그", permission: "prompt-catalog:read" },
  { key: "adminUsers", label: "사용자", permission: "users:read" },
  { key: "adminRoles", label: "역할 & 권한", permission: "roles:read" },
  { key: "adminTaskPolicy", label: "Runpod Worker 설정", permission: "roles:read" },
  { key: "adminAuditLog", label: "감사 로그", permission: "roles:read" }
];

// 2026-09-13 작업자 식별성 UI 지침 §2·§3: 영역 컬러 + 메뉴 아이콘. 색은 영역 식별에만 쓰고
// 상태 표현에는 쓰지 않는다. 아이콘은 메뉴 key 1개당 1개로 영구 고정(선 아이콘, stroke 1.6).
// 가드레일: NavItem.key · permission · route는 변경하지 않는다(표현 계층만).
export type AppShellAreaKey = "home" | "local" | "generate" | "admin";

export const AREA_META: Record<AppShellAreaKey, { label: string; description: string }> = {
  home: { label: "HOME", description: "시스템 상태 · 작업 현황" },
  local: { label: "IMAGE CUT", description: "S3 업로드 · 서버 컷 분리 · 로컬 다운로드" },
  generate: { label: "GENERATE", description: "영상 생성 · 검수 작업 영역" },
  admin: { label: "ADMIN", description: "권한 · 워크플로 · 인프라 운영" }
};

const GROUP_AREA: Record<string, AppShellAreaKey | null> = { HOME: "home", LOCAL: "local", "이미지 컷 관리": "local", GENERATE: "generate", ADMIN: "admin", HELP: null };

function NavIcon({ name }: { name: string }) {
  const common = { width: 15, height: 15, viewBox: "0 0 14 14", fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
  switch (name) {
    case "dashboard": return <svg {...common}><path d="M2 6.6 7 2.4l5 4.2" /><path d="M3.4 7.6v4h7.2v-4" /></svg>;
    case "webtoonCuts":
    case "webtoonCutSplit":
    case "webtoonCutHistory": return <svg {...common}><rect x="1.8" y="1.8" width="10.4" height="10.4" rx="2" /><line x1="7" y1="2" x2="7" y2="12" strokeDasharray="2 2" /></svg>;
    case "taskHistory": return <svg {...common}><line x1="2" y1="3.2" x2="12" y2="3.2" /><line x1="2" y1="7" x2="12" y2="7" /><line x1="2" y1="10.8" x2="8.4" y2="10.8" /></svg>;
    case "batchJobs": return <svg {...common}><rect x="1.6" y="1.6" width="5" height="5" rx="1" /><rect x="7.6" y="1.6" width="5" height="5" rx="1" /><rect x="1.6" y="7.6" width="5" height="5" rx="1" /><rect x="7.6" y="7.6" width="5" height="5" rx="1" /></svg>;
    case "promptManagement": return <svg {...common}><rect x="1.8" y="2.4" width="10.4" height="8" rx="2" /><line x1="4.2" y1="5.4" x2="9.8" y2="5.4" /><line x1="4.2" y1="7.8" x2="7.6" y2="7.8" /></svg>;
    case "runpodRequests": return <svg {...common}><circle cx="7" cy="7" r="5.2" /><path d="M5.8 4.8 9.6 7l-3.8 2.2z" fill="currentColor" stroke="none" /></svg>;
    case "assets": return <svg {...common}><rect x="1.8" y="4.4" width="10.4" height="7.4" rx="1.6" /><line x1="3.8" y1="2.2" x2="10.2" y2="2.2" /></svg>;
    case "adminSandbox": return <svg {...common}><rect x="1.8" y="3" width="10.4" height="8" rx="1.6" /><line x1="4.4" y1="6" x2="6.4" y2="6" /><line x1="4.4" y1="8.2" x2="8.4" y2="8.2" /></svg>;
    case "adminWorkflows": return <svg {...common}><circle cx="3.2" cy="7" r="1.6" /><circle cx="10.8" cy="3.4" r="1.6" /><circle cx="10.8" cy="10.6" r="1.6" /><path d="M4.7 6.3 9.3 4M4.7 7.7l4.6 2.3" /></svg>;
    case "adminGrokInstructions": return <svg {...common}><path d="M2.4 2.4h9.2v6.4H6.2L3.6 11V8.8H2.4z" /></svg>;
    case "adminCatalog": return <svg {...common}><path d="M2.2 2.6h4.4v9H2.2zM7.4 2.6h4.4v9H7.4z" /></svg>;
    case "adminUsers": return <svg {...common}><circle cx="7" cy="4.6" r="2.4" /><path d="M2.6 12c.6-2.6 2.2-3.8 4.4-3.8s3.8 1.2 4.4 3.8" /></svg>;
    case "adminRoles": return <svg {...common}><path d="M7 1.8 11.6 3.6v3.2c0 2.8-1.9 4.6-4.6 5.6C4.3 11.4 2.4 9.6 2.4 6.8V3.6z" /></svg>;
    case "adminTaskPolicy": return <svg {...common}><circle cx="7" cy="7" r="2" /><path d="M7 1.8v1.6M7 10.6v1.6M1.8 7h1.6M10.6 7h1.6M3.3 3.3l1.2 1.2M9.5 9.5l1.2 1.2M3.3 10.7l1.2-1.2M9.5 4.5l1.2-1.2" /></svg>;
    case "adminAuditLog": return <svg {...common}><path d="M3 1.8h5.4L11 4.4v7.8H3z" /><line x1="4.8" y1="6.6" x2="9.2" y2="6.6" /><line x1="4.8" y1="9" x2="8" y2="9" /></svg>;
    case "help.manual": return <svg {...common}><path d="M2.2 2.6h4.8v8.8H2.2z" /><path d="M7 2.6h4.8v8.8H7z" /></svg>;
    case "help.meta": return <svg {...common}><circle cx="7" cy="7" r="5.2" /><line x1="2" y1="7" x2="12" y2="7" /></svg>;
    default: return <svg {...common}><circle cx="7" cy="7" r="2" /></svg>;
  }
}

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
  const navGroups = area === "admin"
    ? [{ label: "HOME", items: HOME_NAV_ITEMS }, { label: "ADMIN", items: ADMIN_NAV_ITEMS }]
    : [
      { label: "HOME", items: HOME_NAV_ITEMS },
      { label: "이미지 컷 관리", items: LOCAL_NAV_ITEMS },
      { label: "GENERATE", items: GENERATE_NAV_ITEMS }
    ];
  const visibleNavGroups = navGroups.map((group) => ({
    ...group,
    items: group.items.filter((item) => {
    if (item.permissions?.length) {
      return item.permissions.every((permission) => canUse(user, permission));
    }
    return !item.permission || canUse(user, item.permission);
    })
  })).filter((group) => group.items.length);
  const chrome = React.useContext(AppShellChromeContext);

  // HELP 그룹: design_handoff 6b의 사이드바가 GENERATE 그룹 아래 두는 HELP 묶음
  // (User Manual / System Status / Metadata). 구버전 TopBar가 담당하던 접근을 이관.
  // 2026-09-13: System Status는 사용자 요청으로 HELP 그룹에서 제거(라우트 admin.status 자체는 유지).
  const helpItems: { route: StudioRoute; label: string; permission: string }[] = [
    { route: "access.manual", label: "User Manual", permission: "manual:read" },
    { route: "admin.metadata", label: "Metadata", permission: "metadata:read" },
  ];
  const visibleHelpItems = helpItems.filter((item) => canUse(user, item.permission));

  // 현재 영역: HOME(대시보드)은 generate/admin 쉘 안의 그룹이므로 activeItem으로 판정한다.
  const currentArea: AppShellAreaKey = activeItem === "dashboard" ? "home" : area;
  const areaMeta = AREA_META[currentArea];

  return (
    <div className={`v3-shell is-area-${currentArea}`}>
      <nav className="v3-sidebar" aria-label="주 메뉴">
        <span className="v3-sidebar-rail" aria-hidden="true" />
        <div className="v3-sidebar-brand">
          <img className="v3-sidebar-brand-mark" src="/studio/favicon.png" alt="" aria-hidden="true" />
          <div className="v3-sidebar-brand-name">DOBEDUB</div>
        </div>

        {/* 2026-08-12: 사용자 요청 - 관리자 콘솔/스튜디오 전환 버튼이 사이드바
            최하단(서비스 상태 아래)에 묻혀 있어 눈에 잘 안 띄었다. 로고 바로
            아래·GENERATE/ADMIN 메뉴 라벨 바로 위로 옮겨 영역 전환이라는 중요한
            동작을 더 눈에 띄게 한다. */}
        {/* 2026-09-13: area="local"(이미지 컷 분할)에서도 전환 버튼이 사라지지 않도록
            generate 한정 → admin이 아닌 모든 영역으로 완화(사용자 리포트). */}
        {visibleNavGroups.map((group) => {
          const groupArea = GROUP_AREA[group.label] ?? null;
          const isCurrentGroup = groupArea === currentArea;
          return (
            <React.Fragment key={group.label}>
              <div className={`v3-sidebar-group-label${isCurrentGroup ? ` is-current is-area-${groupArea}` : ""}`}>
                <i className="v3-sidebar-group-dot" aria-hidden="true" />{group.label}
              </div>
              <div className="v3-sidebar-nav">
                {group.items.map((item) => (
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
                    <span className="v3-sidebar-nav-icon"><NavIcon name={item.key} /></span>
                    <span className="v3-sidebar-nav-label">{item.label}</span>
                    {item.unimplemented ? <span className="v3-sidebar-nav-item-badge">미구현</span> : null}
                  </button>
                ))}
              </div>
            </React.Fragment>
          );
        })}

        {/* HELP 그룹(GENERATE 영역에서만). ADMIN 영역은 자체 nav에 Status/Metadata를 이미 둔다. */}
        {area !== "admin" && chrome && visibleHelpItems.length ? (
          <>
            <div className="v3-sidebar-group-label"><i className="v3-sidebar-group-dot" aria-hidden="true" />HELP</div>
            <div className="v3-sidebar-nav">
              {visibleHelpItems.map((item) => (
                <button
                  key={item.route}
                  type="button"
                  className="v3-sidebar-nav-item"
                  onClick={() => chrome.onNavigateRoute(item.route)}
                >
                  <span className="v3-sidebar-nav-icon"><NavIcon name={item.route === "access.manual" ? "help.manual" : "help.meta"} /></span>
                  <span className="v3-sidebar-nav-label">{item.label}</span>
                </button>
              ))}
            </div>
          </>
        ) : null}

        {sidebarExtra ? <div className="v3-sidebar-extra">{sidebarExtra}</div> : null}

        {/* 영역 전환(지침 §3): 목적지 영역 색으로 칠하고 도착지를 1줄로 안내. 도착지는 항상 대시보드. */}
        {chrome && area !== "admin" && canUseAdminConsole(user) ? (
          <div className="v3-sidebar-switch-block">
            <button className="v3-sidebar-switch is-to-admin" type="button" onClick={() => chrome.onNavigateRoute("admin.dashboard")}>
              <NavIcon name="batchJobs" /><span>관리자 콘솔</span><b>→</b>
            </button>
            <p className="v3-sidebar-switch-hint">도착: 관리자 대시보드</p>
          </div>
        ) : null}
        {chrome && area === "admin" ? (
          <div className="v3-sidebar-switch-block">
            <button className="v3-sidebar-switch is-to-home" type="button" onClick={() => chrome.onNavigateRoute("home.dashboard")}>
              <b>←</b><span>스튜디오</span><NavIcon name="dashboard" />
            </button>
            <p className="v3-sidebar-switch-hint">도착: 스튜디오 대시보드</p>
          </div>
        ) : null}
        {sidebarFooter ? <div className="v3-sidebar-footer">{sidebarFooter}</div> : null}

        {/* 계정 블록: 구버전 TopBar의 유저/로그아웃을 이관. 사이드바 최하단에 고정한다.
            2026-09-13: ComfyUI·Qwen 서비스 상태 표시는 사용자 요청으로 제거. */}
        {chrome ? (
          <div className="v3-sidebar-account">
            <div className="v3-sidebar-user">
              <span className="v3-sidebar-user-name">{user?.name || user?.id}<span className="v3-sidebar-user-role">{user?.role || ""}</span></span>
              <button className="v3-sidebar-logout" type="button" onClick={chrome.onLogout}>로그아웃</button>
            </div>
          </div>
        ) : null}
      </nav>

      <div className="v3-main">
        <span className="v3-main-rail" aria-hidden="true" />
        <header className="v3-header">
          <div>
            <div className="v3-header-crumb">
              <span className={`v3-area-badge is-area-${currentArea}`}>{areaMeta.label}</span>
              {headerEyebrow ? <><span className="v3-header-crumb-sep">/</span><span className="v3-header-eyebrow">{headerEyebrow}</span></> : null}
            </div>
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
