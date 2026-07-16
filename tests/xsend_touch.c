#define _POSIX_C_SOURCE 200809L
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static void delay_ms(long milliseconds)
{
    struct timespec delay = {
        .tv_sec = milliseconds / 1000,
        .tv_nsec = (milliseconds % 1000) * 1000000L,
    };
    (void)nanosleep(&delay, NULL);
}

static void button(Display *display, Window window, int type, int x, int y)
{
    XEvent event;
    memset(&event, 0, sizeof(event));
    event.xbutton.type = type;
    event.xbutton.display = display;
    event.xbutton.window = window;
    event.xbutton.root = DefaultRootWindow(display);
    event.xbutton.same_screen = True;
    event.xbutton.button = Button1;
    event.xbutton.x = x;
    event.xbutton.y = y;
    event.xbutton.state = type == ButtonRelease ? Button1Mask : 0U;
    XSendEvent(display, window, False,
               type == ButtonPress ? ButtonPressMask : ButtonReleaseMask,
               &event);
    XFlush(display);
}

static void motion(Display *display, Window window, int x, int y)
{
    XEvent event;
    memset(&event, 0, sizeof(event));
    event.xmotion.type = MotionNotify;
    event.xmotion.display = display;
    event.xmotion.window = window;
    event.xmotion.root = DefaultRootWindow(display);
    event.xmotion.same_screen = True;
    event.xmotion.state = Button1Mask;
    event.xmotion.x = x;
    event.xmotion.y = y;
    XSendEvent(display, window, False, PointerMotionMask, &event);
    XFlush(display);
}

int main(int argc, char **argv)
{
    Display *display;
    Window window;
    int y;
    if(argc != 2) return 2;
    display = XOpenDisplay(NULL);
    if(display == NULL) return 1;
    window = (Window)strtoul(argv[1], NULL, 0);
    button(display, window, ButtonPress, 72, 132);
    delay_ms(100);
    button(display, window, ButtonRelease, 72, 132);
    delay_ms(250);
    button(display, window, ButtonPress, 250, 300);
    for(y = 280; y >= 150; y -= 20) {
        motion(display, window, 250, y);
        delay_ms(25);
    }
    button(display, window, ButtonRelease, 250, 150);
    XCloseDisplay(display);
    return 0;
}

