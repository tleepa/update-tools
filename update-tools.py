#! /usr/bin/env python3

from datetime import datetime
from jinja2 import Template

import argparse
import glob
import json
import os
import re
import requests
import shlex
import subprocess
import sys
import urllib.parse
import yaml


class Color:
    RED = "\033[31m"
    GRN = "\033[32m"
    YLW = "\033[33m"
    RST = "\033[0m"


class Tool:
    def check(self, verbose, skip=False) -> None:
        print_details = False
        if version_mismatch(self.v_remote, self.v_local):
            print(f"{Color.YLW}    {self.name}{Color.RST}")
            print_details = True
        else:
            if not skip:
                print(f"    {self.name}")
                print_details = True
        if verbose >= 2:
            print_info(self, verbose)

        if print_details and verbose >= 1:
            print(f"           remote name: {self.pkg_name}")
            print(f"            remote url: {self.pkg_url}")
            print(f"        remote version: {self.v_remote}")
            print(f"         local version: {self.v_local}")
            print(f"        local packages: {self.pkg_local}")

    def download(self, verbose, force=False, skip=False) -> None:
        dl = False
        if force:
            dl = True
            if verbose >= 2:
                print("        Download forced")
        elif not os.path.exists(os.path.join(self.pkg_dir, self.pkg_name)):
            dl = True
            if verbose >= 2:
                print("        Local file does not exist")
        else:
            r = requests.get(self.pkg_url, stream=True)
            remote_size = int(r.headers.get("Content-Length"))
            local_size = os.path.getsize(os.path.join(self.pkg_dir, self.pkg_name))
            if remote_size != local_size:
                dl = True
                if verbose >= 2:
                    print("        Local file exists but has different size")
                    print(f"        Local file size: {local_size}")
                    print(f"       Remote file size: {remote_size}")
            else:
                remote_dt = datetime.strptime(
                    r.headers.get("Last-Modified", r.headers.get("Date")),
                    "%a, %d %b %Y %H:%M:%S %Z",
                )
                local_dt = datetime.fromtimestamp(
                    int(os.path.getmtime(os.path.join(self.pkg_dir, self.pkg_name)))
                )
                if remote_dt > local_dt:
                    dl = True
                    if verbose >= 2:
                        print("        Local file exists but is older")
                        print(f"        Local file date: {local_dt}")
                        print(f"       Remote file date: {remote_dt}")

        if dl:
            print(f"{Color.YLW}    {self.name}{Color.RST}")
            if verbose >= 2:
                print(f"        Downloading package {self.pkg_name}")
            if download_file(self.pkg_url, self.pkg_dir, self.pkg_name):
                if verbose >= 1:
                    print(f"        Downloaded {self.pkg_name}")
                self.dl_ok = True
        elif not skip:
            print(f"    {self.name}")
            if verbose >= 2:
                print(f"        Not downloading package: {self.pkg_name}")
                print(f"        Exisiting local packages: {self.pkg_local}")
                print(f"        Local file size: {local_size}")
                print(f"        Remote file size: {remote_size}")
                print(f"        Local file date: {local_dt}")
                print(f"        Remote file date: {remote_dt}")

    def update(self, verbose, force=False, skip=False) -> None:
        update = False
        if force:
            update = True
            if verbose >= 2:
                print("        Update forced")
        elif not self.is_rpm and version_mismatch(self.v_remote, self.v_local):
            print(f"{Color.YLW}    {self.name}{Color.RST}")
            update = True
        else:
            if not skip:
                print(f"    {self.name}")
        if update and verbose >= 2:
            print(f"        Updating: {self.pkg_name}")
        elif verbose >= 2:
            print(f"        Not updating: {self.pkg_name}")
            print(f"        RPM package: {self.is_rpm}")

        if update:
            for count, step in enumerate(self.inst, start=1):
                tm = Template(os.path.expandvars(step))
                cmd = tm.render(tool=self)
                if verbose >= 2:
                    print(f"           Step {count}/{len(self.inst)}: {cmd}")
                if not subprocess.run(
                    shlex.split(cmd), capture_output=True, encoding="UTF-8"
                ).returncode:
                    if verbose >= 1:
                        print(f"           Step {count}/{len(self.inst)}: completed.")
                else:
                    raise RuntimeError(
                        f"           Step {count}/{len(self.inst)}: failed."
                    )

    def _get_data_local(self) -> None:
        files = list(os.scandir(os.path.realpath(os.path.expandvars(self.pkg_dir))))
        self.pkg_local = [
            file.name for file in files if self.name.lower() in file.name.lower()
        ]

        if self.pkg_local and self.is_rpm:
            rpm_name = subprocess.run(
                shlex.split(
                    f"rpm --qf '%{{NAME}}' -qp {os.path.join(self.pkg_dir, self.pkg_local[0])}"
                ),
                capture_output=True,
                encoding="UTF-8",
            ).stdout.strip("\n")
            ver = subprocess.run(
                shlex.split(f"rpm --qf '%{{VERSION}}' -q {rpm_name}"),
                capture_output=True,
                encoding="UTF-8",
            ).stdout.strip("\n")
            if not "not installed" in ver:
                self.v_local = ver
        elif self.ver.get("type") == "cmd":
            ver_cmd = self.ver.get("name")
            tm = Template(ver_cmd)
            cmd = tm.render(tool=self)
            if not subprocess.run(
                ["command", "-v", shlex.split(cmd)[0]],
                capture_output=True,
                encoding="UTF-8",
            ).returncode:
                ver = subprocess.run(
                    shlex.split(cmd), capture_output=True, encoding="UTF-8"
                ).stdout.strip("\n")
                if rx := self.ver.get("regex"):
                    if m := re.search(rx, ver):
                        if m.groups():
                            self.v_local = m.groups()[0]
                        elif m.group():
                            self.v_local = m.group()
                else:
                    self.v_local = ver.strip("v")
        elif self.ver.get("type") == "file":
            ver_file = self.ver.get("name")
            tm = Template(ver_file)
            file_name = tm.render(tool=self)
            if fp := glob.glob(os.path.expandvars(file_name)):
                file_path = max(fp, key=lambda f: os.stat(f).st_ctime)
            else:
                self._errors.append(f"File '{file_name}' not found")
                return

            if rx := self.ver.get("regex"):
                if m := re.search(rx, file_path):
                    if m.groups():
                        self.v_local = m.groups()[0]
                    elif m.group():
                        self.v_local = m.group()
                else:
                    with open(file_path, "r") as f:
                        file_lines = f.readlines()
                    for line in file_lines:
                        m = re.search(rx, line.strip("\n"))
                        if m and m.groups():
                            self.v_local = m.groups()[0]
                        elif m and m.group():
                            self.v_local = m.group()


class ToolGit(Tool):
    def __init__(self, tool_def: dict, defaults: dict) -> None:
        self.tool_def = tool_def
        self.defaults = defaults
        self.name = tool_def["name"]
        self.repo = tool_def["repo"]
        self.look_up = tool_def.get("look_up", defaults["git"]["look_up"])
        self.tag = tool_def.get("tag", defaults["git"]["tag"])
        custom = tool_def.get("custom", defaults["git"]["custom"])
        if custom == 1 or custom == "yes" or custom is True:
            self.custom = True
        else:
            self.custom = False
        self.url = tool_def.get("url")
        self.package = tool_def.get("package")
        self.not_tags = tool_def.get("not_tags", [])
        self.incl = tool_def.get("incl", [])
        self.excl = tool_def.get("excl", [])
        self.inst = tool_def.get("inst", [])
        self.ver = defaults["ver"].copy()
        if tool_def.get("ver"):
            for (key, value) in tool_def.get("ver").items():
                self.ver[key] = value
        self.is_rpm = False
        self.dl_ok = False
        self.v_local = None

        self.bin_dir = os.path.expandvars(tool_def.get("bin_dir", defaults["bin_dir"]))
        self.opt_dir = os.path.expandvars(tool_def.get("opt_dir", defaults["opt_dir"]))
        self.tmp_dir = os.path.expandvars(tool_def.get("tmp_dir", defaults["tmp_dir"]))
        self.pkg_dir = os.path.expandvars(tool_def.get("plg_dir", defaults["pkg_dir"]))
        self.__env_token_name = defaults["git"]["token_env"]

        self._errors = []
        self._get_data_remote()
        self._get_data_local()

    def _get_data_remote(self) -> None:
        if self.__env_token_name:
            gh_token = os.environ.get(self.__env_token_name)
        if gh_token:
            headers = {"Authorization": f"token {gh_token}"}
        else:
            headers = {}

        if self.tag == "latest":
            url = f"https://api.github.com/repos/{self.repo}/{self.look_up}/{self.tag}"
        else:
            url = f"https://api.github.com/repos/{self.repo}/{self.look_up}"

        req = requests.get(url, headers=headers)
        resp = json.loads(req.content.decode())

        if self.look_up == "releases":
            if self.tag != "latest":
                for not_tag in self.not_tags:
                    resp = list(filter(lambda i: not_tag not in i["tag_name"], resp))
                resp = list(filter(lambda i: self.tag in i["tag_name"], resp))
                self.v_remote = resp[0]["tag_name"].strip("v")
                if not self.custom:
                    assets = resp[0]["assets"]
            else:
                self.v_remote = resp["tag_name"].strip("v")
                if not self.custom:
                    assets = resp["assets"]
        elif self.look_up == "tags":
            if not "^" in self.tag and not "$" in self.tag:
                git_tag = list(filter(lambda i: self.tag in i["name"], resp))
            if self.tag.startswith("^"):
                git_tag = list(
                    filter(lambda i: i["name"].startswith(self.tag.strip("^")), resp)
                )
            if self.tag.endswith("$"):
                git_tag = list(
                    filter(lambda i: i["name"].endwith(self.tag.strip("$")), resp)
                )
            self.v_remote = f"{git_tag[0]['name']}"

        else:
            raise ValueError(f"Not recognized look up: {self.look_up}")

        if not self.custom:
            for incl in self.incl:
                assets = list(filter(lambda i: incl in i["name"], assets))
            for excl in self.excl:
                assets = list(filter(lambda i: excl not in i["name"], assets))

            if self.url:
                tm = Template(self.url)
                self.pkg_url = tm.render(tool=self)
                if not self.package:
                    self.pkg_name = self.pkg_url.split("/")[-1]
                else:
                    tm = Template(self.package)
                    self.pkg_name = tm.render(tool=self)
            else:
                if len(assets) > 1:
                    raise ValueError(
                        f"Found more than one asset!\n{[item['name'] for item in assets]}"
                    )
                else:
                    self.pkg_url = assets[0]["browser_download_url"]
                    self.pkg_name = assets[0]["name"]
        else:
            self.url = (
                f"https://api.github.com/repos/{self.repo}/{self.look_up}/{self.tag}"
            )
            custom_tool = ToolCustom.from_tool(self)
            self.pkg_url = custom_tool.pkg_url
            self.pkg_name = custom_tool.pkg_name

        if "rpm" in self.pkg_name:
            self.is_rpm = True


class ToolDirect(Tool):
    def __init__(self, tool_def: dict, defaults: dict) -> None:
        self.tool_def = tool_def
        self.name = tool_def["name"]
        self.url = self.pkg_url = tool_def["url"]
        self.package = tool_def.get("package")
        self.inst = tool_def.get("inst", [])
        self.ver = defaults["ver"].copy()
        if tool_def.get("ver"):
            for (key, value) in tool_def.get("ver").items():
                self.ver[key] = value
        self.is_rpm = False
        self.v_local = None
        self.v_remote = None
        self.dl_ok = False

        self.bin_dir = os.path.expandvars(tool_def.get("bin_dir", defaults["bin_dir"]))
        self.opt_dir = os.path.expandvars(tool_def.get("opt_dir", defaults["opt_dir"]))
        self.tmp_dir = os.path.expandvars(tool_def.get("tmp_dir", defaults["tmp_dir"]))
        self.pkg_dir = os.path.expandvars(tool_def.get("plg_dir", defaults["pkg_dir"]))

        self._errors = []
        self._get_data_remote()
        self._get_data_local()

    def _get_data_remote(self) -> None:
        if self.url:
            tm = Template(self.url)
            self.pkg_url = tm.render(tool=self)

        if not self.package:
            self.pkg_name = self.pkg_url.split("/")[-1]
        else:
            tm = Template(self.package)
            self.pkg_name = tm.render(tool=self)

        if "rpm" in self.pkg_name:
            self.is_rpm = True
            self.v_remote = subprocess.run(
                shlex.split(f"rpm --qf '%{{VERSION}}' -qp {self.pkg_url}"),
                capture_output=True,
                encoding="UTF-8",
            ).stdout.strip("\n")


class ToolCustom(Tool):
    def __init__(self, tool_def: dict, defaults: dict) -> None:
        self.tool_def = tool_def
        self.name = tool_def["name"]
        self.url = self.pkg_url = tool_def["url"]
        self.package = tool_def.get("package")
        self.inst = tool_def.get("inst", [])
        self.ver = defaults["ver"].copy()
        if tool_def.get("ver"):
            for (key, value) in tool_def.get("ver").items():
                self.ver[key] = value
        self.is_rpm = False
        self.v_local = tool_def.get("v_local")
        self.v_remote = tool_def.get("v_remote")
        self.dl_ok = False

        self.bin_dir = os.path.expandvars(
            tool_def.get("bin_dir", defaults.get("bin_dir"))
        )
        self.opt_dir = os.path.expandvars(
            tool_def.get("opt_dir", defaults.get("opt_dir"))
        )
        self.tmp_dir = os.path.expandvars(
            tool_def.get("tmp_dir", defaults.get("tmp_dir"))
        )
        self.pkg_dir = os.path.expandvars(
            tool_def.get("pkg_dir", defaults.get("pkg_dir"))
        )

        getattr(self, f"_get_data_{self.name}")()
        if "rpm" in self.pkg_name:
            self.is_rpm = True

        self._errors = []
        self._get_data_local()

    @classmethod
    def from_tool(cls, tool: Tool) -> None:
        custom_dict = {
            "name": tool.name,
            "url": tool.url,
            "package": tool.package,
            "inst": tool.inst,
            "ver": tool.ver,
            "is_rpm": tool.is_rpm,
            "v_local": tool.v_local,
            "v_remote": tool.v_remote,
            "bin_dir": tool.bin_dir,
            "opt_dir": tool.opt_dir,
            "tmp_dir": tool.tmp_dir,
            "pkg_dir": tool.pkg_dir,
        }
        return cls(custom_dict, tool.defaults)

    def _get_data_azuredatastudio(self) -> None:
        r = requests.get(self.url)
        if m := re.search(
            R"\[linux-rpm\]: (.*)\r", json.loads(r.content.decode())["body"]
        ):
            self.pkg_url = m.groups()[0]
        else:
            self.pkg_url = None

        if not self.package:
            self.pkg_name = self.pkg_url.split("/")[-1]
        else:
            tm = Template(self.package)
            self.pkg_name = tm.render(tool=self)

    def _get_data_usbimager(self) -> None:
        r = requests.get(self.url)
        if m := re.search(
            R"Linux PC.*?\[GTK\+\]\((.*?" + self.package + ")\)", r.content.decode()
        ):
            self.pkg_url = m.groups()[0]
            self.pkg_name = self.pkg_url.split("/")[-1]
            self.v_remote = re.search(
                R"usbimager_(.*?)" + self.package, self.pkg_name
            ).groups()[0]
        else:
            self.pkg_url = None
            self.pkg_name = None

    def _get_data_postman(self) -> None:
        self.pkg_url = self.url

        r = requests.get(self.pkg_url, stream=True)
        if m := re.search(R".*filename=(.*)", r.headers["Content-Disposition"]):
            self.pkg_name = m.groups()[0]
        else:
            self.pkg_name = None

        r = requests.get("https://www.postman.com/mkapi/release.json")
        if r.ok:
            self.v_remote = json.loads(r.content)["notes"][0]["version"]
        else:
            self.v_remote = None

    def _get_data_icaclient(self) -> None:
        r = requests.get(self.url)
        if m := re.search(
            R'rel="(.*ICAClient-rhel.*x86_64.rpm.*?)"', r.content.decode()
        ):
            self.pkg_url = f"http:{m.groups()[0]}"
        else:
            self.pkg_url = None

        if m := re.search(R"ICAClient.*rpm", self.pkg_url):
            self.pkg_name = m.group()
        else:
            self.pkg_name = None

        if m := re.search(R"rhel-(.*)-", self.pkg_name):
            self.v_remote = m.groups()[0]
        else:
            self.v_remote = None


def version_mismatch(v_remote: str, v_local: str) -> bool:
    if v_local is None or v_remote is None:
        return False
    else:
        if v_local in v_remote or v_remote in v_local:
            return False
        else:
            return True


def download_file(url: str, dest_folder: str, file_name=None) -> bool:
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)

    if not file_name:
        file_name = urllib.parse.unquote(url).split("/")[-1]
    file_path = os.path.join(dest_folder, file_name)

    r = requests.get(url, stream=True)
    if r.ok:
        with open(file_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
        return True
    else:
        print(f"Download failed: status code {r.status_code}\n{r.text}")
        return False


def print_info(tool: Tool, verbose) -> None:
    indent = " " * 4
    print(indent * 2, "Tool definition:")
    for line in yaml.dump(
        tool.tool_def,
        default_flow_style=False,
        sort_keys=False,
        indent=4,
        width=1000,
    ).split("\n"):
        print(indent * 3, line)
    print("")

    print(indent * 2, "Tool definition (rendered):")
    tm = Template(
        yaml.dump(
            tool.tool_def,
            default_flow_style=False,
            sort_keys=False,
            indent=4,
            width=1000,
        )
    )
    for line in tm.render(tool=tool).split("\n"):
        print(indent * 3, line)
    print("")

    if verbose >= 3:
        print(indent * 2, "Tool object attributes (rendered):")
        tm = Template(
            yaml.safe_dump(
                json.loads(json.dumps(vars(tool))),
                default_flow_style=False,
                sort_keys=False,
                indent=4,
                width=1000,
            )
        )
        for line in tm.render(tool=tool).split("\n"):
            print(indent * 3, line)
        print("")

    print("")


def update_repo(repo_path):
    cmd = subprocess.run(
        shlex.split(f"createrepo '{os.path.expandvars(repo_path)}'"),
        capture_output=True,
        encoding="UTF-8",
    )
    if cmd.returncode:
        raise RuntimeError(f"Failed to update repo in {repo_path}")


def main():
    try:
        script_file_name, _ = os.path.splitext(__file__)

        parser = argparse.ArgumentParser()
        group = parser.add_mutually_exclusive_group()
        parser.add_argument(
            "-g",
            "--config-file",
            help=f"path to configuration file, defaults to <script dir>/<script name>.yaml",
            type=argparse.FileType("r"),
            default=f"{script_file_name}.yaml",
        )
        parser.add_argument(
            "name", help="tool name", type=str, default="all", nargs="*"
        )
        group.add_argument(
            "-l", "--list", action="store_true", help="list supported tools"
        )
        group.add_argument(
            "-c", "--check", action="store_true", help="check for new version only"
        )
        group.add_argument(
            "-d",
            "--download",
            action="store_true",
            help="download new version only (refreshes local repository)",
        )
        group.add_argument(
            "-u",
            "--update",
            action="store_true",
            help="update tools (will not install if not installed already)",
        )
        parser.add_argument(
            "-f", "--force", action="store_true", help="force download or install"
        )
        parser.add_argument(
            "-s", "--skip-current", action="store_true", help="do not show current"
        )
        parser.add_argument("-v", "--verbose", action="count", default=0)
        args = parser.parse_args()
        conf = args.config_file
        names = args.name

        if args.verbose >= 2:
            print(f"Running script: '{__file__}'")
            print(f"Configuration file: '{conf.name}'")
            print("")

        with conf as stream:
            data_loaded = yaml.safe_load(stream)

        defaults_dict = {
            "bin_dir": "$HOME/bin",
            "opt_dir": "/opt",
            "tmp_dir": "/tmp",
            "pkg_dir": "$HOME/Repos/packages",
            "ver": {
                "type": "cmd",
                "name": "{{ tool.name }} --version",
                "regex": None,
            },
            "git": {
                "look_up": "releases",
                "tag": "latest",
                "custom": "no",
                "token_env": "GITHUB_TOKEN",
            },
        }
        defaults = data_loaded.get("defaults", {})

        for key in defaults_dict.keys():
            if not type(defaults_dict[key]) is dict:
                try:
                    defaults[key] = defaults[key]
                except KeyError:
                    defaults[key] = defaults_dict[key]
            else:
                for subkey in defaults_dict[key].keys():
                    try:
                        defaults[key][subkey] = defaults[key][subkey]
                    except KeyError:
                        defaults[key][subkey] = defaults_dict[key][subkey]

        if args.verbose >= 2:
            print("Defaults:")
            for line in yaml.dump(
                defaults,
                default_flow_style=False,
                sort_keys=False,
                indent=4,
                width=1000,
            ).split("\n"):
                print("    ", line)
            print("")

        tools = data_loaded.get("tools", [])

        if args.list:
            print("Supported tools:")
            for tool in sorted(tools, key=lambda item: item["name"]):
                print(f"    {tool['name']}")
            sys.exit()

        if names and "all" not in names:
            tools = [tool for tool in tools.copy() if tool["name"] in names]
        if not tools:
            print("Tool(s) not found!")
        else:
            print("Processing tools...")

        if args.verbose >= 2:
            print("Tools to process:")
            for tool in sorted(tools, key=lambda item: item["name"]):
                print(f"    {tool['name']}")
            print("")

        rpms_dl = False
        errors_list = []
        for tool_def in sorted(tools, key=lambda item: item["name"]):
            tool = None
            try:
                if tool_def.get("type") == "git":
                    tool = ToolGit(tool_def, defaults)
                elif tool_def.get("type") == "direct":
                    tool = ToolDirect(tool_def, defaults)
                else:
                    tool = ToolCustom(tool_def, defaults)

                for error in tool._errors:
                    errors_list.append((tool_def["name"], error))

                if args.update:
                    tool.update(
                        verbose=args.verbose, force=args.force, skip=args.skip_current
                    )
                elif args.download:
                    tool.download(
                        verbose=args.verbose, force=args.force, skip=args.skip_current
                    )
                    if tool.is_rpm and tool.dl_ok:
                        rpms_dl = True
                else:
                    tool.check(verbose=args.verbose, skip=args.skip_current)
            except Exception as e:
                errors_list.append((tool_def["name"], e))

        if rpms_dl:
            if args.verbose >= 2:
                print("")
                print(f"Updating repo: {os.path.expandvars(defaults['pkg_dir'])}")
                print("")
            try:
                update_repo(os.path.expandvars(defaults["pkg_dir"]))
            except Exception as e:
                errors_list.append(("repo_update", e))

        if errors_list:
            print("")
            print("Errors:")
            for tool, error in errors_list:
                print(f"    Tool '{tool}' - {error}")

    except SystemExit:
        pass
    except KeyError as e:
        print(f"Missing section {e} in configuration file: {conf}")
    except Exception as e:
        print(f"Error: {e}\n")


if __name__ == "__main__":
    main()
