import logging
import aiohttp
import os
from pathlib import Path

logger = logging.getLogger(__name__)

class StorageManager:
    def __init__(self):
        self.upload_chunk_size = 5 * 1024 * 1024  # 5MB
        
    async def upload_video(self, file_path, inspection_id, camera_id, token):
        """上传视频文件"""
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                raise FileNotFoundError(f"文件不存在: {file_path}")
                
            file_size = file_path.stat().st_size
            
            # 初始化上传
            async with aiohttp.ClientSession() as session:
                # 1. 初始化上传
                init_data = {
                    "inspection_id": inspection_id,
                    "camera_id": camera_id,
                    "file_size": file_size
                }
                
                async with session.post(
                    "https://circuit.bjzntd.com/api/v1/inspection/upload/init",
                    headers={"Authorization": f"Bearer {token}"},
                    json=init_data
                ) as response:
                    result = await response.json()
                    if result["code"] != 0:
                        raise Exception(f"初始化上传失败: {result['message']}")
                    
                    upload_id = result["data"]["upload_id"]
                    
                # 2. 分片上传
                with open(file_path, 'rb') as f:
                    chunk_index = 0
                    while True:
                        chunk = f.read(self.upload_chunk_size)
                        if not chunk:
                            break
                            
                        data = aiohttp.FormData()
                        data.add_field('upload_id', upload_id)
                        data.add_field('chunk_index', str(chunk_index))
                        data.add_field('chunk', chunk)
                        
                        async with session.post(
                            "https://circuit.bjzntd.com/api/v1/inspection/upload/chunk",
                            headers={"Authorization": f"Bearer {token}"},
                            data=data
                        ) as response:
                            result = await response.json()
                            if result["code"] != 0:
                                raise Exception(f"上传分片失败: {result['message']}")
                                
                        chunk_index += 1
                        
                # 3. 完成上传
                complete_data = {
                    "upload_id": upload_id
                }
                
                async with session.post(
                    "https://circuit.bjzntd.com/api/v1/inspection/upload/complete",
                    headers={"Authorization": f"Bearer {token}"},
                    json=complete_data
                ) as response:
                    result = await response.json()
                    if result["code"] != 0:
                        raise Exception(f"完成上传失败: {result['message']}")
                        
            logger.info(f"文件 {file_path} 上传成功")
            
        except Exception as e:
            logger.error(f"上传文件失败: {e}")
            raise
            
    def cleanup_storage(self, threshold_mb=1000):
        """清理存储空间"""
        try:
            videos_dir = Path("videos")
            if not videos_dir.exists():
                return
                
            # 获取所有视频文件
            video_files = list(videos_dir.glob("*.mp4"))
            
            # 计算总大小
            total_size = sum(f.stat().st_size for f in video_files)
            
            # 如果超过阈值,删除最旧的文件
            if total_size > threshold_mb * 1024 * 1024:
                video_files.sort(key=lambda x: x.stat().st_mtime)
                while total_size > threshold_mb * 1024 * 1024 and video_files:
                    file_to_delete = video_files.pop(0)
                    total_size -= file_to_delete.stat().st_size
                    file_to_delete.unlink()
                    logger.info(f"删除文件: {file_to_delete}")
                    
        except Exception as e:
            logger.error(f"清理存储空间失败: {e}")
            raise 