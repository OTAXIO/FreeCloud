# Android 视觉状态机测试工具

这是一个用于独立 Android 测试 APK 的 ADB/OpenCV 图像识别与交互测试项目。代码按
`截图 -> 模板识别 -> 状态稳定判断 -> 动作规划 -> ADB 执行` 分层，使用 ROI、多尺度
模板匹配、状态重试和未知画面回退点击来验证移动端测试流程。

项目只有一套代码和一份默认配置 `config.json`。`package` 用于填写你有权测试的 APK
包名；设置为 `none` 时程序只做单帧识别，不发送点击。识别模板、流程、等待时间、点击
坐标和状态机参数都集中在这一个配置文件中。

## 一键启动

双击 `启动测试.bat`，或在 Python 文件关联到项目 Conda 环境时运行 `start.py`。程序会
读取 `emulator_path` 并启动雷电模拟器，等待 ADB 截图成功后识别 `launcher_icon`，点击
测试应用图标；若随后识别到 `splash_skip`，则点击“跳过”，再交给原状态机。启动器固定
读取 `config.json`；如需临时使用别的配置，可传入 `--config`。

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

启动图标和开屏跳过属于进入应用前的引导动作，因此只核对点击开关和包名是否已配置；
进入应用后，执行器会继续核对配置包名与实际前台窗口。包名为 `none`、点击开关关闭，
或主流程前台包不匹配时不会发送主流程输入。

## 默认测试流程

状态机保留以下识别与交互逻辑：

1. `launcher_icon`：在雷电启动器中点击识别到的测试应用图标。
2. `splash_skip`：开屏页出现时点击识别到的“跳过”。
3. `home`：向左滑动顶部频道栏。
4. `free_listen`：点击识别到的目标频道。
5. `free_listen_icon`：顶部频道未出现时，点击识别到的“免”备用入口。
6. `free_listen_page`：进入备用页面后向上滑动，使下方拼图入口完整显示。
7. `ready`：点击识别到的测试入口。
8. `ad_interaction`：从广告页开始计时，先等待 `minimum_ad_seconds`，点击配置的
   互动点，再等待 `ad_post_click_wait_seconds`；两段计时完成后才处理退出。
9. `download_prompt`：只匹配“取消”按钮并点击识别中心。
10. `landing`：只匹配左上角返回箭头，然后发送 Android 返回键。
11. `ad_close`：点击识别到的关闭按钮。
12. `limit`：停止流程，并在 `close_emulator_on_limit=true` 时关闭雷电实例。

连续执行使用独立的广告周期阶段锁。点击入口后，第一次看到广告相关画面（即使模板暂时
无法识别）才开始前置计时；前置 15 秒和点击后 10 秒内，任何关闭图标、下载弹窗或落地
页都不会触发退出动作。两段计时完成后才开放退出状态，因此关闭图标的识别优先级无法再
绕过计时。

`limit` 模板当前只截取结束卡片最下方的“已全部点亮，明天再来”文字行，不使用人物、
拼图或整块按钮作为判断依据。连续两帧达到独立阈值 `0.88` 后，状态机立即以 `limit`
结束；该判断位于广告计时和所有点击动作之前。

如果从 `ready` 或 `ad_interaction` 进入未知画面，持续 3 秒仍未识别到模板时，状态机只
执行一次屏幕中心回退点击。可重试状态在动作后没有变化时，每 3 秒重试一次，最多执行
3 次，以免无限点击。

## 环境和检查

本机当前使用：

- Python：`D:\Basement\Miniconda3\envs\jiaoworun\python.exe`
- ADB：`D:\others\TOOLS\platform-tools\adb.exe`
- Python 3.11、NumPy、OpenCV

可先单独检查 ADB 环境：

```powershell
& 'D:\Basement\Miniconda3\envs\jiaoworun\python.exe' -m wyy_assist doctor
```

如果没有设备，可按模拟器实际设置连接 ADB 端口，例如：

```powershell
& 'D:\others\TOOLS\platform-tools\adb.exe' connect 127.0.0.1:5555
```

## 模板与校准

`templates/` 中保留了这些状态的参考模板：`launcher_icon`、`splash_skip`、`home`、
`free_listen`、`free_listen_icon`、`free_listen_page`、`ready`、`ad_interaction`、
`download_prompt`、`landing`、`ad_close` 和 `limit`。模板搜索区域和优先级位于
`config.json`；滚动后的拼图按钮有一份独立 `ready` 模板，不改变原模板。

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

- `emulator_path`：雷电 `dnplayer.exe` 的完整路径。
- `emulator_index`：达到结束状态后要关闭的雷电实例编号。
- `emulator_start_timeout_seconds`：等待 ADB 设备和首张截图的最长时间。
- `startup_navigation_timeout_seconds`：启动图标/跳过页导航的最长时间。
- `close_emulator_on_limit`：识别到 `limit` 后是否关闭配置实例。
- `serial`：多设备时指定 `adb devices` 显示的序列号。
- `package`：独立测试 APK 的真实包名；设为 `none` 时只演练。
- `execution_enabled`：`start.py` 是否进入连续点击状态机；当前为 `true`。
- `threshold`：模板匹配阈值，默认 `0.86`。
- `template_scales`：多尺度匹配比例。
- `state_priority`：同帧命中多个状态时的优先级。
- `template_roi`：先从参考图中裁出真正要识别的按钮，使用归一化坐标。
- `poll_interval_seconds`：截图轮询间隔。
- `consecutive_hits`：确认状态所需的连续命中帧数。
- `minimum_ad_seconds`：进入广告页后的互动前等待时间，当前为 15 秒。
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
