#!/usr/bin/env python3
import configparser
import hashlib
import json
import os
import re
import subprocess
import threading
import random

import gi
try:
    import cairo
    HAVE_CAIRO = True
except Exception:
    HAVE_CAIRO = False

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GdkPixbuf, Gtk, GLib, Pango


def build_wallpaper_tab(window):
    window.thumb_flow = Gtk.FlowBox()
    window.thumb_flow.set_selection_mode(Gtk.SelectionMode.SINGLE)
    window.thumb_flow.set_min_children_per_line(4)
    window.thumb_flow.set_max_children_per_line(4)
    window.thumb_flow.set_row_spacing(10)
    window.thumb_flow.set_column_spacing(10)
    window.thumb_flow.set_halign(Gtk.Align.CENTER)
    window.thumb_flow.set_valign(Gtk.Align.START)
    window.thumb_flow.set_homogeneous(True)
    window.thumb_flow.connect("child-activated", window._on_thumb_activated)

    window.wallpaper_tab = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

    window.logo_label = Gtk.Label(label="jasmine 🍚")
    window.logo_label.set_xalign(0.5)
    window.logo_label.set_halign(Gtk.Align.CENTER)
    window.logo_label.set_margin_bottom(6)
    window.logo_label.get_style_context().add_class("logo-label")
    window.logo_label.get_style_context().add_class("title-label")
    window.wallpaper_tab.pack_start(window.logo_label, False, False, 0)

    window.preview_overlay = Gtk.Overlay()
    window.preview_overlay.set_size_request(-1, 360)
    window.preview_overlay.set_margin_top(8)
    window.preview_image = Gtk.Image()
    window.preview_image.set_size_request(-1, 360)
    window.preview_image.set_opacity(1.0)
    window.preview_overlay.add(window.preview_image)

    window.sparkle_labels = []
    window._sparkle_symbols = ["✦", "✧", "♡", "☆", "✩", "❀", "❁", "❃", "✿", "✪"]
    for symbol in window._sparkle_symbols:
        sparkle = Gtk.Label(label=symbol)
        sparkle.get_style_context().add_class("kawaii-sparkle")
        sparkle.set_halign(Gtk.Align.START)
        sparkle.set_valign(Gtk.Align.START)
        sparkle.set_opacity(0.0)
        window.root_overlay.add_overlay(sparkle)
        window.sparkle_labels.append(sparkle)
    window._sparkle_index = 0
    window._sparkle_colors = ["#ffd6e2", "#ffb6c1", "#ffe4ef"]
    window._start_sparkle_loop()
    window.wallpaper_tab.pack_start(window.preview_overlay, False, False, 0)

    window.palette_grid = Gtk.Grid()
    window.palette_grid.set_column_spacing(6)
    window.palette_grid.set_row_spacing(6)
    window.palette_grid.set_halign(Gtk.Align.CENTER)
    window.palette_grid.set_opacity(1.0)

    swatch_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    swatch_box.set_margin_top(6)
    swatch_box.set_margin_bottom(6)
    swatch_box.set_margin_start(8)
    swatch_box.set_margin_end(8)
    swatch_box.pack_start(window.palette_grid, False, False, 0)

    swatch_frame = Gtk.Frame()
    swatch_frame.set_shadow_type(Gtk.ShadowType.NONE)
    swatch_frame.set_halign(Gtk.Align.CENTER)
    swatch_frame.set_valign(Gtk.Align.END)
    swatch_frame.set_margin_bottom(18)
    swatch_frame.get_style_context().add_class("swatch-frame")
    swatch_frame.add(swatch_box)
    window.preview_overlay.add_overlay(swatch_frame)

    frame_css = """
    .swatch-frame {
        border: 2px solid rgba(255, 255, 255, 0.6);
        border-radius: 10px;
        background-color: rgba(20, 16, 16, 0.35);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.45);
    }
    """
    frame_provider = Gtk.CssProvider()
    frame_provider.load_from_data(frame_css.encode("utf-8"))
    swatch_frame.get_style_context().add_provider(
        frame_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    thumb_scroll = Gtk.ScrolledWindow()
    thumb_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    thumb_scroll.set_min_content_height(160)
    thumb_scroll.add(window.thumb_flow)
    window.wallpaper_tab.pack_start(thumb_scroll, True, True, 0)

    apply_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    apply_row.set_halign(Gtk.Align.CENTER)
    window.apply_button = Gtk.Button(label="Apply")
    window.apply_button.connect("clicked", window._apply_matugen)
    apply_row.pack_start(window.apply_button, False, False, 0)
    window.wallpaper_tab.pack_start(apply_row, False, False, 10)

    return window.wallpaper_tab


KEY_COLORS = [
    "background",
    "on_surface",
    "on_background",
    "primary",
    "primary_container",
    "secondary",
    "tertiary",
]
SWATCH_COLORS = ["background", "primary", "primary_container", "secondary", "tertiary"]
KEY_PATTERNS = {
    key: re.compile(r"\b%s\b" % re.escape(key), re.IGNORECASE)
    for key in KEY_COLORS
}
HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")
THUMBNAIL_CACHE_VERSION = "v4"
SIDEBAR_WIDTH = 220
SWWW_TRANSITIONS = [
    "center",
    "fade",
    "wipe",
    "wave",
    "grow",
    "outer",
    "random",
    "left",
    "right",
    "top",
    "bottom",
]
SWWW_RESIZE_TYPES = ["crop", "fit", "center", "zoom"]


def config_path():
    return os.path.join(os.path.expanduser("~/.config"), "jasmine", "settings.ini")


def load_settings():
    config = configparser.ConfigParser()
    path = config_path()
    if os.path.exists(path):
        config.read(path)
    if "main" not in config:
        config["main"] = {}
    main = config["main"]
    return {
        "images_folder": main.get("images_folder", os.path.expanduser("~/Pictures/BG")),
        "theme": main.get("theme", "scheme-tonal-spot"),
        "mode": main.get("mode", "dark"),
        "contrast": int(main.get("contrast", "0")),
    }


def save_settings(values):
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    config = configparser.ConfigParser()
    config["main"] = {
        "images_folder": values["images_folder"],
        "theme": values["theme"],
        "mode": values["mode"],
        "contrast": str(values["contrast"]),
    }
    with open(path, "w", encoding="utf-8") as handle:
        config.write(handle)


def matugen_config_path():
    return os.path.expanduser("~/.config/matugen/config.toml")


def _find_toml_block(lines, header):
    start_idx = None
    end_idx = None
    idx = 0
    for line in lines:
        stripped = line.strip()
        if stripped == header:
            start_idx = idx
        elif start_idx is not None and stripped.startswith("[") and stripped.endswith("]"):
            end_idx = idx
            break
        idx += 1
    return start_idx, end_idx


def _parse_toml_args_block(lines, start_idx, end_idx):
    if start_idx is None:
        return []
    arg_lines = []
    idx = start_idx + 1
    while idx < len(lines):
        if end_idx is not None and idx >= end_idx:
            break
        stripped = lines[idx].strip()
        if stripped.startswith("arguments"):
            arg_lines.append(lines[idx])
            if "]" in lines[idx]:
                break
            idx += 1
            while idx < len(lines):
                arg_lines.append(lines[idx])
                if "]" in lines[idx]:
                    break
                idx += 1
            break
        idx += 1
    if not arg_lines:
        return []
    joined = "".join(arg_lines)
    values = []
    for match in re.finditer(r'"([^"]*)"|\'([^\']*)\'', joined):
        value = match.group(1) if match.group(1) is not None else match.group(2)
        values.append(value)
    return values


def load_matugen_wallpaper_args():
    path = matugen_config_path()
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.readlines()
    start_idx, end_idx = _find_toml_block(lines, "[config.wallpaper]")
    return _parse_toml_args_block(lines, start_idx, end_idx)


def write_matugen_wallpaper_args(args):
    path = matugen_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    else:
        lines = []
    start_idx, end_idx = _find_toml_block(lines, "[config.wallpaper]")
    quoted = ", ".join('"%s"' % value for value in args)
    new_line = "arguments = [%s]\n" % quoted

    if start_idx is None:
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.extend(
            [
                "[config.wallpaper]\n",
                "set = true\n",
                'command = "swww"\n',
                new_line,
            ]
        )
    else:
        replaced = False
        idx = start_idx + 1
        while idx < end_idx:
            stripped = lines[idx].strip()
            if stripped.startswith("arguments"):
                end_args = idx + 1
                if "]" not in lines[idx]:
                    while end_args < end_idx and "]" not in lines[end_args]:
                        end_args += 1
                    if end_args < end_idx:
                        end_args += 1
                lines[idx:end_args] = [new_line]
                replaced = True
                break
            idx += 1
        if not replaced:
            insert_at = start_idx + 1
            for idx in range(start_idx + 1, end_idx):
                if lines[idx].strip().startswith("command"):
                    insert_at = idx + 1
                    break
            lines[insert_at:insert_at] = [new_line]

    with open(path, "w", encoding="utf-8") as handle:
        handle.writelines(lines)


def _find_arg_value(args, flag):
    try:
        idx = args.index(flag)
    except ValueError:
        return None
    if idx + 1 < len(args):
        return args[idx + 1]
    return None


def _merge_swww_args(args, updates):
    result = []
    used = set()
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg in updates:
            result.append(arg)
            result.append(updates[arg])
            used.add(arg)
            idx += 2
            continue
        result.append(arg)
        idx += 1
    for key, value in updates.items():
        if key not in used:
            result.extend([key, value])
    if "img" not in result:
        result.insert(0, "img")
    return result


def load_swww_settings_from_config():
    args = load_matugen_wallpaper_args()
    settings = {
        "transition_type": _find_arg_value(args, "--transition-type") or "center",
        "duration": _find_arg_value(args, "--transition-duration") or "1",
        "fps": _find_arg_value(args, "--transition-fps") or "60",
        "degree": _find_arg_value(args, "--transition-angle") or "0",
        "step": _find_arg_value(args, "--transition-step") or "1",
        "resize": _find_arg_value(args, "--resize") or "crop",
        "fill_color": _find_arg_value(args, "--fill-color") or "",
    }
    return settings


def build_swww_args(settings):
    args = load_matugen_wallpaper_args()
    updates = {
        "--transition-type": settings["transition_type"],
        "--transition-duration": settings["duration"],
        "--transition-fps": settings["fps"],
        "--transition-angle": settings["degree"],
        "--transition-step": settings["step"],
        "--resize": settings["resize"],
    }
    fill_color = settings.get("fill_color", "").strip()
    if fill_color:
        updates["--fill-color"] = fill_color.lstrip("#")
    return _merge_swww_args(args, updates)
def supported_image_exts():
    exts = set()
    for fmt in GdkPixbuf.Pixbuf.get_formats():
        for ext in fmt.get_extensions():
            exts.add(ext.lower())
    return exts


def thumbnail_cache_dir():
    return os.path.expanduser("~/.cache/jasmine")


def thumbnail_cache_path(path, size):
    try:
        stat = os.stat(path)
    except OSError:
        stat = None
    token = "%s|%s|%s" % (
        path,
        getattr(stat, "st_mtime", 0),
        getattr(stat, "st_size", 0),
    )
    token = "%s|%sx%s|%s" % (token, size[0], size[1], THUMBNAIL_CACHE_VERSION)
    digest = hashlib.sha1(token.encode("utf-8")).hexdigest()
    return os.path.join(thumbnail_cache_dir(), digest + ".png")


def load_thumbnail(path, size=(96, 64)):
    cache_path = thumbnail_cache_path(path, size)
    if os.path.exists(cache_path):
        try:
            return GdkPixbuf.Pixbuf.new_from_file(cache_path)
        except Exception:
            pass

    target_w, target_h = size
    info = GdkPixbuf.Pixbuf.get_file_info(path)
    if info and info[1] and info[2]:
        width, height = info[1], info[2]
        scale = max(target_w / float(width), target_h / float(height))
        scaled_w = max(1, int(width * scale + 0.5))
        scaled_h = max(1, int(height * scale + 0.5))
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                path, scaled_w, scaled_h, False
            )
        except Exception:
            return None
        pixbuf = crop_center_pixbuf(pixbuf, size)
    else:
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                path, target_w, target_h, False
            )
        except Exception:
            return None

    if pixbuf.get_width() != target_w or pixbuf.get_height() != target_h:
        pixbuf = pixbuf.scale_simple(
            target_w, target_h, GdkPixbuf.InterpType.BILINEAR
        )

    os.makedirs(thumbnail_cache_dir(), exist_ok=True)
    try:
        pixbuf.savev(cache_path, "png", [], [])
    except Exception:
        pass
    return pixbuf


def hex_to_rgba(hex_color, alpha):
    value = hex_color.lstrip("#")
    if len(value) != 6:
        return "rgba(0, 0, 0, %s)" % alpha
    r = int(value[0:2], 16)
    g = int(value[2:4], 16)
    b = int(value[4:6], 16)
    return "rgba(%d, %d, %d, %s)" % (r, g, b, alpha)


def _rounded_rect(ctx, x, y, w, h, r):
    r = max(0.0, min(r, min(w, h) / 2.0))
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -1.5708, 0.0)
    ctx.arc(x + w - r, y + h - r, r, 0.0, 1.5708)
    ctx.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    ctx.arc(x + r, y + r, r, 3.1416, 4.7124)
    ctx.close_path()


def round_pixbuf(pixbuf, radius):
    if not HAVE_CAIRO:
        return pixbuf
    if pixbuf is None:
        return pixbuf
    width = pixbuf.get_width()
    height = pixbuf.get_height()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    _rounded_rect(ctx, 0, 0, width, height, float(radius))
    ctx.clip()
    Gdk.cairo_set_source_pixbuf(ctx, pixbuf, 0, 0)
    ctx.paint()
    return Gdk.pixbuf_get_from_surface(surface, 0, 0, width, height)


def crop_center_pixbuf(pixbuf, size):
    if pixbuf is None:
        return pixbuf
    target_w, target_h = size
    width = pixbuf.get_width()
    height = pixbuf.get_height()
    if width < target_w or height < target_h:
        return pixbuf
    x = max(0, (width - target_w) // 2)
    y = max(0, (height - target_h) // 2)
    return GdkPixbuf.Pixbuf.new_subpixbuf(pixbuf, x, y, target_w, target_h)

def ensure_thumbnail_cache(version):
    cache_dir = thumbnail_cache_dir()
    version_path = os.path.join(cache_dir, ".version")
    try:
        with open(version_path, "r", encoding="utf-8") as handle:
            if handle.read().strip() == version:
                return
    except Exception:
        pass

    if os.path.isdir(cache_dir):
        try:
            for name in os.listdir(cache_dir):
                if name.endswith(".png"):
                    try:
                        os.remove(os.path.join(cache_dir, name))
                    except Exception:
                        pass
        except Exception:
            pass
    else:
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except Exception:
            return
    try:
        with open(version_path, "w", encoding="utf-8") as handle:
            handle.write(version)
    except Exception:
        pass

def add_border(pixbuf, radius, color=(1.0, 1.0, 1.0, 0.2), width_px=1.0):
    if not HAVE_CAIRO:
        return pixbuf
    if pixbuf is None:
        return pixbuf
    width = pixbuf.get_width()
    height = pixbuf.get_height()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    Gdk.cairo_set_source_pixbuf(ctx, pixbuf, 0, 0)
    ctx.paint()
    _rounded_rect(ctx, width_px / 2.0, width_px / 2.0, width - width_px, height - width_px, radius)
    ctx.set_source_rgba(*color)
    ctx.set_line_width(width_px)
    ctx.stroke()
    return Gdk.pixbuf_get_from_surface(surface, 0, 0, width, height)


def parse_matugen_output(output, mode):
    colors_by_name = {}
    current_mode = None
    for line in output.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("light") and HEX_RE.search(stripped) is None:
            current_mode = "light"
            continue
        if lower.startswith("dark") and HEX_RE.search(stripped) is None:
            current_mode = "dark"
            continue
        hexes = [h.lower() for h in HEX_RE.findall(line)]
        if not hexes:
            continue
        for key, pattern in KEY_PATTERNS.items():
            if pattern.search(line):
                entry = colors_by_name.setdefault(key, {})
                if len(hexes) >= 2:
                    entry["light"] = hexes[0]
                    entry["dark"] = hexes[1]
                else:
                    if current_mode in ("light", "dark"):
                        entry[current_mode] = hexes[0]
                    else:
                        entry.setdefault("light", hexes[0])
                        entry.setdefault("dark", hexes[0])
                break

    resolved = {}
    for name in KEY_COLORS:
        entry = colors_by_name.get(name)
        if not entry:
            continue
        resolved[name] = entry.get(mode, "")
    return resolved


def set_widget_color(widget, color):
    css = """
    .swatch {
        background-color: %s;
        border: 1px solid #222;
        border-radius: 4px;
    }
    """ % (
        color,
    )
    provider = Gtk.CssProvider()
    provider.load_from_data(css.encode("utf-8"))
    context = widget.get_style_context()
    context.add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    context.add_class("swatch")

def ensure_value_in_list(value, options):
    if value and value not in options:
        return [value] + list(options)
    return list(options)

class MatugenWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Jasmine 🍚")
        self.set_default_size(1100, 700)
        self.settings = load_settings()
        self.swww_settings = load_swww_settings_from_config()
        self._request_id = 0
        self._thumb_request_id = 0
        self._thumb_shimmer_id = None
        self.settings_window = None
        self._palette_provider = None
        self._current_folder = None
        self.get_style_context().add_class("palette-window")

        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property("gtk-tooltip-timeout", 300)

        ensure_thumbnail_cache(THUMBNAIL_CACHE_VERSION)
        self._thumb_placeholders = self._create_thumb_placeholders()

        self._build_ui()
        self._load_images(self.settings["images_folder"])

        self.add_events(Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("key-press-event", self._on_keypress)

    def _build_ui(self):
        self.set_decorated(False)

        self.root_overlay = Gtk.Overlay()
        self.add(self.root_overlay)
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        main_box.set_margin_top(8)
        main_box.set_margin_bottom(0)
        main_box.set_margin_start(8)
        main_box.set_margin_end(8)
        self.root_overlay.add(main_box)

        self.center_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.center_panel.set_hexpand(True)
        main_box.pack_start(self.center_panel, True, True, 0)

        self.notebook = Gtk.Notebook()
        self.notebook.set_show_tabs(False)
        self.notebook.set_show_border(False)
        self.notebook.set_hexpand(True)
        self.notebook.set_vexpand(True)
        self.center_panel.pack_start(self.notebook, True, True, 0)

        self.wallpaper_tab = build_wallpaper_tab(self)
        self.notebook.append_page(self.wallpaper_tab, Gtk.Label(label="Wallpaper"))

        self.settings_revealer = Gtk.Revealer()
        self.settings_revealer.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self.settings_revealer.set_transition_duration(220)
        self.settings_revealer.set_reveal_child(False)
        self.settings_revealer.set_no_show_all(True)
        self.settings_revealer.hide()
        self.settings_revealer.set_size_request(0, -1)
        self.settings_revealer.set_valign(Gtk.Align.FILL)
        self.settings_revealer.set_margin_top(8)
        self.settings_revealer.set_margin_end(8)
        main_box.pack_start(self.settings_revealer, False, False, 0)

        self.settings_panel = Gtk.Overlay()
        self.settings_panel.set_size_request(SIDEBAR_WIDTH, -1)
        self.settings_panel.set_valign(Gtk.Align.FILL)
        self.settings_revealer.add(self.settings_panel)


        settings_top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        settings_top.set_valign(Gtk.Align.START)
        settings_top.set_margin_top(16)
        self.settings_panel.add(settings_top)

        settings_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        settings_header.set_halign(Gtk.Align.FILL)
        settings_top.pack_start(settings_header, False, False, 0)
        settings_header.pack_start(Gtk.Label(label=""), True, True, 0)

        self.settings_stack = Gtk.Stack()
        self.settings_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.settings_stack.set_transition_duration(180)
        settings_top.pack_start(self.settings_stack, True, True, 0)

        wallpaper_settings = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.settings_stack.add_named(wallpaper_settings, "wallpaper")

        self.settings_stack.set_visible_child_name("wallpaper")

        self.center_menu_button = Gtk.Button()
        center_menu_icon = Gtk.Image.new_from_icon_name(
            "open-menu-symbolic", Gtk.IconSize.BUTTON
        )
        self.center_menu_button.add(center_menu_icon)
        self.center_menu_button.connect("clicked", self._open_settings_window)

        self.panel_toggle = Gtk.Button()
        self.toggle_icon = Gtk.Image.new_from_icon_name(
            "pan-start-symbolic", Gtk.IconSize.BUTTON
        )
        self.panel_toggle.add(self.toggle_icon)
        self.panel_toggle.connect("clicked", self._toggle_settings_panel)

        self.top_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.top_controls.set_halign(Gtk.Align.END)
        self.top_controls.set_valign(Gtk.Align.START)
        self.top_controls.set_margin_top(6)
        self.top_controls.set_margin_end(6)
        self.top_controls.pack_start(self.panel_toggle, False, False, 0)
        self.top_controls.pack_start(self.center_menu_button, False, False, 0)
        self.root_overlay.add_overlay(self.top_controls)

        matugen_settings = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        matugen_settings.set_margin_top(6)
        matugen_expander = Gtk.Expander()
        matugen_label = Gtk.Label(label="Matugen")
        matugen_label.set_xalign(0.0)
        matugen_label.get_style_context().add_class("section-label")
        matugen_expander.set_label_widget(matugen_label)
        matugen_expander.set_expanded(True)
        matugen_expander.add(matugen_settings)
        wallpaper_settings.pack_start(matugen_expander, False, False, 0)

        swww_settings = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        swww_settings.set_margin_top(6)
        swww_expander = Gtk.Expander()
        swww_label = Gtk.Label(label="swww")
        swww_label.set_xalign(0.0)
        swww_label.get_style_context().add_class("section-label")
        swww_expander.set_label_widget(swww_label)
        swww_expander.set_expanded(True)
        swww_expander.add(swww_settings)
        wallpaper_settings.pack_start(swww_expander, False, False, 0)

        theme_label = Gtk.Label(label="Theme")
        theme_label.set_xalign(0)
        matugen_settings.pack_start(theme_label, False, False, 0)

        self.theme_combo = Gtk.ComboBoxText()
        themes = [
            "scheme-content",
            "scheme-expressive",
            "scheme-fidelity",
            "scheme-fruit-salad",
            "scheme-monochrome",
            "scheme-neutral",
            "scheme-rainbow",
            "scheme-tonal-spot",
        ]
        theme_labels = [theme.replace("scheme-", "", 1) for theme in themes]
        self._theme_values = themes
        for label in theme_labels:
            self.theme_combo.append_text(label)
        if self.settings["theme"] in themes:
            self.theme_combo.set_active(themes.index(self.settings["theme"]))
        else:
            self.theme_combo.set_active(themes.index("scheme-tonal-spot"))
        self.theme_combo.connect("changed", self._on_theme_changed)
        matugen_settings.pack_start(self.theme_combo, False, False, 0)

        mode_label = Gtk.Label(label="Mode")
        mode_label.set_xalign(0)
        matugen_settings.pack_start(mode_label, False, False, 0)

        self.mode_combo = Gtk.ComboBoxText()
        for mode in ["dark", "light"]:
            self.mode_combo.append_text(mode)
        if self.settings["mode"] in ("dark", "light"):
            self.mode_combo.set_active(0 if self.settings["mode"] == "dark" else 1)
        else:
            self.mode_combo.set_active(0)
        self.mode_combo.connect("changed", self._on_mode_changed)
        matugen_settings.pack_start(self.mode_combo, False, False, 0)

        contrast_label = Gtk.Label(label="Contrast")
        contrast_label.set_xalign(0)
        matugen_settings.pack_start(contrast_label, False, False, 0)

        contrast_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.contrast_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, -1, 1, 1
        )
        self.contrast_scale.set_value(self.settings["contrast"])
        self.contrast_scale.set_digits(0)
        self.contrast_scale.connect("value-changed", self._on_contrast_changed)
        contrast_row.pack_start(self.contrast_scale, True, True, 0)

        self.contrast_value = Gtk.Label(label=str(self.settings["contrast"]))
        self.contrast_value.set_xalign(1)
        contrast_row.pack_start(self.contrast_value, False, False, 0)
        matugen_settings.pack_start(contrast_row, False, False, 0)

        transition_values = ensure_value_in_list(
            self.swww_settings["transition_type"], SWWW_TRANSITIONS
        )
        transition_row, self.swww_transition_combo = self._make_combo_row(
            "Transition", transition_values, self.swww_settings["transition_type"], "transition_type"
        )
        swww_settings.pack_start(transition_row, False, False, 0)

        resize_values = ensure_value_in_list(self.swww_settings["resize"], SWWW_RESIZE_TYPES)
        resize_row, self.swww_resize_combo = self._make_combo_row(
            "Resize", resize_values, self.swww_settings["resize"], "resize"
        )
        swww_settings.pack_start(resize_row, False, False, 0)

        duration_row, self.swww_duration_entry = self._make_entry_row(
            "Duration", self.swww_settings["duration"], "duration"
        )
        swww_settings.pack_start(duration_row, False, False, 0)

        fps_row, self.swww_fps_entry = self._make_entry_row(
            "FPS", self.swww_settings["fps"], "fps"
        )
        swww_settings.pack_start(fps_row, False, False, 0)

        degree_row, self.swww_degree_entry = self._make_entry_row(
            "Angle", self.swww_settings["degree"], "degree"
        )
        swww_settings.pack_start(degree_row, False, False, 0)

        step_row, self.swww_step_entry = self._make_entry_row(
            "Step", self.swww_settings["step"], "step"
        )
        swww_settings.pack_start(step_row, False, False, 0)

        fill_row, self.swww_fill_entry = self._make_entry_row(
            "Fill Color", self.swww_settings["fill_color"], "fill_color"
        )
        swww_settings.pack_start(fill_row, False, False, 0)

    def _create_thumb_placeholders(self):
        base = GdkPixbuf.Pixbuf.new(
            GdkPixbuf.Colorspace.RGB, True, 8, 96, 64
        )
        base.fill(0x2A2A2A40)
        base = add_border(base, 6, color=(1.0, 1.0, 1.0, 0.15), width_px=2.0)
        if not HAVE_CAIRO:
            return [base]

        def shimmer_frame(offset):
            width = base.get_width()
            height = base.get_height()
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            ctx = cairo.Context(surface)
            Gdk.cairo_set_source_pixbuf(ctx, base, 0, 0)
            ctx.paint()
            ctx.set_source_rgba(1.0, 1.0, 1.0, 0.18)
            ctx.rectangle(offset, 0, 26, height)
            ctx.fill()
            return Gdk.pixbuf_get_from_surface(surface, 0, 0, width, height)

        return [base, shimmer_frame(-10), shimmer_frame(30)]

    def _choose_folder(self, _button=None):
        dialog = Gtk.FileChooserDialog(
            title="Select Image Folder",
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN,
            Gtk.ResponseType.OK,
        )
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            folder = dialog.get_filename()
            if folder:
                self.settings["images_folder"] = folder
                save_settings(self.settings)
                if hasattr(self, "folder_value"):
                    self.folder_value.set_text(folder)
        dialog.destroy()

    def _load_images(self, folder, select_first=True, fade_preview=True):
        self._thumb_request_id += 1
        thumb_request_id = self._thumb_request_id
        for child in self.thumb_flow.get_children():
            self.thumb_flow.remove(child)

        if not os.path.isdir(folder):
            return
        self._current_folder = folder

        exts = supported_image_exts()
        files = [
            name
            for name in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, name))
            and name.split(".")[-1].lower() in exts
        ]
        files.sort(key=str.lower)

        new_children = []
        for name in files:
            path = os.path.join(folder, name)
            image = Gtk.Image.new_from_pixbuf(self._thumb_placeholders[0])
            image.set_size_request(96, 64)
            child = Gtk.FlowBoxChild()
            child.set_size_request(96, 64)
            child.set_halign(Gtk.Align.CENTER)
            child.set_valign(Gtk.Align.CENTER)
            child.get_style_context().add_class("thumb-cell")
            child.add(image)
            child.set_tooltip_text(name)
            child.image_path = path
            child.image_widget = image
            child.image_loaded = False
            self.thumb_flow.add(child)
            new_children.append(child)

        self.thumb_flow.show_all()
        if new_children:
            self._start_thumb_shimmer(new_children, thumb_request_id)
            self._start_thumb_loader(new_children, thumb_request_id)
        children = self.thumb_flow.get_children()
        if select_first and children:
            self.thumb_flow.select_child(children[0])
            self._set_preview_from_child(children[0], fade_preview=fade_preview)

    def _start_thumb_loader(self, children, request_id):
        def worker():
            for child in children:
                if request_id != self._thumb_request_id:
                    return
                path = getattr(child, "image_path", None)
                if not path:
                    continue
                thumb = load_thumbnail(path)
                if thumb is None:
                    continue
                thumb = round_pixbuf(thumb, 6)
                thumb = add_border(thumb, 6, color=(1.0, 1.0, 1.0, 0.4), width_px=2.0)
                GLib.idle_add(self._apply_thumb, child, thumb, request_id)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def _start_thumb_shimmer(self, children, request_id):
        if len(self._thumb_placeholders) < 2:
            return
        if self._thumb_shimmer_id is not None:
            return
        state = {"index": 0}

        def tick():
            if request_id != self._thumb_request_id:
                self._thumb_shimmer_id = None
                return False
            any_pending = False
            for child in children:
                if request_id != self._thumb_request_id:
                    self._thumb_shimmer_id = None
                    return False
                if getattr(child, "image_loaded", False):
                    continue
                any_pending = True
                image = getattr(child, "image_widget", None)
                if image is not None:
                    image.set_from_pixbuf(self._thumb_placeholders[state["index"]])
            if not any_pending:
                self._thumb_shimmer_id = None
                return False
            state["index"] = (state["index"] + 1) % len(self._thumb_placeholders)
            return True

        self._thumb_shimmer_id = GLib.timeout_add(140, tick)

    def _apply_thumb(self, child, pixbuf, request_id):
        if request_id != self._thumb_request_id:
            return False
        image = getattr(child, "image_widget", None)
        if image is not None:
            image.set_from_pixbuf(pixbuf)
            image.set_size_request(96, 64)
        child.image_loaded = True
        return False

    def _on_thumb_activated(self, _flowbox, child):
        self._set_preview_from_child(child)

    def _set_preview_from_child(self, child, fade_preview=True):
        path = getattr(child, "image_path", None)
        if not path:
            return
        self._set_preview_image(path, fade=fade_preview)
        self._run_matugen(path, palette_fade_ms=120 if fade_preview else 500)

    def _set_preview_image(self, path, fade=True):
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        except Exception:
            return
        height = 360
        if pixbuf.get_height() > 0:
            scale = height / float(pixbuf.get_height())
            width = max(1, int(pixbuf.get_width() * scale))
        else:
            width = 1
        scaled = pixbuf.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)
        if scaled is None:
            return
        scaled = round_pixbuf(scaled, 16)
        scaled = add_border(scaled, 16, color=(1.0, 1.0, 1.0, 0.4), width_px=2.0)
        def apply_pixbuf():
            self.preview_image.set_from_pixbuf(scaled)
        if fade:
            self._fade_widget(self.preview_image, apply_pixbuf, duration_ms=550)
        else:
            apply_pixbuf()

    def _fade_widget(self, widget, update_func, duration_ms=900):
        if not hasattr(self, "_fade_jobs"):
            self._fade_jobs = {}
        token = self._fade_jobs.get(widget, 0) + 1
        self._fade_jobs[widget] = token

        steps = 24
        step_ms = max(12, int(duration_ms / (2 * steps)))
        phase = {"name": "out", "step": 0}

        def tick():
            if self._fade_jobs.get(widget) != token:
                return False
            if phase["name"] == "out":
                t = phase["step"] / float(steps)
                widget.set_opacity(max(0.0, 1.0 - t))
                if phase["step"] >= steps:
                    update_func()
                    phase["name"] = "in"
                    phase["step"] = 0
                else:
                    phase["step"] += 1
                return True

            t = phase["step"] / float(steps)
            widget.set_opacity(min(1.0, t))
            if phase["step"] >= steps:
                widget.set_opacity(1.0)
                return False
            phase["step"] += 1
            return True

        GLib.timeout_add(step_ms, tick)

    def _fade_out_widget(self, widget, duration_ms=300):
        if not hasattr(self, "_fade_jobs"):
            self._fade_jobs = {}
        token = self._fade_jobs.get(widget, 0) + 1
        self._fade_jobs[widget] = token

        steps = 18
        step_ms = max(12, int(duration_ms / steps))
        step = {"value": 0}

        def tick():
            if self._fade_jobs.get(widget) != token:
                return False
            t = step["value"] / float(steps)
            widget.set_opacity(max(0.0, 1.0 - t))
            if step["value"] >= steps:
                widget.set_opacity(0.0)
                return False
            step["value"] += 1
            return True

        GLib.timeout_add(step_ms, tick)

    def _set_sparkle_markup(self, label, symbol, color):
        label.set_markup('<span foreground="%s">%s</span>' % (color, symbol))

    def _emit_sparkle(self):
        width = max(1, self.root_overlay.get_allocated_width())
        height = max(1, self.root_overlay.get_allocated_height())
        if width < 2 or height < 2:
            return
        if not self.sparkle_labels:
            return
        label = self.sparkle_labels[self._sparkle_index % len(self.sparkle_labels)]
        self._sparkle_index += 1
        symbol = random.choice(self._sparkle_symbols)
        color = random.choice(self._sparkle_colors)
        self._set_sparkle_markup(label, symbol, color)
        x = random.randint(12, max(12, width - 24))
        y = random.randint(12, max(12, height - 24))
        label.set_margin_start(x)
        label.set_margin_top(y)
        label.set_opacity(1.0)
        self._fade_out_widget(label, duration_ms=random.randint(1400, 2200))

    def _start_sparkle_loop(self):
        def tick():
            self._emit_sparkle()
            return True

        GLib.timeout_add(240, tick)

    def _apply_styles(self):
        font_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets",
            "jasmine.ttf",
        )
        font_url = "file://%s" % font_path
        css = """
        @font-face {
            font-family: "Jasmine";
            src: url("%s");
        }
        .title-label {
            font-family: "Jasmine";
            font-size: 22px;
            color: #9A232A;
            text-shadow: 1px 0 rgba(255, 255, 255, 0.5), -1px 0 rgba(255, 255, 255, 0.5),
                0 1px rgba(255, 255, 255, 0.5), 0 -1px rgba(255, 255, 255, 0.5);
        }
        """ % (font_url,)
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode("utf-8"))
        screen = Gdk.Screen.get_default()
        if screen is not None:
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _on_theme_changed(self, combo):
        index = combo.get_active()
        if index < 0:
            return
        if hasattr(self, "_theme_values") and index < len(self._theme_values):
            value = self._theme_values[index]
        else:
            value = combo.get_active_text()
        if value:
            self.settings["theme"] = value
            save_settings(self.settings)
            self._rerun_matugen()

    def _on_mode_changed(self, combo):
        value = combo.get_active_text()
        if value:
            self.settings["mode"] = value
            save_settings(self.settings)
            self._rerun_matugen()

    def _on_contrast_changed(self, scale):
        value = int(scale.get_value())
        self.settings["contrast"] = value
        self.contrast_value.set_text(str(value))
        save_settings(self.settings)
        self._rerun_matugen()

    def _make_combo_row(self, label_text, options, active_value, key):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        label = Gtk.Label(label=label_text)
        label.set_xalign(0)
        row.pack_start(label, False, False, 0)

        combo = Gtk.ComboBoxText()
        for option in options:
            combo.append_text(option)
        if active_value in options:
            combo.set_active(options.index(active_value))
        elif options:
            combo.set_active(0)
        combo.connect("changed", self._on_swww_changed, key)
        row.pack_start(combo, False, False, 0)
        return row, combo

    def _make_entry_row(self, label_text, value, key):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        label = Gtk.Label(label=label_text)
        label.set_xalign(0)
        row.pack_start(label, False, False, 0)

        entry = Gtk.Entry()
        entry.set_text(str(value))
        entry.set_width_chars(6)
        tooltip = self._swww_tooltip_for_key(key)
        if tooltip:
            entry.set_tooltip_text(tooltip)
        entry.connect("activate", self._on_swww_entry_commit, key)
        entry.connect("focus-out-event", self._on_swww_entry_commit, key)
        row.pack_start(entry, False, False, 0)
        return row, entry

    def _on_swww_changed(self, combo, key):
        value = combo.get_active_text()
        if not value:
            return
        self.swww_settings[key] = value
        self._write_swww_settings()

    def _on_swww_entry_commit(self, entry, event_or_key=None, key=None):
        if key is None and isinstance(event_or_key, str):
            key = event_or_key
        if key is None:
            return False
        text = entry.get_text().strip()
        if key == "duration":
            try:
                value = float(text)
            except ValueError:
                value = None
            if value is None or value < 0:
                entry.set_text(str(self.swww_settings[key]))
                return False
            cleaned = ("%g" % value)
        elif key == "fps":
            try:
                value = int(text)
            except ValueError:
                value = None
            if value is None or value < 1 or value > 255:
                entry.set_text(str(self.swww_settings[key]))
                return False
            cleaned = str(value)
        elif key == "degree":
            try:
                value = int(text)
            except ValueError:
                value = None
            if value is None or value < 0 or value > 360:
                entry.set_text(str(self.swww_settings[key]))
                return False
            cleaned = str(value)
        elif key == "step":
            try:
                value = float(text)
            except ValueError:
                value = None
            if value is None or value < 0:
                entry.set_text(str(self.swww_settings[key]))
                return False
            cleaned = ("%g" % value)
        elif key == "fill_color":
            if not text:
                cleaned = ""
            else:
                value = text.lstrip("#")
                if not re.match(r"^[0-9a-fA-F]{6}$", value):
                    entry.set_text(str(self.swww_settings[key]))
                    return False
                cleaned = value
        else:
            return False

        self.swww_settings[key] = cleaned
        entry.set_text(cleaned)
        self._write_swww_settings()
        return False

    def _write_swww_settings(self):
        try:
            args = build_swww_args(self.swww_settings)
            write_matugen_wallpaper_args(args)
        except Exception:
            pass

    def _swww_tooltip_for_key(self, key):
        if key == "step":
            return (
                "How fast the transition approaches the new image.\n"
                "Larger values are faster but more abrupt; 255 switches immediately.\n"
                "Default: 90 (2 for 'simple' transition)"
            )
        if key == "duration":
            return (
                "How long the transition takes in seconds.\n"
                "Does not work with 'simple' transition.\n"
                "Default: 3"
            )
        if key == "fps":
            return (
                "Frame rate for the transition effect.\n"
                "Different from step (step controls per-frame change).\n"
                "Default: 30"
            )
        if key == "degree":
            return (
                "Angle of the transition effect in degrees.\n"
                "Default: 0"
            )
        if key == "resize":
            return (
                "Resize mode for the wallpaper.\n"
                "crop fills the screen; fit keeps aspect with bars.\n"
                "center shows original size; zoom is similar to crop."
            )
        if key == "fill_color":
            return (
                "Background color for fit/center modes.\n"
                "Hex color like 000000."
            )
        return ""

    def _rerun_matugen(self):
        selected = self.thumb_flow.get_selected_children()
        if not selected:
            return
        self._set_preview_from_child(selected[0], fade_preview=False)

    def _open_settings_window(self, _button=None):
        if self.settings_window is not None:
            self.settings_window.present()
            return

        window = Gtk.Window(title="Settings", transient_for=self)
        window.get_style_context().add_class("palette-window")
        window.set_default_size(360, 320)
        window.set_border_width(12)
        window.connect("key-press-event", self._on_settings_keypress)
        window.connect("delete-event", self._on_settings_delete)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        window.add(content)

        folder_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        folder_label = Gtk.Label(label="Image Folder")
        folder_label.set_xalign(0)
        folder_row.pack_start(folder_label, False, False, 0)
        self.folder_value = Gtk.Label(label=self.settings["images_folder"])
        self.folder_value.set_xalign(0)
        self.folder_value.set_line_wrap(True)
        folder_row.pack_start(self.folder_value, False, False, 0)
        choose_button = Gtk.Button(label="Choose Folder...")
        choose_button.connect("clicked", self._choose_folder)
        folder_row.pack_start(choose_button, False, False, 0)
        content.pack_start(folder_row, False, False, 0)

        apply_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        apply_row.set_halign(Gtk.Align.END)
        apply_button = Gtk.Button(label="Apply & Close")
        apply_button.connect("clicked", self._on_settings_apply_close)
        apply_row.pack_start(apply_button, False, False, 0)
        content.pack_start(apply_row, False, False, 0)

        window.connect("destroy", self._on_settings_destroy)
        window.show_all()
        self.settings_window = window

    def _on_settings_destroy(self, _window):
        self.settings_window = None

    def _on_settings_delete(self, window, _event):
        window.destroy()
        return True

    def _on_settings_apply_close(self, _button):
        save_settings(self.settings)
        if self.settings["images_folder"] != self._current_folder:
            self._load_images(self.settings["images_folder"], fade_preview=False)
        else:
            self._rerun_matugen()
        if self.settings_window is not None:
            self.settings_window.destroy()

    def _on_settings_keypress(self, window, event):
        if event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval == Gdk.KEY_comma:
            window.destroy()
            return True
        if event.keyval == Gdk.KEY_Escape:
            window.destroy()
            return True
        return False

    def _run_matugen(self, path, palette_fade_ms=500):
        self._request_id += 1
        request_id = self._request_id
        if not hasattr(self, "_palette_fades"):
            self._palette_fades = {}
        self._palette_fades[request_id] = palette_fade_ms

        def worker():
            try:
                args = [
                    "matugen",
                    "image",
                    path,
                    "--dry-run",
                    "--show-colors",
                    "-t",
                    self.settings["theme"],
                    "-m",
                    self.settings["mode"],
                    "--contrast",
                    str(self.settings["contrast"]),
                ]
                result = subprocess.run(
                    args, capture_output=True, text=True, check=False
                )
                output = (result.stdout or "") + "\n" + (result.stderr or "")
                palette = parse_matugen_output(output, self.settings["mode"])
            except Exception:
                palette = {}
            GLib.idle_add(self._update_palette, palette, request_id)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def _apply_matugen(self, _button):
        selected = self.thumb_flow.get_selected_children()
        if not selected:
            return
        path = getattr(selected[0], "image_path", None)
        if not path:
            return
        args = [
            "matugen",
            "image",
            path,
            "-t",
            self.settings["theme"],
            "-m",
            self.settings["mode"],
            "--contrast",
            str(self.settings["contrast"]),
        ]
        subprocess.Popen(args)


    def _update_palette(self, palette, request_id):
        if request_id != self._request_id:
            return False
        for child in self.palette_grid.get_children():
            self.palette_grid.remove(child)

        if not palette:
            label = Gtk.Label(label="No colors detected.")
            label.set_xalign(0)
            self.palette_grid.attach(label, 0, 0, 1, 1)
            self.palette_grid.show_all()
            return False

        for idx, key in enumerate(SWATCH_COLORS):
            color = palette.get(key)
            if not color:
                continue
            swatch = Gtk.Box()
            swatch.set_size_request(22, 22)
            set_widget_color(swatch, color)
            self.palette_grid.attach(swatch, idx, 0, 1, 1)
        self.palette_grid.show_all()
        fade_ms = 500
        if hasattr(self, "_palette_fades"):
            fade_ms = self._palette_fades.pop(request_id, 500)
        self._fade_widget(self.palette_grid, lambda: None, duration_ms=fade_ms)
        self._apply_palette_style(palette)
        self._update_sparkle_colors(palette)
        return False

    def _apply_palette_style(self, palette):
        bg = palette.get("background")
        fg = palette.get("on_background")
        accent = palette.get("primary_container") or palette.get("primary")
        logo_border = palette.get("on_surface") or fg
        if not bg or not fg:
            return
        border = hex_to_rgba(fg, "0.35")
        accent_bg = accent or fg
        css = """
        .palette-window {
            background-color: %s;
        }
        .palette-window * {
            color: %s;
        }
        .palette-window headerbar {
            background-color: %s;
        }
        .palette-window headerbar * {
            color: %s;
        }
        .palette-window button,
        .palette-window combobox,
        .palette-window scale,
        .palette-window entry {
            color: %s;
            background-color: %s;
            border-color: %s;
        }
        .palette-window scale trough {
            background-color: %s;
        }
        .palette-window scale slider {
            background-color: %s;
            border-color: %s;
        }
        .palette-window flowboxchild:selected {
            background-color: %s;
            border-radius: 8px;
        }
        .palette-window checkbutton,
        .palette-window togglebutton {
            color: %s;
            background-color: %s;
            border-color: %s;
        }
        .palette-window checkbutton * {
            color: %s;
        }
        .palette-window checkbutton check,
        .palette-window checkbutton indicator,
        .palette-window checkbutton image,
        .palette-window togglebutton check,
        .palette-window togglebutton indicator,
        .palette-window togglebutton image {
            background-color: %s;
            border-color: %s;
            color: %s;
            background-image: none;
            box-shadow: none;
            -gtk-icon-source: none;
        }
        .palette-window checkbutton check:checked,
        .palette-window checkbutton check:active,
        .palette-window togglebutton check:checked,
        .palette-window togglebutton check:active {
            background-color: %s;
            border-color: %s;
            color: %s;
            background-image: none;
            box-shadow: none;
            -gtk-icon-source: none;
        }
        .palette-window checkbutton check:hover,
        .palette-window togglebutton check:hover {
            background-color: %s;
            border-color: %s;
            background-image: none;
            box-shadow: none;
            -gtk-icon-source: none;
        }
        .palette-window frame,
        .palette-window frame > border {
            border-color: %s;
        }
        .palette-window notebook > header {
            background-color: %s;
            border-color: %s;
            box-shadow: none;
        }
        .palette-window notebook > header > tabs {
            background-color: %s;
            border-color: %s;
            box-shadow: none;
        }
        .palette-window notebook > header > tabs > tab {
            background-color: %s;
            color: %s;
            border-color: %s;
            border-image: none;
            box-shadow: none;
            outline-color: transparent;
            border-radius: 10px;
            padding: 4px 8px;
        }
        .palette-window notebook > header > tabs > tab label {
            color: %s;
        }
        .palette-window notebook > header > tabs > tab:checked {
            background-color: %s;
            color: %s;
            border-bottom-color: %s;
            box-shadow: none;
        }
        .section-expander,
        .section-expander > box,
        .section-expander > box > box {
            background-color: transparent;
            border-color: transparent;
            box-shadow: none;
        }
        .section-expander > title {
            padding: 6px 8px;
            border-radius: 10px;
            background-color: %s;
            color: %s;
        }
        .section-expander > title > arrow {
            color: transparent;
            background-color: transparent;
            border: none;
            box-shadow: none;
            min-width: 0;
            min-height: 0;
            margin: 0;
            padding: 0;
            -gtk-icon-source: none;
        }
        .section-expander > title button {
            background-color: transparent;
            border: none;
            box-shadow: none;
            color: %s;
        }
        .palette-window notebook,
        .palette-window notebook > stack,
        .palette-window notebook > stack > box,
        .palette-window scrolledwindow,
        .palette-window viewport,
        .palette-window scrolledwindow > viewport > box,
        .palette-window scrolledwindow > viewport > box > box {
            background-color: %s;
        }
        .palette-window frame > border {
            background-color: transparent;
        }
        .logo-label {
            color: %s;
            text-shadow: 1px 0 %s, -1px 0 %s, 0 1px %s, 0 -1px %s;
            font-family: "Jasmine";
            font-size: 50px;
        }
        .kawaii-sticker {
            color: rgba(255, 182, 193, 0.85);
            font-size: 12px;
        }
        .kawaii-sparkle {
            color: rgba(255, 214, 226, 0.95);
            font-size: 14px;
        }
        .section-label {
            font-weight: 600;
        }
        """ % (
            bg,
            fg,
            bg,
            fg,
            fg,
            hex_to_rgba(bg, "0.15"),
            border,
            hex_to_rgba(bg, "0.25"),
            accent_bg,
            border,
            hex_to_rgba(accent_bg, "0.45"),
            fg,
            hex_to_rgba(bg, "0.15"),
            border,
            fg,
            hex_to_rgba(bg, "0.2"),
            border,
            fg,
            accent_bg,
            border,
            fg,
            hex_to_rgba(accent_bg, "0.4"),
            border,
            border,
            bg,
            border,
            bg,
            border,
            bg,
            fg,
            border,
            fg,
            accent_bg,
            bg,
            border,
            hex_to_rgba(bg, "0.12"),
            fg,
            fg,
            bg,
            fg,
            logo_border,
            logo_border,
            logo_border,
            logo_border,
        )
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode("utf-8"))
        screen = Gdk.Screen.get_default()
        if screen is not None:
            if self._palette_provider is not None:
                Gtk.StyleContext.remove_provider_for_screen(screen, self._palette_provider)
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            self._palette_provider = provider

    def _update_sparkle_colors(self, palette):
        colors = []
        for key in ("primary", "secondary", "tertiary", "primary_container"):
            value = palette.get(key)
            if value:
                colors.append(value)
        if not colors:
            colors = ["#ffd6e2", "#ffb6c1", "#ffe4ef"]
        self._sparkle_colors = colors





    def _on_keypress(self, _window, event):
        if event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval == Gdk.KEY_comma:
            if self.settings_window is not None:
                self.settings_window.destroy()
            else:
                self._open_settings_window()
            return True
        if event.keyval in (Gdk.KEY_Up, Gdk.KEY_Left):
            self._select_thumb_direction("up" if event.keyval == Gdk.KEY_Up else "left")
            return True
        if event.keyval in (Gdk.KEY_Down, Gdk.KEY_Right):
            self._select_thumb_direction("down" if event.keyval == Gdk.KEY_Down else "right")
            return True
        return False

    def _select_thumb_direction(self, direction):
        children = self.thumb_flow.get_children()
        if not children:
            return
        selected = self.thumb_flow.get_selected_children()
        if selected:
            current = selected[0]
            try:
                index = children.index(current)
            except ValueError:
                index = 0
        else:
            index = 0

        cols = self.thumb_flow.get_max_children_per_line()
        if cols <= 0:
            cols = 4
        total = len(children)
        rows = max(1, (total + cols - 1) // cols)
        row = index // cols
        col = index % cols

        if direction == "left":
            if col > 0:
                col -= 1
            else:
                row = (row - 1) % rows
                col = min(cols - 1, total - 1 - row * cols)
        elif direction == "right":
            row_len = min(cols, total - row * cols)
            if col < row_len - 1:
                col += 1
            else:
                row = (row + 1) % rows
                col = 0
        elif direction == "up":
            row = (row - 1) % rows
        elif direction == "down":
            row = (row + 1) % rows

        row_len = min(cols, total - row * cols)
        col = min(col, max(0, row_len - 1))
        new_index = row * cols + col
        new_child = children[new_index]
        self.thumb_flow.select_child(new_child)
        self._set_preview_from_child(new_child)

    def _toggle_settings_panel(self, _button):
        visible = self.settings_revealer.get_reveal_child()
        if visible:
            self._hide_settings_panel()
        else:
            self.settings_revealer.set_no_show_all(False)
            self.settings_revealer.show_all()
            self.settings_revealer.set_size_request(SIDEBAR_WIDTH, -1)
            self.settings_revealer.set_reveal_child(True)
            pos_x, pos_y = self.get_position()
            width, height = self.get_size()
            self.resize(width + SIDEBAR_WIDTH, height)
            self.move(pos_x, pos_y)
            self.toggle_icon.set_from_icon_name("pan-end-symbolic", Gtk.IconSize.BUTTON)

    def _hide_settings_panel(self):
        if not self.settings_revealer.get_reveal_child():
            return
        self.settings_revealer.set_reveal_child(False)
        self.settings_revealer.set_size_request(0, -1)
        self.settings_revealer.set_no_show_all(True)
        self.settings_revealer.hide()
        pos_x, pos_y = self.get_position()
        width, height = self.get_size()
        self.resize(max(1, width - SIDEBAR_WIDTH), height)
        self.move(pos_x, pos_y)
        self.toggle_icon.set_from_icon_name("pan-start-symbolic", Gtk.IconSize.BUTTON)



def main():
    window = MatugenWindow()
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
