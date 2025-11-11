import ipaddress
import socket
from typing import Dict, List


DEFAULT_TIMEOUT = 0.3


def _tcp_check(ip: str, port: int) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=DEFAULT_TIMEOUT):
            return True
    except OSError:
        return False


def scan_modbus(ip: str) -> bool:
    return _tcp_check(ip, 502)


def scan_snmp(ip: str) -> bool:
    return _tcp_check(ip, 161)


def scan_bacnet(ip: str) -> bool:
    return _tcp_check(ip, 47808)


def discover(subnet: str) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    network = ipaddress.ip_network(subnet, strict=False)
    for ip in network.hosts():
        ip_str = str(ip)
        if scan_modbus(ip_str):
            results.append({"ip": ip_str, "proto": "modbus", "guess": "crac"})
            continue
        if scan_bacnet(ip_str):
            results.append({"ip": ip_str, "proto": "bacnet", "guess": "crac"})
            continue
        if scan_snmp(ip_str):
            results.append({"ip": ip_str, "proto": "snmp", "guess": "pdu"})
    return results
