import cv2
import asyncio
import logging
import datetime

logger = logging.getLogger(__name__)

class CameraManager:
    def __init__(self):
        self.captures = {}
        self.writers = {}
        self.recording_tasks = {}
        # 新增一个标志位字典，用于控制录制循环退出
        self.recording_flags = {}  # { camera_id: True/False }

    async def start_recording(self, camera_id, video_config, inspection_id):
        """开始录制视频"""
        try:
            index = self.get_camera_index(camera_id)
            cap = cv2.VideoCapture(index)
            if not cap.isOpened():
                raise Exception(f"无法打开摄像头 {camera_id}")

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # 使用 'mp4v' 编码
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            video_path = f"videos/{inspection_id}_{camera_id}_{timestamp}.mp4"
            frame_size = (
                int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            )
            out = cv2.VideoWriter(video_path, fourcc, video_config['fps'], frame_size)

            self.captures[camera_id] = cap
            self.writers[camera_id] = out

            # 录制标志位设为 True，表示允许录制循环继续
            self.recording_flags[camera_id] = True

            logger.info(f"摄像头 {camera_id} 开始录制到文件: {video_path}")

            # 异步任务录制视频
            self.recording_tasks[camera_id] = asyncio.create_task(
                self._record(cap, out, camera_id)
            )

        except Exception as e:
            logger.error(f"开始录制失败: {e}")

    async def _record(self, cap, out, camera_id):
        """录制视频的异步任务"""
        try:
            # 只要摄像头打开且标志位为 True，就持续录制
            while cap.isOpened() and self.recording_flags.get(camera_id, False):
                ret, frame = cap.read()
                if not ret:
                    logger.error("无法读取帧")
                    break
                out.write(frame)
                # 让出事件循环，避免阻塞
                await asyncio.sleep(0)
        finally:
            cap.release()
            out.release()
            # 移除 destroyAllWindows()，防止 Windows GUI 库不匹配时报错
            logger.info(f"摄像头 {camera_id} 停止录制")

    async def stop_recording(self, camera_id, inspection_id=None):
        """停止录制视频"""
        try:
            # 将标志位置为 False，录制循环会自然退出
            self.recording_flags[camera_id] = False

            # 等待该摄像头录制任务结束
            task = self.recording_tasks.get(camera_id)
            if task and not task.done():
                await task

            logger.info(f"摄像头 {camera_id} 停止录制")
        except Exception as e:
            logger.error(f"停止录制失败: {e}")

    def get_camera_index(self, camera_id):
        """
        根据摄像头ID映射到对应的摄像头索引
        如果 camera_id 是 '0' 或 '1' 等纯数字字符串，可直接 int 转换使用。
        """
        try:
            return int(camera_id)
        except:
            return 0
