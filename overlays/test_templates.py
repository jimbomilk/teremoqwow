"""Tests de los 12 templates de overlays — E4-T2."""
import json
import os
import pytest

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'templates')
TEMPLATE_IDS = [
    'logo-corner', 'banner-bottom', 'lower-third', 'scoreboard-sport',
    'stats-bar', 'ad-countdown', 'ticker-news', 'countdown-clock',
    'image-overlay', 'sponsor-banner', 'poll-interactive', 'custom-html',
]


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_template_has_index_html(template_id):
    path = os.path.join(TEMPLATES_DIR, template_id, 'index.html')
    assert os.path.exists(path), f"Missing {path}"


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_template_has_metadata_json(template_id):
    path = os.path.join(TEMPLATES_DIR, template_id, 'metadata.json')
    assert os.path.exists(path), f"Missing {path}"


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_metadata_has_required_fields(template_id):
    path = os.path.join(TEMPLATES_DIR, template_id, 'metadata.json')
    with open(path) as f:
        meta = json.load(f)
    assert meta['id'] == template_id
    assert 'name' in meta
    assert 'kind' in meta
    assert 'vars' in meta
    assert 'required' in meta['vars']


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_template_listens_to_overlay_data(template_id):
    path = os.path.join(TEMPLATES_DIR, template_id, 'index.html')
    with open(path) as f:
        content = f.read()
    assert 'overlay:data' in content, f"{template_id}: no escucha overlay:data"


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_template_posts_overlay_ready(template_id):
    path = os.path.join(TEMPLATES_DIR, template_id, 'index.html')
    with open(path) as f:
        content = f.read()
    assert 'overlay:ready' in content, f"{template_id}: no envía overlay:ready"


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_template_no_external_imports(template_id):
    """Templates deben ser autocontenidos — sin CDN links."""
    path = os.path.join(TEMPLATES_DIR, template_id, 'index.html')
    with open(path) as f:
        content = f.read()
    forbidden = ['cdn.jsdelivr.net', 'unpkg.com', 'cdnjs.cloudflare.com']
    for f_url in forbidden:
        assert f_url not in content, f"{template_id}: contiene import externo {f_url}"


def test_no_innerhtml_with_user_data_in_custom_html():
    """custom-html no debe usar innerHTML con datos del usuario sin sanitizar."""
    path = os.path.join(TEMPLATES_DIR, 'custom-html', 'index.html')
    with open(path) as f:
        content = f.read()
    assert (
        'sanitize' in content.lower()
        or 'whitelist' in content.lower()
        or 'allowed' in content.lower()
    ), "custom-html debe tener función de sanitización (sanitize/whitelist/allowed)"
