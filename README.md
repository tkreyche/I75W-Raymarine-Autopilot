## I75W Display for Raymarine Tilllerpilot


### Short Description
This project uses off-the-shelf hardware to create an remote daylight-visible display for Raymarine Tillerpilots, such as the ST1000+. It's not convenient to depend on the one-line display on the Tillerpilot, typically mounted near the stern of a boat.

This display is intended to be a companion to the NautiControl ST Wirelss module and allows a sailor to get immediate feedback when operating the Tillerpilot remote control.

This project is for DIY sailors. For those not inclined, there are commerically available (expensive) displays available.

### Hardware
The hardware is a Pimoroni I75W board driving a LED Matrix Display. The display used here is a 64x64 2mm pitch LED Matrix (128x128mm). The 2mm pitch offers higher LED density and a compact package. These displays are widely available in different sizes.

### Waterproofing
The display is not waterproof and requires a case. Later, I'll add documentation for a case build using a low-reflective acrylic front panel. It's possible to buy waterproof matrix display, but they are expensive - intended for use in outdoor venues such as sports stadiums.

### LED Matrix and Power 
The LED matrix is used because it's bright, inexpensive, readily availble and updates quickly (unlike eink). LED matrix displays can use a lot of power, dependent on the display size and how many LEDs are turned on. For a text-only display the power consumption is reasonable. The system is capable of fancy graphics but this version doesn't use any (see Pimoroni for examples). 

The hardware runs on 5v and will need a voltage coverter for a 12 or 24v system.

### Tillerpilot
This project depends on using a Raymarine Tillerpilot. These devices are somewhat antiquated, but are widely used and relatively low-cost solution for automated steering. They have well-known flaws, such as lack of waterproofing and use of an outdated communications protocol. Other DIY options are available, such as pyPilot or mechanical windvanes which are not covered here.

### Signal K Server
This project requires a Signal K server, typically running on a Raspbery Pi, and used by many DIY sailors. The Tillerpilot sends data using the Seatalk1 protocol to the Signal K server.
The I75W board and display connects wirelessly to the Signal K server.

There are several ways to send data from the Tillerpilot to the Signal K server:
1) Use an optoisolater to hard-wire the Tillerpilot to a Raspbery Pi port - this is simple and is described in the Signal K documentation for Seatalk.
2) Use a MacArthur Hat, which has a Seatalk1 port, also hard-wired. This Hat is widely used and also handles NMEA2000 connections.
3) Send the data wireless to the Signal K server from a NautiControl ST Wirelss module. The Tillerpilot is hard-wired to the NautiContol module. TK needs to be tested.



### Software Description (optional read)
The code is written in Micropython with the help of Claude.ai.
The connection uses the Signal K websockets interface for lowest latency.
Retry logic is used for the wireless LAN connection and for the websocket connection to the Signal K server.
Common configuration items are in a secrets.py file, so the main code file doesn't need to be edited, unless the display size or other significant changes are made.
 The connection uses the Signal K websockets interface for lowest latency.
Runs on single core, there is plenty of headroom.

Performance flags available.


### Installation on I75W Board
The Pimoroni I75W web site has additional details. Basic steps:
1) Reset the I75W board while plugged into a USB port, and it will show up as a disk drive.
2) Update the I75W board using their lastest custom micropython build.
3) Follow the instructions here to add a websocket library to a lib folder: https://pypi.org/project/micropython-async-websocket-client/
5) Drop in the secrets file, modified for the wireless network, and the program file.

### Links:

https://shop.pimoroni.com/products/interstate-75-w?variant=54977948713339

https://nauti-control.com/







