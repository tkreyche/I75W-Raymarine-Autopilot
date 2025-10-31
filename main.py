# Simple WebSocket Frame Monitor - Raw frames with timestamps
import secrets
import time
import network
import uasyncio as asyncio
import socket
import ubinascii
import gc

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

# Radian to degree conversion constant (more efficient than math.degrees)
RAD_TO_DEG = 57.29577951308232  # 180 / π

# Display settings
ENABLE_DISPLAY = getattr(secrets, 'ENABLE_DISPLAY', True) and DISPLAY_AVAILABLE
TEXT_SCALE = 0.7     # Scale for all text
TEXT_THICKNESS = 2   # Thickness for better visibility on LED matrix
COLOR_WHITE = (255, 255, 255)

# Status indicator settings
INDICATOR_BLINK_INTERVAL = getattr(secrets, 'INDICATOR_BLINK_INTERVAL', 500)  # ms between blinks
INDICATOR_LEFT_X = 0
INDICATOR_RIGHT_X = 54  # Right side (64 - 10 = 54)
INDICATOR_Y = 61
INDICATOR_WIDTH = 10
INDICATOR_HEIGHT = 3

# Indicator colors
COLOR_GREEN_BRIGHT = (0, 255, 0)
COLOR_RED_BRIGHT = (255, 0, 0)
COLOR_RED_DIM = (0, 0, 0)  # Off when blinking

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
        """Update blinking animation for any stale indicators.
        Should be called periodically from blink task.
        """
        if not self.graphics:
            return
        
        # Check if any indicator needs blinking
        needs_blink = not self.heartbeat_ok or not self.mag_heading_ok
        if not needs_blink:
            return
        
        current_ms = time.ticks_ms()
        if time.ticks_diff(current_ms, self.last_blink_ms) >= INDICATOR_BLINK_INTERVAL:
            self.indicator_blink_state = not self.indicator_blink_state
            self.last_blink_ms = current_ms
            
            # Update both indicators if they need blinking
            if not self.heartbeat_ok:
                self._draw_heartbeat_indicator()
            if not self.mag_heading_ok:
                self._draw_mag_heading_indicator()
            
            self.i75.update()
    
    def _draw_heartbeat_indicator(self):
        """Draw the heartbeat status indicator in lower left corner."""
        if not self.graphics:
            return
        
        try:
            if self.heartbeat_ok:
                # Green solid - heartbeat is current
                self.graphics.set_pen(self.pen_green_bright)
            else:
                # Red blinking - heartbeat is stale
                if self.indicator_blink_state:
                    self.graphics.set_pen(self.pen_red_bright)
                else:
                    self.graphics.set_pen(self.pen_red_dim)
            
            self.graphics.rectangle(INDICATOR_LEFT_X, INDICATOR_Y, INDICATOR_WIDTH, INDICATOR_HEIGHT)
            
        except Exception as e:
            print("Heartbeat indicator draw error: {}".format(e))
    
    def _draw_mag_heading_indicator(self):
        """Draw the magnetic heading status indicator in lower right corner."""
        if not self.graphics:
            return
        
        try:
            if self.mag_heading_ok:
                # Green solid - mag heading is current
                self.graphics.set_pen(self.pen_green_bright)
            else:
                # Red blinking - mag heading is stale
                if self.indicator_blink_state:
                    self.graphics.set_pen(self.pen_red_bright)
                else:
                    self.graphics.set_pen(self.pen_red_dim)
            
            self.graphics.rectangle(INDICATOR_RIGHT_X, INDICATOR_Y, INDICATOR_WIDTH, INDICATOR_HEIGHT)
            
        except Exception as e:
            print("Mag heading indicator draw error: {}".format(e))
    
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


def connect_wifi(retry_delay=2):
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
    start = time.time()
    while time.time() - start < timeout:
        if is_wifi_connected():
            return wlan.ifconfig()[0]
        time.sleep(retry_delay)
    
    raise Exception("WiFi connection failed")


# ============================================================================
# WEBSOCKET CLIENT
# ============================================================================

class SimpleWebSocketClient:
    """Minimal WebSocket client."""
    
    def __init__(self):
        self.sock = None
        self.connected = False
    
    async def connect(self, host, port, path):
        """Connect and perform WebSocket handshake."""
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
                chunk = self.sock.recv(1024)
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
        
        start_time = time.time()
        
        # Read frame header
        header = bytearray()
        while len(header) < 2:
            if timeout and (time.time() - start_time) > timeout:
                return None, None
            try:
                chunk = self.sock.recv(1)
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
                if timeout and (time.time() - start_time) > timeout:
                    return None, None
                try:
                    chunk = self.sock.recv(1)
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
                if timeout and (time.time() - start_time) > timeout:
                    return None, None
                try:
                    chunk = self.sock.recv(1)
                    if chunk:
                        len_bytes.extend(chunk)
                    else:
                        await asyncio.sleep(0.01)
                except OSError:
                    await asyncio.sleep(0.01)
            payload_len = int.from_bytes(len_bytes, 'big')
        
        # Read mask key if present
        if masked:
            mask_key = bytearray()
            while len(mask_key) < 4:
                if timeout and (time.time() - start_time) > timeout:
                    return None, None
                try:
                    chunk = self.sock.recv(1)
                    if chunk:
                        mask_key.extend(chunk)
                    else:
                        await asyncio.sleep(0.01)
                except OSError:
                    await asyncio.sleep(0.01)
        
        # Read payload
        payload = bytearray()
        while len(payload) < payload_len:
            if timeout and (time.time() - start_time) > timeout:
                return None, None
            try:
                remaining = payload_len - len(payload)
                chunk = self.sock.recv(min(remaining, 1024))
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
# UTILITY FUNCTIONS
# ============================================================================

def get_timestamp():
    """Get formatted timestamp."""
    t = time.localtime()
    # Format: HH:MM:SS.mmm
    ms = time.ticks_ms() % 1000
    return "{:02d}:{:02d}:{:02d}.{:03d}".format(t[3], t[4], t[5], ms)


def calculate_backoff(attempt, initial, max_delay, multiplier):
    """Calculate exponential backoff delay."""
    delay = initial * (multiplier ** attempt)
    return min(delay, max_delay)


# ============================================================================
# MESSAGE DEDUPLICATION
# ============================================================================

class MessageDeduplicator:
    """Deduplicate Signal K messages based on timestamp, source, path, and value."""
    
    def __init__(self, window_ms=150, cache_size=50):
        """Initialize deduplicator.
        
        Args:
            window_ms: Time window in milliseconds for considering duplicates
            cache_size: Maximum number of recent messages to track
        """
        self.window_ms = window_ms
        self.cache_size = cache_size
        self.cache = []  # List of (timestamp_ms, hash) tuples
    
    def _compute_hash(self, timestamp, source, path, value):
        """Compute a simple hash for the message components."""
        # Convert value to string for hashing
        value_str = str(value) if value is not None else "None"
        # Combine components and compute hash
        combined = "{}:{}:{}:{}".format(timestamp, source, path, value_str)
        # Simple hash function
        h = 0
        for c in combined:
            h = (h * 31 + ord(c)) & 0xFFFFFFFF
        return h
    
    def is_duplicate(self, timestamp, source, path, value):
        """Check if message is a duplicate.
        
        Args:
            timestamp: Message timestamp string
            source: Message source string
            path: Data path string
            value: Data value
            
        Returns:
            True if message is a duplicate, False otherwise
        """
        if not ENABLE_DEDUPLICATION:
            return False
        
        current_ms = time.ticks_ms()
        msg_hash = self._compute_hash(timestamp, source, path, value)
        
        # Remove old entries outside the time window
        # Only clean up when cache is getting full to avoid constant list operations
        if len(self.cache) > int(self.cache_size * 0.8):
            # Remove expired entries in-place (iterate backwards to avoid index issues)
            i = len(self.cache) - 1
            while i >= 0:
                if time.ticks_diff(current_ms, self.cache[i][0]) >= self.window_ms:
                    self.cache.pop(i)
                i -= 1
        
        # Check if this hash exists in recent cache
        is_dup = any(h == msg_hash for _, h in self.cache)
        
        # Add to cache if not duplicate
        if not is_dup:
            self.cache.append((current_ms, msg_hash))
            # Trim cache if too large (remove oldest)
            if len(self.cache) > self.cache_size:
                self.cache.pop(0)
        
        return is_dup


# ============================================================================
# VALUE CHANGE MONITORING
# ============================================================================

class ValueChangeMonitor:
    """Monitor a specific value for changes and freshness."""
    
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
        current_time = time.time()
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
        
        current_time = time.time()
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
        return self.update_value(time.time())


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
            ip = connect_wifi()
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
                wifi_retry_count = 0
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
                
                if opcode == 0x1:  # Text frame
                    try:
                        text = payload.decode('utf-8')
                        
                        # Try to parse as JSON
                        try:
                            msg = json.loads(text)
                            
                            # Handle delta updates
                            if 'updates' in msg:
                                updates = msg.get('updates', [])
                                current_ms = time.ticks_ms()
                                
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
                                        
                                        # Periodic garbage collection every 100 messages
                                        if messages_received % 100 == 0:
                                            gc.collect()
                                        
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
                                            
                                            skip_pct = (messages_skipped * 100) // messages_received if messages_received > 0 else 0
                                            
                                            
                                            print("[{}] TEXT: {} [dedup: {}/{} skipped ({}.{}%)]".format(
                                                timestamp, text, messages_skipped, messages_received, 
                                                skip_pct // 10, skip_pct % 10))
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
                
                elif opcode == 0x2:  # Binary frame
                    print("[{}] BINARY: {} bytes".format(timestamp, len(payload)))
                elif opcode == 0x8:  # Close frame
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
                elif opcode == 0x9:  # Ping frame
                    print("[{}] PING".format(timestamp))
                elif opcode == 0xA:  # Pong frame
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
            gc.collect()  # Clean up after error
            print("[{}] Will reconnect Signal K in {}s...".format(get_timestamp(), backoff_delay))
            await asyncio.sleep(backoff_delay)
        
        await asyncio.sleep(0)


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
        
        # Create and run both tasks concurrently
        async def main():
            tasks = [monitor(display_instance, heartbeat_monitor_instance, mag_heading_monitor_instance)]
            if display_instance and display_instance.graphics:
                tasks.append(heartbeat_blink_task(display_instance, heartbeat_monitor_instance, mag_heading_monitor_instance))
            await asyncio.gather(*tasks)
        
        asyncio.run(main())
            
    except KeyboardInterrupt:
        print("\n[{}] Stopped".format(get_timestamp()))
    except Exception as e:
        print("\n[{}] FATAL: {}".format(get_timestamp(), e))