from pathlib import Path


SOURCE = Path("frontend/src/screens/adminScreens.tsx")
STYLES = Path("frontend/src/styles.css")


def _function(name: str, next_name: str) -> str:
    source = SOURCE.read_text(encoding="utf-8")
    return source.split(f"export function {name}", 1)[1].split(f"export function {next_name}", 1)[0]


def test_role_selector_is_above_role_detail_in_main_content() -> None:
    screen = _function("Create3bScreen", "Create7bScreen")

    assert "sidebarExtra=" not in screen
    assert 'className="v3-admin-selector-card"' in screen
    assert 'className={`v3-admin-selector-button ${selectedRole?.code === role.code ? "is-active" : ""}`}' in screen
    assert screen.index("v3-admin-selector-card") < screen.index("v3-card")


def test_workflow_selector_is_above_workflow_detail_in_main_content() -> None:
    screen = _function("Create4aScreen", "Create4dScreen")

    assert "sidebarExtra=" not in screen
    assert 'className="v3-admin-selector-card is-workflows"' in screen
    assert 'className={`v3-admin-selector-button ${selectedWorkflowId === item.id ? "is-active" : ""}`}' in screen
    assert screen.index("v3-admin-selector-card") < screen.index("워크플로 상세")


def test_admin_selector_layout_is_responsive() -> None:
    styles = STYLES.read_text(encoding="utf-8")

    assert ".v3-admin-selector-card" in styles
    assert ".v3-admin-selector-grid" in styles
    assert ".v3-admin-selector-button.is-active" in styles
    assert "repeat(auto-fit, minmax(" in styles
