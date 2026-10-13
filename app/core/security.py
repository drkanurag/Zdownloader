import socket
import ipaddress
from urllib.parse import urlparse
from typing import Tuple
from app.domain.exceptions import SSRFSecurityException

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
      2. Hostname must not be empty or localhost.
      3. Resolved IP must NOT belong to private/internal/cloud-metadata networks.
    """
    try:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            return False, f"Prohibited URL scheme '{scheme}'. Only HTTP and HTTPS are permitted."

        hostname = parsed.hostname
        if not hostname:
            return False, "URL contains no valid host."

        # Reject explicit loopback names
        if hostname.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False, "Access to localhost or loopback addresses is blocked for security."

        # Resolve hostname to IP to verify against private networks
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for family, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                ip_obj = ipaddress.ip_address(ip_str)

                # Check if IP falls in any blocked network or is private/loopback
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
                    return False, f"Target IP address '{ip_str}' is within a private/restricted network range."

                for blocked_net in BLOCKED_NETWORKS:
                    if ip_obj in blocked_net:
                        return False, f"Target IP address '{ip_str}' is in blocked network {blocked_net}."

        except socket.gaierror:
            # Domain could not be resolved
            return False, f"Domain name '{hostname}' could not be resolved via DNS."

        return True, "URL is safe"

    except Exception as e:
        return False, f"Security validation error: {str(e)}"

