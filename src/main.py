from os import getenv

from dotenv import load_dotenv

import config
import utils

load_dotenv()

lc = utils.LightControl(devices=config.DEVICES, lights=config.LIGHTS)
pl = utils.PresenceLighting(light_control=lc, light_mapping=config.PRESENCE_LIGHTING_MAPPING)

event_stream = utils.EventStream(url=getenv("ISAPI_EVENT_URL"),
                                 username=getenv("ISAPI_USERNAME"),
                                 password=getenv("ISAPI_PASSWORD"),
                                 handle_event=pl.handle_event)
