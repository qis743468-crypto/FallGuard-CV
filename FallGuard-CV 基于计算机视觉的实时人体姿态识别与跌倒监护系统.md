- 

- # 🛡️ FallGuard-CV: 基于计算机视觉的实时人体姿态识别与跌倒监护系统

  > **FallGuard-CV** 是一款基于 OpenCV 和 MediaPipe 骨骼关键点检测的智能视觉监护系统。系统能够精准分类识别人体日常动作（站立、行走、坐下、起立、弯腰捡东西、躺卧等），并在发生突发性跌倒或失能异常姿态时，实现毫秒级响应、本地声音报警、5秒前后视频自动回溯留存以及微信 PushPlus 抓拍图像实时推送。

  ---

  ## ✨ 核心功能与亮点 (Key Features)

  - 🦴 **全姿态骨骼追踪与动作分类 (Full-Body Pose Estimation)**
    - 基于 MediaPipe 提取人体 33 个骨骼关键点，结合躯干倾角、下坠速度及高宽比（Aspect Ratio）等多维度几何力学算法。
    - 精准区分日常干扰动作（弯腰拾物、坐下起立、蹲下、躺卧）与真实跌倒，大幅降低误报率。

  - 🚨 **分级状态响应机制 (Multi-State Early Warning)**
    - **NORMAL（正常监护）**：绿色 HUD 显示，系统平稳监控。
    - **SUSPECTED（疑似观察）**：黄色 HUD 显示，触发倾角/加速度异常时进入毫秒级二次观察期，自动过滤短暂弯腰或抖动。
    - **FALL_ALERT（摔倒告警）**：红色 HUD 闪烁，自动播放报警音效并启动云端推送与视频备份。

  - 📸 **事件抓拍与 5s 视频回溯留存 (Event Capture & Video Buffer)**
    - 采用**环形帧缓冲区（Ring Buffer）**技术，实时保存报警发生前 3 秒与后 2 秒的高清画面，自动导出 5 秒短视频至本地进行责任溯源。

  - 📲 **微信实时推送与多节点图床 (WeChat Push & Image Hosting)**
    - 接入 PushPlus 微信推送 API，结合多节点公网图床自动上传现场高清抓拍照片，实现远端无延迟警报。

  - 🔒 **隐私防护与双屏交互控制 (Privacy & Interactive HUD)**
    - 提供多档隐私模式切换（原图 / 人脸动态高斯模糊 / 纯数字骨骼模式）。
    - 支持从实时摄像头监控一键无缝跳转至视频离线分析大屏（PyQt5 开发），便于批量回归测试与算法校验。

  ---

  ## 🛠️ 技术栈 (Tech Stack)

  | 模块               | 技术选型                            |
  | :----------------- | :---------------------------------- |
  | **编程语言**       | Python 3.8+                         |
  | **计算机视觉**     | OpenCV, MediaPipe (Pose Estimation) |
  | **GUI 界面**       | PyQt5                               |
  | **数据计算与绘图** | NumPy, Pillow                       |
  | **音频与网络**     | Pygame, Requests, PushPlus API      |

  ---

  ## 🚀 快速开始 (Quick Start)

  ### 1. 克隆项目与安装依赖
  ```bash
  git clone [https://github.com/YourUsername/FallGuard-CV.git](https://github.com/YourUsername/FallGuard-CV.git)
  cd FallGuard-CV
  pip install -r requirements.txt
  



### 	快捷键指南

- `M` 键：切换隐私模式（原图 ↔ 人脸模糊 ↔ 纯黑数字骨骼）
- `T` 键：测试微信推送并切换至 PyQt5 交互大屏
- `Q` 键：安全退出系统

## 📋 预期测试与验证场景 (Testing Matrix)

| **测试场景** | **动作内容**                  | **系统预期反应**                                             |
| ------------ | ----------------------------- | ------------------------------------------------------------ |
| **常规活动** | 快速弯腰捡东西、站立行走      | 识别为 `弯腰/正常`，保持 `NORMAL` 状态 **（无误报）**        |
| **日常休息** | 顺畅坐下、起立或躺在沙发/床上 | 识别为 `坐下/躺卧`，保持 `NORMAL` 状态 **（无误报）**        |
| **突发意外** | 站立/行走中瞬间失重绊倒或仰倒 | 进入 `SUSPECTED` 观察，超时后触发 `FALL_ALERT`，完成抓拍与推送 |