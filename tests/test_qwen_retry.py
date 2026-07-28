"""`_call_qwen` retry policy: transient 5xx vs. everything else.

The vLLM engine worker occasionally dies (OOM / CUDA fault) mid-batch. On the
way out it answers 500 `EngineCore encountered an issue`, and while it restarts
the front proxy answers 502 `upstream: All connection attempts failed`. Both are
transient and the request is idempotent, so a short backoff rides through the
restart instead of failing the whole paper.

The distinctions that matter, pinned here:
  * a 5xx blip is retried and succeeds — the caller never sees it
  * a sustained 5xx still raises, so ServerGuard can pause and poll the server
    rather than the outage being silently absorbed
  * 4xx is never retried — that is our own malformed request
  * timeout retries stay governed by `retries` (callers shrink the batch), and
    are not affected by the 5xx budget
"""
import pytest
import requests

from papermeister import biblio


class _Resp:
    def __init__(self, status, content='ok'):
        self.status_code = status
        self.text = 'boom' if status >= 400 else 'fine'
        self._content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f'{self.status_code}', response=self)

    def json(self):
        return {'choices': [{'message': {'content': self._content}}]}


@pytest.fixture
def qwen(monkeypatch):
    """Drive _call_qwen off a scripted list of responses/exceptions."""
    calls, slept = [], []
    monkeypatch.setattr(biblio.time, 'sleep', lambda s: slept.append(s))

    def run(script, **kwargs):
        queue = list(script)

        def fake_post(url, **_):
            calls.append(url)
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        monkeypatch.setattr(requests, 'post', fake_post)
        return biblio._call_qwen('p', 'http://server', **kwargs)

    run.calls, run.slept = calls, slept
    return run


@pytest.mark.unit
def test_500_blip_is_retried_and_succeeds(qwen):
    """Engine hiccup while the process is up: 500, 500, then fine."""
    assert qwen([_Resp(500), _Resp(500), _Resp(200, 'refs')]) == 'refs'
    assert len(qwen.calls) == 3
    assert qwen.slept == [5.0, 15.0]  # backoff grows, then holds


@pytest.mark.unit
def test_gateway_statuses_are_not_retried(qwen):
    """A restarting container will not be back inside the backoff, so burning it
    only delays handing the problem to code that can actually wait."""
    for status in (502, 503, 504):
        qwen.calls.clear()
        qwen.slept.clear()
        with pytest.raises(requests.exceptions.HTTPError):
            qwen([_Resp(status)])
        assert len(qwen.calls) == 1, status
        assert qwen.slept == [], status


@pytest.mark.unit
def test_500_engine_core_is_retried(qwen):
    """The 500 the engine emits is worth one wait — unlike a gateway status, it
    does not necessarily mean the process is gone."""
    assert qwen([_Resp(500), _Resp(200, 'refs')]) == 'refs'
    assert len(qwen.calls) == 2


@pytest.mark.unit
def test_sustained_500_still_raises(qwen):
    """A server that is really down must surface, so ServerGuard pauses the
    batch. Absorbing it here would spin through every paper doing nothing."""
    with pytest.raises(requests.exceptions.HTTPError):
        qwen([_Resp(500)] * 3)
    assert len(qwen.calls) == 3  # initial + server_retries, then give up


@pytest.mark.unit
def test_4xx_is_not_retried(qwen):
    """A malformed request will not fix itself — fail fast, no backoff."""
    with pytest.raises(requests.exceptions.HTTPError):
        qwen([_Resp(400)])
    assert len(qwen.calls) == 1
    assert qwen.slept == []


@pytest.mark.unit
def test_timeout_budget_is_separate_from_5xx_budget(qwen):
    """`retries=0` (what the references batcher uses, since it shrinks instead)
    must still get the 5xx retries — the two failures are unrelated."""
    assert qwen([_Resp(500), _Resp(200, 'refs')], retries=0) == 'refs'

    with pytest.raises(requests.exceptions.Timeout):
        qwen([requests.exceptions.Timeout()], retries=0)


@pytest.mark.unit
def test_timeout_retries_honor_the_retries_arg(qwen):
    """Pre-existing behavior: retries=1 means two attempts total."""
    assert qwen([requests.exceptions.Timeout(), _Resp(200, 'refs')],
                retries=1) == 'refs'
    assert len(qwen.calls) == 2
