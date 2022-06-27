# Zucchini -- A cost-effective™ smart home irrigation solution.

# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License version 3 as published by
# the Free Software Foundation at <https://www.gnu.org/licenses/agpl-3.0>.

# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more
# details.

import network
import re
import gc
import json
import machine
import esp
import socket
import time
import ntptime
import sys
import os
import math
import wifi_config

run_pump_until = 0
run_pump_for = 0
http_server = None
next_start_time = []

wdt = None

relais_pin = machine.Pin(0)
relais_pin.init(relais_pin.OUT)
relais_pin.on()

led_pin = machine.Pin(2)
led_pin.init(led_pin.OUT)
led_pin.off()

def http_get(url):
    import socket
    _, _, host, path = url.split('/', 3)
    addr = socket.getaddrinfo(host, 80)[0][-1]
    s = socket.socket()
    s.connect(addr)
    s.send(bytes('GET /%s HTTP/1.0\r\nHost: %s\r\n\r\n' % (path, host), 'utf8'))
    response = bytes()
    while True:
        data = s.recv(100)
        if data:
            response += data
        else:
            break
    s.close()
    return response.decode('utf-8')

def factor():
    global config
    location = "%s,%s" % (config["latitude"], config["longitude"])
    base_eto_inch = config["reference_evaporation"] / 25.4
    elevation_foot = config["elevation"] * 3.28084
    url = "http://weather.opensprinkler.com/weather3.py?loc=" + location + "&key=&wto=%22baseETo%22:" + str(base_eto_inch) + ",%22elevation%22:" + str(elevation_foot)
    print(url)
    response = http_get(url)
    print(response)
    m = re.search("scale=([0-9]*)[^0-9]", response)
    if m is None:
        return None
    else:
        return float(m.group(1))

def update_next_start_time():
    global config, next_start_time
    next_start_time = [intceil((time.time() + 1 - event["start"]), config["day_length"]) * config["day_length"] + event["start"] for event in config["schedule"]]

def set_config(new_config):
    global config
    if not validate_config(new_config):
        raise ValueError()
    config = new_config

    with open("config.json", "w") as file:
        json.dump(config, file)

    update_next_start_time()

def handler(method, path, args, body, conn):
    global run_pump_until, run_pump_for, config, wdt
    if method == 'GET':
        if path == '/status.json':
            return ("200 OK", "text/json", json.dumps({
                "GC enabled" : gc.isenabled(),
                "GC mem free" : gc.mem_free(),
                "time": time.gmtime(),
                "next_start_time": [time.gmtime(t) for t in next_start_time],
                "ntp_server": ntptime.host,
                "watchdog_running": wdt is not None
            }))
        elif path == '/log.csv':
            conn.send('HTTP/1.1 200 OK\n')
            conn.send('Content-Type: text/plain\n')
            conn.send('Connection: close\n\n')
            try:
                with open("water.old", "r") as f:
                    for line in f:
                        conn.sendall(line)
            except:
                pass
            with open("water.new", "r") as f:
                for line in f:
                    conn.sendall(line)
            return (None, None, None)
        elif path == '/main.py':
            conn.send('HTTP/1.1 200 OK\n')
            conn.send('Content-Type: text/plain\n')
            conn.send('Connection: close\n\n')
            with open("main.py", "r") as f:
                for line in f:
                    conn.sendall(line)
            return (None, None, None)
        elif path == "/config.json":
            return("200 OK", "text/json", json.dumps(config))
        elif path == "/factor":
            return("200 OK", "text/html", "%s" % factor())
    elif method == 'PUT':
        if path == '/config.json':
            try:
                new_config = json.loads(body.decode("utf-8"))
                if not validate_config(new_config):
                    raise ValueError()
                set_config(new_config)
                return("200 OK", "text/json", json.dumps(config))
            except:
                return("400 Bad Request", "text/html", "<h1>Bad Request</h1>Invalid config")
    elif method == 'POST':
        if path == '/ntp':
            old_time = time.time()
            ntptime.settime()
            return("200 OK", "text/json", json.dumps({"time": time.gmtime(), "difference": time.time() - old_time}))
        if path == '/water':
            try:
                seconds = int(args['seconds'])
            except:
                return("400 Bad Request", "text/html", "<h1>Bad Request</h1>Missing or invalid <tt>?seconds=&lt;num&gt;</tt> parameter")
            run_pump_for = seconds
            run_pump_until = time.time() + run_pump_for
            write_log("water", "%d,%d,0,MANUAL" % (time.time(), seconds))
            return("200 OK", "text/json", json.dumps({"time": time.time(), "end_time": run_pump_until}))


    return ("404 Not Found", "text/html", "<h1>Not found</h1")

class HttpServer:
    def __init__(self, handler, port = 80, max_backlog = 5):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(('', port))
        self.sock.listen(max_backlog)
        self.sock.setblocking(False)
        self.handler = handler

    def poll(self):
        activity = False
        while True:
            try:
                (conn, (addr, port)) = self.sock.accept()
                conn.settimeout(2)

                try:
                    try:
                        parts = conn.readline()
                        print("received %d bytes" % len(parts))
                    except OSError:
                        parts = bytes()

                    content_length = None
                    try:
                        while True:
                            header = conn.readline().decode("utf-8").strip()
                            if header == "":
                                break
                            print("parsing header '%s'" % header)
                            [key, value] = header.split(": ")
                            if key == "Content-Length":
                                content_length = int(value)
                    except OSError:
                        pass

                    if content_length is not None:
                        body = conn.read(content_length)
                    else:
                        body = None

                    parts = parts.decode("utf-8").split()
                    print("decoded %s segments" % len(parts))
                    if len(parts) == 0:
                        print("timeout")
                        status, content_type, content = "408 Request Timeout", "text/html", "<h1>Request timed out</h1>"
                    else:
                        method = parts[0]
                        path_args = parts[1].split('?', 1)
                        args = {}
                        path = path_args[0]
                        if len(path_args) > 1:
                            for foo in path_args[1].split('&'):
                                arg_val = foo.split('=', 1)
                                if len(arg_val) == 1:
                                    args[arg_val[0]] = None
                                else:
                                    args[arg_val[0]] = arg_val[1]
                        try:
                            print("Got %s for %s with args %s and body %s" % (method, path, args, body))
                            status, content_type, content = self.handler(method, path, args, body, conn)
                        except Exception as e:
                            status = "500 Internal Server Error"
                            content_type = "text/html"
                            content = "<h1>Error 500: Internal Server Error</h1><p>The handler function raised an exception:</p><pre>%s</pre>" % e
                            sys.print_exception(e)
                except Exception as e:
                    status, content_type, content = "400 Bad Request", "text/html", "<h1>Bad Request</h1>"
                    sys.print_exception(e)

                if status is not None:
                    print("Replying with %s, %s, %s" % (status, content_type, content))
                    conn.send('HTTP/1.1 %s\n' % status)
                    conn.send('Content-Type: %s\n' % content_type)
                    conn.send('Connection: close\n\n')
                    conn.sendall(content)
                else:
                    print("Reply has been sent by handler")
                conn.close()
                activity = True
            except OSError:
                return activity
        return activity
            
def write_log(filename, text):
    MAX_SIZE = 8 * 1024

    f = open("%s.new" % filename, 'a')
    print(text, file = f)
    f.close()

    size = os.stat("%s.new" % filename)[6]
    if size > MAX_SIZE:
        os.rename("%s.new" % filename, "%s.old" % filename)

def validate_config(config):
    try:
        if not isinstance(config["schedule"], list):
            return None
        for event in config["schedule"]:
            event["start"] = int(event["start"])
            event["duration"] = int(event["duration"])
            event["subtract"] = 0 if "subtract" not in event else int(event["subtract"])
            event["max"] = 10*event["duration"] if "max" not in event else int(event["max"])
        config["day_length"] = 24 * 3600 if "day_length" not in config else int(config["day_length"])
        config["reference_evaporation"] = float(config["reference_evaporation"])
        config["longitude"] = float(config["longitude"])
        config["latitude"] = float(config["latitude"])
        config["elevation"] = float(config["elevation"])
        return config
    except:
        return None

def default_config():
    return {
        "day_length": 3600*24,
        "schedule": [{
                "start": 8 * 3600, # 10am CEST
                "duration": 5,
                "subtract": 0,
                "max": 50
        }],
        "reference_evaporation": 6,
        "latitude": 49.5529,
        "longitude": 11.0191559,
        "elevation": 279
    }


def intceil(a,b):
    return (a+b-1)//b

def run():
    global run_pump_until, run_pump_for, next_start_time, relais_pin, wdt, led_pin, http_server
    performance_until = 0
    NTP_RESYNC_INTERVAL = 3600
    next_ntp_sync = time.time() + NTP_RESYNC_INTERVAL

    wdt_start = time.time() + 60

    while True:
        if wdt is None and time.time() > wdt_start:
            led_pin.on()
            wdt = machine.WDT()

        if http_server.poll() or performance_until > time.time() + 120:
            performance_until = time.time() + 120
            print("setting performance_until to %d" % performance_until)

        if time.time() < performance_until:
            machine.lightsleep(10)
        else:
            if performance_until != 0:
                print("Leaving performance mode")
                performance_until = 0
            machine.lightsleep(500)

        if next_ntp_sync > time.time() + NTP_RESYNC_INTERVAL:
            next_ntp_sync = time.time() + NTP_RESYNC_INTERVAL

        if time.time() > next_ntp_sync:
            try:
                ntptime.settime()
            except:
                pass
            next_ntp_sync = time.time() + NTP_RESYNC_INTERVAL


        if time.time() + run_pump_for < run_pump_until:
            run_pump_until = time.time() + run_pump_for

        if wdt is not None:
            if time.time() < run_pump_until:
                relais_pin.off() # turn the relais ON
            else:
                relais_pin.on() # relais OFF

            wdt.feed()

        for (starttime, event) in zip(next_start_time, config["schedule"]):
            if time.time() >= starttime:
                update_next_start_time()
                try:
                    curr_factor = factor()
                    curr_factor_readable = curr_factor
                except:
                    curr_factor = 100
                    curr_factor_readable = "FAIL"

                run_pump_for = int(event["duration"] * curr_factor / 100 - event["subtract"])
                run_pump_for = max(run_pump_for, 0)
                run_pump_for = min(run_pump_for, event["max"])

                if run_pump_for > 0:
                    run_pump_until = time.time() + run_pump_for
                    write_log("water", "%d,%d,%s,AUTO" % (time.time(), run_pump_for, curr_factor_readable))

gc.enable()

esp.sleep_type(esp.SLEEP_LIGHT)

ap = network.WLAN(network.AP_IF)
ap.active(False)

wlan = network.WLAN()
wlan.connect(wifi_config.wifi_ssid, wifi_config.wifi_key)

try:
    config = json.load(open("config.json", "r"))
    if not validate_config(config):
        config = default_config()
except:
    config = default_config()

toggle = True
while True:
    try:
        ntptime.settime()
        break
    except:
        print("Setting time from NTP failed, retrying")
        time.sleep(1)
        toggle = not toggle
        if toggle:
            led_pin.on()
        else:
            led_pin.off()

led_pin.off()

update_next_start_time()

http_server = HttpServer(handler)
run()
