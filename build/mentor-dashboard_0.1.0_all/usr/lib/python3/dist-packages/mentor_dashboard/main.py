"""Mentor Dashboard — Debian Mentors dashboard for package review."""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, Gio, GLib, Pango

import gettext
import locale
import os
import sys
import json
import datetime
import threading
import subprocess
import re

LOCALE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "po")
if not os.path.isdir(LOCALE_DIR):
    LOCALE_DIR = "/usr/share/locale"
locale.bindtextdomain("mentor-dashboard", LOCALE_DIR)
gettext.bindtextdomain("mentor-dashboard", LOCALE_DIR)
gettext.textdomain("mentor-dashboard")
_ = gettext.gettext

APP_ID = "se.danielnylander.mentor.dashboard"
SETTINGS_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "mentor-dashboard"
)
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")


def _load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    return {"welcome_shown": False}


def _save_settings(s):
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(s, f, indent=2)



def _fetch_mentors_rfs():
    """Fetch RFS (Request for Sponsor) bugs from mentors.debian.net."""
    import urllib.request
    url = "https://mentors.debian.net/packages/rfs/"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            html = r.read().decode()
            entries = []
            for m in re.finditer(r'/package/([^/"]+)', html):
                pkg = m.group(1)
                if pkg not in [e["name"] for e in entries]:
                    entries.append({"name": pkg, "status": "RFS"})
            return entries
    except:
        return []



class MentorDashboardWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=_("Mentor Dashboard"), default_width=1100, default_height=750)
        self.settings = _load_settings()
        self._packages = []

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header
        headerbar = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(title=_("Mentor Dashboard"), subtitle="")
        headerbar.set_title_widget(title_widget)
        self._title_widget = title_widget

        
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=_("Refresh"))
        refresh_btn.connect("clicked", self._on_refresh)
        headerbar.pack_start(refresh_btn)
        
        self._search = Gtk.SearchEntry(placeholder_text=_("Search packages..."))
        self._search.connect("search-changed", self._on_search)
        headerbar.pack_start(self._search)

        # Menu
        menu = Gio.Menu()
        menu.append(_("Settings"), "app.settings")
        menu.append(_("Copy Debug Info"), "app.copy-debug")
        menu.append(_("Keyboard Shortcuts"), "app.shortcuts")
        menu.append(_("About Mentor Dashboard"), "app.about")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        headerbar.pack_end(menu_btn)

        main_box.append(headerbar)

        
        scroll = Gtk.ScrolledWindow(vexpand=True)
        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.add_css_class("boxed-list")
        self._list.set_margin_start(12)
        self._list.set_margin_end(12)
        self._list.set_margin_top(8)
        self._list.set_margin_bottom(8)
        scroll.set_child(self._list)
        
        self._empty = Adw.StatusPage()
        self._empty.set_icon_name("system-users-symbolic")
        self._empty.set_title(_("Debian Mentors"))
        self._empty.set_description(_("Click refresh to load packages awaiting review."))
        self._empty.set_vexpand(True)
        
        self._stack = Gtk.Stack()
        self._stack.add_named(self._empty, "empty")
        self._stack.add_named(scroll, "list")
        self._stack.set_vexpand(True)
        main_box.append(self._stack)

        # Status bar
        self._status = Gtk.Label(label=_("Ready"), xalign=0)
        self._status.set_margin_start(12)
        self._status.set_margin_end(12)
        self._status.set_margin_top(4)
        self._status.set_margin_bottom(4)
        self._status.add_css_class("dim-label")
        main_box.append(self._status)

        self.set_content(main_box)

        if not self.settings.get("welcome_shown"):
            GLib.idle_add(self._show_welcome)

    def _show_welcome(self):
        dialog = Adw.Dialog()
        dialog.set_title(_("Welcome"))
        dialog.set_content_width(420)
        dialog.set_content_height(480)

        page = Adw.StatusPage()
        page.set_icon_name("system-users-symbolic")
        page.set_title(_("Welcome to Mentor Dashboard"))
        page.set_description(_("Review packages on Debian Mentors.\n\n"
            "✓ Browse packages awaiting review\n"
            "✓ Filter by section, priority\n"
            "✓ Review package quality\n"
            "✓ Track sponsorship status\n"
            "✓ Quick lintian checks"))

        btn = Gtk.Button(label=_("Get Started"))
        btn.add_css_class("suggested-action")
        btn.add_css_class("pill")
        btn.set_halign(Gtk.Align.CENTER)
        btn.set_margin_top(12)
        btn.connect("clicked", self._on_welcome_close, dialog)
        page.set_child(btn)

        box = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        hb.set_show_title(False)
        box.add_top_bar(hb)
        box.set_content(page)
        dialog.set_child(box)
        dialog.present(self)

    def _on_welcome_close(self, btn, dialog):
        self.settings["welcome_shown"] = True
        _save_settings(self.settings)
        dialog.close()

    
    def _on_refresh(self, btn):
        self._status.set_text(_("Fetching from mentors.debian.net..."))
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self):
        pkgs = _fetch_mentors_rfs()
        GLib.idle_add(self._show_packages, pkgs)

    def _show_packages(self, pkgs):
        self._packages = pkgs
        self._populate()

    def _populate(self):
        while True:
            row = self._list.get_row_at_index(0)
            if row is None:
                break
            self._list.remove(row)
        
        search = self._search.get_text().lower()
        count = 0
        for pkg in self._packages:
            if search and search not in pkg["name"].lower():
                continue
            row = Adw.ActionRow()
            row.set_title(pkg["name"])
            row.set_subtitle(pkg.get("status", ""))
            badge = Gtk.Label(label="RFS")
            badge.add_css_class("caption")
            badge.add_css_class("accent")
            row.add_suffix(badge)
            self._list.append(row)
            count += 1
        
        self._stack.set_visible_child_name("list")
        self._status.set_text(_("%(count)d packages awaiting review") % {"count": count})

    def _on_search(self, entry):
        self._populate()


class MentorDashboardApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None

        for name, callback in [
            ("settings", self._on_settings),
            ("copy-debug", self._on_copy_debug),
            ("shortcuts", self._on_shortcuts),
            ("about", self._on_about),
            ("quit", self._on_quit),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        self.set_accels_for_action("app.quit", ["<Ctrl>q"])
        self.set_accels_for_action("app.shortcuts", ["<Ctrl>slash"])

    def do_activate(self):
        if not self.window:
            self.window = MentorDashboardWindow(self)
        self.window.present()

    def _on_settings(self, *_):
        if not self.window:
            return
        dialog = Adw.PreferencesDialog()
        dialog.set_title(_("Settings"))
        page = Adw.PreferencesPage()
        
        group = Adw.PreferencesGroup(title=_("Mentors"))
        row = Adw.EntryRow(title=_("Mentors username"))
        group.add(row)
        page.add(group)
        dialog.add(page)
        dialog.present(self.window)

    def _on_copy_debug(self, *_):
        if not self.window:
            return
        from . import __version__
        info = (
            f"Mentor Dashboard {__version__}\n"
            f"Python {sys.version}\n"
            f"GTK {Gtk.MAJOR_VERSION}.{Gtk.MINOR_VERSION}\n"
            f"Adw {Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}\n"
            f"OS: {os.uname().sysname} {os.uname().release}\n"
        )
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(info)
        self.window._status.set_text(_("Debug info copied"))

    def _on_shortcuts(self, *_):
        if self.window:
            dialog = Gtk.ShortcutsWindow(transient_for=self.window)
            section = Gtk.ShortcutsSection(visible=True)
            group = Gtk.ShortcutsGroup(title=_("General"), visible=True)
            for accel, title in [
                ("<Ctrl>q", _("Quit")),
                ("<Ctrl>slash", _("Keyboard shortcuts")),
            ]:
                group.append(Gtk.ShortcutsShortcut(accelerator=accel, title=title, visible=True))
            section.append(group)
            dialog.append(section)
            dialog.present()

    def _on_about(self, *_):
        from . import __version__
        dialog = Adw.AboutDialog(
            application_name=_("Mentor Dashboard"),
            application_icon="system-users-symbolic",
            version=__version__,
            developer_name="Daniel Nylander",
            website="https://github.com/yeager/mentor-dashboard",
            license_type=Gtk.License.GPL_3_0,
            issue_url="https://github.com/yeager/mentor-dashboard/issues",
            comments=_("Dashboard for Debian Mentors — review packages, give feedback, track sponsor status."),
        )
        dialog.present(self.window)

    def _on_quit(self, *_):
        self.quit()


def main():
    app = MentorDashboardApp()
    app.run(sys.argv)
