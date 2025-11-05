# secrets.py - Configuration template for ws10b.py
# MicroPython WebSocket Frame Monitor for Signal K
# 
# This file contains all the configuration settings needed for the program.
# Copy this file to your device and update the values below.

# ============================================================================
# REQUIRED SETTINGS - You must set these
# ============================================================================

# WiFi Credentials
SSID = "your-wifi-network-name"      # Your WiFi network SSID
PASSWORD = "your-wifi-password"       # Your WiFi password

# Signal K Server Connection
HOST = "192.168.1.10"                 # Signal K server IP address or hostname
PORT = 3000                           # Signal K server WebSocket port (default: 3000)
VERSION = "v1"                        # Signal K API version (typically "v1")


# ============================================================================
# OPTIONAL SETTINGS - Static IP Configuration
# ============================================================================

# Set to True to use static IP instead of DHCP
USE_STATIC_IP = False

# Static IP settings (only used if USE_STATIC_IP = True)
STATIC_IP = "192.168.1.100"
STATIC_SUBNET = "255.255.255.0"
STATIC_GATEWAY = "192.168.1.1"
STATIC_DNS = "8.8.8.8"


# ============================================================================
# OPTIONAL SETTINGS - Signal K Subscriptions
# ============================================================================

# Comma-separated list of Signal K paths to subscribe to
# Default monitors heading, autopilot state, and heartbeat
SUBSCRIBE = (
    "navigation.headingMagnetic,"
    "steering.autopilot.state,"
    "steering.autopilot.target.headingMagnetic,"
    "environment.heartbeat"
)


# ============================================================================
# OPTIONAL SETTINGS - Connection Timing
# ============================================================================

# Seconds to wait before reconnecting after connection loss
RECONNECT_WAIT = 5

# Seconds to wait for initial connection before timeout
CONNECTION_TIMEOUT = 30

# Seconds between subscription confirmation checks
SUBSCRIPTION_CHECK_INTERVAL = 15

# Seconds to wait after connection before checking subscriptions
SUBSCRIPTION_INITIAL_WAIT = 5


# ============================================================================
# OPTIONAL SETTINGS - Exponential Backoff
# ============================================================================

# Signal K reconnection backoff settings
SIGNALK_BACKOFF_INITIAL = 5        # Initial delay in seconds
SIGNALK_BACKOFF_MAX = 30           # Maximum delay in seconds
SIGNALK_BACKOFF_MULTIPLIER = 2     # Multiplier for each retry

# WiFi reconnection backoff settings
WIFI_BACKOFF_INITIAL = 5           # Initial delay in seconds
WIFI_BACKOFF_MAX = 30              # Maximum delay in seconds
WIFI_BACKOFF_MULTIPLIER = 2        # Multiplier for each retry


# ============================================================================
# OPTIONAL SETTINGS - Data Processing
# ============================================================================

# Deduplication settings (prevents duplicate messages within time window)
ENABLE_DEDUPLICATION = True        # Enable/disable deduplication
DEDUP_WINDOW_MS = 150              # Time window in milliseconds
DEDUP_CACHE_SIZE = 50              # Number of recent messages to track

# Output formatting
PRINT_FULL_JSON = False            # Print complete JSON messages
PRINT_PATH_VALUE = True            # Print path: value pairs

# Garbage collection
GC_COLLECT_INTERVAL = 100          # Force GC after this many messages


# ============================================================================
# OPTIONAL SETTINGS - Heartbeat Monitoring
# ============================================================================

# Monitor for regular heartbeat signals from Signal K
HEARTBEAT_TIMEOUT = 30             # Seconds before heartbeat considered stale
HEARTBEAT_PATH = "environment.heartbeat"  # Path to monitor for heartbeat
HEARTBEAT_DEBUG = True             # Print heartbeat status messages


# ============================================================================
# OPTIONAL SETTINGS - Magnetic Heading Monitoring
# ============================================================================

# Monitor for changes in magnetic heading
MAG_HEADING_TIMEOUT = 30           # Seconds before heading considered stale
MAG_HEADING_PATH = "navigation.headingMagnetic"  # Path to monitor
MAG_HEADING_TOLERANCE = 0.01       # Minimum change to detect (radians)
MAG_HEADING_DEBUG = True           # Print heading status messages


# ============================================================================
# OPTIONAL SETTINGS - EWMA Filtering
# ============================================================================

# Exponentially Weighted Moving Average filter for heading smoothing
ENABLE_HEADING_EWMA = True         # Enable heading smoothing
HEADING_EWMA_ALPHA = 0.2           # Smoothing factor (0.0-1.0, lower = more smoothing)

# EWMA filter for WiFi signal strength (RSSI) smoothing
ENABLE_RSSI_EWMA = True            # Enable RSSI smoothing
RSSI_EWMA_ALPHA = 0.3              # Smoothing factor (0.0-1.0, lower = more smoothing)


# ============================================================================
# OPTIONAL SETTINGS - Display
# ============================================================================

# Display settings (for Pimoroni Interstate 75 W)
ENABLE_DISPLAY = True              # Enable/disable display output

# Status indicator blink rate
INDICATOR_BLINK_INTERVAL = 500     # Milliseconds between blinks for stale indicators
