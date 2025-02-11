# Circuit 客户端

## 1. 环境要求
- Python 3.8+
- 树莓派4B
- Ubuntu 22.04 LTS/树莓派OS
- USB摄像头支持
- 32G存储空间

## 2. 依赖安装
```bash
pip install -r requirements.txt
```

## 3. 项目结构
```
circuit_client/
├── config/                 # 配置文件目录
│   └── config.yaml        # 配置文件
├── src/                   # 源代码目录
│   ├── camera/           # 摄像头相关模块
│   ├── network/          # 网络通信模块
│   ├── storage/          # 存储管理模块
│   └── main.py           # 主程序入口
├── logs/                  # 日志目录
├── requirements.txt       # 项目依赖
└── README.md             # 项目说明
```

## 4. 配置说明
配置文件 `config/config.yaml`:
```yaml
server:
  url: https://circuit.bjzntd.com
  ws_url: ws://circuit.bjzntd.com/api/v1/devices/commands

device:
  name: "circuit_device_01"
  type: "raspberry_pi_4b"
  
camera:
  video_format: "mp4"
  bitrate: 2000000  # 2Mbps
  resolution: "1920x1080"
  fps: 30

storage:
  max_space: 20GB  # ��大存储空间
  cleanup_threshold: 80  # 清理阈值(%)

network:
  upload_chunk_size: 5MB
  retry_times: 3
  heartbeat_interval: 30  # 秒
```

## 5. 主要功能
1. 设备管理
   - 开机自启动
   - 设备注册
   - 心跳保活
   
2. 摄像头控制
   - 多摄像头支持
   - 视频录制
   - 参数配置
   
3. 存储管理
   - 本地视频存储
   - 存储空间管理
   - 自动清理策略
   
4. 网络通信
   - WebSocket连接维护
   - 分片上传
   - 断点续传
   
5. 任务管理
   - 巡检任务执行
   - 视频上传任务

## 6. 运行说明
1. 安装依赖：
```bash
pip install -r requirements.txt
```

2. 修改配置文件：
```bash
cp config/config.yaml.example config/config.yaml
# 编辑 config.yaml
```

3. 运行程序：
```bash
python src/main.py
```
