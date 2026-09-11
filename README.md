# Android 视觉状态机测试工具

这是一个用于独立 Android 测试 APK 的 ADB/OpenCV 图像识别与交互测试项目。代码按
`截图 -> 模板识别 -> 状态稳定判断 -> 动作规划 -> ADB 执行` 分层，使用 ROI、多尺度
模板匹配、状态重试和未知画面回退点击来验证移动端测试流程。

项目只有一套代码和一份默认配置 `config.json`。`package` 用于填写你有权测试的 APK
包名；设置为 `none` 时程序只做单帧识别，不发送点击。识别模板、等待时间、点击坐标和状态机参数集中在这一个配置文件中；
入口导航通过 `start.py` 中的 `NAVIGATION_LOGIC` 选择，步骤顺序定义在 `ENTRY_ROUTES`。

## 一键启动

双击 `启动测试.bat`，或在 Python 文件关联到项目 Conda 环境时运行 `start.py`。程序会
读取 `emulator_path` 并启动雷电模拟器，等待 ADB 截图成功后识别 `launcher_icon`，点击
测试应用图标；若随后识别到 `splash_skip`，则点击“跳过”，再交给原状态机。启动器固定
读取 `config.json`；如需临时使用别的配置，可传入 `--config`。

```powershell
Set-Location 'D:\others\TOOLS\FreeCloud'
& 'D:\Basement\Miniconda3\envs\jiaoworun\python.exe' .\start.py
```

## 手动运行与每日记录

默认配置已开启 `daily_run_enabled`。程序只有在状态机确实识别到 `limit` 后，才会把当天
日期写入项目根目录的 `session.json`：

```json
{
  "last_limit_date": "2026-09-09"
}
```

同一天再次启动时，程序会在打开雷电模拟器之前直接结束；第二天可再次手动启动。超时、识别失败、手动按 Ctrl+C 或其他非 `limit` 结果不会写入完成日期，因此不会
误锁当天后续运行。`session.json` 是本机运行状态，已被 Git 忽略。

程序只通过 `启动测试.bat`、`start.py` 或命令行手动启动。每次执行的 UTF-8 日志保存在
`logs/run-日期时间.log`，单实例限制避免两份流程同时点击。

点击应用图标后 10 秒内仍没有可识别的应用页面，或启动导航超时，会强制停止配置的
App 进程并重新启动一次；重启后仍失败就中断，不再自动重启或进入页面恢复循环。
每次尝试都受 `startup_navigation_timeout_seconds` 限制，包含 ADB 命令耗时。

运行失败后保留模拟器现场，现有的“继续 / 放弃”弹窗允许手动决定下一步：

- **继续**：手动重新启动整个流程。
- **放弃**（包括关闭弹窗）：结束本次运行，不记录今日完成日期，之后仍可手动启动。

管理进程关闭时执行进程也会停止；只有确认达到 `limit` 才记录完成并按配置关闭模拟器。

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

## 入口导航选择

默认在 `start.py` 中设置 `NAVIGATION_LOGIC = 1`，入口顺序集中在同文件的 `ENTRY_ROUTES`：

```python
NAVIGATION_LOGIC = 1
ENTRY_ROUTES = {
    1: ("my_tab", "menu_button", "free_listen_vip"),
    2: ("home", "free_listen"),
}
```

- **逻辑1（默认）**：先识别并点击底部“我的”，再识别并点击“我的”页面右上角菜单，
  最后识别固定文字“免费听VIP歌曲”并点击。底部模板只含“我的”文字；白色菜单模板来自实机截图，
  VIP文字模板不含剩余时长，避免消息红点或倒计时影响。
- **逻辑2（保留）**：原来的推荐菜单重复点击、顶部频道栏横向滑动、点击免费听频道。
  只有把 `NAVIGATION_LOGIC` 改成 `2` 才使用；旧的“免”图标备用入口和进入页面后的纵向滑动均已删除。

模块分工：`startup.py` 负责启动应用、跳过开屏和一次重启；`entry_navigation.py` 负责
入口步骤、顺序识别和有界重试；`automation.py` 负责 `ready` 点击之后的共用广告周期；
`recovery.py` 负责异常页面退出。`start.py:run_workflow` 编排三个阶段，恢复回入口后也由它重走所选路线。

导航同时看到“我的”和菜单时，先点击“我的”。每次点击后重新截图确认后续步骤；已在菜单抽屉或
拼图入口时可接着执行。每个按钮最多尝试三次，整个导航受 `startup_navigation_timeout_seconds`
约束。进入VIP页面后只等待“看视频，点亮拼图”出现，超时中断，不自动滚动或切换路线。

启动、演练、只读识别和异常恢复都使用 `start.py` 所选路线；共用广告循环排除所有入口导航动作。
入口模块确认 `ready` 后返回，不点击该按钮；按钮点击和后续计时、广告互动、取消、返回、关闭及
结束判断由原广告流程继续处理。

## 默认测试流程

状态机保留以下识别与交互逻辑：

1. `launcher_icon`：在雷电启动器中点击识别到的测试应用图标。
2. `splash_skip`：开屏页出现时点击识别到的“跳过”。
3. `my_tab`：识别并点击最下方的“我的”。
4. `menu_button`：识别并点击“我的”页面右上角三横杠菜单。
5. `free_listen_vip`：识别并点击菜单中的“免费听VIP歌曲”。
6. 确认识别到“看视频，点亮拼图”入口，接回共用流程。
7. `ready`：点击识别到的测试入口。
8. `ad_interaction`：以 `minimum_ad_seconds` 和 `ad_post_click_wait_seconds` 为基准，
   每轮两段等待各自随机上下浮动 1 秒，保留一位小数；前段结束后点击互动点，后段结束才处理退出。
9. `download_prompt`：只匹配“取消”按钮并点击识别中心。
10. `landing`：`landing_reference.png` 仅保存重新截取的左上角返回箭头，不含标题；
    只搜索画面左侧 15%、顶部 2%–12% 区域（恢复阶段同样限制），命中后点击箭头中心返回。
11. `ad_close`：点击识别到的关闭按钮。
12. `limit`：停止流程，并在 `close_emulator_on_limit=true` 时关闭雷电实例。

返回模板于 2026-09-11 从 1080×1920 的 ADB 落地页截图裁出，范围为
`x=44..123, y=112..187`，尺寸 80×76。标题栏样本保存在
`tests/fixtures/landing_header.png`，用于验证更换或删除标题后仍只依赖返回箭头。
历史模板生成脚本保留这张实机模板，不再用旧标题栏覆盖它。

连续执行使用独立的广告周期阶段锁。点击入口后，第一次看到广告相关画面（即使模板暂时
无法识别）才开始前置计时并为本轮抽取两段等待时长。默认前段为 14.0～16.0 秒，
后段为 9.0～11.0 秒，步长均为 0.1 秒；时长一经抽取，该轮内保持不变，下一轮重新抽取。
等待完成前，任何关闭图标、下载弹窗或落地页都不会触发退出动作。两段计时完成后才开放退出状态，因此关闭图标的识别优先级无法再
绕过计时。日志显示本轮实际抽取的秒数，异常恢复也使用该时长；设置为 0 时仍不等待。

`limit` 模板只截取“已全部点亮，明天再来”文字行；独立缩放范围也覆盖VIP页面较大的文字布局，不使用人物、
拼图或整块按钮作为判断依据。连续两帧达到独立阈值 `0.88` 后，状态机立即以 `limit`
结束；该判断位于广告计时和所有点击动作之前。启动、入口导航、广告循环及异常恢复都识别同一结束文字；
结束标志固定优先于其他匹配结果，不受 `state_priority` 调整影响。

一键启动或 `automate --execute` 会把任一阶段的 `limit` 结果交给 `start.py` 统一处理：
先停止点击、保存完成与待关闭记录，再关闭配置的雷电实例。只有控制台确认停止且已绑定的窗口、
虚拟机进程全部退出后，才清除待关闭记录并报告正常结束；关闭失败会保留待关闭记录，
下次运行优先重试关闭。默认 `close_emulator_on_limit=true`。单独调用入口导航模块只返回结果，
不会关闭模拟器；实际运行使用上述完整入口。

未知页面、状态停滞或点击后未按预期推进，会进入独立的 **30 秒恢复阶段**。正常等待
阶段结束后，全屏匹配取消和叉，返回箭头仍只搜索左上角；找不到时尝试 Android 返回键，
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

`templates/` 保存启动、底部“我的”、菜单、VIP文字、逻辑2频道入口以及广告流程参考模板。
模板搜索区域和优先级位于 `config.json`；`ready` 保留两种现有布局的识别模板，只用于被动识别，
不会触发滑动。启动图标和开屏跳过只在启动模块参与操作。

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
- `startup_navigation_timeout_seconds`：每次启动图标/跳过页导航尝试的最长时间（包含重启命令）。
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
- `minimum_ad_seconds`：互动前等待基准，支持一位小数，当前为 15.0 秒，实际目标为 14.0～16.0 秒。
- `ad_post_click_wait_seconds`：互动后等待基准，支持一位小数，当前为 10.0 秒，实际目标为 9.0～11.0 秒。
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
  同一轮恢复只允许强制停止后重启一次，5 秒后仍停在桌面就中断；总时限为 30 秒。
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
  放弃即结束本次运行。未完成或失败的流程不会主动关闭模拟器。

### 自动化回归测试

```powershell
& 'D:\Basement\Miniconda3\envs\jiaoworun\python.exe' -m unittest discover -s tests -v
```

本项目用于你有权控制的测试 APK 和测试环境。第三方应用的条款及其真实广告、奖励或
账户权益不属于本项目的测试范围。
