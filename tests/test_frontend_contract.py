import os
import re
import shutil
import subprocess
import textwrap

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _frontend_html():
    with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as source:
        return source.read()


def _mobile_css(html):
    style = re.search(r"<style>([\s\S]*?)</style>", html)
    assert style, "frontend stylesheet is missing"
    css = re.sub(r"\s+", "", style.group(1))
    marker = "@media(max-width:720px)"
    assert marker in css, "frontend must define an explicit 720px mobile breakpoint"

    opening = css.index("{", css.index(marker))
    depth = 0
    for offset in range(opening, len(css)):
        if css[offset] == "{":
            depth += 1
        elif css[offset] == "}":
            depth -= 1
            if depth == 0:
                return css[opening + 1:offset]
    raise AssertionError("mobile breakpoint is not closed")


def test_transform_live_accepts_pipeline_briefing_bullets():
    node = shutil.which("node")
    if not node:
        pytest.skip("node unavailable")
    script = textwrap.dedent(r"""
        const fs = require('fs');
        const html = fs.readFileSync('index.html', 'utf8');
        const m = html.match(/<script type="text\/x-dc"[\s\S]*?>([\s\S]*?)<\/script>/);
        if (!m) throw new Error('component script not found');
        globalThis.DCLogic = class {};
        eval(m[1] + '\nglobalThis.__Component = Component;');
        const component = new globalThis.__Component();
        component.props = {};
        const doc = JSON.parse(fs.readFileSync('mena_data.json', 'utf8'));
        const out = component.transformLive(doc);
        if (out.meta.mainIndex !== doc.meta.main_index) throw new Error('live meta not used');
        if (!out.brief.bullets.every(b => typeof b.text === 'string' && typeof b.cat === 'string')) {
            throw new Error('brief bullets were not normalized');
        }
    """)
    subprocess.run([node, "-e", script], cwd=ROOT, check=True)


def test_overview_removes_model_badge_and_constrains_ranking_menu():
    html = _frontend_html()

    assert "v2.0.0" not in html
    assert "{{ modelLabel }}" not in html
    assert "data-ranking-menu" in html
    assert "max-height:460px" in html
    assert "overflow-y:auto" in html


def test_mobile_contract_defines_document_width_and_shrink_safeguards():
    html = _frontend_html()
    mobile_css = _mobile_css(html)

    assert re.search(r"html,body\{[^}]*max-width:100%", mobile_css)
    assert re.search(r"\.mti-shell\{[^}]*width:100%[^}]*max-width:100%", mobile_css)
    assert re.search(r"\.mti-main(?:,[^{]+)?\{[^}]*min-width:0", mobile_css)


def test_mobile_contract_exposes_semantic_layout_hooks():
    html = _frontend_html()

    for hook in (
        "mti-shell",
        "mti-header",
        "mti-header-inner",
        "mti-nav",
        "mti-main",
        "mti-overview-grid",
        "mti-dashboard-grid",
        "mti-feed-row",
    ):
        class_token = rf'class="[^"]*\b{re.escape(hook)}\b[^"]*"'
        assert re.search(class_token, html), f"missing {hook} layout hook"


def test_mobile_contract_stacks_overview_and_scales_key_typography():
    html = _frontend_html()
    mobile_css = _mobile_css(html)

    assert re.search(r"\.mti-overview-grid\{[^}]*grid-template-columns:minmax\(0,1fr\)!important", mobile_css)
    assert re.search(r"\.mti-score\{[^}]*font-size:clamp\(", mobile_css)
    assert re.search(r"\.mti-brief-headline\{[^}]*font-size:clamp\(", mobile_css)


def test_mobile_contract_uses_phone_padding_and_responsive_content_rows():
    html = _frontend_html()
    mobile_css = _mobile_css(html)

    assert re.search(r"\.mti-main\{[^}]*padding-left:16px!important[^}]*padding-right:16px!important", mobile_css)
    assert re.search(r"\.mti-dashboard-grid\{[^}]*grid-template-columns:minmax\(0,1fr\)!important", mobile_css)
    assert re.search(r"\.mti-feed-row\{[^}]*grid-template-columns:minmax\(0,1fr\)!important", mobile_css)
