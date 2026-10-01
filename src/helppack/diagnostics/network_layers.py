from __future__ import annotations

import ipaddress
import secrets
import socket
import ssl
import struct
import urllib.error
import urllib.parse
import urllib.request

import psutil

from .investigation import Finding, Investigation, query, rows
from .runner import CommandRunner


def validate_target(value: str) -> tuple[str, str]:
    parsed = urllib.parse.urlsplit(value if "://" in value else "https://" + value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("请输入不含账号、密码、查询参数或片段的 HTTPS 网址")
    try:
        port = parsed.port
        host = parsed.hostname.encode("idna").decode("ascii")
    except (ValueError, UnicodeError) as exc:
        raise ValueError("网址或端口格式无效") from exc
    if port not in (None, 443):
        raise ValueError("此检查只访问标准 HTTPS 端口 443")
    if len(host) > 253 or any(not label or len(label) > 63 or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in label.lower()) for label in host.split(".")):
        raise ValueError("请输入合法域名，不支持带命令或 IPv6 字面量的输入")
    return urllib.parse.urlunsplit(("https", host, parsed.path or "/", "", "")), host


def _skip_name(packet: bytes, offset: int) -> int:
    for _ in range(128):
        if offset >= len(packet):
            raise ValueError("DNS 响应截断")
        size = packet[offset]
        if size & 0xC0 == 0xC0:
            if offset + 1 >= len(packet):
                raise ValueError("DNS 指针截断")
            return offset + 2
        if size & 0xC0:
            raise ValueError("DNS 标签无效")
        offset += 1
        if size == 0:
            return offset
        offset += size
    raise ValueError("DNS 名称过长")


def parse_dns(packet: bytes, request_id: int) -> list[str]:
    if len(packet) < 12:
        raise ValueError("DNS 响应过短")
    ident, flags, questions, answers, _, _ = struct.unpack("!6H", packet[:12])
    if ident != request_id or not flags & 0x8000 or flags & 0xF or flags & 0x200:
        raise ValueError("DNS 响应不匹配、解析失败或被截断")
    if questions != 1 or answers > 256:
        raise ValueError("DNS 响应计数异常")
    offset = _skip_name(packet, 12) + 4
    values = []
    for _ in range(answers):
        offset = _skip_name(packet, offset)
        if offset + 10 > len(packet):
            raise ValueError("DNS 记录截断")
        kind, klass, _, size = struct.unpack("!HHIH", packet[offset:offset + 10])
        offset += 10
        data = packet[offset:offset + size]
        if len(data) != size:
            raise ValueError("DNS 数据截断")
        if klass == 1 and (kind, size) in {(1, 4), (28, 16)}:
            values.append(str(ipaddress.ip_address(data)))
        offset += size
    return sorted(set(values))


def explicit_dns(host: str, server: str, timeout: float = 3) -> list[str]:
    address = ipaddress.ip_address(server)
    # UDP queries disclose only the chosen domain, never change system DNS.
    name = b"".join(bytes([len(label)]) + label.encode("ascii") for label in host.split(".")) + b"\0"
    result = []
    for kind in (1, 28):
        ident = secrets.randbelow(65536)
        packet = struct.pack("!6H", ident, 0x100, 1, 0, 0, 0) + name + struct.pack("!HH", kind, 1)
        with socket.socket(socket.AF_INET6 if address.version == 6 else socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.connect((str(address), 53))
            sock.send(packet)
            response = sock.recv(65535)
            # A truncated UDP response needs TCP rather than being misclassified.
            if len(response) >= 4 and struct.unpack("!H", response[2:4])[0] & 0x200:
                with socket.create_connection((str(address), 53), timeout=timeout) as stream:
                    stream.sendall(struct.pack("!H", len(packet)) + packet)
                    def receive(size):
                        chunks = b""
                        while len(chunks) < size:
                            part = stream.recv(size - len(chunks))
                            if not part:
                                raise ValueError("DNS TCP 响应截断")
                            chunks += part
                        return chunks
                    length = struct.unpack("!H", receive(2))[0]
                    response = receive(length)
            result.extend(parse_dns(response, ident))
    return sorted(set(result))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Do not silently send diagnostics to a different service.


def probe_https(url: str, direct: bool, timeout: float = 6) -> tuple[bool, str]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({} if direct else None),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    try:
        with opener.open(urllib.request.Request(url, method="HEAD", headers={"User-Agent": "HelpPack"}), timeout=timeout) as response:
            return True, f"完成证书校验及 HTTP 响应：{response.status}"
    except urllib.error.HTTPError as exc:
        if exc.code == 407:
            return False, "代理要求身份验证（HTTP 407），未验证目标服务连接；不收集代理密码。"
        # A 403/404/redirect is server evidence, not evidence of DNS failure.
        return True, f"已收到 HTTP {exc.code}（服务拒绝/重定向不等于网络断开）"
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return False, f"连接失败：{type(exc).__name__}；尚未定位 DNS/代理/TLS/防火墙具体原因"


def investigate_network(target: str, dns_server: str, cancel, progress, runner=None,
                        resolver=None, dns_query=explicit_dns, https=probe_https) -> Investigation:
    url, host = validate_target(target)
    if dns_server:
        ipaddress.ip_address(dns_server)
    runner = runner or CommandRunner()
    output = Investigation("网络分层定位", f"目标域名：{host}")
    def step(percent, name):
        if cancel.is_set():
            raise InterruptedError("检查已取消")
        progress(percent, name)
    step(5, "网络适配器")
    try:
        stats = psutil.net_if_stats()
        up = [name for name, value in stats.items() if value.isup and "loopback" not in name.lower()]
        output.findings.append(Finding("适配器", "已读取" if up else "未检测到活动接口", "、".join(up) or "没有活动接口证据；优先检查适配器连接状态"))
    except OSError:
        output.findings.append(Finding("适配器", "无法读取", "系统接口受限，继续检查其他层"))
    step(15, "默认网关")
    try:
        gateways = rows(query(runner, "Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | Select-Object -First 3 NextHop | ConvertTo-Json -Compress"))
        details = []
        for gateway in gateways:
            address = str(ipaddress.ip_address(gateway["NextHop"]))
            answer = runner.run(["ping.exe", "-n", "1", "-w", "1000", address], timeout=3)
            details.append("响应" if answer.returncode == 0 else "未响应（可能禁用 ICMP）")
        output.findings.append(Finding("网关", "已检查" if details else "未知", "；".join(details) or "未获取默认路由"))
    except (OSError, ValueError, KeyError, TimeoutError):
        output.findings.append(Finding("网关", "无法读取", "权限/接口限制；不据此判断网络故障"))
    step(35, "系统 DNS 与用户指定 DNS")
    system = None
    specified = None
    try:
        system = sorted(set(resolver(host) if resolver else [r[4][0] for r in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]))
        output.findings.append(Finding("系统 DNS", "有结果" if system else "无结果", "、".join(system)))
    except OSError:
        output.findings.append(Finding("系统 DNS", "解析失败", "本次目标域名解析失败"))
    if dns_server:
        try:
            specified = dns_query(host, dns_server)
            output.findings.append(Finding("指定 DNS", "有结果" if specified else "无地址结果", "、".join(specified)))
        except (OSError, ValueError):
            output.findings.append(Finding("指定 DNS", "未获得结果", "指定服务器超时、拒绝或返回无法解析的响应；不改变系统设置"))
    if not system and specified:
        output.recommendations.append("指定 DNS 可解析而系统 DNS 失败，优先检查系统解析器、DNS 服务器及缓存；这不是确定原因。")
    elif system is not None and specified is not None and set(system) != set(specified):
        output.recommendations.append("两条解析路径结果不同；CDN、区域、缓存也会产生差异，不能仅据此断言 DNS 污染。")
    elif not system:
        output.recommendations.append("系统 DNS 层本次未取得解析证据，先核对该域名及系统 DNS；也可能是域名不存在，不能认定整机断网。")
    step(60, "代理与直连 HTTPS 对照")
    proxies = urllib.request.getproxies()
    bypass = urllib.request.proxy_bypass(host)
    output.findings.append(Finding("代理", "存在静态代理" if proxies else "未获得静态代理", f"使用系统/环境静态代理路径；目标是否绕过代理：{bypass}。PAC/WPAD 不由 urllib 执行，不能代表浏览器全部代理行为。"))
    direct_ok, direct_detail = https(url, True)
    step(80, "默认代理路径与目标服务")
    configured_ok, configured_detail = https(url, False)
    output.findings += [Finding("直连 HTTPS", "可达" if direct_ok else "失败", direct_detail),
                        Finding("默认静态代理路径 HTTPS", "可达" if configured_ok else "失败", configured_detail)]
    if direct_ok != configured_ok:
        output.recommendations.append("直连与默认静态代理路径结果不同，优先检查代理/绕过列表；一次差异不能证明代理就是根因。")
    if direct_ok or configured_ok:
        output.findings.append(Finding("目标服务", "收到 HTTP 响应", "目标连接层有响应；登录、页面脚本、下载和具体服务功能尚未验证。"))
    else:
        output.findings.append(Finding("目标服务", "无法验证", "连接路径失败，不能断言目标服务宕机。"))
        output.recommendations.append("若解析成功但 HTTPS 失败，核对系统时间、证书、代理/防火墙和目标可用性；不要关闭证书校验。")
    output.recommendations.append("结果仅针对本次目标；请结合其他网站及故障发生时间复查。")
    step(100, "检查完成")
    return output
