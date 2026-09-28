"""抓取前的 SSRF 守卫：判定一个 URL 是否"公网可达"。

## 为什么必须有这一层

导入的表格是**用户上传的任意内容**，而抓取动作由**服务器**发起。没有守卫时，
一张表里写 `http://169.254.169.254/latest/meta-data/`（云元数据）或
`http://redis:6379/`（容器内服务）就能让后端去请求内网 —— 这是典型 SSRF。

现成的 `job_agent/tools/url_safety.py` **不是** SSRF 守卫：它是"域名黑白名单 +
HEAD 探活"，且**未知域名明确放行**（`url_safety.py:79-80`）。它是给 ReAct 模型
用的**工具**，不适合直接当安全边界，故这里独立实现。

## 判定规则（任一不满足即拒绝）

1. scheme 只允许 `http` / `https`；
2. 不允许 URL 里内嵌账号密码（`http://user:pass@host/`，常用于绕过 host 解析）；
3. 主机名必须存在，且**必须带点**（挡掉 `localhost` / `redis` / `postgres` 这类
   容器内单标签名字 —— 它们在 docker 网络里可解析，是内网横向的首选目标）；
4. 主机名（或其 IP 字面量）解析出的**每一个** IP 都必须是公网地址；
5. 解析失败一律拒绝（宁可漏抓，不可内探）。

第 4 条覆盖了回环、内网、链路本地（含 `169.254.169.254` 云元数据）、保留、
组播、未指定，以及 IPv4-mapped IPv6（`::ffff:127.0.0.1`）。

**重定向要逐跳检查**：守卫只保证"这一个 URL"安全，被 302 到内网同样能完成 SSRF。
因此 `fetch.py` 自己处理跳转（`follow_redirects=False` + 每跳复检），不交给 httpx。

## 已知的**残余风险**（诚实标注，别误以为这套是"完全防住 SSRF"）

**DNS rebinding / TOCTOU**：守卫在这里解析一次域名、判定公网；httpx 真正建连时会
**再解析一次**。攻击者若控制权威 DNS，可以让两次解析给出不同结果（第一次公网骗过检查，
第二次内网完成请求）。彻底堵住要把校验通过的 IP **钉住**、直接连 IP 并带 `Host`
头（连接复用 + SNI 处理会变复杂）。

当前**没有**做这层加固，原因：本功能的输入是用户自己上传的岗位表（不是公开的多租户
表单），且执行者是本机部署的单个后端；把复杂度压在这里收益有限。**但如果你以后要把
导入功能开放给不受信的用户，必须先补上 IP 钉扎。** 这条写在这里，避免将来有人
把"有守卫"误读成"没有残余风险"。
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from loguru import logger

#: 只允许这两种 scheme（`file://` / `gopher://` / `data:` 都是经典 SSRF/本地读取载荷）
ALLOWED_SCHEMES = frozenset({"http", "https"})

#: 单标签主机名的后缀黑名单（多一层防御：即使 DNS 把 `.local` 解析成公网地址也拒绝）
_BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".localdomain")


@dataclass(frozen=True)
class UrlVerdict:
    """守卫结论。`ok=False` 时 `reason` 必定非空，可直接记进统计。"""

    ok: bool
    reason: str = ""
    host: str = ""
    ips: tuple[str, ...] = field(default_factory=tuple)


def _block_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """把一个 IP 归类；返回拒绝原因，公网地址返回 None。"""
    if ip.is_loopback:
        return "回环地址"
    if ip.is_link_local:
        return "链路本地地址（含云元数据 169.254.169.254）"
    if ip.is_private:
        return "内网地址"
    if ip.is_multicast:
        return "组播地址"
    if ip.is_reserved:
        return "保留地址"
    if ip.is_unspecified:
        return "未指定地址"
    if not ip.is_global:
        return "非公网地址"
    return None


def classify_ip(raw: str) -> str | None:
    """字符串 IP → 拒绝原因（公网返回 None，无法解析也返回原因）。

    IPv4-mapped IPv6（`::ffff:10.0.0.1`）先折叠回 IPv4 再判定 —— 否则
    `is_private` 看不穿这层包装，能直接绕过守卫。
    """
    try:
        ip = ipaddress.ip_address(raw.strip())
    except ValueError:
        return "无法解析为 IP"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return _block_reason(ip)


async def resolve_host(host: str) -> list[str]:
    """解析主机名 → 去重排序的 IP 列表（在线程池里跑，避免阻塞事件循环）。"""
    loop = asyncio.get_running_loop()
    infos = await loop.run_in_executor(
        None, lambda: socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    )
    return sorted({str(info[4][0]) for info in infos})


async def check_url(url: str, *, resolver=resolve_host) -> UrlVerdict:
    """判定 URL 是否允许抓取。`resolver` 可注入，便于测试不碰真实 DNS。"""
    text = (url or "").strip()
    if not text:
        return UrlVerdict(False, "空 URL")

    parts = urlsplit(text)
    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        return UrlVerdict(False, f"不允许的协议：{scheme or '(无)'}")

    if parts.username or parts.password:
        return UrlVerdict(False, "URL 内嵌账号密码")

    host = (parts.hostname or "").strip().lower()
    if not host:
        return UrlVerdict(False, "缺少主机名")

    if host.endswith(_BLOCKED_SUFFIXES):
        return UrlVerdict(False, f"内部域名后缀：{host}", host)

    # IP 字面量：直接判定，不去问 DNS（也避免 `http://0x7f.1/` 之类的花式写法歧义）
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        reason = classify_ip(host)
        if reason:
            return UrlVerdict(False, f"{reason}：{host}", host, (host,))
        return UrlVerdict(True, "IP 字面量且为公网地址", host, (host,))

    # 单标签主机名（localhost / redis / postgres）在 docker 网络里可解析 → 一律拒绝
    if "." not in host:
        return UrlVerdict(False, f"单标签主机名（疑似容器内服务）：{host}", host)

    try:
        ips = await resolver(host)
    except Exception as exc:  # noqa: BLE001 - DNS 失败种类多，统一拒绝
        logger.debug("SSRF 守卫：DNS 解析失败 | host={} | error={}", host, exc)
        return UrlVerdict(False, f"域名无法解析：{host}", host)

    if not ips:
        return UrlVerdict(False, f"域名无解析结果：{host}", host)

    for ip in ips:
        reason = classify_ip(ip)
        if reason:
            return UrlVerdict(False, f"{reason}：{host} → {ip}", host, tuple(ips))

    return UrlVerdict(True, "公网地址", host, tuple(ips))


__all__ = ["ALLOWED_SCHEMES", "UrlVerdict", "check_url", "classify_ip", "resolve_host"]
