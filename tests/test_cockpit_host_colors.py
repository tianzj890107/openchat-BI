"""Host palette must not redefine component/dashboard theme tokens."""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]/'bi_agent/web/static/cockpit'


def test_host_palette_matches_supplied_spec():
    css=(ROOT/'host-colors.css').read_text()
    for token,color in [('primary','#165dff'),('success','#44bc09'),('warning','#ff8f1f'),('error','#ff4d4f'),('link','#165dff'),('input-border','#dcdfe6'),('divider','#eaebf2')]:
        assert f'--cockpit-{token}: {color};' in css
    assert '--pro-' not in css and '--dashboard-' not in css
    assert css.count('{')==css.count('}')


def test_custom_color_references_are_defined_and_no_legacy_colors_remain():
    palette=(ROOT/'host-colors.css').read_text()
    defined=set(re.findall(r'(--cockpit-[\w-]+)\s*:',palette))
    files=list((ROOT/'insight-components').rglob('*.css'))+[ROOT/'insight-components/registry.js',ROOT/'cockpit.css']
    for path in files:
        css=path.read_text()
        assert set(re.findall(r'var\((--cockpit-[\w-]+)',css)) <= defined,path
        assert not re.search(r'#(?:cf1322|d46b08|389e0d|1677ff)\b',css,re.I),path


def test_palette_is_loaded_after_vendor_before_host_styles():
    html=(ROOT/'index.html').read_text()
    assert html.index('vendor/pro-ui.min.css') < html.index('host-colors.css') < html.index('/cockpit.css')
