import asyncio
import json
import logging
import os
import cv2
import datetime
import time
import asyncio.subprocess
import base64
import aiohttp
import re  # 用于正则解析标注结果
from websockets import connect, exceptions
import aiofiles  
import urllib.parse 
import requests

# 已有常量
CHUNK_SIZE = 32 * 1024
WS_MAX_SIZE = 32 * 1024 * 1024     # 32 MB – 要与服务端保持一致
PING_INTERVAL = 20                 # s
PING_TIMEOUT  = 20                 # s
RETRY_DELAY   = 5                  # s

logger = logging.getLogger(__name__)

class WebSocketClient:
    def __init__(self, device_manager, camera_manager):
        self.device_manager = device_manager
        self.camera_manager = camera_manager
        self.ws = None
        # 用于保存当前正在进行的视频预览任务
        self.current_preview_task = None

    # async def connect(self):
    #     """建立 WebSocket 连接，并输出详细错误信息"""
    #     config = self.device_manager.config
    #     ws_url = config['server']['ws_url']

    #     try:
    #         logger.info(f"正在连接 WebSocket：{ws_url}")
    #         self.ws = await connect(ws_url)
    #         logger.info("WebSocket 连接成功")

    #         # 启动心跳和消息处理任务
    #         asyncio.create_task(self._heartbeat())
    #         asyncio.create_task(self._handle_messages())
    #         # 启动文件变化监控任务：监控 videos、outputs 和模型目录
    #         asyncio.create_task(self.watch_file_changes())

    #     except exceptions.InvalidStatus as e:
    #         logger.error(f"WebSocket 连接失败: Invalid HTTP status {e.status_code} with headers {e.headers}")
    #     except Exception as e:
    #         logger.exception("连接时出现意外错误")
# =====================================
# 连接入口改成“循环重连”版本
# =====================================
    async def connect_forever(self):
        """
        不断尝试连接，任意子任务（心跳/文件监控/消息循环）结束后
        都重新建立连接，不再卡死。
        """
        while True:
            try:
                await self._connect_once()
            except Exception:
                logger.exception("WebSocket 连接失败，%s 秒后重试", RETRY_DELAY)
            await asyncio.sleep(RETRY_DELAY)

    async def _connect_once(self):
        """
        建立一次连接，连接内部并发三个子任务：
          1. _heartbeat()
          2. watch_file_changes()
          3. _handle_messages()
        只要其中任意一个自然结束（正常或异常），就取消剩余任务并退出，
        让 connect_forever 进行下次重连。
        """
        ws_url = self.device_manager.config['server']['ws_url']
        logger.info("Connecting WebSocket: %s", ws_url)

        async with connect(
            ws_url,
            ping_interval=PING_INTERVAL,
            ping_timeout=PING_TIMEOUT,
            max_size=WS_MAX_SIZE
        ) as self.ws:
            logger.info("WebSocket connected")

            # 启动三个子任务
            tasks = [
                asyncio.create_task(self._heartbeat()),
                asyncio.create_task(self.watch_file_changes()),
                asyncio.create_task(self._handle_messages())
            ]

            # 任意一个完成（正常 return 或抛异常）就触发
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED
            )
            # 取消没完成的
            for t in pending:
                t.cancel()
            # 等待取消后的清理
            await asyncio.gather(*pending, return_exceptions=True)

            logger.warning("WebSocket 子任务结束，准备重连")


                
    async def send_heartbeat_message(self):
        """构建并发送心跳包"""
        try:
            if self.ws:
                camera_ids = [str(device['id']) for device in self.device_manager.config["camera"]["devices"]]

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
                # logger.info(f"发送心跳包: {heartbeat_message}")
        except Exception as e:
            logger.exception("心跳发送失败")

    async def _heartbeat(self):
        """定时发送心跳包，断连后退出循环由 connect_forever 重连"""
        while True:
            try:
                await self.send_heartbeat_message()
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                logger.info("_heartbeat 被取消，退出心跳循环")
                break
            except exceptions.ConnectionClosedError:
                logger.warning("心跳发送时 WebSocket 已关闭，退出心跳循环")
                break
            except Exception:
                logger.exception("心跳发送失败，退出心跳循环")
                break

    async def watch_file_changes(self):
        """
        监控 videos/outputs/models 目录变化，
        一旦检测到变化就发一次心跳，遇断连或取消时退出循环。
        """
        directories = ["videos", "outputs", self.device_manager.config.get("model_path", "models")]
        previous = {}
        for d in directories:
            if os.path.exists(d):
                for f in os.listdir(d):
                    try:
                        previous[os.path.join(d, f)] = os.path.getmtime(os.path.join(d, f))
                    except:
                        pass
        while True:
            try:
                await asyncio.sleep(1)
                current = {}
                for d in directories:
                    if os.path.exists(d):
                        for f in os.listdir(d):
                            path = os.path.join(d, f)
                            try:
                                current[path] = os.path.getmtime(path)
                            except:
                                pass
                if current != previous:
                    previous = current
                    logger.info("检测到文件变化，发送一次心跳")
                    await self.send_heartbeat_message()
            except asyncio.CancelledError:
                logger.info("watch_file_changes 被取消，退出文件监控")
                break
            except exceptions.ConnectionClosedError:
                logger.warning("文件监控时 WebSocket 已关闭，退出文件监控")
                break
            except Exception:
                logger.exception("watch_file_changes 出错，继续监控")

    async def _handle_messages(self):
        """
        接收所有服务器 WS 消息，断连或取消后退出循环，
        由 connect_forever 再次建立连接。
        """
        while True:
            try:
                msg = await self.ws.recv()
                if msg is None:
                    logger.warning("服务器端主动关闭 WS，退出消息循环")
                    break
                data = json.loads(msg)
                await self._process_message(data)
            except asyncio.CancelledError:
                logger.info("_handle_messages 被取消，退出消息循环")
                break
            except exceptions.ConnectionClosedError:
                logger.warning("消息接收时 WS 已关闭，退出消息循环")
                break
            except Exception:
                logger.exception("消息处理失败，1s 后重试")
                await asyncio.sleep(1)


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
        elif cmd == "upload_video_start":
            await self._handle_upload_video_start(data)
        elif cmd == "upload_video_chunk":
            await self._handle_upload_video_chunk(data)
        elif cmd == "upload_video_end":
            await self._handle_upload_video_end(data)
        # 新增处理标注结果的消息（若其他终端需要使用）
        elif cmd == "annotation_result":
            logger.info(f"收到标注结果: {data}")
        # 其他命令可以按需扩展
        elif cmd == "upload_outputs":
            await self._handle_upload_outputs(data)
        elif cmd == "upload_outputs_ack":
            logger.info(f"服务端确认 outputs 上传完成: {data.get('filename')}")

    async def _handle_start_inspection(self, data):
        """
        支持单个摄像头或全部摄像头。
        如果 data 中带有 camera_id，则只启动该摄像头的录制；
        否则遍历所有摄像头。
        """
        try:
            inspection_id = data.get("inspection_id")
            camera_id = data.get("camera_id")
            video_config = self.device_manager.config["camera"]["video_config"]
            if camera_id:
                logger.info(f"开始巡检: 设备={inspection_id}, 仅摄像头={camera_id}")
                await self.camera_manager.start_recording(camera_id, video_config, inspection_id=inspection_id)
            else:
                logger.info(f"开始巡检: {inspection_id}，视频配置: {video_config}")
                camera_devices = self.device_manager.config["camera"]["devices"]
                for camera in camera_devices:
                    cam_id = str(camera['id'])
                    await self.camera_manager.start_recording(cam_id, video_config, inspection_id=inspection_id)
        except Exception as e:
            logger.exception("开始巡检命令处理失败")

    async def _handle_stop_inspection(self, data):
        """
        支持单个摄像头或全部摄像头。
        如果 data 中带有 camera_id，则只停止该摄像头的录制；否则遍历所有摄像头。
        """
        try:
            inspection_id = data.get("inspection_id")
            camera_id = data.get("camera_id")
            logger.info(f"结束巡检: 设备={inspection_id}, camera_id={camera_id if camera_id else 'ALL'}")
            if camera_id:
                await self.camera_manager.stop_recording(camera_id)
            else:
                camera_devices = self.device_manager.config["camera"]["devices"]
                for camera in camera_devices:
                    cam_id = str(camera['id'])
                    await self.camera_manager.stop_recording(cam_id)
        except Exception as e:
            logger.exception("结束巡检命令处理失败")

    async def _handle_run_annotation(self, data):
        """处理运行视频标注程序命令，并在标注成功后发送标注结束信息至服务端"""
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
                # 解析标注结果：从输出中匹配每个区域的计数
                counts = self.parse_annotation_result(stdout.decode())
                # 发送标注结果消息到服务端，包含视频文件名和计数结果
                annotation_msg = {
                    "cmd": "annotation_result",
                    "video_file": video_file,
                    "counts": counts
                }
                await self.ws.send(json.dumps(annotation_msg))
                logger.info(f"发送标注结果: {annotation_msg}")
                # 原有上传标注文件的调用已移除
            else:
                logger.error(f"标注程序返回错误码: {proc.returncode}")
                await self.ws.send(json.dumps({"cmd": "annotation_complete", "message": f"标注程序错误，返回码：{proc.returncode}"}))
        except Exception as e:
            logger.exception("运行标注程序失败")
            await self.ws.send(json.dumps({"cmd": "annotation_complete", "message": f"标注程序异常: {str(e)}"}))


    def parse_annotation_result(self, output):
        """
        解析标注程序输出，提取各区域计数。
        假设输出中包含类似：
          "区域: YOLOv8 Polygon Region，计数: 0"
        """
        result = {}
        pattern = re.compile(r"区域:\s*(.+?)，计数:\s*(\d+)")
        for line in output.splitlines():
            match = pattern.search(line)
            if match:
                region = match.group(1)
                count = int(match.group(2))
                result[region] = count
        return result

    async def _handle_start_video_preview(self, data):
        """处理服务端下发的视频预览请求"""
        filename = data.get("filename")
        folder = data.get("folder", "videos")
        if not filename:
            logger.error("start_video_preview 缺少 filename")
            return
        if self.current_preview_task is not None and not self.current_preview_task.done():
            logger.info("取消当前正在进行的视频预览任务")
            self.current_preview_task.cancel()
            try:
                await self.current_preview_task
            except asyncio.CancelledError:
                logger.info("当前视频预览任务已取消")
        self.current_preview_task = asyncio.create_task(self._video_preview_loop(filename, folder))

    async def _video_preview_loop(self, filename: str, folder: str):
        """
        处理服务端下发的 'start_video_preview'，连续发送 JPEG 帧。
        支持任务取消、连接断开时优雅退出，并在 finally 清理任务引用。
        """
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

                ok, jpeg = cv2.imencode('.jpg', frame)
                if not ok:
                    continue

                b64 = base64.b64encode(jpeg.tobytes()).decode('utf-8')
                msg = json.dumps({"cmd": "video_frame", "data": b64})

                try:
                    await self.ws.send(msg)
                except exceptions.ConnectionClosedError:
                    logger.warning("WebSocket 已关闭，停止视频帧发送")
                    break
                except Exception as e:
                    logger.error(f"发送视频帧出错: {e}")
                    break

                await asyncio.sleep(0.033)
        except asyncio.CancelledError:
            logger.info("视频预览任务被取消")
        except Exception as e:
            logger.exception(f"视频预览循环异常: {e}")
        finally:
            cap.release()
            # 发送结束通知（保护式捕获错误）
            try:
                await self.ws.send(json.dumps({"cmd": "video_preview_end"}))
            except exceptions.ConnectionClosedError:
                logger.warning("WebSocket 已关闭，无法发送预览结束通知")
            except Exception as e:
                logger.error(f"发送 video_preview_end 失败: {e}")
            # **清理引用**，保证下次还能新建任务
            self.current_preview_task = None

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
            logger.exception("视频下载失败")

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
        try:
            chunk_data = base64.b64decode(data.get("data"))
            if hasattr(self, "upload_file") and self.upload_file:
                self.upload_file.write(chunk_data)
        except Exception as e:
            logger.exception("处理上传视频块时失败")

    async def _handle_upload_video_end(self, data):
        try:
            if hasattr(self, "upload_file") and self.upload_file:
                self.upload_file.close()
                logger.info(f"上传视频结束: {data.get('filename')}")
                self.upload_file = None
        except Exception as e:
            logger.exception("处理上传视频结束时失败")

# ==========================================================
# 统一推导服务器 HTTP 根地址：新增对 server.url 的兜底处理
# ==========================================================
    def _get_http_base_url(self) -> str:
        """
        ⬇ 解析顺序（前一个满足就返回）：
        1) 明确配置 server.http_url
        2) server.url 已带 http/https 前缀
        3) server.url 仅 IP:PORT —— 自动补 "http://"
        4) 从 ws_url 自动推导（ws→http / wss→https）
        """
        srv_cfg = self.device_manager.config["server"]

        # 1) 明确 http_url
        http_url = srv_cfg.get("http_url")
        if http_url:
            return http_url.rstrip("/")

        # 2-3) server.url
        raw_url = srv_cfg.get("url")
        if raw_url:
            if raw_url.startswith(("http://", "https://")):
                return raw_url.rstrip("/")
            return f"http://{raw_url.rstrip('/')}"

        # 4) fallback: 从 ws_url 推导
        ws_url = srv_cfg["ws_url"]
        parsed = urllib.parse.urlparse(ws_url)
        scheme = "https" if parsed.scheme == "wss" else "http"
        return f"{scheme}://{parsed.netloc}"



    async def _upload_outputs_http(self, filename: str, folder: str = "outputs"):
        """
        通过同步 requests 做文件上传，放到线程池中执行，避免 multipart/form-data 兼容问题。
        """
        base_url   = self._get_http_base_url()
        device_id  = self.device_manager.config["device"]["name"]
        upload_url = f"{base_url}/api/v1/outputs/upload?deviceId={device_id}"
        file_path  = os.path.join(folder, filename)

        if not os.path.exists(file_path):
            logger.error("输出文件不存在: %s", file_path)
            return

        logger.info("开始 HTTP 上传（requests）：%s → %s", file_path, upload_url)

        def sync_upload():
            try:
                with open(file_path, "rb") as f:
                    resp = requests.post(
                        upload_url,
                        files={"file": (filename, f, "video/mp4")},
                        timeout=None
                    )
                return resp.status_code, resp.text
            except Exception as e:
                return None, str(e)

        # 在默认线程池中运行
        status, text = await asyncio.get_event_loop().run_in_executor(None, sync_upload)

        if status == 200:
            logger.info("✔ 上传成功，服务器响应: %s", text)
        elif status is None:
            logger.error("✘ 上传异常: %s", text)
        else:
            logger.error("✘ 上传失败（%s）：%s", status, text)




# ==========================================================
# 收到服务器指令后触发上传
# ==========================================================
    async def _handle_upload_outputs(self, data):
        filename = data.get("filename")
        folder   = data.get("folder", "outputs")
        if not filename:
            logger.error("upload_outputs 缺少文件名")
            return
        logger.info("服务器要求上传 outputs: %s", filename)
        await self._upload_outputs_http(filename, folder)