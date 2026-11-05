"""Homelab network values for the Mac-side phone helpers, read from the environment.

The router address and the two subnets are not in this public repo. Export them before running
router-phone.py, wireguard-phone.py or update-phone-alias.py (docs/profiles.md, "Local data keys"):

    HOMELAB_ROUTER     router address (OPNsense), for example 192.0.2.1
    HOMELAB_LAN_CIDR   home LAN, a /24, for example 192.0.2.0/24
    HOMELAB_WG_CIDR    WireGuard subnet, a /24, for example 198.51.100.0/24

A missing or invalid value fails with a message that names it.
"""
import ipaddress
import os


def require(name, error=RuntimeError):
    value = os.environ.get(name, "").strip()
    if not value:
        raise error(f"environment variable {name} is not set; see docs/profiles.md, section \"Local data keys\"")
    return value


def network(name, error=RuntimeError):
    value = require(name, error)
    try:
        net = ipaddress.IPv4Network(value)
    except ValueError as exc:
        raise error(f"environment variable {name} is not an IPv4 network: {exc}") from exc
    if net.prefixlen != 24:
        raise error(f"environment variable {name} must be a /24 network")
    return net


def prefix24(net):
    """'a.b.c.' for the /24 network a.b.c.0/24."""
    return str(net.network_address).rsplit(".", 1)[0] + "."
