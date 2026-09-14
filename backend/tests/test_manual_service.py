from __future__ import annotations

from backend.app.services.manual_service import (
    inline_markdown,
    render_manual_callout,
    render_manual_markdown,
)


def test_inline_markdown_renders_color_emphasis_mark() -> None:
    assert inline_markdown("==중요 공지==") == '<mark class="manual-emphasis">중요 공지</mark>'


def test_inline_markdown_still_supports_bold_and_code() -> None:
    assert inline_markdown("**굵게** `코드`") == "<strong>굵게</strong> <code>코드</code>"


def test_render_manual_callout_known_type_uses_label_and_title() -> None:
    html = render_manual_callout("warning", "Network Volume 삭제", ["되돌릴 수 없습니다."])
    assert 'class="manual-callout is-warning"' in html
    assert "주의 · Network Volume 삭제" in html
    assert "<p>되돌릴 수 없습니다.</p>" in html


def test_render_manual_callout_without_title_omits_separator() -> None:
    html = render_manual_callout("info", "", ["본문"])
    assert '<p class="manual-callout-title">안내</p>' in html


def test_render_manual_callout_unknown_type_falls_back_to_info() -> None:
    html = render_manual_callout("bogus", "", ["본문"])
    assert 'class="manual-callout is-info"' in html


def test_render_manual_callout_renders_bullet_list() -> None:
    html = render_manual_callout("danger", "", ["- 첫째", "- 둘째"])
    assert "<ul><li>첫째</li><li>둘째</li></ul>" in html


def test_render_manual_markdown_parses_callout_block() -> None:
    markdown = "\n".join(
        [
            ":::warning 제목",
            "본문 문단",
            "- 항목1",
            ":::",
            "",
            "다음 문단",
        ]
    )
    html = render_manual_markdown(markdown)
    assert '<div class="manual-callout is-warning">' in html
    assert "<p>본문 문단</p>" in html
    assert "<li>항목1</li>" in html
    assert "<p>다음 문단</p>" in html


def test_render_manual_markdown_inline_emphasis_inside_paragraph() -> None:
    html = render_manual_markdown("일반 문단 ==강조==입니다.")
    assert '<mark class="manual-emphasis">강조</mark>' in html
