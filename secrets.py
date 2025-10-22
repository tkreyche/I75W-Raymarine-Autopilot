# =============================================================
# secrets.py - Configuration file for Signal K WebSocket client
# =============================================================

# WiFi Credentials
SSID = "my wireless lan"
PASSWORD = "my password"

# Static IP Configuration (Optional)
# -----------------------------------
# Set USE_STATIC_IP to True to use static IP instead of DHCP
# If USE_STATIC_IP is False or not defined, DHCP will be used

USE_STATIC_IP = False  # Set to True to enable static IP

# Static IP Settings (only used if USE_STATIC_IP = True)
STATIC_IP = "192.168.1.100"       # Your desired static IP address
STATIC_SUBNET = "255.255.255.0"   # Subnet mask (usually 255.255.255.0)
STATIC_GATEWAY = "192.168.1.1"    # Your router's IP address
STATIC_DNS = "8.8.8.8"            # DNS server (8.8.8.8 is Google DNS)

# Signal K Server Configuration
HOST = "192.168.0.99"
PORT = 3000
VERSION = "v1"

# Display Colors (RGB tuples)
# Matrix Display colors
# All white for better visibility, change as you like
COLOR_AUTO = (255,255,255)      
COLOR_COMPASS = (255,255,255)
COLOR_TARGET = (255,255,255)
COLOR_ERROR = (255,0,0)
COLOR_DIFF = (0,0,255)

# Performance Tuning
HEADING_SMOOTHING = 0.9  # EMA smoothing factor (0.0-1.0)
                         # Lower = smoother but slower response
                         # Higher = faster but more jitter

# Debug Options
# Performance tuning
DEBUG_TIMING = False # Set to True to print timing diagnostics for display updates
DEBUG_WS = True     # Set to True to track and print WebSocket response time statistics


# EXAMPLE: Static IP Configuration
# ---------------------------------
# If you want to use a static IP address instead of DHCP:
#
# 1. Set USE_STATIC_IP = True
# 2. Configure your network settings:
#    STATIC_IP = "192.168.1.100"       # Choose an unused IP on your network
#    STATIC_SUBNET = "255.255.255.0"   # Typically this for home networks
#    STATIC_GATEWAY = "192.168.1.1"    # Your router's IP (usually .1 or .254)
#    STATIC_DNS = "8.8.8.8"            # DNS server address
#
# 3. Make sure the IP address you choose:
#    - Is in the same subnet as your router
#    - Is NOT in your router's DHCP range
#    - Is not already used by another device
#
# To find your current network settings (when using DHCP):
# - Check your router's admin page
# - Or use a device already connected to see its IP/Gateway/Subnet
