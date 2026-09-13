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
    assert 'onNavigateRoute("admin.dashboard")}>관리자 콘솔 →' in APP_SHELL
    assert 'onNavigateRoute("home.dashboard")}>← 스튜디오' in APP_SHELL
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
    assert '"/api/dashboard/summary?range=' in CLIENT.replace("`", '"')
    assert "export type DashboardSummary" in CLIENT
    assert 'export type DashboardRange = "today" | "7d" | "30d"' in CLIENT


def test_screen_blocks_and_refresh_policy():
    for marker in ("v3-dash-tiles", "v3-dash-kpi", "v3-dash-recent", "v3-dash-alerts", "REFRESH_INTERVAL_MS = 60_000", "document.hidden", "dobedub.dashboard.range"):
        assert marker in SCREEN, marker
    # 실패 시 마지막 성공 값 유지 — 오류는 헤더 배지로만
    assert "갱신 실패" in SCREEN
    for class_name in (".v3-dash-tiles", ".v3-dash-kpi-grid", ".v3-dash-table", ".v3-dash-alerts", ".v3-dash-bar"):
        assert class_name in STYLES, class_name
