# Zucchini

An el-cheapo small-scale irrigation system for watering my zucchini plant.

It uses an ESP8266 module (the cheap ESP-01 module, to be exact) and a relay board, both of which
can be bought at your favourite chinese marketplace for less than three bucks.  Oh yea and it uses
[micropython](https://micropython.org/).

![Photo of the ESP8266 relay board](esp_relay.png)

Together with a small water pump that is driven by the relay, and some hose which I drilled holes
into, this makes for a really ~~feature-rich~~cheap irrigation solution.

It automatically adjusts irrigation time based on the estimated evaporation which depends on the
weather.

Throw in a 5V linear regulator and a 12V/1A power supply to the mix and we're talking less than 20
bucks in total.

And the best is: Of course it's internet of things, and of course it speaks a REST-ish API!

## Usage

Download the "ESP8266 with 1MiB flash" version from [micropython's download
page](https://micropython.org/download/?mcu=esp8266). Erase the chip's flash and flash the firmware,
e.g. using `esptool`.

Attach a serial adapter and set it to 115200 baud. Press enter for a python shell.  Follow [their
guide](https://docs.micropython.org/en/latest/esp8266/tutorial/intro.html) to enable webrepl.

Search for the following lines in `main.py` and change them accordingly:

```python
wifi_ssid = 'YOUR WIFI SSID'
wifi_key = 'YOUR WIFI KEY'
```

Use [Webrepl](http://micropython.org/webrepl) to upload the `main.py` file.

Upon rebooting, the device should connect to your WiFi and expose the following HTTP endpoints:

- `GET /status.json` gives you information about the current state of the system.
- `GET /log.csv` should give you a log of past activations, but currently does not work.
- `GET /config.json` reads the current config as JSON.
- `PUT /config.json` sets a new config. See below for the configuration format.
- `POST /ntp` forces the system to re-fetch its time via NTP. Note that this is done on startup
  anyway and should not be neccessary.
- `POST /water?seconds=42` will turn on the pump relais for 42 seconds.

## Configuration

```javascript
{
  "day_length": 86400,          // Optional and mainly useful for testing

  "start_time_in_day": 28800,   // When the irrigation starts in seconds after the start of a
                                // day. 28800 = 8 * 3600.
  
  "irrigation_duration": 5,     // Irrigation duration in seconds at the reference evaporation. If
                                // the current evaporation is higher(lower), this gets scaled up(down)
  
  "reference_evaporation": 6,   // Reference evaporation in mm/day.
  
  "latitude": 49.5529,          // Your location (required for the weather forecast)
  "longitude": 11.0191559,
  "elevation": 279              // Elevation in m above NN
}
```

Note that the `wifi_ssid` and `wifi_key` are hard-coded and can only be changed by editing `main.py`.
