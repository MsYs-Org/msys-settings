CC ?= cc
UI_DIR ?= ../msys-ui-lvgl
BUILD_DIR ?= build/lvgl
TARGET := $(BUILD_DIR)/msys-settings-lvgl
PACKAGE_TARGET := files/bin/msys-settings-lvgl
LICENSE_TARGET := files/share/licenses/lvgl/LICENCE.txt
UI_LIBRARY := $(UI_DIR)/build/libmsys-ui-lvgl.a
CPPFLAGS += -I$(UI_DIR)/include -I$(UI_DIR)/vendor/lvgl -I$(UI_DIR) \
	-DLV_CONF_INCLUDE_SIMPLE
CFLAGS ?= -O2
CFLAGS += -std=c11 -Wall -Wextra -Wpedantic -Werror \
	-ffunction-sections -fdata-sections
LDLIBS += $(UI_LIBRARY) -lX11 -lm -ldl

OBJECTS := $(BUILD_DIR)/main.o

.PHONY: all clean probe

all: $(PACKAGE_TARGET) $(LICENSE_TARGET)
	@echo "build: $(PACKAGE_TARGET)"

$(UI_LIBRARY):
	@$(MAKE) -C $(UI_DIR) -j2

$(BUILD_DIR)/main.o: native/src/main.c $(UI_LIBRARY)
	@mkdir -p $(@D)
	@$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@

$(TARGET): $(OBJECTS) $(UI_LIBRARY)
	@$(CC) $(CFLAGS) -Wl,--gc-sections $(OBJECTS) -o $@ $(LDLIBS)

$(PACKAGE_TARGET): $(TARGET)
	@mkdir -p $(@D)
	@cp $(TARGET) $@

$(LICENSE_TARGET): $(UI_DIR)/vendor/lvgl/LICENCE.txt
	@mkdir -p files/share/licenses/lvgl files/share/licenses/msys-ui-lvgl
	@cp $(UI_DIR)/vendor/lvgl/LICENCE.txt $(UI_DIR)/vendor/lvgl/COPYRIGHTS.md \
		files/share/licenses/lvgl/
	@cp $(UI_DIR)/LICENSE files/share/licenses/msys-ui-lvgl/

probe: all
	@sh tests/probe_lvgl_runtime.sh

clean:
	@rm -rf $(BUILD_DIR) $(PACKAGE_TARGET) files/share/licenses/lvgl \
		files/share/licenses/msys-ui-lvgl
