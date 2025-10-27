# signalk_ws_raw_monitor.py - Raw WebSocket Frame Monitor
# ============================================================================
# Custom WebSocket implementation that captures all frame details
# Provides complete visibility into Signal K WebSocket frame structure
# ============================================================================




"""

============================================================
FINAL SESSION SUMMARY
============================================================
Total Runtime: 1800.2s (30.0 min)
Total Connections: 1

CUMULATIVE FRAMES RECEIVED:
  Total: 4005
  Text (0x1): 4005
  Binary (0x2): 0
  Continuation (0x0): 0
  Control frames: 0
    - Ping (0x9): 0
    - Pong (0xA): 0
    - Close (0x8): 0

  *** RESERVED OPCODES: 0 ***

COMPLETE OPCODE BREAKDOWN (session):
  0x1 (TEXT): 4005

CUMULATIVE DATA:
  JSON messages: 4005
  JSON errors: 0
  Total payload bytes: 1324724

AVERAGE RATES (entire session):
  Frames/sec: 2.22
  Text frames/sec: 2.22
  JSON messages/sec: 2.22
  Control frames/sec: 0.00



"""


import secrets
import time
import gc
import network
import uasyncio as asyncio
import socket
import ubinascii
import hashlib

# Import compatibility layer
try:
    import json
except ImportError:
    import ujson as json

# ============================================================================
# CONFIGURATION
# ============================================================================

# WiFi Credentials
SSID = secrets.SSID
PASSWORD = secrets.PASSWORD

# Static IP Configuration
USE_STATIC_IP = getattr(secrets, 'USE_STATIC_IP', False)
STATIC_IP = getattr(secrets, 'STATIC_IP', '192.168.1.100')
STATIC_SUBNET = getattr(secrets, 'STATIC_SUBNET', '255.255.255.0')
STATIC_GATEWAY = getattr(secrets, 'STATIC_GATEWAY', '192.168.1.1')
STATIC_DNS = getattr(secrets, 'STATIC_DNS', '8.8.8.8')

# Signal K Server
HOST = secrets.HOST
PORT = secrets.PORT
VERSION = secrets.VERSION
SUBSCRIBE = (
    "navigation.headingMagnetic,"
    "steering.autopilot.state,"
    "steering.autopilot.target.headingMagnetic,"
    "environment.heartbeat"
)

# Monitoring Configuration
LOG_FILE = '/ws_raw_monitor_log.txt'
LOG_MAX_SIZE = 150000  # 150KB
STATS_INTERVAL = 30  # Print stats every 30 seconds
RECONNECT_WAIT = 5
MAX_RUNTIME_MINUTES = 30  # Automatically stop and print summary after this many minutes
                          # Change this value to run for longer/shorter duration

# ============================================================================
# WIFI CONNECTION
# ============================================================================

def is_wifi_connected():
    """Check if WiFi is connected."""
    wlan = network.WLAN(network.STA_IF)
    return wlan.isconnected() and wlan.ifconfig()[0] != "0.0.0.0"


def connect_wifi(max_retries=5, retry_delay=2):
    """Connect to WiFi network."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if is_wifi_connected():
        ip = wlan.ifconfig()[0]
        print("WiFi: Already connected - IP:", ip)
        return ip
    
    if USE_STATIC_IP:
        wlan.ifconfig((STATIC_IP, STATIC_SUBNET, STATIC_GATEWAY, STATIC_DNS))
    
    print("WiFi: Connecting to '{}'...".format(SSID))
    wlan.connect(SSID, PASSWORD)
    
    for attempt in range(max_retries):
        timeout = 10
        start = time.time()
        
        while time.time() - start < timeout:
            if is_wifi_connected():
                ip = wlan.ifconfig()[0]
                print("WiFi: Connected! IP: {}".format(ip))
                return ip
            time.sleep(0.5)
        
        print("WiFi: Attempt {} failed".format(attempt + 1))
        if attempt < max_retries - 1:
            time.sleep(retry_delay)
    
    raise Exception("WiFi connection failed")


# ============================================================================
# LOGGING
# ============================================================================

def log_to_file(message):
    """Append message to log file with rotation."""
    try:
        import os
        
        try:
            file_size = os.stat(LOG_FILE)[6]
            if file_size > LOG_MAX_SIZE:
                try:
                    with open(LOG_FILE, 'r') as f:
                        lines = f.readlines()
                    keep_lines = int(len(lines) * 0.3)
                    with open(LOG_FILE, 'w') as f:
                        f.write("=== LOG ROTATED ===\n")
                        f.writelines(lines[-keep_lines:])
                except Exception:
                    with open(LOG_FILE, 'w') as f:
                        f.write("=== LOG TRUNCATED ===\n")
        except OSError:
            pass
        
        with open(LOG_FILE, 'a') as f:
            f.write(message)
            f.flush()
    except Exception as e:
        print("Log error:", e)


# ============================================================================
# RAW WEBSOCKET CLIENT
# ============================================================================

class RawWebSocketClient:
    """Minimal WebSocket client with raw frame inspection."""
    
    # WebSocket opcodes (RFC 6455)
    OPCODE_CONTINUATION = 0x0
    OPCODE_TEXT = 0x1
    OPCODE_BINARY = 0x2
    OPCODE_CLOSE = 0x8
    OPCODE_PING = 0x9
    OPCODE_PONG = 0xA
    
    OPCODE_NAMES = {
        0x0: "CONTINUATION",
        0x1: "TEXT",
        0x2: "BINARY",
        0x3: "RESERVED-0x3",
        0x4: "RESERVED-0x4",
        0x5: "RESERVED-0x5",
        0x6: "RESERVED-0x6",
        0x7: "RESERVED-0x7",
        0x8: "CLOSE",
        0x9: "PING",
        0xA: "PONG",
        0xB: "RESERVED-0xB",
        0xC: "RESERVED-0xC",
        0xD: "RESERVED-0xD",
        0xE: "RESERVED-0xE",
        0xF: "RESERVED-0xF",
    }
    
    def __init__(self):
        self.sock = None
        self.connected = False
    
    async def connect(self, host, port, path):
        """Connect and perform WebSocket handshake."""
        print("Raw WS: Connecting to {}:{}...".format(host, port))
        
        # Create socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setblocking(False)
        
        # Connect
        addr = socket.getaddrinfo(host, port)[0][-1]
        try:
            self.sock.connect(addr)
        except OSError as e:
            if e.args[0] != 115:  # EINPROGRESS
                raise
        
        # Wait for connection
        await asyncio.sleep(0.1)
        
        # Generate WebSocket key
        key = ubinascii.b2a_base64(bytes([i & 0xFF for i in range(16)])).decode().strip()
        
        # Send HTTP upgrade request
        request = (
            "GET {} HTTP/1.1\r\n"
            "Host: {}:{}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: {}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).format(path, host, port, key)
        
        self.sock.send(request.encode())
        
        # Read response
        response = b""
        for _ in range(10):  # Max 10 attempts
            await asyncio.sleep(0.1)
            try:
                chunk = self.sock.recv(1024)
                if chunk:
                    response += chunk
                    if b"\r\n\r\n" in response:
                        break
            except OSError:
                pass
        
        # Check for successful upgrade
        if b"101" not in response or b"Upgrade: websocket" not in response:
            raise Exception("WebSocket handshake failed")
        
        self.connected = True
        print("Raw WS: Connected!")
    
    async def recv_frame(self):
        """Receive and parse a single WebSocket frame.
        
        Returns:
            dict with frame details, or None on timeout
        """
        if not self.connected:
            return None
        
        try:
            # Read first 2 bytes (header)
            header = await self._recv_bytes(2, timeout=1.0)
            if not header:
                return None
            
            # Parse first byte
            byte1 = header[0]
            fin = (byte1 & 0x80) != 0
            rsv1 = (byte1 & 0x40) != 0
            rsv2 = (byte1 & 0x20) != 0
            rsv3 = (byte1 & 0x10) != 0
            opcode = byte1 & 0x0F
            
            # Parse second byte
            byte2 = header[1]
            masked = (byte2 & 0x80) != 0
            payload_len = byte2 & 0x7F
            
            # Extended payload length
            if payload_len == 126:
                ext_len = await self._recv_bytes(2, timeout=0.5)
                if not ext_len:
                    return None
                payload_len = (ext_len[0] << 8) | ext_len[1]
            elif payload_len == 127:
                ext_len = await self._recv_bytes(8, timeout=0.5)
                if not ext_len:
                    return None
                payload_len = int.from_bytes(ext_len, 'big')
            
            # Masking key (should not be present from server)
            mask_key = None
            if masked:
                mask_key = await self._recv_bytes(4, timeout=0.5)
            
            # Payload data
            payload = None
            if payload_len > 0:
                # Limit payload read to prevent memory issues
                read_len = min(payload_len, 10000)
                payload = await self._recv_bytes(read_len, timeout=1.0)
                
                # If we didn't read everything, skip the rest
                if read_len < payload_len:
                    remaining = payload_len - read_len
                    await self._recv_bytes(remaining, timeout=1.0)
            
            # Build frame info
            frame_info = {
                'fin': fin,
                'rsv1': rsv1,
                'rsv2': rsv2,
                'rsv3': rsv3,
                'opcode': opcode,
                'opcode_hex': "0x{:X}".format(opcode),
                'opcode_name': self.OPCODE_NAMES.get(opcode, "UNKNOWN"),
                'masked': masked,
                'payload_length': payload_len,
                'payload_data': payload,
                'is_control_frame': opcode >= 0x8,
                'is_reserved_opcode': opcode in [0x3, 0x4, 0x5, 0x6, 0x7, 0xB, 0xC, 0xD, 0xE, 0xF],
            }
            
            return frame_info
            
        except Exception as e:
            print("Raw WS: Frame receive error:", e)
            return None
    
    async def _recv_bytes(self, n, timeout=1.0):
        """Receive exactly n bytes with timeout."""
        data = b""
        start = time.ticks_ms()
        
        while len(data) < n:
            if time.ticks_diff(time.ticks_ms(), start) > timeout * 1000:
                return None
            
            try:
                chunk = self.sock.recv(n - len(data))
                if chunk:
                    data += chunk
                else:
                    await asyncio.sleep(0.01)
            except OSError:
                await asyncio.sleep(0.01)
        
        return data
    
    def close(self):
        """Close the WebSocket connection."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.connected = False


# ============================================================================
# MONITORING STATISTICS
# ============================================================================

class RawMonitorStats:
    """Track detailed frame statistics."""
    
    def __init__(self):
        self.session_start = time.ticks_ms()
        self.total_connections = 0
        
        # Session-level cumulative stats (never reset)
        self.session_frames_total = 0
        self.session_frames_text = 0
        self.session_frames_binary = 0
        self.session_frames_control = 0
        self.session_frames_reserved = 0
        self.session_frames_ping = 0
        self.session_frames_pong = 0
        self.session_frames_close = 0
        self.session_frames_continuation = 0
        self.session_payload_bytes_total = 0
        self.session_json_messages = 0
        self.session_json_errors = 0
        
        # Per-opcode counters (session-level)
        self.session_opcode_counts = {}
        for i in range(16):
            self.session_opcode_counts[i] = 0
        
        # Period stats (reset every interval)
        self.reset()
    
    def reset(self):
        """Reset period statistics."""
        self.start_time = time.ticks_ms()
        self.frames_total = 0
        self.frames_text = 0
        self.frames_binary = 0
        self.frames_control = 0
        self.frames_reserved = 0
        self.frames_ping = 0
        self.frames_pong = 0
        self.frames_close = 0
        self.frames_continuation = 0
        self.payload_bytes_total = 0
        self.json_messages = 0
        self.json_errors = 0
        
        # Per-opcode counters (period)
        self.opcode_counts = {}
        for i in range(16):
            self.opcode_counts[i] = 0
    
    def record_frame(self, frame_info):
        """Record a frame's statistics (both period and session)."""
        opcode = frame_info['opcode']
        payload_len = frame_info['payload_length']
        
        # Update period stats
        self.frames_total += 1
        self.opcode_counts[opcode] += 1
        self.payload_bytes_total += payload_len
        
        # Update session stats
        self.session_frames_total += 1
        self.session_opcode_counts[opcode] += 1
        self.session_payload_bytes_total += payload_len
        
        # Categorize by opcode (period)
        if opcode == 0x1:
            self.frames_text += 1
            self.session_frames_text += 1
        elif opcode == 0x2:
            self.frames_binary += 1
            self.session_frames_binary += 1
        elif opcode == 0x0:
            self.frames_continuation += 1
            self.session_frames_continuation += 1
        elif opcode == 0x9:
            self.frames_ping += 1
            self.session_frames_ping += 1
        elif opcode == 0xA:
            self.frames_pong += 1
            self.session_frames_pong += 1
        elif opcode == 0x8:
            self.frames_close += 1
            self.session_frames_close += 1
        
        if frame_info['is_control_frame']:
            self.frames_control += 1
            self.session_frames_control += 1
        if frame_info['is_reserved_opcode']:
            self.frames_reserved += 1
            self.session_frames_reserved += 1
    
    def print_stats(self):
        """Print comprehensive statistics."""
        elapsed_ms = time.ticks_diff(time.ticks_ms(), self.start_time)
        elapsed_s = elapsed_ms / 1000.0
        session_s = time.ticks_diff(time.ticks_ms(), self.session_start) / 1000.0
        
        msg = "\n" + "="*60 + "\n"
        msg += "Raw WebSocket Frame Statistics (Period)\n"
        msg += "="*60 + "\n"
        msg += "Session Runtime: {:.1f}s ({:.1f} min)\n".format(session_s, session_s / 60.0)
        msg += "Period: {:.1f}s\n".format(elapsed_s)
        msg += "Total Connections: {}\n".format(self.total_connections)
        msg += "\n"
        msg += "FRAMES RECEIVED (this period):\n"
        msg += "  Total: {}\n".format(self.frames_total)
        msg += "  Text (0x1): {}\n".format(self.frames_text)
        msg += "  Binary (0x2): {}\n".format(self.frames_binary)
        msg += "  Continuation (0x0): {}\n".format(self.frames_continuation)
        msg += "  Control frames: {}\n".format(self.frames_control)
        msg += "    - Ping (0x9): {}\n".format(self.frames_ping)
        msg += "    - Pong (0xA): {}\n".format(self.frames_pong)
        msg += "    - Close (0x8): {}\n".format(self.frames_close)
        msg += "  RESERVED OPCODES: {} *** SPEC VIOLATION ***\n".format(self.frames_reserved)
        msg += "\n"
        
        # Show opcode breakdown for period
        msg += "OPCODE BREAKDOWN (this period):\n"
        for opcode in range(16):
            count = self.opcode_counts[opcode]
            if count > 0:
                name = RawWebSocketClient.OPCODE_NAMES.get(opcode, "UNKNOWN")
                violation = " *** RFC 6455 VIOLATION ***" if opcode in [0x3,0x4,0x5,0x6,0x7,0xB,0xC,0xD,0xE,0xF] else ""
                msg += "  0x{:X} ({}): {}{}\n".format(opcode, name, count, violation)
        msg += "\n"
        
        msg += "DATA (this period):\n"
        msg += "  JSON messages: {}\n".format(self.json_messages)
        msg += "  JSON errors: {}\n".format(self.json_errors)
        msg += "  Total payload bytes: {}\n".format(self.payload_bytes_total)
        msg += "\n"
        
        if elapsed_s > 0:
            msg += "RATES (this period):\n"
            msg += "  Frames/sec: {:.2f}\n".format(self.frames_total / elapsed_s)
            msg += "  Text frames/sec: {:.2f}\n".format(self.frames_text / elapsed_s)
            msg += "  Control frames/sec: {:.2f}\n".format(self.frames_control / elapsed_s)
            if self.frames_reserved > 0:
                msg += "  RESERVED frames/sec: {:.2f} *** PROBLEM ***\n".format(self.frames_reserved / elapsed_s)
        
        msg += "="*60 + "\n"
        
        print(msg)
        log_to_file(msg)
    
    def print_session_summary(self):
        """Print final cumulative session summary."""
        session_s = time.ticks_diff(time.ticks_ms(), self.session_start) / 1000.0
        
        msg = "\n" + "="*60 + "\n"
        msg += "FINAL SESSION SUMMARY\n"
        msg += "="*60 + "\n"
        msg += "Total Runtime: {:.1f}s ({:.1f} min)\n".format(session_s, session_s / 60.0)
        msg += "Total Connections: {}\n".format(self.total_connections)
        msg += "\n"
        msg += "CUMULATIVE FRAMES RECEIVED:\n"
        msg += "  Total: {}\n".format(self.session_frames_total)
        msg += "  Text (0x1): {}\n".format(self.session_frames_text)
        msg += "  Binary (0x2): {}\n".format(self.session_frames_binary)
        msg += "  Continuation (0x0): {}\n".format(self.session_frames_continuation)
        msg += "  Control frames: {}\n".format(self.session_frames_control)
        msg += "    - Ping (0x9): {}\n".format(self.session_frames_ping)
        msg += "    - Pong (0xA): {}\n".format(self.session_frames_pong)
        msg += "    - Close (0x8): {}\n".format(self.session_frames_close)
        msg += "\n"
        msg += "  *** RESERVED OPCODES: {} ***\n".format(self.session_frames_reserved)
        if self.session_frames_reserved > 0:
            msg += "  ^^^ RFC 6455 SPEC VIOLATIONS DETECTED ^^^\n"
        msg += "\n"
        
        # Show all opcodes used in session
        msg += "COMPLETE OPCODE BREAKDOWN (session):\n"
        for opcode in range(16):
            count = self.session_opcode_counts[opcode]
            if count > 0:
                name = RawWebSocketClient.OPCODE_NAMES.get(opcode, "UNKNOWN")
                violation = " *** RFC 6455 VIOLATION ***" if opcode in [0x3,0x4,0x5,0x6,0x7,0xB,0xC,0xD,0xE,0xF] else ""
                msg += "  0x{:X} ({}): {}{}\n".format(opcode, name, count, violation)
        msg += "\n"
        
        msg += "CUMULATIVE DATA:\n"
        msg += "  JSON messages: {}\n".format(self.session_json_messages)
        msg += "  JSON errors: {}\n".format(self.session_json_errors)
        msg += "  Total payload bytes: {}\n".format(self.session_payload_bytes_total)
        msg += "\n"
        
        if session_s > 0:
            msg += "AVERAGE RATES (entire session):\n"
            msg += "  Frames/sec: {:.2f}\n".format(self.session_frames_total / session_s)
            msg += "  Text frames/sec: {:.2f}\n".format(self.session_frames_text / session_s)
            msg += "  JSON messages/sec: {:.2f}\n".format(self.session_json_messages / session_s)
            msg += "  Control frames/sec: {:.2f}\n".format(self.session_frames_control / session_s)
            if self.session_frames_reserved > 0:
                msg += "\n"
                msg += "  *** RESERVED frames/sec: {:.2f} ***\n".format(self.session_frames_reserved / session_s)
                msg += "  This represents {:.1f}% of all frames!\n".format(
                    (self.session_frames_reserved / self.session_frames_total * 100) if self.session_frames_total > 0 else 0
                )
        
        msg += "\n"
        msg += "="*60 + "\n"
        msg += "Log file: {}\n".format(LOG_FILE)
        msg += "="*60 + "\n"
        
        print(msg)
        log_to_file(msg)


# ============================================================================
# FRAME LOGGER
# ============================================================================

def log_frame_details(frame_info, stats):
    """Log detailed information about a frame."""
    rtc_time = time.localtime()
    timestamp = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
        rtc_time[0], rtc_time[1], rtc_time[2],
        rtc_time[3], rtc_time[4], rtc_time[5]
    )
    
    msg = "\n" + "-"*60 + "\n"
    msg += "[{}] FRAME RECEIVED\n".format(timestamp)
    msg += "-"*60 + "\n"
    msg += "Opcode: {} ({}) {}\n".format(
        frame_info['opcode_hex'],
        frame_info['opcode_name'],
        "*** RFC 6455 VIOLATION ***" if frame_info['is_reserved_opcode'] else ""
    )
    msg += "FIN: {} | RSV1: {} | RSV2: {} | RSV3: {}\n".format(
        frame_info['fin'], frame_info['rsv1'], frame_info['rsv2'], frame_info['rsv3']
    )
    msg += "Masked: {} ({})\n".format(
        frame_info['masked'],
        "INCORRECT - server should not mask" if frame_info['masked'] else "correct"
    )
    msg += "Payload Length: {} bytes\n".format(frame_info['payload_length'])
    msg += "Control Frame: {}\n".format(frame_info['is_control_frame'])
    msg += "Frame Count (session): {}\n".format(stats.frames_total + 1)
    
    # Show payload preview for text frames
    if frame_info['opcode'] == 0x1 and frame_info['payload_data']:
        try:
            text = frame_info['payload_data'].decode('utf-8')
            preview = text[:200] if len(text) > 200 else text
            msg += "\nPayload Preview:\n{}\n".format(preview)
            if len(text) > 200:
                msg += "... (truncated)\n"
        except Exception:
            msg += "\nPayload: (not UTF-8)\n"
    
    msg += "-"*60 + "\n"
    
    # Log to file
    log_to_file(msg)
    
    # Print if reserved opcode
    if frame_info['is_reserved_opcode']:
        print(msg)


# ============================================================================
# MAIN MONITORING LOOP
# ============================================================================

async def monitor():
    """Main raw monitoring loop."""
    print("\n" + "="*60)
    print("Signal K RAW WebSocket Frame Monitor")
    print("="*60)
    print("Monitoring with custom WebSocket client...")
    print("Runtime: {} minutes (automatic)".format(MAX_RUNTIME_MINUTES))
    print("Log file: {}".format(LOG_FILE))
    print("Summary will be printed automatically at end")
    print("="*60 + "\n")
    
    # Initialize log
    rtc_time = time.localtime()
    timestamp = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
        rtc_time[0], rtc_time[1], rtc_time[2],
        rtc_time[3], rtc_time[4], rtc_time[5]
    )
    log_to_file("\n" + "="*60 + "\n")
    log_to_file("Raw WebSocket Monitor Session Started\n")
    log_to_file("[{}]\n".format(timestamp))
    log_to_file("="*60 + "\n\n")
    
    # Connect WiFi
    try:
        ip = connect_wifi()
    except Exception as e:
        print("FATAL: WiFi failed:", e)
        return
    
    # Build path
    path = "/signalk/{}/stream?subscribe={}".format(VERSION, SUBSCRIBE)
    print("Path: {}\n".format(path))
    
    # Initialize
    stats = RawMonitorStats()
    ws_client = None
    last_stats_ms = time.ticks_ms()
    max_runtime_ms = MAX_RUNTIME_MINUTES * 60 * 1000
    
    print("Monitor will run for {} minutes and then provide summary...\n".format(MAX_RUNTIME_MINUTES))
    
    # Main loop
    try:
        while True:
            now_ms = time.ticks_ms()
            
            # Check if we've reached max runtime
            if time.ticks_diff(now_ms, stats.session_start) >= max_runtime_ms:
                print("\n" + "="*60)
                print("Reached {} minute runtime limit".format(MAX_RUNTIME_MINUTES))
                print("="*60)
                break
            
            # Periodic GC
            if time.ticks_diff(now_ms, last_stats_ms) >= 30000:
                gc.collect()
            
            # Print stats
            if time.ticks_diff(now_ms, last_stats_ms) >= STATS_INTERVAL * 1000:
                stats.print_stats()
                stats.reset()
                last_stats_ms = now_ms
                
                # Show countdown
                elapsed_min = time.ticks_diff(now_ms, stats.session_start) / 60000.0
                remaining_min = MAX_RUNTIME_MINUTES - elapsed_min
                if remaining_min > 0:
                    print("Time remaining: {:.1f} minutes\n".format(remaining_min))
            
            # Connect if needed
            if ws_client is None:
                try:
                    ws_client = RawWebSocketClient()
                    await ws_client.connect(HOST, PORT, path)
                    stats.total_connections += 1
                    gc.collect()
                except Exception as e:
                    print("Connection failed:", e)
                    if ws_client:
                        ws_client.close()
                    ws_client = None
                    await asyncio.sleep(RECONNECT_WAIT)
                    continue
            
            # Receive frame
            try:
                frame_info = await ws_client.recv_frame()
                
                if frame_info:
                    # Record statistics
                    stats.record_frame(frame_info)
                    
                    # Log frame details
                    log_frame_details(frame_info, stats)
                    
                    # Try to parse JSON from text frames
                    if frame_info['opcode'] == 0x1 and frame_info['payload_data']:
                        try:
                            text = frame_info['payload_data'].decode('utf-8')
                            data = json.loads(text)
                            stats.json_messages += 1
                            stats.session_json_messages += 1
                        except Exception:
                            stats.json_errors += 1
                            stats.session_json_errors += 1
            
            except Exception as e:
                print("Error:", e)
                if ws_client:
                    ws_client.close()
                ws_client = None
                await asyncio.sleep(RECONNECT_WAIT)
            
            await asyncio.sleep(0)
    
    finally:
        # Always print session summary on exit
        print("\n\nGenerating final session summary...\n")
        stats.print_session_summary()


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    try:
        asyncio.run(monitor())
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped by user")
    except Exception as e:
        print("\n\nFATAL ERROR:", e)
        import sys
        sys.print_exception(e)
