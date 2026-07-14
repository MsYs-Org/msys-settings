# MSYS Settings

## 0.2.11 compact, scrollable Settings pages

The role, HAL, applications, and updates pages now use the same touch-drag
surface as the existing display and radio pages.  HAL, Wi-Fi, and Bluetooth
surface their availability in responsive status cards, and long status text
reflows at phone portrait and landscape widths without extra dependencies.

## 0.2.9 truthful display diagnostics

The Display page now exposes the optional CH347 typed debug contract without
coupling the rest of Settings to that hardware.  It distinguishes configured
FPS, the XCAP capture ceiling, idle FPS, and a provider-reported observation;
a missing counter stays explicitly unavailable instead of being synthesized
from the configured target.  Debug changes report whether they are live or
saved for the next provider start and show the authoritative provider
generation.  The card remains touch-scrollable at 320×480, with the longer
debug action on its own compact row. Changing the sink debug overlay requires
an explicit warning confirmation because a running `:24` provider restarts
briefly and Settings may be reopened by the restored display session.

## 0.2.8 system cards, connectivity, capability-gated rotation, and scrolling

The System page now presents session, component, role, service, and isolation
state as responsive cards.  The complete JSON snapshot remains available under
an explicit diagnostic-details disclosure instead of occupying the normal UI.
Compact pages also accept vertical page drags that start over tables and
read-only detail widgets, while buttons and editors retain exclusive input.

- Native HAL-backed Wi-Fi scanning/connect/disconnect/forget and open networks
- Bluetooth power plus optional Linux Management discovery without D-Bus
- Separate logical layout and physical panel rotation controls
- Responsive card text, touch scrolling, vector icons, and tree scrollbars

## 0.2.5 complete Settings catalog

Appearance choices, display-profile/orientation labels, role migration progress,
HAL availability details, CH347 controls, and package summaries now all use the
same bilingual catalog and built-in English recovery text. Protocol identifiers,
provider IDs, and JSON diagnostics remain unmodified so operators can still
copy them into tooling and logs.

## 0.2.3 self-contained isolated runtime

Release builds vendor the immutable `msys_sdk` source into `files/app/msys_sdk`.
The baseline application sandbox can therefore keep `PYTHONPATH` isolated while
the localized Settings UI still uses the shared, language-neutral mIPC SDK.

## 0.2.1 cold HAL catalog reads

HAL `inventory`, `get_state`, and `list_providers` are idempotent reads but may
need to build the bounded provider catalog on their first call. Settings gives
these calls an explicit 35-second deadline, matching the existing `set_state`
transport margin, instead of inheriting the component channel's general
five-second default. Other RPCs retain their shorter failure detection.

## 0.2.0 responsive Settings and unified i18n

- 320×480 uses a touch-scrollable phone-style card home with prominent Wi-Fi,
  Bluetooth, Display, and on-screen-keyboard entries. Wider displays use a
  searchable Win11-style left navigation rail and spacious card content.
- All navigation, system overview, display, radio-provider state, and common
  status/action wording comes from a validated `msys.i18n.catalog.v1` resource
  (`zh-CN` and `en-US`) through `msys_sdk.i18n`; a built-in English recovery
  catalog keeps Settings usable if packaged resources are damaged.
- Wi-Fi and Bluetooth consume only `org.msys.hal.manager.v1` domains. Missing,
  degraded, or read-only providers are visible states and never fake switches.
- Wi-Fi distinguishes saved profiles from scan-only results, omits PSKs when
  selecting an existing profile, forgets by exact `network_id`, reports whether
  wpa_supplicant persisted a change, and refreshes asynchronous scans after a
  short non-blocking delay. Bluetooth respects and recovers from rfkill hard
  blocks without leaving a false switch state.
- The on-screen-keyboard card calls only the replaceable `role:input-method`
  typed `status`/`toggle` API; it is disabled with a clear message when the role
  has no provider.

### Provider and frontend integration

Settings contains no board-specific Wi-Fi, Bluetooth, or input-method code. A
developer gets UI integration by implementing the existing generic contracts:

- publish a HAL `network` or `bluetooth` domain through
  `org.msys.hal.manager.v1`; inventory supplies devices and `get_state` supplies
  current values plus the exact `mutable` fields. Network command providers use
  the write-only `action` capability (`scan`, `connect`, `disconnect`, `forget`),
  while Bluetooth exposes a power control only when `powered` is mutable;
- provide the exclusive `input-method` role with typed `status({})` and
  `toggle({})` returning `msys.input-method-state.v1` and a boolean `visible`;
- put user-facing text in `files/share/i18n/catalog.json` and use the same
  `msys_sdk.i18n.Translator` API. No global locale daemon or UI framework is
  required.

Missing providers are ordinary, explicit unavailable cards. Frontends never
call `wpa_cli`, BlueZ/D-Bus, or board scripts directly, so a provider can be
replaced without changing this application.

## 0.1.10 supervised startup

The first page load is deferred until the inherited component channel has
completed its handshake and started its single reply/event reader. This
removes the transient `component mIPC reader is not running` page that could
appear on the first frame; standalone mode still loads immediately.

When launched by `msysd`, Settings performs calls and receives broadcasts on
the same inherited private component channel. A single reader dispatches RPC
replies and events, so every privileged operation is checked against the
permissions in this package manifest. The root-only public control socket is
used only by explicit standalone development, not as an in-session ACL bypass.

这是一个真正可安装的 MSYS 应用包。当前前端使用 Python 标准库 Tk，未依赖
systemd、D-Bus、logind、polkit、目标机包管理器或第三方 Python 包。Tk 只是可替换
前端；客户端和模型只依赖语言中立的 JSON/mIPC 地址，因此后续可以用 Qt、Electron、
C/C++ 或其他框架重写界面而不改变系统接口。

## 页面与接口

| 页面 | mIPC 调用 |
| --- | --- |
| System overview | `msys.core.discover/list_components/isolation_capabilities/list_roles` |
| Display | `role:window-manager.get_layout/set_layout` + `msys.core.list_roles` + HAL display domain |
| Desktop appearance | `role:launcher.get_preferences/set_preferences` |
| Apps | `role:install-agent.registry/uninstall` typed RPC |
| Roles | `msys.core.list_roles/select_role/reset_role` |
| HAL | `interface:org.msys.hal.manager.v1.inventory/get_state/set_state/list_providers/select_provider/reset_provider` |
| Updates | `role:update-agent.check_updates/apply_updates` typed RPC |
| Rollback | `role:install-agent.rollback` typed RPC |

### Typed uninstall, update, rollback, and display migration results

Uninstall, update, and rollback buttons wait for a terminal RPC response; a successful
`msys.core.broadcast` acknowledgement is never presented as an installation
success. The three mutating/read operations use these stable addresses:

- `role:update-agent.check_updates`
- `role:update-agent.apply_updates`
- `role:install-agent.registry`
- `role:install-agent.uninstall`
- `role:install-agent.rollback`

The Updates page preserves the full `msys.install-agent-result.v1` envelope,
including its real `ok`, `result`, and per-package `result.errors` fields.
An `msys.install-agent-error.v1` RPC error is shown with its `code`, `message`,
and structured `details`. A partial apply is therefore displayed as a failed
terminal result even though it arrived in a normal mIPC `return` packet.

The Apps page refreshes the authoritative `msys.installed.v1` registry instead
of inferring packages from running components. Selecting Uninstall always opens
a warning confirmation whose default is No. After confirmation it calls
`role:install-agent.uninstall({"package": id})`, waits for the catalog health
gate, preserves the complete typed result/error document on the page, and only
then refreshes the registry. A cancelled confirmation sends no RPC.

The component channel remains subscribed to `msys.update.checked`,
`msys.update.applied`, `msys.update.error`, `msys.install.package_changed`, and
`msys.install.error`. These events form progress/history only; they do not
replace the typed terminal response.

Display-output selection is asynchronous. Settings subscribes to the single
`msys.display.migration` topic and correlates `planned`, `switching`,
`succeeded`, and `rolled-back` records by their positive `id` under schema
`msys.display-migration.v1`. The Roles page keeps the old active provider
visible while the migration is pending. A terminal record refreshes Roles,
Display, and HAL; `rolled-back` exposes the structured error and restores the
provider selector instead of claiming that the requested provider was chosen.
The idempotent `msys.core.display_migration_status({"id": ...})` query provides
the same behavior in standalone debugging when no inherited event channel is
available.

公共 `control.sock` 用于按钮触发的 RPC。组件继承的 `MSYS_CONTROL_FD` 仅用于
hello/ready、订阅更新结果和接收事件，两者不会抢同一个 fd 上的回包。应用不会
`import msys_core`，HAL 或某个职位未安装时只会让对应页面显示结构化的 unavailable
状态，不会导致整个 Settings 退出。

应用声明了 `settings-panel` 的
`system/layout/display/appearance/apps/roles/hal/updates` intent；`layout` 与 `display`
都打开统一的 Display 页面。运行中的实例收到 `msys.activation` 后会直接切换到请求页面。

Display 页面不会假设固定 compositor 或板卡。它分别读取 window-manager 的逻辑布局、
Core 动态返回的 `display-output` role/provider catalog，以及 HAL 的 display domain/device。
任一服务缺失时只禁用对应控件；仍可从该页进入 Roles 或 HAL 管理当前可用的部分。
Core role catalog 按 `list_roles` 当前返回的 `role`、`exclusive`、`preferred`、
`active`、`active_providers` 与 `candidates` 形状校验，不在界面内硬编码候选应用。

Desktop appearance 只使用 launcher 职位契约，不读取或修改某个 Shell 的私有文件。
它管理 `layout`、`wallpaper_color`、`accent_color`、`icon_size`、`show_labels` 与
`sort`，并订阅 `msys.shell.preferences.changed`。因此将 launcher 换成 Qt、Electron
或其他实现后，Settings 页面仍可复用。颜色严格使用 `#RRGGBB`，图标尺寸限制在
40–96，非法响应会以 `SHELL_BAD_RESPONSE` 显示而不会破坏其他页面。
`layout=profile` 在界面中表示 “Profile default”，不会把首次启动时的 mobile/desktop
结果永久钉死；只有显式选择 `auto/mobile/desktop/kiosk` 才覆盖产品 profile。

HAL 页面严格使用 `org.msys.hal.manager.v1`。刷新时会合并 `inventory` 与
`list_providers`，所以没有设备的 domain 仍能显示 unavailable 原因并管理候选
provider。provider 管理方法暂时不可用时，设备清单和状态读取仍可继续工作；反过来，
某个 provider 导致 inventory 暂时失败而 `list_providers` 仍可用时，设备列表会明确显示
unavailable，但 domain/provider 选择与恢复自动选择仍保持可用。

### HAL 0.1.4 provider health 与安全切换

0.1.7 先读取无 domain 的 provider 目录以取得完整 domain 集合，再对每个 domain
调用 `list_providers({"domain":...,"probe":true})`。候选项会显示静态
`capabilities` 和最新 `health`；`unavailable` 或探测失败的候选仍可查看，但 Select
按钮默认禁用。320×480 模式只显示两项能力和简短健康摘要，详细设备状态仍位于下方
JSON 区域，不增加横向控件。

切换与恢复自动选择会携带页面加载时的 `expected_revision`。HAL 返回
`HAL_CONFLICT` 时 Settings 不会以旧页面重试写入，而是重新加载目录。0.1.3 HAL
因不认识 `probe`/`expected_revision` 返回 `HAL_BAD_PAYLOAD` 时，会回退到旧的只读
目录与 last-writer-wins 调用；这一路径把健康显示为 unknown，但保持原有管理能力。
显式 `allow_unavailable` 已保留在 client/model 契约中，当前紧凑 UI 不暴露该操作，
也绝不会把 override 降级为 0.1.3 的无预检写入。

HAL inventory 的正式形状如下：

```json
{
  "devices": [
    {
      "id": "display:primary",
      "name": "Internal display",
      "domain": "display",
      "available": true,
      "mutable": ["orientation"],
      "metadata": {"output": "SPI"},
      "provider": "org.example.hal:display"
    }
  ]
}
```

- `get_state({"id":"display:primary"})` 返回 `state.values` 与 `state.mutable`。
- `set_state({"id":"display:primary","changes":{...}})` 只提交 `mutable` 白名单内真正
  发生变化的字段；篡改只读字段、删除字段或无变化提交会在本地被拒绝。
- `select_provider({"domain":"display","component":"org.example.hal:display","expected_revision":12})`
  固定 provider；`reset_provider({"domain":"display","expected_revision":13})`
  恢复自动优先级选择。
- `HAL_UNAVAILABLE`、`HAL_READ_ONLY` 等结构化错误只显示在 HAL 页面，不会关闭
  Settings 或影响其他页面。

HAL 页面订阅 `msys.hal.changed`，支持强制刷新 inventory/provider catalog 与
`get_state(refresh=true)`。每个 unavailable domain 会显示 status、reason/error；即使
该 domain 没有设备，仍可选择或重置 provider。provider 管理接口不可用时，设备状态
读取仍保持可用。

320×480 等窄屏会切换为顶部七页导航；Display 表单纵向排列，主操作与
Outputs/Display HAL 跳转分成两行，Roles 的 provider 与操作按钮分行，HAL 和 Updates
控件也按触摸宽度堆叠。应用本身不固定 X11 display，
组件环境中没有 `DISPLAY=:24`，`windowing.display` 使用正式值 `inherit`；它继承
MSYS visual session 注入的 `DISPLAY`，独立调试
时才由开发者显式设置该环境变量。

包内含零依赖的 32×32 PPM 图标，并通过 `package.icons` 声明。Tk launcher 可直接
读取它，在 mobile 列表和 desktop 图标网格中无需 Pillow 或占位图标。
字体选择和像素字号来自 `msys_sdk.ui_fonts`；源码不再维护应用私有副本。正式构建
使用下方 overlay 将同一 SDK 放进 `files/app`，因此应用隔离不会依赖平台
`PYTHONPATH`。

0.1.8 在 manifest 中显式声明 Display、Core、role、HAL、update/install RPC 与全部
实际事件订阅权限。它们当前是审计/策略元数据，不被描述为完整安全沙箱。

## 本地验证

从 `G:\Code\MsYs` 执行：

```powershell
wsl env PYTHONDONTWRITEBYTECODE=1 `
  PYTHONPATH=/mnt/g/Code/MsYs/msys-settings/files/app:/mnt/g/Code/MsYs/msys-sdk `
  python3 -m unittest discover -s /mnt/g/Code/MsYs/msys-settings/tests -v

wsl env PYTHONPATH=/mnt/g/Code/MsYs/msys-tools `
  python3 -m msys_tools.dev package validate /mnt/g/Code/MsYs/msys-settings
```

直接连接正在运行的开发会话调 UI：

```powershell
wsl env DISPLAY=:24 MSYS_RUNTIME_DIR=/tmp/msys-main `
  PYTHONDONTWRITEBYTECODE=1 `
  PYTHONPATH=/mnt/g/Code/MsYs/msys-settings/files/app:/mnt/g/Code/MsYs/msys-sdk `
  python3 /mnt/g/Code/MsYs/msys-settings/files/app/main.py
```

这种直接模式没有组件 ready/event 通道，但全部按钮仍通过公共 mIPC 工作。

## 构建、安装和启动

```powershell
wsl env PYTHONPATH=/mnt/g/Code/MsYs/msys-tools `
  python3 -m msys_tools.dev package build /mnt/g/Code/MsYs/msys-settings `
  --output /mnt/g/Code/MsYs/dist --force `
  --overlay /mnt/g/Code/MsYs/msys-sdk/msys_sdk=files/app/msys_sdk

# 使用上一步 JSON 输出中的 archive 路径
wsl env PYTHONPATH=/mnt/g/Code/MsYs/msys-tools `
  python3 -m msys_tools.dev install-archive /mnt/g/Code/MsYs/dist/<archive>.tar.gz

wsl env PYTHONPATH=/mnt/g/Code/MsYs/msys-tools `
  python3 -m msys_tools.dev start-component org.msys.settings:main
```

安装代理会校验 manifest/hashes 并原子切换 installed registry；不调用 apt、pip 或
其他目标机包管理器。应用状态仍使用 MSYS 为第三方包分配的独立 HOME/XDG/runtime
目录，这属于依赖与状态隔离，不宣称是完整安全沙箱。

## 目录

```text
manifest.json                 语言中立安装与启动声明
files/app/main.py             包入口
files/app/msys_settings/ipc.py    mIPC wire client
files/app/msys_settings/client.py 接口地址映射
files/app/msys_settings/model.py  校验、归一化和失败降级
files/app/msys_settings/focus.py  Role/HAL 页面定位的无 GUI 逻辑
files/app/msys_settings/viewport.py 320×480/桌面 viewport 策略
files/app/msys_settings/ui.py     可替换的 Tk 前端
tests/                        无显示服务器依赖的契约、UI 状态与 Python 3.10 语法测试
```

## CH347 typed hardware controls (0.2.9)

When HAL inventory reports `display-output:ch347` with metadata
`control_interface: org.msys.hal.ch347-control.v1`, the HAL page shows a live
status summary and opens a touch-friendly control window. The window exposes:

- driver status, component state, live process count, package version, and
  bounded configuration errors;
- active FPS (1-240) and idle FPS (0-60, never greater than active FPS);
- `get_debug({})` / `set_debug({"enabled":bool})` state with separate FPS,
  XCAP ceiling, runtime application, generation, and nullable capture/panel
  measurements. Cumulative frames are never converted into a pretend sample
  window;
- all boolean and numeric touch-calibration fields from the CH347 v1 contract;
- explicit frame-rate apply, confirmed calibration apply, and confirmed
  supervised output restart actions.

These controls call only
`interface:org.msys.hal.ch347-control.v1`. Every typed call has a 60-second
deadline because calibration writes and restart may stop/start the supervised
display pipeline. Errors stay inline in the control window and never close
Settings. If the interface, driver, or package-owned configuration is
unavailable, mutation controls are disabled while status/refresh remains
useful. The generic `org.msys.hal.manager.v1` inventory, provider selector,
and JSON state editor remain unchanged for every provider, including CH347.

The manifest grants the dedicated typed-interface call permission in addition
to the portable HAL manager permission. It does not add systemd, D-Bus, a
package manager, or a Python package dependency.
