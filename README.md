# 抖音直播数据采编工作流（社区源码包）

这是一个在 Windows 上运行的本地脚本：通过 Selenium 接管 Chrome，依次读取罗盘直播间列表、场次详情、基础大屏、专业版大屏和千川核心数据页，最后按开播日期生成 Markdown 直播数据笔记。公开版从现有便携工作流整理而来，所有账号、邮箱、SMTP 授权码、浏览器资料和历史采集结果均未打包。

> 这是源码分发包，不含 Python 运行时、ChromeDriver、浏览器登录资料或第三方依赖。下载仓库源码或[源码 ZIP](douyin-live-data-workflow-source-20260930.zip) 后，需要按下文安装和配置。

## 当前能做什么

- 用桌面启动器设置当天／指定日期、输出目录、入口 URL、Chrome 参数，并直接启动流程。
- 从列表页寻找目标日期的已结束场次；同一天多场可依次处理，跨天场次按开播日期归档。
- 采集直播详情、基础大屏、专业版大屏和千川核心数据；将结果写入日期对应的 Markdown 笔记。
- 生成各阶段 JSON、完整流程摘要及时间戳备份。运行失败时可在 `output/mail-drafts/` 留下通知草稿；用户自行配置 SMTP 后可尝试发送邮件。
- `run_portable_check.cmd` 可检查本机的基础环境与必填配置。

## 环境和安装

1. Windows 10/11、Google Chrome、Python 3.12 或更高版本。Python 安装时启用 `py` 启动器或让 `python` 位于 `PATH`。
2. 在仓库目录安装依赖：

   ```powershell
   py -3 -m pip install -r requirements.txt
   ```

   如本机使用 `python` 命令，可将上式中的 `py -3` 改为 `python`。Selenium 可通过 Selenium Manager 获取匹配的 ChromeDriver；若网络环境不允许，请自行下载与 Chrome 版本匹配的驱动，并填写 `chromedriver_path`。
3. 复制样例配置（本地配置已被 `.gitignore` 忽略）：

   ```powershell
   Copy-Item .\config\douyin_workflow_config.example.json .\config\douyin_workflow_config.json
   ```

4. 打开 `config/douyin_workflow_config.json`，至少填写下表中的必填项。也可以双击 `start_desktop_launcher.cmd` 在界面里编辑后保存。

| 配置项 | 填写内容 |
| --- | --- |
| `chrome_start_url` | **必填**。你有权限访问的罗盘起始页面 URL。 |
| `luopan_entry_url` | **必填**。你自己的罗盘入口 URL；脚本不能点击 Chrome 书签栏。 |
| `obsidian_output_path` | **必填**。Markdown 笔记目标目录，可为 Obsidian 仓库内目录。 |
| `chrome_path` | Chrome 程序路径。留空时尝试 Windows 常见安装路径。 |
| `chromedriver_path` | ChromeDriver 路径。留空时由 Selenium Manager 处理。 |
| `chrome_profile_dir` | 专用浏览器配置目录，默认 `.chrome-automation`；该目录不会上传。 |
| `prompt_file` | 个人提示词文件路径，留空即可；当前自动采集与笔记生成流程不读取它。 |
| `failure_email` / `smtp` | 可选失败通知。公开样例全部留空且 SMTP 默认关闭。 |

5. 双击 `run_portable_check.cmd` 查看缺失项。登录你自己的罗盘／千川账号后，双击 `start_full_workflow.cmd`；若要先启动专用 Chrome，可在 PowerShell 中运行：

   ```powershell
   .\run_douyin_full_workflow.ps1 -LaunchChrome
   ```

主要输出位于 `output/`；笔记位于你配置的 `obsidian_output_path`。运行前请确认目标日期和输出目录，避免覆盖同名笔记。

## 当前局限

- 仅按 Windows + Chrome 工作流整理；其他系统未验证。需要自行登录平台并拥有对应页面权限，不能绕过验证码或访问限制。
- 依赖页面结构、按钮文字和 URL 特征。平台改版、账号权限差异或网络波动可能导致阶段失败；部分页面需要用户手动切换并继续。
- 桌面界面主要支持当天和单日操作。配置中虽保留日期范围与定时字段，**本包未提供后台定时调度或自动等待直播结束后重试**；需要自行使用系统任务计划或手动重跑。
- `prompt_file` 当前仅作为配置字段保留，不参与最终 Markdown 内容生成。生成结果仍需人工核对。
- SMTP 为可选功能，需用户填写自己的服务器及邮箱；授权码只在当前启动器进程中使用。不要把真实配置文件、邮箱草稿、浏览器资料或 `output/` 提交到公开仓库。
- 包内没有预置 Python、依赖或 ChromeDriver，因此并非开箱即用的完整便携二进制包。

## 文件说明

- `src/`：采集、阶段控制、笔记写入及桌面启动器源码。
- `config/douyin_workflow_config.example.json`：无个人信息的配置样例。
- `start_desktop_launcher.cmd` / `start_full_workflow.cmd`：双击入口。
- `run_douyin_full_workflow.ps1`：完整工作流入口。
- `first_run_check.ps1`：基础环境检查。

请仅采集自己有权访问的数据，并遵守相关平台规则。
