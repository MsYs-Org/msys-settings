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
       PANEL_APPEARANCE, PANEL_INPUT, PANEL_STORAGE, PANEL_REGIONAL,
       PANEL_APPS, PANEL_UPDATES, PANEL_HAL, PANEL_ROLES, PANEL_DEVELOPER,
       PANEL_CALIBRATION, PANEL_SYSTEM, PANEL_COUNT };

enum { APP_MODE_SETTINGS, APP_MODE_SOFTWARE_CENTER };
enum { SOFTWARE_MAX_PACKAGES = 96 };
enum { SETTINGS_MAX_ITEMS = 64 };

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
    char id[160];
    char label[192];
    char meta[192];
} setting_item_t;

typedef struct {
    char layout[16];
    char navigation_mode[16];
    char navigation_visibility[16];
    char status_visibility[16];
    char orientation[16];
    char wallpaper_color[16];
    char accent_color[16];
    char wallpaper_path[1024];
    char sort[16];
    int icon_size;
    int icon_spacing;
    int grid_columns;
    int grid_rows;
    bool show_labels;
    bool folders_enabled;
    bool large_folders_enabled;
    bool acrylic;
    bool animations_enabled;
    bool reduce_motion;
    bool available;
} desktop_state_t;

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
    lv_obj_t *action_primary;
    lv_obj_t *action_primary_label;
    lv_obj_t *action_secondary;
    lv_obj_t *action_secondary_label;
    lv_obj_t *choice_row;
    lv_obj_t *choice_buttons[4];
    lv_obj_t *choice_labels[4];
    lv_obj_t *choice2_row;
    lv_obj_t *choice2_buttons[4];
    lv_obj_t *choice2_labels[4];
    lv_obj_t *adjust_row;
    lv_obj_t *adjust_label;
    lv_obj_t *adjust_value;
    lv_obj_t *input_card;
    lv_obj_t *input_label;
    lv_obj_t *input_secondary_label;
    lv_obj_t *input_value;
    lv_obj_t *input_secret;
    lv_obj_t *input_apply;
    lv_obj_t *input_apply_label;
    lv_obj_t *dynamic_list;
    lv_obj_t *toast;
    lv_obj_t *toast_label;
    lv_timer_t *toast_timer;
    lv_obj_t *status_label;
    lv_obj_t *appearance_page;
    lv_obj_t *appearance_status;
    lv_obj_t *appearance_layout[5];
    lv_obj_t *appearance_sort[2];
    lv_obj_t *appearance_navigation[2];
    lv_obj_t *appearance_navigation_visibility[2];
    lv_obj_t *appearance_status_visibility[2];
    lv_obj_t *appearance_orientation[3];
    lv_obj_t *appearance_icon_size;
    lv_obj_t *appearance_icon_spacing;
    lv_obj_t *appearance_grid_columns;
    lv_obj_t *appearance_grid_rows;
    lv_obj_t *appearance_wallpaper_color;
    lv_obj_t *appearance_accent_color;
    lv_obj_t *appearance_wallpaper_path;
    lv_obj_t *appearance_switches[6];
    desktop_state_t desktop;
    bool applying_snapshot;
    bool snapshot_changed;
    int audio_volume;
    bool audio_player_enabled;
    char audio_player_server[256];
    char audio_player_name[80];
    char display_profile[16];
    char display_insets[64];
    char physical_rotation[16];
    char input_mode[16];
    int developer_fps;
    bool developer_debug;
    bool developer_cursor;
    bool input_visible;
    bool physical_rotation_writable;
    bool hal_mutable;
    char regional_language[16];
    char regional_timezone[64];
    setting_item_t items[SETTINGS_MAX_ITEMS];
    size_t item_count;
    bool items_changed;
    char items_panel[32];
    char selected_item[160];
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
        {.id="appearance", .title="桌面", .note="Launcher 布局、图标与动效", .symbol=LV_SYMBOL_HOME},
        {.id="input", .title="输入法", .note="悬浮触摸键盘与焦点行为", .symbol=LV_SYMBOL_KEYBOARD},
        {.id="storage", .title="存储", .note="U 盘、TF 卡与自动挂载", .symbol=LV_SYMBOL_DRIVE},
        {.id="regional", .title="语言和时间", .note="语言、时区与格式", .symbol=LV_SYMBOL_GPS},
        {.id="apps", .title="应用", .note="已安装软件与卸载", .symbol=LV_SYMBOL_LIST},
        {.id="updates", .title="更新", .note="签名更新、恢复与回退", .symbol=LV_SYMBOL_REFRESH},
        {.id="hal", .title="硬件抽象", .note="设备、能力与提供者", .symbol=LV_SYMBOL_EYE_OPEN},
        {.id="roles", .title="系统角色", .note="可替换系统职位与当前提供者", .symbol=LV_SYMBOL_SHUFFLE},
        {.id="developer", .title="开发者选项", .note="FPS、脏区与触摸调试", .symbol=LV_SYMBOL_SETTINGS},
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
    copy_text(app->desktop.layout, sizeof(app->desktop.layout), "profile");
    copy_text(app->desktop.navigation_mode,
              sizeof(app->desktop.navigation_mode), "pill");
    copy_text(app->desktop.navigation_visibility,
              sizeof(app->desktop.navigation_visibility), "always");
    copy_text(app->desktop.status_visibility,
              sizeof(app->desktop.status_visibility), "always");
    copy_text(app->desktop.orientation, sizeof(app->desktop.orientation), "auto");
    copy_text(app->desktop.wallpaper_color,
              sizeof(app->desktop.wallpaper_color), "#F4F6FA");
    copy_text(app->desktop.accent_color,
              sizeof(app->desktop.accent_color), "#55A8FF");
    copy_text(app->desktop.sort, sizeof(app->desktop.sort), "name");
    app->desktop.icon_size = 64;
    app->desktop.icon_spacing = 8;
    app->desktop.show_labels = true;
    app->desktop.folders_enabled = true;
    app->desktop.large_folders_enabled = true;
    app->desktop.animations_enabled = true;
    app->audio_volume = 50;
    copy_text(app->audio_player_name, sizeof(app->audio_player_name), "MSYS Audio");
    copy_text(app->display_profile, sizeof(app->display_profile), "mobile");
    copy_text(app->display_insets, sizeof(app->display_insets), "auto");
    copy_text(app->physical_rotation, sizeof(app->physical_rotation), "normal");
    copy_text(app->input_mode, sizeof(app->input_mode), "en");
    app->developer_fps = 60;
    copy_text(app->regional_language, sizeof(app->regional_language), "system");
    copy_text(app->regional_timezone, sizeof(app->regional_timezone), "UTC");
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
    if(app != NULL) app->toast_timer = NULL;
    if(app != NULL && app->toast != NULL && lv_obj_is_valid(app->toast))
        msys_ui_animate_toast(app->toast, app->policy, false);
    lv_timer_delete(timer);
}

static void show_toast(app_t *app, const char *message)
{
    if(app == NULL || app->toast == NULL || app->toast_label == NULL ||
       !lv_obj_is_valid(app->toast) || !lv_obj_is_valid(app->toast_label)) {
        fprintf(stderr, "settings-lvgl: toast unavailable message=%s\n",
                message != NULL ? message : "");
        return;
    }
    set_label_text(app->toast_label, message);
    lv_anim_delete(app->toast, NULL);
    msys_ui_animate_toast(app->toast, app->policy, true);
    if(app->toast_timer != NULL) lv_timer_delete(app->toast_timer);
    app->toast_timer = lv_timer_create(hide_toast_cb, 1800U, app);
}

static bool create_toast(app_t *app)
{
    lv_obj_t *screen;
    if(app == NULL || app->surface == NULL || app->theme == NULL) return false;
    screen = msys_ui_surface_screen(app->surface);
    if(screen == NULL) return false;
    app->toast = lv_obj_create(screen);
    if(app->toast == NULL) return false;
    lv_obj_set_width(app->toast, 256);
    lv_obj_set_height(app->toast, LV_SIZE_CONTENT);
    lv_obj_align(app->toast, LV_ALIGN_TOP_MID, 0, 0);
    lv_obj_add_flag(app->toast, LV_OBJ_FLAG_FLOATING | LV_OBJ_FLAG_IGNORE_LAYOUT);
    lv_obj_remove_flag(app->toast, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(app->toast, lv_color_hex(0x202636), LV_PART_MAIN);
    lv_obj_set_style_bg_opa(app->toast, LV_OPA_90, LV_PART_MAIN);
    lv_obj_set_style_radius(app->toast, 14, LV_PART_MAIN);
    lv_obj_set_style_border_width(app->toast, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_hor(app->toast, 16, LV_PART_MAIN);
    lv_obj_set_style_pad_ver(app->toast, 10, LV_PART_MAIN);
    lv_obj_set_style_translate_y(app->toast, -48, LV_PART_MAIN);
    lv_obj_set_style_opa(app->toast, LV_OPA_TRANSP, LV_PART_MAIN);
    app->toast_label = lv_label_create(app->toast);
    if(app->toast_label == NULL) return false;
    lv_obj_set_width(app->toast_label, LV_PCT(100));
    lv_obj_set_height(app->toast_label, LV_SIZE_CONTENT);
    lv_label_set_long_mode(app->toast_label, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_align(app->toast_label, LV_TEXT_ALIGN_CENTER,
                                LV_PART_MAIN);
    lv_obj_set_style_text_font(app->toast_label,
                               msys_ui_theme_font(app->theme, 12),
                               LV_PART_MAIN);
    lv_obj_set_style_text_color(app->toast_label, lv_color_hex(0xffffff),
                                LV_PART_MAIN);
    return true;
}

static void update_visible(app_t *app);
static int clamp_integer(int value, int minimum, int maximum);

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
    if(strcmp(panel->id, "input") == 0) return "input_toggle";
    return NULL;
}

static const char *toggle_label(const panel_t *panel)
{
    if(strcmp(panel->id, "storage") == 0) return "自动挂载";
    if(strcmp(panel->id, "audio") == 0) return "静音";
    if(strcmp(panel->id, "input") == 0) return "显示触摸键盘";
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
    if(active_app->active_panel == PANEL_APPEARANCE && active_app->appearance_page != NULL)
        lv_obj_scroll_to_y(active_app->appearance_page, 0, LV_ANIM_OFF);
    else if(active_app->detail_page != NULL)
        lv_obj_scroll_to_y(active_app->detail_page, 0, LV_ANIM_OFF);
    send_bridge(active_app, "REFRESH", panel->id, "");
    send_bridge(active_app, "ACTION", "settings_page", panel->id);
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
    if(active_app->home_page != NULL)
        lv_obj_scroll_to_y(active_app->home_page, 0, LV_ANIM_OFF);
    send_bridge(active_app, "ACTION", "settings_page", "home");
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

static void panel_primary_event(lv_event_t *event)
{
    const char *action = NULL;
    if(active_app == NULL || active_app->active_panel < 0) return;
    switch(active_app->active_panel) {
    case PANEL_WIFI: action = "wifi_scan"; break;
    case PANEL_BLUETOOTH: action = "bluetooth_scan"; break;
    case PANEL_AUDIO: action = "audio_output"; break;
    case PANEL_STORAGE: action = "storage_refresh"; break;
    case PANEL_INPUT: action = "input_show"; break;
    case PANEL_APPS: action = "open_software"; break;
    case PANEL_UPDATES: action = "open_updates"; break;
    case PANEL_DEVELOPER: action = "developer_debug_toggle"; break;
    default: break;
    }
    if(action != NULL) {
        const char *value = active_app->active_panel == PANEL_AUDIO
                                ? active_app->selected_item : "1";
        send_bridge(active_app, "ACTION", action, value);
        show_toast(active_app, "正在执行…");
    }
    (void)event;
}

static void panel_secondary_event(lv_event_t *event)
{
    const char *action = NULL;
    if(active_app == NULL || active_app->active_panel < 0) return;
    switch(active_app->active_panel) {
    case PANEL_WIFI: action = "wifi_disconnect"; break;
    case PANEL_DEVELOPER: action = "developer_cursor_toggle"; break;
    default: break;
    }
    if(action != NULL) {
        const char *value = "1";
        send_bridge(active_app, "ACTION", action, value);
        show_toast(active_app, "正在执行…");
    }
    (void)event;
}

static void panel_choice_event(lv_event_t *event)
{
    const char *choice_text = lv_event_get_user_data(event);
    int choice = choice_text != NULL ? atoi(choice_text) : -1;
    const char *action = NULL;
    const char *value = NULL;
    if(active_app == NULL || active_app->active_panel < 0 ||
       choice < 0 || choice > 3) return;
    if(active_app->active_panel == PANEL_DISPLAY) {
        static const char *const profiles[] = {
            "mobile", "kiosk", "desktop", NULL
        };
        action = "display_set_profile";
        value = profiles[choice];
    }
    else if(active_app->active_panel == PANEL_REGIONAL) {
        static const char *const languages[] = {
            "system", "zh-CN", "en-US", "system"
        };
        action = "regional_language";
        value = languages[choice];
    }
    else if(active_app->active_panel == PANEL_BLUETOOTH) {
        static const char *const actions[] = {
            "bluetooth_pair", "bluetooth_connect",
            "bluetooth_disconnect", "bluetooth_forget"
        };
        action = actions[choice];
        value = active_app->selected_item;
    }
    else if(active_app->active_panel == PANEL_WIFI) {
        static const char *const actions[] = {"wifi_connect", "wifi_forget", NULL, NULL};
        static char request[384];
        action = actions[choice];
        if(action != NULL) {
            const char *password = active_app->input_secret != NULL
                                       ? lv_textarea_get_text(active_app->input_secret) : "";
            (void)snprintf(request, sizeof(request), "%s\x1f%s",
                           active_app->selected_item, password);
            value = request;
        }
    }
    else if(active_app->active_panel == PANEL_STORAGE) {
        static const char *const actions[] = {"storage_mount", "storage_unmount", NULL, NULL};
        action = actions[choice];
        value = active_app->selected_item;
    }
    else if(active_app->active_panel == PANEL_HAL) {
        static const char *const actions[] = {"hal_select", "hal_reset", NULL, NULL};
        action = actions[choice];
        value = active_app->selected_item;
    }
    else if(active_app->active_panel == PANEL_ROLES) {
        static const char *const actions[] = {"role_select", "role_reset", NULL, NULL};
        action = actions[choice];
        value = active_app->selected_item;
    }
    else if(active_app->active_panel == PANEL_INPUT) {
        static const char *const modes[] = {"en", "zh", "numeric", "symbols"};
        action = "input_mode";
        value = modes[choice];
    }
    else if(active_app->active_panel == PANEL_AUDIO) {
        static const char *const enabled[] = {"1", "0", NULL, NULL};
        action = "audio_player_enabled";
        value = enabled[choice];
    }
    if(action != NULL && value != NULL) {
        send_bridge(active_app, "ACTION", action, value);
        show_toast(active_app, "正在应用…");
    }
}

static void panel_choice2_event(lv_event_t *event)
{
    const char *choice_text = lv_event_get_user_data(event);
    int choice = choice_text != NULL ? atoi(choice_text) : -1;
    if(active_app == NULL || active_app->active_panel != PANEL_DISPLAY ||
       choice < 0 || choice > 3) return;
    {
        static const char *const rotations[] = {
            "normal", "right", "inverted", "left"
        };
        send_bridge(active_app, "ACTION", "physical_rotation", rotations[choice]);
        show_toast(active_app, "正在同步旋转面板与触摸矩阵…");
    }
}

static void panel_adjust_event(lv_event_t *event)
{
    const char *delta_text = lv_event_get_user_data(event);
    int delta = delta_text != NULL ? atoi(delta_text) : 0;
    char value[32];
    const char *action = NULL;
    int next;
    if(active_app == NULL || (delta != -1 && delta != 1)) return;
    if(active_app->active_panel == PANEL_AUDIO) {
        next = clamp_integer(active_app->audio_volume + delta * 5, 0, 100);
        active_app->audio_volume = next;
        action = "audio_volume";
    }
    else if(active_app->active_panel == PANEL_DEVELOPER) {
        next = clamp_integer(active_app->developer_fps + delta * 5, 5, 60);
        active_app->developer_fps = next;
        action = "developer_fps";
    }
    else return;
    (void)snprintf(value, sizeof(value), "%d", next);
    send_bridge(active_app, "ACTION", action, value);
    update_visible(active_app);
}

static void panel_input_apply_event(lv_event_t *event)
{
    const char *action = NULL;
    const char *first;
    const char *second;
    char value[640];
    if(active_app == NULL || active_app->input_value == NULL) return;
    first = lv_textarea_get_text(active_app->input_value);
    second = active_app->input_secret != NULL
                 ? lv_textarea_get_text(active_app->input_secret) : "";
    switch(active_app->active_panel) {
    case PANEL_REGIONAL: action = "regional_timezone"; break;
    case PANEL_DISPLAY: action = "display_set_insets"; break;
    case PANEL_AUDIO: action = "audio_player_config"; break;
    default: break;
    }
    if(action == NULL) return;
    (void)snprintf(value, sizeof(value), "%s\x1f%s", first, second);
    send_bridge(active_app, "ACTION", action, value);
    show_toast(active_app, "正在应用…");
    (void)event;
}

static void appearance_update_visible(app_t *app);

static void appearance_choice_event(lv_event_t *event)
{
    const char *choice = lv_event_get_user_data(event);
    const char *separator;
    char field[32];
    size_t length;
    if(active_app == NULL || choice == NULL) return;
    separator = strchr(choice, '=');
    if(separator == NULL) return;
    length = (size_t)(separator - choice);
    if(length == 0U || length >= sizeof(field)) return;
    memcpy(field, choice, length);
    field[length] = '\0';
    if(strcmp(field, "orientation") == 0) {
        copy_text(active_app->desktop.orientation,
                  sizeof(active_app->desktop.orientation), separator + 1);
        send_bridge(active_app, "ACTION", "appearance_orientation", separator + 1);
    }
    else if(strcmp(field, "layout") == 0) {
        copy_text(active_app->desktop.layout,
                  sizeof(active_app->desktop.layout), separator + 1);
        send_bridge(active_app, "ACTION", "appearance_set_layout", separator + 1);
    }
    else if(strcmp(field, "navigation_mode") == 0) {
        copy_text(active_app->desktop.navigation_mode,
                  sizeof(active_app->desktop.navigation_mode), separator + 1);
        send_bridge(active_app, "ACTION", "appearance_set_navigation_mode", separator + 1);
    }
    else if(strcmp(field, "navigation_visibility") == 0) {
        copy_text(active_app->desktop.navigation_visibility,
                  sizeof(active_app->desktop.navigation_visibility), separator + 1);
        send_bridge(active_app, "ACTION", "appearance_set_navigation_visibility", separator + 1);
    }
    else if(strcmp(field, "status_visibility") == 0) {
        copy_text(active_app->desktop.status_visibility,
                  sizeof(active_app->desktop.status_visibility), separator + 1);
        send_bridge(active_app, "ACTION", "appearance_set_status_visibility", separator + 1);
    }
    else if(strcmp(field, "sort") == 0) {
        copy_text(active_app->desktop.sort,
                  sizeof(active_app->desktop.sort), separator + 1);
        send_bridge(active_app, "ACTION", "appearance_set_sort", separator + 1);
    }
    else return;
    appearance_update_visible(active_app);
    show_toast(active_app, "正在实时应用…");
}

static int clamp_integer(int value, int minimum, int maximum)
{
    if(value < minimum) return minimum;
    if(value > maximum) return maximum;
    return value;
}

static void appearance_adjust_event(lv_event_t *event)
{
    const char *request = lv_event_get_user_data(event);
    const char *separator;
    char field[32];
    char value[24];
    int *target = NULL;
    int minimum = 0;
    int maximum = 0;
    int next;
    size_t length;
    if(active_app == NULL || request == NULL) return;
    separator = strchr(request, '=');
    if(separator == NULL) return;
    length = (size_t)(separator - request);
    if(length == 0U || length >= sizeof(field)) return;
    memcpy(field, request, length);
    field[length] = '\0';
    if(strcmp(field, "icon_size") == 0) {
        target = &active_app->desktop.icon_size; minimum = 40; maximum = 96;
    }
    else if(strcmp(field, "icon_spacing") == 0) {
        target = &active_app->desktop.icon_spacing; maximum = 48;
    }
    else if(strcmp(field, "grid_columns") == 0) {
        target = &active_app->desktop.grid_columns; maximum = 8;
    }
    else if(strcmp(field, "grid_rows") == 0) {
        target = &active_app->desktop.grid_rows; maximum = 6;
    }
    else return;
    next = clamp_integer(*target + atoi(separator + 1), minimum, maximum);
    if(next == *target) return;
    *target = next;
    (void)snprintf(value, sizeof(value), "%d", next);
    send_bridge(active_app, "ACTION", field, value);
    appearance_update_visible(active_app);
}

static void appearance_toggle_event(lv_event_t *event)
{
    const char *field = lv_event_get_user_data(event);
    lv_obj_t *object = lv_event_get_current_target(event);
    bool selected;
    if(active_app == NULL || field == NULL || object == NULL ||
       active_app->applying_snapshot) return;
    selected = lv_obj_has_state(object, LV_STATE_CHECKED);
    if(strcmp(field, "show_labels") == 0)
        active_app->desktop.show_labels = selected;
    else if(strcmp(field, "folders_enabled") == 0)
        active_app->desktop.folders_enabled = selected;
    else if(strcmp(field, "large_folders_enabled") == 0)
        active_app->desktop.large_folders_enabled = selected;
    else if(strcmp(field, "acrylic") == 0)
        active_app->desktop.acrylic = selected;
    else if(strcmp(field, "animations_enabled") == 0)
        active_app->desktop.animations_enabled = selected;
    else if(strcmp(field, "reduce_motion") == 0)
        active_app->desktop.reduce_motion = selected;
    else return;
    send_bridge(active_app, "ACTION", field, selected ? "1" : "0");
    show_toast(active_app, "正在实时应用…");
}

static void appearance_apply_wallpaper_event(lv_event_t *event)
{
    const char *color;
    const char *accent;
    const char *path;
    char request[1080];
    (void)event;
    if(active_app == NULL || active_app->appearance_wallpaper_color == NULL ||
       active_app->appearance_accent_color == NULL ||
       active_app->appearance_wallpaper_path == NULL) return;
    color = lv_textarea_get_text(active_app->appearance_wallpaper_color);
    accent = lv_textarea_get_text(active_app->appearance_accent_color);
    path = lv_textarea_get_text(active_app->appearance_wallpaper_path);
    (void)snprintf(request, sizeof(request), "%.7s\x1f%.7s\x1f%s",
                   color, accent, path);
    send_bridge(active_app, "ACTION", "appearance_wallpaper", request);
    show_toast(active_app, "正在应用壁纸…");
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

static bool bind_textarea(app_t *app, lv_obj_t *textarea)
{
    if(textarea == NULL) return true;
    if(msys_ui_surface_bind_textarea(app->surface, textarea)) return true;
    fprintf(stderr, "settings-lvgl: cannot bind textarea input\n");
    return false;
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
       lv_xml_register_font(scope, "symbols_16",
                            &lv_font_montserrat_16) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "settings_press", xml_press_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "settings_navigate", xml_navigate_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "settings_back", xml_back_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "settings_toggle", xml_toggle_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "settings_refresh", xml_refresh_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "settings_calibration", xml_calibration_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "panel_primary", panel_primary_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "panel_secondary", panel_secondary_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "panel_choice", panel_choice_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "panel_choice2", panel_choice2_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "panel_adjust", panel_adjust_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "panel_input_apply", panel_input_apply_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "appearance_choice", appearance_choice_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "appearance_adjust", appearance_adjust_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "appearance_toggle", appearance_toggle_event) != LV_RESULT_OK ||
       lv_xml_register_event_cb(scope, "appearance_apply_wallpaper", appearance_apply_wallpaper_event) != LV_RESULT_OK ||
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
    if(app->toast == NULL && !create_toast(app))
        fprintf(stderr, "settings-lvgl: toast-create-failed\n");
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
    app->appearance_page = ui_object(app, "appearance_page");
    app->appearance_status = ui_object(app, "appearance_status");
    app->appearance_layout[0] = ui_object(app, "layout_profile");
    app->appearance_layout[1] = ui_object(app, "layout_mobile");
    app->appearance_layout[2] = ui_object(app, "layout_desktop");
    app->appearance_layout[3] = ui_object(app, "layout_kiosk");
    app->appearance_layout[4] = ui_object(app, "layout_embedded");
    app->appearance_sort[0] = ui_object(app, "sort_name");
    app->appearance_sort[1] = ui_object(app, "sort_component");
    app->appearance_navigation[0] = ui_object(app, "navigation_buttons");
    app->appearance_navigation[1] = ui_object(app, "navigation_pill");
    app->appearance_navigation_visibility[0] = ui_object(app, "navigation_visibility_always");
    app->appearance_navigation_visibility[1] = ui_object(app, "navigation_visibility_auto");
    app->appearance_status_visibility[0] = ui_object(app, "status_visibility_always");
    app->appearance_status_visibility[1] = ui_object(app, "status_visibility_auto");
    app->appearance_orientation[0] = ui_object(app, "orientation_auto");
    app->appearance_orientation[1] = ui_object(app, "orientation_portrait");
    app->appearance_orientation[2] = ui_object(app, "orientation_landscape");
    app->appearance_icon_size = ui_object(app, "icon_size_value");
    app->appearance_icon_spacing = ui_object(app, "icon_spacing_value");
    app->appearance_grid_columns = ui_object(app, "grid_columns_value");
    app->appearance_grid_rows = ui_object(app, "grid_rows_value");
    app->appearance_wallpaper_color = ui_object(app, "wallpaper_color_input");
    app->appearance_accent_color = ui_object(app, "accent_color_input");
    app->appearance_wallpaper_path = ui_object(app, "wallpaper_path_input");
    app->appearance_switches[0] = ui_object(app, "show_labels_switch");
    app->appearance_switches[1] = ui_object(app, "folders_switch");
    app->appearance_switches[2] = ui_object(app, "large_folders_switch");
    app->appearance_switches[3] = ui_object(app, "acrylic_switch");
    app->appearance_switches[4] = ui_object(app, "animations_switch");
    app->appearance_switches[5] = ui_object(app, "reduce_motion_switch");
    app->detail_title = ui_object(app, "detail_title");
    app->detail_note = ui_object(app, "detail_note");
    app->detail_summary = ui_object(app, "detail_summary");
    app->detail_label = ui_object(app, "detail_text");
    app->toggle_row = ui_object(app, "toggle_row");
    app->toggle = ui_object(app, "panel_toggle");
    app->action_primary = ui_object(app, "action_primary");
    app->action_primary_label = ui_object(app, "action_primary_label");
    app->action_secondary = ui_object(app, "action_secondary");
    app->action_secondary_label = ui_object(app, "action_secondary_label");
    app->choice_row = ui_object(app, "choice_row");
    app->choice2_row = ui_object(app, "choice2_row");
    app->adjust_row = ui_object(app, "adjust_row");
    app->adjust_label = ui_object(app, "adjust_label");
    app->adjust_value = ui_object(app, "adjust_value");
    app->input_card = ui_object(app, "input_card");
    app->input_label = ui_object(app, "input_label");
    app->input_secondary_label = ui_object(app, "input_secondary_label");
    app->input_value = ui_object(app, "input_value");
    app->input_secret = ui_object(app, "input_secret");
    app->input_apply = ui_object(app, "input_apply");
    app->input_apply_label = ui_object(app, "input_apply_label");
    app->dynamic_list = ui_object(app, "dynamic_list");
    if(!bind_textarea(app, app->input_value) ||
       !bind_textarea(app, app->input_secret) ||
       !bind_textarea(app, app->appearance_wallpaper_color) ||
       !bind_textarea(app, app->appearance_accent_color) ||
       !bind_textarea(app, app->appearance_wallpaper_path))
        return;
    for(index = 0; index < 4; index++) {
        char name[32];
        (void)snprintf(name, sizeof(name), "choice_%d", index);
        app->choice_buttons[index] = ui_object(app, name);
        (void)snprintf(name, sizeof(name), "choice_%d_label", index);
        app->choice_labels[index] = ui_object(app, name);
        (void)snprintf(name, sizeof(name), "choice2_%d", index);
        app->choice2_buttons[index] = ui_object(app, name);
        (void)snprintf(name, sizeof(name), "choice2_%d_label", index);
        app->choice2_labels[index] = ui_object(app, name);
    }
    app->calibration_button = ui_object(app, "calibration_button");
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
        if(app->home_page != NULL) {
            lv_obj_set_scroll_dir(app->home_page, LV_DIR_VER);
            lv_obj_set_scrollbar_mode(app->home_page, LV_SCROLLBAR_MODE_AUTO);
        }
        if(app->detail_page != NULL) {
            lv_obj_set_scroll_dir(app->detail_page, LV_DIR_VER);
            lv_obj_set_scrollbar_mode(app->detail_page, LV_SCROLLBAR_MODE_AUTO);
        }
        if(app->appearance_page != NULL) {
            lv_obj_set_scroll_dir(app->appearance_page, LV_DIR_VER);
            lv_obj_set_scrollbar_mode(app->appearance_page,
                                      LV_SCROLLBAR_MODE_AUTO);
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

static void set_choice_selected(lv_obj_t *object, bool selected)
{
    lv_color_t color;
    lv_obj_t *label;
    if(object == NULL) return;
    color = lv_color_hex(selected ? 0x356ae6U : 0xeef2f8U);
    if(!lv_color_eq(lv_obj_get_style_bg_color(object, LV_PART_MAIN), color))
        lv_obj_set_style_bg_color(object, color, LV_PART_MAIN);
    label = lv_obj_get_child(object, 0);
    if(label != NULL)
        lv_obj_set_style_text_color(
            label, lv_color_hex(selected ? 0xffffffU : 0x28405fU), LV_PART_MAIN);
}

static void set_switch_value(lv_obj_t *object, bool selected)
{
    if(object == NULL) return;
    if(selected && !lv_obj_has_state(object, LV_STATE_CHECKED))
        lv_obj_add_state(object, LV_STATE_CHECKED);
    else if(!selected && lv_obj_has_state(object, LV_STATE_CHECKED))
        lv_obj_remove_state(object, LV_STATE_CHECKED);
}

static void set_textarea_text(lv_obj_t *object, const char *value)
{
    if(object == NULL || value == NULL) return;
    if(strcmp(lv_textarea_get_text(object), value) != 0)
        lv_textarea_set_text(object, value);
}

static void appearance_update_visible(app_t *app)
{
    char text[64];
    const bool switches[6] = {
        app->desktop.show_labels,
        app->desktop.folders_enabled,
        app->desktop.large_folders_enabled,
        app->desktop.acrylic,
        app->desktop.animations_enabled,
        app->desktop.reduce_motion,
    };
    size_t index;
    set_label_text(app->appearance_status,
        app->desktop.available
            ? "已连接 Launcher 与 Window Manager；设置实时生效"
            : "Launcher 或 Window Manager 当前不可用；未伪造本地状态");
    set_choice_selected(app->appearance_layout[0],
                        strcmp(app->desktop.layout, "profile") == 0 ||
                        strcmp(app->desktop.layout, "auto") == 0);
    set_choice_selected(app->appearance_layout[1],
                        strcmp(app->desktop.layout, "mobile") == 0);
    set_choice_selected(app->appearance_layout[2],
                        strcmp(app->desktop.layout, "desktop") == 0);
    set_choice_selected(app->appearance_layout[3],
                        strcmp(app->desktop.layout, "kiosk") == 0);
    set_choice_selected(app->appearance_layout[4],
                        strcmp(app->desktop.layout, "embedded") == 0);
    set_choice_selected(app->appearance_sort[0],
                        strcmp(app->desktop.sort, "name") == 0);
    set_choice_selected(app->appearance_sort[1],
                        strcmp(app->desktop.sort, "component") == 0);
    set_choice_selected(app->appearance_navigation[0],
                        strcmp(app->desktop.navigation_mode, "buttons") == 0);
    set_choice_selected(app->appearance_navigation[1],
                        strcmp(app->desktop.navigation_mode, "pill") == 0);
    set_choice_selected(app->appearance_navigation_visibility[0],
                        strcmp(app->desktop.navigation_visibility, "always") == 0);
    set_choice_selected(app->appearance_navigation_visibility[1],
                        strcmp(app->desktop.navigation_visibility, "auto-hide") == 0);
    set_choice_selected(app->appearance_status_visibility[0],
                        strcmp(app->desktop.status_visibility, "always") == 0);
    set_choice_selected(app->appearance_status_visibility[1],
                        strcmp(app->desktop.status_visibility, "auto-hide") == 0);
    set_choice_selected(app->appearance_orientation[0],
                        strcmp(app->desktop.orientation, "auto") == 0);
    set_choice_selected(app->appearance_orientation[1],
                        strcmp(app->desktop.orientation, "portrait") == 0);
    set_choice_selected(app->appearance_orientation[2],
                        strcmp(app->desktop.orientation, "landscape") == 0);
    (void)snprintf(text, sizeof(text), "%d px", app->desktop.icon_size);
    set_label_text(app->appearance_icon_size, text);
    (void)snprintf(text, sizeof(text), "%d px", app->desktop.icon_spacing);
    set_label_text(app->appearance_icon_spacing, text);
    if(app->desktop.grid_columns == 0) copy_text(text, sizeof(text), "自动");
    else (void)snprintf(text, sizeof(text), "%d", app->desktop.grid_columns);
    set_label_text(app->appearance_grid_columns, text);
    if(app->desktop.grid_rows == 0) copy_text(text, sizeof(text), "自动");
    else (void)snprintf(text, sizeof(text), "%d", app->desktop.grid_rows);
    set_label_text(app->appearance_grid_rows, text);
    set_textarea_text(app->appearance_wallpaper_color,
                      app->desktop.wallpaper_color);
    set_textarea_text(app->appearance_accent_color,
                      app->desktop.accent_color);
    set_textarea_text(app->appearance_wallpaper_path,
                      app->desktop.wallpaper_path);
    app->applying_snapshot = true;
    for(index = 0U; index < 6U; index++)
        set_switch_value(app->appearance_switches[index], switches[index]);
    app->applying_snapshot = false;
}

static void set_hidden(lv_obj_t *object, bool hidden)
{
    if(object != NULL) lv_obj_set_flag(object, LV_OBJ_FLAG_HIDDEN, hidden);
}

static void set_choice_labels(app_t *app, const char *a, const char *b,
                              const char *c, const char *d)
{
    const char *values[4] = {a, b, c, d};
    int index;
    for(index = 0; index < 4; index++) {
        set_label_text(app->choice_labels[index], values[index]);
        set_hidden(app->choice_buttons[index], values[index] == NULL || values[index][0] == '\0');
    }
}

static void set_choice2_labels(app_t *app, const char *a, const char *b,
                               const char *c, const char *d)
{
    const char *values[4] = {a, b, c, d};
    int index;
    for(index = 0; index < 4; index++) {
        set_label_text(app->choice2_labels[index], values[index]);
        set_hidden(app->choice2_buttons[index],
                   values[index] == NULL || values[index][0] == '\0');
    }
}

static void setting_item_event(lv_event_t *event)
{
    setting_item_t *item = lv_event_get_user_data(event);
    lv_obj_t *current = lv_event_get_current_target(event);
    lv_obj_t *parent;
    uint32_t index;
    bool expand;
    if(active_app == NULL || item == NULL) return;
    expand = strcmp(active_app->selected_item, item->id) != 0 ||
             !lv_obj_has_state(current, LV_STATE_USER_1);
    copy_text(active_app->selected_item, sizeof(active_app->selected_item), item->id);
    if(active_app->input_value != NULL)
        set_textarea_text(active_app->input_value, item->label);
    parent = current != NULL ? lv_obj_get_parent(current) : NULL;
    if(parent != NULL) {
        for(index = 0U; index < lv_obj_get_child_count(parent); index++) {
            lv_obj_t *row = lv_obj_get_child(parent, (int32_t)index);
            lv_obj_t *text = lv_obj_get_child(row, 0);
            lv_obj_t *marker = lv_obj_get_child(row, 1);
            lv_obj_set_style_bg_color(row, lv_color_hex(0xffffff), LV_PART_MAIN);
            lv_obj_set_style_border_color(row, lv_color_hex(0xdfe4ee), LV_PART_MAIN);
            lv_obj_remove_state(row, LV_STATE_USER_1);
            lv_obj_set_height(row, 62);
            if(text != NULL && lv_obj_get_child_count(text) >= 2U) {
                lv_label_set_long_mode(lv_obj_get_child(text, 0), LV_LABEL_LONG_DOT);
                lv_label_set_long_mode(lv_obj_get_child(text, 1), LV_LABEL_LONG_DOT);
            }
            if(marker != NULL) lv_label_set_text(marker, LV_SYMBOL_RIGHT);
        }
    }
    if(current != NULL) {
        lv_obj_set_style_bg_color(current, lv_color_hex(0xe7edfb), LV_PART_MAIN);
        lv_obj_set_style_border_color(current, lv_color_hex(0x7d9fe9), LV_PART_MAIN);
        if(expand) {
            lv_obj_t *text = lv_obj_get_child(current, 0);
            lv_obj_add_state(current, LV_STATE_USER_1);
            lv_obj_set_height(current, 92);
            if(text != NULL && lv_obj_get_child_count(text) >= 2U) {
                lv_label_set_long_mode(lv_obj_get_child(text, 0), LV_LABEL_LONG_WRAP);
                lv_label_set_long_mode(lv_obj_get_child(text, 1), LV_LABEL_LONG_WRAP);
            }
        }
        {
            lv_obj_t *marker = lv_obj_get_child(current, 1);
            if(marker != NULL) lv_label_set_text(marker, LV_SYMBOL_OK);
        }
    }
}

static void render_setting_items(app_t *app)
{
    size_t index;
    char last_category[128] = "";
    if(app->dynamic_list == NULL || !app->items_changed) return;
    lv_obj_clean(app->dynamic_list);
    for(index = 0U; index < app->item_count; index++) {
        setting_item_t *item = &app->items[index];
        if(strcmp(app->items_panel, "hal") == 0 ||
           strcmp(app->items_panel, "roles") == 0) {
            const char *separator = strchr(item->id, '\x1f');
            size_t length = separator != NULL
                                ? (size_t)(separator - item->id)
                                : strlen(item->id);
            if(length >= sizeof(last_category)) length = sizeof(last_category) - 1U;
            if(length > 0U &&
               (strncmp(last_category, item->id, length) != 0 ||
                last_category[length] != '\0')) {
                lv_obj_t *header = lv_label_create(app->dynamic_list);
                memcpy(last_category, item->id, length);
                last_category[length] = '\0';
                lv_label_set_text(header, last_category);
                lv_obj_set_width(header, LV_PCT(100));
                lv_obj_set_height(header, LV_SIZE_CONTENT);
                lv_obj_set_style_pad_top(header, 6, LV_PART_MAIN);
                lv_obj_set_style_pad_bottom(header, 1, LV_PART_MAIN);
                lv_obj_set_style_text_font(header,
                                           msys_ui_theme_font(app->theme, 12),
                                           LV_PART_MAIN);
                lv_obj_set_style_text_color(header, lv_color_hex(0x526071),
                                            LV_PART_MAIN);
            }
        }
        lv_obj_t *row = lv_obj_create(app->dynamic_list);
        lv_obj_t *text = lv_obj_create(row);
        lv_obj_t *label = lv_label_create(text);
        lv_obj_t *meta = lv_label_create(text);
        lv_obj_t *marker = lv_label_create(row);
        bool selected = strcmp(app->selected_item, item->id) == 0;
        lv_obj_set_width(row, LV_PCT(100));
        lv_obj_set_height(row, 62);
        lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START,
                              LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        lv_obj_set_style_bg_color(row, lv_color_hex(selected ? 0xe7edfb : 0xffffff), LV_PART_MAIN);
        lv_obj_set_style_bg_opa(row, LV_OPA_COVER, LV_PART_MAIN);
        lv_obj_set_style_border_width(row, 1, LV_PART_MAIN);
        lv_obj_set_style_border_color(row, lv_color_hex(selected ? 0x7d9fe9 : 0xdfe4ee), LV_PART_MAIN);
        lv_obj_set_style_radius(row, 14, LV_PART_MAIN);
        lv_obj_set_style_pad_all(row, 9, LV_PART_MAIN);
        lv_obj_add_flag(row, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(row, setting_item_event, LV_EVENT_CLICKED, item);
        lv_obj_add_event_cb(row, xml_press_event, LV_EVENT_ALL, NULL);
        lv_obj_set_flex_grow(text, 1);
        lv_obj_set_height(text, LV_SIZE_CONTENT);
        lv_obj_set_flex_flow(text, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_style_bg_opa(text, LV_OPA_TRANSP, LV_PART_MAIN);
        lv_obj_set_style_border_width(text, 0, LV_PART_MAIN);
        lv_obj_set_style_pad_all(text, 0, LV_PART_MAIN);
        lv_label_set_text(label, item->label);
        lv_obj_set_width(label, LV_PCT(100));
        lv_label_set_long_mode(label, LV_LABEL_LONG_DOT);
        lv_obj_set_style_text_font(label, msys_ui_theme_font(app->theme, 14), LV_PART_MAIN);
        lv_obj_set_style_text_color(label, lv_color_hex(0x182033), LV_PART_MAIN);
        lv_label_set_text(meta, item->meta);
        lv_obj_set_width(meta, LV_PCT(100));
        lv_label_set_long_mode(meta, LV_LABEL_LONG_DOT);
        lv_obj_set_style_text_font(meta, msys_ui_theme_font(app->theme, 12), LV_PART_MAIN);
        lv_obj_set_style_text_color(meta, lv_color_hex(0x667085), LV_PART_MAIN);
        lv_label_set_text(marker, selected ? LV_SYMBOL_OK : LV_SYMBOL_RIGHT);
        lv_obj_set_style_text_font(marker, &lv_font_montserrat_16, LV_PART_MAIN);
        lv_obj_set_style_text_color(marker, lv_color_hex(0x356ae6), LV_PART_MAIN);
    }
    app->items_changed = false;
}

static void update_panel_controls(app_t *app)
{
    panel_t *panel = &app->panels[app->active_panel];
    char value[48];
    bool primary = false;
    bool secondary = false;
    bool choices = false;
    bool choices2 = false;
    bool adjustment = false;
    bool inputs = false;
    bool secret = false;
    const char *primary_label = "";
    const char *secondary_label = "";
    const char *input_label = "";
    const char *secondary_input_label = "";
    const char *apply_label = "应用";

    switch(app->active_panel) {
    case PANEL_WIFI:
        primary = secondary = choices = inputs = secret = true;
        primary_label = "扫描网络";
        secondary_label = "断开连接";
        input_label = "所选网络的密码（开放/已保存网络留空）";
        apply_label = "连接 Wi-Fi";
        set_choice_labels(app, "连接选中网络", "忘记选中网络", "", "");
        break;
    case PANEL_BLUETOOTH:
        primary = choices = true;
        primary_label = "扫描蓝牙设备（15 秒）";
        set_choice_labels(app, "配对", "连接", "断开", "忘记");
        break;
    case PANEL_AUDIO:
        primary = adjustment = choices = inputs = secret = true;
        primary_label = "使用选中的音频输出";
        input_label = "Squeezelite 服务器（留空为自动发现）";
        secondary_input_label = "播放器名称";
        apply_label = "保存播放器配置";
        set_choice_labels(app, "启用播放器", "停用播放器", "", "");
        set_label_text(app->adjust_label, "播放音量");
        (void)snprintf(value, sizeof(value), "%d%%", app->audio_volume);
        set_label_text(app->adjust_value, value);
        break;
    case PANEL_DISPLAY:
        choices = inputs = true;
        choices2 = app->physical_rotation_writable;
        input_label = "安全区域（auto 或 top,right,bottom,left）";
        apply_label = "应用安全区域";
        set_choice_labels(app, "手机", "单应用", "桌面", "");
        set_choice2_labels(app, "面板正常", "面板右转", "面板倒置", "面板左转");
        break;
    case PANEL_INPUT:
        primary = choices = true;
        primary_label = "显示触摸键盘";
        set_choice_labels(app, "English", "中文拼音", "数字", "符号");
        break;
    case PANEL_STORAGE:
        primary = choices = true;
        primary_label = "重新扫描存储设备";
        set_choice_labels(app, "挂载选中卷", "卸载选中卷", "", "");
        break;
    case PANEL_REGIONAL:
        choices = inputs = true;
        input_label = "时区（例如 Asia/Shanghai）";
        apply_label = "应用时区";
        set_choice_labels(app, "跟随系统", "简体中文", "English", "");
        break;
    case PANEL_APPS:
        primary = true;
        primary_label = "打开软件中心";
        break;
    case PANEL_UPDATES:
        primary = true;
        primary_label = "打开更新与回退";
        break;
    case PANEL_HAL:
        choices = app->hal_mutable;
        set_choice_labels(app, "使用选中提供者", "恢复该域默认", "", "");
        break;
    case PANEL_ROLES:
        choices = true;
        set_choice_labels(app, "使用选中提供者", "恢复该角色默认", "", "");
        break;
    case PANEL_DEVELOPER:
        primary = secondary = adjustment = true;
        primary_label = app->developer_debug ? "关闭调试叠加层" : "打开调试叠加层";
        secondary_label = app->developer_cursor ? "关闭触摸光标" : "打开触摸光标";
        set_label_text(app->adjust_label, "捕捉上限");
        (void)snprintf(value, sizeof(value), "%d FPS", app->developer_fps);
        set_label_text(app->adjust_value, value);
        break;
    default:
        break;
    }
    set_label_text(app->action_primary_label, primary_label);
    set_label_text(app->action_secondary_label, secondary_label);
    set_label_text(app->input_label, input_label);
    set_label_text(app->input_secondary_label, secondary_input_label);
    set_label_text(app->input_apply_label, apply_label);
    set_hidden(app->action_primary, !primary);
    set_hidden(app->action_secondary, !secondary);
    set_hidden(app->choice_row, !choices);
    set_hidden(app->choice2_row, !choices2);
    set_hidden(app->adjust_row, !adjustment);
    set_hidden(app->input_card, !inputs);
    set_hidden(app->input_secret, !secret);
    set_hidden(app->input_secondary_label, !secret || secondary_input_label[0] == '\0');
    set_hidden(app->input_value, app->active_panel == PANEL_WIFI);
    set_hidden(app->input_apply, app->active_panel == PANEL_WIFI);
    if(inputs && app->active_panel == PANEL_REGIONAL)
        set_textarea_text(app->input_value, app->regional_timezone);
    else if(inputs && app->active_panel == PANEL_DISPLAY)
        set_textarea_text(app->input_value, app->display_insets);
    else if(inputs && app->active_panel == PANEL_AUDIO) {
        set_textarea_text(app->input_value, app->audio_player_server);
        set_textarea_text(app->input_secret, app->audio_player_name);
    }
    if(app->input_secret != NULL)
        lv_textarea_set_password_mode(app->input_secret,
                                      app->active_panel == PANEL_WIFI);
    if(app->input_value != NULL)
        lv_textarea_set_placeholder_text(app->input_value,
            app->active_panel == PANEL_DISPLAY ? "auto / 0,0,42,0" :
            app->active_panel == PANEL_AUDIO ? "192.168.1.2" :
            app->active_panel == PANEL_REGIONAL ? "Asia/Shanghai" : "输入值");
    if(app->input_secret != NULL)
        lv_textarea_set_placeholder_text(app->input_secret,
            app->active_panel == PANEL_AUDIO ? "MSYS Audio" : "Wi-Fi 密码");
    if(app->active_panel == PANEL_DISPLAY) {
        set_choice_selected(app->choice_buttons[0], strcmp(app->display_profile, "mobile") == 0);
        set_choice_selected(app->choice_buttons[1], strcmp(app->display_profile, "kiosk") == 0);
        set_choice_selected(app->choice_buttons[2], strcmp(app->display_profile, "desktop") == 0);
        set_choice_selected(app->choice2_buttons[0], strcmp(app->physical_rotation, "normal") == 0);
        set_choice_selected(app->choice2_buttons[1], strcmp(app->physical_rotation, "right") == 0);
        set_choice_selected(app->choice2_buttons[2], strcmp(app->physical_rotation, "inverted") == 0);
        set_choice_selected(app->choice2_buttons[3], strcmp(app->physical_rotation, "left") == 0);
    }
    else if(app->active_panel == PANEL_INPUT) {
        set_choice_selected(app->choice_buttons[0], strcmp(app->input_mode, "en") == 0);
        set_choice_selected(app->choice_buttons[1], strcmp(app->input_mode, "zh") == 0);
        set_choice_selected(app->choice_buttons[2], strcmp(app->input_mode, "numeric") == 0);
        set_choice_selected(app->choice_buttons[3], strcmp(app->input_mode, "symbols") == 0);
    }
    else if(app->active_panel == PANEL_AUDIO) {
        set_choice_selected(app->choice_buttons[0], app->audio_player_enabled);
        set_choice_selected(app->choice_buttons[1], !app->audio_player_enabled);
    }
    if(panel->toggle_available && app->toggle != NULL) {
        app->applying_snapshot = true;
        set_switch_value(app->toggle, panel->toggle_value);
        app->applying_snapshot = false;
    }
    set_hidden(app->dynamic_list,
               app->item_count == 0U || strcmp(app->items_panel, panel->id) != 0);
    if(app->active_panel == PANEL_AUDIO)
        software_set_disabled(app->action_primary, app->selected_item[0] == '\0');
    if(app->active_panel == PANEL_WIFI || app->active_panel == PANEL_BLUETOOTH ||
       app->active_panel == PANEL_STORAGE || app->active_panel == PANEL_HAL ||
       app->active_panel == PANEL_ROLES) {
        int index;
        for(index = 0; index < 4; index++)
            software_set_disabled(app->choice_buttons[index],
                                  app->selected_item[0] == '\0');
    }
    render_setting_items(app);
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
                        app->active_panel < 0 ||
                        app->active_panel == PANEL_APPEARANCE);
    if(app->appearance_page != NULL)
        lv_obj_set_flag(app->appearance_page, LV_OBJ_FLAG_HIDDEN,
                        app->active_panel != PANEL_APPEARANCE);
    set_label_text(app->status_label, app->status);
    if(app->active_panel < 0) {
        for(index = 0; index < PANEL_COUNT; index++)
            set_label_text(app->summary_labels[index], app->panels[index].summary);
        return;
    }
    if(app->active_panel == PANEL_APPEARANCE) {
        /* Keep the appearance page as a real, full-workarea scroll surface.
         * Some LVGL XML builds retain the initial hidden/layout state when a
         * sibling page is first revealed; explicitly re-apply it here so the
         * desktop settings page never becomes a blank sibling overlay. */
        if(app->appearance_page != NULL) {
            lv_obj_remove_flag(app->appearance_page, LV_OBJ_FLAG_HIDDEN);
            lv_obj_set_pos(app->appearance_page, 0, 0);
            lv_obj_set_width(app->appearance_page, LV_PCT(100));
            lv_obj_set_height(app->appearance_page, LV_PCT(100));
            lv_obj_set_scroll_dir(app->appearance_page, LV_DIR_VER);
            lv_obj_set_scrollbar_mode(app->appearance_page,
                                      LV_SCROLLBAR_MODE_AUTO);
        }
        if(app->home_page != NULL)
            lv_obj_add_flag(app->home_page, LV_OBJ_FLAG_HIDDEN);
        if(app->detail_page != NULL)
            lv_obj_add_flag(app->detail_page, LV_OBJ_FLAG_HIDDEN);
        fprintf(stderr,
                "settings-lvgl: appearance geometry page=%p hidden=%d pos=%d,%d size=%dx%d children=%u status=%p\n",
                (void *)app->appearance_page,
                app->appearance_page != NULL &&
                    lv_obj_has_flag(app->appearance_page, LV_OBJ_FLAG_HIDDEN),
                app->appearance_page != NULL ? (int)lv_obj_get_x(app->appearance_page) : -1,
                app->appearance_page != NULL ? (int)lv_obj_get_y(app->appearance_page) : -1,
                app->appearance_page != NULL ? (int)lv_obj_get_width(app->appearance_page) : -1,
                app->appearance_page != NULL ? (int)lv_obj_get_height(app->appearance_page) : -1,
                app->appearance_page != NULL ? (unsigned)lv_obj_get_child_count(app->appearance_page) : 0U,
                (void *)app->appearance_status);
        appearance_update_visible(app);
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
    update_panel_controls(app);
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

static bool apply_appearance_field(app_t *app, const char *key,
                                   const char *value)
{
    const char *field;
    int parsed;
    if(strcmp(key, "appearance.orientation") == 0)
        return replace_text(app->desktop.orientation,
                            sizeof(app->desktop.orientation), value);
    if(strcmp(key, "appearance.contract.available") == 0) {
        bool next = parse_bool(value);
        if(app->desktop.available == next) return false;
        app->desktop.available = next;
        return true;
    }
    if(strncmp(key, "appearance.preference.", 22U) != 0) return false;
    field = key + 22U;
    if(strcmp(field, "layout") == 0)
        return replace_text(app->desktop.layout,
                            sizeof(app->desktop.layout), value);
    if(strcmp(field, "navigation_mode") == 0)
        return replace_text(app->desktop.navigation_mode,
                            sizeof(app->desktop.navigation_mode), value);
    if(strcmp(field, "navigation_visibility") == 0)
        return replace_text(app->desktop.navigation_visibility,
                            sizeof(app->desktop.navigation_visibility), value);
    if(strcmp(field, "status_visibility") == 0)
        return replace_text(app->desktop.status_visibility,
                            sizeof(app->desktop.status_visibility), value);
    if(strcmp(field, "wallpaper_color") == 0)
        return replace_text(app->desktop.wallpaper_color,
                            sizeof(app->desktop.wallpaper_color), value);
    if(strcmp(field, "accent_color") == 0)
        return replace_text(app->desktop.accent_color,
                            sizeof(app->desktop.accent_color), value);
    if(strcmp(field, "wallpaper_path") == 0)
        return replace_text(app->desktop.wallpaper_path,
                            sizeof(app->desktop.wallpaper_path), value);
    if(strcmp(field, "sort") == 0)
        return replace_text(app->desktop.sort,
                            sizeof(app->desktop.sort), value);
    if(strcmp(field, "icon_size") == 0) {
        parsed = atoi(value);
        if(app->desktop.icon_size == parsed) return false;
        app->desktop.icon_size = parsed;
        return true;
    }
    if(strcmp(field, "icon_spacing") == 0) {
        parsed = atoi(value);
        if(app->desktop.icon_spacing == parsed) return false;
        app->desktop.icon_spacing = parsed;
        return true;
    }
    if(strcmp(field, "grid_columns") == 0) {
        parsed = atoi(value);
        if(app->desktop.grid_columns == parsed) return false;
        app->desktop.grid_columns = parsed;
        return true;
    }
    if(strcmp(field, "grid_rows") == 0) {
        parsed = atoi(value);
        if(app->desktop.grid_rows == parsed) return false;
        app->desktop.grid_rows = parsed;
        return true;
    }
#define APPLY_DESKTOP_BOOL(NAME, MEMBER) do { \
        if(strcmp(field, NAME) == 0) { \
            bool next = parse_bool(value); \
            if(app->desktop.MEMBER == next) return false; \
            app->desktop.MEMBER = next; \
            return true; \
        } \
    } while(0)
    APPLY_DESKTOP_BOOL("show_labels", show_labels);
    APPLY_DESKTOP_BOOL("folders_enabled", folders_enabled);
    APPLY_DESKTOP_BOOL("large_folders_enabled", large_folders_enabled);
    APPLY_DESKTOP_BOOL("acrylic", acrylic);
    APPLY_DESKTOP_BOOL("animations_enabled", animations_enabled);
    APPLY_DESKTOP_BOOL("reduce_motion", reduce_motion);
#undef APPLY_DESKTOP_BOOL
    return false;
}

static void apply_field(app_t *app, char *key, char *value)
{
    char *dot;
    panel_t *panel;
    percent_decode(value);
    if(strcmp(key, "items.panel") == 0) {
        copy_text(app->items_panel, sizeof(app->items_panel), value);
        app->item_count = 0U;
        app->selected_item[0] = '\0';
        app->items_changed = true;
        app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "items.count") == 0) {
        unsigned long count = strtoul(value, NULL, 10);
        app->item_count = count > SETTINGS_MAX_ITEMS ? SETTINGS_MAX_ITEMS : (size_t)count;
        app->items_changed = true;
        app->snapshot_changed = true;
        return;
    }
    if(strncmp(key, "items.", 6U) == 0 && key[6] >= '0' && key[6] <= '9') {
        char *end = NULL;
        unsigned long index = strtoul(key + 6, &end, 10);
        if(end != NULL && *end == '.' && index < SETTINGS_MAX_ITEMS) {
            setting_item_t *item = &app->items[index];
            const char *field = end + 1;
            if(strcmp(field, "id") == 0) {
                copy_text(item->id, sizeof(item->id), value);
                if(index == 0U && app->selected_item[0] == '\0')
                    copy_text(app->selected_item, sizeof(app->selected_item), value);
            }
            else if(strcmp(field, "label") == 0)
                copy_text(item->label, sizeof(item->label), value);
            else if(strcmp(field, "meta") == 0)
                copy_text(item->meta, sizeof(item->meta), value);
            else return;
            app->items_changed = true;
            app->snapshot_changed = true;
        }
        return;
    }
    if(strcmp(key, "audio.volume") == 0) {
        app->audio_volume = clamp_integer(atoi(value), 0, 100);
        app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "audio.player.enabled") == 0) {
        app->audio_player_enabled = parse_bool(value);
        app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "audio.player.server") == 0) {
        copy_text(app->audio_player_server, sizeof(app->audio_player_server), value);
        app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "audio.player.name") == 0) {
        copy_text(app->audio_player_name, sizeof(app->audio_player_name), value);
        app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "developer.fps") == 0) {
        app->developer_fps = clamp_integer(atoi(value), 5, 60);
        app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "developer.debug") == 0) {
        app->developer_debug = parse_bool(value);
        app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "developer.cursor") == 0) {
        app->developer_cursor = parse_bool(value);
        app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "regional.language") == 0) {
        copy_text(app->regional_language, sizeof(app->regional_language), value);
        app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "regional.timezone") == 0) {
        copy_text(app->regional_timezone, sizeof(app->regional_timezone), value);
        app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "display.profile") == 0) {
        copy_text(app->display_profile, sizeof(app->display_profile), value);
        app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "display.insets") == 0) {
        copy_text(app->display_insets, sizeof(app->display_insets), value);
        app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "display.physical.rotation") == 0) {
        copy_text(app->physical_rotation, sizeof(app->physical_rotation), value);
        app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "input.mode") == 0) {
        copy_text(app->input_mode, sizeof(app->input_mode), value);
        app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "display.physical.available") == 0) {
        app->physical_rotation_writable = parse_bool(value);
        app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "hal.mutable") == 0) {
        app->hal_mutable = parse_bool(value);
        app->snapshot_changed = true;
        return;
    }
    if(strcmp(key, "settings.page") == 0) {
        panel_t *selected = panel_by_id(app, value);
        app->active_panel = selected != NULL ? (int)(selected - app->panels) : -1;
        app->snapshot_changed = true;
        if(selected != NULL) send_bridge(app, "REFRESH", selected->id, "");
        return;
    }
    if(strncmp(key, "appearance.preference.", 22U) == 0 ||
       strcmp(key, "appearance.orientation") == 0 ||
       strcmp(key, "appearance.contract.available") == 0) {
        if(apply_appearance_field(app, key, value)) app->snapshot_changed = true;
        return;
    }
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
        .component_id="org.msys.settings:main", .role="application",
        .wm_instance="main", .override_redirect=false,
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
