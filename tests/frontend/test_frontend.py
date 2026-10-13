"""Presentation and transport checks; never connect to PostgreSQL or live AI."""
import io
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

import pytest

from frontend.app import create_app


@pytest.fixture
def client():
    """Return the Flask frontend client used by each transport test."""
    return create_app().test_client()


def test_jinja_shell_and_static_assets(client):
    page = client.get('/')
    assert page.status_code == 200
    assert b'/static/app.js' in page.data
    assert b'Demo workflow' in page.data
    with client.get('/static/styles.css') as asset:
        assert asset.status_code == 200
    assert client.get('/app.py').status_code == 404
    assert client.get('/tests/frontend/fixture.json').status_code == 404


def test_multipart_passes_file_and_boundary(client):
    with patch('frontend.app.urlopen') as open_url:
        response = MagicMock(status=200, headers={'Content-Type': 'application/json'})
        response.read.return_value = b'{"payload":{},"errors":[]}'
        open_url.return_value.__enter__.return_value = response
        result = client.post('/api/projects/1/process', data={
            'modules': '[{"file_field":"image"}]', 'image': (io.BytesIO(b'image-data'), 'module.png'),
        })
        assert result.status_code == 200
        upstream = open_url.call_args.args[0]
        assert 'boundary=' in upstream.get_header('Content-type')
        assert b'image-data' in upstream.data
        assert b'module.png' in upstream.data


def test_unavailable_api_is_explicit(client):
    with patch('frontend.app.urlopen', side_effect=URLError('unavailable')):
        result = client.get('/health')
    assert result.status_code == 502
    assert result.json['payload'] is None


def test_partial_and_error_responses_are_not_hidden(client):
    with patch('frontend.app.urlopen') as open_url:
        body = b'{"payload":null,"errors":["Project not found"]}'
        open_url.side_effect = HTTPError('http://helper/api', 404, 'Not found', {'Content-Type': 'application/json'}, io.BytesIO(body))
        result = client.get('/api/projects/1')
    assert result.status_code == 404
    assert result.data == body
