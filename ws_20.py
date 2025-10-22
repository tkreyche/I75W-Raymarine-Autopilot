# signalk_ws_i75w.py - Optimized for Pimoroni Interstate 75 W (RP2350)
# ========================================================================
# Signal K WebSocket client with HUB75 LED matrix display
#
# BOARD: Pimoroni Interstate 75 W
# --------------------------------
# - RP2350 dual-core Cortex-M33 @ 150MHz
# - 520KB SRAM (shared between cores)
# - Pico W wireless module (CYW43439)
# - HUB75 interface for LED matrices
#
# DISPLAY: 64x64 RGB LED Matrix
# ------------------------------
# Layout (three horizontal sections):
# • Top Section (0-21): Autopilot mode + Current heading
#   - "C" for standby (Compass display mode)
#   - "A" for auto (Auto mode)
#   - Three-digit heading: "045"
# • Middle Section (22-42): Target heading (auto mode only)
#   - "T" for target + Three-digit target heading: "270"
#   - Only displayed when autopilot is in auto mode
# • Bottom Section (43-63): Heading difference (auto mode only)
#   - Sign and three-digit value: "+015" or "-020"
#   - Positive = turn right to reach target, Negative = turn left
#   - Only displayed when autopilot is in auto mode
# • Activity Indicator: Bottom-right corner (61-63, 61-63)
#   - 3x3 pixel block that shows connection status
#   - Green (blinking): Data flowing normally
#   - Yellow (blinking): Data stale - no updates for 10+ seconds
#   - Red (blinking): Connection broken - no data for 20+ seconds

#Websockets
#--------------------------------
# uses library from:
# https://pypi.org/project/micropython-async-websocket-client/
# A client-specific library designed to maintain a persistent WebSocket connection in the background using asyncio. 
# Best for: Client-only projects, such as an IoT sensor sending data to a remote server
# Usage:
#>>> import mip
#>>> mip.install("github:Vovaman/micropython_async_websocket_client/async_websocket_client/ws.py")
# this will put the code in the lib folder

import math
import secrets
import time
import gc
import network
import uasyncio as asyncio

# Interstate 75 W display drivers
from interstate75 import Interstate75, DISPLAY_INTERSTATE75_64X64
from picographics import PicoGraphics, DISPLAY_INTERSTATE75_64X64

# Import external WebSocket library (from lib/ws.py)
from ws import AsyncWebsocketClient

# Import compatibility layer for different MicroPython builds
try:
    import json
except ImportError:
    import ujson as json

# ============================================================================
# USER CONFIGURATION
# ============================================================================

# WiFi Credentials
SSID = secrets.SSID
PASSWORD = secrets.PASSWORD

# Static IP Configuration (optional)
# If USE_STATIC_IP is False or not defined, DHCP will be used
USE_STATIC_IP = getattr(secrets, 'USE_STATIC_IP', False)
STATIC_IP = getattr(secrets, 'STATIC_IP', '192.168.1.100')
STATIC_SUBNET = getattr(secrets, 'STATIC_SUBNET', '255.255.255.0')
STATIC_GATEWAY = getattr(secrets, 'STATIC_GATEWAY', '192.168.1.1')
STATIC_DNS = getattr(secrets, 'STATIC_DNS', '8.8.8.8')

# Signal K Server
HOST = secrets.HOST
PORT = secrets.PORT
VERSION = secrets.VERSION

# SignalK Subscription Paths
# Not in secrets file because changing them would require code changes to handle display and printing
# Subscription Paths
SUBSCRIBE = (
    "navigation.headingMagnetic,"
    "steering.autopilot.state,"
    "steering.autopilot.target.headingMagnetic"
)

TOKEN = ""

# ============================================================================
# TIMING PARAMETERS
# ============================================================================

RECONNECT_WAIT = 3
PRINT_INTERVAL = 1  # Increase to 10+ to reduce console output for better performance
WIFI_CHECK_INTERVAL = 10
GC_INTERVAL = 30
DATA_STALE_TIMEOUT = 10   # Seconds without data before showing warning
DATA_DEAD_TIMEOUT = 20    # Seconds without data before showing error
INDICATOR_BLINK_INTERVAL = 0.5  # Seconds between indicator blinks

# Performance tuning
DEBUG_TIMING = secrets.DEBUG_TIMING # Set to True to print timing diagnostics for display updates
DEBUG_WS = secrets.DEBUG_WS     # Set to True to track and print WebSocket response time statistics

# Constants
RAD_TO_DEG = 57.2957795
HEADING_SMOOTHING = secrets.HEADING_SMOOTHING
                         # EMA smoothing factor for navigation heading
                         # Range: 0.0 (max smoothing) to 1.0 (no smoothing)
                         # Typical values: 0.1-0.3 for smooth display
                         #                 0.5-0.8 for responsive display
                         # Lower = smoother but SLOWER response (more lag)
                         # Higher = faster response but more jitter
                         # If display feels laggy, try increasing this value

# ============================================================================
# DISPLAY CONFIGURATION
# ============================================================================

# Display section boundaries (64 pixels tall / 3 sections)
TOP_SECTION_Y = 0       # Top section: 0-21 (22 pixels)
MID_SECTION_Y = 22      # Middle section: 22-42 (21 pixels)
BOT_SECTION_Y = 43      # Bottom section: 43-63 (21 pixels)
SECTION_HEIGHT = 21

# Display colors 
COLOR_BLACK = (0, 0, 0)
COLOR_AUTO = secrets.COLOR_AUTO    
COLOR_COMPASS = secrets.COLOR_COMPASS
COLOR_TARGET = secrets.COLOR_TARGET
COLOR_DIFF = secrets.COLOR_DIFF
COLOR_ERROR = secrets.COLOR_ERROR

# Text scaling (bitmap sans font with thickness)
TEXT_SCALE = 0.7     # Scale for all text
TEXT_SCALE_SMALL = 0.4     # Small scale
TEXT_THICKNESS = 2   # Thickness for better visibility on LED matrix
TEXT_THICKNESS_SMALL = 1 

# ============================================================================
# WEBSOCKET RESPONSE TIME TRACKER
# ============================================================================

class WSResponseTimeTracker:
    """Tracks WebSocket response time statistics with minimal overhead.
    
    When DEBUG_WS is True:
    - Records response time for each websocket.recv() call
    - Calculates min, max, and average response times
    - Prints statistics every minute
    
    When DEBUG_WS is False:
    - All methods become no-ops for minimal performance impact
    """
    
    def __init__(self, enabled):
        """Initialize the tracker.
        
        Args:
            enabled: True to enable tracking, False to disable
        """
        self.enabled = enabled
        if self.enabled:
            self.reset_stats()
            self.last_report_ms = time.ticks_ms()
            self.report_interval_ms = 60000  # 60 seconds
            print("WS Debug: Response time tracking enabled (60s reporting interval)")
    
    def reset_stats(self):
        """Reset all statistics."""
        if self.enabled:
            self.min_time = None
            self.max_time = None
            self.total_time = 0
            self.count = 0
    
    def record(self, response_time_ms):
        """Record a websocket response time.
        
        Args:
            response_time_ms: Response time in milliseconds
        """
        if not self.enabled:
            return
        
        # Update min/max
        if self.min_time is None or response_time_ms < self.min_time:
            self.min_time = response_time_ms
        if self.max_time is None or response_time_ms > self.max_time:
            self.max_time = response_time_ms
        
        # Update running totals
        self.total_time += response_time_ms
        self.count += 1
    
    def check_and_report(self, now_ms):
        """Check if it's time to report statistics and print if so.
        
        Args:
            now_ms: Current timestamp in milliseconds
        """
        if not self.enabled:
            return
        
        # Check if a minute has passed
        if time.ticks_diff(now_ms, self.last_report_ms) >= self.report_interval_ms:
            self.print_stats()
            self.reset_stats()
            self.last_report_ms = now_ms
    
    def print_stats(self):
        """Print current statistics."""
        if not self.enabled or self.count == 0:
            return
        
        avg_time = self.total_time / self.count
        print("\n" + "="*50)
        print("WS Response Time Statistics (last 60s):")
        print("  Messages: {}".format(self.count))
        print("  Min: {:.1f}ms".format(self.min_time))
        print("  Max: {:.1f}ms".format(self.max_time))
        print("  Avg: {:.1f}ms".format(avg_time))
        print("="*50 + "\n")

# ============================================================================
# DISPLAY MANAGEMENT
# ============================================================================

class DisplayManager:
    """Manages the 64x64 LED matrix display on Interstate 75 W.
    
    Responsibilities:
    -----------------
    • Initialize HUB75 display hardware
    • Manage display buffer and updates
    • Draw sectioned layout with autopilot status
    • Top section: Mode indicator + current heading
    • Middle section: Target heading (auto mode only)
    • Bottom section: Heading difference (auto mode only)
    • Activity indicator: Multi-state connection status (bottom-right corner)
      - Green (blinking): Healthy - data flowing
      - Yellow (blinking): Warning - data stale (10+ sec)
      - Red (blinking): Error - connection broken (20+ sec)
    • Minimize display updates (only on data changes)
    
    Display Memory:
    ---------------
    • 64x64 RGB display = 12,288 bytes (64*64*3)
    • Uses double buffering via PicoGraphics
    • Updates triggered only when data changes
    """
    
    def __init__(self):
        """Initialize Interstate 75 W display hardware."""
        print("Display: Initializing 64x64 matrix...")


        try:
            # Create Interstate75 instance with 64x64 display
            self.i75 = Interstate75(
                display=DISPLAY_INTERSTATE75_64X64,
                color_order=Interstate75.COLOR_ORDER_BGR
            )
            
            # Get the graphics object for drawing
            self.graphics = self.i75.display
            
            # Display dimensions
            self.width = 64
            self.height = 64
            
            # Set font to sans for cleaner look
            try:
                self.graphics.set_font("sans")
                self.graphics.set_thickness(TEXT_THICKNESS_SMALL)
                print("Display: Using 'sans' font with thickness {}".format(TEXT_THICKNESS_SMALL))
            except Exception as e:
                print("Display: Could not set sans font:", e)
                print("Display: Using default font")
            
            print("Display: Graphics object type:", type(self.graphics))
            print("Display: Width={}, Height={}".format(self.width, self.height))
            
          
            # Track last displayed values to minimize updates
            self.last_mode = None
            self.last_heading = None
            self.last_target = None
            self.last_diff = None
            
            # Activity indicator state
            self.activity_state = False
            self.indicator_color = "green"  # green, yellow, red
            
            # Initial clear
            self.graphics.set_pen(self.graphics.create_pen(*COLOR_BLACK))
            self.graphics.clear()
            self.i75.update()
            
            print("Display: Initialized successfully")
        
        except Exception as e:
            print("Display: Initialization FAILED:", e)
            raise
    
    def set_indicator_ok(self):
        """Set activity indicator to healthy state (green)."""
        if self.indicator_color != "green":
            self.indicator_color = "green"
            self.activity_state = False
    
    def set_indicator_warning(self):
        """Set activity indicator to warning state (yellow)."""
        if self.indicator_color != "yellow":
            self.indicator_color = "yellow"
            self.activity_state = False
            self.toggle_activity_indicator()
    
    def set_indicator_error(self):
        """Set activity indicator to error state (red)."""
        if self.indicator_color != "red":
            self.indicator_color = "red"
            self.activity_state = False
            self.toggle_activity_indicator()
    
    def toggle_activity_indicator(self):
        """Toggle the activity indicator on/off for blinking effect."""
        self.activity_state = not self.activity_state
        
        # Choose color based on indicator state
        if self.indicator_color == "green":
            if self.activity_state:
                color = (0, 255, 0)  # Bright green - data received
            else:
                color = (0, 50, 0)   # Dim green - waiting
        elif self.indicator_color == "yellow":
            if self.activity_state:
                color = (255, 200, 0)  # Bright yellow/orange - warning
            else:
                color = (50, 40, 0)    # Dim yellow - warning
        else:  # red
            if self.activity_state:
                color = (255, 0, 0)    # Bright red - error
            else:
                color = (50, 0, 0)     # Dim red - error
        
        # Draw 3x3 pixel block in bottom-right corner
        self.graphics.set_pen(self.graphics.create_pen(*color))
        self.graphics.rectangle(61, 61, 3, 3)
        
        self.i75.update()
    
    def show_connecting(self):
        """Display 'CONN' message while connecting."""
        self.graphics.set_pen(self.graphics.create_pen(*COLOR_BLACK))
        self.graphics.clear()
        
        # Show "CONN" in center
        self.graphics.set_pen(self.graphics.create_pen(255, 255, 0))
        self.graphics.set_thickness(TEXT_THICKNESS_SMALL)
        msg = "CONNECT"
        w = self.graphics.measure_text(msg, TEXT_SCALE_SMALL)
        x = (self.width - w) // 2
        y = (self.height // 2) - 4
        self.graphics.text(msg, x, y, scale=TEXT_SCALE_SMALL)
        
        self.i75.update()
    
    def show_error(self, error_msg="ERROR"):
        """Display error message.
        
        Args:
            error_msg: Error message to display (default: "ERROR")
        """
        self.graphics.set_pen(self.graphics.create_pen(*COLOR_BLACK))
        self.graphics.clear()
        
        # Show error in center with red color
        self.graphics.set_pen(self.graphics.create_pen(*COLOR_ERROR))
        self.graphics.set_thickness(TEXT_THICKNESS_SMALL)
        w = self.graphics.measure_text(error_msg[:12], TEXT_SCALE_SMALL)
        x = (self.width - w) // 2
        y = (self.height // 2) - 4
        self.graphics.text(error_msg[:12], x, y, scale=TEXT_SCALE_SMALL)
        
        self.i75.update()
    
    def update_display(self, mode, heading, target):
        """Update LED matrix with current autopilot state.
        
        Only updates display when values change to minimize refresh overhead.
        
        Args:
            mode: Autopilot mode ("auto", "standby", etc.")
            heading: Current heading in degrees (0-359)
            target: Target heading in degrees (0-359) or None
        """
        # Round values to minimize spurious updates
        if heading is not None:
            heading = round(heading)
        if target is not None:
            target = round(target)
        
        # Calculate heading difference if in auto mode
        diff = None
        if mode == "auto" and heading is not None and target is not None:
            diff = target - heading
            # Normalize to -180 to +180
            if diff > 180:
                diff -= 360
            elif diff < -180:
                diff += 360
            diff = round(diff)
        
        # Check if display needs updating
        if (mode == self.last_mode and 
            heading == self.last_heading and 
            target == self.last_target and
            diff == self.last_diff):
            return  # No change, skip update
        
        # Store current values
        self.last_mode = mode
        self.last_heading = heading
        self.last_target = target
        self.last_diff = diff
        
        # Clear display
        self.graphics.set_pen(self.graphics.create_pen(*COLOR_BLACK))
        self.graphics.clear()
        
        # ============================================================
        # TOP SECTION: Current Heading (always line 1)
        # ============================================================
        self.graphics.set_thickness(TEXT_THICKNESS)
        
        if mode is None or heading is None:
            # Show waiting state
            self.graphics.set_pen(self.graphics.create_pen(100, 100, 100))
            self.graphics.text("WAIT", 4, 10, scale=TEXT_SCALE_SMALL)
            self.i75.update()
            return
        
        mode_lower = str(mode).lower()
        
        # Line 1 always shows "C" + current heading (both modes)
        heading_str = "{:03d}".format(int(heading) % 360)
        line = "C{}".format(heading_str)
        
        # Draw with compass color
        self.graphics.set_pen(self.graphics.create_pen(*COLOR_COMPASS))
        self.graphics.text(line, 4, 10, scale=TEXT_SCALE)
        
        # ============================================================
        # MIDDLE SECTION: Locked Heading (auto mode only)
        # ============================================================
        if mode_lower == "auto" and target is not None:
            # Build display line: "A270" (locked autopilot heading)
            target_str = "{:03d}".format(int(target) % 360)
            line = "A{}".format(target_str)
            
            # Draw in auto color (showing locked heading)
            self.graphics.set_pen(self.graphics.create_pen(*COLOR_AUTO))
            self.graphics.text(line, 4, 31, scale=TEXT_SCALE)
        
        # ============================================================
        # BOTTOM SECTION: Heading Difference (auto mode only)
        # ============================================================
        if mode_lower == "auto" and diff is not None:
            # Build display line: "+015" or "-020"
            sign = "+" if diff >= 0 else "-"
            diff_str = "{:03d}".format(abs(int(diff)))
            line = "{}{}".format(sign, diff_str)
            
            # Draw in diff color
            self.graphics.set_pen(self.graphics.create_pen(*COLOR_DIFF))
            self.graphics.text(line, 4, 52, scale=TEXT_SCALE)
        
        # ============================================================
        # ACTIVITY INDICATOR: Redraw after clearing display
        # ============================================================
        # FIX: Redraw the activity indicator since we cleared the entire display
        # This prevents the indicator from glitching when the display updates
        if self.indicator_color == "green":
            if self.activity_state:
                color = (0, 255, 0)  # Bright green
            else:
                color = (0, 50, 0)   # Dim green
        elif self.indicator_color == "yellow":
            if self.activity_state:
                color = (255, 200, 0)  # Bright yellow
            else:
                color = (50, 40, 0)    # Dim yellow
        else:  # red
            if self.activity_state:
                color = (255, 0, 0)    # Bright red
            else:
                color = (50, 0, 0)     # Dim red
        
        self.graphics.set_pen(self.graphics.create_pen(*color))
        self.graphics.rectangle(61, 61, 3, 3)
        
        # Update the physical display
        self.i75.update()


# ============================================================================
# WIFI CONNECTION
# ============================================================================

def is_wifi_connected():
    """Check if WiFi is connected and has an IP address.
    
    Returns:
        bool: True if connected with valid IP, False otherwise
    """
    wlan = network.WLAN(network.STA_IF)
    return wlan.isconnected() and wlan.ifconfig()[0] != "0.0.0.0"


def connect_wifi(max_retries=5, retry_delay=2):
    """Connect to WiFi network with retries.
    
    Supports both DHCP and static IP configuration based on USE_STATIC_IP setting.
    
    Args:
        max_retries: Maximum connection attempts
        retry_delay: Seconds to wait between retries
    
    Returns:
        str: Assigned IP address
    
    Raises:
        Exception: If connection fails after all retries
    """
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    # If already connected, return IP
    if is_wifi_connected():
        ip = wlan.ifconfig()[0]
        print("WiFi: Already connected - IP:", ip)
        return ip
    
    # Configure static IP if enabled
    if USE_STATIC_IP:
        print("WiFi: Configuring static IP: {}".format(STATIC_IP))
        wlan.ifconfig((STATIC_IP, STATIC_SUBNET, STATIC_GATEWAY, STATIC_DNS))
    else:
        print("WiFi: Using DHCP for IP configuration")
    
    print("WiFi: Connecting to '{}'...".format(SSID))
    wlan.connect(SSID, PASSWORD)
    
    # Wait for connection with retries
    for attempt in range(max_retries):
        timeout = 10  # seconds per attempt
        start = time.time()
        
        while time.time() - start < timeout:
            if is_wifi_connected():
                ip = wlan.ifconfig()[0]
                subnet = wlan.ifconfig()[1]
                gateway = wlan.ifconfig()[2]
                dns = wlan.ifconfig()[3]
                print("WiFi: Connected successfully!")
                print("  IP:      {}".format(ip))
                print("  Subnet:  {}".format(subnet))
                print("  Gateway: {}".format(gateway))
                print("  DNS:     {}".format(dns))
                return ip
            time.sleep(0.5)
        
        print("WiFi: Attempt {} failed".format(attempt + 1))
        if attempt < max_retries - 1:
            time.sleep(retry_delay)
    
    raise Exception("Failed to connect after {} attempts".format(max_retries))


# ============================================================================
# DATA PROCESSING
# ============================================================================

def process_signalk_update(data, state_cache, deg_cache, last_raw_values):
    """Process Signal K delta update and update caches.
    
    Signal K Delta Format:
    {
        "updates": [
            {
                "values": [
                    {"path": "navigation.headingMagnetic", "value": 1.234},
                    {"path": "steering.autopilot.state", "value": "auto"}
                ]
            }
        ]
    }
    
    Args:
        data: Parsed JSON delta message
        state_cache: Dict for caching state values
        deg_cache: Dict for caching degree values
        last_raw_values: Dict tracking last raw values for change detection
    
    Returns:
        bool: True if any value changed, False otherwise
    """
    changed = False
    
    if "updates" not in data:
        return changed
    
    for update in data["updates"]:
        if "values" not in update:
            continue
        
        for item in update["values"]:
            path = item.get("path")
            value = item.get("value")
            
            if path is None or value is None:
                continue
            
            # Check if this is a path we care about
            if path not in last_raw_values:
                continue
            
            # Check if value actually changed (performance optimization)
            if last_raw_values[path] == value:
                continue
            
            last_raw_values[path] = value
            changed = True
            
            # Process heading values (radians → degrees with smoothing)
            if "heading" in path.lower():
                deg_value = value * RAD_TO_DEG
                
                # Apply EMA smoothing for navigation heading only
                if path == "navigation.headingMagnetic" and deg_cache[path] is not None:
                    old_value = deg_cache[path]
                    deg_value = old_value + HEADING_SMOOTHING * (deg_value - old_value)
                
                deg_cache[path] = deg_value
            
            # Process state values
            elif path == "steering.autopilot.state":
                state_cache[path] = value
    
    return changed


def format_status_line(state_cache, deg_cache):
    """Format current status as console output string.
    
    Args:
        state_cache: Dict with state values
        deg_cache: Dict with degree values
    
    Returns:
        str: Formatted status line or None if data missing
    """
    mode = state_cache.get("steering.autopilot.state")
    heading = deg_cache.get("navigation.headingMagnetic")
    target = deg_cache.get("steering.autopilot.target.headingMagnetic")
    
    if mode is None or heading is None:
        return None
    
    # Format heading
    heading_str = "{:03d}°".format(int(heading) % 360)
    
    if mode == "auto" and target is not None:
        # Auto mode: show target and difference
        target_str = "{:03d}°".format(int(target) % 360)
        diff = target - heading
        # Normalize to -180 to +180
        if diff > 180:
            diff -= 360
        elif diff < -180:
            diff += 360
        diff_str = "{:+04d}°".format(int(diff))
        return "Mode: AUTO | HDG: {} | TGT: {} | DIFF: {}".format(
            heading_str, target_str, diff_str
        )
    else:
        # Stby/Compass mode: just show heading
        return "Mode: STBY/COMPASS | HDG: {}".format(heading_str)


# ============================================================================
# BACKGROUND TASKS
# ============================================================================

async def activity_indicator_task(display):
    """Background task that blinks the activity indicator at regular intervals.
    
    This runs independently of the main loop to ensure consistent blinking
    regardless of websocket message timing.
    
    Args:
        display: DisplayManager instance
    """
    print("Activity indicator task: Starting")
    
    while True:
        try:
            display.toggle_activity_indicator()
            await asyncio.sleep(INDICATOR_BLINK_INTERVAL)
        except Exception as e:
            print("Activity indicator error:", e)
            await asyncio.sleep(INDICATOR_BLINK_INTERVAL)


# ============================================================================
# MAIN ASYNC EVENT LOOP
# ============================================================================

async def main():
    """Main async event loop.
    
    Responsibilities:
    -----------------
    • Manage WiFi connection
    • Maintain WebSocket connection to Signal K server
    • Process incoming Signal K delta messages
    • Update LED matrix display on data changes
    • Monitor connection health and show status indicators
    • Periodic garbage collection and health checks
    
    Performance Optimizations:
    --------------------------
    • Immediate display updates on data changes (responsive)
    • Change detection to avoid redundant processing
    • EMA smoothing for heading values (configurable)
    • Minimal console output (configurable interval)
    • Strategic garbage collection
    """
    print("\n" + "="*50)
    print("SIGNAL K DISPLAY - Interstate 75 W")
    print("="*50)
    
    # Run startup splash screen
    run_startup_sequence()
    
    
    # Initialize hardware
    display = DisplayManager()
    
    # Show connecting message
    display.show_connecting()
    
    # Initialize WebSocket response time tracker
    ws_tracker = WSResponseTimeTracker(DEBUG_WS)
    
    # Start background task for activity indicator blinking
    asyncio.create_task(activity_indicator_task(display))
    
    # Connect to WiFi
    try:
        ip = connect_wifi()
    except Exception as e:
        print("FATAL: WiFi connection failed:", e)
        display.show_error("WiFi Fail")
        return
    
    # Build WebSocket URL
    ws_url = "ws://{}:{}/signalk/{}/stream?subscribe={}".format(
        HOST, PORT, VERSION, SUBSCRIBE
    )
    
    print("\nSignal K WebSocket URL:")
    print(ws_url)
    print()
    
    # State caches (minimize redundant processing)
    state_cache = {
        "steering.autopilot.state": None,
    }
    deg_cache = {
        "navigation.headingMagnetic": None,
        "steering.autopilot.target.headingMagnetic": None,
    }
    
    # Track last raw values to detect changes (performance optimization)
    last_raw_values = {
        "navigation.headingMagnetic": None,
        "steering.autopilot.state": None,
        "steering.autopilot.target.headingMagnetic": None,
    }
    
    # Connection state
    websocket = None
    
    # Timing trackers
    last_print_ms = 0
    last_wifi_check_ms = 0
    last_gc_ms = 0
    last_data_ms = 0  # Track when we last received data
    
    print("\n" + "="*50)
    print("Entering main loop...")
    print("="*50 + "\n")
    
    # Main event loop
    while True:
        # Cache current time for all checks in this iteration
        now_ms = time.ticks_ms()
        
        # Periodic garbage collection
        if time.ticks_diff(now_ms, last_gc_ms) >= GC_INTERVAL * 1000:
            gc.collect()
            last_gc_ms = now_ms
        
        # Periodic WiFi health check
        if time.ticks_diff(now_ms, last_wifi_check_ms) >= WIFI_CHECK_INTERVAL * 1000:
            if not is_wifi_connected():
                print("WiFi: Connection lost - reconnecting...")
                
                if websocket:
                    try:
                        await websocket.close()
                    except Exception:
                        pass
                    websocket = None
                
                try:
                    ip = connect_wifi()
                except Exception as e:
                    print("WiFi: Reconnect failed:", e)
                    display.show_error("WiFi Fail")
                    await asyncio.sleep(RECONNECT_WAIT)
                    continue
            
            last_wifi_check_ms = now_ms
        
        # Ensure WebSocket is connected
        if websocket is None:
            try:
                display.show_connecting()
                websocket = AsyncWebsocketClient()
                
                # Add timeout to prevent hanging when server is down
                await asyncio.wait_for(websocket.handshake(ws_url), timeout=5.0)
                
                print("WS: Connected")
                last_print_ms = now_ms
                last_data_ms = now_ms  # Reset data timestamp on new connection
                display.set_indicator_ok()  # Reset to green on reconnection
                
                # Clear display state to force update on next data
                display.last_mode = None
                display.last_heading = None
                display.last_target = None
                
                # Immediately clear the "CONNECT" message by showing current state
                # Even if we don't have data yet, this clears the CONNECT screen
                mode = state_cache["steering.autopilot.state"]
                heading = deg_cache["navigation.headingMagnetic"]
                target = deg_cache["steering.autopilot.target.headingMagnetic"]
                display.update_display(mode, heading, target)
                
                gc.collect()
                
            except asyncio.TimeoutError:
                print("WS: Connection timeout")
                websocket = None
                display.set_indicator_error()
                display.show_error("WS TIMEOUT")
                await asyncio.sleep(RECONNECT_WAIT)
                continue
            
            except Exception as e:
                print("WS: Connection failed:", e)
                websocket = None
                display.set_indicator_error()
                display.show_error("WS Fail")
                await asyncio.sleep(RECONNECT_WAIT)
                continue
        
        # Receive and process WebSocket frame
        try:
            # Track websocket response time if debugging enabled
            if DEBUG_WS:
                ws_start = time.ticks_ms()
            
            # Add timeout to recv to prevent indefinite blocking
            # This allows the loop to check for stale data and reconnect if needed
            connection_closed = False
            try:
                message_text = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                # Check if connection was actually closed by server
                if message_text is None:
                    connection_closed = True
            except asyncio.TimeoutError:
                # No message received within timeout - not an error, just continue
                # This allows us to check data staleness and other conditions
                message_text = None
            
            # Record response time if debugging enabled (only if message received)
            if DEBUG_WS and message_text:
                ws_time = time.ticks_diff(time.ticks_ms(), ws_start)
                ws_tracker.record(ws_time)
            
            # Check if connection was closed by server (not just timeout)
            if connection_closed:
                print("WS: Connection closed by server")
                websocket = None
                display.set_indicator_error()
                display.show_error("WS CLOSE")
                await asyncio.sleep(RECONNECT_WAIT)
                continue
            
            if message_text:
                # Update last data timestamp
                last_data_ms = now_ms
                
                # Set indicator to healthy (green) if it was in error state
                display.set_indicator_ok()
                
                # Parse JSON
                try:
                    data = json.loads(message_text)
                except Exception as e:
                    print("JSON parse error:", e)
                    data = None
                
                # Process Signal K delta
                changed = False
                if data:
                    changed = process_signalk_update(data, state_cache, deg_cache, last_raw_values)
                
                # In auto mode, always update display on ANY change to be more responsive
                # Don't wait for PRINT_INTERVAL when data changes
                if changed:
                    # Update LED matrix display immediately on change
                    try:
                        if DEBUG_TIMING:
                            update_start = time.ticks_ms()
                        
                        mode = state_cache["steering.autopilot.state"]
                        heading = deg_cache["navigation.headingMagnetic"]
                        target = deg_cache["steering.autopilot.target.headingMagnetic"]
                        
                        display.update_display(mode, heading, target)
                        
                        if DEBUG_TIMING:
                            update_time = time.ticks_diff(time.ticks_ms(), update_start)
                            print("Display update took {}ms".format(update_time))
                    except Exception as e:
                        print("Display update error:", e)
                
                # Update console print on change or periodic interval
                time_for_update = time.ticks_diff(now_ms, last_print_ms) >= PRINT_INTERVAL * 1000
                
                if changed or time_for_update:
                    # Print to console
                    status = format_status_line(state_cache, deg_cache)
                    if status:
                        print(status)
                        last_print_ms = now_ms
            
            # Check and report WebSocket statistics if debugging enabled
            if DEBUG_WS:
                ws_tracker.check_and_report(now_ms)
            
            # Check for stale/dead data (only if we've received data before)
            if last_data_ms > 0:
                time_since_data = time.ticks_diff(now_ms, last_data_ms) / 1000.0
                
                if time_since_data > DATA_DEAD_TIMEOUT:
                    # No data for a long time - connection likely dead
                    display.set_indicator_error()
                elif time_since_data > DATA_STALE_TIMEOUT:
                    # No data for a while - show warning
                    display.set_indicator_warning()
        
        except OSError as e:
            print("WS: Error:", e)
            try:
                await websocket.close()
            except Exception:
                pass
            websocket = None
            display.set_indicator_error()  # Show connection error
            display.show_error("WS ERR")
            gc.collect()
            await asyncio.sleep(RECONNECT_WAIT)
        
        except Exception as e:
            print("ERROR:", e)
            try:
                await websocket.close()
            except Exception:
                pass
            websocket = None
            display.set_indicator_error()  # Show connection error
            display.show_error("ERR")
            gc.collect()
            await asyncio.sleep(RECONNECT_WAIT)







def run_startup_sequence():
    """
    Run the complete startup sequence: red, green, blue spirals,
    black pause, then multicolor starburst turning white.
    
    This function initializes its own display instance and cleans up after itself.
    """
    print("Splash: Starting splash screen sequence...")
    
    # Initialize the display
    i75 = Interstate75(display=DISPLAY_INTERSTATE75_64X64, color_order=Interstate75.COLOR_ORDER_BGR)
    display = i75.display
    
    WIDTH = i75.width
    HEIGHT = i75.height
    CENTER_X = WIDTH // 2
    CENTER_Y = HEIGHT // 2
    
    # Define colors
    BLACK = display.create_pen(0, 0, 0)
    RED = display.create_pen(255, 0, 0)
    GREEN = display.create_pen(0, 255, 0)
    BLUE = display.create_pen(0, 0, 255)
    WHITE = display.create_pen(255, 255, 255)
    
    def draw_spiral(color, duration):
        """Draw a classic mathematical spiral using the simpler equation"""
        display.set_pen(BLACK)
        display.clear()
        
        start_time = time.ticks_ms()
        n = 0
        c = 2
        
        while time.ticks_diff(time.ticks_ms(), start_time) < duration * 1000:
            # Classic spiral equation - simple and elegant
            a = n * 40
            r = c * math.sqrt(n)
            
            x = int(r * math.cos(a) + CENTER_X)
            y = int(r * math.sin(a) + CENTER_Y)
            
            if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                display.set_pen(color)
                display.circle(x, y, 1)
            
            i75.update()
            n += 1
            
            # Small delay to control speed
            time.sleep(0.003)
    
    def draw_starburst(duration):
        """Draw an atmospheric energy wave with muted colors and flowing movement"""
        display.set_pen(BLACK)
        display.clear()
        
        start_time = time.ticks_ms()
        
        # Phase 1: Flowing energy wave (first 0.8 seconds) - longer and denser
        phase1_duration = int(duration * 800)
        
        while time.ticks_diff(time.ticks_ms(), start_time) < phase1_duration:
            elapsed = time.ticks_diff(time.ticks_ms(), start_time)
            progress = elapsed / phase1_duration
            
            # Clear for animation
            display.set_pen(BLACK)
            display.clear()
            
            # Create flowing energy field with density variation - MORE PARTICLES
            # Multiple layers at different densities for depth
            for layer in range(3):
                layer_offset = layer * 0.33
                layer_speed = 0.5 + layer * 0.25
                num_particles = 60 + layer * 25  # Increased from 35+15
                
                for i in range(num_particles):
                    # More organic angle distribution
                    base_angle = (2 * math.pi * i / num_particles)
                    angle_noise = math.sin(i * 1.3 + progress * 2) * 0.6 + math.cos(i * 0.7) * 0.3
                    angle = base_angle + angle_noise
                    
                    # Slow, varied expansion with wave-like motion
                    speed_variation = 0.5 + 0.7 * (math.sin(i * 1.9) * 0.5 + 0.5)
                    distance = (progress ** 0.8) * 40 * layer_speed * speed_variation
                    
                    # Add flowing turbulence - slower, more fluid
                    wave_phase = progress * 2 + i * 0.3
                    turbulence_x = math.sin(wave_phase * 1.3) * 4 + math.cos(i * 0.9) * 2
                    turbulence_y = math.cos(wave_phase * 1.1) * 4 + math.sin(i * 1.2) * 2
                    
                    px = int(CENTER_X + distance * math.cos(angle) + turbulence_x)
                    py = int(CENTER_Y + distance * math.sin(angle) + turbulence_y)
                    
                    if 0 <= px < WIDTH and 0 <= py < HEIGHT:
                        # Muted, desaturated color palette - more atmospheric
                        color_shift = (i / num_particles + layer_offset + progress * 0.2) % 1.0
                        
                        # Fade based on distance and layer
                        distance_fade = max(0.2, 1.0 - (distance / 45))
                        layer_fade = 0.6 + layer * 0.2
                        fade = distance_fade * layer_fade * (0.7 + 0.3 * math.sin(progress * math.pi))
                        
                        if color_shift < 0.33:
                            # Muted amber/gold tones
                            r = int(160 * fade)
                            g = int((100 + 50 * color_shift * 3) * fade)
                            b = int(40 * fade)
                        elif color_shift < 0.66:
                            # Soft rose/lavender tones
                            r = int((160 - 60 * (color_shift - 0.33) * 3) * fade)
                            g = int((150 - 70 * (color_shift - 0.33) * 3) * fade)
                            b = int((40 + 140 * (color_shift - 0.33) * 3) * fade)
                        else:
                            # Cool slate/periwinkle tones
                            r = int((100 + 60 * (color_shift - 0.66) * 3) * fade)
                            g = int((80 + 70 * (color_shift - 0.66) * 3) * fade)
                            b = int((180 - 40 * (color_shift - 0.66) * 3) * fade)
                        
                        particle_color = display.create_pen(r, g, b)
                        display.set_pen(particle_color)
                        
                        # Soft particles - mostly single pixels with occasional soft glow
                        display.pixel(px, py)
                        
                        # Add soft glow to MORE particles for density
                        if i % 6 == 0 and distance > 12:  # Changed from i % 8
                            glow_r, glow_g, glow_b = int(r * 0.5), int(g * 0.5), int(b * 0.5)
                            glow_color = display.create_pen(glow_r, glow_g, glow_b)
                            display.set_pen(glow_color)
                            if px + 1 < WIDTH:
                                display.pixel(px + 1, py)
                            if py + 1 < HEIGHT:
                                display.pixel(px, py + 1)
                        
                        # More energy trails for density
                        if i % 9 == 0 and distance > 15:  # Changed from i % 12
                            trail_dist = distance * 0.6
                            tx = int(CENTER_X + trail_dist * math.cos(angle) + turbulence_x * 0.6)
                            ty = int(CENTER_Y + trail_dist * math.sin(angle) + turbulence_y * 0.6)
                            if 0 <= tx < WIDTH and 0 <= ty < HEIGHT:
                                trail_color = display.create_pen(int(r * 0.3), int(g * 0.3), int(b * 0.3))
                                display.set_pen(trail_color)
                                display.pixel(tx, ty)
            
            # Soft, pulsing core - very subtle
            core_pulse = 0.6 + 0.4 * math.sin(progress * math.pi * 3)
            for radius in range(1, 6):
                core_fade = (6 - radius) / 5.0 * core_pulse * (1 - progress * 0.3)
                core_r = int(140 * core_fade)
                core_g = int(120 * core_fade)
                core_b = int(80 * core_fade)
                core_color = display.create_pen(core_r, core_g, core_b)
                display.set_pen(core_color)
                
                # Draw subtle core outline
                for angle in range(0, 360, 45):
                    rad = angle * math.pi / 180
                    cx = int(CENTER_X + radius * math.cos(rad))
                    cy = int(CENTER_Y + radius * math.sin(rad))
                    if 0 <= cx < WIDTH and 0 <= cy < HEIGHT:
                        display.pixel(cx, cy)
            
            i75.update()
            time.sleep(0.02)  # Slower frame rate for smoother feel
        
        # Phase 2: Gentle white bloom (last 0.4 seconds) - longer
        phase2_duration = int(duration * 400)
        phase2_start = time.ticks_ms()
        
        while time.ticks_diff(time.ticks_ms(), phase2_start) < phase2_duration:
            elapsed = time.ticks_diff(time.ticks_ms(), phase2_start)
            progress = elapsed / phase2_duration
            
            display.set_pen(BLACK)
            display.clear()
            
            # Soft expanding light field - denser rings
            for ring in range(7):  # Increased from 5 rings
                ring_radius = int((6 + ring * 7) * (progress ** 0.7))
                ring_fade = (7 - ring) / 7.0 * (0.5 + 0.5 * progress)
                
                brightness = int(200 * ring_fade)
                ring_color = display.create_pen(brightness, brightness, brightness)
                display.set_pen(ring_color)
                
                # Draw soft ring with irregular points - more density
                for angle_deg in range(0, 360, 10):  # Changed from 12 to 10 degrees
                    angle = angle_deg * math.pi / 180
                    radius_var = ring_radius + int(3 * math.sin(angle * 3 + progress * 5))
                    
                    rx = int(CENTER_X + radius_var * math.cos(angle))
                    ry = int(CENTER_Y + radius_var * math.sin(angle))
                    
                    if 0 <= rx < WIDTH and 0 <= ry < HEIGHT:
                        display.pixel(rx, ry)
                        # Add soft glow around points
                        if rx + 1 < WIDTH:
                            display.pixel(rx + 1, ry)
                        if ry + 1 < HEIGHT:
                            display.pixel(rx, ry + 1)
            
            # Soft center bloom
            bloom_size = int(4 + progress * 12)
            for radius in range(1, bloom_size, 2):
                bloom_fade = 1.0 - (radius / bloom_size) * 0.5
                bloom_brightness = int(255 * bloom_fade * progress)
                bloom_color = display.create_pen(bloom_brightness, bloom_brightness, bloom_brightness)
                display.set_pen(bloom_color)
                
                for angle in range(0, 360, 30):
                    rad = angle * math.pi / 180
                    bx = int(CENTER_X + radius * math.cos(rad))
                    by = int(CENTER_Y + radius * math.sin(rad))
                    if 0 <= bx < WIDTH and 0 <= by < HEIGHT:
                        display.pixel(bx, by)
            
            i75.update()
            time.sleep(0.015)
        
        # Final soft white glow
        display.set_pen(WHITE)
        display.clear()
        i75.update()
        time.sleep(0.15)
    
    try:
        # Run the complete sequence
        # 1. Red spiral - 1 second
        draw_spiral(RED, 1)
        
        # 2. Green spiral - 1 second
        draw_spiral(GREEN, 1)
        
        # 3. Blue spiral - 1 second
        draw_spiral(BLUE, 1)
        
        # 4. Black screen - 1 second
        display.set_pen(BLACK)
        display.clear()
        i75.update()
        time.sleep(1)
        
        # 5. Multicolor starburst turning white - 1 second
        draw_starburst(1)
        
        # 6. Final black before main program
        display.set_pen(BLACK)
        display.clear()
        i75.update()
        
        print("Splash: Splash screen complete!")
        
    finally:
        # Clean up display resources
        print("Splash: Cleaning up display resources...")
        del display
        del i75
        gc.collect()
        time.sleep(0.2)  # Give hardware time to reset
        print("Splash: Display cleanup complete")
    

# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        print("Cleaning up...")
        gc.collect()
    except Exception as e:
        print("\n\nFATAL ERROR:", e)
        import sys
        sys.print_exception(e)