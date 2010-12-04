#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# «dell-recovery» - OEM Config plugin for Dell-Recovery Media
#
# Copyright (C) 2010, Dell Inc.
#
# Author:
#  - Mario Limonciello <Mario_Limonciello@Dell.com>
#
# This is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this application; if not, write to the Free Software Foundation, Inc., 51
# Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
##################################################################################

from ubiquity.plugin import PluginUI, InstallPlugin, Plugin
import subprocess
import os
import Dell.recovery_common as magic
import dbus
import syslog

NAME = 'dell-recovery'
AFTER = 'usersetup'
BEFORE = None
WEIGHT = 12

ROTATIONAL_CHAR = ['\\', '|', '/', '-']

#Gtk widgets
class PageGtk(PluginUI):
    """GTK frontend for the dell-recovery oem-config plugin"""
    plugin_title = 'ubiquity/text/recovery_heading_label'

    def __init__(self, controller, *args, **kwargs):
        self.controller = controller
        upart, rpart  = magic.find_partitions('','')
        dvd, usb = magic.find_burners()
        oem = 'UBIQUITY_OEM_USER_CONFIG' in os.environ
        self.genuine = magic.check_vendor()
        if oem and (dvd or usb) and (rpart or not self.genuine):
            try:
                import gtk
                builder = gtk.Builder()
                builder.add_from_file('/usr/share/ubiquity/gtk/stepRecoveryMedia.ui')
                builder.connect_signals(self)
                self.controller.add_builder(builder)
                self.plugin_widgets = builder.get_object('stepRecoveryMedia')
                self.usb_media = builder.get_object('save_to_usb')
                self.dvd_media = builder.get_object('save_to_dvd')
                self.none_media = builder.get_object('save_to_none')
                if not dvd:
                    builder.get_object('dvd_box').hide()
                if not usb:
                    builder.get_object('usb_box').hide()
                if not self.genuine:
                    builder.get_object('usb_box').hide()
                    builder.get_object('dvd_box').hide()
                    builder.get_object('none_box').hide()
                    builder.get_object('genuine_box').show()
            except Exception, err:
                syslog.syslog('Could not create Dell Recovery page: %s', err)
                self.plugin_widgets = None
        else:
            if not oem:
                pass
            elif not rpart:
                syslog.syslog('%s: partition problems with up[%s] and rp[%s]'
                % (NAME, upart, rpart))
            self.plugin_widgets = None

        PluginUI.__init__(self, controller, *args, **kwargs)

    def plugin_get_current_page(self):
        """Called when ubiquity tries to realize this page."""
        if not self.genuine:
            self.controller.allow_go_forward(False)
        return self.plugin_widgets

    def get_type(self):
        """Returns the type of recovery to do from GUI"""
        if self.usb_media.get_active():
            return "usb"
        elif self.dvd_media.get_active():
            return "dvd"
        else:
            return "none"

    def set_type(self, value):
        """Sets the type of recovery to do in GUI"""
        if value == "usb":
            self.usb_media.set_active(True)
        elif value == "dvd":
            self.dvd_media.set_active(True)
        else:
            self.none_media.set_active(True)

class Page(Plugin):
    """Debconf driven page for the dell-recovery oem-config plugin"""
    def prepare(self, unfiltered=False):
        """Prepares the debconf plugin"""
        destination = self.db.get('dell-recovery/destination')
        self.ui.set_type(destination)
        return Plugin.prepare(self, unfiltered=unfiltered)

    def ok_handler(self):
        """Handler ran when OK is pressed"""
        destination = self.ui.get_type()
        self.preseed('dell-recovery/destination', destination)
        Plugin.ok_handler(self)

class Install(InstallPlugin):
    """The dell-recovery media creator install time ubiquity plugin"""
    def __init__(self, frontend, db=None, ui=None):
        self.index = 0
        self.progress = None
        InstallPlugin.__init__(self, frontend, db, ui)

    def log(self, error):
        """Outputs a debugging string to /var/log/installer/debug"""
        self.debug("%s: %s" % (NAME, error))
        
    def _update_progress_gui(self, progress_text, progress_percent):
        """Function called by the backend to update the progress in frontend"""
        self.progress.substitute('dell-recovery/build_progress', 'MESSAGE', \
                                                                  progress_text)
        if float(progress_percent) < 0:
            if self.index >= len(ROTATIONAL_CHAR):
                self.index = 0
            progress_percent = ROTATIONAL_CHAR[self.index]
            self.index += 1
        else:
            progress_percent += "%"
        self.progress.substitute('dell-recovery/build_progress', 'PERCENT', \
                                                               progress_percent)
        self.progress.info('dell-recovery/build_progress')

    def install(self, target, progress, *args, **kwargs):
        """Perform actual install time activities for oem-config"""
        if not 'UBIQUITY_OEM_USER_CONFIG' in os.environ:
            return

        #can also expect that this was mounted at /cdrom during OOBE
        rpart = magic.find_factory_rp_stats()
        if rpart and os.path.exists('/cdrom/.disk/info'):
            lang = progress.get('debian-installer/locale')
            magic.process_conf_file('/usr/share/dell/grub/99_dell_recovery', \
                                    '/etc/grub.d/99_dell_recovery',          \
                                    str(rpart["uuid"]), str(rpart["number"]),\
                                    'locale=' + lang)
            os.chmod('/etc/grub.d/99_dell_recovery', 0755)
            subprocess.call(['update-grub'])

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.progress = progress
        rec_type = progress.get('dell-recovery/destination')
        if rec_type != "none":
            dvd, usb = magic.find_burners()
            upart, rpart  = magic.find_partitions('', '')
            self.index = 0
            fname = os.path.join('/tmp/dell.iso')
            try:
                bus = dbus.SystemBus()
                dbus_iface = dbus.Interface(bus.get_object(magic.DBUS_BUS_NAME,
                                            '/RecoveryMedia'),
                                            magic.DBUS_INTERFACE_NAME)
            except Exception, err:
                self.log('install function exception while creating dbus backend: %s' % str(err))
                return

            progress.info('dell-recovery/build_start')

            #Determine internal version number of image
            (version, date) = dbus_iface.query_bto_version(rpart)
            version = magic.increment_bto_version(version)
            self.log("Generating recovery media from %s : %s" % (version, date))

            #Build image
            try:
                magic.dbus_sync_call_signal_wrapper(dbus_iface,
                                                    'create_ubuntu',
                                                    {'report_progress':self._update_progress_gui},
                                                    upart,
                                                    rpart,
                                                    version,
                                                    fname)
            except dbus.DBusException, err:
                self.log('install function exception while calling backend: %s' % str(err))
                return

            #Close backend
            try:
                dbus_iface.request_exit()
            except dbus.DBusException, err:
                if hasattr(err, '_dbus_error_name') and err._dbus_error_name == \
                        'org.freedesktop.DBus.Error.ServiceUnknown':
                    pass
                else:
                    self.log("Received %s when closing recovery-media-backend" \
                                                                     % str(err))
                    return

            #Launch burning tool
            if rec_type == "dvd":
                cmd = dvd + [fname]
            elif rec_type == "usb":
                cmd = usb + [fname]
            else:
                cmd = None
            if cmd:
                if 'DBUS_SESSION_BUS_ADDRESS' in os.environ:
                    os.environ.pop('DBUS_SESSION_BUS_ADDRESS')
                progress.info('dell-recovery/burning')
                subprocess.call(cmd)

            #Clean up when done
            if os.path.exists(fname):
                os.remove(fname)

        return InstallPlugin.install(self, target, progress, *args, **kwargs)

