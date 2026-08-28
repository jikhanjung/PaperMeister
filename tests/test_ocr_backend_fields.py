"""Which OCR settings each backend actually uses, and what we call it.

The Preferences OCR tab offers three backends, and only one of them — RunPod
Serverless — has anything to do with the Endpoint ID and API Key. A self-hosted
server (Direct vLLM, Wrapper API) is reached by URL and nothing else. The tab
used to stack all three radios and then list every field below them, which reads
as "these apply to the selected backend"; it isn't so, and this pins down both
halves of that: the config path ignores the credentials, and the dialog puts
each field with the backend that owns it.
"""
import pathlib

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


@pytest.mark.unit
@pytest.mark.parametrize('backend,expected', [
    ('serverless', 'RunPod OCR'),
    ('pod', 'Direct vLLM OCR'),
    ('wrapper', 'Wrapper API OCR'),
])
def test_messages_name_the_configured_backend(prefs, backend, expected):
    """Saying "RunPod" while pointed at a self-hosted server is not a wording
    nit: it claims the papers are leaving the building."""
    prefs['ocr_backend'] = backend
    assert ocr.backend_label() == expected
    assert ocr.is_serverless_mode() is (backend == 'serverless')


@pytest.mark.unit
def test_label_works_before_the_backend_is_configured(prefs):
    """A label is wanted exactly when something is being reported, including
    when _ensure_config would raise."""
    assert ocr.backend_label() == 'RunPod OCR'   # the default, not an exception


@pytest.mark.unit
def test_self_hosted_ready_check_skips_the_runpod_wake(prefs, monkeypatch):
    """There is no cold start to trigger, and no _BASE_URL to send it to —
    the wake POST would go to the string 'None/run'."""
    prefs.update({'ocr_backend': 'wrapper', 'ocr_pod_url': 'http://172.16.112.150:8080'})
    posted = []
    monkeypatch.setattr(ocr.requests, 'post', lambda *a, **k: posted.append(a))
    monkeypatch.setattr(ocr, 'is_ready', lambda: False)
    monkeypatch.setattr(ocr, '_poll_until_ready', lambda timeout, poll: True)

    assert ocr.wake_and_wait(timeout=1) is True
    assert posted == []


@pytest.mark.unit
def test_not_ready_error_names_the_backend(prefs, monkeypatch):
    prefs.update({'ocr_backend': 'wrapper', 'ocr_pod_url': 'http://172.16.112.150:8080'})
    monkeypatch.setattr(ocr, 'wake_and_wait', lambda timeout: False)
    monkeypatch.setattr(ocr, '_workers_confirmed', False)

    with pytest.raises(RuntimeError, match='Wrapper API OCR not ready'):
        ocr.ensure_workers_ready(timeout=1)


ROOT = pathlib.Path(__file__).resolve().parent.parent

# Where the name is the subject rather than an assumption: the RunPod-only code
# path and its config, the radio that selects it, and the licence table.
_MAY_SAY_RUNPOD = {
    'papermeister/ocr.py',
    'papermeister/ui/preferences_dialog.py',
    'papermeister/about.py',
}


def _strings_naming_runpod(source):
    """RunPod in a string literal — what a user could end up reading.

    Comments and docstrings are not it; an ast walk skips comments for free,
    and a docstring is filtered out by where it sits.
    """
    import ast
    tree = ast.parse(source)
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and 'RunPod' in node.value and node.value not in docstrings
    ]


@pytest.mark.unit
def test_naming_runpod_requires_checking_that_it_is_runpod():
    """A message may say RunPod — but only in a file that establishes it is
    talking to RunPod. Two of the three backends are servers we host, and
    telling the user their papers went to RunPod is then simply false.
    """
    offenders = []
    for spot in ('papermeister', 'desktop', 'cli.py'):
        path = ROOT / spot
        for f in ([path] if path.is_file() else path.rglob('*.py')):
            rel = str(f.relative_to(ROOT)).replace('\\', '/')
            if rel in _MAY_SAY_RUNPOD:
                continue
            source = f.read_text(encoding='utf-8')
            named = _strings_naming_runpod(source)
            if named and 'is_serverless_mode' not in source:
                offenders.append(f'{rel}: {named}')
    assert not offenders, (
        'RunPod named without checking the backend:\n' + '\n'.join(offenders))
