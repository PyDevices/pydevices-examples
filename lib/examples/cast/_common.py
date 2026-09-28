# Shared by the demos: a console log with a millisecond clock, and Wi-Fi up
# with power save off (an ESP32 in power save answers late enough to starve a
# stream). The log is never written to flash: a littlefs block erase parks
# core 0 and stalls the cast.
import time

T0 = time.ticks_ms()


def log(*a):
    print("[%6d] " % time.ticks_diff(time.ticks_ms(), T0) + " ".join(str(x) for x in a))


def wifi_up():
    try:
        import network
        import wifi
        w = network.WLAN(network.STA_IF)
        if not w.isconnected():
            log("connecting Wi-Fi...")
            wifi.connect_from_secrets()
        w.config(pm=network.WLAN.PM_NONE)
        log("Wi-Fi", w.ifconfig()[0], "rssi", w.status("rssi"))
        return w
    except Exception as e:
        log("wifi error", e)
        return None
