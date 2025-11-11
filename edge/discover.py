import ipaddress
import json
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pymodbus.client import ModbusTcpClient
from pysnmp.hlapi import (CommunityData, ContextData, ObjectIdentity,
                          ObjectType, SnmpEngine, UdpTransportTarget,
                          getCmd)

PORTS = {
    "modbus": 502,
    "snmp": 161,
    "bacnet": 47808,
    "mqtt": 1883,
}


@dataclass
class Fingerprint:
    proto: str
    info: Dict[str, str]


class TemplateRegistry:
    def __init__(self, template_dir: str) -> None:
        self.template_dir = Path(template_dir)
        self.templates: List[Dict[str, str]] = []
        self.reload()

    def reload(self) -> None:
        self.templates = []
        if not self.template_dir.exists():
            return
        for file in self.template_dir.glob("*.yaml"):
            with file.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
                if data:
                    self.templates.append(data)

    def match(self, fingerprint: Fingerprint) -> Dict[str, str]:
        for template in self.templates:
            if template.get("proto") != fingerprint.proto:
                continue
            match = template.get("match", {})
            vendor_match = match.get("vendor")
            contains = match.get("contains", False)
            vendor = fingerprint.info.get("vendor", "")
            if not vendor_match:
                return template
            if contains and vendor_match.lower() in vendor.lower():
                return template
            if not contains and vendor.lower() == vendor_match.lower():
                return template
        # fallback template per proto
        for template in self.templates:
            if template.get("proto") == fingerprint.proto:
                return template
        return {
            "template": "generic_" + fingerprint.proto,
            "proto": fingerprint.proto,
            "type": fingerprint.proto,
            "map": f"{fingerprint.proto}_default",
            "write": False,
        }


class DiscoveryService:
    def __init__(self) -> None:
        self.rate_limit = float(os.environ.get("DISCOVERY_IPS_PER_MIN", "50"))
        self.delay = 60.0 / self.rate_limit if self.rate_limit > 0 else 0
        self.snmp_community = os.environ.get("DISCOVERY_SNMP_COMMUNITY", "public")
        template_dir = os.environ.get("DISCOVERY_TEMPLATE_DIR", "./config/templates")
        self.templates = TemplateRegistry(template_dir)
        self.log_path = Path(os.environ.get("DISCOVERY_LOG_PATH", "./data/discovery.log"))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def scan(self, subnet: str) -> Dict[str, Any]:
        network = ipaddress.ip_network(subnet, strict=False)
        raw: List[Dict[str, any]] = []
        devices: List[Dict[str, any]] = []
        start = time.time()
        for ip in network.hosts():
            ip_str = str(ip)
            services = self._probe_services(ip_str)
            if not services:
                if self.delay:
                    time.sleep(self.delay)
                continue
            raw.append({"ip": ip_str, "services": services})
            fingerprint = self._fingerprint(ip_str, services)
            if fingerprint:
                template = self.templates.match(fingerprint)
                devices.append(
                    {
                        "ip": ip_str,
                        "proto": fingerprint.proto,
                        "type_guess": template.get("type", fingerprint.proto),
                        "template": template.get("template", template.get("map")),
                        "map": template.get("map"),
                        "fingerprint": fingerprint.info,
                        "write": template.get("write", False),
                    }
                )
            if self.delay:
                time.sleep(self.delay)
        duration = time.time() - start
        self._log_run(subnet, raw, devices, duration)
        return {"raw": raw, "devices": devices, "duration": duration}

    def _probe_services(self, ip: str) -> Dict[str, bool]:
        services = {}
        for proto, port in PORTS.items():
            if proto == "bacnet":
                ok = self._probe_udp(ip, port)
            else:
                ok = self._probe_tcp(ip, port)
            if ok:
                services[proto] = True
        return services

    @staticmethod
    def _probe_tcp(ip: str, port: int) -> bool:
        try:
            with socket.create_connection((ip, port), timeout=0.8):
                return True
        except OSError:
            return False

    @staticmethod
    def _probe_udp(ip: str, port: int) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(0.5)
            who_is = bytes.fromhex("810b000c0120ffffffff")  # minimal BACnet BVLC Who-Is
            sock.sendto(who_is, (ip, port))
            sock.recvfrom(1024)
            return True
        except OSError:
            return False
        finally:
            sock.close()

    def _fingerprint(self, ip: str, services: Dict[str, bool]) -> Optional[Fingerprint]:
        if services.get("modbus"):
            fp = self._fingerprint_modbus(ip)
            if fp:
                return Fingerprint(proto="modbus", info=fp)
        if services.get("snmp"):
            fp = self._fingerprint_snmp(ip)
            if fp:
                return Fingerprint(proto="snmp", info=fp)
        if services.get("bacnet"):
            return Fingerprint(proto="bacnet", info={"vendor": "bacnet_device"})
        if services.get("mqtt"):
            return Fingerprint(proto="mqtt", info={"vendor": "mqtt_gateway"})
        return None

    @staticmethod
    def _fingerprint_modbus(ip: str) -> Optional[Dict[str, str]]:
        client = ModbusTcpClient(ip, port=PORTS["modbus"], timeout=1)
        try:
            if not client.connect():
                return None
            if not hasattr(client, "read_device_info"):
                return {"vendor": "modbus_device", "model": "unknown"}
            result = client.read_device_info()
            if not result.isError():
                vendor = b"".join(result.information.get(0x00, [])).decode(errors="ignore")
                model = b"".join(result.information.get(0x01, [])).decode(errors="ignore")
                return {"vendor": vendor or "modbus_device", "model": model or "unknown"}
        except Exception:
            return None
        finally:
            client.close()
        return None

    def _fingerprint_snmp(self, ip: str) -> Optional[Dict[str, str]]:
        iterator = getCmd(
            SnmpEngine(),
            CommunityData(self.snmp_community, mpModel=0),
            UdpTransportTarget((ip, PORTS["snmp"]), timeout=1, retries=0),
            ContextData(),
            ObjectType(ObjectIdentity("SNMPv2-MIB", "sysObjectID", 0)),
        )
        try:
            errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
            if errorIndication or errorStatus:
                return None
            oid = str(varBinds[0][1])
            return {"vendor": oid, "model": oid.split(".")[-1]}
        except StopIteration:
            return None

    def _log_run(self, subnet: str, raw: List[Dict[str, Any]], devices: List[Dict[str, Any]], duration: float) -> None:
        log_entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "subnet": subnet,
            "raw_count": len(raw),
            "device_count": len(devices),
            "duration_s": round(duration, 2),
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(log_entry) + "\n")
