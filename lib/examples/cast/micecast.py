"""Cast from MicroPython to a Wi-Fi Display sink (a Windows PC or a Roku) over Miracast-over-Infrastructure (MS-MICE).

One poll loop, no threads: MICE on TCP 7250, the Wi-Fi Display
RTSP session served on 7236, then RTP/UDP from the advertised server port
(Windows opens its firewall for that port only). A *streamer* object made by
``make_streamer(dst_ip, dst_port, server_port)`` produces the RTP: it has
``pump(budget_us)``, ``done`` and ``close()``.
"""
import socket, struct, time, select

try:
    import network          # a board: its Wi-Fi interface
except ImportError:
    network = None          # CPython on a desktop (pycast.py streams there)

# MicroPython's tick functions, or the same on CPython's monotonic clock
try:
    ticks_ms, ticks_add, ticks_diff, sleep_ms = time.ticks_ms, time.ticks_add, time.ticks_diff, time.sleep_ms
except AttributeError:
    def ticks_ms():
        return int(time.monotonic() * 1000)

    def ticks_add(t, d):
        return t + d

    def ticks_diff(a, b):
        return a - b

    def sleep_ms(ms):
        time.sleep(ms / 1000)


def _send(sock, data):
    """MicroPython sockets write(); CPython's sendall()."""
    (sock.write if hasattr(sock, "write") else sock.sendall)(data)


class _Poller:
    """select.poll() as MicroPython has it -- events name the socket object --
    over select.select(), which CPython has everywhere (Windows has no poll)."""

    def __init__(self):
        self.socks = []

    def register(self, s, mask=None):
        if s not in self.socks:
            self.socks.append(s)

    def unregister(self, s):
        if s in self.socks:
            self.socks.remove(s)

    def poll(self, timeout_ms):
        if not self.socks:
            sleep_ms(timeout_ms)
            return []
        r, _, _ = select.select(self.socks, [], [], max(0, timeout_ms) / 1000)
        return [(s, _POLLIN if hasattr(select, "POLLIN") else 1) for s in r]


_POLLIN = getattr(select, "POLLIN", 1)

MICE_PORT = 7250


def utf16(s):
    """UTF-16LE with a byte-order mark, as GNOME's source sends it."""
    return b"\xff\xfe" + "".join(c + "\x00" for c in s if ord(c) < 128).encode()


def tlv(t, v):
    return struct.pack(">BH", t, len(v)) + v


def mice_msg(cmd, tlvs):
    body = b"".join(tlvs)
    return struct.pack(">HBB", 4 + len(body), 1, cmd) + body


def parse_params(body):
    out = {}
    for ln in body.split("\r\n"):
        if ":" in ln:
            k, v = ln.split(":", 1)
            out[k.strip()] = v.strip()
    return out


class Rtsp:
    def __init__(self, conn, log):
        self.conn = conn
        self.log = log
        self.buf = b""
        self.cseq = 0
        self.session = None
        self.client_port = None
        self.pending = {}

    def feed(self):
        d = self.conn.recv(2048)
        if not d:
            return False
        self.buf += d
        return True

    def pop_msg(self):
        if b"\r\n\r\n" not in self.buf:
            return None
        head, rest = self.buf.split(b"\r\n\r\n", 1)
        lines = head.decode().split("\r\n")
        headers = {}
        for ln in lines[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        clen = int(headers.get("content-length", "0") or 0)
        if len(rest) < clen:
            return None
        self.buf = rest[clen:]
        return lines[0], headers, rest[:clen].decode()

    def send_raw(self, text):
        self.log("RTSP >>> " + text.replace("\r\n", " | "))
        _send(self.conn, text.encode())

    def request(self, method, target, label, extra="", body=""):
        self.cseq += 1
        self.pending[str(self.cseq)] = label
        msg = "%s %s RTSP/1.0\r\nCSeq: %d\r\n" % (method, target, self.cseq) + extra
        if body:
            msg += "Content-Type: text/parameters\r\nContent-Length: %d\r\n" % len(body)
        self.send_raw(msg + "\r\n" + body)

    def respond(self, cseq, extra="", body="", status="200 OK"):
        msg = "RTSP/1.0 %s\r\nCSeq: %s\r\n" % (status, cseq) + extra
        if body:
            msg += "Content-Type: text/parameters\r\nContent-Length: %d\r\n" % len(body)
        self.send_raw(msg + "\r\n" + body)


GENERIC_IE = {0: "touch_down", 1: "touch_up", 2: "touch_move", 3: "key_down", 4: "key_up", 5: "zoom", 6: "vscroll", 7: "hscroll", 8: "rotate"}
HID_TYPES = {0: "keyboard", 1: "mouse", 2: "single_touch", 3: "multi_touch", 4: "joystick", 5: "camera", 6: "gesture", 7: "remote"}


class Session:
    def __init__(self, sink_ip, name="PyDevices P4", source_id=b"PyDevicesP4cast!", rtsp_port=7236,
                 server_port=15550, video_m4="28 00 01 01 00000020 00000000 00000000 00 0000 0000 11 none none",
                 audio_m4="LPCM 00000002 00", log=print, uibc_port=7239, on_input=None):
        self.sink = sink_ip
        self.uibc_port = uibc_port
        self.on_input = on_input
        self.hidc_caps = "Keyboard/USB, Mouse/USB"
        self.session_request = None   # None, or a Security Options byte to send a Session Request first
        self.uibc_packets = 0
        self.sink_uibc = None
        self.name = name
        self.source_id = source_id
        self.rtsp_port = rtsp_port
        self.server_port = server_port
        self.video_m4 = video_m4
        self.audio_m4 = audio_m4
        self.log = log
        self.idr_requests = 0
        self.streamer = None

    def _uibc_packet(self, p):
        """One UIBC packet: header (version/timestamp flag, category, length), then
        either generic input events or an HID report. Logs the first packets raw."""
        self.uibc_packets += 1
        if self.uibc_packets <= 12:
            self.log("UIBC raw:", p.hex()[:64] + ("..." if len(p) > 32 else ""))   # descriptors run to 1 KB
        cat = p[1] & 0x0F
        off = 4
        if p[0] & 0x10:
            off += 2   # timestamp present
        body = p[off:]
        if cat == 0:
            i = 0
            while i + 3 <= len(body):
                ie = body[i]
                n = (body[i + 1] << 8) | body[i + 2]
                d = body[i + 3:i + 3 + n]
                i += 3 + n
                kind = GENERIC_IE.get(ie, "ie%d" % ie)
                if ie in (0, 1, 2) and len(d) >= 6:
                    pts = []
                    for k in range(d[0]):
                        o = 1 + k * 5
                        if o + 5 <= len(d):
                            pts.append((d[o], (d[o + 1] << 8) | d[o + 2], (d[o + 3] << 8) | d[o + 4]))
                    self._input(kind, pts)
                elif ie in (3, 4) and len(d) >= 5:
                    self._input(kind, ((d[1] << 8) | d[2], (d[3] << 8) | d[4]))
                else:
                    self._input(kind, d)
        elif cat == 1 and len(body) >= 5:
            # input path (1 = USB), HID type, report type, length, then the report.
            # Windows sends the report descriptors first (report type 1), then reports.
            hid_type = HID_TYPES.get(body[1], "hid%d" % body[1])
            report_type = body[2]
            n = (body[3] << 8) | body[4]
            report = body[5:5 + n]
            self._input("hid_" + hid_type + ("_descriptor" if report_type == 1 else ""), report)
        else:
            self._input("uibc_cat%d" % cat, body)

    def _input(self, kind, data):
        if self.uibc_packets <= 40 or self.uibc_packets % 200 == 0:
            self.log("UIBC %d: %s %s" % (self.uibc_packets, kind, data if not isinstance(data, (bytes, bytearray)) else data.hex()))
        if self.on_input:
            try:
                self.on_input(kind, data)
            except Exception as e:
                self.log("on_input:", repr(e))

    def run(self, make_streamer, seconds=3600, idle_after_done=3, stop=None):
        log = self.log
        if network is not None:
            w = network.WLAN(network.STA_IF)
            my_ip = w.ifconfig()[0]
            log("ip", my_ip, "rssi", w.status("rssi"))
            try:
                w.config(pm=network.WLAN.PM_NONE)
            except Exception as e:
                log("pm", e)
        else:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect((self.sink, MICE_PORT))
            my_ip = probe.getsockname()[0]
            probe.close()
            log("ip", my_ip)
        ls = socket.socket()
        ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.bind(("0.0.0.0", self.rtsp_port))
        ls.listen(1)
        mc = socket.socket()
        mc.settimeout(10)
        mc.connect(socket.getaddrinfo(self.sink, MICE_PORT)[0][-1])
        mc.setblocking(False)
        if self.session_request is not None:
            sreq = mice_msg(4, [tlv(0, utf16(self.name)), tlv(3, self.source_id), tlv(5, bytes([self.session_request]))])
            _send(mc, sreq)
            log("MICE >>> Session Request (security options %d) to %s" % (self.session_request, self.sink))
            sleep_ms(500)
            ready = mice_msg(1, [tlv(2, struct.pack(">H", self.rtsp_port)), tlv(3, self.source_id)])
        else:
            ready = mice_msg(1, [tlv(0, utf16(self.name)), tlv(2, struct.pack(">H", self.rtsp_port)), tlv(3, self.source_id)])
        _send(mc, ready)
        log("MICE >>> Source Ready to", self.sink)
        uls = socket.socket()
        uls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        uls.bind(("0.0.0.0", self.uibc_port))
        uls.listen(1)
        uconn = None
        ubuf = b""
        poller = select.poll() if hasattr(select, "poll") and network is not None else _Poller()
        poller.register(mc, _POLLIN)
        poller.register(ls, _POLLIN)
        poller.register(uls, _POLLIN)
        r = conn = None
        streamer = None
        sink_params = {}
        last_keepalive = ticks_ms()
        deadline = ticks_add(ticks_ms(), seconds * 1000)
        done_at = None

        def send_m3(r):
            # Wi-Fi Display M3 (GET_PARAMETER) is valid only once BOTH our M1
            # OPTIONS has been answered AND we have answered the sink's own M2
            # OPTIONS. Windows tolerates M3 straight after M1; the Roku returns
            # 455 "Method Not Valid In This State" unless M2 has completed, so
            # gate the request on both conditions.
            if r.m1_ok and r.m2_done and not r.m3_sent:
                r.m3_sent = True
                r.request("GET_PARAMETER", "rtsp://localhost/wfd1.0", "M3",
                          body="wfd_content_protection\r\nwfd_video_formats\r\nwfd_audio_codecs\r\nwfd_client_rtp_ports\r\nwfd_uibc_capability\r\n")

        try:
            while ticks_diff(deadline, ticks_ms()) > 0:
                if stop is not None and stop():
                    log("stop requested")
                    return "stopped"
                if streamer and not streamer.done:
                    tp = ticks_ms()
                    streamer.pump(4000)
                    dp = ticks_diff(ticks_ms(), tp)
                    if dp > 500:
                        log("slow pump: %d ms" % dp)
                    # A Python pump has to be called back often, so it busy-polls.
                    # A streamer that does its own streaming (castif, on core 0)
                    # sets idle_poll: then this loop blocks in poll() instead of
                    # spinning, and hands the GIL to the app it is meant to keep
                    # out of the way of.
                    timeout = 50 if getattr(streamer, "idle_poll", False) else 0
                else:
                    timeout = 200
                tq = ticks_ms()
                events = poller.poll(timeout)
                dq = ticks_diff(ticks_ms(), tq)
                if dq > 500:
                    log("slow poll: %d ms (timeout %d)" % (dq, timeout))
                for obj, ev in events:
                    if obj is mc:
                        try:
                            d = mc.recv(256)
                        except OSError:
                            d = None
                        if not d:
                            log("MICE <<< closed by sink")
                            poller.unregister(mc)
                            if r is None:
                                return "refused"
                        else:
                            log("MICE <<<", d.hex())
                    elif obj is ls:
                        conn, addr = ls.accept()
                        log("RTSP client connected from", addr)
                        conn.setblocking(False)
                        r = Rtsp(conn, log)
                        r.m1_ok = r.m2_done = r.m3_sent = False
                        poller.register(conn, _POLLIN)
                        r.request("OPTIONS", "*", "M1", extra="Require: org.wfa.wfd1.0\r\n")
                    elif obj is uls:
                        uconn, uaddr = uls.accept()
                        uconn.setblocking(False)
                        poller.register(uconn, _POLLIN)
                        log("UIBC: sink connected from", uaddr)
                    elif obj is uconn:
                        try:
                            d = uconn.recv(512)
                        except OSError:
                            d = None
                        if not d:
                            log("UIBC: closed")
                            poller.unregister(uconn)
                            uconn = None
                        else:
                            ubuf += d
                            while len(ubuf) >= 4:
                                plen = (ubuf[2] << 8) | ubuf[3]
                                if plen < 4 or len(ubuf) < plen:
                                    if plen < 4:
                                        log("UIBC: bad length", ubuf[:8].hex()); ubuf = b""
                                    break
                                self._uibc_packet(ubuf[:plen])
                                ubuf = ubuf[plen:]
                    elif obj is conn:
                        if not r.feed():
                            log("RTSP closed by sink")
                            return "closed"
                        while True:
                            m = r.pop_msg()
                            if m is None:
                                break
                            first, headers, body = m
                            log("RTSP <<< " + first + " | " + " | ".join("%s: %s" % kv for kv in headers.items()) + (" | " + body.replace("\r\n", " / ") if body else ""))
                            if first.startswith("RTSP/1.0"):
                                label = r.pending.pop(headers.get("cseq", ""), "?")
                                ok = " 200 " in first
                                if label == "M1" and ok:
                                    r.m1_ok = True
                                    send_m3(r)
                                elif label == "M3" and ok:
                                    sink_params = parse_params(body)
                                    ports = sink_params.get("wfd_client_rtp_ports", "RTP/AVP/UDP;unicast 1028 0 mode=play")
                                    self.sink_uibc = sink_params.get("wfd_uibc_capability")
                                    m4 = ("wfd_video_formats: %s\r\n" % self.video_m4 + "wfd_audio_codecs: %s\r\n" % self.audio_m4 +
                                          "wfd_presentation_URL: rtsp://%s/wfd1.0/streamid=0 none\r\n" % my_ip +
                                          "wfd_client_rtp_ports: %s\r\n" % ports)
                                    if self.sink_uibc and self.sink_uibc != "none":
                                        # Windows' receiver offers HID reports only (HIDC); take that when
                                        # it's there, generic events otherwise
                                        if "HIDC" in self.sink_uibc:
                                            m4 += ("wfd_uibc_capability: input_category_list=HIDC;generic_cap_list=none;"
                                                   "hidc_cap_list=%s;port=%d\r\n" % (self.hidc_caps, self.uibc_port))
                                        else:
                                            m4 += ("wfd_uibc_capability: input_category_list=GENERIC;generic_cap_list=Mouse, Keyboard, SingleTouch;"
                                                   "hidc_cap_list=none;port=%d\r\n" % self.uibc_port)
                                    r.request("SET_PARAMETER", "rtsp://localhost/wfd1.0", "M4", body=m4)
                                elif label == "M4" and ok:
                                    r.request("SET_PARAMETER", "rtsp://localhost/wfd1.0", "M5", body="wfd_trigger_method: SETUP\r\n")
                                elif label in ("M4", "M5") and not ok:
                                    log("sink rejected", label)
                                    return "rejected " + label
                                continue
                            method = first.split(" ")[0]
                            cseq = headers.get("cseq", "0")
                            if method == "OPTIONS":
                                r.respond(cseq, extra="Public: org.wfa.wfd1.0, SETUP, TEARDOWN, PLAY, PAUSE, GET_PARAMETER, SET_PARAMETER\r\n")
                                r.m2_done = True
                                send_m3(r)
                            elif method == "SETUP":
                                port = None
                                for tok in headers.get("transport", "").split(";"):
                                    if tok.startswith("client_port="):
                                        port = int(tok.split("=")[1].split("-")[0])
                                if port is None:
                                    port = int(sink_params.get("wfd_client_rtp_ports", "x x 1028").split()[1])
                                r.client_port = port
                                r.session = "424242"
                                r.respond(cseq, extra="Session: %s;timeout=30\r\nTransport: RTP/AVP/UDP;unicast;client_port=%d;server_port=%d\r\n" % (r.session, port, self.server_port))
                            elif method == "PLAY":
                                r.respond(cseq, extra="Session: %s;timeout=30\r\n" % r.session)
                                if streamer is None:
                                    streamer = make_streamer(addr[0], r.client_port, self.server_port)
                                    self.streamer = streamer
                                    last_keepalive = ticks_ms()
                                if self.sink_uibc and self.sink_uibc != "none":
                                    r.request("SET_PARAMETER", "rtsp://localhost/wfd1.0", "M14", extra="Session: %s\r\n" % r.session,
                                              body="wfd_uibc_setting: enable\r\n")
                            elif method == "TEARDOWN":
                                r.respond(cseq, extra="Session: %s\r\n" % r.session)
                                log("sink tore down")
                                return "teardown"
                            elif method in ("GET_PARAMETER", "SET_PARAMETER"):
                                if "wfd_idr_request" in body:
                                    self.idr_requests += 1
                                    if streamer and hasattr(streamer, "force_idr"):
                                        streamer.force_idr()
                                r.respond(cseq, extra=("Session: %s\r\n" % r.session) if r.session else "")
                            else:
                                r.respond(cseq, status="405 Method Not Allowed")
                if r and r.session and ticks_diff(ticks_ms(), last_keepalive) > 10000:
                    r.request("GET_PARAMETER", "rtsp://localhost/wfd1.0", "M16", extra="Session: %s\r\n" % r.session)
                    last_keepalive = ticks_ms()
                if streamer and streamer.done:
                    if done_at is None:
                        done_at = ticks_ms()
                        log("stream finished")
                    elif ticks_diff(ticks_ms(), done_at) > idle_after_done * 1000:
                        return "finished"
            return "timeout"
        finally:
            try:
                _send(mc, mice_msg(2, [tlv(0, utf16(self.name)), tlv(3, self.source_id)]))
                sleep_ms(300)
            except Exception as e:
                log("stop:", e)
            if streamer:
                streamer.close()
            for s in (conn, mc, ls, uls, uconn):
                try:
                    if s:
                        s.close()
                except Exception:
                    pass
            log("session closed, %d IDR requests" % self.idr_requests)
