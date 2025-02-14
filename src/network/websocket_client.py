import asyncio
import json
import logging
import os
import cv2
import datetime
import time
import asyncio.subprocess
import base64
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
            
        except exceptions.InvalidStatus as e:
            logger.error(f"WebSocket 连接失败: {e}")
        except Exception as e:
            logger.error(f"连接时出现意外错误: {e}")
            
    async def _heartbeat(self):
        """发送心跳包, 包含视频和模型信息"""
        while True:
            try:
                if self.ws:
                    camera_ids = [device['id'] for device in self.device_manager.config["camera"]["devices"]]
                    
                    # 收集视频信息
                    video_list = []
                    video_folder = "videos"
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
                                video_list.append({
                                    "file_name": file,
                                    "file_size": file_size,
                                    "duration": duration,
                                    "creation_time": creation_time
                                })
                    
                    # 收集模型信息
                    model_list = []
                    model_folder = self.device_manager.config.get("model_path", "models")
                    if os.path.exists(model_folder):
                        for file in os.listdir(model_folder):
                            if file.endswith(".pt"):
                                file_path = os.path.join(model_folder, file)
                                file_size = os.path.getsize(file_path)
                                creation_time = datetime.datetime.fromtimestamp(
                                    os.path.getctime(file_path)
                                ).strftime("%Y-%m-%d %H:%M:%S")
                                model_list.append({
                                    "file_name": file,
                                    "file_size": file_size,
                                    "creation_time": creation_time
                                })
                    
                    heartbeat_message = json.dumps({
                        "cmd": "heartbeat",
                        "device_id": self.device_manager.config["device"]["name"],
                        "device_name": self.device_manager.config["device"]["name"],
                        "device_type": self.device_manager.config["device"]["type"],
                        "camera_ids": camera_ids,
                        "ip_address": self.device_manager._get_ip_address(),
                        "mac_address": self.device_manager._get_mac_address(),
                        "last_heartbeat": int(time.time()),
                        "video_list": video_list,
                        "model_list": model_list
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
        # 新增：处理视频预览、下载和删除命令
        elif cmd == "start_video_preview":
            await self._handle_start_video_preview(data)
        elif cmd == "video_download":
            await self._handle_video_download(data)
        elif cmd == "delete_video":
            await self._handle_delete_video(data)
    
    async def _handle_start_inspection(self, data):
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
            video_path = os.path.abspath(os.path.join("videos", video_file))
            model_path = os.path.abspath(os.path.join("models", model_file))
            logger.info(f"收到 run_annotation 命令：video_path={video_path}, model_path={model_path}")
            
            cmd = [
                "conda", "run", "-n", "yolocode", "python",
                "/home/coatcn/workspace/ultralytics/count3.py",
                "--source", video_path,
                "--weights", model_path
            ]
            logger.info(f"执行命令: {' '.join(cmd)}")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if stdout:
                logger.info(f"标注程序输出: {stdout.decode()}")
            if stderr:
                logger.error(f"标注程序错误: {stderr.decode()}")
            if proc.returncode == 0:
                logger.info("标注程序运行成功")
            else:
                logger.error(f"标注程序返回错误码: {proc.returncode}")
        except Exception as e:
            logger.error(f"运行标注程序失败: {e}")

    async def _handle_start_video_preview(self, data):
        """处理服务端下发的视频预览请求：读取本地视频，连续发送 JPEG 帧"""
        filename = data.get("filename")
        if not filename:
            logger.error("start_video_preview 缺少 filename")
            return
        video_path = os.path.abspath(os.path.join("videos", filename))
        if not os.path.exists(video_path):
            logger.error(f"视频文件不存在: {video_path}")
            return
        cap = cv2.VideoCapture(video_path)
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                ret, jpeg = cv2.imencode('.jpg', frame)
                if not ret:
                    continue
                b64 = base64.b64encode(jpeg.tobytes()).decode('utf-8')
                message = json.dumps({"cmd": "video_frame", "data": b64})
                await self.ws.send(message)
                await asyncio.sleep(0.033)  # 大约30帧每秒
        finally:
            cap.release()
            # 可选：发送结束标记（服务器端可据此停止等待）
            await self.ws.send(json.dumps({"cmd": "video_preview_end"}))

    async def _handle_video_download(self, data):
        """处理服务端下发的视频下载请求：读取本地视频文件并分块发送"""
        filename = data.get("filename")
        if not filename:
            logger.error("video_download 缺少 filename")
            return
        video_path = os.path.abspath(os.path.join("videos", filename))
        if not os.path.exists(video_path):
            logger.error(f"视频文件不存在: {video_path}")
            return
        try:
            with open(video_path, "rb") as f:
                while True:
                    chunk = f.read(1024*64)  # 每块64KB
                    if not chunk:
                        break
                    b64 = base64.b64encode(chunk).decode('utf-8')
                    message = json.dumps({"cmd": "video_download_chunk", "data": b64})
                    await self.ws.send(message)
                    await asyncio.sleep(0.01)
            await self.ws.send(json.dumps({"cmd": "video_download_end"}))
        except Exception as e:
            logger.error(f"视频下载失败: {e}")

    async def _handle_delete_video(self, data):
        """处理服务端下发的删除视频请求：删除本地视频文件并返回结果"""
        filename = data.get("filename")
        if not filename:
            logger.error("delete_video 缺少 filename")
            return
        video_path = os.path.abspath(os.path.join("videos", filename))
        result = {"cmd": "delete_video_ack", "filename": filename}
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
                result["status"] = "success"
            else:
                result["status"] = "file not found"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
        await self.ws.send(json.dumps(result))
