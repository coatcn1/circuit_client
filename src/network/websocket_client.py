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
        # 用于保存当前正在进行的视频预览任务
        self.current_preview_task = None

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
            # 启动文件变化监控任务：监控 videos、outputs 和模型目录
            asyncio.create_task(self.watch_file_changes())

        except exceptions.InvalidStatus as e:
            logger.error(f"WebSocket 连接失败: {e}")
        except Exception as e:
            logger.error(f"连接时出现意外错误: {e}")

    async def send_heartbeat_message(self):
        """构建并发送心跳包"""
        try:
            if self.ws:
                camera_ids = [device['id'] for device in self.device_manager.config["camera"]["devices"]]

                # 收集 videos 文件夹视频信息
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

                # 收集 outputs 文件夹视频信息
                outputs_list = []
                outputs_folder = "outputs"
                if os.path.exists(outputs_folder):
                    for file in os.listdir(outputs_folder):
                        if file.endswith(".mp4") or file.endswith(".avi"):
                            file_path = os.path.join(outputs_folder, file)
                            file_size = os.path.getsize(file_path)
                            creation_time = datetime.datetime.fromtimestamp(
                                os.path.getctime(file_path)
                            ).strftime("%Y-%m-%d %H:%M:%S")
                            cap = cv2.VideoCapture(file_path)
                            fps = cap.get(cv2.CAP_PROP_FPS)
                            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                            duration = frame_count / fps if fps and fps != 0 else 0
                            cap.release()
                            outputs_list.append({
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
                    "outputs_list": outputs_list,
                    "model_list": model_list
                })
                await self.ws.send(heartbeat_message)
                logger.info(f"发送心跳包: {heartbeat_message}")
        except Exception as e:
            logger.error(f"心跳发送失败: {e}")

    async def _heartbeat(self):
        """定时发送心跳包"""
        while True:
            try:
                await self.send_heartbeat_message()
            except Exception as e:
                logger.error(f"心跳发送失败: {e}")
            await asyncio.sleep(30)

    async def watch_file_changes(self):
        """
        监控指定目录中的文件变化（增删改）
        目录包括：videos、outputs 以及模型目录
        一旦检测到变化，立即发送一次心跳包
        """
        directories = ["videos", "outputs", self.device_manager.config.get("model_path", "models")]
        previous_snapshot = {}
        for d in directories:
            if os.path.exists(d):
                for file in os.listdir(d):
                    full_path = os.path.join(d, file)
                    try:
                        previous_snapshot[full_path] = os.path.getmtime(full_path)
                    except Exception:
                        pass
        while True:
            await asyncio.sleep(1)
            current_snapshot = {}
            for d in directories:
                if os.path.exists(d):
                    for file in os.listdir(d):
                        full_path = os.path.join(d, file)
                        try:
                            current_snapshot[full_path] = os.path.getmtime(full_path)
                        except Exception:
                            pass
            if current_snapshot != previous_snapshot:
                logger.info("检测到文件变化，立即发送心跳包")
                previous_snapshot = current_snapshot
                await self.send_heartbeat_message()

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
        elif cmd == "start_video_preview":
            await self._handle_start_video_preview(data)
        elif cmd == "video_download":
            await self._handle_video_download(data)
        elif cmd == "delete_video":
            await self._handle_delete_video(data)
        # 新增：处理上传视频命令
        elif cmd == "upload_video_start":
            await self._handle_upload_video_start(data)
        elif cmd == "upload_video_chunk":
            await self._handle_upload_video_chunk(data)
        elif cmd == "upload_video_end":
            await self._handle_upload_video_end(data)

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
        """处理服务端下发的视频预览请求：如果已有预览任务则提前取消，启动新的视频预览任务"""
        filename = data.get("filename")
        folder = data.get("folder", "videos")
        if not filename:
            logger.error("start_video_preview 缺少 filename")
            return
        # 如果已有正在进行的视频预览任务，则取消它
        if self.current_preview_task is not None and not self.current_preview_task.done():
            logger.info("取消当前正在进行的视频预览任务")
            self.current_preview_task.cancel()
            try:
                await self.current_preview_task
            except asyncio.CancelledError:
                logger.info("当前视频预览任务已取消")
        # 启动新的视频预览任务
        self.current_preview_task = asyncio.create_task(self._video_preview_loop(filename, folder))

    async def _video_preview_loop(self, filename, folder):
        """视频预览任务：读取本地视频文件并连续发送 JPEG 帧，支持任务取消"""
        video_path = os.path.abspath(os.path.join(folder, filename))
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
        except asyncio.CancelledError:
            logger.info("视频预览任务被取消")
            raise
        finally:
            cap.release()
            await self.ws.send(json.dumps({"cmd": "video_preview_end"}))

    async def _handle_video_download(self, data):
        """处理服务端下发的视频下载请求：读取本地视频文件并分块发送"""
        filename = data.get("filename")
        folder = data.get("folder", "videos")
        if not filename:
            logger.error("video_download 缺少 filename")
            return
        video_path = os.path.abspath(os.path.join(folder, filename))
        if not os.path.exists(video_path):
            logger.error(f"视频文件不存在: {video_path}")
            return
        try:
            with open(video_path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 64)
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
        folder = data.get("folder", "videos")
        if not filename:
            logger.error("delete_video 缺少 filename")
            return
        video_path = os.path.abspath(os.path.join(folder, filename))
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

    async def _handle_upload_video_start(self, data):
        filename = data.get("filename")
        file_path = os.path.abspath(os.path.join("videos", filename))
        self.upload_file = open(file_path, "wb")
        logger.info(f"开始上传视频: {filename}")

    async def _handle_upload_video_chunk(self, data):
        import base64
        chunk_data = base64.b64decode(data.get("data"))
        if hasattr(self, "upload_file") and self.upload_file:
            self.upload_file.write(chunk_data)

    async def _handle_upload_video_end(self, data):
        if hasattr(self, "upload_file") and self.upload_file:
            self.upload_file.close()
            logger.info(f"上传视频结束: {data.get('filename')}")
            self.upload_file = None
