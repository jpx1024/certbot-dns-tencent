"""Minimal client for the Tencent Cloud DNSPod API 3.0 (TC3-HMAC-SHA256 signed)."""
import datetime
import hashlib
import hmac
import json
import logging
import time
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import requests

from certbot import errors
from certbot.plugins import dns_common

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = 'dnspod.tencentcloudapi.com'
SERVICE = 'dnspod'
API_VERSION = '2021-03-23'
DEFAULT_RECORD_LINE = '默认'
PAGE_LIMIT = 3000


class TencentCloudAPIError(Exception):
    """An error returned by the Tencent Cloud API."""

    def __init__(self, code: str, message: str, request_id: Optional[str] = None) -> None:
        super().__init__(f'{code}: {message} (RequestId: {request_id})')
        self.code = code
        self.message = message
        self.request_id = request_id


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def sign_request(secret_id: str, secret_key: str, host: str, action: str, payload: str,
                 timestamp: int, service: str = SERVICE) -> Dict[str, str]:
    """Build the signed HTTP headers for a Tencent Cloud API 3.0 POST request.

    See https://cloud.tencent.com/document/api/1427/56189 (TC3-HMAC-SHA256).
    """
    content_type = 'application/json; charset=utf-8'
    date = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc).strftime('%Y-%m-%d')

    signed_headers = 'content-type;host;x-tc-action'
    canonical_headers = (f'content-type:{content_type}\n'
                         f'host:{host}\n'
                         f'x-tc-action:{action.lower()}\n')
    canonical_request = '\n'.join([
        'POST', '/', '', canonical_headers, signed_headers, _sha256_hex(payload),
    ])

    credential_scope = f'{date}/{service}/tc3_request'
    string_to_sign = '\n'.join([
        'TC3-HMAC-SHA256', str(timestamp), credential_scope, _sha256_hex(canonical_request),
    ])

    secret_date = _hmac_sha256(('TC3' + secret_key).encode('utf-8'), date)
    secret_service = _hmac_sha256(secret_date, service)
    secret_signing = _hmac_sha256(secret_service, 'tc3_request')
    signature = hmac.new(secret_signing, string_to_sign.encode('utf-8'),
                         hashlib.sha256).hexdigest()

    authorization = (f'TC3-HMAC-SHA256 Credential={secret_id}/{credential_scope}, '
                     f'SignedHeaders={signed_headers}, Signature={signature}')

    return {
        'Authorization': authorization,
        'Content-Type': content_type,
        'Host': host,
        'X-TC-Action': action,
        'X-TC-Timestamp': str(timestamp),
        'X-TC-Version': API_VERSION,
    }


class TencentCloudClient:
    """Encapsulates all communication with the Tencent Cloud DNSPod API."""

    def __init__(self, secret_id: str, secret_key: str, endpoint: str = DEFAULT_ENDPOINT,
                 timeout: int = 30) -> None:
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.endpoint = endpoint
        self.timeout = timeout
        self._session = requests.Session()
        self._domains: Optional[List[str]] = None
        # (record_name, record_content) -> (zone, record_id), used for precise cleanup.
        self._created: Dict[Tuple[str, str], Tuple[str, int]] = {}

    def call(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Call a DNSPod API action and return the ``Response`` object.

        :raises TencentCloudAPIError: if the API returns an error.
        :raises certbot.errors.PluginError: on network or protocol errors.
        """
        payload = json.dumps(params, ensure_ascii=False, separators=(',', ':'))
        headers = sign_request(self.secret_id, self.secret_key, self.endpoint, action, payload,
                               int(time.time()))
        try:
            resp = self._session.post(f'https://{self.endpoint}/', data=payload.encode('utf-8'),
                                      headers=headers, timeout=self.timeout)
            body = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise errors.PluginError(f'Error communicating with the Tencent Cloud API: {e}')

        response = body.get('Response', {})
        error = response.get('Error')
        if error:
            raise TencentCloudAPIError(error.get('Code', 'Unknown'), error.get('Message', ''),
                                       response.get('RequestId'))
        return response

    def add_txt_record(self, domain: str, record_name: str, record_content: str,
                       record_ttl: int) -> None:
        """Add a TXT record using the supplied information.

        :param str domain: The domain to use to look up the DNSPod zone.
        :param str record_name: The record name (typically beginning with '_acme-challenge.').
        :param str record_content: The record content (typically the challenge validation).
        :param int record_ttl: The record TTL (number of seconds that the record may be cached).
        :raises certbot.errors.PluginError: if an error occurs communicating with the API
        """
        zone = self._find_zone(domain, record_name)
        sub_domain = self._sub_domain(record_name, zone)

        logger.debug('Adding TXT record %s (zone %s) with value %s', sub_domain, zone,
                     record_content)
        try:
            response = self.call('CreateRecord', {
                'Domain': zone,
                'SubDomain': sub_domain,
                'RecordType': 'TXT',
                'RecordLine': DEFAULT_RECORD_LINE,
                'Value': record_content,
                'TTL': record_ttl,
            })
        except TencentCloudAPIError as e:
            if e.code == 'InvalidParameter.DomainRecordExist':
                logger.info('TXT record %s already exists with the same value; reusing it.',
                            record_name)
                return
            raise errors.PluginError(f'Error adding TXT record: {e}{self._hint(e)}')

        record_id = response['RecordId']
        self._created[(record_name, record_content)] = (zone, record_id)
        logger.debug('Successfully added TXT record with record_id: %s', record_id)

    def del_txt_record(self, domain: str, record_name: str, record_content: str) -> None:
        """Delete a TXT record using the supplied information.

        Failures are logged, but not raised.

        :param str domain: The domain to use to look up the DNSPod zone.
        :param str record_name: The record name (typically beginning with '_acme-challenge.').
        :param str record_content: The record content (typically the challenge validation).
        """
        try:
            created = self._created.pop((record_name, record_content), None)
            if created:
                zone, record_ids = created[0], [created[1]]
            else:
                zone = self._find_zone(domain, record_name)
                record_ids = self._find_txt_record_ids(zone, self._sub_domain(record_name, zone),
                                                       record_content)
            for record_id in record_ids:
                self.call('DeleteRecord', {'Domain': zone, 'RecordId': record_id})
                logger.debug('Successfully deleted TXT record %s (%s)', record_name, record_id)
            if not record_ids:
                logger.debug('TXT record %s not found; no cleanup needed.', record_name)
        except (TencentCloudAPIError, errors.PluginError) as e:
            logger.warning('Encountered error deleting TXT record %s: %s', record_name, e)

    def _find_txt_record_ids(self, zone: str, sub_domain: str, record_content: str) -> List[int]:
        try:
            response = self.call('DescribeRecordList', {
                'Domain': zone,
                'Subdomain': sub_domain,
                'RecordType': 'TXT',
            })
        except TencentCloudAPIError as e:
            if e.code == 'ResourceNotFound.NoDataOfRecord':
                return []
            raise
        return [r['RecordId'] for r in response.get('RecordList', [])
                if r.get('Value', '').strip('"') == record_content]

    def _list_domains(self) -> List[str]:
        if self._domains is None:
            domains: List[str] = []
            offset = 0
            while True:
                try:
                    response = self.call('DescribeDomainList',
                                         {'Type': 'ALL', 'Offset': offset, 'Limit': PAGE_LIMIT})
                except TencentCloudAPIError as e:
                    if e.code.startswith('ResourceNotFound'):
                        break
                    raise errors.PluginError(f'Error listing DNSPod domains: {e}{self._hint(e)}')
                page = [d['Name'].lower().rstrip('.') for d in response.get('DomainList', [])]
                domains.extend(page)
                total = response.get('DomainCountInfo', {}).get('AllTotal', len(domains))
                offset += len(page)
                if not page or offset >= total:
                    break
            self._domains = domains
        return self._domains

    def _find_zone(self, domain: str, record_name: str) -> str:
        domains = set(self._list_domains())
        for guess in dns_common.base_domain_name_guesses(record_name.lower().rstrip('.')):
            if guess in domains:
                logger.debug('Found DNSPod zone %s for %s', guess, record_name)
                return guess
        raise errors.PluginError(
            f'Unable to find a Tencent Cloud DNS (DNSPod) zone for {domain}. Make sure the '
            f'domain is added to DNSPod and that the credentials can access it.')

    @staticmethod
    def _sub_domain(record_name: str, zone: str) -> str:
        name = record_name.lower().rstrip('.')
        if name == zone:
            return '@'
        return name[:-(len(zone) + 1)]

    @staticmethod
    def _hint(e: TencentCloudAPIError) -> str:
        if e.code.startswith('AuthFailure'):
            return ' (Hint: check dns_tencent_secret_id / dns_tencent_secret_key.)'
        if e.code.startswith('UnauthorizedOperation') or e.code.startswith('OperationDenied'):
            return (' (Hint: the CAM user needs DNSPod permissions, e.g. the '
                    'QcloudDNSPodFullAccess policy.)')
        if e.code == 'LimitExceeded.RecordTtlLimit':
            return ' (Hint: your DNSPod plan does not allow this TTL; the free plan minimum is 600.)'
        return ''
