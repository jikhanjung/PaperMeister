"""Which OCR settings each backend actually uses.

The Preferences OCR tab offers three backends, and only one of them — RunPod
Serverless — has anything to do with the Endpoint ID and API Key. A self-hosted
server (Direct vLLM, Wrapper API) is reached by URL and nothing else. The tab
used to stack all three radios and then list every field below them, which reads
as "these apply to the selected backend"; it isn't so, and this pins down both
halves of that: the config path ignores the credentials, and the dialog puts
each field with the backend that owns it.
"""
import pytest

from papermeister import ocr


@pytest.fixture
def prefs(monkeypatch):
    """Drive _ensure_config off a dict, with the module's cache cleared."""
    values = {}

    def fake_get_pref(key, default=None):
        return values.get(key, default)

    monkeypatch.setattr('papermeister.preferences.get_pref', fake_get_pref)
    for name in ('_BACKEND', '_BASE_URL', '_HEADERS', '_POD_URL', '_WRAPPER_URL'):
        monkeypatch.setattr(ocr, name, None)
    return values


@pytest.mark.unit
@pytest.mark.parametrize('backend', ['wrapper', 'pod'])
def test_self_hosted_backends_need_no_runpod_credentials(prefs, backend):
    prefs.update({'ocr_backend': backend, 'ocr_pod_url': 'http://172.16.112.150:8080'})
    ocr._ensure_config()      # no endpoint id, no api key — and no complaint
    assert (ocr._WRAPPER_URL or ocr._POD_URL) == 'http://172.16.112.150:8080'
    assert ocr._BASE_URL is None   # the RunPod URL is never even built


@pytest.mark.unit
def test_self_hosted_backends_still_need_a_url(prefs):
    prefs.update({'ocr_backend': 'wrapper', 'runpod_endpoint_id': 'x', 'runpod_api_key': 'y'})
    with pytest.raises(RuntimeError, match='URL'):
        ocr._ensure_config()   # credentials are no substitute for the URL


@pytest.mark.unit
def test_serverless_is_the_one_backend_that_needs_them(prefs):
    prefs.update({'ocr_backend': 'serverless', 'ocr_pod_url': 'http://172.16.112.150:8080'})
    with pytest.raises(RuntimeError, match='RunPod credentials'):
        ocr._ensure_config()


@pytest.mark.ui
@pytest.mark.parametrize('radio,runpod_on,url_on', [
    ('_ocr_runpod_radio', True, False),
    ('_ocr_pod_radio', False, True),
    ('_ocr_wrapper_radio', False, True),
])
def test_dialog_enables_only_the_selected_backends_fields(qapp, radio, runpod_on, url_on):
    from papermeister.ui.preferences_dialog import PreferencesDialog

    dlg = PreferencesDialog()
    getattr(dlg, radio).setChecked(True)
    dlg._on_ocr_backend_changed()

    assert dlg.runpod_endpoint_edit.isEnabled() is runpod_on
    assert dlg.runpod_api_key_edit.isEnabled() is runpod_on
    assert dlg.ocr_pod_url_edit.isEnabled() is url_on


@pytest.mark.ui
def test_runpod_fields_sit_under_the_runpod_radio(qapp):
    """Ordering, not just enablement: the fields must read as RunPod's own."""
    from papermeister.ui.preferences_dialog import PreferencesDialog

    dlg = PreferencesDialog()
    order = lambda w: w.mapTo(dlg, w.rect().topLeft()).y()  # noqa: E731

    assert order(dlg._ocr_runpod_radio) < order(dlg.runpod_endpoint_edit)
    assert order(dlg.runpod_endpoint_edit) < order(dlg._ocr_pod_radio)
    # The URL is shared by both self-hosted backends, so it follows them both.
    assert order(dlg._ocr_wrapper_radio) < order(dlg.ocr_pod_url_edit)
