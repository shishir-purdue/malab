"""Local bench settings shared by drivers, notebooks and the dashboard.

Real identities belong in ignored config/bench.local.json, never in source.
Set DAC_BENCH_CONFIG to an alternative local path on another computer.
"""
import ipaddress
import json
import os
from pathlib import Path


def config_path(path=None):
    return Path(path or os.environ.get("DAC_BENCH_CONFIG") or
                Path(__file__).resolve().parents[1] / "config/bench.local.json")


def load_bench_config(path=None):
    path = config_path(path)
    if not path.is_file():
        raise ValueError("Create ignored config/bench.local.json or set DAC_BENCH_CONFIG before connecting")
    config = json.loads(path.read_text(encoding="utf-8"))
    units = config.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError("Bench configuration requires an ordered, nonempty units list")
    names, addresses, ports = set(), set(), set()
    for unit in units:
        name, address = unit["name"], str(ipaddress.IPv4Address(unit["address"]))
        port = unit.get("usb_port")
        if not isinstance(name, str) or not name or name in names or address in addresses:
            raise ValueError("Duplicate or invalid unit name/address")
        if port is not None:
            if not isinstance(port, str) or not port.strip() or port.upper() in ports:
                raise ValueError("Duplicate or invalid USB port")
            ports.add(port.upper())
        names.add(name); addresses.add(address)
    meter = config.get("meter", {})
    ipaddress.IPv4Address(meter["address"])
    if type(meter.get("channel")) is not int or not 1 <= meter["channel"] <= 4 * len(units):
        raise ValueError("Meter channel must belong to the configured unit list")
    return config


def dashboard_options(path=None):
    config = load_bench_config(path)
    return dict(addresses=[u["address"] for u in config["units"]],
                bench_ports=[u.get("usb_port") for u in config["units"]],
                meter_address=config["meter"]["address"], meter_channel=config["meter"]["channel"])


def instrument_address(name):
    """Optional legacy instruments also take addresses from local settings."""
    config = load_bench_config()
    try:
        return config["instruments"][name]
    except KeyError as exc:
        raise ValueError(f"Configure instruments.{name} in the local bench file") from exc
