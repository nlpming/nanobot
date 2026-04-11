# Python SSL 证书验证失败修复指南

## 问题现象

启动 nanobot 连接飞书等外部服务时，报如下错误：

```
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain (_ssl.c:1081)
```

连接会持续失败并不断重试。

## 原因分析

macOS 上通过官方安装包（python.org）安装的 Python **不自带系统根证书**。Python 使用 OpenSSL 独立的证书存储路径，而非系统钥匙串，安装后该路径下 `cert.pem` 文件缺失，导致所有 HTTPS/WSS 连接的证书验证都会失败。

可以通过以下命令确认：

```bash
python3 -c "import ssl; print(ssl.get_default_verify_paths())"
```

如果输出中 `cafile=None`，且对应的 `openssl_cafile` 路径下文件不存在，则说明证书缺失。

## 修复方法

### 方法一：运行官方证书安装脚本（推荐）

Python 官方安装包自带了证书安装脚本，运行即可：

```bash
# 将 3.xx 替换为你的 Python 版本号
/Applications/Python\ 3.xx/Install\ Certificates.command
```

该脚本会安装 `certifi` 包并将其证书文件软链接到 Python 的 OpenSSL 目录。

### 方法二：通过环境变量指定证书

如果你有自定义的 CA 证书文件（如企业内网 CA），可以通过环境变量指定：

```bash
export REQUESTS_CA_BUNDLE=/path/to/ca-bundle.pem
export SSL_CERT_FILE=/path/to/ca-bundle.pem
```

将以上内容加入 `~/.zshrc` 或 `~/.bashrc` 可永久生效。

### 方法三：手动安装 certifi 并创建软链接

```bash
pip install --upgrade certifi

# 查看 certifi 证书路径
python3 -c "import certifi; print(certifi.where())"

# 查看 Python 期望的证书路径
python3 -c "import ssl; print(ssl.get_default_verify_paths().openssl_cafile)"

# 创建软链接（将下面的路径替换为实际输出）
ln -s /path/to/certifi/cacert.pem /path/to/openssl/cert.pem
```

## 验证修复

```bash
python3 -c "import ssl, urllib.request; urllib.request.urlopen('https://open.feishu.cn'); print('SSL verification OK')"
```

输出 `SSL verification OK` 即表示修复成功。
