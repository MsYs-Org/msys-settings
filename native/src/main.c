#define _POSIX_C_SOURCE 200809L

#include "msys_ui/document.h"
#include "msys_ui/fonts.h"
#include "msys_ui/runtime.h"
#include "msys_ui/theme.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

enum { PANEL_WIFI, PANEL_BLUETOOTH, PANEL_AUDIO, PANEL_DISPLAY,
       PANEL_STORAGE, PANEL_REGIONAL, PANEL_APPS, PANEL_UPDATES,
       PANEL_CALIBRATION, PANEL_SYSTEM, PANEL_COUNT };

enum { APP_MODE_SETTINGS, APP_MODE_SOFTWARE_CENTER };
enum { SOFTWARE_MAX_PACKAGES = 96 };

typedef struct {
    const char *id;
    const char *title;
    const char *note;
    const char *symbol;
    char summary[192];
    char detail[768];
    bool toggle_available;
    bool toggle_value;
    bool available;
} panel_t;

typedef struct {
    char id[160];
    char version[80];
    char path[320];
} software_package_t;

typedef struct {
    msys_ui_runtime_t *runtime;
    msys_ui_surface_t *surface;
    msys_ui_theme_t *theme;
    msys_ui_document_t *document;
    const msys_ui_anim_policy_t *policy;
    panel_t panels[PANEL_COUNT];
    int active_panel;
    lv_obj_t *summary_labels[PANEL_COUNT];
    lv_obj_t *detail_label;
    lv_obj_t *detail_summary;
    lv_obj_t *detail_title;
    lv_obj_t *detail_note;
    lv_obj_t *home_page;
    lv_obj_t *detail_page;
    lv_obj_t *toggle_row;
    lv_obj_t *calibration_button;
    lv_obj_t *toggle;
    lv_obj_t *toast;
    lv_obj_t *toast_label;
    lv_obj_t *status_label;
    bool applying_snapshot;
    bool snapshot_changed;
    char status[192];
    char line_buffer[8192];
    size_t line_used;
    FILE *bridge_input;
    int bridge_output;
    pid_t bridge_pid;
    uint64_t run_until;
    uint64_t next_ui_check;
    const char *ui_path;
    bool watch_ui;
    int mode;
    software_package_t packages[SOFTWARE_MAX_PACKAGES];
    software_package_t pending_packages[SOFTWARE_MAX_PACKAGES];
    size_t package_count;
    size_t package_total;
    size_t pending_package_count;
    size_t pending_package_total;
    bool pending_packages_valid;
    int selected_package;
    char selected_package_id[160];
    bool software_available;
    bool software_busy;
    bool packages_changed;
    char software_status[256];
    char software_source[512];
    char software_operation[1024];
    char software_page[16];
    char software_intent[24];
    char pending_action[32];
    lv_obj_t *software_apps_page;
    lv_obj_t *software_updates_page;
    lv_obj_t *software_detail_page;
    lv_obj_t *software_package_list;
    lv_obj_t *software_apps_status;
    lv_obj_t *software_source_label;
    lv_obj_t *software_update_status;
    lv_obj_t *software_detail_id;
    lv_obj_t *software_detail_version;
    lv_obj_t *software_detail_path;
    lv_obj_t *software_confirm;
    lv_obj_t *software_confirm_title;
    lv_obj_t *software_confirm_text;
    lv_obj_t *software_check_button;
    lv_obj_t *software_apply_button;
    lv_obj_t *software_uninstall_button;
    lv_obj_t *software_rollback_button;
} app_t;

static volatile sig_atomic_t stopping;
static app_t *active_app;

static uint64_t now_ms(void)
{
    struct timespec now;
    (void)clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint64_t)now.tv_sec * 1000U + (uint64_t)now.tv_nsec / 1000000U;
}

static void signal_handler(int signal_number)
{
    (void)signal_number;
    stopping = 1;
}

static void copy_text(char *target, size_t capacity, const char *value)
{
    if(capacity == 0U) return;
    (void)snprintf(target, capacity, "%s", value != NULL ? value : "");
}

static bool replace_text(char *target, size_t capacity, const char *value)
{
    const char *next = value != NULL ? value : "";
    if(strcmp(target, next) == 0) return false;
    copy_text(target, capacity, next);
    return true;
}

static void set_label_text(lv_obj_t *label, const char *value)
{
    const char *current;
    if(label == NULL) return;
    current = lv_label_get_text(label);
    if(current == NULL || strcmp(current, value) != 0) lv_label_set_text(label, value);
}

static panel_t *panel_by_id(app_t *app, const char *id)
{
    int index;
    for(index = 0; index < PANEL_COUNT; index++)
        if(strcmp(app->panels[index].id, id) == 0) return &app->panels[index];
    return NULL;
}

static void init_panels(app_t *app)
{
    static const panel_t defaults[PANEL_COUNT] = {
        {.id="wifi", .title="Wi-Fi", .note="网络、信号与连接", .symbol=LV_SYMBOL_WIFI},
        {.id="bluetooth", .title="蓝牙", .note="设备、配对与音频", .symbol=LV_SYMBOL_BLUETOOTH},
        {.id="audio", .title="音频", .note="输出、音量与播放器", .symbol=LV_SYMBOL_AUDIO},
        {.id="display", .title="显示", .note="布局、方向与屏幕", .symbol=LV_SYMBOL_IMAGE},
        {.id="storage", .title="存储", .note="U 盘、TF 卡与自动挂载", .symbol=LV_SYMBOL_DRIVE},
        {.id="regional", .title="语言和时间", .note="语言、时区与格式", .symbol=LV_SYMBOL_GPS},
        {.id="apps", .title="应用", .note="已安装软件与卸载", .symbol=LV_SYMBOL_LIST},
        {.id="updates", .title="更新", .note="签名更新、恢复与回退", .symbol=LV_SYMBOL_REFRESH},
        {.id="calibration", .title="触摸校准", .note="校准触摸坐标", .symbol=LV_SYMBOL_EDIT},
        {.id="system", .title="系统", .note="组件、输入与运行状态", .symbol=LV_SYMBOL_SETTINGS},
    };
    int index;
    memcpy(app->panels, defaults, sizeof(defaults));
    for(index = 0; index < PANEL_COUNT; index++) {
        copy_text(app->panels[index].summary,
                  sizeof(app->panels[index].summary), "正在读取…");
        copy_text(app->panels[index].detail,
                  sizeof(app->panels[index].detail), "正在读取真实系统状态…");
        app->panels[index].available = true;
    }
    copy_text(app->status, sizeof(app->status), "正在连接 SettingsModel…");
    app->software_available = true;
    app->selected_package = -1;
    copy_text(app->software_status, sizeof(app->software_status),
              "正在读取已安装软件…");
    copy_text(app->software_source, sizeof(app->software_source),
              "未配置更新源");
    copy_text(app->software_operation, sizeof(app->software_operation),
              "尚未执行更新操作。");
    copy_text(app->software_page, sizeof(app->software_page), "apps");
}

static void hide_toast_cb(lv_timer_t *timer)
{
    app_t *app = lv_timer_get_user_data(timer);
    if(app != NULL && app->toast != NULL)
        msys_ui_animate_toast(app->toast, app->policy, false);
    lv_timer_delete(timer);
}

static void show_toast(app_t *app, const char *message)
{
    set_label_text(app->toast_label, message);
    msys_ui_animate_toast(app->toast, app->policy, true);
    (void)lv_timer_create(hide_toast_cb, 1800U, app);
}

static void update_visible(app_t *app);

static void send_bridge(app_t *app, const char *command, const char *name,
                        const char *value)
{
    if(app->bridge_input == NULL) {
        show_toast(app, "快照模式：操作未发送");
        return;
    }
    if(fprintf(app->bridge_input, "%s\t%s\t%s\n", command,
               name != NULL ? name : "", value != NULL ? value : "") < 0 ||
       fflush(app->bridge_input) != 0) {
        show_toast(app, "SettingsModel 通道不可用");
    }
}

static const char *toggle_action(const panel_t *panel)
{
    if(strcmp(panel->id, "wifi") == 0) return "wifi_toggle";
    if(strcmp(panel->id, "bluetooth") == 0) return "bluetooth_toggle";
    if(strcmp(panel->id, "storage") == 0) return "storage_toggle";
    if(strcmp(panel->id, "audio") == 0) return "audio_toggle";
    return NULL;
}

static const char *toggle_label(const panel_t *panel)
{
    if(strcmp(panel->id, "storage") == 0) return "自动挂载";
    if(strcmp(panel->id, "audio") == 0) return "静音";
    return "启用";
}

static lv_obj_t *ui_object(app_t *app, const char *name)
{
    return msys_ui_document_find(app->document, name);
}

static void xml_press_event(lv_event_t *event)
{
    lv_event_code_t code;
    lv_obj_t *object;
    if(active_app == NULL) return;
    code = lv_event_get_code(event);
    object = lv_event_get_current_target(event);
    if(code == LV_EVENT_PRESSED)
        msys_ui_animate_press(object, active_app->policy, true);
    else if(code == LV_EVENT_RELEASED || code == LV_EVENT_PRESS_LOST)
        msys_ui_animate_press(object, active_app->policy, false);
}

static void xml_navigate_event(lv_event_t *event)
{
    const char *id = lv_event_get_user_data(event);
    panel_t *panel;
    if(active_app == NULL || id == NULL) return;
    panel = panel_by_id(active_app, id);
    if(panel == NULL) return;
    active_app->active_panel = (int)(panel - active_app->panels);
    fprintf(stderr, "settings-lvgl: page=%s\n", panel->id);
    update_visible(active_app);
    if(active_app->detail_title != NULL)
        msys_ui_animate_opening(active_app->detail_title, active_app->policy);
}

static void xml_back_event(lv_event_t *event)
{
    (void)event;
    if(active_app == NULL) return;
    active_app->active_panel = -1;
    fprintf(stderr, "settings-lvgl: page=home\n");
    update_visible(active_app);
}

static void xml_toggle_event(lv_event_t *event)
{
    panel_t *panel;
    const char *action;
    if(active_app == NULL || active_app->active_panel < 0 ||
       active_app->applying_snapshot) return;
    panel = &active_app->panels[active_app->active_panel];
    action = toggle_action(panel);
    if(action == NULL) return;
    panel->toggle_value = lv_obj_has_state(active_app->toggle, LV_STATE_CHECKED);
    send_bridge(active_app, "ACTION", action,
                panel->toggle_value ? "1" : "0");
    show_toast(active_app, "正在应用…");
    (void)event;
}

static void xml_refresh_event(lv_event_t *event)
{
    if(active_app == NULL) return;
    send_bridge(active_app, "REFRESH",
                active_app->active_panel >= 0
                    ? active_app->panels[active_app->active_panel].id : "all",
                "");
    show_toast(active_app, "正在刷新真实状态…");
    (void)event;
}

static void xml_calibration_event(lv_event_t *event)
{
    if(active_app == NULL) return;
    send_bridge(active_app, "ACTION", "calibration_start", "1");
    show_toast(active_app, "正在启动触摸校准…");
    (void)event;
}

static void software_update_visible(app_t *app);
static void software_show_confirm(app_t *app, const char *action);

static void software_set_disabled(lv_obj_t *object, bool disabled)
{
    if(object == NULL) return;
    if(disabled) lv_obj_add_state(object, LV_STATE_DISABLED);
    else lv_obj_remove_state(object, LV_STATE_DISABLED);
}

static void software_show_page(app_t *app, const char *page)
{
    bool apps = strcmp(page, "apps") == 0;
    bool updates = strcmp(page, "updates") == 0;
    bool detail = strcmp(page, "detail") == 0;
    if(app->software_apps_page != NULL)
        lv_obj_set_flag(app->software_apps_page, LV_OBJ_FLAG_HIDDEN, !apps);
    if(app->software_updates_page != NULL)
        lv_obj_set_flag(app->software_updates_page, LV_OBJ_FLAG_HIDDEN, !updates);
    if(app->software_detail_page != NULL)
        lv_obj_set_flag(app->software_detail_page, LV_OBJ_FLAG_HIDDEN, !detail);
    fprintf(stderr, "settings-lvgl: software-page=%s\n", page);
}

static void software_package_event(lv_event_t *event)
{
    software_package_t *package = lv_event_get_user_data(event);
    ptrdiff_t index;
    if(active_app == NULL || package == NULL) return;
    index = package - active_app->packages;
    if(index < 0 || (size_t)index >= active_app->package_count) return;
    active_app->selected_package = (int)index;
    copy_text(active_app->selected_package_id,
              sizeof(active_app->selected_package_id), package->id);
    software_update_visible(active_app);
    copy_text(active_app->software_page,
              sizeof(active_app->software_page), "detail");
    software_show_page(active_app, "detail");
    send_bridge(active_app, "ACTION", "software_page", "detail");
    if(active_app->software_detail_id != NULL)
        msys_ui_animate_opening(active_app->software_detail_id,
                                active_app->policy);
}

static void software_render_packages(app_t *app)
{
    size_t index;
    if(app->software_package_list == NULL || !app->packages_changed) return;
    lv_obj_clean(app->software_package_list);
    if(app->package_count == 0U) {
        lv_obj_t *empty = lv_label_create(app->software_package_list);
        lv_label_set_text(empty, app->software_available
                                  ? "没有已安装的软件包。"
                                  : "Install Agent 当前不可用。");
        lv_obj_set_width(empty, LV_PCT(100));
        lv_label_set_long_mode(empty, LV_LABEL_LONG_WRAP);
        lv_obj_set_style_text_font(empty,
            msys_ui_theme_font(app->theme, 14), LV_PART_MAIN);
        lv_obj_set_style_text_color(empty, lv_color_hex(0x667085), LV_PART_MAIN);
    }
    for(index = 0U; index < app->package_count; index++) {
        software_package_t *package = &app->packages[index];
        lv_obj_t *row = lv_obj_create(app->software_package_list);
        lv_obj_t *text = lv_obj_create(row);
        lv_obj_t *name = lv_label_create(text);
        lv_obj_t *version = lv_label_create(text);
        lv_obj_t *arrow = lv_label_create(row);
        lv_obj_set_width(row, LV_PCT(100));
        lv_obj_set_height(row, 68);
        lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START,
                              LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        lv_obj_set_style_bg_color(row, lv_color_hex(0xffffff), LV_PART_MAIN);
        lv_obj_set_style_bg_opa(row, LV_OPA_COVER, LV_PART_MAIN);
        lv_obj_set_style_border_width(row, 1, LV_PART_MAIN);
        lv_obj_set_style_border_color(row, lv_color_hex(0xdfe4ee), LV_PART_MAIN);
        lv_obj_set_style_radius(row, 15, LV_PART_MAIN);
        lv_obj_set_style_pad_all(row, 10, LV_PART_MAIN);
        lv_obj_add_flag(row, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(row, software_package_event, LV_EVENT_CLICKED, package);
        lv_obj_add_event_cb(row, xml_press_event, LV_EVENT_ALL, NULL);

        lv_obj_set_flex_grow(text, 1);
        lv_obj_set_height(text, LV_SIZE_CONTENT);
        lv_obj_set_flex_flow(text, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_style_bg_opa(text, LV_OPA_TRANSP, LV_PART_MAIN);
        lv_obj_set_style_border_width(text, 0, LV_PART_MAIN);
        lv_obj_set_style_pad_all(text, 0, LV_PART_MAIN);
        lv_obj_set_style_pad_row(text, 4, LV_PART_MAIN);
        lv_label_set_text(name, package->id);
        lv_obj_set_width(name, LV_PCT(100));
        lv_label_set_long_mode(name, LV_LABEL_LONG_DOT);
        lv_obj_set_style_text_font(name,
            msys_ui_theme_font(app->theme, 14), LV_PART_MAIN);
        lv_obj_set_style_text_color(name, lv_color_hex(0x182033), LV_PART_MAIN);
        lv_label_set_text(version, package->version[0] != '\0'
                                   ? package->version : "版本未知");
        lv_obj_set_width(version, LV_PCT(100));
        lv_label_set_long_mode(version, LV_LABEL_LONG_WRAP);
        lv_obj_set_style_text_font(version,
            msys_ui_theme_font(app->theme, 12), LV_PART_MAIN);
        lv_obj_set_style_text_color(version, lv_color_hex(0x667085), LV_PART_MAIN);
        lv_label_set_text(arrow, LV_SYMBOL_RIGHT);
        lv_obj_set_style_text_font(arrow, &lv_font_montserrat_16, LV_PART_MAIN);
        lv_obj_set_style_text_color(arrow, lv_color_hex(0x356ae6), LV_PART_MAIN);
    }
    app->packages_changed = false;
}

static void software_update_visible(app_t *app)
{
    char summary[352];
    software_package_t *selected = NULL;
    if(app->selected_package >= 0 &&
       (size_t)app->selected_package < app->package_count)
        selected = &app->packages[app->selected_package];
    set_label_text(app->software_apps_status, app->software_status);
    set_label_text(app->software_source_label, app->software_source);
    set_label_text(app->software_update_status, app->software_operation);
    if(selected != NULL) {
        set_label_text(app->software_detail_id, selected->id);
        (void)snprintf(summary, sizeof(summary), "版本：%s",
                       selected->version[0] != '\0' ? selected->version : "未知");
        set_label_text(app->software_detail_version, summary);
        (void)snprintf(summary, sizeof(summary), "安装位置：%s",
                       selected->path[0] != '\0' ? selected->path : "未提供");
        set_label_text(app->software_detail_path, summary);
    }
    software_set_disabled(app->software_check_button,
                          app->software_busy || app->software_source[0] == '\0' ||
                          strcmp(app->software_source, "未配置更新源") == 0);
    software_set_disabled(app->software_apply_button,
                          app->software_busy || app->software_source[0] == '\0' ||
                          strcmp(app->software_source, "未配置更新源") == 0);
    software_set_disabled(app->software_uninstall_button,
                          app->software_busy || selected == NULL);
    software_set_disabled(app->software_rollback_button,
                          app->software_busy || selected == NULL);
    software_render_packages(app);
    software_show_page(app, app->software_page);
    if(selected != NULL && strcmp(app->software_intent, "uninstall") == 0) {
        app->software_intent[0] = '\0';
        software_show_confirm(app, "software_uninstall");
    }
}

static void software_navigate_event(lv_event_t *event)
{
    const char *page = lv_event_get_user_data(event);
    if(active_app == NULL || page == NULL) return;
    copy_text(active_app->software_page,
              sizeof(active_app->software_page), page);
    software_show_page(active_app, page);
    send_bridge(active_app, "ACTION", "software_page", page);
    (void)event;
}

static void software_back_event(lv_event_t *event)
{
    if(active_app == NULL) return;
    copy_text(active_app->software_page,
              sizeof(active_app->software_page), "apps");
    software_show_page(active_app, "apps");
    send_bridge(active_app, "ACTION", "software_page", "apps");
    (void)event;
}

static void software_refresh_event(lv_event_t *event)
{
    if(active_app == NULL || active_app->software_busy) return;
    send_bridge(active_app, "REFRESH", "software", "");
    show_toast(active_app, "正在刷新真实软件注册表…");
    (void)event;
}

static void software_check_event(lv_event_t *event)
{
    if(active_app == NULL || active_app->software_busy) return;
    send_bridge(active_app, "ACTION", "software_check", "all");
    show_toast(active_app, "正在等待 Update Agent 检查结果…");
    (void)event;
}

static void software_hide_confirm(app_t *app)
{
    if(app->software_confirm != NULL)
        lv_obj_add_flag(app->software_confirm, LV_OBJ_FLAG_HIDDEN);
    app->pending_action[0] = '\0';
}

static void software_show_confirm(app_t *app, const char *action)
{
    software_package_t *selected = NULL;
    const char *title;
    char prompt[640];
    if(app->software_busy) return;
    if(app->selected_package >= 0 &&
       (size_t)app->selected_package < app->package_count)
        selected = &app->packages[app->selected_package];
    if(strcmp(action, "software_apply") == 0) {
        title = "应用签名更新？";
        (void)snprintf(prompt, sizeof(prompt),
                       "将从下方更新源应用全部可用更新。操作仍由 Update Agent 校验、安装并执行健康检查。\n\n%s",
                       app->software_source);
    }
    else {
        if(selected == NULL) return;
        title = strcmp(action, "software_uninstall") == 0
                    ? "卸载这个软件包？" : "回退这个软件包？";
        (void)snprintf(prompt, sizeof(prompt),
                       "%s\n版本：%s\n\n确认后仍会等待 Install Agent 返回真实终态；失败不会显示为成功。",
                       selected->id,
                       selected->version[0] != '\0' ? selected->version : "未知");
    }
    copy_text(app->pending_action, sizeof(app->pending_action), action);
    set_label_text(app->software_confirm_title, title);
    set_label_text(app->software_confirm_text, prompt);
    if(app->software_confirm != NULL)
        lv_obj_remove_flag(app->software_confirm, LV_OBJ_FLAG_HIDDEN);
}

static void software_request_confirm_event(lv_event_t *event)
{
    const char *action = lv_event_get_user_data(event);
    if(active_app != NULL && action != NULL)
        software_show_confirm(active_app, action);
}

static void software_cancel_event(lv_event_t *event)
{
    if(active_app != NULL) software_hide_confirm(active_app);
    (void)event;
}

static void software_confirm_event(lv_event_t *event)
{
    const char *value = "all";
    char action[sizeof(active_app->pending_action)];
    if(active_app == NULL || active_app->pending_action[0] == '\0') return;
    copy_text(action, sizeof(action), active_app->pending_action);
    if(strcmp(action, "software_apply") != 0) {
        if(active_app->selected_package < 0 ||
           (size_t)active_app->selected_package >= active_app->package_count)
            return;
        value = active_app->packages[active_app->selected_package].id;
    }
    software_hide_confirm(active_app);
    send_bridge(active_app, "ACTION", action, value);
    show_toast(active_app, "请求已发送，正在等待代理终态…");
    (void)event;
}

static int xml_bind(lv_xml_component_scope_t *scope, void *user_data)
{
    app_t *app = user_data;
    if(scope == NULL || app == NULL || app->theme == NULL) return -1;
    if(lv_xml_register_font(scope, "msys_12",
                            msys_ui_theme_font(app->theme, 12)) != LV_RESULT_OK ||
       lv_xml_register_font(scope, "msys_14",
                            msys_ui_theme_font(app->theme, 14)) != LV_RESULT_OK ||
       lv_xml_register_font(scope, "msys_16",
                            msys_ui_theme_font(app->theme, 16)) != LV_RESULT_OK ||
       lv_xml_register_font(scope, "msys_20",
                            msys_ui_theme_font(app->theme, 20)) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "settings_press", xml_press_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "settings_navigate", xml_navigate_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "settings_back", xml_back_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "settings_toggle", xml_toggle_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "settings_refresh", xml_refresh_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "settings_calibration", xml_calibration_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "software_navigate", software_navigate_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "software_back", software_back_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "software_refresh", software_refresh_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "software_check", software_check_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "software_request_confirm", software_request_confirm_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "software_cancel", software_cancel_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "software_confirm", software_confirm_event) != LV_RESULT_OK)
        return -1;
    return 0;
}

static void wire_document(app_t *app)
{
    int index;
    if(app->mode == APP_MODE_SOFTWARE_CENTER) {
        app->software_apps_page = ui_object(app, "software_apps_page");
        app->software_updates_page = ui_object(app, "software_updates_page");
        app->software_detail_page = ui_object(app, "software_detail_page");
        app->software_package_list = ui_object(app, "software_package_list");
        app->software_apps_status = ui_object(app, "software_apps_status");
        app->software_source_label = ui_object(app, "software_source");
        app->software_update_status = ui_object(app, "software_update_status");
        app->software_detail_id = ui_object(app, "software_detail_id");
        app->software_detail_version = ui_object(app, "software_detail_version");
        app->software_detail_path = ui_object(app, "software_detail_path");
        app->software_confirm = ui_object(app, "software_confirm");
        app->software_confirm_title = ui_object(app, "software_confirm_title");
        app->software_confirm_text = ui_object(app, "software_confirm_text");
        app->software_check_button = ui_object(app, "software_check_button");
        app->software_apply_button = ui_object(app, "software_apply_button");
        app->software_uninstall_button = ui_object(app, "software_uninstall_button");
        app->software_rollback_button = ui_object(app, "software_rollback_button");
        app->toast = ui_object(app, "toast");
        app->toast_label = ui_object(app, "toast_text");
        if(app->software_package_list != NULL) {
            lv_obj_set_scroll_dir(app->software_package_list, LV_DIR_VER);
            lv_obj_set_scrollbar_mode(app->software_package_list,
                                      LV_SCROLLBAR_MODE_AUTO);
        }
        app->packages_changed = true;
        software_show_page(app, "apps");
        software_update_visible(app);
        return;
    }
    app->home_page = ui_object(app, "home_page");
    app->detail_page = ui_object(app, "detail_page");
    app->status_label = ui_object(app, "model_status");
    app->detail_title = ui_object(app, "detail_title");
    app->detail_note = ui_object(app, "detail_note");
    app->detail_summary = ui_object(app, "detail_summary");
    app->detail_label = ui_object(app, "detail_text");
    app->toggle_row = ui_object(app, "toggle_row");
    app->toggle = ui_object(app, "panel_toggle");
    app->calibration_button = ui_object(app, "calibration_button");
    app->toast = ui_object(app, "toast");
    app->toast_label = ui_object(app, "toast_text");
    for(index = 0; index < PANEL_COUNT; index++) {
        char name[64];
        lv_obj_t *title;
        lv_obj_t *icon;
        (void)snprintf(name, sizeof(name), "summary_%s", app->panels[index].id);
        app->summary_labels[index] = ui_object(app, name);
        (void)snprintf(name, sizeof(name), "title_%s", app->panels[index].id);
        title = ui_object(app, name);
        set_label_text(title, app->panels[index].title);
        (void)snprintf(name, sizeof(name), "icon_%s", app->panels[index].id);
        icon = ui_object(app, name);
        set_label_text(icon, app->panels[index].symbol);
        if(icon != NULL)
            lv_obj_set_style_text_font(icon, &lv_font_montserrat_16, LV_PART_MAIN);
    }
    {
        lv_obj_t *home_content = ui_object(app, "home_content");
        lv_obj_t *detail_content = ui_object(app, "detail_content");
        if(home_content != NULL) {
            lv_obj_set_scroll_dir(home_content, LV_DIR_VER);
            lv_obj_set_scrollbar_mode(home_content, LV_SCROLLBAR_MODE_AUTO);
        }
        if(detail_content != NULL) {
            lv_obj_set_scroll_dir(detail_content, LV_DIR_VER);
            lv_obj_set_scrollbar_mode(detail_content, LV_SCROLLBAR_MODE_AUTO);
        }
    }
    update_visible(app);
}

static int load_ui_document(app_t *app)
{
    msys_ui_document_config_t config = {
        .max_bytes = 128U * 1024U,
        .bind = xml_bind,
        .user_data = app,
    };
    int result;
    app->document = msys_ui_document_create(
        msys_ui_surface_screen(app->surface), &config);
    if(app->document == NULL) return MSYS_UI_DOCUMENT_CREATE;
    result = msys_ui_document_load_file(app->document, app->ui_path);
    if(result == MSYS_UI_DOCUMENT_OK) wire_document(app);
    return result;
}

static void update_visible(app_t *app)
{
    int index;
    if(app->mode == APP_MODE_SOFTWARE_CENTER) {
        software_update_visible(app);
        return;
    }
    if(app->home_page != NULL)
        lv_obj_set_flag(app->home_page, LV_OBJ_FLAG_HIDDEN,
                        app->active_panel >= 0);
    if(app->detail_page != NULL)
        lv_obj_set_flag(app->detail_page, LV_OBJ_FLAG_HIDDEN,
                        app->active_panel < 0);
    set_label_text(app->status_label, app->status);
    if(app->active_panel < 0) {
        for(index = 0; index < PANEL_COUNT; index++)
            set_label_text(app->summary_labels[index], app->panels[index].summary);
        return;
    }
    set_label_text(app->detail_title, app->panels[app->active_panel].title);
    set_label_text(app->detail_note, app->panels[app->active_panel].note);
    set_label_text(app->detail_summary, app->panels[app->active_panel].summary);
    set_label_text(app->detail_label, app->panels[app->active_panel].detail);
    {
        panel_t *panel = &app->panels[app->active_panel];
        lv_obj_t *label = ui_object(app, "toggle_label");
        set_label_text(label, toggle_label(panel));
        if(app->toggle_row != NULL)
            lv_obj_set_flag(app->toggle_row, LV_OBJ_FLAG_HIDDEN,
                            !panel->toggle_available);
        if(app->calibration_button != NULL)
            lv_obj_set_flag(app->calibration_button, LV_OBJ_FLAG_HIDDEN,
                            app->active_panel != PANEL_CALIBRATION ||
                            !panel->available);
    }
    if(app->toggle != NULL) {
        app->applying_snapshot = true;
        if(app->panels[app->active_panel].toggle_value)
            lv_obj_add_state(app->toggle, LV_STATE_CHECKED);
        else
            lv_obj_remove_state(app->toggle, LV_STATE_CHECKED);
        app->applying_snapshot = false;
    }
}

static int hex_value(char value)
{
    if(value >= '0' && value <= '9') return value - '0';
    if(value >= 'a' && value <= 'f') return value - 'a' + 10;
    if(value >= 'A' && value <= 'F') return value - 'A' + 10;
    return -1;
}

static void percent_decode(char *text)
{
    char *source = text;
    char *target = text;
    while(*source != '\0') {
        if(source[0] == '%' && source[1] != '\0' && source[2] != '\0') {
            int high = hex_value(source[1]);
            int low = hex_value(source[2]);
            if(high >= 0 && low >= 0) {
                *target++ = (char)((high << 4) | low);
                source += 3;
                continue;
            }
        }
        *target++ = *source++;
    }
    *target = '\0';
}

static bool parse_bool(const char *value)
{
    return strcmp(value, "1") == 0 || strcmp(value, "true") == 0;
}

static bool apply_software_field(app_t *app, const char *key, const char *value)
{
    const char *field;
    char *end = NULL;
    unsigned long parsed;
    size_t index;
    if(strcmp(key, "software.status") == 0)
        return replace_text(app->software_status,
                            sizeof(app->software_status), value);
    if(strcmp(key, "software.source") == 0)
        return replace_text(app->software_source,
                            sizeof(app->software_source), value);
    if(strcmp(key, "software.operation") == 0)
        return replace_text(app->software_operation,
                            sizeof(app->software_operation), value);
    if(strcmp(key, "software.page") == 0) {
        if(strcmp(value, "apps") != 0 && strcmp(value, "updates") != 0 &&
           strcmp(value, "detail") != 0) return false;
        return replace_text(app->software_page,
                            sizeof(app->software_page), value);
    }
    if(strcmp(key, "software.select") == 0) {
        size_t selected;
        bool changed = replace_text(app->selected_package_id,
                                    sizeof(app->selected_package_id), value);
        app->selected_package = -1;
        for(selected = 0U; selected < app->package_count; selected++) {
            if(strcmp(app->packages[selected].id, value) == 0) {
                app->selected_package = (int)selected;
                break;
            }
        }
        return changed;
    }
    if(strcmp(key, "software.intent") == 0)
        return replace_text(app->software_intent,
                            sizeof(app->software_intent), value);
    if(strcmp(key, "software.available") == 0) {
        bool next = parse_bool(value);
        if(app->software_available == next) return false;
        app->software_available = next;
        return true;
    }
    if(strcmp(key, "software.busy") == 0) {
        bool next = parse_bool(value);
        if(app->software_busy == next) return false;
        app->software_busy = next;
        return true;
    }
    if(strcmp(key, "software.package_count") == 0) {
        parsed = strtoul(value, &end, 10);
        if(end == value || *end != '\0') return false;
        app->pending_package_total = (size_t)parsed;
        app->pending_package_count = app->pending_package_total;
        if(app->pending_package_count > SOFTWARE_MAX_PACKAGES)
            app->pending_package_count = SOFTWARE_MAX_PACKAGES;
        memset(app->pending_packages, 0, sizeof(app->pending_packages));
        app->pending_packages_valid = true;
        return false;
    }
    if(strncmp(key, "software.package.", 17U) != 0 ||
       !app->pending_packages_valid) return false;
    parsed = strtoul(key + 17U, &end, 10);
    if(end == key + 17U || *end != '.' ||
       parsed >= app->pending_package_count) return false;
    index = (size_t)parsed;
    field = end + 1;
    if(strcmp(field, "id") == 0)
        copy_text(app->pending_packages[index].id,
                  sizeof(app->pending_packages[index].id), value);
    else if(strcmp(field, "version") == 0)
        copy_text(app->pending_packages[index].version,
                  sizeof(app->pending_packages[index].version), value);
    else if(strcmp(field, "path") == 0)
        copy_text(app->pending_packages[index].path,
                  sizeof(app->pending_packages[index].path), value);
    return false;
}

static void finish_software_packages(app_t *app)
{
    size_t index;
    bool changed;
    if(!app->pending_packages_valid) return;
    changed = app->package_count != app->pending_package_count ||
              app->package_total != app->pending_package_total ||
              memcmp(app->packages, app->pending_packages,
                     sizeof(app->packages)) != 0;
    if(changed) {
        app->package_count = app->pending_package_count;
        app->package_total = app->pending_package_total;
        memcpy(app->packages, app->pending_packages, sizeof(app->packages));
        app->packages_changed = true;
        app->selected_package = -1;
        if(app->selected_package_id[0] != '\0') {
            for(index = 0U; index < app->package_count; index++) {
                if(strcmp(app->packages[index].id,
                          app->selected_package_id) == 0) {
                    app->selected_package = (int)index;
                    break;
                }
            }
        }
    }
    app->pending_packages_valid = false;
}

static void apply_field(app_t *app, char *key, char *value)
{
    char *dot;
    panel_t *panel;
    percent_decode(value);
    if(strncmp(key, "software.", 9U) == 0) {
        if(apply_software_field(app, key, value)) app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "status") == 0) {
        if(strcmp(app->status, value) != 0) {
            copy_text(app->status, sizeof(app->status), value);
            app->snapshot_changed = true;
        }
        return;
    }
    if(strcmp(key, "toast") == 0) {
        show_toast(app, value);
        return;
    }
    dot = strchr(key, '.');
    if(dot == NULL) return;
    *dot++ = '\0';
    panel = panel_by_id(app, key);
    if(panel == NULL) return;
    if(strcmp(dot, "summary") == 0) copy_text(panel->summary, sizeof(panel->summary), value);
    else if(strcmp(dot, "detail") == 0) copy_text(panel->detail, sizeof(panel->detail), value);
    else if(strcmp(dot, "available") == 0) panel->available = parse_bool(value);
    else if(strcmp(dot, "toggle.available") == 0) panel->toggle_available = parse_bool(value);
    else if(strcmp(dot, "toggle.value") == 0) panel->toggle_value = parse_bool(value);
    else return;
    app->snapshot_changed = true;
}

static void parse_line(app_t *app, char *line)
{
    char *tab;
    size_t length = strlen(line);
    while(length > 0U && (line[length - 1U] == '\r' || line[length - 1U] == '\n'))
        line[--length] = '\0';
    if(strncmp(line, "BEGIN\t", 6U) == 0) {
        app->snapshot_changed = false;
        return;
    }
    if(strncmp(line, "END\t", 4U) == 0) {
        if(app->mode == APP_MODE_SOFTWARE_CENTER && app->pending_packages_valid) {
            bool was_changed = app->packages_changed;
            finish_software_packages(app);
            if(app->packages_changed != was_changed) app->snapshot_changed = true;
        }
        if(app->snapshot_changed) update_visible(app);
        return;
    }
    tab = strchr(line, '\t');
    if(tab == NULL) return;
    *tab++ = '\0';
    apply_field(app, line, tab);
}

static void read_bridge(app_t *app)
{
    char chunk[2048];
    ssize_t count;
    while((count = read(app->bridge_output, chunk, sizeof(chunk))) > 0) {
        size_t offset;
        for(offset = 0U; offset < (size_t)count; offset++) {
            char value = chunk[offset];
            if(value == '\n') {
                app->line_buffer[app->line_used] = '\0';
                parse_line(app, app->line_buffer);
                app->line_used = 0U;
            }
            else if(app->line_used + 1U < sizeof(app->line_buffer)) {
                app->line_buffer[app->line_used++] = value;
            }
            else {
                app->line_used = 0U;
                show_toast(app, "SettingsModel 返回行过长");
            }
        }
    }
    if(count == 0) {
        close(app->bridge_output);
        app->bridge_output = -1;
        show_toast(app, "SettingsModel 已断开");
    }
    else if(count < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
        show_toast(app, "SettingsModel 读取失败");
    }
}

static int start_bridge(app_t *app, const char *python, const char *script)
{
    int input_pipe[2];
    int output_pipe[2];
    pid_t pid;
    const char *control_fd;
    if(pipe(input_pipe) != 0 || pipe(output_pipe) != 0) return -1;
    pid = fork();
    if(pid < 0) return -1;
    if(pid == 0) {
        (void)dup2(input_pipe[0], STDIN_FILENO);
        (void)dup2(output_pipe[1], STDOUT_FILENO);
        close(input_pipe[0]);
        close(input_pipe[1]);
        close(output_pipe[0]);
        close(output_pipe[1]);
        execlp(python, python, "-B", script, (char *)NULL);
        _exit(127);
    }
    close(input_pipe[0]);
    close(output_pipe[1]);
    app->bridge_input = fdopen(input_pipe[1], "w");
    app->bridge_output = output_pipe[0];
    app->bridge_pid = pid;
    (void)fcntl(app->bridge_output, F_SETFL,
                fcntl(app->bridge_output, F_GETFL, 0) | O_NONBLOCK);
    if(app->bridge_input != NULL) setvbuf(app->bridge_input, NULL, _IOLBF, 0U);
    control_fd = getenv("MSYS_CONTROL_FD");
    if(control_fd != NULL) {
        char *end = NULL;
        long fd = strtol(control_fd, &end, 10);
        if(end != control_fd && *end == '\0' && fd >= 0 && fd <= INT32_MAX)
            close((int)fd);
    }
    return app->bridge_input != NULL ? 0 : -1;
}

static const char *resolve_python(const char *requested, char *buffer,
                                  size_t capacity)
{
    const char *configured;
    char link_path[64];
    ssize_t length;
    if(strcmp(requested, "@supervisor-python") != 0) return requested;
    configured = getenv("MSYS_PYTHON_EXECUTABLE");
    if(configured != NULL && configured[0] == '/') return configured;
    (void)snprintf(link_path, sizeof(link_path), "/proc/%ld/exe",
                   (long)getppid());
    length = readlink(link_path, buffer, capacity - 1U);
    if(length > 0 && (size_t)length < capacity) {
        const char *basename;
        buffer[length] = '\0';
        basename = strrchr(buffer, '/');
        basename = basename != NULL ? basename + 1 : buffer;
        if(strstr(basename, "python") != NULL) return buffer;
    }
    return "python";
}

static int load_snapshot(app_t *app, const char *path)
{
    FILE *stream = fopen(path, "r");
    char line[8192];
    if(stream == NULL) return -1;
    while(fgets(line, sizeof(line), stream) != NULL) parse_line(app, line);
    fclose(stream);
    return 0;
}

static void stop_bridge(app_t *app)
{
    if(app->bridge_input != NULL) {
        (void)fprintf(app->bridge_input, "QUIT\n");
        (void)fclose(app->bridge_input);
        app->bridge_input = NULL;
    }
    if(app->bridge_output >= 0) close(app->bridge_output);
    if(app->bridge_pid > 0) {
        int status;
        int attempt;
        for(attempt = 0; attempt < 10; attempt++) {
            if(waitpid(app->bridge_pid, &status, WNOHANG) == app->bridge_pid) return;
            struct timespec delay = {.tv_sec = 0, .tv_nsec = 10000000L};
            (void)nanosleep(&delay, NULL);
        }
        (void)kill(app->bridge_pid, SIGTERM);
        (void)waitpid(app->bridge_pid, &status, 0);
    }
}

static int event_loop(app_t *app)
{
    while(!stopping && !msys_ui_surface_closed(app->surface) &&
          (app->run_until == 0U || now_ms() < app->run_until)) {
        struct pollfd descriptors[2];
        nfds_t count = 1U;
        uint32_t timeout;
        int result;
        if(msys_ui_runtime_pump(app->runtime) <= 0) break;
        if(app->watch_ui && now_ms() >= app->next_ui_check) {
            int reload = msys_ui_document_reload_if_changed(app->document);
            app->next_ui_check = now_ms() + 250U;
            if(reload == MSYS_UI_DOCUMENT_OK) {
                wire_document(app);
                fprintf(stderr, "settings-lvgl: reloaded-ui=%s\n", app->ui_path);
            }
            else if(reload != MSYS_UI_DOCUMENT_UNCHANGED) {
                fprintf(stderr, "settings-lvgl: ui-reload-failed=%d path=%s\n",
                        reload, app->ui_path);
            }
        }
        timeout = msys_ui_runtime_next_deadline_ms(app->runtime);
        if(timeout == LV_NO_TIMER_READY || timeout > 100U) timeout = 100U;
        descriptors[0].fd = msys_ui_runtime_poll_fd(app->runtime);
        descriptors[0].events = POLLIN;
        descriptors[0].revents = 0;
        if(app->bridge_output >= 0) {
            descriptors[1].fd = app->bridge_output;
            descriptors[1].events = POLLIN | POLLHUP;
            descriptors[1].revents = 0;
            count = 2U;
        }
        result = poll(descriptors, count, (int)timeout);
        if(result < 0 && errno != EINTR) return -1;
        if(count == 2U && (descriptors[1].revents & (POLLIN | POLLHUP)) != 0)
            read_bridge(app);
    }
    return 0;
}

static void usage(const char *program)
{
    fprintf(stderr, "usage: %s [--bridge FILE --python PYTHON] "
                    "[--snapshot FILE] [--ui FILE] [--watch-ui] "
                    "[--mode settings|software-center] "
                    "[--display NAME] [--run-ms N]\n", program);
}

int main(int argc, char **argv)
{
    app_t app;
    msys_ui_runtime_config_t runtime_config = {.output = MSYS_UI_OUTPUT_SPI};
    msys_ui_surface_config_t surface_config = {
        .x=0, .y=42, .width=320, .height=396, .draw_rows=48,
        .title="MSYS 设置", .app_id="org.msys.settings",
        .component_id="org.msys.settings:main-lvgl", .role="application",
        .wm_instance="main-lvgl", .override_redirect=false,
    };
    const char *bridge = NULL;
    const char *python = "python";
    const char *snapshot = NULL;
    char python_path[PATH_MAX];
    int index;
    int result;
    memset(&app, 0, sizeof(app));
    app.mode = APP_MODE_SETTINGS;
    app.active_panel = -1;
    app.bridge_output = -1;
    app.ui_path = "files/share/ui/settings.xml";
    init_panels(&app);
    for(index = 1; index < argc; index++) {
        if(strcmp(argv[index], "--describe") == 0) {
            puts("{\"frontend\":\"lvgl-xml\",\"theme\":\"light\","
                 "\"modes\":[\"settings\",\"software-center\"],"
                 "\"model\":\"msys-settings-python-bridge\"}");
            return 0;
        }
        if(strcmp(argv[index], "--bridge") == 0 && index + 1 < argc) bridge = argv[++index];
        else if(strcmp(argv[index], "--python") == 0 && index + 1 < argc) python = argv[++index];
        else if(strcmp(argv[index], "--snapshot") == 0 && index + 1 < argc) snapshot = argv[++index];
        else if(strcmp(argv[index], "--ui") == 0 && index + 1 < argc) app.ui_path = argv[++index];
        else if(strcmp(argv[index], "--mode") == 0 && index + 1 < argc) {
            const char *mode = argv[++index];
            if(strcmp(mode, "software-center") == 0)
                app.mode = APP_MODE_SOFTWARE_CENTER;
            else if(strcmp(mode, "settings") != 0) {
                usage(argv[0]);
                return 2;
            }
        }
        else if(strcmp(argv[index], "--watch-ui") == 0) app.watch_ui = true;
        else if(strcmp(argv[index], "--display") == 0 && index + 1 < argc) runtime_config.display_name = argv[++index];
        else if(strcmp(argv[index], "--run-ms") == 0 && index + 1 < argc)
            app.run_until = now_ms() + strtoull(argv[++index], NULL, 10);
        else if(strcmp(argv[index], "--output") == 0 && index + 1 < argc)
            runtime_config.output = strcmp(argv[++index], "hdmi") == 0
                                        ? MSYS_UI_OUTPUT_HDMI : MSYS_UI_OUTPUT_SPI;
        else if(strcmp(argv[index], "--reduced-motion") == 0) runtime_config.reduced_motion = true;
        else { usage(argv[0]); return 2; }
    }
    if(app.mode == APP_MODE_SOFTWARE_CENTER) {
        surface_config.title = "MSYS 软件中心";
        surface_config.app_id = "org.msys.software-center";
        surface_config.component_id = "org.msys.settings:software-center";
        surface_config.wm_instance = "software-center";
    }
    app.runtime = msys_ui_runtime_create(&runtime_config);
    if(app.runtime == NULL) return 1;
    (void)msys_ui_dynamic_fonts_init(NULL);
    app.policy = msys_ui_runtime_policy(app.runtime);
    app.surface = msys_ui_surface_create(app.runtime, &surface_config);
    if(app.surface == NULL) {
        msys_ui_dynamic_fonts_shutdown();
        msys_ui_runtime_destroy(app.runtime);
        return 1;
    }
    app.theme = msys_ui_theme_create(msys_ui_surface_display(app.surface), app.policy);
    if(app.theme == NULL) {
        msys_ui_dynamic_fonts_shutdown();
        msys_ui_runtime_destroy(app.runtime);
        return 1;
    }
    msys_ui_theme_set_font_provider(app.theme, msys_ui_font_provider,
                                    NULL, "zh-CN");
    active_app = &app;
    result = load_ui_document(&app);
    if(result != MSYS_UI_DOCUMENT_OK) {
        fprintf(stderr, "settings-lvgl: ui-load-failed=%d path=%s\n",
                result, app.ui_path);
        msys_ui_document_destroy(app.document);
        msys_ui_theme_destroy(app.theme);
        msys_ui_dynamic_fonts_shutdown();
        msys_ui_runtime_destroy(app.runtime);
        return 1;
    }
    msys_ui_surface_show(app.surface);
    if(snapshot != NULL) {
        if(load_snapshot(&app, snapshot) != 0) show_toast(&app, "无法读取测试快照");
    }
    else if(bridge == NULL ||
            start_bridge(&app, resolve_python(python, python_path,
                                              sizeof(python_path)), bridge) != 0) {
        show_toast(&app, "SettingsModel bridge 启动失败");
    }
    (void)signal(SIGINT, signal_handler);
    (void)signal(SIGTERM, signal_handler);
    result = event_loop(&app);
    stop_bridge(&app);
    active_app = NULL;
    msys_ui_document_destroy(app.document);
    msys_ui_theme_destroy(app.theme);
    msys_ui_dynamic_fonts_shutdown();
    msys_ui_runtime_destroy(app.runtime);
    return result == 0 ? 0 : 1;
}
