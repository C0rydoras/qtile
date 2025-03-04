# -*- coding: utf-8 -*-
# Copyright (c) 2011 Florian Mounier
# Copyright (c) 2011 Mounier Florian
# Copyright (c) 2012 roger
# Copyright (c) 2012-2014 Tycho Andersen
# Copyright (c) 2012-2013 Craig Barnes
# Copyright (c) 2013 Tao Sauvage
# Copyright (c) 2014 Sean Vig
# Copyright (c) 2014 Adi Sieker
# Copyright (c) 2020 elParaguayo
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
from os import path

from libqtile import bar, pangocffi, utils
from libqtile.command.base import expose_command
from libqtile.log_utils import logger
from libqtile.notify import ClosedReason, notifier
from libqtile.widget import base


class Notify(base._TextBox):
    """
    A notify widget

    This widget can handle actions provided by notification clients. However, only the
    default action is supported, so if a client provides multiple actions then only the
    default (first) action can be invoked. Some programs will provide their own
    notification windows if the notification server does not support actions, so if you
    want your notifications to handle more than one action then specify ``False`` for
    the ``action`` option to disable all action handling. Unfortunately we cannot
    specify the capability for exactly one action.
    """

    defaults = [
        ("foreground_urgent", "ff0000", "Foreground urgent priority colour"),
        ("foreground_low", "dddddd", "Foreground low priority  colour"),
        ("default_timeout_low", 5, "Default timeout (seconds) for low urgency notifications."),
        ("default_timeout", 10, "Default timeout (seconds) for normal notifications"),
        ("default_timeout_urgent", None, "Default timeout (seconds) for urgent notifications"),
        ("audiofile", None, "Audiofile played during notifications"),
        ("action", True, "Enable handling of default action upon right click"),
        (
            "parse_text",
            None,
            "Function to parse and modify notifications. "
            "e.g. function in config that removes line returns:"
            "def my_func(text)"
            "   return text.replace('\n', '')"
            "then set option parse_text=my_func",
        ),
        ("background_urgent", "440000", "Background urgent priority colour"),
        ("background_low", "444444", "Background low priority colour"),
    ]
    capabilities = {"body", "actions"}

    def __init__(self, width=bar.CALCULATED, **config):
        base._TextBox.__init__(self, "", width, **config)
        self.add_defaults(Notify.defaults)
        self.current_id = 0

        default_callbacks = {
            "Button1": self.clear,
            "Button4": self.prev,
            "Button5": self.next,
        }
        if self.action:
            default_callbacks["Button3"] = self._invoke
        else:
            self.capabilities = Notify.capabilities.difference({"actions"})
        self.add_callbacks(default_callbacks)

        self.background_normal = self.background

    def _configure(self, qtile, bar):
        base._TextBox._configure(self, qtile, bar)
        self.layout = self.drawer.textlayout(
            self.text, self.foreground, self.font, self.fontsize, self.fontshadow, markup=True
        )
        if notifier is None:
            logger.warning("You must install dbus-next to use the Notify widget.")

        # Create a tuple of our default timeouts. Urgency is an integer of 0-2
        # (see https://specifications.freedesktop.org/notification-spec/notification-spec-latest.html#urgency-levels)
        # so they will work as the index of the tuple.
        self._timeouts = (
            self.default_timeout_low,
            self.default_timeout,
            self.default_timeout_urgent,
        )

    async def _config_async(self):
        if notifier is None:
            return

        await notifier.register(self.update, self.capabilities, on_close=self.on_close)

    def set_notif_text(self, notif):
        self.text = pangocffi.markup_escape_text(notif.summary)
        urgency = getattr(notif.hints.get("urgency"), "value", 1)
        if urgency != 1:
            self.text = '<span color="%s">%s</span>' % (
                utils.hex(self.foreground_urgent if urgency == 2 else self.foreground_low),
                self.text,
            )
            self.background = self.background_urgent if urgency == 2 else self.background_low
        else:
            self.background = self.background_normal

        if notif.body:
            self.text = '<span weight="bold">%s</span> - %s' % (
                self.text,
                pangocffi.markup_escape_text(notif.body),
            )
        if callable(self.parse_text):
            try:
                self.text = self.parse_text(self.text)
            except:  # noqa: E722
                logger.exception("parse_text function failed:")
        if self.audiofile and path.exists(self.audiofile):
            self.qtile.spawn("aplay -q '%s'" % self.audiofile)

    def update(self, notif):
        self.qtile.call_soon_threadsafe(self.real_update, notif)

    def real_update(self, notif):
        self.set_notif_text(notif)
        self.current_id = notif.id - 1
        if notif.timeout and notif.timeout > 0:
            self.timeout_add(
                notif.timeout / 1000, self.clear, method_args=(ClosedReason.expired,)
            )
        else:
            urgency = getattr(notif.hints.get("urgency"), "value", 1)
            try:
                timeout = self._timeouts[urgency]
            except IndexError:
                logger.warning(
                    "Notification had an unexpected urgency value. Treating as normal priority."
                )
                timeout = self._timeouts[1]

            if timeout:
                self.timeout_add(timeout, self.clear, method_args=(ClosedReason.expired,))
        self.bar.draw()
        return True

    @expose_command()
    def display(self):
        if notifier is None:
            return

        self.set_notif_text(notifier.notifications[self.current_id])
        self.bar.draw()

    @expose_command()
    def clear(self, reason=ClosedReason.dismissed):
        """Clear the notification"""
        if notifier is None:
            return

        notifier._service.NotificationClosed(notifier.notifications[self.current_id].id, reason)
        self.text = ""
        self.background = self.background_normal
        self.current_id = len(notifier.notifications) - 1
        self.bar.draw()

    def on_close(self, nid):
        if self.current_id < len(notifier.notifications):
            notif = notifier.notifications[self.current_id]
            if notif.id == nid:
                self.clear(ClosedReason.method)

    @expose_command()
    def prev(self):
        """Show previous notification."""
        if self.current_id > 0:
            self.current_id -= 1
        self.display()

    @expose_command()
    def next(self):
        if notifier is None:
            return

        """Show next notification."""
        if self.current_id < len(notifier.notifications) - 1:
            self.current_id += 1
            self.display()

    def _invoke(self):
        if self.current_id < len(notifier.notifications):
            notif = notifier.notifications[self.current_id]
            if notif.actions:
                notifier._service.ActionInvoked(notif.id, notif.actions[0])
            self.clear()

    @expose_command()
    def toggle(self):
        """Toggle showing/clearing the notification"""
        if self.text == "":
            self.display()
        else:
            self.clear()

    @expose_command()
    def invoke(self):
        """Invoke the notification's default action"""
        if self.action:
            self._invoke()

    def finalize(self):
        notifier.unregister(self.update)
        base._TextBox.finalize(self)
