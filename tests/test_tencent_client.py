"""Tests for the TC3-HMAC-SHA256 signing and HTTP layer of TencentCloudClient."""
import sys
from unittest import mock

import pytest
import requests

from certbot import errors

from certbot_dns_tencent._internal.tencent_client import TencentCloudAPIError
from certbot_dns_tencent._internal.tencent_client import TencentCloudClient
from certbot_dns_tencent._internal.tencent_client import sign_request


def test_sign_request_matches_official_sdk():
    # Expected signature computed with tencentcloud-sdk-python-common's Sign.sign_tc3.
    payload = '{"Domain":"example.com","RecordLine":"默认"}'
    headers = sign_request('AKIDtest', 'secret-key', 'dnspod.tencentcloudapi.com',
                           'CreateRecord', payload, 1727580000)

    assert headers['Authorization'] == (
        'TC3-HMAC-SHA256 Credential=AKIDtest/2024-09-29/dnspod/tc3_request, '
        'SignedHeaders=content-type;host;x-tc-action, '
        'Signature=d611dd4602e9f138cc8251d1724200223ba6cbdf8af5f7cdab7cf71cd1c73f64')
    assert headers['X-TC-Action'] == 'CreateRecord'
    assert headers['X-TC-Timestamp'] == '1727580000'
    assert headers['X-TC-Version'] == '2021-03-23'


def _client_with_response(json_body=None, exc=None):
    client = TencentCloudClient('AKIDtest', 'secret-key')
    client._session = mock.MagicMock()  # pylint: disable=protected-access
    if exc:
        client._session.post.side_effect = exc  # pylint: disable=protected-access
    else:
        client._session.post.return_value.json.return_value = json_body  # pylint: disable=protected-access
    return client


def test_call_success():
    client = _client_with_response({'Response': {'RecordId': 1, 'RequestId': 'r'}})
    assert client.call('CreateRecord', {'Domain': 'example.com'})['RecordId'] == 1

    args, kwargs = client._session.post.call_args  # pylint: disable=protected-access
    assert args[0] == 'https://dnspod.tencentcloudapi.com/'
    assert kwargs['data'] == b'{"Domain":"example.com"}'
    assert kwargs['headers']['X-TC-Action'] == 'CreateRecord'


def test_call_api_error():
    client = _client_with_response({'Response': {
        'Error': {'Code': 'AuthFailure.SignatureFailure', 'Message': 'bad'}, 'RequestId': 'r'}})
    with pytest.raises(TencentCloudAPIError) as e:
        client.call('DescribeDomainList', {})
    assert e.value.code == 'AuthFailure.SignatureFailure'


def test_call_network_error():
    client = _client_with_response(exc=requests.ConnectionError('down'))
    with pytest.raises(errors.PluginError, match='down'):
        client.call('DescribeDomainList', {})


if __name__ == '__main__':
    sys.exit(pytest.main(sys.argv[1:] + [__file__]))  # pragma: no cover
