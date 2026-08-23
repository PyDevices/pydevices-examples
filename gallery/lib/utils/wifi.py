"""
Minimal ``wifi`` shim for MicroPython (``network.WLAN``).

Provides a CircuitPython-shaped subset so examples can use::

    import wifi
    wifi.radio.connect("ssid", "password")
    print(wifi.radio.ipv4_address)

Or, when a ``secrets`` module provides ``WIFI_SSID`` / ``WIFI_PASSWORD``::

    import wifi
    wifi.connect_from_secrets()

This is **not** a full ``wifi.Radio`` implementation and is **not** a drop-in
for CircuitPython ``socketpool.SocketPool(wifi.radio)`` (that requires the
native CP radio object). On MicroPython, use ``network``/``socket`` or a
third-party HTTP client instead.

``connect()`` returns ``None`` (like CP). ``ipv4_address`` is ``None`` until
DHCP assigns a non-zero address.
"""

from time import sleep_ms, ticks_diff, ticks_ms

import network

# Wall-clock wait for association + DHCP. ESP-IDF *debug* builds are much
# slower (verbose logging on the same UART as the REPL); a fixed retry count
# that assumed ~100ms/iter under-counted when each print blocked on logging.
_CONNECT_TIMEOUT_MS = 45000
_POLL_MS = 200
_PROGRESS_MS = 1000


def _valid_ipv4(ip):
    return bool(ip) and ip != "0.0.0.0"


class Radio:
    def __init__(self):
        self._wlan = network.WLAN(network.STA_IF)

    def _ipv4(self):
        # Prefer ifconfig over isconnected(): ESP-IDF "got ip" is ifconfig;
        # isconnected() can lag on debug builds.
        try:
            ip = self._wlan.ifconfig()[0]
        except Exception:
            return None
        if not _valid_ipv4(ip):
            return None
        return ip

    def connect(self, ssid, password):
        if self._ipv4() is not None:
            print("\nAlready connected.\nNetwork config:", self._wlan.ifconfig(), "\n")
            return None

        self._wlan.active(True)
        print("Connecting to:", ssid)
        self._wlan.connect(ssid, password)
        t0 = ticks_ms()
        last_prog = t0
        while ticks_diff(ticks_ms(), t0) < _CONNECT_TIMEOUT_MS:
            if self._ipv4() is not None:
                print("Connection established.\nNetwork config:", self._wlan.ifconfig(), "\n")
                return None
            now = ticks_ms()
            if ticks_diff(now, last_prog) >= _PROGRESS_MS:
                # Sparse progress — avoid flooding UART alongside ESP_LOG.
                st = None
                try:
                    st = self._wlan.status()
                except Exception:
                    pass
                print("  waiting %ds (status=%s)" % (ticks_diff(now, t0) // 1000, st))
                last_prog = now
            sleep_ms(_POLL_MS)
        if self._ipv4() is not None:
            print("Connection established.\nNetwork config:", self._wlan.ifconfig(), "\n")
            return None
        print("Failed to connect after %ds.\n" % (_CONNECT_TIMEOUT_MS // 1000))
        return None

    @property
    def ipv4_address(self):
        return self._ipv4()


radio = Radio()


def connect_from_secrets(module="secrets"):
    """Connect using ``WIFI_SSID`` / ``WIFI_PASSWORD`` (or ``ssid`` / ``password``).

    Returns ``True`` if an IPv4 address is assigned after ``connect()``.
    """
    try:
        s = __import__(module)
    except ImportError:
        print("wifi: no secrets module")
        return False
    ssid = getattr(s, "WIFI_SSID", None) or getattr(s, "ssid", None)
    password = getattr(s, "WIFI_PASSWORD", None) or getattr(s, "password", None)
    # Already online (e.g. NVS auto-reconnect) — do not call connect() again.
    if radio.ipv4_address is not None:
        print("\nAlready connected.\nNetwork config:", radio._wlan.ifconfig(), "\n")
        return True
    if not ssid:
        print("wifi: WIFI_SSID missing in secrets")
        return False
    radio.connect(ssid, password or "")
    return radio.ipv4_address is not None
