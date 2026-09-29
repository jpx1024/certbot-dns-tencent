"""DNS Authenticator for Tencent Cloud DNS (DNSPod)."""
import logging
from typing import Any
from typing import Callable
from typing import Optional

from certbot import errors
from certbot.plugins import dns_common
from certbot.plugins.dns_common import CredentialsConfiguration

from certbot_dns_tencent._internal.tencent_client import DEFAULT_ENDPOINT
from certbot_dns_tencent._internal.tencent_client import TencentCloudClient

logger = logging.getLogger(__name__)

ACCOUNT_URL = 'https://console.cloud.tencent.com/cam/capi'


class Authenticator(dns_common.DNSAuthenticator):
    """DNS Authenticator for Tencent Cloud DNS (DNSPod)

    This Authenticator uses the Tencent Cloud DNSPod API 3.0 to fulfill a dns-01 challenge.
    """

    description = ('Obtain certificates using a DNS TXT record (if you are using Tencent Cloud '
                   'DNS / DNSPod for DNS).')
    ttl = 600

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.credentials: Optional[CredentialsConfiguration] = None
        self._client: Optional[TencentCloudClient] = None

    @classmethod
    def add_parser_arguments(cls, add: Callable[..., None],
                             default_propagation_seconds: int = 30) -> None:
        super().add_parser_arguments(add, default_propagation_seconds)
        add('credentials', help='Tencent Cloud credentials INI file.')

    def more_info(self) -> str:
        return ('This plugin configures a DNS TXT record to respond to a dns-01 challenge using '
                'the Tencent Cloud DNSPod API.')

    def _setup_credentials(self) -> None:
        self.credentials = self._configure_credentials(
            'credentials',
            'Tencent Cloud credentials INI file',
            {
                'secret_id': f'SecretId of a Tencent Cloud API key, obtained from {ACCOUNT_URL}',
                'secret_key': f'SecretKey of a Tencent Cloud API key, obtained from {ACCOUNT_URL}',
            },
        )

    def _perform(self, domain: str, validation_name: str, validation: str) -> None:
        self._get_client().add_txt_record(domain, validation_name, validation, self.ttl)

    def _cleanup(self, domain: str, validation_name: str, validation: str) -> None:
        self._get_client().del_txt_record(domain, validation_name, validation)

    def _get_client(self) -> TencentCloudClient:
        if not self.credentials:  # pragma: no cover
            raise errors.Error('Plugin has not been prepared.')
        if self._client is None:
            self._client = TencentCloudClient(
                self.credentials.conf('secret_id'),
                self.credentials.conf('secret_key'),
                endpoint=self.credentials.conf('endpoint') or DEFAULT_ENDPOINT,
            )
        return self._client
