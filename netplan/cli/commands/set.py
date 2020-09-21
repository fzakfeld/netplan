#!/usr/bin/python3
#
# Copyright (C) 2020 Canonical, Ltd.
# Author: Lukas Märdian <lukas.maerdian@canonical.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

'''netplan set command line'''

import os
import yaml
import tempfile
import shutil
import re

import netplan.cli.utils as utils


class NetplanSet(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='set',
                         description='Add new setting by specifying a dotted key=value pair like ethernets.eth0.dhcp4=true',
                         leaf=True)

    def run(self):
        self.parser.add_argument('key_value', type=str, help='The nested key=value pair in dotted format')
        self.parser.add_argument('--origin-hint',
                                 type=str, default='90-netplan-set',
                                 help='Can be used to help choose a name for the overwrite YAML file')
        self.parser.add_argument('--root-dir',
                                 help='Overwrite configuration files in this root directory instead of /')

        self.func = self.command_set

        self.parse_args()
        self.run_command()

    def command_set(self):
        root = self.root_dir if self.root_dir else '/'
        split = self.key_value.split('=', 1)
        key, value = (split[0], None)
        if len(split) > 1:
            value = split[1]
        self.write_file(key, value, self.origin_hint + '.yaml', root)

    def parse_key(self, key, value):
        # Split at '.' but not at '\.' via negative lookbehind expression
        split = re.split(r'(?<!\\)\.', 'network.' + key)
        tree = {}
        i = 1
        t = tree
        for part in split:
            part = part.replace('\\.', '.')  # Unescape interface-ids, containing dots
            val = {}
            if i == len(split):
                val = value
            t = t.setdefault(part, val)
            i += 1
        return tree

    def merge(self, a, b, path=None):
        "merges b into a"
        if path is None:
            path = []
        for key in b:
            if key in a:
                if isinstance(a[key], dict) and isinstance(b[key], dict):
                    self.merge(a[key], b[key], path + [str(key)])
                elif b[key] is None:
                    del a[key]
                else:
                    # Overwrite existing key with new key/value from 'set' command
                    a[key] = b[key]
            else:
                a[key] = b[key]
        return a

    def strip(self, data):
        "clear empty branches"
        new_data = {}
        for k, v in data.items():
            if isinstance(v, dict):
                v = self.strip(v)
            if v not in (u'', None, {}):
                new_data[k] = v
        return new_data

    def write_file(self, key, value, name, rootdir='/', path='etc/netplan/'):
        tmproot = tempfile.TemporaryDirectory(prefix='netplan-set_')
        os.makedirs(os.path.join(tmproot.name, 'etc', 'netplan'))

        config = {'network': {}}
        absp = os.path.join(rootdir, path, name)
        if os.path.isfile(absp):
            with open(absp, 'r') as f:
                config = yaml.safe_load(f)

        new_tree = self.merge(config, self.parse_key(key, yaml.safe_load(value)))
        stripped = self.strip(new_tree)
        if 'network' in stripped:
            tmpp = os.path.join(tmproot.name, path, name)
            with open(tmpp, 'w+') as f:
                new_yaml = yaml.dump(stripped, indent=2, default_flow_style=False)
                f.write(new_yaml)
            try:
                # Validate the newly created file, by parsing it via libnetplan
                utils.netplan_parse(tmpp)
                # Valid, move it to final destination
                os.replace(tmpp, absp)
            finally:
                shutil.rmtree(os.path.join(tmproot.name, 'etc', 'netplan'))
        else:
            # Clear file if the last/only key got removed
            os.remove(absp)
        shutil.rmtree(tmproot.name)
