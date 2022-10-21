# update-tools

Python script to help download and install tools not available in the standard
repositories.

Developed and daily used on Fedora Linux, but should be working on OSes like
Rocky Linux, Alma Linux, CentOS Stream and similar.

## Overview

This project consists of the script itself and `.yaml` configuration file, which
holds definition of the tools to manage.

If the tool is an rpm package, the script can donwload it and create/refresh
local rpm repository. This repository needs to be added to dnf configuration.

If the tool is a deb package, the script can donwload it and create/refresh
local apt repository. This source needs to be added to apr sources list.

If the tool is a binary or an archive, the script can download and install/update
it as specified in the configuration file.

## Prerequisites

Should be working with Python 3.8+, with additional libraries:

- jinja2
- pyyaml
- requests

that can be installed via `pip install --user -r requirements.txt`.

As for other dependencies:

- any tool being used in the configuration file should be installed
- any directory being used in the configuration file should exist
- proper permissions for any command executed from configuration file
- createrepo - installed if managing rpm files
- dpkg-dev - installed if managing deb files
- for rpm packages: local repository configured in dnf, e.g.:

  ```ini
  ❯ cat /etc/yum.repos.d/local.repo
  [local]
  name=local
  baseurl=file:///<path to directory with packages>
  enabled=1
  gpgcheck=0
  ```

- for deb packages: local repository configured in apt, e.g.:

  ```ini
  ❯ cat /etc/apt/sources.list.d/local.list
  deb [trusted=yes] file:///<path to directory with packages> /
  ```

## Usage

```bash
❯ update-tools.py --help
usage: update-tools.py [-h] [-g CONFIG_FILE] [-l | -c | -d | -u] [-f] [-s] [-v] [name ...]

positional arguments:
  name                  tool name

options:
  -h, --help            show this help message and exit
  -g CONFIG_FILE, --config-file CONFIG_FILE
                        path to configuration file, defaults to <script dir>/<script name>.yaml
  -l, --list            list supported tools
  -c, --check           check for new version only
  -d, --download        download new version only (refreshes local repository)
  -u, --update          update tools (will not install if not installed already)
  -f, --force           force download or install
  -s, --skip-current    do not show current
  -v, --verbose
```

### List tools from configuration file

```bash
❯ update-tools.py -l
```

### Check for updates

```bash
❯ update-tools.py -c

# verbose
❯ update-tools.py -cv

# skip tools that are up-to-date
❯ update-tools.py -cvs
```

### Download updates

```bash
❯ update-tools.py -d

# verbose, download only specified tools
❯ update-tools.py -dv azcopy zoom
```

### Update tools

```bash
# this only updates of the tool is already installed
❯ update-tools.py -u

# verbose, force update (installs if not installed)
❯ update-tools.py -uvf
```

### Other

- configuration file's location can be adjusted using `-g|--config-file` parameter
- there are 2 levels of verbosity `-v` and `-vv`

### Configuration file

#### Default values

- `bin_dir` - target directory for any binary
- `opt_dir` - target directory for unpacking
- `tmp_dir` - temporary directory
- `pkg_dir` - target directory for storing downloaded packages (also base for RPM repository)
- `ver` - default way of checking the local version of a tool
  - `type`
    - `cmd` for command,
    - `file` for checking content of a file
  - `name`
    - for `cmd` templated command, e.g `"{{ tool.name }} --version"`
    - for `file` templated path to the file, e.g. `"{{ tool.opt_dir }}/Postman/app/resources/app/package.json"`
  - `regex` - regular expression to extract the version, e.g. `'\d.*'`
- `git` - default settings for tools hosted on GitHub
  - `look_up` - `releases` or `tags`
  - `tag` - `latest`
  - `custom` - if the tools needs custom logic, e.g. AzureDataStudio where release
    on GitHub does not store the binaries - but as links in the release body  
    **This requires tool-specific function defined in the script.**
  - `token_env` - name of the environment variable with GitHub's
    [Personal access tokens](https://github.com/settings/tokens) - as unauthenticated
    calls are limited to 60 per hour

Each of the above default values can be overriden as needed in the tools section.

#### Tools definitions

- `name` - name of the tool
- `type` - type (`git`, `direct`, `custom`)
- `inst` - list of templated commands to update/install the tool.

If `type` is `git`:

- `repo` - GitHub repository `user/repository`
- `look_up` - where to look for versions (`releases` or `tags`)
- `tag` - which tag to look for (can use `^` and `$` to match start or end of the string)
- `not_tags` - list of tags to exclude
- `incl` - list of strings to match when looking for an asset
- `excl` - list of strings to not match when looking for an asset
- `custom` - `yes` if the tools needs custom logic

If `type` is `direct`:

- `url` - where to download package from
- `package` - name of the local file when downloading the package
- `ver_remote` - dictionary to find version of the tool:
  - `url` - what page to search for the version
  - `regex` - regular expression to extract the version

#### Templating

Templating is done using Jinja2 library and the following properties can be used
(using `tool.<property>`):

- name - tool name
- bin_dir - as in [default values](#default-values)
- opt_dir - as in [default values](#default-values)
- tmp_dir - as in [default values](#default-values)
- pkg_dir - as in [default values](#default-values)
- pkg_name - name of the local package (downloaded file)

---

Please, check the `update-tools.yaml` for some examples.
