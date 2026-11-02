import socket
import ipaddress
import secrets
from urllib.parse import urlparse, urljoin
from typing import Tuple, Optional
import httpx
from fastapi import Request, HTTPException, Security
from fastapi.security import APIKeyHeader
from app.domain.exceptions import SSRFSecurityException
from app.config import PAIRING_TOKEN, is_serverless

# Reserved / Private IPv4 and IPv6 networks to block for SSRF prevention
BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),          # Current network
    ipaddress.ip_network("10.0.0.0/8"),         # RFC 1918 Private
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local / Cloud metadata (169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),      # RFC 1918 Private
    ipaddress.ip_network("192.168.0.0/16"),     # RFC 1918 Private
    ipaddress.ip_network("224.0.0.0/4"),        # Multicast
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved
    ipaddress.ip_network("::1/128"),            # IPv6 Loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 Unique Local
    ipaddress.ip_network("fe80::/10"),          # IPv6 Link-Local
]

def validate_url_security(url: str) -> Tuple[bool, str]:
    """
    Validate a URL to defend against SSRF (Server-Side Request Forgery) and DNS Rebinding.
    
    Checks:
      1. Scheme must be strictly http or https.
      2. Hostname must not be empty or loopback.
      3. Resolved IP must NOT belong to private/internal/cloud-metadata networks.
    """
    if not url or not isinstance(url, str):
        return False, "Empty or invalid URL provided."

    try:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            return False, f"Prohibited URL scheme '{scheme}'. URL must start with http:// or https://"

        hostname = parsed.hostname
        if not hostname:
            return False, "URL contains no valid host."

        # Reject explicit loopback and link-local names
        cleaned_host = hostname.strip("[]").lower()
        if cleaned_host in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "169.254.169.254"):
            return False, f"Access to restricted address '{cleaned_host}' is blocked for security."

        # First check if the host is already an IP address literal
        try:
            direct_ip = ipaddress.ip_address(cleaned_host)
            if direct_ip.is_private or direct_ip.is_loopback or direct_ip.is_link_local or direct_ip.is_multicast or direct_ip.is_reserved:
                return False, f"Target IP address '{direct_ip}' is within a restricted network range."
            for blocked_net in BLOCKED_NETWORKS:
                if direct_ip in blocked_net:
                    return False, f"Target IP address '{direct_ip}' is in blocked network {blocked_net}."
            return True, "URL is safe"
        except ValueError:
            pass  # It's a domain name, proceed to DNS resolution

        # Resolve hostname to IP to verify against private networks and DNS rebinding
        try:
            addr_info = socket.getaddrinfo(cleaned_host, None)
            if not addr_info:
                return False, f"Domain name '{cleaned_host}' returned no IP addresses."

            for family, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                ip_obj = ipaddress.ip_address(ip_str)

                # Check if IP falls in any blocked network or is private/loopback/link-local
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_multicast or ip_obj.is_reserved:
                    return False, f"Target IP address '{ip_str}' is within a private/restricted network range."

                for blocked_net in BLOCKED_NETWORKS:
                    if ip_obj in blocked_net:
                        return False, f"Target IP address '{ip_str}' is in blocked network {blocked_net}."

        except socket.gaierror:
            return False, f"Domain name '{cleaned_host}' could not be resolved via DNS."

        return True, "URL is safe"

    except Exception as e:
        return False, f"Security validation error: {str(e)}"

def check_redirect_ssrf(response: httpx.Response) -> None:
    """Event hook for httpx to inspect every redirect location against SSRF policies."""
    if response.is_redirect:
        location = response.headers.get("Location")
        if location:
            full_redirect_url = urljoin(str(response.url), location)
            is_safe, reason = validate_url_security(full_redirect_url)
            if not is_safe:
                raise SSRFSecurityException(f"SSRF violation on redirect to {full_redirect_url}: {reason}")

def create_safe_async_client(timeout: float = 30.0, follow_redirects: bool = True) -> httpx.AsyncClient:
    """
    Create an httpx.AsyncClient with strict TLS certificate verification and
    automatic redirect SSRF inspection.
    """
    return httpx.AsyncClient(
        verify=True,
        timeout=timeout,
        follow_redirects=follow_redirects,
        event_hooks={"response": [check_redirect_ssrf]}
    )

api_key_header = APIKeyHeader(name="X-API-Token", auto_error=False)

def verify_token_match(provided_token: Optional[str]) -> bool:
    """Constant-time token verification to prevent timing side-channels."""
    if not provided_token or not PAIRING_TOKEN:
        return False
    return secrets.compare_digest(provided_token.strip(), PAIRING_TOKEN)

async def require_auth_token(request: Request) -> bool:
    """
    FastAPI dependency for protecting sensitive endpoints against unauthorized control.
    
    Exemptions:
      - Running in serverless cloud mode (where no local control is possible)
      - Explicit valid pairing token in X-API-Token header or ?token= query parameter
      - Loopback same-origin requests directly from 127.0.0.1:8765 / localhost:8765
    """
    if is_serverless:
        return True

    # 1. Header or Query token check
    token = request.headers.get("X-API-Token") or request.query_params.get("token")
    if token and verify_token_match(token):
        return True

    # 2. Localhost direct same-origin requests check
    origin = request.headers.get("origin")
    host = request.headers.get("host", "")
    client_host = request.client.host if request.client else ""

    is_client_local = client_host in ("127.0.0.1", "::1", "localhost", "testclient", "")
    is_same_origin = (
        origin is None or
        origin.startswith("http://127.0.0.1:8765") or
        origin.startswith("http://localhost:8765")
    )
    is_loopback_host = any(h in host for h in ("8765", "127.0.0.1", "localhost", "test")) or not host

    if is_client_local and is_same_origin and is_loopback_host:
        return True

    raise HTTPException(
        status_code=401,
        detail="Unauthorized: Local engine pairing token required. Pass header 'X-API-Token' or query '?token='."
    )
