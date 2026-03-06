"""Flow Edge Indicator - transparent overlay showing cursor handoff zone.

A glowing cyan pill on the screen edge with flared ends and breathing
animation, matching the JuhRadial MX Linux indicator design.
"""

import logging
import threading

logger = logging.getLogger("juhflow")

try:
    import objc
    from AppKit import (
        NSApplication, NSApplicationActivationPolicyAccessory,
        NSWindow, NSView, NSColor, NSBezierPath, NSFont, NSMutableParagraphStyle,
        NSScreen, NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
        NSMutableDictionary, NSForegroundColorAttributeName,
        NSFontAttributeName, NSParagraphStyleAttributeName, NSString,
        NSGraphicsContext, NSObject, NSMakeRect,
        NSTimer, NSRunLoop, NSDefaultRunLoopMode,
    )
    from Quartz import CGContextRef
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False

# Dimensions - matching Linux indicator proportions
PILL_LENGTH = 260
PILL_THICKNESS = 4
GLOW_PAD = 30       # Glow spread around pill
FLARE_SIZE = 18     # Bright flare at pill ends
WINDOW_PAD = 10

# JuhRadial MX accent color - #00d4ff cyan
ACCENT = (0.0, 0.831, 1.0)


class FlowIndicator:
    """Manages the edge indicator overlay window."""

    def __init__(self, edge="left"):
        self._edge = edge
        self._window = None
        self._view = None
        self._visible = False
        self._timer = None
        self._alpha_dir = 1
        self._helper = None
        if HAS_APPKIT:
            self._helper = _Helper.alloc().init()
            self._helper._indicator = self

    def _dispatch(self, fn):
        if self._helper:
            self._helper._fn = fn
            self._helper.performSelectorOnMainThread_withObject_waitUntilDone_(
                "run:", None, False)
        else:
            fn()

    def _create_window(self):
        screen = NSScreen.mainScreen()
        if not screen:
            return
        sf = screen.frame()
        sw, sh = sf.size.width, sf.size.height

        vertical = self._edge in ("left", "right")
        if vertical:
            win_w = PILL_THICKNESS + GLOW_PAD * 2 + WINDOW_PAD * 2
            win_h = PILL_LENGTH + GLOW_PAD * 2 + WINDOW_PAD * 2
        else:
            win_w = PILL_LENGTH + GLOW_PAD * 2 + WINDOW_PAD * 2
            win_h = PILL_THICKNESS + GLOW_PAD * 2 + WINDOW_PAD * 2

        if self._edge == "left":
            x, y = 0, (sh - win_h) / 2
        elif self._edge == "right":
            x, y = sw - win_w, (sh - win_h) / 2
        elif self._edge == "top":
            x, y = (sw - win_w) / 2, sh - win_h
        else:
            x, y = (sw - win_w) / 2, 0

        frame = NSMakeRect(x, y, win_w, win_h)
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
        window.setLevel_(25)
        window.setBackgroundColor_(NSColor.clearColor())
        window.setOpaque_(False)
        window.setHasShadow_(False)
        window.setIgnoresMouseEvents_(True)
        window.setCollectionBehavior_(1 << 0 | 1 << 4)
        window.setAlphaValue_(0.0)

        view = _GlowView.alloc().initWithFrame_(NSMakeRect(0, 0, win_w, win_h))
        view._edge = self._edge
        window.setContentView_(view)

        self._window = window
        self._view = view

    def show(self):
        if not HAS_APPKIT:
            return
        if self._visible and self._window:
            return
        self._visible = True
        self._dispatch(self._do_show)

    def _do_show(self):
        if not self._window:
            self._create_window()
        if not self._window:
            return
        self._window.orderFrontRegardless()
        self._window.setAlphaValue_(1.0)
        if not self._timer:
            self._helper._indicator = self
            self._timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
                0.03, self._helper, "breathe:", None, True)
            NSRunLoop.currentRunLoop().addTimer_forMode_(self._timer, NSDefaultRunLoopMode)
        logger.info("Flow indicator shown on %s edge", self._edge)

    def hide(self):
        if not HAS_APPKIT or not self._visible:
            return
        self._visible = False
        self._dispatch(self._do_hide)

    def _do_hide(self):
        if self._timer:
            self._timer.invalidate()
            self._timer = None
        if self._window:
            self._window.setAlphaValue_(0.0)
            self._window.orderOut_(None)
        logger.info("Flow indicator hidden")

    def set_edge(self, edge):
        if edge == self._edge:
            return
        self._edge = edge
        was_visible = self._visible
        if was_visible:
            self.hide()
        self._window = None
        self._view = None
        if was_visible:
            self.show()

    def _breathe_tick(self):
        if not self._window or not self._visible:
            return
        a = self._window.alphaValue()
        if self._alpha_dir > 0:
            a += 0.008
            if a >= 1.0:
                a = 1.0
                self._alpha_dir = -1
        else:
            a -= 0.008
            if a <= 0.7:
                a = 0.7
                self._alpha_dir = 1
        self._window.setAlphaValue_(a)


if HAS_APPKIT:
    class _Helper(NSObject):
        _fn = None
        _indicator = None

        def run_(self, _):
            if self._fn:
                try:
                    self._fn()
                except Exception as e:
                    logger.debug("Indicator dispatch error: %s", e)

        def breathe_(self, timer):
            if self._indicator:
                self._indicator._breathe_tick()

    class _GlowView(NSView):
        _edge = "left"

        def initWithFrame_(self, f):
            self = objc.super(_GlowView, self).initWithFrame_(f)
            if self:
                self.setWantsLayer_(True)
            return self

        def isFlipped(self):
            return True

        def drawRect_(self, rect):
            ctx = NSGraphicsContext.currentContext()
            if not ctx:
                return
            ctx.saveGraphicsState()

            w = self.bounds().size.width
            h = self.bounds().size.height
            r, g, b = ACCENT
            vertical = self._edge in ("left", "right")

            # Pill center position
            if vertical:
                pw, ph = PILL_THICKNESS, PILL_LENGTH
                px = GLOW_PAD + WINDOW_PAD if self._edge == "left" else w - GLOW_PAD - WINDOW_PAD - pw
                py = (h - ph) / 2
            else:
                pw, ph = PILL_LENGTH, PILL_THICKNESS
                px = (w - pw) / 2
                py = GLOW_PAD + WINDOW_PAD if self._edge == "top" else h - GLOW_PAD - WINDOW_PAD - ph

            # --- Outer diffuse glow (wide, soft) ---
            for spread, alpha in [(28, 0.04), (22, 0.06), (16, 0.10), (12, 0.14)]:
                gr = NSMakeRect(px - spread, py - spread, pw + spread * 2, ph + spread * 2)
                radius = spread + (pw if vertical else ph) / 2
                gp = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(gr, radius, radius)
                NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, alpha).setFill()
                gp.fill()

            # --- Inner tight glow (bright, close to pill) ---
            for spread, alpha in [(8, 0.20), (5, 0.35), (3, 0.50), (1.5, 0.65)]:
                gr = NSMakeRect(px - spread, py - spread, pw + spread * 2, ph + spread * 2)
                radius = spread + (pw if vertical else ph) / 2
                gp = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(gr, radius, radius)
                NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, alpha).setFill()
                gp.fill()

            # --- Flared ends (bright glow bursts at top/bottom of pill) ---
            for end_offset in [0, 1]:
                if vertical:
                    fx = px + pw / 2
                    fy = py if end_offset == 0 else py + ph
                else:
                    fx = px if end_offset == 0 else px + pw
                    fy = py + ph / 2

                # Diamond-shaped flare
                for fs, fa in [(FLARE_SIZE, 0.08), (FLARE_SIZE * 0.7, 0.15),
                               (FLARE_SIZE * 0.4, 0.30), (FLARE_SIZE * 0.2, 0.50)]:
                    if vertical:
                        fr = NSMakeRect(fx - fs * 1.8, fy - fs * 0.6, fs * 3.6, fs * 1.2)
                    else:
                        fr = NSMakeRect(fx - fs * 0.6, fy - fs * 1.8, fs * 1.2, fs * 3.6)
                    fp = NSBezierPath.bezierPathWithOvalInRect_(fr)
                    NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, fa).setFill()
                    fp.fill()

                # Bright center dot at flare
                dot_r = 3
                dr = NSMakeRect(fx - dot_r, fy - dot_r, dot_r * 2, dot_r * 2)
                dp = NSBezierPath.bezierPathWithOvalInRect_(dr)
                NSColor.colorWithCalibratedRed_green_blue_alpha_(r * 0.8, g * 0.95, b, 0.7).setFill()
                dp.fill()

            # --- Pill body (bright core line) ---
            pr = NSMakeRect(px, py, pw, ph)
            pp = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(pr, pw / 2, pw / 2)
            NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 0.95).setFill()
            pp.fill()

            # White-hot center line (1px bright highlight inside pill)
            if vertical:
                cr = NSMakeRect(px + pw * 0.3, py + 2, pw * 0.4, ph - 4)
            else:
                cr = NSMakeRect(px + 2, py + ph * 0.3, pw - 4, ph * 0.4)
            cp = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(cr, 1, 1)
            NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.4).setFill()
            cp.fill()

            # --- "Juhflow" text label ---
            attrs = NSMutableDictionary.alloc().init()
            attrs[NSFontAttributeName] = NSFont.systemFontOfSize_(9)
            attrs[NSForegroundColorAttributeName] = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                r, g, b, 0.6)
            style = NSMutableParagraphStyle.alloc().init()
            style.setAlignment_(1)  # Center
            attrs[NSParagraphStyleAttributeName] = style

            text = NSString.stringWithString_("Juhflow")
            ts = text.sizeWithAttributes_(attrs)

            if vertical:
                # Draw text rotated 90 degrees alongside pill
                cgctx = ctx.CGContext()
                from Quartz import CGContextSaveGState, CGContextRestoreGState, \
                    CGContextTranslateCTM, CGContextRotateCTM
                import math
                CGContextSaveGState(cgctx)
                # Position text centered on pill, rotated
                tx = px + pw / 2 + ts.height / 2 + 8
                # Flip for non-flipped coordinate system
                ty = h / 2 + ts.width / 2
                CGContextTranslateCTM(cgctx, tx, ty)
                CGContextRotateCTM(cgctx, -math.pi / 2)
                text.drawAtPoint_withAttributes_((- ts.width / 2, -ts.height / 2), attrs)
                CGContextRestoreGState(cgctx)
            else:
                # Horizontal text below pill
                tx = px + pw / 2 - ts.width / 2
                ty = py + ph + 8
                text.drawAtPoint_withAttributes_((tx, ty), attrs)

            ctx.restoreGraphicsState()
