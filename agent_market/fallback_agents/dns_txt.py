"""TXT records through this machine's own resolver, with the standard library only (agent team 11-17; dnspython is not
in the release environments). Used by the dns-spf-dmarc substitute (dns.mail_auth.v1).

One question per name (QTYPE TXT, recursion desired) over UDP to the first nameserver in /etc/resolv.conf; a
truncated answer is asked again over TCP. Only the answer section is read; TXT strings of every record in it are
returned (a CNAME chain answered by the resolver is followed by it, not by us). NXDOMAIN and NOERROR without TXT are
both "no records". Nothing but the question is sent, and nothing is cached here (the agent caches answers).
"""
from __future__ import annotations

import ipaddress
import secrets
import socket
import struct

RESOLV_CONF = "/etc/resolv.conf"
TXT, CLASS_IN = 16, 1
MAX_UDP = 4096


class DnsError(OSError):
    """The resolver did not answer usefully (timeout, SERVFAIL, REFUSED or a malformed answer)."""


def nameserver(path: str = RESOLV_CONF) -> str:
    """The first nameserver of this machine's resolver configuration (our own resolver, never one a caller names)."""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    ipaddress.ip_address(parts[1].split("%")[0])
                    return parts[1].split("%")[0]
    except (OSError, ValueError):
        pass
    return "127.0.0.1"


def query(name: str) -> tuple[bytes, int]:
    ident = secrets.randbits(16)
    header = struct.pack(">HHHHHH", ident, 0x0100, 1, 0, 0, 0)   # recursion desired, one question
    labels = b"".join(bytes([len(p)]) + p.encode("ascii") for p in name.rstrip(".").split("."))
    return header + labels + b"\x00" + struct.pack(">HH", TXT, CLASS_IN), ident


def _skip_name(msg: bytes, i: int) -> int:
    for _ in range(128):
        if i >= len(msg):
            raise DnsError("malformed answer")
        n = msg[i]
        if n == 0:
            return i + 1
        if n & 0xC0 == 0xC0:
            return i + 2
        i += 1 + n
    raise DnsError("malformed answer")


def parse(msg: bytes, ident: int) -> tuple[list[str], bool]:
    """(TXT strings in the answer, truncated). NXDOMAIN is an empty list; other error codes raise."""
    if len(msg) < 12:
        raise DnsError("short answer")
    rid, flags, qd, an, _ns, _ar = struct.unpack(">HHHHHH", msg[:12])
    if rid != ident:
        raise DnsError("answer for another question")
    truncated = bool(flags & 0x0200)
    rcode = flags & 0x000F
    if rcode == 3:
        return [], truncated
    if rcode != 0:
        raise DnsError(f"resolver error {rcode}")
    i = 12
    for _ in range(qd):
        i = _skip_name(msg, i) + 4
    out = []
    for _ in range(an):
        i = _skip_name(msg, i)
        if i + 10 > len(msg):
            raise DnsError("malformed answer")
        rtype, _cls, _ttl, length = struct.unpack(">HHIH", msg[i:i + 10])
        i += 10
        data = msg[i:i + length]
        i += length
        if rtype != TXT:
            continue
        j, parts = 0, []
        while j < len(data):
            n = data[j]
            parts.append(data[j + 1:j + 1 + n].decode("utf-8", "replace"))
            j += 1 + n
        out.append("".join(parts))
    return out, truncated


def txt(name: str, timeout: float = 3.0, server: str | None = None, udp=None, tcp=None) -> list[str]:
    """TXT strings for NAME. UDP first, TCP when the answer is truncated."""
    server = server or nameserver()
    family = socket.AF_INET6 if ":" in server else socket.AF_INET
    packet, ident = query(name)
    send_udp = udp or _udp
    answers, truncated = parse(send_udp(packet, server, family, timeout), ident)
    if truncated:
        answers, _ = parse((tcp or _tcp)(packet, server, family, timeout), ident)
    return answers


def _udp(packet: bytes, server: str, family, timeout: float) -> bytes:
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.sendto(packet, (server, 53))
            data, _ = sock.recvfrom(MAX_UDP)
        except OSError as exc:
            raise DnsError("the resolver did not answer") from exc
    return data


def _tcp(packet: bytes, server: str, family, timeout: float) -> bytes:
    try:
        with socket.create_connection((server, 53), timeout=timeout) as sock:
            sock.sendall(struct.pack(">H", len(packet)) + packet)
            head = _read(sock, 2)
            return _read(sock, struct.unpack(">H", head)[0])
    except OSError as exc:
        raise DnsError("the resolver did not answer over TCP") from exc


def _read(sock, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise DnsError("short TCP answer")
        buf += chunk
    return buf

