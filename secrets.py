# secrets.py - Configuration file for Signal K WebSocket Monitor
# This file contains credentials and configuration for the MicroPython program

# ============================================================================
# REQUIRED SETTINGS
# ============================================================================

# WiFi Credentials
SSID = "YourWiFiNetworkName"        # Your WiFi network name (SSID)
PASSWORD = "YourWiFiPassword"        # Your WiFi password

# Signal K Server Configuration
HOST = "192.168.1.10"                # Signal K server IP address or hostname
PORT = 3000                          # Signal K server port (default: 3000)
VERSION = "v1"                       # Signal K API version (usually "v1")

# ============================================================================
# OPTIONAL SETTINGS (uncomment and modify as needed)
# ============================================================================

# Static IP Configuration (optional - uses DHCP if not set)
# USE_STATIC_IP = True
# STATIC_IP = "192.168.1.100"
# STATIC_SUBNET = "255.255.255.0"
# STATIC_GATEWAY = "192.168.1.1"
# STATIC_DNS = "8.8.8.8"

# Signal K Subscription Paths
# Comma-separated list of Signal K paths to subscribe to
# SUBSCRIBE = (
#     "navigation.headingMagnetic,"
#     "steering.autopilot.state,"
#     "steering.autopilot.target.headingMagnetic,"
#     "environment.heartbeat"
# )

# Connection Timing Settings
# RECONNECT_WAIT = 5                 # Seconds to wait before reconnecting
# CONNECTION_TIMEOUT = 30            # Connection timeout in seconds
# SUBSCRIPTION_CHECK_INTERVAL = 15   # Seconds between subscription checks
# SUBSCRIPTION_INITIAL_WAIT = 5      # Seconds to wait before first subscription check

# Exponential Backoff Settings - Signal K
# SIGNALK_BACKOFF_INITIAL = 5        # Initial backoff delay in seconds
# SIGNALK_BACKOFF_MAX = 30           # Maximum backoff delay in seconds
# SIGNALK_BACKOFF_MULTIPLIER = 2     # Multiplier for exponential backoff

# Exponential Backoff Settings - WiFi
# WIFI_BACKOFF_INITIAL = 5           # Initial backoff delay in seconds
# WIFI_BACKOFF_MAX = 30              # Maximum backoff delay in seconds
# WIFI_BACKOFF_MULTIPLIER = 2        # Multiplier for exponential backoff

# Deduplication Settings
# ENABLE_DEDUPLICATION = True        # Enable message deduplication
# DEDUP_WINDOW_MS = 150              # Deduplication time window in milliseconds
# DEDUP_CACHE_SIZE = 50              # Number of messages to cache for deduplication

# Output Settings
# PRINT_FULL_JSON = False            # Print full JSON messages
# PRINT_PATH_VALUE = True            # Print path/value pairs in simplified format

# Heartbeat Monitoring Settings
# HEARTBEAT_TIMEOUT = 30             # Seconds before heartbeat is considered stale
# HEARTBEAT_PATH = "environment.heartbeat"  # Signal K path for heartbeat data
# HEARTBEAT_DEBUG = True             # Enable heartbeat debug messages

# Magnetic Heading Change Monitoring Settings
# MAG_HEADING_TIMEOUT = 30           # Seconds before heading is considered stale
# MAG_HEADING_PATH = "navigation.headingMagnetic"  # Signal K path for magnetic heading
# MAG_HEADING_TOLERANCE = 0.01       # Minimum heading change to consider as "changed" (radians)
# MAG_HEADING_DEBUG = True           # Enable heading debug messages

# EWMA Filter Settings for Heading
# ENABLE_HEADING_EWMA = True         # Enable exponential weighted moving average filter
# HEADING_EWMA_ALPHA = 0.2           # Smoothing factor (0.0-1.0, lower = more smoothing)

# Display Settings
# ENABLE_DISPLAY = True              # Enable the Interstate 75 W LED display

# Status Indicator Settings
# INDICATOR_BLINK_INTERVAL = 500     # Milliseconds between indicator blinks
