import sys,os,time
import logging
from bluepy.btle import Peripheral, DefaultDelegate, ADDR_TYPE_RANDOM,ADDR_TYPE_PUBLIC, BTLEException
from constants import UUIDS, AUTH_STATES, ALERT_TYPES, QUEUE_TYPES, MUSICSTATE
import struct
from datetime import datetime, timedelta
from Crypto.Cipher import AES
from datetime import datetime
try:
    import zlib
except ImportError:
    print("zlib module not found. Updating watchface/firmware requires zlib")
try:
    from Queue import Queue, Empty
except ImportError:
    from queue import Queue, Empty
try:
    xrange
except NameError:
    xrange = range


class Delegate(DefaultDelegate):
    def __init__(self, device):
        DefaultDelegate.__init__(self)
        self.device = device
        self.pkg = 0

    def handleNotification(self, hnd, data):
        if hnd == self.device._char_auth.getHandle():
            if data[:3] == b'\x10\x01\x01':
                self.device._req_rdn()
            elif data[:3] == b'\x10\x01\x04':
                self.device.state = AUTH_STATES.KEY_SENDING_FAILED
            elif data[:3] == b'\x10\x02\x01':
                # 16 bytes
                random_nr = data[3:]
                self.device._send_enc_rdn(random_nr)
            elif data[:3] == b'\x10\x02\x04':
                self.device.state = AUTH_STATES.REQUEST_RN_ERROR
            elif data[:3] == b'\x10\x03\x01':
                self.device.state = AUTH_STATES.AUTH_OK
            elif data[:3] == b'\x10\x03\x04':
                self.device.status = AUTH_STATES.ENCRIPTION_KEY_FAILED
                self.device._send_key()
            else:
                self.device.state = AUTH_STATES.AUTH_FAILED
        elif hnd == self.device._char_heart_measure.getHandle():
            self.device.queue.put((QUEUE_TYPES.HEART, data))
        elif hnd == 0x38:
            if len(data) == 20 and struct.unpack('b', data[0:1])[0] == 1:
                self.device.queue.put((QUEUE_TYPES.RAW_ACCEL, data))
            elif len(data) == 16:
                self.device.queue.put((QUEUE_TYPES.RAW_HEART, data))
        # The fetch characteristic controls the communication with the activity characteristic.
        elif hnd == self.device._char_fetch.getHandle():
            if data[:3] == b'\x10\x01\x01':
                # get timestamp from what date the data actually is received
                year = struct.unpack("<H", data[7:9])[0]
                month = struct.unpack("b", data[9:10])[0]
                day = struct.unpack("b", data[10:11])[0]
                hour = struct.unpack("b", data[11:12])[0]
                minute = struct.unpack("b", data[12:13])[0]
                self.device.first_timestamp = datetime(year, month, day, hour, minute)
                print("Fetch data from {}-{}-{} {}:{}".format(year, month, day, hour, minute))
                self.pkg = 0 #reset the packing index
                self.device._char_fetch.write(b'\x02', False)
            elif data[:3] == b'\x10\x02\x01':
                if self.device.last_timestamp > self.device.end_timestamp - timedelta(minutes=1):
                    print("Finished fetching")
                    return
                print("Trigger more communication")
                time.sleep(1)
                t = self.device.last_timestamp + timedelta(minutes=1)
                self.device.start_get_previews_data(t)

            elif data[:3] == b'\x10\x02\x04':
                print("No more activity fetch possible")
                return
            else:
                print("Unexpected data on handle " + str(hnd) + ": " + str(data))
                return
        elif hnd == self.device._char_activity.getHandle():
            if len(data) % 4 == 1:
                self.pkg += 1
                i = 1
                while i < len(data):
                    index = int(self.pkg) * 4 + (i - 1) / 4
                    timestamp = self.device.first_timestamp + timedelta(minutes=index)
                    self.device.last_timestamp = timestamp
                    category = struct.unpack("<B", data[i:i + 1])[0]
                    intensity = struct.unpack("B", data[i + 1:i + 2])[0]
                    steps = struct.unpack("B", data[i + 2:i + 3])[0]
                    heart_rate = struct.unpack("B", data[i + 3:i + 4])[0]
                    if timestamp < self.device.end_timestamp:
                        self.device.activity_callback(timestamp,category,intensity,steps,heart_rate)
                    i += 4

        #music controls
        elif(hnd == 74):
            if(data[1:] == b'\xe0'):
                self.device.setMusic()
                if(self.device._default_music_focus_in):
                    self.device._default_music_focus_in()
            elif(data[1:]==b'\xe1'):
                if(self.device._default_music_focus_out):
                    self.device._default_music_focus_out()
            elif(data[1:]==b'\x00'):
                if(self.device._default_music_play):
                    self.device._default_music_play()
            elif(data[1:]==b'\x01'):
                if(self.device._default_music_pause):
                    self.device._default_music_pause()
            elif(data[1:]==b'\x03'):
                if(self.device._default_music_forward):
                    self.device._default_music_forward()
            elif(data[1:]==b'\x04'):
                if(self.device._default_music_back):
                    self.device._default_music_back()
            elif(data[1:]==b'\x05'):
                if(self.device._default_music_vup):
                    self.device._default_music_vup()
            elif(data[1:]==b'\x06'):
                if(self.device._default_music_vdown):
                    self.device._default_music_vdown()

class miband(Peripheral):
    _send_rnd_cmd = struct.pack('<2s', b'\x02\x00')
    _send_enc_key = struct.pack('<2s', b'\x03\x00')
    def __init__(self, mac_address,key=None, timeout=0.5, debug=False):
        FORMAT = '%(asctime)-15s %(name)s (%(levelname)s) > %(message)s'
        logging.basicConfig(format=FORMAT)
        log_level = logging.WARNING if not debug else logging.DEBUG
        self._log = logging.getLogger(self.__class__.__name__)
        self._log.setLevel(log_level)


        self._log.info('Connecting to ' + mac_address)
        Peripheral.__init__(self, mac_address, addrType=ADDR_TYPE_PUBLIC)
        self._log.info('Connected')
        if not key:
            self.setSecurityLevel(level = "medium")
        self.timeout = timeout
        self.mac_address = mac_address
        self.state = None
        self.heart_measure_callback = None
        self.heart_raw_callback = None
        self.accel_raw_callback = None
        self.auth_key = key
        self.queue = Queue()
        self.svc_1 = self.getServiceByUUID(UUIDS.SERVICE_MIBAND1)
        self.svc_2 = self.getServiceByUUID(UUIDS.SERVICE_MIBAND2)
        self.svc_heart = self.getServiceByUUID(UUIDS.SERVICE_HEART_RATE)

        self._char_auth = self.svc_2.getCharacteristics(UUIDS.CHARACTERISTIC_AUTH)[0]
        self._desc_auth = self._char_auth.getDescriptors(forUUID=UUIDS.NOTIFICATION_DESCRIPTOR)[0]

        self._char_heart_ctrl = self.svc_heart.getCharacteristics(UUIDS.CHARACTERISTIC_HEART_RATE_CONTROL)[0]
        self._char_heart_measure = self.svc_heart.getCharacteristics(UUIDS.CHARACTERISTIC_HEART_RATE_MEASURE)[0]

        # Recorded information
        self._char_fetch = self.getCharacteristics(uuid=UUIDS.CHARACTERISTIC_FETCH)[0]
        self._desc_fetch = self._char_fetch.getDescriptors(forUUID=UUIDS.NOTIFICATION_DESCRIPTOR)[0]
        self._char_activity = self.getCharacteristics(uuid=UUIDS.CHARACTERISTIC_ACTIVITY_DATA)[0]
        self._desc_activity = self._char_activity.getDescriptors(forUUID=UUIDS.NOTIFICATION_DESCRIPTOR)[0]

        #chunked transfer and music
        self._char_chunked = self.svc_1.getCharacteristics(UUIDS.CHARACTERISTIC_CHUNKED_TRANSFER)[0]
        self._char_music_notif= self.svc_1.getCharacteristics(UUIDS.CHARACTERISTIC_MUSIC_NOTIFICATION)[0]
        self._desc_music_notif = self._char_music_notif.getDescriptors(forUUID=UUIDS.NOTIFICATION_DESCRIPTOR)[0]

        self._auth_notif(True)
        self.activity_notif_enabled = False
        self.waitForNotifications(0.1)
        self.setDelegate( Delegate(self) )
        
    def generateAuthKey(self):
        if(self.authKey):
            return struct.pack('<18s',b'\x01\x00'+ self.auth_key)

    def _send_key(self):
        self._log.info("Sending Key...")
        self._char_auth.write(self._send_my_key)
        self.waitForNotifications(self.timeout)

    def _auth_notif(self, enabled):
        if enabled:
            self._log.info("Enabling Auth Service notifications status...")
            self._desc_auth.write(b"\x01\x00", True)
        elif not enabled:
            self._log.info("Disabling Auth Service notifications status...")
            self._desc_auth.write(b"\x00\x00", True)
        else:
            self._log.error("Something went wrong while changing the Auth Service notifications status...")

    def initialize(self):
        self._req_rdn()

        while True:
            self.waitForNotifications(0.1)
            if self.state == AUTH_STATES.AUTH_OK:
                self._log.info('Initialized')
                self._auth_notif(False)
                return True
            elif self.state is None:
                continue

            self._log.error(self.state)
            return False

    def _req_rdn(self):
        self._log.info("Requesting random number...")
        self._char_auth.write(self._send_rnd_cmd)
        self.waitForNotifications(self.timeout)

    def _send_enc_rdn(self, data):
        self._log.info("Sending encrypted random number")
        cmd = self._send_enc_key + self._encrypt(data)
        send_cmd = struct.pack('<18s', cmd)
        self._char_auth.write(send_cmd)
        self.waitForNotifications(self.timeout)

    def _encrypt(self, message):
        aes = AES.new(self.auth_key, AES.MODE_ECB)
        return aes.encrypt(message)

    def _get_from_queue(self, _type):
        try:
            res = self.queue.get(False)
        except Empty:
            return None
        if res[0] != _type:
            self.queue.put(res)
            return None
        return res[1]

    def _parse_queue(self):
        while True:
            try:
                res = self.queue.get(False)
                _type = res[0]
                if self.heart_measure_callback and _type == QUEUE_TYPES.HEART:
                    self.heart_measure_callback(struct.unpack('bb', res[1])[1])
                elif self.heart_raw_callback and _type == QUEUE_TYPES.RAW_HEART:
                    self.heart_raw_callback(self._parse_raw_heart(res[1]))
                elif self.accel_raw_callback and _type == QUEUE_TYPES.RAW_ACCEL:
                    self.accel_raw_callback(self._parse_raw_accel(res[1]))
            except Empty:
                break

    def _parse_raw_accel(self, bytes):
        res = []
        for i in xrange(3):
            g = struct.unpack('hhh', bytes[2 + i * 6:8 + i * 6])
            res.append({'x': g[0], 'y': g[1], 'wtf': g[2]})
        return res

    def _parse_raw_heart(self, bytes):
        # Interpret as accelerometer data
        res = []
        for i in range(0, len(bytes), 4):  # Assuming each reading is 4 bytes (2 axes)
            x, y = struct.unpack('<hh', bytes[i:i + 4])  # Two 16-bit integers
            res.append({'x': x, 'y': y})
        return res

    @staticmethod
    def _parse_date(bytes):
        year = struct.unpack('h', bytes[0:2])[0] if len(bytes) >= 2 else None
        month = struct.unpack('b', bytes[2:3])[0] if len(bytes) >= 3 else None
        day = struct.unpack('b', bytes[3:4])[0] if len(bytes) >= 4 else None
        hours = struct.unpack('b', bytes[4:5])[0] if len(bytes) >= 5 else None
        minutes = struct.unpack('b', bytes[5:6])[0] if len(bytes) >= 6 else None
        seconds = struct.unpack('b', bytes[6:7])[0] if len(bytes) >= 7 else None
        day_of_week = struct.unpack('b', bytes[7:8])[0] if len(bytes) >= 8 else None
        fractions256 = struct.unpack('b', bytes[8:9])[0] if len(bytes) >= 9 else None

        return {"date": datetime(*(year, month, day, hours, minutes, seconds)), "day_of_week": day_of_week, "fractions256": fractions256}

    @staticmethod
    def create_date_data(date):
        data = struct.pack( 'hbbbbbbbxx', date.year, date.month, date.day, date.hour, date.minute, date.second, date.weekday(), 0 )
        return data

    def _parse_battery_response(self, bytes):
        level = struct.unpack('b', bytes[1:2])[0] if len(bytes) >= 2 else None
        last_level = struct.unpack('b', bytes[19:20])[0] if len(bytes) >= 20 else None
        status = 'normal' if struct.unpack('b', bytes[2:3])[0] == b'0' else "charging"
        datetime_last_charge = self._parse_date(bytes[11:18])
        datetime_last_off = self._parse_date(bytes[3:10])

        res = {
            "status": status,
            "level": level,
            "last_level": last_level,
            "last_level": last_level,
            "last_charge": datetime_last_charge,
            "last_off": datetime_last_off
        }
        return res

    def get_battery_info(self):
        char = self.svc_1.getCharacteristics(UUIDS.CHARACTERISTIC_BATTERY)[0]
        return self._parse_battery_response(char.read())

    def get_current_time(self):
        char = self.svc_1.getCharacteristics(UUIDS.CHARACTERISTIC_CURRENT_TIME)[0]
        return self._parse_date(char.read()[0:9])

    def get_heart_rate_one_time(self):
        # stop continuous
        self._char_heart_ctrl.write(b'\x15\x01\x00', True)
        # stop manual
        self._char_heart_ctrl.write(b'\x15\x02\x00', True)
        # start manual
        self._char_heart_ctrl.write(b'\x15\x02\x01', True)
        res = None
        while not res:
            self.waitForNotifications(self.timeout)
            res = self._get_from_queue(QUEUE_TYPES.HEART)

        # Parse as accelerometer data (x, y axes)
        x, y = struct.unpack('<hh', res[:4])  # Assuming data is in 2x 16-bit integers
        return {'x': x, 'y': y}

    def start_heart_rate_realtime(self, heart_measure_callback):
        char_m = self.svc_heart.getCharacteristics(UUIDS.CHARACTERISTIC_HEART_RATE_MEASURE)[0]
        char_d = char_m.getDescriptors(forUUID=UUIDS.NOTIFICATION_DESCRIPTOR)[0]
        char_ctrl = self.svc_heart.getCharacteristics(UUIDS.CHARACTERISTIC_HEART_RATE_CONTROL)[0]

        self.heart_measure_callback = heart_measure_callback

        # stop heart monitor continuous & manual
        char_ctrl.write(b'\x15\x02\x00', True)
        char_ctrl.write(b'\x15\x01\x00', True)
        # enable notifications
        char_d.write(b'\x01\x00', True)
        # start accelerometer continuous mode
        char_ctrl.write(b'\x15\x01\x01', True)
        t = time.time()
        while True:
            self.waitForNotifications(0.5)
            self._parse_queue()
            # send ping request every 12 sec
            if (time.time() - t) >= 12:
                char_ctrl.write(b'\x16', True)
                t = time.time()

    def stop_realtime(self):
        char_m = self.svc_heart.getCharacteristics(UUIDS.CHARACTERISTIC_HEART_RATE_MEASURE)[0]
        char_d = char_m.getDescriptors(forUUID=UUIDS.NOTIFICATION_DESCRIPTOR)[0]
        char_ctrl = self.svc_heart.getCharacteristics(UUIDS.CHARACTERISTIC_HEART_RATE_CONTROL)[0]

        char_sensor1 = self.svc_1.getCharacteristics(UUIDS.CHARACTERISTIC_HZ)[0]
        char_sens_d1 = char_sensor1.getDescriptors(forUUID=UUIDS.NOTIFICATION_DESCRIPTOR)[0]

        char_sensor2 = self.svc_1.getCharacteristics(UUIDS.CHARACTERISTIC_SENSOR)[0]

        # stop heart monitor continues
        char_ctrl.write(b'\x15\x01\x00', True)
        char_ctrl.write(b'\x15\x01\x00', True)
        # IMO: stop heart monitor notifications
        char_d.write(b'\x00\x00', True)
        # WTF
        char_sensor2.write(b'\x03')
        # IMO: stop notifications from sensors
        char_sens_d1.write(b'\x00\x00', True)

        self.heart_measure_callback = None
        self.heart_raw_callback = None
        self.accel_raw_callback = None