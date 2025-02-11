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
        video_path = "videos"  # 或者从配置中读取路径
        if not os.path.exists(video_path):
            os.makedirs(video_path)
            logger.info(f"创建视频存储目录: {video_path}")
        # 初始化设备管理器
        device_manager = DeviceManager()
        # 初始化摄像头管理器
        camera_manager = CameraManager()
        # 初始化WebSocket客户端
        ws_client = WebSocketClient(device_manager, camera_manager)
        # 初始化存储管理器
        storage_manager = StorageManager()
        # 启动WebSocket连接
        await ws_client.connect()
        
        # 保持程序运行
        while True:
            await asyncio.sleep(1)
            
    except Exception as e:
        logger.error(f"程序异常: {e}")
        raise
if __name__ == "__main__":
    asyncio.run(main()) 