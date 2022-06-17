import network
import re
import gc
import json
import machine
import esp
import socket
import time
import ntptime

gc.enable()

wifi_ssid = 'YOUR WIFI SSID'
wifi_key = 'YOUR WIFI KEY'
elevation_meters = 279
location = "49.5529,11.0191559"
base_eto_mm = 6

elevation_foot = 3.28084 * elevation_meters
base_eto_inch = 6 / 25.4

wlan = network.WLAN()
wlan.connect(wifi_ssid, wifi_key)

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
    url = "http://weather.opensprinkler.com/weather3.py?loc=" + location + "&key=&wto=%22baseETo%22:" + str(base_eto_inch) + ",%22elevation%22:" + str(elevation_foot)
    print(url)
    response = http_get(url)
    print(response)
    m = re.search("scale=([0-9]*)[^0-9]", response)
    if m is None:
        return None
    else:
        return float(m.group(1))

def handler(method, path, args):
    if method == 'GET':
        if path == '/status.json':
            return ("200 OK", "text/json", json.dumps({
                "GC enabled" : gc.isenabled(),
                "GC mem free" : gc.mem_free(),
                "time": time.time(),
                "ntp_server": ntptime.host
            }))
    elif method == 'POST':
        if path == '/ntp':
            ntptime.settime()
            return("200 OK", "text/json", json.dumps({"time": time.time()}))

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
                        parts = conn.recv(1024)
                        print("received %d bytes" % len(parts))
                    except:
                        parts = bytes()
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
                            print("Got %s for %s with args %s" % (method, path, args))
                            status, content_type, content = self.handler(method, path, args)
                        except:
                            status = "500 Internal Server Error"
                            content_type = "text/html"
                            content = "<h1>Error 500: Internal Server Error</h1>The handler function raised an exception"
                except:
                    status, content_type, content = "400 Bad Request", "text/html", "<h1>Bad Request</h1>"

                print("Replying with %s, %s, %s" % (status, content_type, content))
                conn.send('HTTP/1.1 %s\n' % status)
                conn.send('Content-Type: %s\n' % content_type)
                conn.send('Connection: close\n\n')
                conn.sendall(content)
                conn.close()
                activity = True
            except OSError:
                return activity
        return activity
            
h = HttpServer(handler)

run_pump_until = 0
run_pump_for = 0

relais_pin = machine.Pin(2) # actually, its 0

relais_pin.init(relais_pin.OUT)
relais_pin.off()

def run():
    global run_pump_until, run_pump_for
    performance_until = 0
    while True:
        if h.poll() or performance_until > time.time() + 120:
            performance_until = time.time() + 120
            print("setting performance_until to %d" % performance_until)

        if time.time() < performance_until:
            machine.lightsleep(10)
        else:
            if performance_until != 0:
                print("Leaving performance mode")
                performance_until = 0
            machine.lightsleep(500)


        if time.time() + run_pump_for > run_pump_until:
            run_pump_until = time.time() + run_pump_for

        if time.time() < run_pump_until:
            relais_pin.on()
        else:
            relais_pin.off()


run()
