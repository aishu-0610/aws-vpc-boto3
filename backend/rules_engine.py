"""
dns_engine.py  —  FocusGate Core DNS Proxy
Developer A owns this file.

How DNS works (interview version):
  When you type "youtube.com" your OS sends a UDP datagram to port 53
  of your configured DNS resolver containing a binary DNS query:
    Bytes 0-1  : Transaction ID (echo'd back in response)
    Bytes 2-3  : Flags (QR, OPCODE, AA, TC, RD, RA, RCODE)
    Bytes 4-11 : Counts for questions/answers/authority/additional sections
    Question   : QNAME (length-prefixed labels), QTYPE (A=1), QCLASS (IN=1)

  We intercept this at 127.0.0.1:DNS_PORT.
  For blocked domains  → return NXDOMAIN (RCODE=3)  in <0.5 ms
  For allowed domains  → forward to Cloudflare DoH and return real answer

NXDOMAIN vs 0.0.0.0 sinkhole:
  NXDOMAIN = "domain does not exist" — browser shows DNS_PROBE_FINISHED_NXDOMAIN
  Sinkhole  = return 0.0.0.0 — browser tries to connect, hangs briefly
  We use NXDOMAIN: cleaner, faster, no connection attempts.

DNS-over-HTTPS (DoH):
  Instead of forwarding plain UDP (visible to ISP/network), we wrap
  the raw DNS wire-format bytes in a GET request to:
    https://cloudflare-dns.com/dns-query?dns=<base64url-encoded-query>
  The response body is the raw DNS wire-format answer.
  This keeps the forwarded queries encrypted and private.

Performance:
  Each query handled in its own daemon thread.
  Logging to SQLite is async (fire-and-forget thread).
  Blocked domain latency: 0.1–0.5 ms (no network round trip).
  Allowed domain latency: ~10–15 ms (Cloudflare DoH RTT).

Usage:
  sudo python backend/dns_engine.py          # port 53 (production)
  DNS_PORT=5353 python backend/dns_engine.py # port 5353 (dev, no sudo)
"""

import os
import socket
import threading
import time
import base64
import logging
import sys

import dnslib
import httpx

# Allow running as __main__ from project root
sys.path.insert(0, os.path.dirname(__file__))

from db import init_db, seed_blocklist, log_query
from rules_engine import RulesEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [DNS] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DNS_HOST    = "0.0.0.0"
DNS_PORT    = int(os.environ.get("DNS_PORT", 5353))
DOH_URL     = "https://cloudflare-dns.com/dns-query"
DOH_TIMEOUT = 5.0
BUFFER_SIZE = 4096

# Module-level shared RulesEngine (also imported by api.py)
rules_engine = RulesEngine()

# Persistent httpx client with HTTP/2 for DoH performance
_doh_client = httpx.Client(
    http2=True,
    timeout=DOH_TIMEOUT,
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
)


# ── DoH forwarding ─────────────────────────────────────────────────────

def resolve_via_doh(raw_query: bytes) -> bytes:
    """
    Forward raw DNS wire-format query to Cloudflare DoH.
    Uses GET with base64url-encoded query parameter.
    Falls back to Google DoH if Cloudflare fails.
    """
    encoded = base64.urlsafe_b64encode(raw_query).rstrip(b"=").decode()
    for url in (DOH_URL, "https://dns.google/dns-query"):
        try:
            resp = _doh_client.get(
                url,
                params={"dns": encoded},
                headers={"Accept": "application/dns-message"},
            )
            if resp.status_code == 200:
                return resp.content
        except Exception as e:
            logger.warning(f"DoH {url} failed: {e}")
    # If both fail, return SERVFAIL for the original request
    return _make_servfail(raw_query)


def _make_servfail(raw_query: bytes) -> bytes:
    try:
        req   = dnslib.DNSRecord.parse(raw_query)
        reply = req.reply()
        reply.header.rcode = dnslib.RCODE.SERVFAIL
        return reply.pack()
    except Exception:
        return b""


# ── Block response ─────────────────────────────────────────────────────

def make_nxdomain(request: dnslib.DNSRecord) -> bytes:
    """Return an NXDOMAIN response — domain does not exist."""
    reply = request.reply()
    reply.header.rcode = dnslib.RCODE.NXDOMAIN
    # Optionally set minimum TTL on the SOA to prevent immediate retry
    reply.header.aa = 1   # authoritative answer
    return reply.pack()


# ── Query handler ──────────────────────────────────────────────────────

def handle_query(data: bytes, addr: tuple, sock: socket.socket):
    """
    Process one DNS query:
      1. Parse domain + record type
      2. Ask RulesEngine whether to block
      3. Return NXDOMAIN or proxy via DoH
      4. Log asynchronously
    """
    t0 = time.perf_counter()
    try:
        request = dnslib.DNSRecord.parse(data)
    except Exception as e:
        logger.debug(f"Malformed DNS packet from {addr}: {e}")
        return

    domain = str(request.q.qname).rstrip(".")
    qtype  = dnslib.QTYPE.get(request.q.qtype, "?")

    # Only filter A / AAAA queries — pass MX, TXT, SRV, etc. through
    if qtype not in ("A", "AAAA"):
        try:
            sock.sendto(resolve_via_doh(data), addr)
        except Exception:
            pass
        return

    blocked, category = rules_engine.should_block(domain)
    latency_ms        = (time.perf_counter() - t0) * 1000

    if blocked:
        response = make_nxdomain(request)
        _send(sock, response, addr)
        latency_ms = (time.perf_counter() - t0) * 1000
        logger.info(f"BLOCK  {domain:<45} [{category}]  {latency_ms:.1f}ms")
    else:
        response = resolve_via_doh(data)
        _send(sock, response, addr)
        latency_ms = (time.perf_counter() - t0) * 1000
        logger.info(f"allow  {domain:<45}  {latency_ms:.1f}ms")

    # Async log — don't add latency to response
    threading.Thread(
        target=log_query,
        args=(domain, blocked, category, latency_ms,
              rules_engine.active_session_id),
        daemon=True,
    ).start()


def _send(sock: socket.socket, data: bytes, addr: tuple):
    try:
        sock.sendto(data, addr)
    except Exception as e:
        logger.debug(f"Send error to {addr}: {e}")


# ── UDP server ─────────────────────────────────────────────────────────

def run_udp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((DNS_HOST, DNS_PORT))
    logger.info(f"UDP DNS  →  {DNS_HOST}:{DNS_PORT}")

    while True:
        try:
            data, addr = sock.recvfrom(BUFFER_SIZE)
            threading.Thread(
                target=handle_query,
                args=(data, addr, sock),
                daemon=True,
            ).start()
        except Exception as e:
            logger.error(f"UDP recv error: {e}")


# ── TCP server ─────────────────────────────────────────────────────────

def run_tcp_server():
    """
    TCP DNS: used for large responses (>512 bytes) and AXFR.
    DNS over TCP prefixes each message with a 2-byte length field.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((DNS_HOST, DNS_PORT))
    srv.listen(64)
    logger.info(f"TCP DNS  →  {DNS_HOST}:{DNS_PORT}")

    while True:
        try:
            conn, addr = srv.accept()
            threading.Thread(
                target=_handle_tcp_client,
                args=(conn, addr),
                daemon=True,
            ).start()
        except Exception as e:
            logger.error(f"TCP accept error: {e}")


def _handle_tcp_client(conn: socket.socket, addr: tuple):
    try:
        raw = conn.recv(BUFFER_SIZE)
        if len(raw) < 2:
            return
        length = (raw[0] << 8) | raw[1]
        data   = raw[2:2 + length]
        if not data:
            return

        # Wrap the UDP socket send interface for TCP
        class TCPSock:
            def sendto(self, d, _addr):
                prefix = len(d).to_bytes(2, "big")
                conn.sendall(prefix + d)

        handle_query(data, addr, TCPSock())
    except Exception as e:
        logger.debug(f"TCP client error {addr}: {e}")
    finally:
        conn.close()


# ── Entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    seed_blocklist()

    banner = f"""
╔══════════════════════════════════════════════════════╗
║           FocusGate DNS Proxy  starting...           ║
║  Listening  →  127.0.0.1:{DNS_PORT:<5}                    ║
║  Point device DNS to 127.0.0.1 (port {DNS_PORT})          ║
║  DoH upstream  →  Cloudflare / Google                ║
╚══════════════════════════════════════════════════════╝"""
    print(banner)

    # TCP in background
    tcp_thread = threading.Thread(target=run_tcp_server, daemon=True)
    tcp_thread.start()

    # UDP in foreground (blocking)
    run_udp_server()
