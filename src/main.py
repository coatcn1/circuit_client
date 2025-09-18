import os
import asyncio
import logging
from network.websocket_client import WebSocketClient
from network.device_manager import DeviceManager
from camera.camera_manager import CameraManager
from storage.storage_manager import StorageManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    try:
        # 确保视频存储目录存在
        video_path = "videos"
        if not os.path.exists(video_path):
            os.makedirs(video_path)
            logger.info(f"创建视频目录: {video_path}")
        
        # 初始化各模块（请确保相应模块已实现）
        device_manager = DeviceManager()      # 应返回包含设备配置的对象，配置中需有 device.name、device.type 以及 model_path（如 "models"）
        camera_manager = CameraManager()        # 摄像头操作管理器
        storage_manager = StorageManager()      # 存储管理（如果需要）
        
        ws_client = WebSocketClient(device_manager, camera_manager)
        await ws_client.connect_forever()

        
        # 保持程序运行
        while True:
            await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"程序异常: {e}")
        raise

if __name__ == '__main__':
    asyncio.run(main())
