# 阿里云 ECS 部署指南

针对你当前这台实例：Ubuntu 24.04 LTS，香港地域，公网 IP `47.76.124.212`，2核4G。

> 试用额度到 2026-11-15 到期，之后会按量计费，记得到时候处理（转包年包月或释放实例）。香港地域访问 GitHub / PyPI / Hugging Face（`sentence-transformers` 首次运行要下模型）通常比内地地域顺畅，不用担心被墙。

## 0. SSH 登录

```bash
ssh root@47.76.124.212
```

阿里云镜像默认允许 root 直接登录（创建实例时设置的密码）。后面命令都假设你是 root，如果不是就把 `sudo` 加回去。

## 1. 安装基础环境

Ubuntu 24.04 自带 Python 3.12，`requirements.txt` 里的包都不需要指定 Python 版本，直接用系统自带的即可。

```bash
apt update
apt install -y python3 python3-venv python3-pip git nginx
```

## 2. 拉取代码 & 建虚拟环境

```bash
mkdir -p /opt/stock-assistant
git clone https://github.com/yixiao-ling/stock-assistant.git /opt/stock-assistant
cd /opt/stock-assistant

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 2.5 安装 TradingAgents 深度研究引擎

深度研究标签页跑的是 TradingAgents（LangGraph 12-agent 流程），单独一个仓库，`pip install -e` 引入，不 vendor 进 stock-assistant（保留跟上游同步的能力）。用的是打了 `sa-integration` 补丁分支的 fork，不是原始上游仓库。

```bash
git clone -b sa-integration https://github.com/yixiao-ling/TradingAgents.git /opt/tradingagents
/opt/stock-assistant/venv/bin/pip install -e /opt/tradingagents
```

**不要用 `uv sync`**——TradingAgents 里的 `uv.lock` 是陈旧产物（钉的是旧版本，会装出一棵完全不同、体积大得多的依赖树，混了 chainlit 和几十个 opentelemetry 包）。只用上面的 `pip install -e .`，读的是 `pyproject.toml`，是对的。

这一步会新增约 180-250MB 依赖（langgraph、langchain-* 系列、stockstats 等）。40GB 系统盘完全够用。

## 3. 配置环境变量

```bash
cp .env.example .env
vi .env
```

需要填：
- `DEEPSEEK_API_KEY`、`NEWS_API_KEY`（原有的）
- `SA_DEEP_TOKEN`——深度研究接口的访问口令，本地生成一个复制过去：
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(24))"
  ```
  这个口令之后要在浏览器「深度研究」标签页第一次使用时手动输入一次（存 localStorage），不需要写进前端代码。

## 4. 配置 systemd 服务

```bash
cp deploy/stock-assistant.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now stock-assistant
systemctl status stock-assistant   # 确认 active (running)
```

日志查看：`journalctl -u stock-assistant -f`

服务文件里设了 `TA_HOME=/opt/stock-assistant/var/tradingagents`（深度研究的结果日志/行情缓存/决策记忆都落在这里，不用默认的 `~/.tradingagents`——root 用户下那会落进 `/root/`，不在你会想到备份的地方）和 `MemoryMax=3G`（超出就让单个请求响亮失败，而不是让 OOM killer 把 nginx 一起带走）。

## 4.5 加一块 Swap（深度研究的内存保险）

阿里云 ECS 默认不带 swap。2核4G 跑深度研究时峰值内存预估 1.5-2.2GB，稳态+空闲余量不算特别宽裕，加 2GB swap 作为廉价保险：

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab   # 开机自动挂载
free -h   # 确认 Swap 那一行显示 2.0Gi
```

## 5. 配置 Nginx 反向代理

```bash
cp deploy/nginx.conf /etc/nginx/sites-available/stock-assistant
ln -s /etc/nginx/sites-available/stock-assistant /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default   # 避免默认站点冲突

nginx -t && systemctl enable --now nginx && systemctl reload nginx
```

这份 nginx 配置里有两个 `location` block：`/deep/stream/` 单独配置了 `proxy_buffering off`（深度研究进度用 SSE 推送，缺了这行会导致进度条卡住不动、事件全部堆到最后一次性吐出——这是最容易踩的坑），其余走默认的 `location /`。

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

这个项目现在是两个仓库，看你改的是哪部分：

```bash
# stock-assistant 本身（前端/API/agents）
cd /opt/stock-assistant
git pull
source venv/bin/activate
pip install -r requirements.txt   # 依赖有变化时执行
systemctl restart stock-assistant

# TradingAgents 深度引擎（如果 sa-integration 分支有更新）
cd /opt/tradingagents
git pull
systemctl restart stock-assistant   # pip install -e 是软链接，改完 TA 代码不用重新 pip install，重启进程即可生效
```

## 部署后验证

```bash
systemctl status stock-assistant           # active (running)
free -h                                    # Swap 2.0Gi 已生效
curl -I http://127.0.0.1:8000/             # 200
```

浏览器打开深度研究标签页跑一次，跑的过程中另开个终端确认站点没被阻塞（证明没有阻塞调用漏进事件循环）：

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/portfolio
```

深度运行期间这条应该照常返回 200，不应该卡住。

## 注意事项

- `chroma_db/`（财报 RAG 索引）和 `var/tradingagents/memory/trading_memory.md`（深度研究的决策复盘记忆）是仅有的两处**不可再生**数据，随 ECS 磁盘持久化，建议定期备份这两处；`var/tradingagents/` 下的 `logs/`、`cache/` 都是可重新生成的中间产物。
- `data/portfolio/mock_data.json` 是 mock 持仓数据，如需修改直接编辑该文件后重启服务。
- `var/tradingagents/cache/` 里的行情 CSV 文件名带当天日期，每天每个 symbol 新增一份且不自动淘汰，建议加个每周清理的 cron：
  ```bash
  # crontab -e
  0 3 * * 0 find /opt/stock-assistant/var/tradingagents/cache -name '*.csv' -mtime +7 -delete
  ```
- 2核4G 对这个项目基础功能（分析/辩论/持仓/RAG）够用；深度研究单次耗时 4-8 分钟、成本约 $0.05-0.2，接口已加 `SA_DEEP_TOKEN` 口令保护，且同一时间只允许跑一个（返回 409），避免并发把内存或账单打爆。
