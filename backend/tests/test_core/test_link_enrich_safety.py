"""B3-1 SSRF 守卫：判定哪些 URL 允许服务器去抓。

这是本批**最重要的安全件**：导入的表格是用户上传的任意内容，而抓取由服务器发起。
没有守卫时，一张表里写 `http://169.254.169.254/latest/meta-data/`（云元数据）或
`http://redis:6379/`（容器内服务）就能让后端去探内网。

用法要点：`check_url(url, resolver=...)` 的 resolver 可注入 —— 这些用例**不碰真实
DNS**，否则结果会随网络环境漂移（在能解析 `foo.local` 的内网里测试会假绿）。
"""

from __future__ import annotations

import pytest
from app.core.link_enrich.safety import check_url, classify_ip


def _resolver(mapping: dict[str, list[str]]):
    """构造一个假 DNS：只认 mapping 里的主机名。"""

    async def _resolve(host: str) -> list[str]:
        if host not in mapping:
            raise OSError(f"unknown host {host}")
        return mapping[host]

    return _resolve


PUBLIC = _resolver({"jobs.example.com": ["93.184.216.34"], "multi.example.com": ["93.184.216.34", "10.0.0.5"]})


class TestClassifyIp:
    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",        # 回环
            "10.1.2.3",         # 内网 A 段
            "172.16.5.5",       # 内网 B 段
            "192.168.1.1",      # 内网 C 段
            "169.254.169.254",  # 云元数据（链路本地）
            "0.0.0.0",          # 未指定
            "224.0.0.1",        # 组播
            "::1",              # IPv6 回环
            "fe80::1",          # IPv6 链路本地
            "fc00::1",          # IPv6 唯一本地
            "::ffff:127.0.0.1", # IPv4-mapped 回环（包装一层就想绕过）
            "::ffff:10.0.0.1",  # IPv4-mapped 内网
        ],
    )
    def test_private_and_special_addresses_are_rejected(self, ip):
        assert classify_ip(ip) is not None

    @pytest.mark.parametrize("ip", ["8.8.8.8", "93.184.216.34", "1.1.1.1", "2606:4700::1111"])
    def test_public_addresses_pass(self, ip):
        assert classify_ip(ip) is None

    def test_unparseable(self):
        assert classify_ip("not-an-ip") is not None


class TestCheckUrlSchemes:
    async def test_https_and_http_allowed(self):
        assert (await check_url("https://jobs.example.com/x", resolver=PUBLIC)).ok
        assert (await check_url("http://jobs.example.com/x", resolver=PUBLIC)).ok

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://a.com/x",
            "gopher://a.com/x",
            "data:text/html,x",
            "javascript:alert(1)",
        ],
    )
    async def test_non_http_schemes_rejected(self, url):
        verdict = await check_url(url, resolver=PUBLIC)
        assert not verdict.ok
        assert "协议" in verdict.reason

    async def test_empty_url_rejected(self):
        assert not (await check_url("", resolver=PUBLIC)).ok

    async def test_embedded_credentials_rejected(self):
        # http://user:pass@host 常用于让解析器认错 host
        verdict = await check_url("https://user:pass@jobs.example.com/x", resolver=PUBLIC)
        assert not verdict.ok
        assert "账号密码" in verdict.reason


class TestCheckUrlHosts:
    async def test_single_label_hostnames_rejected(self):
        # localhost / redis / postgres 在 docker 网络里可解析 —— 内网横向首选目标
        for host in ("localhost", "redis", "postgres", "career_backend"):
            verdict = await check_url(f"http://{host}:6379/", resolver=PUBLIC)
            assert not verdict.ok, host
            assert "单标签" in verdict.reason

    async def test_internal_suffix_rejected(self):
        verdict = await check_url("http://printer.local/", resolver=PUBLIC)
        assert not verdict.ok

    async def test_host_resolving_to_private_ip_rejected(self):
        # 域名看着人畜无害，DNS 指向内网 —— 只查字符串黑名单的实现会在这里放过
        resolver = _resolver({"evil.example.com": ["10.0.0.7"]})
        verdict = await check_url("https://evil.example.com/x", resolver=resolver)
        assert not verdict.ok
        assert "内网" in verdict.reason

    async def test_one_bad_ip_among_many_rejects_the_whole_host(self):
        # 多 A 记录里只要有一个内网，就不能抓（否则等于随机内探）
        verdict = await check_url("https://multi.example.com/x", resolver=PUBLIC)
        assert not verdict.ok

    async def test_ip_literal_public_ok_private_rejected(self):
        assert (await check_url("https://93.184.216.34/x", resolver=PUBLIC)).ok
        verdict = await check_url("http://169.254.169.254/latest/meta-data/", resolver=PUBLIC)
        assert not verdict.ok

    async def test_dns_failure_rejected(self):
        verdict = await check_url("https://nonexistent.example.com/x", resolver=PUBLIC)
        assert not verdict.ok
        assert "无法解析" in verdict.reason

    async def test_verdict_carries_host_and_ips(self):
        verdict = await check_url("https://jobs.example.com/x", resolver=PUBLIC)
        assert verdict.host == "jobs.example.com"
        assert verdict.ips == ("93.184.216.34",)
