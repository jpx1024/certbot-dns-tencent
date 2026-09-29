# certbot-dns-tencent

中文 | [English](README.en.md)

腾讯云 DNS（DNSPod）的 Certbot DNS 认证插件，用法与 `certbot-dns-cloudflare` / `certbot-dns-google` 相同：
通过 DNSPod API 3.0 自动添加、删除 `_acme-challenge` TXT 记录，完成 `dns-01` 验证。支持通配符证书和自动续期。

- 直接调用 DNSPod API 3.0（TC3-HMAC-SHA256 签名），只依赖 `certbot` 和 `requests`，不需要安装腾讯云 SDK
- 自动找到域名所在的 DNSPod 解析域（按最长后缀匹配，支持子域名单独托管）
- 通配符证书和根域名共用同一个 `_acme-challenge` 记录名时，能正确处理多条 TXT 记录；清理时按记录 ID 精确删除

## 1. 准备腾讯云 API 密钥

1. 打开 [访问管理 → 用户](https://console.cloud.tencent.com/cam)，新建一个**子用户**，访问方式选“编程访问”
2. 只给它授予 `QcloudDNSPodFullAccess` 策略
3. 记下 `SecretId` 和 `SecretKey`

不要使用主账号密钥。

## 2. 安装

### 方式一：给 apt 安装的 certbot 加插件（Ubuntu / Debian）

插件是纯 Python 包，只依赖 `certbot` 和 `requests`，这两个 apt 已经装好了。
把 wheel 解压到系统 Python 的 `/usr/local` 目录即可，不需要 pip，也不会影响 apt 管理的包：

```bash
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
sudo mkdir -p /usr/local/lib/python$PYVER/dist-packages
sudo python3 -m zipfile -e certbot_dns_tencent-0.1.0-py3-none-any.whl /usr/local/lib/python$PYVER/dist-packages/
sudo certbot plugins   # 列表中应出现 dns-tencent
```

这样系统自带的 `certbot.timer` 会直接用这个插件续期，不用再配置定时任务。
卸载：删除该目录下的 `certbot_dns_tencent` 和 `certbot_dns_tencent-0.1.0.dist-info`。

### 方式二：独立虚拟环境

把 certbot 和插件一起装进单独的虚拟环境（以 root 执行）：

```bash
python3 -m venv /opt/certbot
/opt/certbot/bin/pip install --upgrade pip
/opt/certbot/bin/pip install certbot ./certbot_dns_tencent-0.1.0-py3-none-any.whl
ln -sf /opt/certbot/bin/certbot /usr/local/bin/certbot
certbot plugins   # 列表中应出现 dns-tencent
```

也可以用源码安装：`/opt/certbot/bin/pip install /path/to/certbot-dns-tencent`。

> 通过 snap 安装的 certbot 无法加载外部插件，这种情况请用方式二另装一份，并停用 snap 的续期定时任务（见第 5 步）。

## 3. 配置凭据

```bash
mkdir -p /root/.secrets/certbot
cat > /root/.secrets/certbot/tencent.ini <<'EOF'
dns_tencent_secret_id = your-secret-id
dns_tencent_secret_key = your-secret-key
EOF
chmod 600 /root/.secrets/certbot/tencent.ini
```

## 4. 签发证书

```bash
certbot certonly \
  --authenticator dns-tencent \
  --dns-tencent-credentials /root/.secrets/certbot/tencent.ini \
  --cert-name example.com \
  -d example.com -d '*.example.com' \
  --deploy-hook 'systemctl reload nginx'
```

`--cert-name` 与原证书名相同时，certbot 会在原来的证书目录上续签，并把认证方式从 `manual` 改为 `dns-tencent`，
Nginx 里的证书路径 `/etc/letsencrypt/live/example.com/` 无需修改。先加 `--dry-run` 跑一遍测试环境更稳妥。

参数：

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--dns-tencent-credentials` | 凭据 INI 文件路径（必填） | — |
| `--dns-tencent-propagation-seconds` | 添加记录后等待多少秒再让 CA 验证 | 30 |

记录 TTL 为 600 秒，这是 DNSPod 免费版允许的最小值。

## 5. 自动续期

```bash
certbot renew --dry-run
```

用方式一安装的，系统自带的 `certbot.timer` 已经会定时续期，到这里就完成了。

用方式二安装的，需要自己添加定时任务（如果旧的 snap/apt certbot 有 `certbot.timer`，先执行 `systemctl disable --now certbot.timer snap.certbot.renew.timer`）：

```bash
echo '0 3 * * * root /opt/certbot/bin/certbot renew -q' > /etc/cron.d/certbot-renew
```

签发时指定的 `--deploy-hook` 会保存在续期配置里，续期成功后会自动 reload Nginx。

## 常见错误

| 错误码 | 原因 |
| --- | --- |
| `AuthFailure.SecretIdNotFound` / `AuthFailure.SignatureFailure` | SecretId / SecretKey 填错 |
| `UnauthorizedOperation` / `OperationDenied.*` | 子用户缺少 DNSPod 权限 |
| `Unable to find a Tencent Cloud DNS (DNSPod) zone` | 域名没有托管在这个腾讯云账号的 DNSPod 下 |
| `LimitExceeded.RecordTtlLimit` | 套餐不支持该 TTL |

加 `-v` 查看详细日志：`/var/log/letsencrypt/letsencrypt.log`。

## 开发

```bash
python -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest tests
```
