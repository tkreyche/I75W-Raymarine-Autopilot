# I75W-Raymarine-Autopilot
Remote LED Matrix Display for Raymarine autopilots using Pimoroni I75W board

This project uses off-the-shelf hardware to create a daylight-visible display for Raymarine tillerpilots, such as the ST1000+.
It is intended to be a companion to the NautiControl ST Wirelss module, although that's not essential

The display can used when it is not convenient to view the small display on the tillerpilot, and when there is no other (typically expensive) marine display available.

The display used here is a 64x64 2mm pitch LED Matrix (128x128mm). These are widely available in different configurations. The 2mm pitch offers higher LED density in a more compact package.

The display is not waterproof and will require a case. Later, I'll discuss a case build using low-reflective acrylic front panel. It's possible to buy a waterproof matrix, but they are expensive - intended for use in outdoor venues such a sports stadiums.

LED matrix display can use a lot of power, but that's dependent on the display size and how many LEDs are turned on. For a text-only display the power consumption is reasonable, about TK. The display is capable of fancy graphics but this version doesn't have any. Pimoroni has examples.

This project requires that you have a Signal K server, typically running on a Raspbery Pi. The tillerpilot sends data using the Seatalk1 protocol to the Signal K server. There are several connection options:
1) Use an optoisolater to hard-wire the Tillerpilot to a Raspbery Pi port - this is described in the Signal K documentation, and is simple.
2) Use a MacArthur Hat, which has a Seatalk1 port, also hard-wired.
3) Send the data wireless to the Signal K server from a NautiControl ST Wirelss module. The Tillerpilot is hard-wired to the NautiContol module. TK needs to be tested.

In all cases, the I75W board and display connects wirelessly to the Signal K server. The connection uses the Signal K websockets interface for lowest latency.






