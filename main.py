# Simple WebSocket Frame Monitor - Raw frames with timestamps
import secrets
import time
import network
import uasyncio as asyncio
import socket
import ubinascii
import gc
from micropython import const

# Cache time functions for performance (avoid module lookup overhead in tight loops)
_ticks_ms = time.ticks_ms
_ticks_diff = time.ticks_diff
_time = time.time
_localtime = time.localtime
_gc_collect = gc.collect
_gc_threshold = gc.threshold

# Configure GC for better performance (keep auto-GC as safety net)
_gc_threshold(8192)  # Raise threshold to reduce auto-GC interruptions (default ~2048)

try:
    import json
except ImportError:
    import ujson as json

# Pimoroni Interstate 75 W display imports
try:
    from interstate75 import Interstate75, DISPLAY_INTERSTATE75_64X64
    from picographics import PicoGraphics, DISPLAY_INTERSTATE75_64X64
    DISPLAY_AVAILABLE = True
except ImportError:
    DISPLAY_AVAILABLE = False
    print("Warning: Interstate75 display library not available")

# ============================================================================
# CONFIGURATION
# ============================================================================

# WiFi Credentials
SSID = secrets.SSID
PASSWORD = secrets.PASSWORD

# Static IP Configuration (optional)
USE_STATIC_IP = getattr(secrets, 'USE_STATIC_IP', False)
STATIC_IP = getattr(secrets, 'STATIC_IP', '192.168.1.100')
STATIC_SUBNET = getattr(secrets, 'STATIC_SUBNET', '255.255.255.0')
STATIC_GATEWAY = getattr(secrets, 'STATIC_GATEWAY', '192.168.1.1')
STATIC_DNS = getattr(secrets, 'STATIC_DNS', '8.8.8.8')

# Signal K Server
HOST = secrets.HOST
PORT = secrets.PORT
VERSION = secrets.VERSION

# Signal K Subscription paths
SUBSCRIBE = getattr(secrets, 'SUBSCRIBE', 
    "navigation.headingMagnetic,"
    "steering.autopilot.state,"
    "steering.autopilot.target.headingMagnetic,"
    "environment.heartbeat"
)

# Connection timing
RECONNECT_WAIT = getattr(secrets, 'RECONNECT_WAIT', 5)
CONNECTION_TIMEOUT = getattr(secrets, 'CONNECTION_TIMEOUT', 30)
SUBSCRIPTION_CHECK_INTERVAL = getattr(secrets, 'SUBSCRIPTION_CHECK_INTERVAL', 15)
SUBSCRIPTION_INITIAL_WAIT = getattr(secrets, 'SUBSCRIPTION_INITIAL_WAIT', 5)

# Exponential backoff settings
SIGNALK_BACKOFF_INITIAL = getattr(secrets, 'SIGNALK_BACKOFF_INITIAL', 5)
SIGNALK_BACKOFF_MAX = getattr(secrets, 'SIGNALK_BACKOFF_MAX', 30)
SIGNALK_BACKOFF_MULTIPLIER = getattr(secrets, 'SIGNALK_BACKOFF_MULTIPLIER', 2)

WIFI_BACKOFF_INITIAL = getattr(secrets, 'WIFI_BACKOFF_INITIAL', 5)
WIFI_BACKOFF_MAX = getattr(secrets, 'WIFI_BACKOFF_MAX', 30)
WIFI_BACKOFF_MULTIPLIER = getattr(secrets, 'WIFI_BACKOFF_MULTIPLIER', 2)

# Deduplication settings
ENABLE_DEDUPLICATION = getattr(secrets, 'ENABLE_DEDUPLICATION', True)
DEDUP_WINDOW_MS = getattr(secrets, 'DEDUP_WINDOW_MS', 150)
DEDUP_CACHE_SIZE = getattr(secrets, 'DEDUP_CACHE_SIZE', 50)

# Output settings
PRINT_FULL_JSON = getattr(secrets, 'PRINT_FULL_JSON', False)
PRINT_PATH_VALUE = getattr(secrets, 'PRINT_PATH_VALUE', True)

# Heartbeat monitoring settings
HEARTBEAT_TIMEOUT = getattr(secrets, 'HEARTBEAT_TIMEOUT', 30)
HEARTBEAT_PATH = getattr(secrets, 'HEARTBEAT_PATH', "environment.heartbeat")
HEARTBEAT_DEBUG = getattr(secrets, 'HEARTBEAT_DEBUG', True)

# Magnetic heading change monitoring settings
MAG_HEADING_TIMEOUT = getattr(secrets, 'MAG_HEADING_TIMEOUT', 30)
MAG_HEADING_PATH = getattr(secrets, 'MAG_HEADING_PATH', "navigation.headingMagnetic")
MAG_HEADING_TOLERANCE = getattr(secrets, 'MAG_HEADING_TOLERANCE', 0.01)
MAG_HEADING_DEBUG = getattr(secrets, 'MAG_HEADING_DEBUG', True)

# EWMA filter settings for navigation.headingMagnetic
ENABLE_HEADING_EWMA = getattr(secrets, 'ENABLE_HEADING_EWMA', True)
HEADING_EWMA_ALPHA = getattr(secrets, 'HEADING_EWMA_ALPHA', 0.2)  # 0.0-1.0, lower = more smoothing

# EWMA filter settings for WiFi RSSI
ENABLE_RSSI_EWMA = getattr(secrets, 'ENABLE_RSSI_EWMA', True)
RSSI_EWMA_ALPHA = getattr(secrets, 'RSSI_EWMA_ALPHA', 0.3)  # 0.0-1.0, lower = more smoothing

# Radian to degree conversion constant (more efficient than math.degrees)
RAD_TO_DEG = const(57.29577951308232)  # 180 / π

# WebSocket frame opcodes
WS_OPCODE_TEXT = const(0x1)
WS_OPCODE_BINARY = const(0x2)
WS_OPCODE_CLOSE = const(0x8)
WS_OPCODE_PING = const(0x9)
WS_OPCODE_PONG = const(0xA)

# WebSocket recv buffer sizes
WS_RECV_PAYLOAD = const(1024)  # Payload chunk size
WS_RECV_HTTP = const(1024)     # HTTP handshake buffer

# Percentage calculation helpers
PERCENT_MULTIPLIER = const(100)
PERCENT_DECIMAL_DIVISOR = const(10)

# Garbage collection settings
GC_COLLECT_INTERVAL = getattr(secrets, 'GC_COLLECT_INTERVAL', 100)

# Display settings
ENABLE_DISPLAY = getattr(secrets, 'ENABLE_DISPLAY', True) and DISPLAY_AVAILABLE
TEXT_SCALE = const(0.75)     # Scale for all text
TEXT_THICKNESS = const(2)   # Thickness for better visibility on LED matrix
COLOR_WHITE = (255, 255, 255)

# Status indicator settings
INDICATOR_BLINK_INTERVAL = getattr(secrets, 'INDICATOR_BLINK_INTERVAL', 500)  # ms between blinks
INDICATOR_LEFT_X = const(0)
INDICATOR_RIGHT_X = const(54)  # Right side (64 - 10 = 54)
INDICATOR_Y = const(60)
INDICATOR_WIDTH = const(10)
INDICATOR_HEIGHT = const(4)
INDICATOR_CENTER_X = const(31)  # Center (64 / 2 - 1 = 31, for 1-pixel wide centered indicator)
INDICATOR_RUNNING_WIDTH = const(1)  # Running indicator is 1 pixel wide

# Indicator colors
COLOR_GREEN_BRIGHT = (0, 255, 0)
COLOR_BLUE_BRIGHT = (0, 127, 255)
COLOR_RED_BRIGHT = (255, 110, 0)
COLOR_RED_DIM = (0, 0, 0)  # Off when blinking

# RSSI bar indicator settings
RSSI_BAR_START_X = const(16)  # Start column for RSSI bars
RSSI_BAR_COUNT = const(5)      # Number of bars (1-5)
RSSI_BAR_WIDTH = const(1)      # Each bar is 1 pixel wide
RSSI_BAR_HEIGHT = const(4)     # Bars are 4 pixels high
RSSI_BAR_Y = const(60)         # Bottom row (same as other status indicators)


# ============================================================================
# TIMESTAMP HELPERS
# ============================================================================

def get_timestamp():
    """Get formatted timestamp with milliseconds."""
    t = _localtime()
    ms = _ticks_ms() % 1000
    return "{:02d}:{:02d}:{:02d}.{:03d}".format(t[3], t[4], t[5], ms)


# ============================================================================
# EXPONENTIAL BACKOFF
# ============================================================================

def calculate_backoff(retry_count, initial, maximum, multiplier):
    """Calculate exponential backoff delay.
    
    Args:
        retry_count: Number of retries so far
        initial: Initial delay in seconds
        maximum: Maximum delay in seconds
        multiplier: Backoff multiplier
        
    Returns:
        Delay in seconds
    """
    if retry_count == 0:
        return 0
    
    delay = initial * (multiplier ** (retry_count - 1))
    return min(delay, maximum)


# ============================================================================
# MESSAGE DEDUPLICATION
# ============================================================================

class MessageDeduplicator:
    """Efficient message deduplicator using circular buffer."""
    
    def __init__(self, window_ms=150, cache_size=50):
        """Initialize deduplicator.
        
        Args:
            window_ms: Time window for deduplication in milliseconds
            cache_size: Maximum number of messages to cache
        """
        self.window_ms = window_ms
        self.cache_size = cache_size
        
        # Circular buffer for messages
        self.messages = []
        self.next_index = 0
        
        # Pre-allocate cache to avoid dynamic growth
        for _ in range(cache_size):
            self.messages.append(None)
    
    def _hash_message(self, timestamp, source, path, value):
        """Create a hash tuple for the message."""
        # For numeric values, round to reduce false non-duplicates
        if isinstance(value, float):
            value = round(value, 6)
        return (timestamp, source, path, value)
    
    def is_duplicate(self, timestamp, source, path, value):
        """Check if message is a duplicate within the time window.
        
        Args:
            timestamp: ISO timestamp string
            source: Source identifier string
            path: Signal K path string
            value: Value (any type)
            
        Returns:
            True if duplicate, False otherwise
        """
        if not ENABLE_DEDUPLICATION:
            return False
        
        current_ms = _ticks_ms()
        msg_hash = self._hash_message(timestamp, source, path, value)
        
        # Check existing messages
        for cached_msg in self.messages:
            if cached_msg is not None:
                cached_hash, cached_time = cached_msg
                
                # Skip if too old
                if _ticks_diff(current_ms, cached_time) > self.window_ms:
                    continue
                
                # Check for duplicate
                if cached_hash == msg_hash:
                    return True
        
        # Add to cache
        self.messages[self.next_index] = (msg_hash, current_ms)
        self.next_index = (self.next_index + 1) % self.cache_size
        
        return False


# ============================================================================
# DISPLAY MANAGER
# ============================================================================

class DisplayManager:
    """Manages the Interstate 75 W LED matrix display."""
    
    def __init__(self):
        """Initialize the display."""
        self.i75 = None
        self.graphics = None
        self.last_heading = None
        self.last_target = None
        self.autopilot_state = None
        
        # Heartbeat indicator state (lower left)
        self.heartbeat_ok = False  # Start red, turn green after first heartbeat
        
        # Mag heading indicator state (lower right)
        self.mag_heading_ok = False  # Start red, turn green after first heading data
        
        # Shared blink state for both indicators
        self.indicator_blink_state = False  # For blinking animation
        self.last_blink_ms = 0
        
        # RSSI indicator state
        self.rssi_dbm = None  # Current RSSI value in dBm
        self.rssi_bars = 0    # Number of bars to display (0-5)
        
        if not ENABLE_DISPLAY:
            return
        
        try:
            # Create Interstate75 instance with 64x64 display
            self.i75 = Interstate75(
                display=DISPLAY_INTERSTATE75_64X64, 
                color_order=Interstate75.COLOR_ORDER_BGR
            )
            
            # Get the graphics object for drawing
            self.graphics = self.i75.display
            
            # Set up the display
            self.graphics.set_font("sans")
            self.graphics.set_thickness(TEXT_THICKNESS)
            
            # Pre-create pen objects for commonly used colors
            self.pen_black = self.graphics.create_pen(0, 0, 0)
            self.pen_white = self.graphics.create_pen(*COLOR_WHITE)
            self.pen_green_bright = self.graphics.create_pen(*COLOR_GREEN_BRIGHT)
            self.pen_blue_bright = self.graphics.create_pen(*COLOR_BLUE_BRIGHT)            
            self.pen_red_bright = self.graphics.create_pen(*COLOR_RED_BRIGHT)
            self.pen_red_dim = self.graphics.create_pen(*COLOR_RED_DIM)
            
            # Clear display and show initialization message
            self.graphics.set_pen(self.pen_black)
            self.graphics.clear()
            self.graphics.set_pen(self.pen_white)
            self.graphics.text("INIT", 4, 10, scale=TEXT_SCALE)
            
            # Draw initial indicators (both red until data received)
            self._draw_heartbeat_indicator()
            self._draw_mag_heading_indicator()
            self._draw_running_indicator()
            self._draw_rssi_bars()

            
            self.i75.update()
            
            print("Display initialized successfully")
        except Exception as e:
            print("Failed to initialize display: {}".format(e))
            self.i75 = None
            self.graphics = None
    
    def set_heartbeat_ok(self):
        """Set heartbeat indicator to OK state (green solid)."""
        if self.heartbeat_ok != True:
            self.heartbeat_ok = True
            self._draw_heartbeat_indicator()
            self.i75.update()
    
    def set_heartbeat_stale(self):
        """Set heartbeat indicator to stale state (red blinking)."""
        if self.heartbeat_ok != False:
            self.heartbeat_ok = False
            self.indicator_blink_state = False
            self._draw_heartbeat_indicator()
            self.i75.update()
    
    def set_mag_heading_ok(self):
        """Set mag heading indicator to OK state (green solid)."""
        if self.mag_heading_ok != True:
            self.mag_heading_ok = True
            self._draw_mag_heading_indicator()
            self.i75.update()
    
    def set_mag_heading_stale(self):
        """Set mag heading indicator to stale state (red blinking)."""
        if self.mag_heading_ok != False:
            self.mag_heading_ok = False
            self.indicator_blink_state = False
            self._draw_mag_heading_indicator()
            self.i75.update()
    
    def update_blink(self):
        """Update blinking animation for any stale indicators and the running indicator.
        Should be called periodically from blink task.
        """
        if not self.graphics:
            return
        
        # Always update blink state for the running indicator
        current_ms = _ticks_ms()
        if _ticks_diff(current_ms, self.last_blink_ms) >= INDICATOR_BLINK_INTERVAL:
            self.indicator_blink_state = not self.indicator_blink_state
            self.last_blink_ms = current_ms
            
            # Always draw the running indicator
            self._draw_running_indicator()
            
            # Always draw RSSI bars
            self._draw_rssi_bars()
            
            # Update status indicators if they need blinking
            if not self.heartbeat_ok:
                self._draw_heartbeat_indicator()
            if not self.mag_heading_ok:
                self._draw_mag_heading_indicator()

            
            self.i75.update()
    
    def _draw_heartbeat_indicator(self):
        """Draw the heartbeat indicator in bottom left corner."""
        if not self.graphics:
            return
        
        try:
            if self.heartbeat_ok:
                # Green solid = heartbeat OK
                self.graphics.set_pen(self.pen_green_bright)
            else:
                # Red blinking = heartbeat stale
                if self.indicator_blink_state:
                    self.graphics.set_pen(self.pen_red_bright)
                else:
                    self.graphics.set_pen(self.pen_red_dim)
            
            self.graphics.rectangle(INDICATOR_LEFT_X, INDICATOR_Y, INDICATOR_WIDTH, INDICATOR_HEIGHT)
            
        except Exception as e:
            print("Heartbeat indicator draw error: {}".format(e))
    
    def _draw_mag_heading_indicator(self):
        """Draw the mag heading indicator in bottom right corner."""
        if not self.graphics:
            return
        
        try:
            if self.mag_heading_ok:
                # Green solid = heading OK
                self.graphics.set_pen(self.pen_green_bright)
            else:
                # Red blinking = heading stale
                if self.indicator_blink_state:
                    self.graphics.set_pen(self.pen_red_bright)
                else:
                    self.graphics.set_pen(self.pen_red_dim)
            
            self.graphics.rectangle(INDICATOR_RIGHT_X, INDICATOR_Y, INDICATOR_WIDTH, INDICATOR_HEIGHT)
            
        except Exception as e:
            print("Mag heading indicator draw error: {}".format(e))
    
    def _draw_running_indicator(self):
        """Draw the running status indicator in bottom center (white blinking)."""
        if not self.graphics:
            return
        
        try:
            # White blinking - always blinks to show program is running
            if self.indicator_blink_state:
                self.graphics.set_pen(self.pen_white)
            else:
                self.graphics.set_pen(self.pen_black)
            
            self.graphics.rectangle(INDICATOR_CENTER_X, INDICATOR_Y, INDICATOR_RUNNING_WIDTH, INDICATOR_HEIGHT)
            
        except Exception as e:
            print("Running indicator draw error: {}".format(e))
    
    def _draw_rssi_bars(self):
        """Draw the RSSI signal strength bars in the status area.
        
        Draws 0-5 bars based on WiFi signal strength:
        - 5 bars: -30 to -50 dBm (Excellent)
        - 4 bars: -50 to -60 dBm (Good)
        - 3 bars: -60 to -67 dBm (Fair)
        - 2 bars: -67 to -70 dBm (Weak)
        - 1 bar:  -70 to -80 dBm (Very weak)
        - 0 bars: worse than -80 dBm
        
        Each bar is 1 pixel wide and 4 pixels high, positioned at columns 16-20.
        """
        if not self.graphics:
            return
        
        try:
            # Draw each bar position
            for bar_num in range(RSSI_BAR_COUNT):
                bar_x = RSSI_BAR_START_X + bar_num
                
                if bar_num < self.rssi_bars:
                    # This bar should be lit (green)
                    self.graphics.set_pen(self.pen_blue_bright)
                else:
                    # This bar should be off (black)
                    self.graphics.set_pen(self.pen_black)
                
                # Draw the bar (1 pixel wide, 4 pixels high)
                self.graphics.rectangle(bar_x, RSSI_BAR_Y, RSSI_BAR_WIDTH, RSSI_BAR_HEIGHT)
            
        except Exception as e:
            print("RSSI bars draw error: {}".format(e))

    
    def update_heading(self, heading_radians):
        """Update the display with new heading value.
        
        Args:
            heading_radians: Heading in radians (after EWMA filter)
        """
        if not self.graphics:
            return
        
        try:
            # Convert radians to degrees and normalize to 0-359
            heading_degrees = int(heading_radians * RAD_TO_DEG) % 360
            
            # Only update if heading changed
            if heading_degrees == self.last_heading:
                return
            
            self.last_heading = heading_degrees
            
            # Redraw the entire display
            self._redraw_display()
            
        except Exception as e:
            print("Display update error: {}".format(e))
    
    def update_autopilot_state(self, state):
        """Update autopilot state.
        
        Args:
            state: Autopilot state string (e.g., "auto", "standby")
        """
        if not self.graphics:
            return
        
        try:
            # Convert to lowercase for comparison
            state_lower = str(state).lower() if state else None
            
            # Only update if state changed
            if state_lower == self.autopilot_state:
                return
            
            self.autopilot_state = state_lower
            
            # Redraw the entire display
            self._redraw_display()
            
        except Exception as e:
            print("Display autopilot state update error: {}".format(e))
    
    def update_target_heading(self, target_radians):
        """Update target heading.
        
        Args:
            target_radians: Target heading in radians
        """
        if not self.graphics:
            return
        
        try:
            # Convert radians to degrees and normalize to 0-359
            target_degrees = int(target_radians * RAD_TO_DEG) % 360
            
            # Only update if target changed
            if target_degrees == self.last_target:
                return
            
            self.last_target = target_degrees
            
            # Redraw the entire display
            self._redraw_display()
            
        except Exception as e:
            print("Display target heading update error: {}".format(e))
    
    def update_rssi(self, rssi_dbm):
        """Update RSSI signal strength bars.
        
        Args:
            rssi_dbm: WiFi signal strength in dBm (typically -30 to -90)
        """
        if not self.graphics:
            return
        
        try:
            # Determine number of bars based on signal strength
            # 5 bars: -30 to -50 dBm (Excellent)
            # 4 bars: -50 to -60 dBm (Good)
            # 3 bars: -60 to -67 dBm (Fair)
            # 2 bars: -67 to -70 dBm (Weak)
            # 1 bar:  -70 to -80 dBm (Very weak)
            # 0 bars: worse than -80 dBm
            
            if rssi_dbm is None:
                bars = 0
            elif rssi_dbm >= -50:
                bars = 5
            elif rssi_dbm >= -60:
                bars = 4
            elif rssi_dbm >= -67:
                bars = 3
            elif rssi_dbm >= -70:
                bars = 2
            elif rssi_dbm >= -80:
                bars = 1
            else:
                bars = 0
            
            # Only update if bars changed
            if bars != self.rssi_bars or rssi_dbm != self.rssi_dbm:
                self.rssi_dbm = rssi_dbm
                self.rssi_bars = bars
                # The bars will be drawn in the next update_blink() call
            
        except Exception as e:
            print("RSSI update error: {}".format(e))
    
    def _redraw_display(self):
        """Internal method to redraw the entire display with current values."""
        if not self.graphics:
            return
        
        try:
            # Clear the top and middle sections (rows 0-42)
            self.graphics.set_pen(self.pen_black)
            self.graphics.rectangle(0, 0, 64, 43)
            
            # Draw the current heading (top section) if available
            if self.last_heading is not None:
                heading_str = "{:03d}".format(self.last_heading)
                text = "C{}".format(heading_str)
                
                self.graphics.set_pen(self.pen_white)
                self.graphics.text(text, 4, 10, scale=TEXT_SCALE)
            
            # Draw the target heading (middle section) ONLY if in auto mode
            if self.autopilot_state == "auto" and self.last_target is not None:
                target_str = "{:03d}".format(self.last_target)
                text = "A{}".format(target_str)
                
                self.graphics.set_pen(self.pen_white)
                self.graphics.text(text, 4, 31, scale=TEXT_SCALE)
            
            # Redraw heartbeat indicator after clearing display
            self._draw_heartbeat_indicator()
            
            # Update the physical display
            self.i75.update()
            
        except Exception as e:
            print("Display redraw error: {}".format(e))
    
    def show_status(self, status_text):
        """Show status message (currently disabled - status shown via print statements).
        
        Args:
            status_text: Text to display (ignored)
        """
        # Status messages are too large for the 3-pixel status bar
        # They're logged to console instead
        # The heading display is the primary visual indicator
        pass

# ============================================================================
# WIFI CONNECTION
# ============================================================================

def is_wifi_connected():
    """Check if WiFi is connected."""
    wlan = network.WLAN(network.STA_IF)
    return wlan.isconnected() and wlan.ifconfig()[0] != "0.0.0.0"


async def connect_wifi(retry_delay=2):
    """Connect to WiFi network."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if is_wifi_connected():
        return wlan.ifconfig()[0]
    
    if USE_STATIC_IP:
        wlan.ifconfig((STATIC_IP, STATIC_SUBNET, STATIC_GATEWAY, STATIC_DNS))
    
    wlan.connect(SSID, PASSWORD)
    
    # Wait for connection
    timeout = 10
    start = _time()
    while _time() - start < timeout:
        if is_wifi_connected():
            return wlan.ifconfig()[0]
        await asyncio.sleep(retry_delay)
    
    raise Exception("WiFi connection failed")


# ============================================================================
# WEBSOCKET CLIENT
# ============================================================================

class SimpleWebSocketClient:
    """Simple async WebSocket client."""
    
    def __init__(self):
        """Initialize WebSocket client."""
        self.sock = None
        self.connected = False
    
    async def connect(self, host, port, path):
        """Connect to WebSocket server."""
        addr = socket.getaddrinfo(host, port)[0][-1]
        
        self.sock = socket.socket()
        self.sock.setblocking(False)
        
        try:
            self.sock.connect(addr)
        except OSError as e:
            if e.args[0] != 115:  # EINPROGRESS
                raise
        
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
        
        # Read HTTP response
        await asyncio.sleep(0.2)
        response = b""
        try:
            while True:
                chunk = self.sock.recv(WS_RECV_HTTP)
                if not chunk:
                    break
                response += chunk
                if b"\r\n\r\n" in response:
                    break
        except OSError:
            pass
        
        if b"101" not in response:
            raise Exception("WebSocket handshake failed")
        
        self.connected = True
    
    async def send_text(self, text):
        """Send text frame."""
        if not self.connected:
            raise Exception("Not connected")
        
        # Text frame: FIN + opcode 1
        frame = bytearray([0x81])
        
        # Payload length and mask
        payload = text.encode()
        length = len(payload)
        
        if length < 126:
            frame.append(0x80 | length)  # Masked + length
        elif length < 65536:
            frame.append(0x80 | 126)
            frame.extend(length.to_bytes(2, 'big'))
        else:
            frame.append(0x80 | 127)
            frame.extend(length.to_bytes(8, 'big'))
        
        # Masking key
        mask = bytes([0, 0, 0, 0])
        frame.extend(mask)
        
        # Masked payload
        frame.extend(payload)
        
        self.sock.send(frame)
    
    async def receive_frame(self, timeout=None):
        """Receive WebSocket frame."""
        if not self.connected:
            return None, None
        
        start_time = _time()
        
        # Read frame header (2 bytes)
        header = bytearray()
        while len(header) < 2:
            if timeout and (_time() - start_time) > timeout:
                return None, None
            try:
                chunk = self.sock.recv(2 - len(header))
                if chunk:
                    header.extend(chunk)
                else:
                    await asyncio.sleep(0.01)
            except OSError:
                await asyncio.sleep(0.01)
        
        # Parse header
        fin = header[0] & 0x80
        opcode = header[0] & 0x0F
        masked = header[1] & 0x80
        payload_len = header[1] & 0x7F
        
        # Extended payload length
        if payload_len == 126:
            len_bytes = bytearray()
            while len(len_bytes) < 2:
                if timeout and (_time() - start_time) > timeout:
                    return None, None
                try:
                    chunk = self.sock.recv(2 - len(len_bytes))
                    if chunk:
                        len_bytes.extend(chunk)
                    else:
                        await asyncio.sleep(0.01)
                except OSError:
                    await asyncio.sleep(0.01)
            payload_len = int.from_bytes(len_bytes, 'big')
        elif payload_len == 127:
            len_bytes = bytearray()
            while len(len_bytes) < 8:
                if timeout and (_time() - start_time) > timeout:
                    return None, None
                try:
                    chunk = self.sock.recv(8 - len(len_bytes))
                    if chunk:
                        len_bytes.extend(chunk)
                    else:
                        await asyncio.sleep(0.01)
                except OSError:
                    await asyncio.sleep(0.01)
            payload_len = int.from_bytes(len_bytes, 'big')
        
        # Read mask key if present (4 bytes)
        if masked:
            mask_key = bytearray()
            while len(mask_key) < 4:
                if timeout and (_time() - start_time) > timeout:
                    return None, None
                try:
                    chunk = self.sock.recv(4 - len(mask_key))
                    if chunk:
                        mask_key.extend(chunk)
                    else:
                        await asyncio.sleep(0.01)
                except OSError:
                    await asyncio.sleep(0.01)
        
        # Read payload
        payload = bytearray()
        while len(payload) < payload_len:
            if timeout and (_time() - start_time) > timeout:
                return None, None
            try:
                remaining = payload_len - len(payload)
                chunk = self.sock.recv(min(remaining, WS_RECV_PAYLOAD))
                if chunk:
                    payload.extend(chunk)
                else:
                    await asyncio.sleep(0.01)
            except OSError:
                await asyncio.sleep(0.01)
        
        # Unmask if needed
        if masked:
            for i in range(len(payload)):
                payload[i] ^= mask_key[i % 4]
        
        return opcode, bytes(payload)
    
    def close(self):
        """Close connection."""
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        self.sock = None
        self.connected = False


# ============================================================================
# SIGNAL K SUBSCRIPTION
# ============================================================================

async def subscribe_to_signal_k(ws_client):
    """Subscribe to Signal K paths."""
    
    # Build subscription request
    subscription = {
        "context": "vessels.self",
        "subscribe": []
    }
    
    # Add each path
    for path in SUBSCRIBE.split(','):
        path = path.strip()
        if path:
            subscription["subscribe"].append({
                "path": path,
                "period": 1000,
                "format": "delta",
                "policy": "instant",
                "minPeriod": 200
            })
    
    # Send subscription
    await ws_client.send_text(json.dumps(subscription))


# ============================================================================
# VALUE CHANGE MONITOR
# ============================================================================

class ValueChangeMonitor:
    """Monitor a value for changes and timeouts."""
    
    def __init__(self, timeout_seconds, tolerance=0.0, debug=False):
        """Initialize monitor.
        
        Args:
            timeout_seconds: Time in seconds before considering data stale
            tolerance: Minimum change to consider value changed (for numeric values)
            debug: Enable debug output
        """
        self.timeout_seconds = timeout_seconds
        self.tolerance = tolerance
        self.debug = debug
        self.last_update_time = None
        self.last_value = None
        self.is_fresh = False
    
    def update_value(self, new_value):
        """Update with new value and check for changes.
        
        Args:
            new_value: New value received
            
        Returns:
            True if state changed from stale to fresh, False otherwise
        """
        current_time = _time()
        value_changed = False
        
        # Check if value actually changed
        if self.last_value is None:
            value_changed = True
        elif isinstance(new_value, (int, float)) and isinstance(self.last_value, (int, float)):
            # For numeric values, check against tolerance
            value_changed = abs(new_value - self.last_value) > self.tolerance
        else:
            # For other types, check equality
            value_changed = new_value != self.last_value
        
        # Update tracking
        was_fresh = self.is_fresh
        if value_changed:
            self.last_update_time = current_time
            self.last_value = new_value
            self.is_fresh = True
        
        # Return True if state changed from stale to fresh
        return not was_fresh and self.is_fresh and value_changed
    
    def check_timeout(self):
        """Check if data has timed out.
        
        Returns:
            True if state changed from fresh to stale, False otherwise
        """
        if self.last_update_time is None:
            return False
        
        current_time = _time()
        time_since_update = current_time - self.last_update_time
        
        was_fresh = self.is_fresh
        if time_since_update > self.timeout_seconds:
            self.is_fresh = False
        
        # Return True if state changed from fresh to stale
        return was_fresh and not self.is_fresh
    
    def reset(self):
        """Reset monitor state."""
        self.last_update_time = None
        self.last_value = None
        self.is_fresh = False


class HeartbeatMonitor(ValueChangeMonitor):
    """Specialized monitor for heartbeat signals."""
    
    def __init__(self, timeout_seconds, debug=False):
        super().__init__(timeout_seconds, tolerance=0.0, debug=debug)
    
    def update_heartbeat(self):
        """Update heartbeat timestamp.
        
        Returns:
            True if state changed from stale to fresh, False otherwise
        """
        # For heartbeat, we just care that we received something
        return self.update_value(_time())


# ============================================================================
# EWMA FILTER
# ============================================================================

class EWMAFilter:
    """Exponential Weighted Moving Average filter for smoothing values."""
    
    def __init__(self, alpha=0.2):
        """Initialize EWMA filter.
        
        Args:
            alpha: Smoothing factor (0.0-1.0). Lower values = more smoothing.
                   alpha=1.0 means no smoothing (just pass through values)
                   alpha=0.0 means infinite smoothing (value never changes)
        """
        self.alpha = max(0.0, min(1.0, alpha))  # Clamp to valid range
        self.value = None
        self.initialized = False
    
    def update(self, new_value):
        """Update filter with new value and return smoothed result.
        
        Args:
            new_value: New raw value
            
        Returns:
            Smoothed value
        """
        if new_value is None:
            return self.value
        
        if not self.initialized:
            # Initialize with first value
            self.value = new_value
            self.initialized = True
        else:
            # Apply EWMA: value = alpha * new_value + (1 - alpha) * old_value
            self.value = self.alpha * new_value + (1.0 - self.alpha) * self.value
        
        return self.value
    
    def reset(self):
        """Reset filter state."""
        self.value = None
        self.initialized = False
    
    def get_value(self):
        """Get current smoothed value without updating."""
        return self.value


# ============================================================================
# MONITORING LOOP
# ============================================================================

async def monitor(display=None, heartbeat_monitor=None, mag_heading_monitor=None):
    """Main monitoring loop.
    
    Args:
        display: Optional DisplayManager instance (created externally to share with blink task)
        heartbeat_monitor: Optional HeartbeatMonitor instance (created externally to share with blink task)
        mag_heading_monitor: Optional ValueChangeMonitor instance (created externally to share with blink task)
    """
    
    # Initialize display if not provided
    if display is None:
        display = DisplayManager() if ENABLE_DISPLAY else None
    
    # Connect to WiFi
    wifi_retry_count = 0
    while True:
        try:
            backoff_delay = calculate_backoff(wifi_retry_count, WIFI_BACKOFF_INITIAL,
                                              WIFI_BACKOFF_MAX, WIFI_BACKOFF_MULTIPLIER)
            print("[{}] Connecting to WiFi...".format(get_timestamp()))
            ip = await connect_wifi()
            print("[{}] Connected! IP: {}".format(get_timestamp(), ip))
            wifi_retry_count = 0  # Reset on success
            
            if display:
                display.show_status("WIFI OK")
            
            break
        except Exception as e:
            print("[{}] WiFi failed: {}".format(get_timestamp(), e))
            wifi_retry_count += 1
            print("[{}] Will retry WiFi in {}s...".format(get_timestamp(), backoff_delay))
            await asyncio.sleep(backoff_delay)
    
    # Initialize message tracking
    messages_received = 0
    messages_skipped = 0
    gc_counter = 0  # Counter for manual GC triggering
    deduplicator = MessageDeduplicator(DEDUP_WINDOW_MS, DEDUP_CACHE_SIZE)
    
    # Initialize monitors if not provided
    if heartbeat_monitor is None:
        heartbeat_monitor = HeartbeatMonitor(HEARTBEAT_TIMEOUT, debug=HEARTBEAT_DEBUG)
    if mag_heading_monitor is None:
        mag_heading_monitor = ValueChangeMonitor(MAG_HEADING_TIMEOUT, 
                                                tolerance=MAG_HEADING_TOLERANCE,
                                                debug=MAG_HEADING_DEBUG)
    
    # Initialize EWMA filter for heading
    heading_ewma_filter = None
    if ENABLE_HEADING_EWMA:
        heading_ewma_filter = EWMAFilter(alpha=HEADING_EWMA_ALPHA)
        print("[{}] EWMA filter enabled for navigation.headingMagnetic (alpha={})".format(
            get_timestamp(), HEADING_EWMA_ALPHA))
    
    # Parse subscription paths for confirmation tracking
    subscription_paths = [p.strip() for p in SUBSCRIBE.split(',') if p.strip()]
    subscriptions_confirmed = {sub: False for sub in subscription_paths}
    
    # Connect to Signal K
    ws_client = None
    signalk_retry_count = 0
    
    while True:
        try:
            # FIX: Check WiFi status and reconnect with backoff if needed
            if not is_wifi_connected():
                print("[{}] WiFi disconnected, reconnecting...".format(get_timestamp()))
                if ws_client:
                    ws_client.close()
                ws_client = None
                subscriptions_confirmed = {sub: False for sub in subscription_paths}
                heartbeat_monitor.reset()
                mag_heading_monitor.reset()
                if heading_ewma_filter:
                    heading_ewma_filter.reset()
                if display:
                    display.show_status("NO WIFI")
                
                # FIX: Actually attempt to reconnect with exponential backoff
                while not is_wifi_connected():
                    try:
                        backoff_delay = calculate_backoff(wifi_retry_count, WIFI_BACKOFF_INITIAL,
                                                          WIFI_BACKOFF_MAX, WIFI_BACKOFF_MULTIPLIER)
                        print("[{}] Attempting WiFi reconnection in {}s...".format(get_timestamp(), backoff_delay))
                        await asyncio.sleep(backoff_delay)
                        
                        print("[{}] Connecting to WiFi...".format(get_timestamp()))
                        ip = await connect_wifi()
                        print("[{}] WiFi reconnected! IP: {}".format(get_timestamp(), ip))
                        wifi_retry_count = 0  # Reset on success
                        
                        if display:
                            display.show_status("WIFI OK")
                        break
                    except Exception as e:
                        print("[{}] WiFi reconnection failed: {}".format(get_timestamp(), e))
                        wifi_retry_count += 1
                
                # After reconnecting WiFi, continue to reconnect to Signal K
                continue
            
            if not ws_client:
                backoff_delay = calculate_backoff(signalk_retry_count, SIGNALK_BACKOFF_INITIAL,
                                                  SIGNALK_BACKOFF_MAX, SIGNALK_BACKOFF_MULTIPLIER)
                print("[{}] Connecting to Signal K at {}:{}...".format(get_timestamp(), HOST, PORT))
                
                if display:
                    display.show_status("CONNECT")
                
                ws_client = SimpleWebSocketClient()
                await ws_client.connect(HOST, PORT, "/signalk/{}/stream".format(VERSION))
                print("[{}] Connected to Signal K!".format(get_timestamp()))
                
                signalk_retry_count = 0  # Reset on success
                subscriptions_confirmed = {sub: False for sub in subscription_paths}
                
                # Subscribe
                print("[{}] Subscribing to paths...".format(get_timestamp()))
                await subscribe_to_signal_k(ws_client)
                
                if display:
                    display.show_status("SUB OK")
                
                # Wait briefly for subscription confirmation
                await asyncio.sleep(SUBSCRIPTION_INITIAL_WAIT)
            
            # Check for subscription confirmations periodically
            all_confirmed = all(subscriptions_confirmed.values())
            if not all_confirmed:
                unconfirmed = [path for path, confirmed in subscriptions_confirmed.items() if not confirmed]
                print("[{}] Waiting for subscription confirmations: {}".format(
                    get_timestamp(), ", ".join(unconfirmed)))
            
            # Check monitors for timeouts
            if heartbeat_monitor.check_timeout():
                print("[{}] *** WARNING: Heartbeat timeout - Signal K data may be STALE ***".format(
                    get_timestamp()))
            
            if mag_heading_monitor.check_timeout():
                print("[{}] *** WARNING: Heading timeout - Magnetic heading data may be STALE ***".format(
                    get_timestamp()))
            
            # Receive frame
            opcode, payload = await ws_client.receive_frame(timeout=CONNECTION_TIMEOUT)
            
            if payload is not None:
                timestamp = get_timestamp()
                
                if opcode == WS_OPCODE_TEXT:  # Text frame
                    try:
                        text = payload.decode('utf-8')
                        
                        # Try to parse as JSON
                        try:
                            msg = json.loads(text)
                            
                            # Handle delta updates
                            if 'updates' in msg:
                                updates = msg.get('updates', [])
                                current_ms = _ticks_ms()
                                
                                # Track if entire message should be printed
                                has_new_data = False
                                
                                for update in updates:
                                    update_timestamp = update.get('timestamp', '')
                                    source_info = update.get('$source') or update.get('source', {})
                                    # Avoid creating new string if already a string
                                    source_str = source_info if isinstance(source_info, str) else str(source_info)
                                    
                                    values = update.get('values', [])
                                    for value_item in values:
                                        value_path = value_item.get('path', '')
                                        value_data = value_item.get('value')
                                        
                                        # Apply EWMA filter to navigation.headingMagnetic if enabled
                                        if value_path == MAG_HEADING_PATH and heading_ewma_filter is not None:
                                            if value_data is not None:
                                                value_data = heading_ewma_filter.update(value_data)
                                                # Update display with filtered heading
                                                if display:
                                                    display.update_heading(value_data)
                                        
                                        # Update autopilot state on display
                                        if value_path == "steering.autopilot.state":
                                            if display:
                                                display.update_autopilot_state(value_data)
                                        
                                        # Update target heading on display
                                        if value_path == "steering.autopilot.target.headingMagnetic":
                                            if display and value_data is not None:
                                                display.update_target_heading(value_data)
                                        
                                        # Check for heartbeat and update monitor
                                        if value_path == HEARTBEAT_PATH:
                                            state_changed = heartbeat_monitor.update_heartbeat()
                                            if HEARTBEAT_DEBUG and state_changed:
                                                print("[{}] *** Heartbeat detected - Signal K data is now FRESH ***".format(timestamp))
                                        
                                        # Check for magnetic heading changes and update monitor
                                        if value_path == MAG_HEADING_PATH:
                                            state_changed = mag_heading_monitor.update_value(value_data)
                                            if MAG_HEADING_DEBUG and state_changed:
                                                print("[{}] *** Heading changed - Magnetic heading data is now FRESH ***".format(timestamp))
                                        
                                        # Check subscription confirmation (only if not yet confirmed)
                                        if value_path:
                                            for sub_path in subscription_paths:
                                                if not subscriptions_confirmed[sub_path] and sub_path in value_path:
                                                    subscriptions_confirmed[sub_path] = True
                                                    print("[{}] *** Subscription confirmed: {} ***".format(
                                                        timestamp, sub_path))
                                                    break  # No need to check other subscriptions for this path
                                        
                                        # Check for duplicates
                                        messages_received += 1
                                        gc_counter += 1
                                        
                                        # Periodic garbage collection every 100 messages
                                        if gc_counter >= GC_COLLECT_INTERVAL:
                                            _gc_collect()
                                            gc_counter = 0
                                        
                                        is_dup = deduplicator.is_duplicate(
                                            update_timestamp, source_str, value_path, value_data
                                        )
                                        
                                        if is_dup:
                                            messages_skipped += 1
                                        else:
                                            has_new_data = True
                                            
                                            # Print path and value in simplified format if enabled
                                            if PRINT_PATH_VALUE and not PRINT_FULL_JSON:
                                                # Convert radians to degrees for heading values
                                                display_value = value_data
                                                if value_data is not None and (value_path == MAG_HEADING_PATH or value_path == "steering.autopilot.target.headingMagnetic"):
                                                    display_value = int(value_data * RAD_TO_DEG)
                                                    print("[{}] {} = {}°".format(timestamp, value_path, display_value))
                                                else:
                                                    print("[{}] {} = {}".format(timestamp, value_path, value_data))
                                
                                # Print message if it contains non-duplicate data
                                if has_new_data:
                                    if PRINT_FULL_JSON:
                                        if ENABLE_DEDUPLICATION and messages_skipped > 0:
                                            
                                            skip_pct = (messages_skipped * PERCENT_MULTIPLIER) // messages_received if messages_received > 0 else 0
                                            
                                            
                                            print("[{}] TEXT: {} [dedup: {}/{} skipped ({}.{}%)]".format(
                                                timestamp, text, messages_skipped, messages_received, 
                                                skip_pct // PERCENT_DECIMAL_DIVISOR, skip_pct % PERCENT_DECIMAL_DIVISOR))
                                        else:
                                            print("[{}] TEXT: {}".format(timestamp, text))
                                # If all values were duplicates, just note it
                                
                                #elif ENABLE_DEDUPLICATION:
                                    
                                    ###################################################################
                                    #print("[{}] [duplicate message skipped]".format(timestamp))
                                    ###################################################################                                 
                            else:
                                # Non-update message (like hello), always print
                                print("[{}] TEXT: {}".format(timestamp, text))
                        
                        except Exception:
                            # JSON parse failed or other error, print as-is
                            print("[{}] TEXT: {}".format(timestamp, text))
                    
                    except Exception:
                        print("[{}] TEXT (decode error): {} bytes".format(timestamp, len(payload)))
                
                elif opcode == WS_OPCODE_BINARY:  # Binary frame
                    print("[{}] BINARY: {} bytes".format(timestamp, len(payload)))
                elif opcode == WS_OPCODE_CLOSE:  # Close frame
                    print("[{}] CLOSE - server closed connection".format(timestamp))
                    ws_client.close()
                    ws_client = None
                    subscriptions_confirmed = {sub: False for sub in subscription_paths}
                    heartbeat_monitor.reset()  # Reset monitors on close
                    mag_heading_monitor.reset()
                    if heading_ewma_filter:
                        heading_ewma_filter.reset()
                    if display:
                        display.show_status("CLOSED")
                elif opcode == WS_OPCODE_PING:  # Ping frame
                    print("[{}] PING".format(timestamp))
                elif opcode == WS_OPCODE_PONG:  # Pong frame
                    print("[{}] PONG".format(timestamp))
                else:
                    print("[{}] OPCODE 0x{:X}: {} bytes".format(timestamp, opcode, len(payload)))
            else:
                # No frame received - connection may be dead
                print("[{}] No frame received - connection lost".format(get_timestamp()))
                if ws_client:
                    ws_client.close()
                ws_client = None
                subscriptions_confirmed = {sub: False for sub in subscription_paths}
                heartbeat_monitor.reset()  # Reset monitors on connection loss
                mag_heading_monitor.reset()
                if heading_ewma_filter:
                    heading_ewma_filter.reset()
                if display:
                    display.show_status("NO DATA")
        
        except Exception as e:
            backoff_delay = calculate_backoff(signalk_retry_count, SIGNALK_BACKOFF_INITIAL,
                                              SIGNALK_BACKOFF_MAX, SIGNALK_BACKOFF_MULTIPLIER)
            print("[{}] Error: {}".format(get_timestamp(), e))
            if ws_client:
                ws_client.close()
            ws_client = None
            subscriptions_confirmed = {sub: False for sub in subscription_paths}
            heartbeat_monitor.reset()  # Reset monitors on error
            mag_heading_monitor.reset()
            if heading_ewma_filter:
                heading_ewma_filter.reset()
            if display:
                display.show_status("ERROR")
            signalk_retry_count += 1
            _gc_collect()  # Clean up after error
            print("[{}] Will reconnect Signal K in {}s...".format(get_timestamp(), backoff_delay))
            await asyncio.sleep(backoff_delay)
        
        await asyncio.sleep(0)


async def wifi_signal_monitor_task(display, rssi_ewma_filter=None):
    """Independent async task to monitor WiFi signal strength.
    
    Checks WiFi signal strength (RSSI) every 1 second and updates the display.
    This runs in parallel with other tasks without interfering.
    
    Args:
        display: DisplayManager instance (can be None if display not available)
        rssi_ewma_filter: Optional EWMAFilter instance for smoothing RSSI values
    """
    print("[{}] WiFi signal monitor task started".format(get_timestamp()))
    
    while True:
        try:
            # Get the WLAN interface (returns existing interface if already created)
            wlan = network.WLAN(network.STA_IF)
            
            if wlan and wlan.isconnected():
                # Get signal strength (RSSI - Received Signal Strength Indicator)
                # Typical range: -30 (excellent) to -90 (poor) dBm
                rssi = wlan.status('rssi')
                
                # Apply EWMA filter if enabled
                if rssi_ewma_filter:
                    rssi = rssi_ewma_filter.update(rssi)
                    # Round to nearest integer for display
                    rssi = round(rssi) if rssi is not None else None
                
                print("[{}] WiFi Signal Strength: {} dBm".format(get_timestamp(), rssi))
                
                # Update display if available
                if display:
                    display.update_rssi(rssi)
            else:
                print("[{}] WiFi Signal Strength: Not connected".format(get_timestamp()))
                
                # Reset EWMA filter when disconnected
                if rssi_ewma_filter:
                    rssi_ewma_filter.reset()
                
                # Update display to show no signal if available
                if display:
                    display.update_rssi(None)
            
            # Wait 1 second before next check
            await asyncio.sleep(1)
            
        except Exception as e:
            print("[{}] WiFi signal monitor error: {}".format(get_timestamp(), e))
            await asyncio.sleep(1)  # Wait before retrying



async def heartbeat_blink_task(display, heartbeat_monitor, mag_heading_monitor):
    """Independent async task to handle heartbeat indicator blinking and state checking.
    
    This runs in parallel with the main monitor loop to ensure consistent
    blinking at the configured interval, regardless of WebSocket state.
    
    DESIGN NOTE: This task is the SINGLE SOURCE OF TRUTH for indicator display state.
    The main loop updates monitor states (is_fresh flags), and this task reads those
    states every 500ms to update the indicators. This separation keeps the logic simple:
    - Main loop: Updates monitors based on data received
    - Blink task: Updates indicators based on monitor state
    
    Args:
        display: DisplayManager instance
        heartbeat_monitor: HeartbeatMonitor instance
        mag_heading_monitor: ValueChangeMonitor instance
    """
    if not display or not display.graphics:
        return
    
    print("[{}] Heartbeat blink task started".format(get_timestamp()))
    
    while True:
        try:
            # Check monitor states and update indicators if needed
            if heartbeat_monitor:
                if heartbeat_monitor.is_fresh and not display.heartbeat_ok:
                    display.set_heartbeat_ok()
                elif not heartbeat_monitor.is_fresh and display.heartbeat_ok:
                    display.set_heartbeat_stale()
            
            if mag_heading_monitor:
                if mag_heading_monitor.is_fresh and not display.mag_heading_ok:
                    display.set_mag_heading_ok()
                elif not mag_heading_monitor.is_fresh and display.mag_heading_ok:
                    display.set_mag_heading_stale()
            
            # Update blink animation
            display.update_blink()
            
            # Sleep for the blink interval (convert ms to seconds)
            await asyncio.sleep_ms(INDICATOR_BLINK_INTERVAL)
        except Exception as e:
            print("[{}] Blink task error: {}".format(get_timestamp(), e))
            await asyncio.sleep(1)  # Wait a bit before retrying


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    try:
        # Create shared instances for both tasks
        display_instance = DisplayManager() if ENABLE_DISPLAY else None
        heartbeat_monitor_instance = HeartbeatMonitor(HEARTBEAT_TIMEOUT, debug=HEARTBEAT_DEBUG)
        mag_heading_monitor_instance = ValueChangeMonitor(MAG_HEADING_TIMEOUT, 
                                                          tolerance=MAG_HEADING_TOLERANCE,
                                                          debug=MAG_HEADING_DEBUG)
        
        # Create RSSI EWMA filter if enabled
        rssi_ewma_filter_instance = EWMAFilter(RSSI_EWMA_ALPHA) if ENABLE_RSSI_EWMA else None
        
        # Create and run all tasks concurrently
        async def main():
            tasks = [monitor(display_instance, heartbeat_monitor_instance, mag_heading_monitor_instance)]
            
            # Add display blink task if display is available
            if display_instance and display_instance.graphics:
                tasks.append(heartbeat_blink_task(display_instance, heartbeat_monitor_instance, mag_heading_monitor_instance))
            
            # Add WiFi signal monitoring task (pass display for RSSI bars)
            tasks.append(wifi_signal_monitor_task(display_instance, rssi_ewma_filter_instance))

            
            await asyncio.gather(*tasks)
        
        asyncio.run(main())
            
    except KeyboardInterrupt:
        print("\n[{}] Stopped".format(get_timestamp()))
    except Exception as e:
        print("\n[{}] FATAL: {}".format(get_timestamp(), e))