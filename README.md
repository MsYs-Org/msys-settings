# MSYS Settings

## 0.5.3 scroll-first complete native Settings

The production LVGL Settings frontend now scrolls each complete page as one
surface, including its title and controls, so small workareas cannot leave
fixed controls covering long content.  Compact device/provider rows remain
ellipsized at rest and expand in place when selected; explanatory text wraps
inside the vertically scrolling page without adding an idle animation timer.

The migration now restores real role selection, input-method mode selection,
POSIX time-zone choices, logical display profile/insets, physical rotation,
Squeezelite player configuration, system overview, launcher sort/accent and
the contract-backed `navigation_visibility` / `status_visibility` settings.
Every mutation still goes through the existing typed role, HAL or Core API;
missing hardware/providers remain explicitly unavailable.  Navigation style
(`buttons` / `pill`) and both system-bar visibility modes are live launcher
preferences and do not restart X11 or the display provider.

## 0.5.2 bounded native toast overlay

Settings and Software Center now own one persistent C/LVGL toast overlay above
the parsed document.  Repeated messages cancel the previous finite animation
and re-arm one hide timer; missing/invalid objects fail safely instead of
passing a null object into LVGL.  This fixes the native crash observed when a
secondary-page action tried to animate the XML tail object that the target
LVGL XML builder did not instantiate.  The Python bridge remains the mIPC
control-channel owner, while the renderer closes only its parent descriptor
copy after `fork`; there is no restart loop or idle timer.

## 0.5.0 production LVGL Settings

`org.msys.settings:main` is now the launchable, default native LVGL frontend.
The previous Python/Tk implementation is no longer a production Settings
component.  The light Material UI groups status cards on its root page and
uses one touch-scrollable secondary-page contract for real Wi-Fi, Bluetooth,
audio, physical display rotation, input method, removable storage, regional,
software, HAL-provider and CH347 developer controls.  Device actions select
only identifiers returned by their typed role/HAL lists; HAL domains with a
single provider truthfully remain non-switchable.

The root page reads only local regional state and the current logical layout.
Audio, input method, Install Agent, storage, scans, provider probes and CH347
diagnostics are loaded only after the corresponding secondary page is opened.
There is no status polling, fixed FPS redraw or idle animation.  All opening,
press, switch and toast animations are finite LVGL transitions and static
pages return to zero presents after they settle.

Application navigation now enters the requested `settings-panel` directly;
Back returns to the Settings root and is unhandled at the root.  The native
bridge also implements the existing regional provider calls and delegates all
business mutations to `SettingsModel`, without systemd, host D-Bus or a
distribution package manager.

## 0.4.1 dynamic LVGL Software Center

`org.msys.settings:software-center` is now the launchable native C/LVGL
frontend.  Its complete light layout lives in
`files/share/ui/software-center.xml`; installed-package cards are generated
from the validated `msys.installed.v1` registry and remain vertically
scrollable at 320×396.  Package detail and update/recovery are separate pages,
and every long source, path, response, and error label uses word wrapping.

Uninstall, package rollback, update check, and update apply still call only
`SettingsModel`, which in turn uses `role:install-agent` and
`role:update-agent`.  The native UI displays success only after the typed
terminal envelope returns.  Uninstall, rollback, and update application have
an in-process confirmation sheet; neither a broadcast acknowledgement nor a
locally inferred registry change is treated as success.  The configured
update source comes from `MSYS_UPDATE_SOURCE` and an empty source disables the
update actions visibly.

The prior Tk implementation remains available as the non-launchable
`org.msys.settings:software-center-tk` fallback.  The package remains
dependency-free with respect to systemd, host D-Bus, and distribution package
managers.  This change does not modify the display provider or dirty-region
logic.

## 0.4.0 dynamic LVGL Settings

The optional `main-lvgl` frontend now loads its complete light UI from
`files/share/ui/settings.xml` through the shared `msys-ui-lvgl` document API.
The XML owns the home cards, secondary-page layout, wrapping, scrolling,
styles and event declarations. C retains only bounded widget binding and the
existing Python bridge retains all real Wi-Fi, Bluetooth, audio, storage,
regional, application and update business operations. `--watch-ui` enables
developer-only 250 ms file change checks; a parse error keeps the last valid
object tree. Production has no UI polling and static pages remain zero-flush.
The Tk component remains the default fallback while the LVGL frontend is
completed and accepted on hardware.

## 0.3.3 LVGL frontend preview

Settings now has an optional native LVGL provider at
`org.msys.settings:main-lvgl`. The existing Tk component
`org.msys.settings:main` remains the launchable default and explicit fallback;
there is no flag day or forced shell migration. A profile or developer can
start the LVGL component directly, then switch back to `:main` without changing
the business contracts.

The native renderer is intentionally only a frontend. Its small Python bridge
imports the existing `SettingsModel`, `SettingsClient`, mIPC transport, radio
normalizers and regional store. It sends bounded presentation fields over two
anonymous pipes, so Wi-Fi, Bluetooth, audio, display, storage, installed-app
and regional summaries are real model results rather than invented demo state.
Writable Wi-Fi/Bluetooth power, storage auto-mount, audio mute and touch
calibration actions also return through the same model methods.
The native host resolves `/proc/$PPID/exe` before forking the bridge, so the
bridge uses the exact isolated Python that is already running Core; it never
falls back to a target package manager or assumes `/usr/bin/python3` exists.

The 320x396 UI uses two-column phone/Win11-style cards, wrapped secondary-page
text, direct vertical dragging and automatic scrollbars. Animation is limited
to compact title entry, card/button press, switches and a small toast. Static
pages have no timer-driven redraw and the frontend adds no dirty threshold or
full-screen damage aggregation.

Build and probe only the native provider with:

```sh
make -j2
make probe
```

The build statically links the sibling `msys-ui-lvgl` runtime. Its bounded
FreeType provider rasterizes Noto Sans CJK at 14/16/20 px with a 256-glyph LRU;
the offline anti-aliased font remains the automatic fallback. There is no font
daemon or package-manager dependency. The Xvfb probe opens a real
secondary page and performs a touch drag. Missing optional Xvfb tools return
77 rather than installing packages.

## 0.2.27 software center, removable storage, and calibration entry

The package now exposes `org.msys.settings:software-center` as a separately
launchable system application with X11 identity `org.msys.software-center`.
It reuses the existing Apps and Updates pages: package registry, uninstall,
rollback, update check, and update apply still call only the typed install and
update agents. No installer or registry logic is copied into the frontend.

Settings adds a compact, touch-scrollable Storage page backed only by
`role:storage.get_state/refresh/set_config/mount/unmount`. It shows the real
automatic-mount policy, managed mount root, volume state, mount point and
provider errors. The Home page also discovers and starts the optional
`org.msys.touch-calibration:touch-calibration` component through Core; when it
is not installed the card remains visibly unavailable.

The existing Appearance role contract also exposes `wallpaper_path`,
`grid_columns`, `grid_rows`, and `acrylic`. Wallpaper files are absolute,
pre-scaled PPM assets, and acrylic uses a static pre-blurred surface so the
Shell never spends CPU or SPI bandwidth on real-time blur.

The light LVGL Appearance page now reads and mutates the same replaceable
launcher role for `navigation_mode`, `icon_spacing`, folder/large-folder and
motion preferences.  Logical portrait/landscape policy remains owned by
`role:window-manager.set_layout`; `kiosk` is presented as the single-app
layout.  These paths are live updates: Settings never restarts X11 or the SPI
provider and does not own a shadow preferences file.

Launcher package details use this activation contract:

```json
{"component":"org.msys.settings:software-center","activation":{"action":"software-center","name":"details","component":"org.example.app:main"}}
```

Use `name: "uninstall"` for the same preselection followed by the Software
Center's normal confirmation, or `apps` / `updates` to open those root pages.

## 0.2.26 CPU display diagnostics

The configurable CH347 on-screen diagnostics now includes a prominent,
localized CPU-usage item. Its canonical and default persisted item sequence is
`fps`, `dirty`, `bytes`, `cpu`; optional bounding-box and memory details remain
available after those items. Settings validates the complete typed overlay,
canonicalizes selections before sending them to HAL, and accepts success only
from the provider's returned state. The controls remain inside the shared
touch-scrollable Display page and retain the two-column compact layout at
320x480.

## 0.2.25 live session language

The regional page now commits its language through Core's small
`msys.session-preferences.v1` contract and listens for
`msys.session.preferences.changed`. Native system UI can redraw in place and
new applications inherit the same `MSYS_LOCALE`; neither X11 nor the SPI
provider is restarted. The private Settings JSON remains a local UI cache and
standalone fallback, while `/etc/localtime` retains the dependency-free POSIX
time-zone path.

## 0.2.23 touch lists and regional settings

Every long Settings page now uses the same direct-touch scrolling surface,
larger list rows, wrapped text, and full-width compact actions at 320×480.
Language and time zone are grouped on one phone/Win11-style secondary page.
The selected Settings language is persisted as UTF-8 JSON and is applied by
rebuilding the UI immediately; the same state and mutations are available
through the nonexclusive `org.msys.settings.regional.v1` component interface.

Time-zone changes use the standard POSIX zoneinfo file contract only: a
validated entry below `/usr/share/zoneinfo` atomically replaces the
`/etc/localtime` symlink. There is no systemd, D-Bus, package-manager, locale
daemon, or fabricated fallback. If the database or write capability is absent,
the action is disabled and Settings reports the real unavailable reason.

## 0.2.22 capability-gated touch cursor

Display diagnostics now exposes CH347 touch-cursor drawing as an independent
setting.  It uses the optional typed `debug.touch_cursor` receipt and sends
only `cursor_enabled` through `set_debug`; Settings never reads or writes the
driver environment directly.  Older providers keep the switch and apply
action disabled.  A write is reported as successful only when the provider
returns the requested value together with an applied or restart-required
receipt and its authoritative generation.  HAL owns persistence.  The
localized panel remains wrapped and touch-scrollable at 320×480.

## 0.2.19 Bounded interactive repaint

Wi-Fi password edits now change button/entry state only when the effective
state changes. Desktop navigation search uses a short debounce and preserves
already-visible packed buttons. Appearance preview edits reuse existing Canvas
items behind a 50 ms debounce instead of deleting and rebuilding the surface.

## 0.2.18 Truthful Bluetooth discovery

Bluetooth discovery now requests a real 15-second RF window, preserves typed
scan diagnostics, and tells the user to put a headset in pairing mode when a
completed scan finds no devices.

## 0.2.17 Audio event UI hygiene

`msys.audio.changed` is now treated strictly as an invalidation signal. It
refreshes the active Bluetooth or Audio page without leaking the internal topic
into the status bar or overwriting scan and pairing feedback.

## 0.2.16 Bluetooth audio device lifecycle

Bluetooth power stays in the replaceable HAL domain. Discovery, listing,
pairing, connection, disconnection, and forgetting now go only through
`role:audio-manager`, so Settings never starts a competing HAL scan. The
touch-friendly device list shows paired and connected state, and truthfully
disables all lifecycle actions when no Linux Management controller is
registered.

## 0.2.15 replaceable audio controls

Settings now exposes the stable `role:audio-manager` as a responsive Audio
page. It reports private stack health and unavailability reasons, lists real
playback outputs, controls output selection/volume/mute, and edits the bounded
squeezelite enabled/server/name configuration. Bluetooth device management is
linked from the existing Bluetooth page. All audio calls are typed mIPC role calls; PCM and private
provider implementation details never cross Settings.

## 0.2.14 cumulative CH347 dirty-region diagnostics

The Display diagnostics card now shows the latest provider-reported cumulative
dirty-region counters: sent and zero-damage frames, full and large refreshes,
total and most-recent pixel counts, and the most-recent rectangle count. These
values are displayed exactly as cumulative sink counters, never converted into
rates, deltas, or an invented sampling window. Older CH347 providers remain
compatible and show a localized unavailable value for every missing counter.

## 0.2.13 radio scan refresh correctness

Wi-Fi and Bluetooth scan completion now refreshes only the radio page that
started the request.  Leaving a page before its delayed refresh fires no
longer updates another page, and Bluetooth results refresh automatically just
like Wi-Fi results.

## 0.2.12 compact, scrollable Settings pages

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
- Audio calls only the replaceable `role:audio-manager` contract. It displays
  truthful stack/output/mixer/player state and links to the existing Bluetooth
  page for discovery and pairing instead of duplicating device lifecycle UI.

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
- provide the exclusive `audio-manager` role with
  `get_state/select_output/set_volume/set_muted/configure_player`; PCM remains
  on the provider's media transport and never crosses mIPC;
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
| Audio | `role:audio-manager.get_state/select_output/set_volume/set_muted/configure_player` |
| Storage | `role:storage.get_state/refresh/set_config/mount/unmount` |
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
它管理 `layout`、`wallpaper_color`、`accent_color`、`icon_size`、`icon_spacing`、
`navigation_mode`、文件夹/大文件夹、动效、`show_labels` 与 `sort`，并订阅
`msys.shell.preferences.changed`。因此将 launcher 换成 Qt、Electron
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
