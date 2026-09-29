"""Tests for certbot_dns_tencent._internal.dns_tencent."""
import os
import sys
import unittest
from unittest import mock

import pytest

from certbot import errors
from certbot.plugins import dns_test_common
from certbot.plugins.dns_test_common import DOMAIN
from certbot.tests import util as test_util

from certbot_dns_tencent._internal.tencent_client import TencentCloudAPIError
from certbot_dns_tencent._internal.tencent_client import TencentCloudClient

SECRET_ID = 'AKIDtest'
SECRET_KEY = 'secret-key'


class AuthenticatorTest(test_util.TempDirTestCase, dns_test_common.BaseAuthenticatorTest):

    def setUp(self):
        from certbot_dns_tencent._internal.dns_tencent import Authenticator

        super().setUp()

        path = os.path.join(self.tempdir, 'file.ini')
        dns_test_common.write({'tencent_secret_id': SECRET_ID,
                               'tencent_secret_key': SECRET_KEY}, path)

        self.config = mock.MagicMock(tencent_credentials=path,
                                     tencent_propagation_seconds=0)  # don't wait during tests

        self.auth = Authenticator(self.config, 'tencent')

        self.mock_client = mock.MagicMock()
        # _get_client | pylint: disable=protected-access
        self.auth._get_client = mock.MagicMock(return_value=self.mock_client)

    @test_util.patch_display_util()
    def test_perform(self, unused_mock_get_utility):
        self.auth.perform([self.achall])

        expected = [mock.call.add_txt_record(DOMAIN, '_acme-challenge.' + DOMAIN, mock.ANY, 600)]
        assert expected == self.mock_client.mock_calls

    def test_cleanup(self):
        # _attempt_cleanup | pylint: disable=protected-access
        self.auth._attempt_cleanup = True
        self.auth.cleanup([self.achall])

        expected = [mock.call.del_txt_record(DOMAIN, '_acme-challenge.' + DOMAIN, mock.ANY)]
        assert expected == self.mock_client.mock_calls

    @test_util.patch_display_util()
    def test_missing_secret_key(self, unused_mock_get_utility):
        dns_test_common.write({'tencent_secret_id': SECRET_ID}, self.config.tencent_credentials)
        with pytest.raises(errors.PluginError):
            self.auth.perform([self.achall])

    def test_real_client_is_cached(self):
        from certbot_dns_tencent._internal.dns_tencent import Authenticator

        auth = Authenticator(self.config, 'tencent')
        auth._setup_credentials()  # pylint: disable=protected-access
        client = auth._get_client()  # pylint: disable=protected-access
        assert isinstance(client, TencentCloudClient)
        assert client.secret_id == SECRET_ID
        assert client.secret_key == SECRET_KEY
        assert auth._get_client() is client  # pylint: disable=protected-access


class FakeAPI:
    """Dispatches TencentCloudClient.call() to a scripted in-memory DNSPod."""

    def __init__(self, domains=('example.com',)):
        self.domains = list(domains)
        self.records = []
        self.calls = []
        self.errors = {}
        self._next_id = 1000

    def __call__(self, action, params):
        self.calls.append((action, params))
        if action in self.errors:
            raise self.errors[action]
        return getattr(self, action)(params)

    def DescribeDomainList(self, params):  # pylint: disable=invalid-name,unused-argument
        if not self.domains:
            raise TencentCloudAPIError('ResourceNotFound.NoDataOfDomain', 'empty')
        return {'DomainCountInfo': {'AllTotal': len(self.domains)},
                'DomainList': [{'Name': d} for d in self.domains]}

    def CreateRecord(self, params):  # pylint: disable=invalid-name
        self._next_id += 1
        self.records.append({'RecordId': self._next_id, 'Name': params['SubDomain'],
                             'Type': params['RecordType'], 'Value': params['Value'],
                             'Domain': params['Domain']})
        return {'RecordId': self._next_id}

    def DescribeRecordList(self, params):  # pylint: disable=invalid-name
        found = [r for r in self.records if r['Domain'] == params['Domain']
                 and r['Name'] == params['Subdomain'] and r['Type'] == params['RecordType']]
        if not found:
            raise TencentCloudAPIError('ResourceNotFound.NoDataOfRecord', 'record list is empty')
        return {'RecordList': found}

    def DeleteRecord(self, params):  # pylint: disable=invalid-name
        self.records = [r for r in self.records if r['RecordId'] != params['RecordId']]
        return {}


class TencentCloudClientTest(unittest.TestCase):
    record_name = '_acme-challenge.' + DOMAIN
    record_content = 'bar'
    record_ttl = 600

    def setUp(self):
        self.client = TencentCloudClient(SECRET_ID, SECRET_KEY)
        self.api = FakeAPI()
        self.client.call = self.api

    def test_add_txt_record(self):
        self.client.add_txt_record(DOMAIN, self.record_name, self.record_content, self.record_ttl)

        assert self.api.calls[-1] == ('CreateRecord', {
            'Domain': DOMAIN, 'SubDomain': '_acme-challenge', 'RecordType': 'TXT',
            'RecordLine': '默认', 'Value': self.record_content, 'TTL': self.record_ttl})

    def test_add_txt_record_longest_zone_match(self):
        self.api.domains = ['example.com', 'sub.example.com']
        self.client.add_txt_record('a.sub.example.com', '_acme-challenge.a.sub.example.com',
                                   self.record_content, self.record_ttl)

        params = self.api.calls[-1][1]
        assert params['Domain'] == 'sub.example.com'
        assert params['SubDomain'] == '_acme-challenge.a'

    def test_wildcard_and_apex_share_record_name(self):
        # Certbot validates *.example.com and example.com via the same record name.
        self.client.add_txt_record('*.' + DOMAIN, self.record_name, 'v1', self.record_ttl)
        self.client.add_txt_record(DOMAIN, self.record_name, 'v2', self.record_ttl)
        assert [r['Value'] for r in self.api.records] == ['v1', 'v2']
        # The domain list is fetched only once.
        assert [c[0] for c in self.api.calls].count('DescribeDomainList') == 1

        self.client.del_txt_record('*.' + DOMAIN, self.record_name, 'v1')
        assert [r['Value'] for r in self.api.records] == ['v2']
        self.client.del_txt_record(DOMAIN, self.record_name, 'v2')
        assert not self.api.records

    def test_add_txt_record_zone_not_found(self):
        self.api.domains = ['other.com']
        with pytest.raises(errors.PluginError, match='Unable to find'):
            self.client.add_txt_record(DOMAIN, self.record_name, self.record_content,
                                       self.record_ttl)

    def test_add_txt_record_no_domains(self):
        self.api.domains = []
        with pytest.raises(errors.PluginError, match='Unable to find'):
            self.client.add_txt_record(DOMAIN, self.record_name, self.record_content,
                                       self.record_ttl)

    def test_add_txt_record_auth_error(self):
        self.api.errors['DescribeDomainList'] = TencentCloudAPIError(
            'AuthFailure.SecretIdNotFound', 'The SecretId is not found')
        with pytest.raises(errors.PluginError, match='dns_tencent_secret_id'):
            self.client.add_txt_record(DOMAIN, self.record_name, self.record_content,
                                       self.record_ttl)

    def test_add_txt_record_create_error(self):
        self.api.errors['CreateRecord'] = TencentCloudAPIError(
            'LimitExceeded.RecordTtlLimit', 'TTL limit')
        with pytest.raises(errors.PluginError, match='600'):
            self.client.add_txt_record(DOMAIN, self.record_name, self.record_content, 1)

    def test_add_txt_record_already_exists(self):
        self.api.errors['CreateRecord'] = TencentCloudAPIError(
            'InvalidParameter.DomainRecordExist', 'exists')
        self.client.add_txt_record(DOMAIN, self.record_name, self.record_content, self.record_ttl)

    def test_add_txt_record_apex(self):
        self.client.add_txt_record(DOMAIN, DOMAIN, self.record_content, self.record_ttl)
        assert self.api.calls[-1][1]['SubDomain'] == '@'

    def test_del_txt_record_uses_cached_id(self):
        self.client.add_txt_record(DOMAIN, self.record_name, self.record_content, self.record_ttl)
        record_id = self.api.records[0]['RecordId']
        self.api.calls.clear()

        self.client.del_txt_record(DOMAIN, self.record_name, self.record_content)

        assert self.api.calls == [('DeleteRecord', {'Domain': DOMAIN, 'RecordId': record_id})]
        assert not self.api.records

    def test_del_txt_record_lookup_by_value(self):
        self.api.records = [
            {'RecordId': 1, 'Domain': DOMAIN, 'Name': '_acme-challenge', 'Type': 'TXT',
             'Value': self.record_content},
            {'RecordId': 2, 'Domain': DOMAIN, 'Name': '_acme-challenge', 'Type': 'TXT',
             'Value': 'keep-me'},
        ]
        self.client.del_txt_record(DOMAIN, self.record_name, self.record_content)
        assert [r['RecordId'] for r in self.api.records] == [2]

    def test_del_txt_record_not_found(self):
        self.client.del_txt_record(DOMAIN, self.record_name, self.record_content)
        assert 'DeleteRecord' not in [c[0] for c in self.api.calls]

    def test_del_txt_record_error_is_not_raised(self):
        self.client.add_txt_record(DOMAIN, self.record_name, self.record_content, self.record_ttl)
        self.api.errors['DeleteRecord'] = TencentCloudAPIError('InternalError', 'boom')
        with self.assertLogs('certbot_dns_tencent', level='WARNING'):
            self.client.del_txt_record(DOMAIN, self.record_name, self.record_content)

    def test_del_txt_record_zone_not_found_is_not_raised(self):
        self.api.domains = ['other.com']
        with self.assertLogs('certbot_dns_tencent', level='WARNING'):
            self.client.del_txt_record(DOMAIN, self.record_name, self.record_content)


if __name__ == '__main__':
    sys.exit(pytest.main(sys.argv[1:] + [__file__]))  # pragma: no cover
