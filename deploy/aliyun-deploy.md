# 阿里云 ECS 部署指南

针对你当前这台实例：Ubuntu 24.04 LTS，香港地域，公网 IP `47.76.124.212`，2核4G。

> 试用额度到 2026-11-15 到期，之后会按量计费，记得到时候处理（转包年包月或释放实例）。香港地域访问 GitHub / PyPI / Hugging Face（`sentence-transformers` 首次运行要下模型）通常比内地地域顺畅，不用担心被墙。

## 0. SSH 登录

```bash
ssh root@47.76.124.212
```

阿里云镜像默认允许 root 直接登录（创建实例时设置的密码）。后面命令都假设你是 root，如果不是就把 `sudo` 加回去。

## 1. 安装基础环境

Ubuntu 24.04 自带 Python 3.12，`requirements.txt` 里的包都不需要指定 Python 版本，直接用系统自带的即可，不用像之前那样折腾版本安装。

```bash
apt update
apt install -y python3 python3-venv python3-pip git nginx
```

## 2. 拉取代码 & 建虚拟环境

```bash
mkdir -p /opt/stock-assistant
git clone <你的仓库地址> /opt/stock-assistant
cd /opt/stock-assistant

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 3. 配置环境变量

```bash
cp .env.example .env
vi .env   # 填入 ANTHROPIC_API_KEY 和 NEWS_API_KEY
```

## 4. 配置 systemd 服务

```bash
cp deploy/stock-assistant.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now stock-assistant
systemctl status stock-assistant   # 确认 active (running)
```

日志查看：`journalctl -u stock-assistant -f`

## 5. 配置 Nginx 反向代理

```bash
cp deploy/nginx.conf /etc/nginx/sites-available/stock-assistant
ln -s /etc/nginx/sites-available/stock-assistant /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default   # 避免默认站点冲突

nginx -t && systemctl enable --now nginx && systemctl reload nginx
```

Ubuntu 24.04 默认没启用 `ufw` 防火墙，一般不用额外处理；如果你手动开过 `ufw`，记得放行 80：

```bash
ufw allow 80/tcp
```

此时浏览器访问 `http://47.76.124.212` 应该能看到页面。

## 6. 开放安全组端口（云端防火墙，容易漏掉的一步）

阿里云控制台 → 该 ECS 实例 → **网络与安全组** → 安全组规则，入方向放行 TCP 80（以及要配 HTTPS 的话放行 443）。这一步和上面本机防火墙是两道独立的防火墙，缺一不可。

## 7.（可选）HTTPS

需要先有一个域名并解析到 `47.76.124.212`（纯 IP 无法申请证书）。

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d your_domain.com
```

## 更新代码后如何重启

```bash
cd /opt/stock-assistant
git pull
source venv/bin/activate
pip install -r requirements.txt   # 依赖有变化时执行
systemctl restart stock-assistant
```

## 注意事项

- `chroma_db/` 目录是本地文件存储，随 ECS 磁盘持久化，不会像部分 PaaS 免费层那样重启丢数据。
- `data/portfolio/mock_data.json` 是 mock 持仓数据，如需修改直接编辑该文件后重启服务。
- 2核4G 对这个项目够用，`sentence-transformers` 首次加载模型没问题。
