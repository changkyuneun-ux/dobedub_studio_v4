"""Source contract for the login landing dashboard (spec 2026-09-13-dashboard-landing-design.md).

Global policy: the dashboard is visible to every signed-in user — no permission
code anywhere on the route, the sidebar item, or the API.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONT = ROOT / "frontend" / "src"
ROUTER = (FRONT / "router.ts").read_text(encoding="utf-8")
MAIN = (FRONT / "main.tsx").read_text(encoding="utf-8")
SHELL = (FRONT / "StudioShell.tsx").read_text(encoding="utf-8")
APP_SHELL = (FRONT / "components" / "AppShell.tsx").read_text(encoding="utf-8")
NAVIGATION = (FRONT / "helpers" / "navigation.ts").read_text(encoding="utf-8")
CLIENT = (FRONT / "api" / "client.ts").read_text(encoding="utf-8")
SCREEN = (FRONT / "screens" / "dashboardScreen.tsx").read_text(encoding="utf-8")
STYLES = (FRONT / "styles.css").read_text(encoding="utf-8")


def test_route_exists_and_is_the_login_landing():
    assert '| "home.dashboard"' in ROUTER
    assert '"home.dashboard": "/studio/home"' in ROUTER
    assert 'studio: "home.dashboard"' in ROUTER
    assert 'return "home.dashboard";' in ROUTER
    assert 'navigate("home.dashboard");' in MAIN
    assert 'navigate("create.load");' not in MAIN


def test_route_has_no_permission_guard_and_a_title():
    guard = SHELL.split("ROUTE_REQUIRED_PERMISSION", 1)[1].split("};", 1)[0]
    assert "home.dashboard" not in guard and "admin.dashboard" not in guard
    assert '"home.dashboard": "대시보드"' in SHELL and '"admin.dashboard": "대시보드"' in SHELL
    assert 'route === "home.dashboard"' in SHELL and "<DashboardScreen" in SHELL
    assert 'route === "admin.dashboard"' in SHELL and 'area="admin"' in SHELL


def test_area_switch_buttons_default_to_dashboard():
    # 2026-09-13: 스튜디오 ↔ 관리자 콘솔 전환의 기본 도착지는 항상 대시보드
    assert '| "admin.dashboard"' in ROUTER and '"admin.dashboard": "/studio/admin/home"' in ROUTER
    admin_switch = APP_SHELL.split('className="v3-sidebar-switch is-to-admin"', 1)[1].split("</button>", 1)[0]
    assert 'onNavigateRoute("admin.dashboard")' in admin_switch and "관리자 콘솔" in admin_switch
    home_switch = APP_SHELL.split('className="v3-sidebar-switch is-to-home"', 1)[1].split("</button>", 1)[0]
    assert 'onNavigateRoute("home.dashboard")' in home_switch and "스튜디오" in home_switch
    assert 'onNavigateRoute("admin.roles")' not in APP_SHELL and 'onNavigateRoute("create.load")' not in APP_SHELL
    admin_nav = NAVIGATION.split("export function shellNavigateAdmin(", 1)[1]
    assert 'onGoTo("admin.dashboard")' in admin_nav
    assert 'area === "admin" ? shellNavigateAdmin' in SCREEN


def test_sidebar_home_group_is_global_and_on_every_area():
    home = APP_SHELL.split("const HOME_NAV_ITEMS", 1)[1].split("];", 1)[0]
    assert 'label: "대시보드"' in home
    assert "permission" not in home
    assert APP_SHELL.count('{ label: "HOME", items: HOME_NAV_ITEMS }') == 2  # admin + non-admin branches
    assert 'key === "dashboard"' in NAVIGATION.split("export function shellNavigate(", 1)[1].split("export function shellNavigateAdmin", 1)[0]
    assert 'key === "dashboard"' in NAVIGATION.split("export function shellNavigateAdmin(", 1)[1]


def test_client_calls_the_global_summary_api():
    # 2026-09-14: 일자별 작업량 그래프 필터(user/workflow/status)를 쿼리 파라미터로 보내기 위해
    # 템플릿 리터럴 대신 URLSearchParams로 바뀜 — 엔드포인트 경로만 확인한다.
    assert "/api/dashboard/summary?" in CLIENT
    assert "export type DashboardSummary" in CLIENT
    assert 'export type DashboardRange = "today" | "7d" | "30d"' in CLIENT
    assert "export type DashboardDailyVolume" in CLIENT


def test_screen_blocks_and_refresh_policy():
    for marker in ("v3-dash-tiles", "v3-dash-kpi", "v3-dash-recent", "v3-dash-alerts", "REFRESH_INTERVAL_MS = 60_000", "document.hidden", "dobedub.dashboard.range"):
        assert marker in SCREEN, marker
    # 실패 시 마지막 성공 값 유지 — 오류는 헤더 배지로만
    assert "갱신 실패" in SCREEN
    for class_name in (".v3-dash-tiles", ".v3-dash-kpi-grid", ".v3-dash-table", ".v3-dash-alerts", ".v3-dash-bar"):
        assert class_name in STYLES, class_name


def test_duration_cost_table_has_ten_row_pagination():
    # 화면에 30일 범위가 표시될 때 컷 길이별 비용 일자 테이블이 길게 늘어나면
    # 카드 하단 비교/각주 확인이 어려워진다. 페이지 크기 변경이나 페이지 slice
    # 누락은 운영 대시보드에서 즉시 회귀이므로 소스 계약으로 보호한다.
    assert "DURATION_COST_PAGE_SIZE = 10" in SCREEN
    assert "durationCostPage" in SCREEN
    assert "durationCostPageCount" in SCREEN
    assert "paginatedDays" in SCREEN
    assert "days.slice(durationCostPageStartIndex, durationCostPageStartIndex + DURATION_COST_PAGE_SIZE)" in SCREEN
    assert "10건 / 페이지" in SCREEN
    assert "v3-dash-duration-pagination" in SCREEN
    assert ".v3-dash-duration-pagination" in STYLES


def test_duration_cost_table_separates_utc_and_kst_counts_from_utc_costs():
    assert "제출(UTC)" in SCREEN
    assert "완료(UTC)" in SCREEN
    assert "실패(UTC)" in SCREEN
    assert "제출(KST)" in SCREEN
    assert "완료(KST)" in SCREEN
    assert "실패(KST)" in SCREEN
    assert "row.kst.submitted" in SCREEN
    assert "row.kst.completed" in SCREEN
    assert "row.kst.failed" in SCREEN
    assert "비용은 RunPod 청구 기준(UTC 캘린더일)" in SCREEN
    assert "kst: DurationCostCount" in CLIENT
