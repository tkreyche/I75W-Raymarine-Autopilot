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
# • Top Section (0-21): Always visible
#   - "C" indicates Compass Heading, Signal K calls it navigation.headingMagnetic
#   - Three-digit heading: "045"
# • Middle Section (22-42): Target heading (auto mode only)
#   - "A" for Auto Mode + Three-digit target heading: "270", Signal K call it steering.autopilot.target.headingMagnetic
#   - Only displayed when autopilot is in auto mode 
# • Bottom Section (43-63): Heading difference (auto mode only)
#   - Sign and three-digit value: "+015" or "-020"
#   - Positive = turn right to reach target, Negative = turn left
#   - Only displayed when autopilot is in auto mode
# • Center Keep-Alive (1x3 pixels at x=32, rows 61-63): Blinks bright white every second to show program is running
# • Status Bar (rows 61-63): Two independent indicators
#   - Lower RIGHT (10x3, cols 54-63): Connection health indicator
#     * Green (solid): Heartbeat data flowing normally (environment.heartbeat updating)
#     * Red (blinking): No heartbeat data for 60+ seconds
#   - Lower LEFT (10x3, cols 0-9): Heading stale indicator
#     * Green (solid): Compass heading updating normally (navigation.headingMagnetic changing)
#     * Yellow/Orange (blinking): Compass heading unchanged for 60+ seconds
#     * Shows independently of connection status (can be orange while right is red)

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
import micropython

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

RUN_SPLASH = secrets.RUN_SPLASH

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
    "steering.autopilot.target.headingMagnetic,"
    "environment.heartbeat"
)

TOKEN = ""

# ============================================================================
# TIMING PARAMETERS
# ============================================================================

RECONNECT_WAIT = 3
PRINT_INTERVAL = 1  # Increase to 10+ to reduce console output for better performance
WIFI_CHECK_INTERVAL = 10
GC_INTERVAL = 30
# NEW: Separate timeouts for the two independent indicators
HEARTBEAT_TIMEOUT = 30   # Seconds without heartbeat before connection health indicator goes red
HEADING_STALE_TIMEOUT = 30  # Seconds without heading change before heading indicator goes orange
INDICATOR_BLINK_INTERVAL = 1.0  # Seconds between indicator blinks (configurable)

# Performance tuning
DEBUG_TIMING = secrets.DEBUG_TIMING # Set to True to print timing diagnostics for display updates
DEBUG_WS = secrets.DEBUG_WS     # Set to True to track and print WebSocket response time statistics

# Error logging to file
LOG_ERRORS_TO_FILE = getattr(secrets, 'LOG_ERRORS_TO_FILE', False)  # Set to True to log errors to file
LOG_FILE_PATH = getattr(secrets, 'LOG_FILE_PATH', '/error_log.txt')  # Path to error log file
LOG_FILE_MAX_SIZE = getattr(secrets, 'LOG_FILE_MAX_SIZE', 50000)  # Max log file size in bytes before rotation
# NOTE: When LOG_ERRORS_TO_FILE is enabled, all errors will be logged to LOG_FILE_PATH with:
#   - Timestamp
#   - Error type and message
#   - Current state (mode, heading, target, connection status)
#   - Memory usage
# Log rotation: When file exceeds LOG_FILE_MAX_SIZE, keeps most recent 20% of entries

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

# Pre-defined color variations for indicators
COLOR_GREEN_BRIGHT = (0, 255, 0)
COLOR_RED_BRIGHT = (255, 0, 0)
COLOR_RED_DIM = (0, 0, 0)
COLOR_ORANGE_BRIGHT = (255, 100, 0)
COLOR_ORANGE_DIM = (0, 0, 0)
COLOR_GRAY = (100, 100, 100)
COLOR_YELLOW = (255, 255, 0)
COLOR_WHITE = (255, 255, 255)
COLOR_KEEPALIVE_BRIGHT = (200, 200, 200)
COLOR_KEEPALIVE_DIM = (0, 0, 0)

# Text scaling (bitmap sans font with thickness)
TEXT_SCALE = 0.7     # Scale for all text
TEXT_SCALE_SMALL = 0.4     # Small scale
TEXT_THICKNESS = 2   # Thickness for better visibility on LED matrix
TEXT_THICKNESS_SMALL = 1 

# ============================================================================
# Helper to ensure we only treat exact 'environment.heartbeat' as a heartbeat
def _is_heartbeat_path(p):
    return p == "environment.heartbeat"
# ============================================================================

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def normalize_heading_difference(target, heading):
    """Calculate and normalize heading difference to -180 to +180 range.
    
    Args:
        target: Target heading in degrees
        heading: Current heading in degrees
    
    Returns:
        int: Normalized difference (-180 to +180)
    """
    diff = target - heading
    # Normalize to -180 to +180
    if diff > 180:
        diff -= 360
    elif diff < -180:
        diff += 360
    return round(diff)


async def wait_for_reconnect_with_indicators(display, seconds):
    """Wait for reconnection while keeping indicators blinking.
    
    Args:
        display: DisplayManager instance
        seconds: Number of seconds to wait
    """
    for i in range(seconds * 10):  # Check every 100ms
        if display.needs_refresh:
            display.toggle_activity_indicator()
            display.i75.update()
            display.needs_refresh = False
        await asyncio.sleep(0.1)


def log_error_to_file(error_type, error_exception, details=None):
    """Log error information to file with timestamp, stack trace, and rotation.
    
    Args:
        error_type: Type of error (e.g., "GENERIC", "OSERROR", "DISPLAY")
        error_exception: The actual exception object (not string)
        details: Optional dictionary with additional context
    """
    if not LOG_ERRORS_TO_FILE:
        return
    
    try:
        import os
        import sys
        import io
        
        # Check if log file exists and its size
        try:
            file_size = os.stat(LOG_FILE_PATH)[6]  # [6] is file size
            
            # If log file is too large, rotate it
            if file_size > LOG_FILE_MAX_SIZE:
                # Try to keep last 20% of log (most recent entries)
                try:
                    with open(LOG_FILE_PATH, 'r') as f:
                        lines = f.readlines()
                    
                    # Keep last 20% of lines
                    keep_lines = int(len(lines) * 0.2)
                    if keep_lines < 10:
                        keep_lines = min(10, len(lines))
                    
                    with open(LOG_FILE_PATH, 'w') as f:
                        f.write("=== LOG ROTATED ===\n")
                        f.writelines(lines[-keep_lines:])
                except Exception:
                    # If rotation fails, just truncate
                    with open(LOG_FILE_PATH, 'w') as f:
                        f.write("=== LOG TRUNCATED (rotation failed) ===\n")
        except OSError:
            # File doesn't exist yet, that's fine
            pass
        
        # Format timestamp
        import time
        rtc_time = time.localtime()
        timestamp = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
            rtc_time[0], rtc_time[1], rtc_time[2],
            rtc_time[3], rtc_time[4], rtc_time[5]
        )
        
        # Capture exception type and message
        exc_type = type(error_exception).__name__
        exc_msg = str(error_exception)
        if not exc_msg:
            exc_msg = "(no error message)"
        
        # Capture stack trace to string
        trace_buffer = io.StringIO()
        sys.print_exception(error_exception, trace_buffer)
        stack_trace = trace_buffer.getvalue()
        
        # Write error to log file
        with open(LOG_FILE_PATH, 'a') as f:
            f.write("\n" + "="*50 + "\n")
            f.write("[{}] {} ERROR\n".format(timestamp, error_type))
            f.write("="*50 + "\n")
            f.write("Exception Type: {}\n".format(exc_type))
            f.write("Error Message: {}\n".format(exc_msg))
            
            f.write("\nStack Trace:\n")
            f.write(stack_trace)
            
            if details:
                f.write("\nContext Details:\n")
                for key, value in details.items():
                    f.write("  {}: {}\n".format(key, value))
            
            f.write("\n")
            f.flush()  # Ensure it's written immediately
        
    except Exception as e:
        # Don't let logging errors crash the program
        print("Warning: Failed to write to error log:", e)


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
        """Record a response time measurement.
        
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
    • Center keep-alive (1x3, in bottom rows): Minimal bright white indicator blinking every second
    • Status bar (rows 61-63): Two INDEPENDENT indicators
      - Lower RIGHT (10x3): Connection health (green solid when heartbeat OK, red blinking when heartbeat stale)
      - Lower LEFT (10x3): Heading status (green solid when heading OK, yellow/orange blinking when heading stale)
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
            
            # Pre-create pen objects for commonly used colors
            self.pen_black = self.graphics.create_pen(*COLOR_BLACK)
            self.pen_compass = self.graphics.create_pen(*COLOR_COMPASS)
            self.pen_auto = self.graphics.create_pen(*COLOR_AUTO)
            self.pen_diff = self.graphics.create_pen(*COLOR_DIFF)
            self.pen_error = self.graphics.create_pen(*COLOR_ERROR)
            self.pen_yellow = self.graphics.create_pen(*COLOR_YELLOW)
            self.pen_gray = self.graphics.create_pen(*COLOR_GRAY)
            
            # Indicator pens
            self.pen_green_bright = self.graphics.create_pen(*COLOR_GREEN_BRIGHT)
            self.pen_red_bright = self.graphics.create_pen(*COLOR_RED_BRIGHT)
            self.pen_red_dim = self.graphics.create_pen(*COLOR_RED_DIM)
            self.pen_orange_bright = self.graphics.create_pen(*COLOR_ORANGE_BRIGHT)
            self.pen_orange_dim = self.graphics.create_pen(*COLOR_ORANGE_DIM)
            self.pen_keepalive_bright = self.graphics.create_pen(*COLOR_KEEPALIVE_BRIGHT)
            self.pen_keepalive_dim = self.graphics.create_pen(*COLOR_KEEPALIVE_DIM)
            
            # Pre-calculate static text measurements
            self.graphics.set_thickness(TEXT_THICKNESS_SMALL)
            self.text_width_wait = self.graphics.measure_text("WAIT", TEXT_SCALE_SMALL)
            self.text_width_connect = self.graphics.measure_text("CONNECT", TEXT_SCALE_SMALL)
            
            # Track last displayed values to minimize updates
            self.last_mode = None
            self.last_heading = None
            self.last_target = None
            self.last_diff = None
            
            # INDEPENDENT indicator states
            self.activity_state = False  # For blinking animation
            self.connection_health_ok = True  # Based ONLY on heartbeat
            self.heading_ok = True  # Based ONLY on magnetic heading changes
            self.keepalive_state = False  # Track keep-alive blink state
            self.needs_refresh = False  # Flag to coordinate display updates
            
            # Initial clear
            self.graphics.set_pen(self.pen_black)
            self.graphics.clear()
            self.i75.update()
            
            print("Display: Initialized successfully")
        
        except Exception as e:
            print("Display: Initialization FAILED:", e)
            raise
    
    def set_indicator_state(self, connection_ok=None, heading_ok=None):
        """Set indicator states with change detection.
        
        Args:
            connection_ok: New connection health state (None to keep current)
            heading_ok: New heading state (None to keep current)
        """
        changed = False
        
        if connection_ok is not None and self.connection_health_ok != connection_ok:
            self.connection_health_ok = connection_ok
            self.activity_state = False
            changed = True
            if DEBUG_TIMING:
                print("DEBUG: Connection health set to {}".format("OK (green)" if connection_ok else "ERROR (red)"))
        
        if heading_ok is not None and self.heading_ok != heading_ok:
            self.heading_ok = heading_ok
            self.activity_state = False
            changed = True
            if DEBUG_TIMING:
                print("DEBUG: Heading set to {}".format("OK (green)" if heading_ok else "STALE (orange)"))
            
            # Force redraw when heading state changes
            if not heading_ok:
                self.last_mode = None
        
        if changed:
            self.needs_refresh = True
    
    def set_connection_health_ok(self):
        """Set connection health indicator to healthy state (green) - heartbeat is current."""
        self.set_indicator_state(connection_ok=True)
    
    def set_connection_health_error(self):
        """Set connection health indicator to error state (red) - no heartbeat."""
        self.set_indicator_state(connection_ok=False)
    
    def set_heading_ok(self):
        """Set heading indicator to healthy state (green) - heading is changing."""
        self.set_indicator_state(heading_ok=True)
    
    def set_heading_stale(self):
        """Set heading stale state (orange blinking) - heading not changing."""
        self.set_indicator_state(heading_ok=False)
    
    def draw_keepalive_indicator(self):
        """Draw the keep-alive indicator in the center of the bottom status rows.
        
        A minimal 1x3 pixel indicator that blinks every second to show
        the program is running. This is separate from the health indicators.
        
        Position: x=32 (center), rows 61-63
        """
        if self.keepalive_state:
            self.graphics.set_pen(self.pen_keepalive_bright)
        else:
            self.graphics.set_pen(self.pen_keepalive_dim)
        
        # Draw minimal 1-pixel wide indicator at center
        self.graphics.rectangle(32, 61, 1, 3)
    
    def toggle_activity_indicator(self):
        """Toggle and redraw BOTH independent activity indicators in the status bar.
        
        This updates both the connection health indicator (right) and the 
        heading staleness indicator (left) based on their current states.
        Does NOT call i75.update() - that's handled by the caller.
        """
        # ============================================================
        # LOWER RIGHT: Connection health indicator (heartbeat-based)
        # 10 columns wide (54-63), 3 rows tall (61-63)
        # ============================================================
        if self.connection_health_ok:
            # Green stays solid (no blinking) - heartbeat is current
            self.graphics.set_pen(self.pen_green_bright)
        else:
            # Red blinks to indicate no heartbeat
            if self.activity_state:
                self.graphics.set_pen(self.pen_red_bright)
            else:
                self.graphics.set_pen(self.pen_red_dim)
        
        # Draw 10x3 block in bottom-RIGHT corner
        self.graphics.rectangle(54, 61, 10, 3)
        
        # ============================================================
        # LOWER LEFT: Heading indicator (magnetic heading-based)
        # 10 columns wide (0-9), 3 rows tall (61-63)
        # ============================================================
        if self.heading_ok:
            # Green stays solid (no blinking) - heading is updating normally
            self.graphics.set_pen(self.pen_green_bright)
        else:
            # Yellow/Orange blinks to indicate stale heading
            if self.activity_state:
                self.graphics.set_pen(self.pen_orange_bright)
            else:
                self.graphics.set_pen(self.pen_orange_dim)
        
        self.graphics.rectangle(0, 61, 10, 3)
        
        # Draw keep-alive indicator
        self.draw_keepalive_indicator()
        
        # Note: Display update coordinated in main loop, not called here
    
    def show_connecting(self):
        """Display 'CONN' message while connecting."""
        self.graphics.set_pen(self.pen_black)
        self.graphics.clear()
        
        # Show "CONNECT" in center (use pre-calculated width)
        self.graphics.set_pen(self.pen_yellow)
        self.graphics.set_thickness(TEXT_THICKNESS_SMALL)
        x = (self.width - self.text_width_connect) // 2
        y = (self.height // 2) - 4
        self.graphics.text("CONNECT", x, y, scale=TEXT_SCALE_SMALL)
        
        # Redraw status indicators after clearing display
        self.toggle_activity_indicator()
        
        self.i75.update()
    
    def show_error(self, error_msg="ERROR"):
        """Display error message.
        
        Args:
            error_msg: Error message to display (default: "ERROR")
        """
        self.graphics.set_pen(self.pen_black)
        self.graphics.clear()
        
        # Show error in center with red color
        self.graphics.set_pen(self.pen_error)
        self.graphics.set_thickness(TEXT_THICKNESS_SMALL)
        msg = error_msg[:12]
        w = self.graphics.measure_text(msg, TEXT_SCALE_SMALL)
        x = (self.width - w) // 2
        y = (self.height // 2) - 4
        self.graphics.text(msg, x, y, scale=TEXT_SCALE_SMALL)
        
        # Redraw status indicators after clearing display
        self.toggle_activity_indicator()
        
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
            diff = normalize_heading_difference(target, heading)
        
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
        self.graphics.set_pen(self.pen_black)
        self.graphics.clear()
        
        # ============================================================
        # TOP SECTION: Current Heading (always line 1)
        # ============================================================
        self.graphics.set_thickness(TEXT_THICKNESS)
        
        if mode is None or heading is None:
            # Show waiting state (use pre-calculated width)
            self.graphics.set_pen(self.pen_gray)
            x = (self.width - self.text_width_wait) // 2
            self.graphics.text("WAIT", x, 10, scale=TEXT_SCALE_SMALL)
            self.i75.update()
            return
        
        mode_lower = str(mode).lower()
        
        # Line 1 always shows "C" + current heading (both modes)
        # Cache normalized heading
        heading_normalized = int(heading) % 360
        heading_str = "{:03d}".format(heading_normalized)
        line = "C{}".format(heading_str)
        
        # Draw with compass color
        self.graphics.set_pen(self.pen_compass)
        self.graphics.text(line, 4, 10, scale=TEXT_SCALE)
        
        # ============================================================
        # MIDDLE SECTION: Locked Heading (auto mode only)
        # ============================================================
        if mode_lower == "auto" and target is not None:
            # Build display line: "A270" (locked autopilot heading)
            target_normalized = int(target) % 360
            target_str = "{:03d}".format(target_normalized)
            line = "A{}".format(target_str)
            
            # Draw in auto color (showing locked heading)
            self.graphics.set_pen(self.pen_auto)
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
            self.graphics.set_pen(self.pen_diff)
            self.graphics.text(line, 4, 52, scale=TEXT_SCALE)
        
        # ============================================================
        # ACTIVITY INDICATOR: Redraw after clearing display
        # ============================================================
        # FIX: Redraw the activity indicator since we cleared the entire display
        # This prevents the indicator from glitching when the display updates
        
        # Always draw lower RIGHT indicator (connection health)
        if self.connection_health_ok:
            self.graphics.set_pen(self.pen_green_bright)
        else:
            if self.activity_state:
                self.graphics.set_pen(self.pen_red_bright)
            else:
                self.graphics.set_pen(self.pen_red_dim)
        
        self.graphics.rectangle(54, 61, 10, 3)
        
        # Additionally draw lower LEFT indicator (heading staleness)
        if self.heading_ok:
            self.graphics.set_pen(self.pen_green_bright)
        else:
            if self.activity_state:
                self.graphics.set_pen(self.pen_orange_bright)
            else:
                self.graphics.set_pen(self.pen_orange_dim)
        
        self.graphics.rectangle(0, 61, 10, 3)
        
        # Draw keep-alive indicator
        self.draw_keepalive_indicator()
        
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
                ifconfig = wlan.ifconfig()
                ip = ifconfig[0]
                subnet = ifconfig[1]
                gateway = ifconfig[2]
                dns = ifconfig[3]
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

@micropython.native
def process_signalk_update(data, state_cache, deg_cache, last_raw_values):
    """Process Signal K delta update and update caches.
    
    Signal K Delta Format:
    {
        "updates": [
            {
                "values": [
                    {"path": "navigation.headingMagnetic", "value": 1.234},
                    {"path": "steering.autopilot.state", "value": "auto"},
                    {"path": "environment.heartbeat", "value": 1234567890}
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
        tuple: (display_changed, heartbeat_received, heading_changed)
            - display_changed: True if display values changed
            - heartbeat_received: True if heartbeat was in this update
            - heading_changed: True if magnetic heading VALUE changed
    """
    display_changed = False
    heartbeat_received = False
    heading_changed = False
    
    updates = data.get("updates")
    if not updates:
        return display_changed, heartbeat_received, heading_changed
    
    # Path constants for faster comparison
    PATH_HEARTBEAT = "environment.heartbeat"
    PATH_HEADING = "navigation.headingMagnetic"
    PATH_AP_STATE = "steering.autopilot.state"
    
    for update in updates:
        values = update.get("values")
        if not values:
            continue
        
        for item in values:
            path = item.get("path")
            value = item.get("value")
            
            if path is None or value is None:
                continue
            
            # Track environment.heartbeat independently
            if path == PATH_HEARTBEAT:
                heartbeat_received = True
                continue  # Don't process further, just note we got it
            
            # Check if this is a path we care about for display
            if path not in last_raw_values:
                continue
            
            # Check if value actually changed (performance optimization for display updates)
            last_value = last_raw_values[path]
            value_changed = last_value != value
            
            if value_changed:
                last_raw_values[path] = value
                display_changed = True
            
            # Track heading VALUE changes for staleness indicator
            # IMPORTANT: Only set heading_changed if the VALUE actually changed
            # This ensures indicator only shows green when heading is actively changing
            if path == PATH_HEADING and value_changed:
                heading_changed = True
            
            # Process heading values (radians → degrees with smoothing)
            # IMPORTANT: Always process headings even if value hasn't changed,
            # because deg_cache needs to be populated (could be None after reconnect)
            if path == PATH_HEADING or "heading" in path:
                was_none = deg_cache[path] is None
                deg_value = value * RAD_TO_DEG
                
                # Apply EMA smoothing for navigation heading only (but not on first value)
                if path == PATH_HEADING and not was_none:
                    old_value = deg_cache[path]
                    deg_value = old_value + HEADING_SMOOTHING * (deg_value - old_value)
                
                # Always update deg_cache
                deg_cache[path] = deg_value
                
                # If this is the first time we're populating deg_cache, trigger display update
                if was_none:
                    display_changed = True
            
            # Process state values (only if changed)
            elif path == PATH_AP_STATE and value_changed:
                state_cache[path] = value
    
    return display_changed, heartbeat_received, heading_changed


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
    heading_normalized = int(heading) % 360
    heading_str = "{:03d}°".format(heading_normalized)
    
    if mode == "auto" and target is not None:
        # Auto mode: show target and difference
        target_normalized = int(target) % 360
        target_str = "{:03d}°".format(target_normalized)
        diff = normalize_heading_difference(target, heading)
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

async def indicator_blink_task(display):
    """Background task that blinks error indicators at regular intervals.

    This task toggles the blink state for both health indicators when they're
    in error mode (connection health red, heading staleness orange).
    """
    if DEBUG_TIMING:
        print("Indicator blink task: Starting")

    while True:
        try:
            display.activity_state = not display.activity_state
            display.needs_refresh = True
            await asyncio.sleep(INDICATOR_BLINK_INTERVAL)
        except Exception as e:
            print("Indicator blink error:", e)
            await asyncio.sleep(INDICATOR_BLINK_INTERVAL)


async def keepalive_indicator_task(display):
    """Background task that blinks the keep-alive indicator every second.
    
    This provides a minimal visual confirmation that the program is running.
    Sets state only; display update is coordinated in the main loop.
    
    Args:
        display: DisplayManager instance
    """
    if DEBUG_TIMING:
        print("Keep-alive indicator task: Starting")
    
    while True:
        try:
            display.keepalive_state = not display.keepalive_state
            display.needs_refresh = True
            await asyncio.sleep(1.0)  # Blink every second
        except Exception as e:
            print("Keep-alive indicator error:", e)
            await asyncio.sleep(1.0)


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
    • Monitor TWO INDEPENDENT health indicators:
      1. Connection health (based ONLY on environment.heartbeat)
      2. Heading staleness (based ONLY on navigation.headingMagnetic VALUE changes)
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
    if RUN_SPLASH:
        run_startup_sequence()
    
    
    # Initialize hardware
    display = DisplayManager()
    
    # Show connecting message
    display.show_connecting()
    
    # Initialize WebSocket response time tracker
    ws_tracker = WSResponseTimeTracker(DEBUG_WS)
    
    # Start background task for error indicator blinking
    asyncio.create_task(indicator_blink_task(display))
    
    # Start background task for keep-alive indicator
    asyncio.create_task(keepalive_indicator_task(display))
    
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
    
    # Timing trackers - NOW COMPLETELY INDEPENDENT
    last_print_ms = 0
    last_wifi_check_ms = 0
    last_gc_ms = 0
    last_heartbeat_ms = time.ticks_ms()  # Track ONLY environmental.heartbeat updates
    last_heading_change_ms = 0  # Track ONLY navigation.headingMagnetic changes
    last_heading_value = None  # Track the actual heading value for change detection
    
    print("\n" + "="*50)
    print("Entering main loop...")
    print("Independent Status Indicators:")
    print("  - Connection Health: Based on environment.heartbeat (60s timeout)")
    print("  - Heading Staleness: Based on navigation.headingMagnetic VALUE changes (60s timeout)")
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
                    await wait_for_reconnect_with_indicators(display, RECONNECT_WAIT)
                    continue
            
            last_wifi_check_ms = now_ms
        
        # Ensure WebSocket is connected
        if websocket is None:
            try:
                # Use current cached state (or WAIT) instead of re-printing CONNECT repeatedly
                mode = state_cache.get("steering.autopilot.state")
                heading = deg_cache.get("navigation.headingMagnetic")
                target = deg_cache.get("steering.autopilot.target.headingMagnetic")
                display.update_display(mode, heading, target)
                
                websocket = AsyncWebsocketClient()
                
                # Add timeout to prevent hanging when server is down
                await asyncio.wait_for(websocket.handshake(ws_url), timeout=5.0)
                
                print("WS: Connected")
                last_print_ms = now_ms
                # Reset BOTH independent timers on new connection
                last_heartbeat_ms = now_ms
                last_heading_change_ms = 0
                last_heading_value = None
                # Reset BOTH indicators to OK state
                display.set_connection_health_ok()
                display.set_heading_ok()
                display.needs_refresh = False  # Clear pending indicator updates
                
                # Clear display state to force update on next data
                display.last_mode = None
                display.last_heading = None
                display.last_target = None
                
                # Immediately clear the "CONNECT" message by showing current state
                # Even if we don't have data yet, this clears the CONNECT screen
                display.update_display(mode, heading, target)
                
                gc.collect()
                
            except asyncio.TimeoutError:
                print("WS: Connection timeout")
                websocket = None
                display.set_connection_health_error()
                display.show_error("WS TIMEOUT")
                await wait_for_reconnect_with_indicators(display, RECONNECT_WAIT)
                continue
            
            except Exception as e:
                print("WS: Connection failed:", e)
                websocket = None
                display.set_connection_health_error()
                display.show_error("WS Fail")
                await wait_for_reconnect_with_indicators(display, RECONNECT_WAIT)
                continue
        
        # Receive and process WebSocket frame
        try:
            # Track websocket response time if debugging enabled
            ws_start = time.ticks_ms() if DEBUG_WS else 0
            
            # Add timeout to recv to prevent indefinite blocking
            # This allows the loop to check for stale data and reconnect if needed
            connection_closed = False
            try:
                message_text = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                # Check if connection was actually closed by server
                if message_text is None:
                    connection_closed = True
            except asyncio.TimeoutError:
                # No message received within timeout - not an error, just continue
                # This allows us to check data staleness and other conditions
                message_text = None
            except NotImplementedError:
                # WebSocket library doesn't handle certain frame types (ping/pong/continuation)
                # This is a known limitation of the async_websocket_client library
                # Just ignore these frames and continue - they're not data we need
                if DEBUG_TIMING:
                    print("DEBUG: WebSocket recv() NotImplementedError - ignoring unsupported frame type")
                message_text = None
            
            # Record response time if debugging enabled (only if message received)
            if DEBUG_WS and message_text:
                ws_time = time.ticks_diff(time.ticks_ms(), ws_start)
                ws_tracker.record(ws_time)
            
            # Check if connection was closed by server (not just timeout)
            if connection_closed:
                print("WS: Connection closed by server")
                websocket = None
                display.set_connection_health_error()
                display.show_error("WS CLOSE")
                await wait_for_reconnect_with_indicators(display, RECONNECT_WAIT)
                continue
            
            if message_text:
                # Parse JSON
                try:
                    data = json.loads(message_text)
                except Exception as e:
                    print("JSON parse error:", e)
                    data = None
                
                # Process Signal K delta - returns THREE independent flags
                display_changed = False
                heartbeat_received = False
                heading_changed = False
                
                if data:
                    display_changed, heartbeat_received, heading_changed = process_signalk_update(
                        data, state_cache, deg_cache, last_raw_values
                    )
                
                # ============================================================
                # INDEPENDENT INDICATOR 1: Connection Health (heartbeat-based)
                # ============================================================
                if heartbeat_received:
                    # Update heartbeat timestamp
                    last_heartbeat_ms = now_ms
                    # Set connection health indicator to OK (green)
                    display.set_connection_health_ok()
                    if DEBUG_TIMING:
                        print("DEBUG: Heartbeat received - connection healthy")
                
                # ============================================================
                # INDEPENDENT INDICATOR 2: Heading Staleness (heading-based)
                # ============================================================
                if heading_changed:
                    # Heading VALUE changed - reset staleness timer
                    # This ensures indicator only shows green when heading is actively changing
                    last_heading_change_ms = now_ms
                    display.set_heading_ok()
                    
                    # Track the value for debugging
                    if DEBUG_TIMING:
                        current_heading_raw = last_raw_values.get("navigation.headingMagnetic")
                        if current_heading_raw is not None:
                            current_heading_deg = round(current_heading_raw * RAD_TO_DEG)
                            if last_heading_value != current_heading_deg:
                                print("DEBUG: Heading updated to {}° - heading healthy".format(current_heading_deg))
                                last_heading_value = current_heading_deg
                
                # Update display if display values changed
                if display_changed:
                    # Update LED matrix display immediately on change
                    try:
                        update_start = time.ticks_ms() if DEBUG_TIMING else 0
                        
                        mode = state_cache["steering.autopilot.state"]
                        heading = deg_cache["navigation.headingMagnetic"]
                        target = deg_cache["steering.autopilot.target.headingMagnetic"]
                        
                        display.update_display(mode, heading, target)
                        
                        if DEBUG_TIMING:
                            update_time = time.ticks_diff(time.ticks_ms(), update_start)
                            print("Display update took {}ms".format(update_time))
                    except Exception as e:
                        print("Display update error:", e)
                        
                        # Log to file if enabled
                        log_error_to_file(
                            "DISPLAY_UPDATE",
                            e,  # Pass exception object, not string
                            {
                                "mode": mode,
                                "heading": heading,
                                "target": target,
                                "last_mode": display.last_mode,
                                "last_heading": display.last_heading,
                                "last_target": display.last_target
                            }
                        )
                        
                        # Detailed debug information when debug mode is enabled
                        if DEBUG_TIMING or DEBUG_WS:
                            print("\n" + "="*50)
                            print("DISPLAY UPDATE ERROR DETAILS:")
                            print("="*50)
                            
                            # Print full stack trace
                            import sys
                            sys.print_exception(e)
                            
                            # Print values being passed to display
                            print("\nValues being displayed:")
                            print("  Mode:", mode)
                            print("  Heading:", heading)
                            print("  Target:", target)
                            print("  Display last_mode:", display.last_mode)
                            print("  Display last_heading:", display.last_heading)
                            print("  Display last_target:", display.last_target)
                            
                            print("="*50 + "\n")
                
                # Update console print on change or periodic interval
                time_for_update = time.ticks_diff(now_ms, last_print_ms) >= PRINT_INTERVAL * 1000
                
                if display_changed or time_for_update:
                    # Print to console
                    status = format_status_line(state_cache, deg_cache)
                    if status:
                        print(status)
                        last_print_ms = now_ms
            
            # Check and report WebSocket statistics if debugging enabled
            if DEBUG_WS:
                ws_tracker.check_and_report(now_ms)
            
            # ============================================================
            # CHECK INDEPENDENT TIMEOUTS
            # ============================================================
            
            # Check heartbeat timeout (connection health)
            if last_heartbeat_ms > 0:
                time_since_heartbeat = time.ticks_diff(now_ms, last_heartbeat_ms) / 1000.0
                
                if time_since_heartbeat >= HEARTBEAT_TIMEOUT:
                    # No heartbeat for 60+ seconds - connection health error
                    display.set_connection_health_error()
                    if DEBUG_TIMING:
                        print("WARNING: No heartbeat for {:.1f}s - Connection health indicator RED".format(
                            time_since_heartbeat))
            
            # Check heading change timeout (heading staleness)
            if last_heading_change_ms > 0:
                time_since_heading_change = time.ticks_diff(now_ms, last_heading_change_ms) / 1000.0
                
                if time_since_heading_change > HEADING_STALE_TIMEOUT:
                    # Heading hasn't changed for 60+ seconds - heading stale
                    display.set_heading_stale()
                    if DEBUG_TIMING:
                        print("WARNING: No heading change for {:.1f}s - Heading indicator ORANGE".format(
                            time_since_heading_change))
            
        
        except OSError as e:
            print("WS: Error:", e)
            
            # Log to file if enabled
            log_error_to_file(
                "OSERROR",
                e,  # Pass exception object, not string
                {
                    "mode": state_cache.get("steering.autopilot.state"),
                    "heading": deg_cache.get("navigation.headingMagnetic"),
                    "target": deg_cache.get("steering.autopilot.target.headingMagnetic"),
                    "websocket_connected": websocket is not None,
                    "wifi_connected": is_wifi_connected()
                }
            )
            
            # Detailed debug information when debug mode is enabled
            if DEBUG_TIMING or DEBUG_WS:
                print("\n" + "="*50)
                print("DETAILED OSERROR INFORMATION:")
                print("="*50)
                
                # Print full stack trace
                import sys
                sys.print_exception(e)
                
                # Print current state
                print("\nCurrent State:")
                print("  Mode:", state_cache.get("steering.autopilot.state"))
                print("  Heading:", deg_cache.get("navigation.headingMagnetic"))
                print("  Target:", deg_cache.get("steering.autopilot.target.headingMagnetic"))
                
                # Print connection state
                print("\nConnection State:")
                print("  WebSocket:", "Connected" if websocket else "Disconnected")
                print("  WiFi:", "Connected" if is_wifi_connected() else "Disconnected")
                
                # Print memory info
                print("\nMemory:")
                print("  Free RAM: {} bytes".format(gc.mem_free()))
                print("  Allocated RAM: {} bytes".format(gc.mem_alloc()))
                
                print("="*50 + "\n")
            
            try:
                await websocket.close()
            except Exception:
                pass
            websocket = None
            display.set_connection_health_error()  # Show connection error
            display.show_error("WS ERR")
            gc.collect()
            await wait_for_reconnect_with_indicators(display, RECONNECT_WAIT)
        
        except Exception as e:
            print("ERROR:", e)
            
            # Log to file if enabled
            time_since_heartbeat = time.ticks_diff(now_ms, last_heartbeat_ms) / 1000.0 if last_heartbeat_ms > 0 else -1
            time_since_heading = time.ticks_diff(now_ms, last_heading_change_ms) / 1000.0 if last_heading_change_ms > 0 else -1
            
            log_error_to_file(
                "GENERIC",
                e,  # Pass exception object, not string
                {
                    "mode": state_cache.get("steering.autopilot.state"),
                    "heading": deg_cache.get("navigation.headingMagnetic"),
                    "target": deg_cache.get("steering.autopilot.target.headingMagnetic"),
                    "last_raw_heading": last_raw_values.get("navigation.headingMagnetic"),
                    "websocket_connected": websocket is not None,
                    "wifi_connected": is_wifi_connected(),
                    "time_since_heartbeat_s": time_since_heartbeat,
                    "time_since_heading_change_s": time_since_heading,
                    "free_ram_bytes": gc.mem_free(),
                    "allocated_ram_bytes": gc.mem_alloc()
                }
            )
            
            # Detailed debug information when debug mode is enabled
            if DEBUG_TIMING or DEBUG_WS:
                print("\n" + "="*50)
                print("DETAILED ERROR INFORMATION:")
                print("="*50)
                
                # Print full stack trace
                import sys
                sys.print_exception(e)
                
                # Print current state
                print("\nCurrent State:")
                print("  Mode:", state_cache.get("steering.autopilot.state"))
                print("  Heading:", deg_cache.get("navigation.headingMagnetic"))
                print("  Target:", deg_cache.get("steering.autopilot.target.headingMagnetic"))
                print("  Last raw heading:", last_raw_values.get("navigation.headingMagnetic"))
                
                # Print connection state
                print("\nConnection State:")
                print("  WebSocket:", "Connected" if websocket else "Disconnected")
                print("  WiFi:", "Connected" if is_wifi_connected() else "Disconnected")
                
                # Print timing information
                print("\nTiming:")
                print("  Time since heartbeat: {:.1f}s".format(time_since_heartbeat))
                if time_since_heading > 0:
                    print("  Time since heading change: {:.1f}s".format(time_since_heading))
                else:
                    print("  Time since heading change: Never")
                
                # Print memory info
                print("\nMemory:")
                print("  Free RAM: {} bytes".format(gc.mem_free()))
                print("  Allocated RAM: {} bytes".format(gc.mem_alloc()))
                
                print("="*50 + "\n")
            
            try:
                await websocket.close()
            except Exception:
                pass
            websocket = None
            display.set_connection_health_error()  # Show connection error
            display.show_error("ERR")
            gc.collect()
            await wait_for_reconnect_with_indicators(display, RECONNECT_WAIT)
        
        # Coordinated display update at end of loop iteration
        # Only runs when indicators need updating
        if display.needs_refresh:
            if DEBUG_TIMING:
                print("DEBUG: Coordinated refresh - conn_health_ok={}, heading_ok={}".format(
                    display.connection_health_ok, display.heading_ok))
            display.toggle_activity_indicator()
            display.i75.update()
            display.needs_refresh = False
        
        # Small yield to allow other tasks to run
        await asyncio.sleep(0)


# ============================================================================
# STARTUP SPLASH SCREEN
# ============================================================================

def run_startup_sequence():
    """Display animated startup splash screen on LED matrix.
    
    Shows a sequence of colored spirals followed by a multicolor starburst
    that transitions to white before starting the main program.
    
    This function creates its own display instance and cleans it up afterward
    to avoid interference with the main program's display management.
    """
    print("Splash: Starting splash screen sequence...")
    
    # Create temporary display instance just for splash
    i75 = Interstate75(
        display=DISPLAY_INTERSTATE75_64X64,
        color_order=Interstate75.COLOR_ORDER_BGR
    )
    display = i75.display
    
    # Display dimensions
    WIDTH = 64
    HEIGHT = 64
    CENTER_X = WIDTH // 2
    CENTER_Y = HEIGHT // 2
    
    # Colors
    BLACK = display.create_pen(0, 0, 0)
    RED = display.create_pen(255, 0, 0)
    GREEN = display.create_pen(0, 255, 0)
    BLUE = display.create_pen(0, 0, 255)
    WHITE = display.create_pen(255, 255, 255)
    
    def draw_spiral(color, duration):
        """Draw an animated spiral that expands from center."""
        print("Splash: Drawing {} spiral...".format("red" if color == RED else "green" if color == GREEN else "blue"))
        
        frames = int(duration * 50)  # 50 FPS
        start_time = time.ticks_ms()
        
        for frame in range(frames):
            elapsed = time.ticks_diff(time.ticks_ms(), start_time)
            if elapsed > duration * 1000:
                break
            
            progress = frame / frames
            
            # Clear screen
            display.set_pen(BLACK)
            display.clear()
            
            # Draw spiral
            display.set_pen(color)
            max_radius = int(32 * progress)
            
            for angle_deg in range(0, 360 * 3, 3):  # 3 rotations
                angle = angle_deg * math.pi / 180
                radius = (angle_deg / (360 * 3)) * max_radius
                
                x = int(CENTER_X + radius * math.cos(angle))
                y = int(CENTER_Y + radius * math.sin(angle))
                
                if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                    display.pixel(x, y)
            
            i75.update()
            time.sleep(0.02)
    
    def draw_starburst(duration):
        """Draw an animated starburst that transitions from multicolor to white."""
        print("Splash: Drawing multicolor starburst...")
        
        # Phase 1: Multicolor outward expansion (first 60% of duration)
        phase1_duration = int(duration * 600)
        phase1_start = time.ticks_ms()
        
        while time.ticks_diff(time.ticks_ms(), phase1_start) < phase1_duration:
            elapsed = time.ticks_diff(time.ticks_ms(), phase1_start)
            progress = elapsed / phase1_duration
            
            display.set_pen(BLACK)
            display.clear()
            
            # Multiple layers of particles for depth
            for layer in range(3):
                layer_offset = layer * 0.15
                num_particles = 80 + layer * 20
                
                for i in range(num_particles):
                    angle = (i / num_particles) * math.pi * 2
                    
                    # Outward expansion with variation
                    distance = progress * (40 + layer * 8)
                    
                    # Add turbulence
                    turbulence_x = math.sin(progress * 6 + i * 0.3) * 2
                    turbulence_y = math.cos(progress * 6 + i * 0.5) * 2
                    
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
        draw_starburst(3)
        
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
