# Android 视觉状态机测试工具

这是一个用于独立 Android 测试 APK 的 ADB/OpenCV 图像识别与交互测试项目。代码按
`截图 -> 模板识别 -> 状态稳定判断 -> 动作规划 -> ADB 执行` 分层，使用 ROI、多尺度
模板匹配、状态重试和未知画面回退点击来验证移动端测试流程。

项目只有一套代码和一份默认配置 `config.json`。默认配置不绑定任何应用：

- `package` 为 `none`；
- `execution_enabled` 保持连续状态机开启；`package: none` 时仍不会发送点击；
- 识别模板、流程、等待时间、点击坐标和状态机参数均已保留。

## 一键启动

双击 `启动测试.bat`，或在 Python 文件关联正确时运行 `start.py`。启动器固定读取
`config.json`；如需临时使用别的配置，可传入 `--config`。

```powershell
Set-Location 'D:\others\TOOLS\wyy_code'
& 'D:\Basement\Miniconda3\envs\jiaoworun\python.exe' .\start.py
```

默认包名为 `none` 时，程序只识别当前画面并打印下一步动作。要在独立测试 APK 中执行
连续状态机，只需要修改 `config.json` 的包名：

```json
{
  "package": "com.example.school.mockads"
}
```

启动前确保该包正处于模拟器前台。执行器会核对配置包名与实际前台窗口；包名仍为
`none`、点击开关关闭或前台包不匹配时不会发送输入。默认配置已经保留
`execution_enabled: true`，因此填入测试包名后，双击 `start.py` 就会恢复连续执行。

## 默认测试流程

状态机保留以下识别与交互逻辑：

1. `home`：向左滑动顶部频道栏。
2. `free_listen`：点击识别到的目标频道。
3. `ready`：点击识别到的测试入口。
4. `ad_interaction`：等待 `minimum_ad_seconds`，点击配置的互动点，再等待
   `ad_post_click_wait_seconds`。
5. `download_prompt`：点击配置的取消位置。
6. `landing`：发送 Android 返回键。
7. `ad_close`：点击识别到的关闭按钮。
8. `limit`：停止流程。

如果从 `ready` 或 `ad_interaction` 进入未知画面，持续 3 秒仍未识别到模板时，状态机只
执行一次屏幕中心回退点击。可重试状态在动作后没有变化时，每 3 秒重试一次，最多执行
3 次，以免无限点击。

## 环境和检查

本机当前使用：

- Python：`D:\Basement\Miniconda3\envs\jiaoworun\python.exe`
- ADB：`D:\others\TOOLS\platform-tools\adb.exe`
- Python 3.11、NumPy、OpenCV

先启动 Android 模拟器并启用 ADB，然后检查环境：

```powershell
& 'D:\Basement\Miniconda3\envs\jiaoworun\python.exe' -m wyy_assist doctor
```

如果没有设备，可按模拟器实际设置连接 ADB 端口，例如：

```powershell
& 'D:\others\TOOLS\platform-tools\adb.exe' connect 127.0.0.1:5555
```

## 模板与校准

`templates/` 中保留了这些状态的参考模板：`home`、`free_listen`、`ready`、
`ad_interaction`、`download_prompt`、`landing`、`ad_close`。模板搜索区域和优先级位于
`config.json`。

测试 APK 画面与现有参考图不同时，应重新校准：

```powershell
& 'D:\Basement\Miniconda3\envs\jiaoworun\python.exe' -m wyy_assist calibrate ready
& 'D:\Basement\Miniconda3\envs\jiaoworun\python.exe' -m wyy_assist calibrate ad_interaction
& 'D:\Basement\Miniconda3\envs\jiaoworun\python.exe' -m wyy_assist calibrate download_prompt
& 'D:\Basement\Miniconda3\envs\jiaoworun\python.exe' -m wyy_assist calibrate ad_close
& 'D:\Basement\Miniconda3\envs\jiaoworun\python.exe' -m wyy_assist calibrate limit
```

在弹出的截图中拖框，按 Enter/Space 保存，按 Esc 取消。同一状态可以保存多个模板；
识别时任一模板达到阈值即可。

其他常用命令：

```powershell
# 保存当前模拟器画面
& 'D:\Basement\Miniconda3\envs\jiaoworun\python.exe' -m wyy_assist screenshot debug\screen.png

# 单次识别当前画面
& 'D:\Basement\Miniconda3\envs\jiaoworun\python.exe' -m wyy_assist recognize

# 只打印动作，不发送输入
& 'D:\Basement\Miniconda3\envs\jiaoworun\python.exe' -m wyy_assist automate

# 在已配置的独立测试 APK 中执行
& 'D:\Basement\Miniconda3\envs\jiaoworun\python.exe' -m wyy_assist automate --execute
```

## 主要配置

- `serial`：多设备时指定 `adb devices` 显示的序列号。
- `package`：独立测试 APK 的真实包名；默认 `none`。
- `execution_enabled`：`start.py` 是否进入连续点击状态机；当前为 `true`。
- `threshold`：模板匹配阈值，默认 `0.86`。
- `template_scales`：多尺度匹配比例。
- `state_priority`：同帧命中多个状态时的优先级。
- `poll_interval_seconds`：截图轮询间隔。
- `consecutive_hits`：确认状态所需的连续命中帧数。
- `minimum_ad_seconds`：互动前等待时间，当前为 17 秒。
- `ad_post_click_wait_seconds`：互动后等待时间，当前为 10 秒。
- `unknown_timeout_seconds`：持续无法识别后的停止时间。
- `ad_interaction_point`：广告测试互动点的归一化坐标。
- `download_cancel_point`：下载测试弹窗取消点的归一化坐标。

## 测试

```powershell
& 'D:\Basement\Miniconda3\envs\jiaoworun\python.exe' -m unittest discover -s tests -v
```

本项目用于你有权控制的测试 APK 和测试环境。第三方应用的条款及其真实广告、奖励或
账户权益不属于本项目的测试范围。
