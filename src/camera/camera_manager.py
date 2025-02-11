import cv2
import asyncio
import logging

logger = logging.getLogger(__name__)

class CameraManager:
    def __init__(self):
        self.captures = {}
        self.writers = {}
        self.recording_tasks = {}

    async def start_recording(self, camera_id, video_config, inspection_id):
        """开始录制视频"""
        try:
            index = self.get_camera_index(camera_id)
            cap = cv2.VideoCapture(index)
            if not cap.isOpened():
                raise Exception(f"无法打开摄像头 {camera_id}")

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # Use 'mp4v' codec for MP4
            video_path = f"videos/{inspection_id}_{camera_id}.mp4"
            frame_size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
            out = cv2.VideoWriter(video_path, fourcc, video_config['fps'], frame_size)

            self.captures[camera_id] = cap
            self.writers[camera_id] = out

            logger.info(f"摄像头 {camera_id} 开始录制")

            # Run the recording in a separate task
            self.recording_tasks[camera_id] = asyncio.create_task(self._record(cap, out, camera_id))

        except Exception as e:
            logger.error(f"开始录制失败: {e}")

    async def _record(self, cap, out, camera_id):
        """录制视频的异步任务"""
        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    logger.error("无法读取帧")
                    break
                out.write(frame)
                await asyncio.sleep(0)  # Yield control to the event loop
        finally:
            cap.release()
            out.release()
            cv2.destroyAllWindows()
            logger.info(f"摄像头 {camera_id} 停止录制")

    async def stop_recording(self, camera_id, inspection_id=None):
        """停止录制视频"""
        try:
            task = self.recording_tasks.get(camera_id)
            if task:
                task.cancel()
                await task

            logger.info(f"摄像头 {camera_id} 停止录制")

        except Exception as e:
            logger.error(f"停止录制失败: {e}")

    def get_camera_index(self, camera_id):
        # Implement logic to map camera_id to the correct index
        camera_map = {
            "cam_01": 0,
            "cam_02": 1
        }
        return camera_map.get(camera_id, 0)