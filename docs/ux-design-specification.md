# UX Design Specification - JuhRadial MX

**Author:** Sally (UX Expert) & Julianhermstad
**Date:** 2025-12-11
**Version:** 1.0
**Status:** Complete

---

## Executive Summary

This specification defines the complete UX design for JuhRadial MX, a god-tier glassmorphic radial menu for the Logitech MX Master 4 on KDE Plasma. The design draws from industry leaders (Logitech Actions Ring, Figma radial menu), applies Fitts' Law principles for optimal target acquisition, and establishes a comprehensive visual system built on glassmorphism and the Catppuccin Mocha palette.

**Core Design Principles:**
1. **Speed over flourish** - 50ms appearance is non-negotiable
2. **Muscle memory first** - Consistent positions, instant recognition
3. **Beauty in restraint** - Glassmorphism without performance sacrifice
4. **Native feel** - Plasma 6 aesthetic, not "app in a browser"

---

## 1. Radial Menu Overlay

### 1.1 Layout Geometry

```
                    N (0°)
                     │
            NW (315°)│ NE (45°)
                   ╲ │ ╱
                    ╲│╱
         W (270°)────●────E (90°)
                    ╱│╲
                   ╱ │ ╲
            SW (225°)│ SE (135°)
                     │
                   S (180°)
```

| Property | Value | Rationale |
|----------|-------|-----------|
| **Total diameter** | 280px | Fits 4K scaled displays, generous targets |
| **Center zone diameter** | 80px | 28% of total - clear "no selection" threshold |
| **Slice arc angle** | 45° each | Equal sectors, predictable positions |
| **Icon zone radius** | 100px from center | Optimal for 32px icons |
| **Outer ring thickness** | 60px | Generous touch/click targets |

### 1.2 Position Behavior

| Question | Answer | Rationale |
|----------|--------|-----------|
| **Where does menu appear?** | Cursor-centered | Muscle memory - menu is always at attention point |
| **Multi-monitor handling** | Appears on monitor with cursor | Follow user's visual focus |
| **Edge clamping** | Menu repositions to stay fully visible | Never clip menu at screen edges |
| **Minimum edge margin** | 20px | Breathing room from screen bounds |

### 1.3 Center Zone

The center serves dual purposes:
1. **Dead zone** - No slice selected when cursor is within center
2. **Center action** - Quick tap (press + release without movement) triggers center action

| State | Visual | Behavior |
|-------|--------|----------|
| **Idle** | Subtle inner glow, icon at 80% opacity | No haptic |
| **Hover** | Brighter glow, icon at 100%, subtle scale (1.05x) | Light haptic pulse |
| **Selected** | Flash animation, icon pulse | Strong haptic confirmation |

---

## 2. Interaction Model

### 2.1 Core Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     INTERACTION TIMELINE                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Button Down          Moving              Button Up             │
│      │                  │                     │                 │
│      ▼                  ▼                     ▼                 │
│  ┌────────┐        ┌────────┐           ┌────────┐              │
│  │ APPEAR │───────►│ SELECT │──────────►│ FIRE   │              │
│  │ <50ms  │        │ track  │           │ action │              │
│  └────────┘        └────────┘           └────────┘              │
│      │                  │                     │                 │
│      ▼                  ▼                     ▼                 │
│  Menu fades in     Slice highlights      Menu fades out        │
│  at cursor pos     follow cursor         action executes       │
│                    haptic on change                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Selection Mechanics

| Property | Specification | Rationale |
|----------|---------------|-----------|
| **Selection method** | Mouse movement from center | Cursor at center on appear, move to select |
| **Selection threshold** | 40px from center (radius of center zone) | Clear transition from "no selection" |
| **Slice transition** | Snap to nearest (no smooth following) | Decisive feel, matches Logitech behavior |
| **Direction calculation** | atan2(deltaY, deltaX) → 8 sectors | Standard angle-to-sector mapping |

**Direction Mapping:**

| Direction | Angle Range | Index |
|-----------|-------------|-------|
| N (Up) | 337.5° - 22.5° | 0 |
| NE | 22.5° - 67.5° | 1 |
| E (Right) | 67.5° - 112.5° | 2 |
| SE | 112.5° - 157.5° | 3 |
| S (Down) | 157.5° - 202.5° | 4 |
| SW | 202.5° - 247.5° | 5 |
| W (Left) | 247.5° - 292.5° | 6 |
| NW | 292.5° - 337.5° | 7 |

### 2.3 Haptic Feedback Profile

| Event | Intensity | Duration | Pattern |
|-------|-----------|----------|---------|
| Menu appear | 20/100 | 10ms | Single pulse |
| Slice change | 40/100 | 15ms | Single pulse |
| Selection confirm | 80/100 | 25ms | Double pulse |
| Invalid action | 30/100 | 50ms | Triple short |

---

## 3. Visual Design System

### 3.1 Glassmorphism Specification

The glassmorphism effect combines multiple layers:

```css
/* Core glassmorphism recipe */
.radial-menu-background {
  /* Layer 1: Base transparency */
  background: rgba(30, 30, 46, 0.75); /* Catppuccin Mocha Base */

  /* Layer 2: Backdrop blur */
  backdrop-filter: blur(24px) saturate(180%);

  /* Layer 3: Inner glow border */
  border: 1px solid rgba(205, 214, 244, 0.15); /* Text color at 15% */

  /* Layer 4: Noise texture overlay */
  background-image: url('noise-4k.png');
  background-blend-mode: overlay;

  /* Layer 5: Subtle shadow */
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.4),
    inset 0 1px 0 rgba(255, 255, 255, 0.1);
}
```

| Property | Value | Notes |
|----------|-------|-------|
| **Blur radius** | 24px | KWin blur effect - test on low-end GPUs |
| **Background opacity** | 75% | Balance: readable but sees through |
| **Saturation boost** | 180% | Makes underlying content more vibrant |
| **Noise opacity** | 3-5% | Subtle texture, prevents banding |
| **Border opacity** | 15% | Just visible, not distracting |

### 3.2 Catppuccin Mocha Color Palette

**Base Colors (Backgrounds & Surfaces):**

| Name | Hex | RGB | Usage |
|------|-----|-----|-------|
| Crust | `#11111b` | (17, 17, 27) | Deepest shadow |
| Mantle | `#181825` | (24, 24, 37) | Outer ring shadow |
| Base | `#1e1e2e` | (30, 30, 46) | Primary background |
| Surface 0 | `#313244` | (49, 50, 68) | Slice default |
| Surface 1 | `#45475a` | (69, 71, 90) | Slice hover subtle |
| Surface 2 | `#585b70` | (88, 91, 112) | Borders |

**Text & Overlay:**

| Name | Hex | Usage |
|------|-----|-------|
| Text | `#cdd6f4` | Primary labels |
| Subtext 1 | `#bac2de` | Secondary labels |
| Overlay 0 | `#6c7086` | Disabled states |

**Accent Colors (Slice Highlights):**

| Name | Hex | Usage |
|------|-----|-------|
| Lavender | `#b4befe` | Default selection highlight |
| Blue | `#89b4fa` | Primary actions |
| Sapphire | `#74c7ec` | Navigation actions |
| Teal | `#94e2d5` | Success states |
| Green | `#a6e3a1` | Confirm actions |
| Peach | `#fab387` | Warning actions |
| Mauve | `#cba6f7` | Creative/custom |
| Pink | `#f5c2e7` | Accent variety |

### 3.3 Slice States

| State | Background | Border | Icon | Glow |
|-------|------------|--------|------|------|
| **Default** | Surface 0 @ 60% | Surface 2 @ 20% | Text @ 80% | None |
| **Hover** | Surface 1 @ 80% | Lavender @ 40% | Text @ 100% | Lavender @ 20%, 8px spread |
| **Selected (frame)** | Lavender @ 30% | Lavender @ 80% | Text @ 100% + scale(1.1) | Lavender @ 40%, 16px spread |
| **Disabled** | Surface 0 @ 30% | None | Overlay 0 @ 50% | None |
| **Empty (unconfigured)** | Surface 0 @ 20% | Dashed, Surface 2 @ 30% | "+" icon @ 40% | None |

### 3.4 Animation Specifications

| Animation | Duration | Easing | Notes |
|-----------|----------|--------|-------|
| **Menu appear** | 30ms | ease-out | Opacity 0→1 ONLY (no scale/slide) |
| **Menu dismiss** | 50ms | ease-in | Opacity 1→0 |
| **Slice highlight in** | 80ms | ease-out | Background + glow fade |
| **Slice highlight out** | 60ms | ease-in | Faster than in (responsive feel) |
| **Icon scale (hover)** | 100ms | cubic-bezier(0.34, 1.56, 0.64, 1) | Slight overshoot for "pop" |
| **Selection flash** | 150ms | linear | Single bright pulse then settle |

**Animation Budget:**
- Menu entrance: **30ms** (well under 50ms requirement)
- No transform animations on entrance (blur rendering is the cost)
- Reserve animation budget for slice highlighting
- Disable all decorative animations if `prefers-reduced-motion`

---

## 4. Theme System Architecture

### 4.1 Theme Structure

Each theme is a directory containing:

```
/usr/share/juhradial/themes/{theme-name}/
├── theme.json          # Color definitions + settings
├── noise.png           # Optional custom noise texture (512x512, tileable)
└── icons/              # Optional themed icon overrides
    └── *.svg
```

### 4.2 Theme Configuration Schema

```json
{
  "name": "Catppuccin Mocha",
  "version": "1.0",
  "author": "JuhRadial Team",

  "colors": {
    "base": "#1e1e2e",
    "surface": "#313244",
    "text": "#cdd6f4",
    "textSecondary": "#bac2de",
    "accent": "#b4befe",
    "accentSecondary": "#89b4fa",
    "border": "#585b70",
    "shadow": "#11111b",
    "success": "#a6e3a1",
    "warning": "#fab387",
    "error": "#f38ba8"
  },

  "glassmorphism": {
    "blurRadius": 24,
    "backgroundOpacity": 0.75,
    "saturation": 1.8,
    "borderOpacity": 0.15,
    "noiseOpacity": 0.04
  },

  "animation": {
    "glowIntensity": 1.0,
    "enableParticles": false,
    "idleEffect": "none"
  },

  "overrides": {
    "sliceColors": null,
    "customFont": null
  }
}
```

### 4.3 Bundled Themes

#### Theme 1: Catppuccin Mocha (Default)
- Warm pastel dark theme
- Lavender accent color
- Balanced glassmorphism (24px blur)

#### Theme 2: Vaporwave
```json
{
  "colors": {
    "base": "#1a1a2e",
    "surface": "#2d2d44",
    "text": "#e0e0ff",
    "accent": "#ff71ce",
    "accentSecondary": "#01cdfe"
  },
  "glassmorphism": {
    "blurRadius": 32,
    "backgroundOpacity": 0.65,
    "saturation": 2.2
  },
  "animation": {
    "glowIntensity": 1.5
  }
}
```

#### Theme 3: Matrix Rain
```json
{
  "colors": {
    "base": "#0d0d0d",
    "surface": "#1a1a1a",
    "text": "#00ff41",
    "accent": "#00ff41",
    "accentSecondary": "#008f11"
  },
  "glassmorphism": {
    "blurRadius": 16,
    "backgroundOpacity": 0.85,
    "saturation": 1.2
  },
  "animation": {
    "idleEffect": "matrix-rain",
    "glowIntensity": 2.0
  }
}
```

### 4.4 What's Configurable Per Theme

| Property | Configurable | Notes |
|----------|--------------|-------|
| Colors (all) | Yes | Full palette override |
| Blur radius | Yes | 8-48px range |
| Background opacity | Yes | 0.5-0.95 range |
| Saturation | Yes | 1.0-2.5 range |
| Border opacity | Yes | 0-0.5 range |
| Glow intensity | Yes | 0-2.0 multiplier |
| Noise texture | Yes | Custom PNG |
| Idle animations | Yes | none, matrix-rain, particles |
| Slice shape | **No** | Consistency for muscle memory |
| Menu size | **No** | Consistency for muscle memory |
| Slice count | **No** | Always 8 + center |

---

## 5. Icon System

### 5.1 Icon Specifications

| Property | Value | Notes |
|----------|-------|-------|
| **Primary size** | 32x32px | Optimal for radial menu |
| **Padding** | 4px | Visual breathing room |
| **Format (vector)** | SVG | Scales for HiDPI |
| **Format (raster)** | PNG @2x | 64x64 for retina |
| **Color mode** | Monochrome with theme color | Icons inherit `text` color |
| **Stroke width** | 2px | Consistent with KDE icons |

### 5.2 Supported Icon Types

| Type | Priority | Implementation |
|------|----------|----------------|
| **Unicode Emoji** | 1 | Native font rendering (Noto Color Emoji) |
| **Custom SVG** | 2 | User-provided, theme-tinted |
| **System icons** | 3 | KDE Breeze icons via Plasma API |
| **Custom PNG** | 4 | User-provided, used as-is |

### 5.3 Default Icon Set

JuhRadial ships with a curated icon set for common actions:

| Category | Icons |
|----------|-------|
| **Clipboard** | copy, paste, cut, clipboard-history |
| **Edit** | undo, redo, select-all, find |
| **Files** | save, open, new-file, folder |
| **Window** | minimize, maximize, close, tile-left, tile-right |
| **Media** | play, pause, next, previous, volume |
| **System** | screenshot, lock, settings, power |
| **Navigation** | back, forward, home, refresh |
| **Apps** | terminal, browser, files, editor |

### 5.4 Emoji Rendering

```qml
// QML emoji rendering with proper fallback
Text {
  text: slice.icon.startsWith("emoji:")
        ? slice.icon.substring(6)  // Raw emoji
        : ""
  font.family: "Noto Color Emoji, Apple Color Emoji, Segoe UI Emoji"
  font.pixelSize: 28
  color: theme.colors.text
}
```

---

## 6. Settings Dashboard

### 6.1 Dashboard Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  JuhRadial MX Settings                                      [─][□][×]│
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────────┐    ┌─────────────────────────────────────────┐  │
│  │                 │    │         RADIAL MENU PREVIEW              │  │
│  │   MX MASTER 4   │    │                                         │  │
│  │   [Interactive] │    │              ┌───────┐                  │  │
│  │                 │    │         ┌────│  📋   │────┐             │  │
│  │    ┌─────────┐  │    │        ╱     └───────┘     ╲            │  │
│  │    │ GESTURE │◀─┼────│       ╱                     ╲           │  │
│  │    │ BUTTON  │  │    │   ┌──────┐            ┌──────┐          │  │
│  │    └─────────┘  │    │   │  📂  │    ●       │  📝  │          │  │
│  │                 │    │   └──────┘   🚀       └──────┘          │  │
│  │                 │    │       ╲                     ╱           │  │
│  │                 │    │        ╲     ┌───────┐     ╱            │  │
│  │                 │    │         └────│  📸   │────┘             │  │
│  │                 │    │              └───────┘                  │  │
│  └─────────────────┘    │                                         │  │
│                         │  Click a slice to edit                  │  │
│                         └─────────────────────────────────────────┘  │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐   │
│  │  TABS: [Profiles] [Theme] [Haptics] [About]                   │   │
│  ├───────────────────────────────────────────────────────────────┤   │
│  │                                                               │   │
│  │  Profile: [Default        ▼]   [+ New] [Duplicate] [Delete]  │   │
│  │                                                               │   │
│  │  App-specific: [✓] Enable per-application profiles           │   │
│  │                                                               │   │
│  │  ┌─────────────────────────────────────────────────────────┐  │   │
│  │  │ App Class          │ Profile          │ Actions         │  │   │
│  │  ├─────────────────────────────────────────────────────────┤  │   │
│  │  │ code               │ VS Code          │ [Edit] [Remove] │  │   │
│  │  │ firefox            │ Browser          │ [Edit] [Remove] │  │   │
│  │  │ dolphin            │ Files            │ [Edit] [Remove] │  │   │
│  │  │ + Add application...                                    │  │   │
│  │  └─────────────────────────────────────────────────────────┘  │   │
│  │                                                               │   │
│  └───────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  [Reset to Defaults]                    [Export] [Import]   [Apply]  │
└──────────────────────────────────────────────────────────────────────┘
```

### 6.2 Interactive Mouse Preview

The left panel shows an accurate MX Master 4 silhouette with clickable zones:

| Zone | Click Action | Visual Feedback |
|------|--------------|-----------------|
| Gesture button | Opens radial menu configuration | Highlight glow |
| Scroll wheel | (Future: SmartShift settings) | Subtle pulse |
| Forward/Back buttons | (Future: Button mapping) | Highlight glow |
| DPI button | (Future: DPI presets) | Highlight glow |

**Art Style:**
- Stylized flat illustration (not photorealistic)
- Catppuccin-themed colors
- Subtle gradients for depth
- Hover states with glow effects

### 6.3 Slice Editor Modal

When clicking a slice in the preview:

```
┌────────────────────────────────────────────────────────────┐
│  Edit Slice: North (Up)                               [×]  │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  Icon:  [📋] [Choose...]    Preview: ┌────┐               │
│                                       │ 📋 │               │
│  Label: [Copy____________]            │Copy│               │
│                                       └────┘               │
│  Action Type:                                              │
│  ○ Keyboard Shortcut                                       │
│  ● Shell Command                                           │
│  ○ D-Bus Call                                              │
│  ○ KWin Script                                             │
│                                                            │
│  Shortcut: [Ctrl+C__________]  [Record]                   │
│                                                            │
│  ─────────────────────────────────────────                │
│                                                            │
│  Per-slice accent color (optional):                        │
│  [Auto (theme)] ▼    ● ● ● ● ● ● ● ●                      │
│                      (color swatches)                      │
│                                                            │
│                        [Cancel]  [Save]                    │
└────────────────────────────────────────────────────────────┘
```

### 6.4 Theme Picker

```
┌────────────────────────────────────────────────────────────┐
│  Theme                                                     │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ ████████████ │  │ ████████████ │  │ ████████████ │     │
│  │ ▓▓▓▓▓▓▓▓▓▓▓▓ │  │ ▓▓▓▓▓▓▓▓▓▓▓▓ │  │ ▓▓▓▓▓▓▓▓▓▓▓▓ │     │
│  │    [RING]    │  │    [RING]    │  │    [RING]    │     │
│  │              │  │              │  │              │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│   Catppuccin ✓      Vaporwave        Matrix Rain          │
│                                                            │
│  [Open Themes Folder]  [Get More Themes...]               │
│                                                            │
│  ─────────────────────────────────────────                │
│                                                            │
│  Preview: ○ Light desktop  ● Dark desktop                 │
│                                                            │
│  [x] Live preview (applies theme temporarily)              │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### 6.5 Haptics Tab

```
┌────────────────────────────────────────────────────────────┐
│  Haptic Feedback                                           │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  [✓] Enable haptic feedback                                │
│                                                            │
│  Global Intensity:                                         │
│  Light ├────────────●──────────┤ Strong                   │
│                    65                                      │
│                                                            │
│  ─────────────────────────────────────────                │
│                                                            │
│  Event-specific:                                           │
│                                                            │
│  Menu appear:       [──●───────] 20    [Test]             │
│  Slice change:      [────●─────] 40    [Test]             │
│  Selection confirm: [────────●─] 80    [Test]             │
│                                                            │
│  [ ] Use device defaults (ignore above)                    │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

## 7. Accessibility

### 7.1 High Contrast Mode

When system high contrast is enabled OR user toggles in settings:

| Element | Default | High Contrast |
|---------|---------|---------------|
| Background opacity | 75% | 95% |
| Border opacity | 15% | 60% |
| Text color | #cdd6f4 | #ffffff |
| Selection highlight | Lavender glow | Solid white border 3px |
| Blur | 24px | 0px (disabled) |

### 7.2 Reduced Motion

When `prefers-reduced-motion` is set:

| Animation | Normal | Reduced Motion |
|-----------|--------|----------------|
| Menu appear | 30ms fade | Instant (0ms) |
| Menu dismiss | 50ms fade | Instant (0ms) |
| Slice highlight | 80ms transition | Instant (0ms) |
| Icon scale | 100ms bounce | None |
| Idle effects | Enabled | Disabled |

### 7.3 Keyboard Navigation (Dashboard)

| Key | Action |
|-----|--------|
| Tab | Move between controls |
| Arrow keys | Navigate slice preview |
| Enter | Activate selected control |
| Escape | Close modal / cancel |
| Ctrl+S | Save changes |

---

## 8. Edge Cases & Error States

### 8.1 Empty Slice Handling

When user configures fewer than 8 slices:

| Option | Visual | Behavior |
|--------|--------|----------|
| **Recommended** | Show "+" affordance | Click opens slice editor |
| Alternative A | Gray out slice | No action on selection |
| Alternative B | Hide slice entirely | **Rejected**: breaks spatial consistency |

**Decision:** Empty slices show subtle "+" icon with dashed border. Selection triggers no action but plays "invalid" haptic pattern.

### 8.2 Profile Transition Mid-Menu

If focused app changes while menu is open:

```
Current Behavior: Menu stays with original profile
Rationale: Changing mid-gesture is disorienting
Alternative (rejected): Close menu and reopen with new profile
```

### 8.3 Mouse Disconnect

| Scenario | Behavior |
|----------|----------|
| Mouse disconnects while menu open | Close menu immediately, no action |
| Mouse reconnects | Resume normal operation, no notification |
| Daemon can't find mouse on start | System tray icon shows warning state |

### 8.4 Display Scaling

| Scale Factor | Menu Diameter | Icon Size | Blur Radius |
|--------------|---------------|-----------|-------------|
| 100% | 280px | 32px | 24px |
| 125% | 350px | 40px | 30px |
| 150% | 420px | 48px | 36px |
| 200% | 560px | 64px | 48px |

All dimensions scale proportionally. Blur radius increases to maintain visual consistency.

---

## 9. Performance Constraints

### 9.1 Frame Budget

| Component | Budget | Priority |
|-----------|--------|----------|
| Blur effect render | 8ms | Critical (GPU) |
| Selection calculation | 1ms | Critical (CPU) |
| Haptic command send | 2ms | High |
| Animation frame | 16ms (60fps) | Medium |
| Total frame time | <16ms | Must hit |

### 9.2 Memory Budget

| Asset | Size | Notes |
|-------|------|-------|
| Menu textures | ~2MB | Including noise, cached |
| Theme JSON | ~10KB | Per theme |
| Icon cache | ~5MB | All default icons |
| Total widget | <15MB | Target |
| Total daemon | <30MB | Target |

### 9.3 KWin Blur Optimization

To maintain performance on lower-end GPUs:

1. **Pre-composite** the radial menu base (without live blur)
2. **Cache** the blurred background region on button down
3. **Limit** blur region to menu bounds (not full screen)
4. **Fallback** to solid background if GPU can't sustain 60fps

---

## 10. Implementation Priorities

### Phase 1: Core Experience (P0)

1. 8-slice radial menu geometry
2. Cursor-centered positioning
3. Movement-based selection
4. 30ms appear / 50ms dismiss
5. Single theme (Catppuccin Mocha)
6. Haptic feedback (basic)

### Phase 2: Polish (P1)

1. Full theme system with 3 bundled themes
2. Complete settings dashboard
3. Per-application profiles
4. Slice editor with icon picker
5. Haptic intensity controls

### Phase 3: Delight (P2)

1. Matrix rain idle animation
2. Custom theme creation
3. Plasma Activities integration
4. Export/import configurations
5. High contrast mode

---

## Appendix A: Design Decisions Log

| Decision | Options Considered | Chosen | Rationale |
|----------|-------------------|--------|-----------|
| Menu position | Cursor-centered vs Fixed screen position | Cursor-centered | Muscle memory, attention follows cursor |
| Slice selection | Click to select vs Movement selects | Movement | Matches Logitech, faster for power users |
| Slice count | 6 vs 8 vs 12 | 8 | Balance of options vs target size |
| Empty slice | Hide vs Gray out vs "+" affordance | "+" affordance | Discoverable, maintains spatial consistency |
| Theme shapes | Configurable vs Fixed | Fixed | Consistency > novelty for muscle memory |
| Entrance animation | Fade vs Scale vs Slide | Fade only | Speed constraint (50ms), blur is the cost |

---

## Appendix B: Competitive Reference

### Logitech Actions Ring (MX Master 4)

**What They Do Well:**
- Cursor-centered appearance
- Haptic feedback on slice change
- App-specific shortcuts
- Clean, minimal visual design
- ~40ms appearance time

**Where JuhRadial Can Exceed:**
- Glassmorphism (Actions Ring is solid color)
- Theme customization
- Linux-native integration
- Open-source extensibility

### Figma Radial Menu

**What They Do Well:**
- Smooth slice highlighting
- Clear visual hierarchy
- Consistent with brand aesthetic

**Where JuhRadial Can Exceed:**
- Haptic feedback
- System-level integration
- More customization options

---

## Appendix C: Asset Checklist

| Asset | Format | Size | Status |
|-------|--------|------|--------|
| noise-4k.png | PNG | 4096x4096 | Planned |
| mx-master-4-illustration.svg | SVG | Vector | Needed |
| default-icons/*.svg | SVG | 32x32 | Needed |
| catppuccin-mocha/theme.json | JSON | ~2KB | Specified |
| vaporwave/theme.json | JSON | ~2KB | Specified |
| matrix-rain/theme.json | JSON | ~2KB | Specified |

---

**Document Complete**

*This specification provides the complete UX foundation for JuhRadial MX. Implementation teams should reference this document for all visual and interaction decisions.*
