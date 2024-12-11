DEVICES = {
    'device1_name': {
        'ip': '192.168.x.y',
        'dev_id': 'device1_id',
        'local_key': 'device_local_key',
        'version': 3.0
    }
}

LIGHTS = {
    'light1_name': {
        'device': 'device1_name',  # device name from DEVICES
        'switch': 1  # switch id
    }
}

PRESENCE_LIGHTING_MAPPING = [
    {
        "channels": [1],  # camera channel ids
        "lights": [{
            "light": "light1_name",  # light name from LIGHTS
            "duration": 45,  # duration in seconds for light to stay on after motion is detected
            "activeTime": [(0, 800), (1600, 2400)]  # 24-hour format active times
        }]
    }
]
