import asyncio
import json
import logging
import os
import cv2
import datetime
import time
import subprocess
from websockets import connect, exceptions

logger = logging.getLogger(__name__)

class WebSocketClient:
    def __init__(self, device_manager, camera_manager):
        self.device_manager = device_manager
        self.camera_manager = camera_manager
        self.ws = None
        
    async def connect(self):
        """建立 WebSocket 连接"""
        config = self.device_manager.config
        ws_url = config['server']['ws_url']
        
        try:
            logger.info(f"正在连接 WebSocket：{ws_url}")
            self.ws = await connect(ws_url)
            logger.info("WebSocket 连接成功")
            
            # 启动心跳和消息处理任务
            asyncio.create_task(self._heartbeat())
            asyncio.create_task(self._handle_messages())
            
            # 连接建立后上报本地视频和模型信息
            await self.report_video_info()
            await self.report_model_info()
            
        except exceptions.InvalidStatus as e:
            logger.error(f"WebSocket 连接失败: {e}")
        except Exception as e:
            logger.error(f"连接时出现意外错误: {e}")
            
    async def _heartbeat(self):
        """发送心跳包"""
        while True:
            try:
                if self.ws:
                    camera_ids = [device['id'] for device in self.device_manager.config["camera"]["devices"]]
                    heartbeat_message = json.dumps({
                        "cmd": "heartbeat",
                        "device_id": self.device_manager.config["device"]["name"],
                        "device_name": self.device_manager.config["device"]["name"],
                        "device_type": self.device_manager.config["device"]["type"],
                        "camera_ids": camera_ids,
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
                    logger.info(f"收到消息: {message}")
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
        cmd = data.get("cmd")
        if cmd == "start_inspection":
            await self._handle_start_inspection(data)
        elif cmd == "stop_inspection":
            await self._handle_stop_inspection(data)
        elif cmd == "heartbeat_ack":
            logger.info("收到心跳包响应")
        elif cmd == "run_annotation":
            await self._handle_run_annotation(data)
        # 可根据需要增加其他命令处理

    async def _handle_start_inspection(self, data):
        """处理开始巡检命令"""
        try:
            inspection_id = data.get("inspection_id")
            video_config = self.device_manager.config["camera"]["video_config"]
            logger.info(f"开始巡检: {inspection_id}，视频配置: {video_config}")
            camera_devices = self.device_manager.config["camera"]["devices"]
            for camera in camera_devices:
                camera_id = camera['id']
                await self.camera_manager.start_recording(camera_id, video_config, inspection_id=inspection_id)
        except Exception as e:
            logger.error(f"开始巡检命令处理失败: {e}")

    async def _handle_stop_inspection(self, data):
        """处理结束巡检命令"""
        try:
            inspection_id = data.get("inspection_id")
            logger.info(f"结束巡检: {inspection_id}")
            camera_devices = self.device_manager.config["camera"]["devices"]
            for camera in camera_devices:
                camera_id = camera['id']
                await self.camera_manager.stop_recording(camera_id)
        except Exception as e:
            logger.error(f"结束巡检命令处理失败: {e}")

    async def _handle_run_annotation(self, data):
        """处理运行视频标注程序命令"""
        try:
            params = data.get("params", {})
            video_file = params.get("video_file")
            model_file = params.get("model_file")
            if not video_file or not model_file:
                logger.error("run_annotation 缺少视频或模型参数")
                return
            # 构建完整路径，假设视频在本地 videos 目录，模型在 models 目录
            video_path = os.path.abspath(os.path.join("videos", video_file))
            model_path = os.path.abspath(os.path.join("models", model_file))
            logger.info(f"收到 run_annotation 命令：video_path={video_path}, model_path={model_path}")
            
            # 调用标注程序，使用 conda 切换至 yolocode 环境运行 /home/coatcn/workspace/ultralytics/count3.py
            cmd = [
                "conda", "run", "-n", "yolocode", "python",
                "/home/coatcn/workspace/ultralytics/count3.py",
                "--source", video_path,
                "--weights", model_path
            ]
            logger.info(f"执行命令: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)
            logger.info("标注程序运行成功")
        except Exception as e:
            logger.error(f"运行标注程序失败: {e}")

    async def report_video_info(self):
        """扫描本地 videos 文件夹，并上报视频信息"""
        video_folder = "videos"
        videos = []
        if os.path.exists(video_folder):
            for file in os.listdir(video_folder):
                if file.endswith(".mp4") or file.endswith(".avi"):
                    file_path = os.path.join(video_folder, file)
                    file_size = os.path.getsize(file_path)
                    creation_time = datetime.datetime.fromtimestamp(
                        os.path.getctime(file_path)
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    cap = cv2.VideoCapture(file_path)
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    duration = frame_count / fps if fps and fps != 0 else 0
                    cap.release()
                    videos.append({
                        "file_name": file,
                        "file_size": file_size,
                        "duration": duration,
                        "creation_time": creation_time
                    })
        report_message = json.dumps({
            "cmd": "video_info_update",
            "device_id": self.device_manager.config["device"]["name"],
            "video_list": videos
        })
        try:
            await self.ws.send(report_message)
            logger.info(f"上报视频信息: {report_message}")
        except Exception as e:
            logger.error(f"上报视频信息失败: {e}")

    async def report_model_info(self):
        """扫描本地模型文件目录，并上报模型信息"""
        model_folder = self.device_manager.config.get("model_path", "models")
        models = []
        if os.path.exists(model_folder):
            for file in os.listdir(model_folder):
                if file.endswith(".pt"):
                    file_path = os.path.join(model_folder, file)
                    file_size = os.path.getsize(file_path)
                    creation_time = datetime.datetime.fromtimestamp(
                        os.path.getctime(file_path)
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    models.append({
                        "file_name": file,
                        "file_size": file_size,
                        "creation_time": creation_time
                    })
        report_message = json.dumps({
            "cmd": "model_info_update",
            "device_id": self.device_manager.config["device"]["name"],
            "model_list": models
        })
        try:
            await self.ws.send(report_message)
            logger.info(f"上报模型信息: {report_message}")
        except Exception as e:
            logger.error(f"上报模型信息失败: {e}")
