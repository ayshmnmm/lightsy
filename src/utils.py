import time
from threading import Timer

import requests
import tinytuya
from lxml import etree
from requests.auth import HTTPDigestAuth


class EventStream:
    """
    A class to listen to the ISAPI event stream and process each event notification.
    """

    def __init__(self,
                 url: str,
                 username: str,
                 password: str,
                 handle_event: callable,
                 max_retries: int = 3):
        """
        Initializes the EventStream object to listen to the ISAPI event stream and call the handler function for each event.
        :param url: the URL of the event stream
        :param username: the username to use for HTTP Digest Authentication
        :param password: the password to use for HTTP Digest Authentication
        :param handle_event: a function to handle each event notification, must accept event data as a parameter
        :param max_retries: the maximum number of times to retry connecting to the event stream
        """
        self.url = url
        self.username = username
        self.password = password
        self.handle_event = handle_event
        self.max_retries = max_retries

        self.run()

    def run(self):
        """
        Connects to the event stream and processes each event. Automatically reconnects if the connection is lost, retrying
        a maximum of max_retries times before giving up.
        :return: None
        """
        retries = self.max_retries
        while True:
            # noinspection PyBroadException
            try:
                self.start()
                retries = self.max_retries
            except Exception as e:
                print(f"An error occurred: {e}")
                retries -= 1
                if retries == 0:
                    print("Max retries exceeded, giving up.")
                    break
                print(f"Retrying in 1 second ({retries} retries left)")
                time.sleep(1)

    @staticmethod
    def parse_event(event_xml: str) -> dict:
        """
        Parses the XML event notification into a dictionary.
        :param event_xml: the XML event notification
        :return: a dictionary containing the event data
        """
        root = etree.fromstring(event_xml)
        event_data = {element.tag.split('}')[1]: element.text for element in root}
        return event_data

    def start(self):
        """
        Connects to the event stream and processes each event.
        :return: None
        """
        response = requests.get(self.url, auth=HTTPDigestAuth(self.username, self.password), stream=True)
        if response.status_code == 200:
            print("Connected to the event stream")
            constructed_response = ""
            for chunk in response.iter_content():
                constructed_response += chunk.decode("utf-8")
                if constructed_response.endswith("</EventNotificationAlert>"):
                    event = constructed_response[constructed_response.find("<EventNotificationAlert"):]
                    constructed_response = ""
                    self.handle_event(self.parse_event(event))
        else:
            raise Exception(f"Failed to connect to the event stream: {response.status_code}")


class LightControl:
    """
    Control lights using tinytuya.
    """

    def __init__(self, devices: dict, lights: dict):
        """
        Initializes LightControl with the specified devices.
        :param devices: a dictionary of devices to control, each device should be a dictionary with the following keys
        - dev_id: the device ID
        - ip: the IP address of the device
        - local_key: the local key of the device
        - version: the firmware version of the device
        :param lights: a dictionary of lights to control, each light should be a dictionary with the following keys
        - device: the device ID of the light
        - switch: the switch number of the light
        """
        self.device_objects: dict[str, tinytuya.OutletDevice] = {}
        for dev_name, dev_info in devices.items():
            self.device_objects[dev_name] = tinytuya.OutletDevice(dev_id=dev_info["dev_id"],
                                                                  address=dev_info["ip"],
                                                                  local_key=dev_info["local_key"],
                                                                  version=dev_info["version"])

        self.lights = lights

    def _turn_on_switch(self, dev_name: str, switch: int):
        """
        Turns on the specified switch of the specified device.
        :param dev_name: the device ID
        :param switch: the switch number
        :return: None
        """
        self.device_objects[dev_name].set_status(True, switch=switch, nowait=True)

    def _turn_off_switch(self, dev_name: str, switch: int):
        """
        Turns off the specified switch of the specified device.
        :param dev_name: the device ID
        :param switch: the switch number
        :return: None
        """
        self.device_objects[dev_name].set_status(False, switch=switch, nowait=True)

    def _get_switch_status(self, dev_name: str, switch: int) -> bool:
        """
        Gets the status of the specified switch of the specified device.
        :param dev_name: the device ID
        :param switch: the switch number
        :return: the status of the switch
        """
        return self.device_objects[dev_name].status()["dps"][f"{switch}"]

    def turn_on(self, light_name: str):
        """
        Turns on the specified light.
        :param light_name: the name of the light to turn on
        :return: None
        """
        self._turn_on_switch(self.lights[light_name]["device"], self.lights[light_name]["switch"])

    def turn_off(self, light_name: str):
        """
        Turns off the specified light.
        :param light_name: the name of the light to turn off
        :return: None
        """
        self._turn_off_switch(self.lights[light_name]["device"], self.lights[light_name]["switch"])

    def get_status(self, light_name: str) -> bool:
        """
        Gets the status of the specified light.
        :param light_name: the name of the light
        :return: the status of the light. True if on, False if off.
        """
        return self._get_switch_status(self.lights[light_name]["device"], self.lights[light_name]["switch"])


class PresenceLighting:
    """
    Control lights based on motion detection events.
    """

    def __init__(self, light_control: LightControl, light_mapping: list):
        """
        Initializes the PresenceLighting with the initialized LightControl object.
        :param light_control: the LightControl object to use for controlling lights
        :param light_mapping: a list of dictionaries mapping channel ids to lights
        """
        self.lc = light_control

        self.light_mapping = {}
        for mapping in light_mapping:
            for channel in mapping["channels"]:
                if channel not in self.light_mapping:
                    self.light_mapping[channel] = []
                self.light_mapping[channel].extend(mapping["lights"])

        # if duplicate lights are mapped to the same channel, raise an error
        for channel, lights in self.light_mapping.items():
            s = set()
            for light in lights:
                if light["light"] in s:
                    raise ValueError(f"Duplicate light {light['light']} in channel {channel}")
                s.add(light["light"])

        print(f"Light mapping: {self.light_mapping}")
        self.timers: dict[str, Timer | None] = {light["light"]: None for lights in self.light_mapping.values() for light
                                                in lights}

    def handle_event(self, event: dict):
        """
        Turns on all lights associated with the channel that triggered the event and sets a timer to turn them off.
        :param event: the event data
        :return: None
        """
        channel_id = int(event["channelID"])

        if channel_id not in self.light_mapping:
            return

        if event["eventType"] == "VMD":
            motion_military_time = int(event["dateTime"].split("T")[1].replace(":", "")[:4])
            print(f"Motion detected at channel {channel_id} at {motion_military_time}")
            for light in self.light_mapping[channel_id]:
                if light.get("activeTime"):
                    is_active = False
                    for period in light["activeTime"]:
                        start, end = period
                        if start <= motion_military_time <= end:
                            is_active = True
                            self.turn_on(light["light"], light["duration"])
                            break
                    if not is_active:
                        print(f"outside active time for light {light['light']} at channel {channel_id}")
                else:
                    self.turn_on(light["light"], light["duration"])

    def turn_on(self, light_name: str, duration: int = 120):
        """
        Turns on the specified light and sets a timer to turn it off after the specified duration.
        :param light_name: the name of the light
        :param duration: the duration in seconds
        :return: None
        """
        print("attempting to turn on light", light_name)
        if not self.timers[light_name]:
            try:
                self.lc.turn_on(light_name)
            except Exception as e:
                print(f"Error turning on light {light_name}: {e}")
                return
        if duration:
            self.set_timer(light_name, duration)

    def set_timer(self, light_name: str, duration: int):
        """
        Sets a timer to turn off the specified light after the specified duration.
        :param light_name: the name of the light
        :param duration: the duration in seconds
        :return: None
        """
        if self.timers[light_name]:
            self.timers[light_name].cancel()
            print(f"Cancelled previous timer for light {light_name}")
        self.timers[light_name] = Timer(duration, lambda l=light_name: self.turn_off(l))
        self.timers[light_name].start()
        print(f"Set timer for light {light_name} for {duration} seconds")

    def turn_off(self, light_name: str):
        """
        Turns off the specified light.
        :param light_name: the name of the light
        :return: None
        """
        print("Turning off light", light_name)
        self.lc.turn_off(light_name)
        self.timers[light_name] = None
