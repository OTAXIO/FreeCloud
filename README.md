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

## 每日运行与开机自启

默认配置已开启 `daily_run_enabled`。程序只有在状态机确实识别到 `limit` 后，才会把当天
日期写入项目根目录的 `session.json`：

```json
{
  "last_limit_date": "2026-09-09"
}
```

同一天再次启动时，程序会在打开雷电模拟器之前直接结束；第二天日期不再相同，流程自动
恢复。超时、识别失败、手动按 Ctrl+C 或其他非 `limit` 结果不会写入完成日期，因此不会
误锁当天后续运行。`session.json` 是本机运行状态，已被 Git 忽略。

双击 `安装开机自启.bat` 会更新当前用户的自启配置。Windows 登录启动参考本机
`D:\dmaid\src\function\startup.py`：使用 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
下独立的 `WyyVisualAssistDaily` 项，命令和配置路径均为绝对路径，不修改 DigitMaid 的启动项。
流程在以下两种情况下运行：

1. 当前用户登录 Windows 时，用于每次开机登录后自动执行。
2. 通过保留的 `WyyVisualAssistDaily` 计划任务每日 00:05 检查；错过后尽快补跑。
   该任务不再包含登录触发器，避免与 Run 项重复触发。

两个触发器共用同一套每日判定，因此同一天不会在检测到 `limit` 后重复执行。开机自动
运行时，命令窗口以最小化状态启动；启动日期判断（包括直接跳过）保存在
`logs/autostart-日期时间.log`，包含当前日期、最后完成日期和状态文件完整路径；
每次尝试的 UTF-8 日志保存在 `logs/run-日期时间.log`。
之前的 `logs/autorun.log` 保留作历史记录。如不再需要，双击 `卸载开机自启.bat` 即可删除
本项目的 Run 项和计划任务。脚本更新后重新运行安装脚本，会更新相同的自启配置。

程序未达到 `limit` 就退出、崩溃或被 Ctrl+C 中断时，会弹出置顶窗口：

- **继续**：重新启动执行进程，从模拟器启动检查开始再尝试一遍。
- **放弃**（包括关闭弹窗）：在 `session.control.json` 中记录本次开机标识，本次开机的
  后续自动触发都会跳过；不会写入今日完成日期。手动运行 `start.py` 可再尝试。

开机标识取自 Windows 的 [LastBootUpTime](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-operatingsystem)
（操作系统启动时间）；跨天不会清除“本次开机放弃”，系统重新启动后才失效。Windows
快速启动可能延续内核会话，需要明确刷新开机标识时使用“重新启动”。
正常完成后按原配置关闭模拟器；失败或放弃时保留模拟器现场。手动启动和自动触发共用
单实例限制，避免两份流程同时点击。运行管理进程监督执行进程；若管理进程也被任务管理器
强制结束或 Windows 正在关机，无法当场弹窗，执行进程会随之停止，且不记录为完成。

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

未知页面、状态停滞或点击后未按预期推进，会进入独立的 **30 秒恢复阶段**。正常等待
阶段结束后，优先全屏匹配已有的取消、叉和返回箭头模板；找不到时尝试 Android 返回键，
动作之间至少间隔 3 秒。恢复不会执行未知画面的中心点击、下载或确认。
每次恢复使用固定截止时间，识别到叉或切换弹窗不会重置计时；ADB 命令也受剩余时间限制。
只有连续确认回到首页、免费听或拼图入口等正常页面（且没有识别到覆盖弹窗）才继续主流程。
一直停在原来的故障页面不算恢复。30 秒仍未恢复则报“本次运行失败”，进入继续/放弃弹窗。
可重试状态仍保留原有的 3 次点击尝试，之后交给恢复流程处理。

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

第一次完成推荐菜单点击和频道栏滑动后，如果画面仍稳定识别为 `home`，状态机会单独
检查右上角“免”图标；该图标使用独立缩放范围，不会再被优先级更高的“推荐”文字遮盖。
点击“免”后会等待 2 秒并立即向下滚动页面（ADB 手势方向为向上），滚动完成后才恢复
截图识别。`splash_skip` 和 `launcher_icon` 只在启动导航阶段参与识别，进入 `home` 后的
主状态机完全排除这两个状态。

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
- `close_emulator_on_exit`：完成流程或单帧演练结束后是否关闭模拟器；运行失败时保留现场。
- `daily_run_enabled`：是否启用“当天检测到 limit 后不再运行”的日期判断。
- `daily_state_file`：保存 `last_limit_date` 的本地 JSON 文件，默认 `session.json`。
- `serial`：多设备时指定 `adb devices` 显示的序列号。
- `package`：独立测试 APK 的真实包名；设为 `none` 时只演练。
- `execution_enabled`：`start.py` 是否进入连续点击状态机；当前为 `true`。
- `threshold`：模板匹配阈值，默认 `0.86`。
- `template_scales`：多尺度匹配比例。
- 模板内的 `scales`：仅覆盖该模板的缩放范围；启动图标用它适配桌面图标尺寸。
- `state_priority`：同帧命中多个状态时的优先级。
- `template_roi`：先从参考图中裁出真正要识别的按钮，使用归一化坐标。
- `poll_interval_seconds`：截图轮询间隔。
- `consecutive_hits`：确认状态所需的连续命中帧数。
- `minimum_ad_seconds`：进入广告页后的互动前等待时间，当前为 15 秒。
- `ad_post_click_wait_seconds`：互动后等待时间，当前为 10 秒。
- `unknown_timeout_seconds`：只读监控的未知状态超时；连续执行的恢复阶段固定为 30 秒。
- `ad_interaction_point`：广告测试互动点的归一化坐标。
- `download_cancel_point`：下载测试弹窗取消点的归一化坐标。

## 测试

### 闪退恢复与退出核验

- `start.py` 和 `python -m wyy_assist automate --execute` 共用每日记录及完成后的关闭流程；
  命令行仍只接管已连接的模拟器，不额外打开应用。没有检测到 `limit` 的运行不会被伪记为完成。
- `limit` 仍仅匹配结束文字、使用原阈值及连续确认次数，但搜索整个应用截图，避免页面移动后漏检。
  启动检查同时优先检查 `limit` 和首页标志，避免已完成页面先触发导航。
- 启动、ADB 连接和退出固定到同一个 `emulator_index`；不再随意连接其他在线设备。
  在打开应用前记录 Windows 窗口和虚拟机进程句柄，退出时保留核验这些句柄，
  防止控制台临时丢失 PID 后误报退出。关闭使用雷电 `quit --index`，不是 App 返回键或 `killapp`。

- 任务未完成、前台回到 Android 桌面时，恢复流程会按 `package` 解析应用启动入口并重新打开；
  同一轮恢复最多重开 3 次，总时限仍为 30 秒，超时进入原来的“继续 / 放弃”提示。
  应用重新进入期间可识别开屏跳过；确认回到正常流程后再次禁用开屏跳过。
- 前台判断优先读取当前焦点窗口，避免应用闪退后残留的 `mFocusedApp` 被误认为仍在应用里。
  浏览器等其他页面仍先尝试返回；不会在桌面上反复按返回。
- 结束时只关闭 `emulator_index` 指定的实例。发送 `quit` 后同时检查 `list2`、`isrunning`
  和已记录的进程退出状态，不再把命令返回成功当作模拟器已经退出。
  常规退出会重试；30 秒后只对本实例、路径已核验的残留进程执行兜底结束，最多再等待 10 秒。
  无法核验或仍未退出会报错，不会关闭所有实例或按进程名批量结束。
  状态字段使用[雷电官方命令行接口](https://help.ldmnq.com/docs/LDPlayer-ming-ling-hang-kai-fa-zhe-shi-yong-shuo-ming)。
- 确认 `limit` 后，先写入 `session.shutdown.json` 待关闭标记，再记录当日完成。
  标记只在确认关闭后清除；关闭失败后选择“继续”，会优先补做关闭，今日已完成时不会再次进入应用。
  放弃仍仅禁止本次开机的后续自动运行。未完成或失败的流程不会主动关闭模拟器。

### 自动化回归测试

```powershell
& 'D:\Basement\Miniconda3\envs\jiaoworun\python.exe' -m unittest discover -s tests -v
```

本项目用于你有权控制的测试 APK 和测试环境。第三方应用的条款及其真实广告、奖励或
账户权益不属于本项目的测试范围。
