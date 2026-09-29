# certbot-dns-tencent

[中文](README.md) | English

A Certbot DNS Authenticator plugin for Tencent Cloud DNS (DNSPod), used the same way as `certbot-dns-cloudflare` / `certbot-dns-google`:
it creates and removes `_acme-challenge` TXT records through the DNSPod API 3.0 to complete `dns-01` challenges. Wildcard certificates and automatic renewal are supported.

- Calls the DNSPod API 3.0 directly (TC3-HMAC-SHA256 signing); depends only on `certbot` and `requests`, no Tencent Cloud SDK required
- Finds the DNSPod zone for a domain automatically (longest suffix match, so separately hosted subdomains work)
- Handles multiple TXT records when a wildcard and its apex domain share the same `_acme-challenge` name; cleanup deletes records precisely by record ID

## 1. Create a Tencent Cloud API key

1. Open [CAM → Users](https://console.cloud.tencent.com/cam) and create a **sub-user** with "Programmatic access"
2. Grant it only the `QcloudDNSPodFullAccess` policy
3. Note down its `SecretId` and `SecretKey`

Do not use your root account's keys.

## 2. Installation

### Option 1: add the plugin to an apt-installed certbot (Ubuntu / Debian)

The plugin is a pure Python package that depends only on `certbot` and `requests`, both of which apt has already installed.
Unpack the wheel into the system Python's `/usr/local` directory. No pip is needed, and apt-managed packages are left untouched:

```bash
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
sudo mkdir -p /usr/local/lib/python$PYVER/dist-packages
sudo python3 -m zipfile -e certbot_dns_tencent-0.1.0-py3-none-any.whl /usr/local/lib/python$PYVER/dist-packages/
sudo certbot plugins   # dns-tencent should be listed
```

The system's own `certbot.timer` then renews with this plugin, so no extra scheduled task is needed.
To uninstall, delete `certbot_dns_tencent` and `certbot_dns_tencent-0.1.0.dist-info` from that directory.

### Option 2: a dedicated virtual environment

Install certbot and the plugin together into their own virtual environment (as root):

```bash
python3 -m venv /opt/certbot
/opt/certbot/bin/pip install --upgrade pip
/opt/certbot/bin/pip install certbot ./certbot_dns_tencent-0.1.0-py3-none-any.whl
ln -sf /opt/certbot/bin/certbot /usr/local/bin/certbot
certbot plugins   # dns-tencent should be listed
```

You can also install from source: `/opt/certbot/bin/pip install /path/to/certbot-dns-tencent`.

> A snap-installed certbot cannot load external plugins. In that case use Option 2 and disable the snap renewal timer (see step 5).

## 3. Configure credentials

```bash
mkdir -p /root/.secrets/certbot
cat > /root/.secrets/certbot/tencent.ini <<'EOF'
dns_tencent_secret_id = your-secret-id
dns_tencent_secret_key = your-secret-key
EOF
chmod 600 /root/.secrets/certbot/tencent.ini
```

## 4. Obtain a certificate

```bash
certbot certonly \
  --authenticator dns-tencent \
  --dns-tencent-credentials /root/.secrets/certbot/tencent.ini \
  --cert-name example.com \
  -d example.com -d '*.example.com' \
  --deploy-hook 'systemctl reload nginx'
```

If `--cert-name` matches an existing certificate, certbot renews it in place and switches its authenticator (for example from `manual`) to `dns-tencent`,
so the certificate paths under `/etc/letsencrypt/live/example.com/` in your web server config stay the same. Running it once with `--dry-run` against the staging environment first is recommended.

Arguments:

| Argument | Description | Default |
| --- | --- | --- |
| `--dns-tencent-credentials` | Path to the credentials INI file (required) | — |
| `--dns-tencent-propagation-seconds` | Seconds to wait after adding the record before asking the CA to verify it | 30 |

Records are created with a TTL of 600 seconds, the minimum allowed on the DNSPod free plan.

## 5. Automatic renewal

```bash
certbot renew --dry-run
```

With Option 1, the system's own `certbot.timer` already renews on a schedule, so you are done.

With Option 2, add a scheduled task yourself (if an old snap/apt certbot has a `certbot.timer`, first run `systemctl disable --now certbot.timer snap.certbot.renew.timer`):

```bash
echo '0 3 * * * root /opt/certbot/bin/certbot renew -q' > /etc/cron.d/certbot-renew
```

The `--deploy-hook` given at issuance is saved in the renewal config, so Nginx is reloaded automatically after each successful renewal.

## Troubleshooting

| Error code | Cause |
| --- | --- |
| `AuthFailure.SecretIdNotFound` / `AuthFailure.SignatureFailure` | Wrong SecretId / SecretKey |
| `UnauthorizedOperation` / `OperationDenied.*` | The sub-user lacks DNSPod permissions |
| `Unable to find a Tencent Cloud DNS (DNSPod) zone` | The domain is not hosted on DNSPod under this Tencent Cloud account |
| `LimitExceeded.RecordTtlLimit` | Your plan does not support this TTL |

Add `-v` for verbose output; the full log is at `/var/log/letsencrypt/letsencrypt.log`.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest tests
```
