import logging
import aiohttp
import yaml
import socket
import uuid
import time
from pathlib import Path

logger = logging.getLogger(__name__)

class DeviceManager:
    def __init__(self):
        self.config = self._load_config()
        self.token = None
        
    def _load_config(self):
        config_path = Path("config/config.yaml")
        with open(config_path) as f:
            return yaml.safe_load(f)
            
    def _get_ip_address(self):
        """获取设备IP地址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
            
    def _get_mac_address(self):
        """获取设备MAC地址"""
        try:
            mac = uuid.getnode()
            return ':'.join(('%012X' % mac)[i:i+2] for i in range(0, 12, 2))
        except:
            return "00:00:00:00:00:00"
