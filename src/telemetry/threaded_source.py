# telemetry/threaded_source.py
import logging
import socket
import threading
import time

log = logging.getLogger("udp")

# How often the reader thread wakes to check the running flag while no
# packets are arriving. Without this, a thread blocked in recvfrom() keeps
# the port bound even after close() until a packet arrives — if the game has
# stopped broadcasting (player in the game's menus), that is never, and the
# next bind on the same port dies with EADDRINUSE.
_RECV_TIMEOUT_S = 0.5

# Bind retry window — absorbs a dying previous process (crash-restart
# overlap) still holding the port for a moment.
_BIND_ATTEMPTS = 4
_BIND_RETRY_DELAY_S = 0.75


class TelemetryThread:
    """Binds a UDP socket and fires a callback per received packet in a daemon thread."""

    def __init__(self, callback, address="0.0.0.0", port=5606, recorder=None):
        """
        :param callback: Function called with each raw packet
        :param address:  IP address to bind to
        :param port:     Port number to bind to
        :param recorder: Optional telemetry.capture.PacketRecorder (--record)
        """
        self.callback = callback
        self.address = address
        self.port = port
        self.recorder = recorder
        self.running = False
        self.thread = None
        self.sock = None

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(_RECV_TIMEOUT_S)
        for attempt in range(1, _BIND_ATTEMPTS + 1):
            try:
                self.sock.bind((self.address, self.port))
                break
            except OSError:
                if attempt == _BIND_ATTEMPTS:
                    raise
                log.warning(f"Port {self.port} busy (attempt {attempt}/{_BIND_ATTEMPTS}) — retrying")
                time.sleep(_BIND_RETRY_DELAY_S)
        log.info(f"Listening on {self.address} port {self.port}")
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while self.running:
            try:
                packet, _ = self.sock.recvfrom(65535)
            except socket.timeout:
                continue  # idle wake-up so stop() takes effect without traffic
            except OSError:
                break  # socket closed — exit cleanly
            if self.recorder:
                self.recorder.write(packet)
            try:
                self.callback(packet)
            except Exception as exc:
                log.exception(f"Unexpected error (thread continues): {exc}")

    def stop(self):
        """Stop the reader and release the port before returning."""
        self.running = False
        # Join before closing: close() does not wake a thread blocked in
        # recvfrom(), and the kernel keeps the port bound until that call
        # returns. The receive timeout guarantees the thread notices the
        # running flag within _RECV_TIMEOUT_S even with no traffic.
        if self.thread:
            self.thread.join(timeout=_RECV_TIMEOUT_S * 3)
            if self.thread.is_alive():
                log.warning("Reader thread did not exit in time — port may linger")
            self.thread = None
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
