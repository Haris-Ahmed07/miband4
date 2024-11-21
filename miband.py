import sys, os, time
import logging
from bluepy.btle import Peripheral, DefaultDelegate, ADDR_TYPE_RANDOM, ADDR_TYPE_PUBLIC, BTLEException
from constants import UUIDS, AUTH_STATES, ALERT_TYPES, QUEUE_TYPES, MUSICSTATE
import struct
from datetime import datetime, timedelta
from Crypto.Cipher import AES
try:
    import zlib  # For compression (used in firmware/watchface updates)
except ImportError:
    print("zlib module not found. Updating watchface/firmware requires zlib")
try:
    from Queue import Queue, Empty  # Python 2 Queue
except ImportError:
    from queue import Queue, Empty  # Python 3 Queue compatibility
try:
    xrange  # Python 2 range
except NameError:
    xrange = range  # Python 3 compatibility

# Delegate class to handle notifications from the Mi Band
class Delegate(DefaultDelegate):
    def __init__(self, device):
        DefaultDelegate.__init__(self)
        self.device = device  # Reference to the Mi Band device
        self.pkg = 0  # Package counter for activity data

    # Handle BLE notifications
    def handleNotification(self, hnd, data):
        # Handle authentication notifications
        if hnd == self.device._char_auth.getHandle():
            if data[:3] == b'\x10\x01\x01':
                self.device._req_rdn()  # Request random number for authentication
            elif data[:3] == b'\x10\x01\x04':
                self.device.state = AUTH_STATES.KEY_SENDING_FAILED
            elif data[:3] == b'\x10\x02\x01':
                # Process received random number
                random_nr = data[3:]
                self.device._send_enc_rdn(random_nr)
            elif data[:3] == b'\x10\x02\x04':
                self.device.state = AUTH_STATES.REQUEST_RN_ERROR
            elif data[:3] == b'\x10\x03\x01':
                self.device.state = AUTH_STATES.AUTH_OK  # Authentication successful
            elif data[:3] == b'\x10\x03\x04':
                self.device.status = AUTH_STATES.ENCRIPTION_KEY_FAILED
                self.device._send_key()  # Retry sending the key
            else:
                self.device.state = AUTH_STATES.AUTH_FAILED
        
        # Handle heart rate measurement notifications
        elif hnd == self.device._char_heart_measure.getHandle():
            self.device.queue.put((QUEUE_TYPES.HEART, data))
        
        # Handle raw accelerometer and heart data
        elif hnd == 0x38:  # Activity data handle
            if len(data) == 20 and struct.unpack('b', data[0:1])[0] == 1:
                self.device.queue.put((QUEUE_TYPES.RAW_ACCEL, data))
            elif len(data) == 16:
                self.device.queue.put((QUEUE_TYPES.RAW_HEART, data))
        
        # Handle activity data fetching notifications
        elif hnd == self.device._char_fetch.getHandle():
            if data[:3] == b'\x10\x01\x01':
                # Parse the timestamp from the fetched data
                year = struct.unpack("<H", data[7:9])[0]
                month = struct.unpack("b", data[9:10])[0]
                day = struct.unpack("b", data[10:11])[0]
                hour = struct.unpack("b", data[11:12])[0]
                minute = struct.unpack("b", data[12:13])[0]
                self.device.first_timestamp = datetime(year, month, day, hour, minute)
                print("Fetch data from {}-{}-{} {}:{}".format(year, month, day, hour, minute))
                self.pkg = 0  # Reset package counter
                self.device._char_fetch.write(b'\x02', False)
            elif data[:3] == b'\x10\x02\x01':
                # Continue fetching more activity data
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
        
        # Parse activity data into human-readable metrics
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
                        self.device.activity_callback(timestamp, category, intensity, steps, heart_rate)
                    i += 4
       
class miband(Peripheral):
    
    # Predefined commands for requesting random number and sending encrypted key
    _send_rnd_cmd = struct.pack('<2s', b'\x02\x00')
    _send_enc_key = struct.pack('<2s', b'\x03\x00')
    
    def __init__(self, mac_address, key=None, timeout=0.5, debug=False):
        """
        Initializes the Mi Band instance and sets up logging, authentication, and BLE characteristics.
        
        Args:
        - mac_address (str): The MAC address of the Mi Band device.
        - key (bytes): Authentication key for secure pairing (if available).
        - timeout (float): Timeout duration for BLE operations.
        - debug (bool): If True, enables debug-level logging.
        """
        FORMAT = '%(asctime)-15s %(name)s (%(levelname)s) > %(message)s'
        logging.basicConfig(format=FORMAT)
        log_level = logging.WARNING if not debug else logging.DEBUG
        self._log = logging.getLogger(self.__class__.__name__)
        self._log.setLevel(log_level)

        self._log.info('Connecting to ' + mac_address)
        # Initialize BLE connection with the given MAC address
        Peripheral.__init__(self, mac_address, addrType=ADDR_TYPE_PUBLIC)
        self._log.info('Connected')

        # If no key is provided, use medium security level
        if not key:
            self.setSecurityLevel(level="medium")

        # Instance variables
        self.timeout = timeout
        self.mac_address = mac_address
        self.state = None  # Current authentication state
        self.auth_key = key  # Authentication key
        self.queue = Queue()  # Queue to handle BLE data asynchronously

        # Callbacks for heart rate and accelerometer data
        self.heart_measure_callback = None
        self.heart_raw_callback = None
        self.accel_raw_callback = None

        # Get BLE services and characteristics
        self.svc_1 = self.getServiceByUUID(UUIDS.SERVICE_MIBAND1)
        self.svc_2 = self.getServiceByUUID(UUIDS.SERVICE_MIBAND2)
        self.svc_heart = self.getServiceByUUID(UUIDS.SERVICE_HEART_RATE)

        # Authentication characteristics
        self._char_auth = self.svc_2.getCharacteristics(UUIDS.CHARACTERISTIC_AUTH)[0]
        self._desc_auth = self._char_auth.getDescriptors(forUUID=UUIDS.NOTIFICATION_DESCRIPTOR)[0]

        # Heart rate characteristics
        self._char_heart_ctrl = self.svc_heart.getCharacteristics(UUIDS.CHARACTERISTIC_HEART_RATE_CONTROL)[0]
        self._char_heart_measure = self.svc_heart.getCharacteristics(UUIDS.CHARACTERISTIC_HEART_RATE_MEASURE)[0]

        # Data fetch characteristics
        self._char_fetch = self.getCharacteristics(uuid=UUIDS.CHARACTERISTIC_FETCH)[0]
        self._desc_fetch = self._char_fetch.getDescriptors(forUUID=UUIDS.NOTIFICATION_DESCRIPTOR)[0]

        # Activity data characteristics
        self._char_activity = self.getCharacteristics(uuid=UUIDS.CHARACTERISTIC_ACTIVITY_DATA)[0]
        self._desc_activity = self._char_activity.getDescriptors(forUUID=UUIDS.NOTIFICATION_DESCRIPTOR)[0]

        # Chunked transfer and music notifications
        self._char_chunked = self.svc_1.getCharacteristics(UUIDS.CHARACTERISTIC_CHUNKED_TRANSFER)[0]
        self._char_music_notif = self.svc_1.getCharacteristics(UUIDS.CHARACTERISTIC_MUSIC_NOTIFICATION)[0]
        self._desc_music_notif = self._char_music_notif.getDescriptors(forUUID=UUIDS.NOTIFICATION_DESCRIPTOR)[0]

        # Enable authentication notifications
        self._auth_notif(True)
        self.activity_notif_enabled = False

        # Process initial notifications
        self.waitForNotifications(0.1)

        # Set delegate for handling notifications
        self.setDelegate(Delegate(self))
        
    def generateAuthKey(self):
        """
        Generates the authentication key packet for secure pairing.

        Returns:
        - struct: The key packet with appropriate formatting.
        """
        if self.authKey:
            return struct.pack('<18s', b'\x01\x00' + self.auth_key)
        
    def _send_key(self):
            """
            Sends the authentication key to the Mi Band for pairing.
            """
            self._log.info("Sending Key...")
            self._char_auth.write(self._send_my_key)
            self.waitForNotifications(self.timeout)

    def _auth_notif(self, enabled):
        """
        Enables or disables authentication notifications.

        Args:
        - enabled (bool): True to enable notifications, False to disable.
        """
        if enabled:
            self._log.info("Enabling Auth Service notifications...")
            self._desc_auth.write(b"\x01\x00", True)
        elif not enabled:
            self._log.info("Disabling Auth Service notifications...")
            self._desc_auth.write(b"\x00\x00", True)
        else:
            self._log.error("Invalid parameter for Auth Service notifications.")

    def initialize(self):
        """
        Performs the initialization process, including authentication and pairing.

        Returns:
        - bool: True if successfully initialized, False otherwise.
        """
        self._req_rdn()  # Request a random number

        while True:
            self.waitForNotifications(0.1)
            if self.state == AUTH_STATES.AUTH_OK:
                self._log.info('Initialized successfully')
                self._auth_notif(False)
                return True
            elif self.state is None:
                continue  # Wait for notifications
            self._log.error(self.state)
            return False
    
    def _req_rdn(self):
        """
        Requests a random number from the Mi Band as part of the authentication process.
        """
        self._log.info("Requesting random number...")
        self._char_auth.write(self._send_rnd_cmd)
        self.waitForNotifications(self.timeout)
    
    def _send_enc_rdn(self, data):
        """
        Sends an encrypted random number to the Mi Band to complete authentication.

        Args:
        - data (bytes): The random number to encrypt.
        """
        self._log.info("Sending encrypted random number...")
        cmd = self._send_enc_key + self._encrypt(data)
        send_cmd = struct.pack('<18s', cmd)
        self._char_auth.write(send_cmd)
        self.waitForNotifications(self.timeout)

    def _encrypt(self, message):
        """
        Encrypts a message using AES encryption and the stored key.

        Args:
        - message (bytes): The message to encrypt.

        Returns:
        - bytes: The encrypted message.
        """
        aes = AES.new(self.auth_key, AES.MODE_ECB)
        return aes.encrypt(message)
    
    def _get_from_queue(self, _type):
        """
        Retrieves an item from the queue of the specified type.

        Args:
        - _type: The type of data to retrieve.

        Returns:
        - bytes or None: The data if found, otherwise None.
        """
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

    def _parse_raw_heart(self, bytes):
        res = struct.unpack('HHHHHHH', bytes[2:])
        return res

    def get_heart_rate_one_time(self):
        # stop continous
        self._char_heart_ctrl.write(b'\x15\x01\x00', True)
        # stop manual
        self._char_heart_ctrl.write(b'\x15\x02\x00', True)
        # start manual
        self._char_heart_ctrl.write(b'\x15\x02\x01', True)
        res = None
        while not res:
            self.waitForNotifications(self.timeout)
            res = self._get_from_queue(QUEUE_TYPES.HEART)

        rate = struct.unpack('bb', res)[1]
        return rate

    def start_heart_rate_realtime(self, heart_measure_callback):
        char_m = self.svc_heart.getCharacteristics(UUIDS.CHARACTERISTIC_HEART_RATE_MEASURE)[0]
        char_d = char_m.getDescriptors(forUUID=UUIDS.NOTIFICATION_DESCRIPTOR)[0]
        char_ctrl = self.svc_heart.getCharacteristics(UUIDS.CHARACTERISTIC_HEART_RATE_CONTROL)[0]

        self.heart_measure_callback = heart_measure_callback

        # stop heart monitor continues & manual
        char_ctrl.write(b'\x15\x02\x00', True)
        char_ctrl.write(b'\x15\x01\x00', True)
        # enable heart monitor notifications
        char_d.write(b'\x01\x00', True)
        # start hear monitor continues
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