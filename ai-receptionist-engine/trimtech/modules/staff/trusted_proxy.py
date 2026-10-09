"""Staff-only client address resolution; never trusts forwarded headers from an untrusted peer."""
import ipaddress
import os

from flask import request


class ProxyConfigurationError(RuntimeError):
    pass


def _address(value):
    # Reject scoped/port-bearing/obfuscated addresses; normalize IPv4-mapped IPv6.
    if not isinstance(value,str) or '%' in value:
        raise ValueError('Invalid address')
    address=ipaddress.ip_address(value.strip())
    return address.ipv4_mapped if isinstance(address,ipaddress.IPv6Address) and address.ipv4_mapped else address


def trusted_networks(value):
    if not value.strip():
        return ()
    networks=[]
    for item in value.split(','):
        try:
            network=ipaddress.ip_network(item.strip(),strict=True)
        except ValueError:
            raise ProxyConfigurationError('Invalid STAFF_TRUSTED_PROXY_CIDRS configuration.') from None
        # Reject universal/default routes and overly broad networks. No automatic private-network trust.
        if network.prefixlen < (16 if network.version==4 else 48):
            raise ProxyConfigurationError('Configure narrowly scoped, verified proxy networks.')
        networks.append(network)
    if len(networks)>128:
        raise ProxyConfigurationError('Too many trusted proxy networks.')
    return tuple(networks)


def resolve(peer,forwarded,networks):
    try:
        direct=_address(peer)
    except ValueError:
        return 'unknown'
    def trusted(address):
        return any(address.version==network.version and address in network for network in networks)
    if not trusted(direct) or not forwarded:
        return str(direct)
    if len(forwarded)>2048:
        return str(direct)
    parts=forwarded.split(',')
    if len(parts)>20:
        return str(direct)
    current=direct
    for part in reversed(parts):
        # Stop before looking at any attacker-controlled values left of the first untrusted hop.
        if not trusted(current):
            return str(current)
        try:
            current=_address(part)
        except ValueError:
            return str(direct)
    # An all-trusted/incomplete chain has no proven client; share the peer's bucket.
    return str(direct) if trusted(current) else str(current)


def client_address():
    networks=trusted_networks(os.getenv('STAFF_TRUSTED_PROXY_CIDRS',''))
    # If other middleware rewrote REMOTE_ADDR, use ProxyFix's saved transport peer.
    original=request.environ.get('werkzeug.proxy_fix.orig',{})
    peer=original.get('REMOTE_ADDR',request.environ.get('REMOTE_ADDR'))
    return resolve(peer,request.headers.get('X-Forwarded-For',''),networks)
