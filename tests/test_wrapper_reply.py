"""What the OCR client says when the wrapper's reply is not JSON.

A proxy in front of the wrapper can answer 2xx with an HTML error page, or with
nothing at all. `raise_for_status` waves that through and `.json()` fails with
"Expecting value: line 1 column 1 (char 0)" — a message that names neither the
request nor the reply, and looks identical whether the server is down, the
upload was refused, or the response was truncated. It cost a run's worth of
guessing, so the reply now describes itself.
"""
import pytest

from papermeister import ocr


class _Reply:
    def __init__(self, status, text, payload=None):
        self.status_code = status
        self.text = text
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError('Expecting value: line 1 column 1 (char 0)')
        return self._payload


@pytest.mark.unit
def test_json_is_returned_untouched():
    assert ocr._wrapper_json(_Reply(200, '{"job_id": "x"}', {'job_id': 'x'}), 'submit') == {
        'job_id': 'x'}


@pytest.mark.unit
def test_an_html_error_page_is_named_as_one():
    reply = _Reply(200, '<html><head><title>502 Bad Gateway</title></head></html>')

    with pytest.raises(ocr.WrapperReplyNotJSON) as caught:
        ocr._wrapper_json(reply, 'poll of job abc')

    message = str(caught.value)
    assert 'poll of job abc' in message      # which request
    assert 'HTTP 200' in message             # what status it claimed
    assert '502 Bad Gateway' in message      # and what actually came back


@pytest.mark.unit
def test_an_empty_body_says_so_rather_than_nothing():
    with pytest.raises(ocr.WrapperReplyNotJSON, match='empty body'):
        ocr._wrapper_json(_Reply(200, ''), 'submit of paper.pdf')


@pytest.mark.unit
def test_the_original_decode_error_is_not_chained_over_the_message():
    """`from None`: the useful sentence must be the one that reaches the log,
    not a JSONDecodeError three frames down."""
    with pytest.raises(ocr.WrapperReplyNotJSON) as caught:
        ocr._wrapper_json(_Reply(200, 'not json'), 'submit')
    assert caught.value.__cause__ is None
