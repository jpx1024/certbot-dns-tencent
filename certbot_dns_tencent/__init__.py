"""
The `~certbot_dns_tencent.dns_tencent` plugin automates the process of
completing a ``dns-01`` challenge (`~acme.challenges.DNS01`) by creating, and
subsequently removing, TXT records using the Tencent Cloud DNSPod API 3.0.

Named Arguments
---------------

==========================================  ===================================
``--dns-tencent-credentials``               Tencent Cloud credentials_ INI file.
                                            (Required)
``--dns-tencent-propagation-seconds``       The number of seconds to wait for DNS
                                            to propagate before asking the ACME
                                            server to verify the DNS record.
                                            (Default: 30)
==========================================  ===================================


Credentials
-----------

Use of this plugin requires an API key (SecretId / SecretKey) obtained from
https://console.cloud.tencent.com/cam/capi. It is recommended to create a
dedicated CAM sub-user with only the ``QcloudDNSPodFullAccess`` policy.

.. code-block:: ini
   :name: credentials.ini
   :caption: Example credentials file:

   # Tencent Cloud API credentials used by Certbot
   dns_tencent_secret_id = your-secret-id
   dns_tencent_secret_key = your-secret-key

The path to this file can be provided interactively or using the
``--dns-tencent-credentials`` command-line argument. Certbot records the path
to this file for use during renewal, but does not store the file's contents.

.. caution::
   You should protect these API credentials as you would a password
   (``chmod 600``). Users who can read this file can use these credentials to
   issue arbitrary API calls on your behalf.


Examples
--------

.. code-block:: bash
   :caption: To acquire a wildcard certificate for ``example.com``

   certbot certonly \
     --authenticator dns-tencent \
     --dns-tencent-credentials ~/.secrets/certbot/tencent.ini \
     -d example.com \
     -d '*.example.com'
"""
