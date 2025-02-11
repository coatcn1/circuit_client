import asyncio
import json
import logging
from websockets import connect, exceptions
import time

logger = logging.getLogger(__name__)

class WebSocketClient:
    def __init__(self, device_manager, camera_manager):
        self.device_manager = device_manager
        self.camera_manager = camera_manager
        self.ws = None
        
    async def connect(self):
        """建立WebSocket连接"""
        config = self.device_manager.config
        ws_url = config['server']['ws_url']
        
        try:
            logger.info(f"Attempting to connect to WebSocket at {ws_url}")
            self.ws = await connect(ws_url)
            logger.info("WebSocket connection established successfully")
            
            # 启动心跳
            asyncio.create_task(self._heartbeat())
            
            # 启动消息处理
            asyncio.create_task(self._handle_messages())
            
        except exceptions.InvalidStatus as e:
            logger.error(f"WebSocket connection failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during WebSocket connection: {e}")
            
    async def _heartbeat(self):
        """发送心跳并包含注册信息"""
        while True:
            try:
                if self.ws:
                    # 获取摄像头 ID 列表
                    camera_ids = [device['id'] for device in self.device_manager.config["camera"]["devices"]]
                    
                    # 构建心跳包，包含摄像头 ID 列表
                    heartbeat_message = json.dumps({
                        "cmd": "heartbeat",
                        "device_id": self.device_manager.config["device"]["name"],
                        "device_name": self.device_manager.config["device"]["name"],
                        "device_type": self.device_manager.config["device"]["type"],
                        "camera_ids": camera_ids,  # 发送摄像头 ID 列表
                        "ip_address": self.device_manager._get_ip_address(),
                        "mac_address": self.device_manager._get_mac_address(),
                        "last_heartbeat": int(time.time())
                    })
                    await self.ws.send(heartbeat_message)
                    logger.info(f"发送心跳包: {heartbeat_message}")
                await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"心跳发送失败: {e}")
                
    async def _handle_messages(self):
        """处理服务器消息"""
        while True:
            try:
                if self.ws:
                    message = await self.ws.recv()
                    logger.info(f"收到消息: {message}")  # 记录原始消息
                    if not message:
                        logger.warning("收到空消息")
                        continue

                    try:
                        data = json.loads(message)
                        await self._process_message(data)
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON解码失败: {e} - 原始消息: {message}")
            except Exception as e:
                logger.error(f"消息处理失败: {e}")
                
    async def _process_message(self, data):
        """处理具体消息"""
        cmd = data.get("cmd")
        if cmd == "start_inspection":
            await self._handle_start_inspection(data)
        elif cmd == "stop_inspection":
            await self._handle_stop_inspection(data)
        elif cmd == "heartbeat_ack":
            # 处理心跳包的响应
            logger.info("收到心跳包响应")
            # 可以在此处解析服务器返回的心跳包响应信息

    async def _handle_start_inspection(self, data):
        """处理开始巡检命令"""
        try:
            inspection_id = data.get("inspection_id")
            
            # 从配置文件中读取视频配置
            video_config = self.device_manager.config["camera"]["video_config"]
            
            logger.info(f"开始巡检: {inspection_id}，视频配置: {video_config}")
            
            # 从配置文件中读取所有摄像头设备
            camera_devices = self.device_manager.config["camera"]["devices"]
            
            # 调用 CameraManager 的 start_recording 方法，启动所有摄像头
            for camera in camera_devices:
                camera_id = camera['id']
                await self.camera_manager.start_recording(camera_id, video_config, inspection_id=inspection_id)
            
        except Exception as e:
            logger.error(f"处理开始巡检命令失败: {e}")

    async def _handle_stop_inspection(self, data):
        """处理结束巡检命令"""
        try:
            inspection_id = data.get("inspection_id")
            
            logger.info(f"结束巡检: {inspection_id}")
            
            # 从配置文件中读取所有摄像头设备
            camera_devices = self.device_manager.config["camera"]["devices"]
            
            # 调用 CameraManager 的 stop_recording 方法，停止所有摄像头
            for camera in camera_devices:
                camera_id = camera['id']
                await self.camera_manager.stop_recording(camera_id)
            
        except Exception as e:
            logger.error(f"处理结束巡检命令失败: {e}")            