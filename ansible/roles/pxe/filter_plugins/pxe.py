"""Validate deployment address plans before emitting network configuration."""
import ipaddress
import re


def valid_address_plan(address, subnet, prefix, netmask, start, end):
    try:
        network = ipaddress.IPv4Network(subnet, strict=True)
        server = ipaddress.IPv4Address(address)
        first = ipaddress.IPv4Address(start)
        last = ipaddress.IPv4Address(end)
        return (
            network.prefixlen == int(prefix)
            and str(network.netmask) == netmask
            and all(ip in network and ip not in (network.network_address, network.broadcast_address)
                    for ip in (server, first, last))
            and first <= last
            and not first <= server <= last
        )
    except (ValueError, TypeError):
        return False


def valid_efi_path(value):
    if not isinstance(value, str):
        return False
    parts = value.split('\\')
    return (
        len(parts) >= 4 and parts[0] == '' and parts[1].casefold() == 'efi'
        and parts[-1].casefold().endswith('.efi')
        and all(re.fullmatch(r'[a-zA-Z0-9_.-]+', part) and part not in ('.', '..')
                for part in parts[1:])
    )


class FilterModule:
    def filters(self):
        return {'pxe_valid_address_plan': valid_address_plan,
                'pxe_valid_efi_path': valid_efi_path}
