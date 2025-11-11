from prometheus_client import Counter, Histogram

DISCOVER_SCANS_TOTAL = Counter(
    "discover_scans_total", "Number of discovery scans triggered"
)
DISCOVER_DEVICES_FOUND_TOTAL = Counter(
    "discover_devices_found_total", "Total devices identified via discovery"
)
DISCOVER_DEVICES_APPROVED_TOTAL = Counter(
    "discover_devices_approved_total", "Devices approved into config"
)
DISCOVER_DURATION_SECONDS = Histogram(
    "discover_duration_seconds", "Duration of discovery scans in seconds"
)
