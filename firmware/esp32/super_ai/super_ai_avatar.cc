#include "super_ai_avatar.h"

extern "C" {
extern const uint8_t super_ai_avatar_map[] asm("_binary_super_ai_avatar_bin_start");
}

const lv_image_dsc_t* super_ai_avatar_image() {
    static lv_image_dsc_t image;
    static bool ready = false;
    if (!ready) {
        image.header.magic = LV_IMAGE_HEADER_MAGIC;
        image.header.cf = LV_COLOR_FORMAT_RGB565;
        image.header.flags = 0;
        image.header.w = 360;
        image.header.h = 360;
        image.header.stride = 360 * 2;
        image.data_size = 360 * 360 * 2;
        image.data = super_ai_avatar_map;
        image.reserved = nullptr;
        ready = true;
    }
    return &image;
}
