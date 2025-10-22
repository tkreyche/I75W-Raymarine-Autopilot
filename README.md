## I75W Display for Raymarine Tilllerpilot

### Target Audience
This project is for DIY sailors with some familiarity with electronics projects. For those not inclined, there are commerically available (and more expensive) displays available.

### Introduction
This project uses off-the-shelf hardware to create an remote daylight-visible display for Raymarine Tillerpilots, such as the ST1000+. The Tillerpilot is typically mounted near the stern of a boat, and it is incovenient to view the display and change control values with the buttons. This display can be mounted in an immediately visible location. The NautiControl ST control module remote control with a handheld wireless keypad. The NautiControl module is not essential, but the combination gives you a complete solution at low cost. It's an alternative to the expensive Raymarine remote.

The I75W Display allows sailors to get immediate visual feedback from their Tillerpilot when controlling it using the ST wireless module. NautiControl can run a web UI on a mobile phone, but I can't manage that in typical sailing conditions.

### Hardware
The hardware is a Pimoroni I75W board driving a LED Matrix Display. The display used here is a 64x64 2mm pitch LED Matrix (128x128mm). The 2mm pitch offers higher LED density and a compact package. These displays are widely available in different sizes.

### Waterproofing
The display is not waterproof and requires a case. Later, I'll add documentation for a case build using a low-reflective acrylic front panel. It's possible to buy waterproof matrix displays, but they are expensive - intended for use in outdoor venues such as sports stadiums.

### LED Matrix and Power 
The LED matrix is used because it's bright, inexpensive, readily availble and updates quickly (unlike eink). LED matrix displays can use a lot of power, dependent on the display size and how many LEDs are turned on. For a text-only display the power consumption is reasonable. The system is capable of fancy graphics but this version doesn't use any (see Pimoroni for examples). 

The hardware runs on 5v and will need a voltage coverter for a 12 or 24v system. It can be powered from a USB-C cable or a simple 5v power cable.

### Tillerpilot
This project depends on using a Raymarine Tillerpilot. These devices are somewhat antiquated, but are widely used and relatively low-cost solution for automated steering. They have well-known flaws, such as lack of waterproofing, hard end stops and the use of an outdated communications protocol. Other DIY options are available, such as pyPilot or mechanical windvanes which are not covered here.

### Signal K Server
This project requires a Signal K server, typically running on a Raspbery Pi, and used by many DIY sailors. The Tillerpilot sends data using the Seatalk1 protocol to the Signal K server.
The I75W board and display connects wirelessly to the Signal K server to retrieve the Tillerpilot data.

There are several options for sending data from the Tillerpilot to the Signal K server:
1) Use an optoisolater to hard-wire the Tillerpilot to a Raspbery Pi port - this is simple and is described in the Signal K documentation for Seatalk.
2) Use a MacArthur Hat, which has a Seatalk1 port, also hard-wires the Tillpilot cable. This Hat is widely used and also handles NMEA2000 connections.
3) Send the data wirelessly to the Signal K server from a NautiControl ST Wirelss module. The Tillerpilot is hard-wired to the NautiContol module.

There may be future options to send Tillerpilot data from a NautiControl ST Wireless module directly to a I75W display, without the need for a Signal K server.

### Software Description (optional read)
The code is written in Micropython with the help of Claude.ai. The code runs on single RP2050 core, and profiling shows there is plenty of headroom.
The connection uses the Signal K websockets interface for lowest latency communications.
Retry logic is used for the wireless LAN connection and for the websocket connection to the Signal K server.
Common configuration items are stored in a secrets.py file, so the main code file doesn't need to be edited, unless the display size or other significant changes are made.

There are optional flags available to print performance data to a console.

### Software Installation on the I75W Board
1) Follow the Pimoroni instructions on how to install the latest version of their custom Micropython distribution onto the I75W board.
2) There are a few options for loading Micropython code files onto the board, the simplest to use the Thonny programming tool - it's a free download. VS Code can be used but it's more complicated to set up. Unfortunately, you can't just drop the files onto the device mounted as a USB drive.
3) Run Thonny, connect the I75W board with a USB cable. Under options, set the Interpreter to MicroPython (Raspberry Pi Pic) and set the Port to the USB serial port the board is using.
4) When this is done correctly, the board file system shows up on the left hand side of the display as Raspberry Pi Pico. If you're having problems there many tutorials for using Thonny with these boards.
3) Follow these instructions to add a websocket library: https://pypi.org/project/micropython-async-websocket-client/
5) Drop in the secrets file, modified for the wireless network, and the program file into the root.

### Links:

https://shop.pimoroni.com/products/interstate-75-w?variant=54977948713339

https://nauti-control.com/







