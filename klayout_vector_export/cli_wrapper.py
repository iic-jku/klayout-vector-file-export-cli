#! /usr/bin/env python3

#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2026 Martin Jan Köhler
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/klayout-pex).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
# --------------------------------------------------------------------------------
#

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import *
import xml.etree.ElementTree as ET

import klayout_vector_export.version as cli_wrapper_version


DEBUG = False

def debug(*args, **kwargs):
    global DEBUG
    if DEBUG:
        print(*args, **kwargs)


class CLIWrapper:
    @staticmethod
    def find_klayout_executable() -> Optional[Path]:
        """Locate the klayout executable on PATH or common install locations."""
        exe = shutil.which("klayout") or shutil.which("klayout_app")
        if exe:
            return Path(exe).resolve()

        # Common platform-specific locations
        candidates = []
        if sys.platform == "win32":
            candidates = [
                Path(r"C:\Program Files\KLayout\klayout_app.exe"),
                Path(r"C:\Program Files (x86)\KLayout\klayout_app.exe"),
            ]
        elif sys.platform == "darwin":
            candidates = [
                Path("/Applications/klayout.app/Contents/MacOS/klayout"),
                Path("/usr/local/bin/klayout"),
            ]
        else:  # Linux
            candidates = [
                Path("/usr/bin/klayout"),
                Path("/usr/local/bin/klayout"),
                Path("/opt/klayout/bin/klayout"),
            ]

        for c in candidates:
            if c.exists():
                return c

        return None

    @staticmethod
    def get_klayout_version(exe: Path) -> str:
        """Run 'klayout -v' and return the version string."""
        try:
            result = subprocess.run(
                [str(exe), "-v"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = (result.stdout + result.stderr).strip()
            return output or "(no version output)"
        except Exception as e:
            return f"(could not determine version: {e})"

    @staticmethod
    def get_klayout_home() -> Path:
        """
        Return the KLayout home directory, respecting the $KLAYOUT_HOME environment
        variable if set (it overrides the platform default of ~/.klayout).
        """
        env_home = os.environ.get("KLAYOUT_HOME")
        if env_home:
            return Path(env_home).expanduser().resolve()

        # Platform defaults
        if sys.platform == "win32":
            return Path.home() / "KLayout"
        else:
            return Path.home() / ".klayout"

    @staticmethod
    def locate_plugin(search_roots: List[Path], plugin_name: str) -> Path | None:
        """
        Search for the plugin directory under the KLayout installation root.
        KLayout plugins live under  <root>/salt/<plugin>/  or  <root>/plugins/<plugin>/
        or in the user's salt directory ($KLAYOUT_HOME, defaulting to ~/.klayout).
        """
        # Directories to search (order: installation root first, then user dir)
        search_roots = list(search_roots)

        user_klayout = CLIWrapper.get_klayout_home()
        if user_klayout.exists():
            search_roots.append(user_klayout)

        for base in search_roots:
            # Use rglob for a thorough search
            for match in base.rglob(plugin_name):
                if match.is_dir():
                    return match

        return None

    @staticmethod
    def add_plugin_to_sys_path(plugin_dir: Path) -> None:
        """Add plugin_dir to sys.path if not already present."""
        plugin_str = str(plugin_dir / 'pymacros')
        if plugin_str not in sys.path:
            sys.path.insert(0, plugin_str)
            debug(f"  ✔  Added to sys.path: {plugin_str}")
        else:
            debug(f"  ℹ  Already in sys.path: {plugin_str}")

    def locate_and_add_plugin_to_sys_path(self,
                                          plugin_name: str,
                                          devel_roots: List[Path],
                                          git_repo_name: str) -> Path:
        debug("\nDetermining KLayout home …")
        home = self.get_klayout_home()
        debug(f"  ✔  KLayout Home: {home}")

        debug(f"\nSearching for plugin '{plugin_name}' …")
        search_roots = [home]
        plugin_dir = self.locate_plugin(search_roots, plugin_name)
        if plugin_dir is None:
            plugin_dir = self.locate_plugin(devel_roots, git_repo_name)  # Git Repo name

            if plugin_dir is None:
                sys.exit(
                    f"\n✖  Plugin '{plugin_name}' not found under {home}.\n"
                    f"   Install the plugin via KLayout's Package Manager (Tools → Manage Packages)"
                )
        debug(f"  ✔  Plugin directory: {plugin_dir}")

        # 4. Add to sys.path
        debug("\nAdding plugin directory to sys.path …")
        self.add_plugin_to_sys_path(plugin_dir)
        return plugin_dir
    
    def get_plugin_version(self, plugin_dir: Path) -> str:
        xml_path = plugin_dir / 'grain.xml'
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()

            # Try common version locations in grain.xml
            # 1. Direct <version> child of root
            version = root.findtext("version")

            # 2. Namespaced or nested — try <salt-grain><version>
            if version is None:
                version = root.findtext("./salt-grain/version")

            # 3. As an attribute on the root element
            if version is None:
                version = root.get("version")
            return version
        except Exception as e:
            raise Exception(f"Unable to read plugin grain.xml from {xml_path} due to exception: {e}")

    def main(self):
        global DEBUG
        DEBUG = '--debug' in sys.argv

        debug("=" * 60)
        debug("KLayout validation & plugin path setup")
        debug("=" * 60)

        # 1. Validate KLayout is installed
        debug("\nLocating KLayout executable …")
        exe = self.find_klayout_executable()
        if exe is None:
            sys.exit(
                "\n✖  KLayout executable not found.\n"
                "   Please install KLayout (https://www.klayout.de) and ensure\n"
                "   it is available on your PATH."
            )
        debug(f"  ✔  Found: {exe}")

        version = self.get_klayout_version(exe)
        debug(f"  ✔  Version: {version}")

        devel_roots = [  # developer dev directory
            Path.home() / 'Source',
            Path.home() / 'src'
        ]

        # 3. Locate the plugin

        plugin_path1 = self.locate_and_add_plugin_to_sys_path(
            plugin_name='KLayoutPluginUtils',
            devel_roots=devel_roots,
            git_repo_name='klayout-plugin-utils'
        )
        
        plugin_path2 = self.locate_and_add_plugin_to_sys_path(
            plugin_name='VectorFileExportPlugin',
            devel_roots=devel_roots,
            git_repo_name='klayout-vector-file-export'
        )

        debug("=" * 60)
        debug("Parse arguments (parser is part of VectorFileExport python plugin)")
        debug("=" * 60)

        # Handle version here, as both CLI wrapper version and Plugin version has to be reported
        if '-v' in sys.argv or '--version' in sys.argv:
            version_data = [
                ('CLI-Wrapper', cli_wrapper_version.__version__),
                ('KLayoutPluginUtils', self.get_plugin_version(plugin_path1)),
                ('VectorFileExportPlugin', self.get_plugin_version(plugin_path2)),
            ]
            plugin_versions = [f"{n} {v}" for n, v in version_data]
            print(' / '.join(plugin_versions))
            sys.exit(0)

        from cli_args import build_parser, args_to_settings, validate_settings
        parser = build_parser()
        args = parser.parse_args(sys.argv[1:])

        settings = args_to_settings(args)
        validate_settings(settings)

        debug("=" * 60)
        debug("Call KLayout")
        debug("=" * 60)

        errors = []

        if args.input_path is None:
            errors += [f"ERROR: Input layout file missing, please provide command line argument --in / -i"]

        if args.output_path is None:
            errors += [f"ERROR: Output vector file missing, please provide command line argument --out / -o"]

        if args.technology is None:
            errors += [f"ERROR: Technology is missing, please provide command line argument --tech / -t"]

        if errors:
            print('\n'.join(errors))
            sys.exit(1)

        input_path = Path(args.input_path).resolve()

        keep_json = hasattr(args, 'keep_json') and args.keep_json

        # Write settings to a temporary JSON file; deleted automatically when done
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.json',
            prefix='vfe_settings_',
            delete=False,
            encoding='utf-8',
        ) as tmp:
            settings_path = tmp.name
            settings.save_json(Path(settings_path))

        debug(f"  ✔  Settings written to temp file: {settings_path}")

        # Build subprocess environment:
        # Set KLAYOUT_PATH="" to prevent KLayout from reading any config files
        # from additional search paths.
        klayout_env = os.environ.copy()
        klayout_env["KLAYOUT_PATH"] = ""

        try:
            # NOTE: we do not pass -nc, as it would hinder us to find the technology
            result = subprocess.run(
                [
                        str(exe),
                        '-z',   # Non-GUI mode (hidden views)
                        # '-nc',  # Don't use a configuration file (implies -t)
                        '-rx',  # Ignore all implicit macros (*.rbm, rbainit, *.lym)
                        '-r', str(plugin_path2.resolve() / 'pymacros' / 'cli_tool.py'),  # Execute main script on startup
                        '-rd', f"input_path={input_path}",
                        '-rd', f"settings_path={settings_path}",
                        '-rd', f"technology={args.technology}",
                ],
                capture_output=True,
                text=True,
                env=klayout_env,
            )
            output = (result.stdout + result.stderr).strip()
            print(output or "(no output)")
        finally:
            try:
                if not keep_json: 
                    os.unlink(settings_path)
                    debug(f"  ✔  Temp settings file removed: {settings_path}")
            except OSError:
                pass

# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli = CLIWrapper()
    cli.main()

