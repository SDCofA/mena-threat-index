import functools
import http.server
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import threading

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _frontend_html():
    with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as source:
        return source.read()


def _contrast_ratio(foreground, background):
    def luminance(color):
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            channel / 12.92
            if channel <= 0.03928
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


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


def _chrome():
    candidates = (
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    )
    return next((candidate for candidate in candidates if candidate and os.path.exists(candidate)), None)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def test_svg_sparkline_binding_emits_no_native_points_console_error():
    chrome = _chrome()
    if not chrome:
        pytest.skip("Chrome/Chromium unavailable")

    html = _frontend_html()
    sparkline = re.search(r"<polyline\b[^>]*\bc\.spark\b[^>]*>", html)
    assert sparkline, "country sparkline template is missing"
    assert 'sc-camel-points="{{ c.spark }}"' in sparkline.group(0)

    handler = functools.partial(_QuietHandler, directory=ROOT)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as profile:
            result = subprocess.run(
                [
                    chrome,
                    "--headless=new",
                    "--disable-gpu",
                    "--disable-extensions",
                    "--no-first-run",
                    f"--user-data-dir={profile}",
                    "--enable-logging=stderr",
                    "--v=0",
                    "--virtual-time-budget=12000",
                    "--dump-dom",
                    f"http://127.0.0.1:{server.server_port}/",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stderr
    assert "<polyline> attribute points:" not in result.stderr


def test_document_exposes_lighthouse_title_language_and_description():
    html = _frontend_html()

    assert re.search(r"<html\b[^>]*\blang=\"en\"", html, re.I)
    assert "<title>MENA Threat Index | SDCofA</title>" in html
    description = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', html, re.I)
    assert description
    assert len(description.group(1)) >= 50


def test_every_select_has_an_accessible_name():
    html = _frontend_html()
    selects = re.findall(r"<select\b[^>]*>", html, re.I)

    assert len(selects) == 4
    assert all(re.search(r'\baria-label="[^"]+"', select, re.I) for select in selects)


def test_muted_text_palette_meets_normal_text_contrast():
    html = _frontend_html()

    compact = re.sub(r"\s+", "", html.lower())
    assert '[style*="color:#6b6457"],[style*="color:#7d7565"]{color:#9a9284!important}' in compact
    assert 'svgtext[fill="#6b6457"],svgtext[fill="#7d7565"]{fill:#9a9284!important}' in compact
    assert "input::placeholder{color:#9a9284}" in compact
    assert _contrast_ratio("#9a9284", "#1c1a14") >= 4.5


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
