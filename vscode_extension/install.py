"""Installs the ADT Flutter Tools button into VS Code.

Packages vscode_extension/ into a .vsix with the path of this repository written
inside, so the button launches main.py from wherever the repository is cloned,
and installs it with the `code` command line tool. No Node.js is needed.

Usage: python3 vscode_extension/install.py [--editor code|cursor|...]
Run it again after moving the repository or pulling a new version of the extension.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from xml.sax.saxutils import escape

EXTENSION_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(EXTENSION_DIR)
FILES = ["package.json", "extension.js", "media/icon-32.png", "media/icon-128.png"]

# Where the `code` CLI lives when it was never added to PATH.
CLI_FALLBACKS = {
    "code": [
        "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
        os.path.expanduser("~/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd"),
    ],
    "cursor": [
        "/Applications/Cursor.app/Contents/Resources/app/bin/cursor",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\cursor\resources\app\bin\cursor.cmd"),
    ],
}

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension=".js" ContentType="application/javascript"/>'
    '<Default Extension=".json" ContentType="application/json"/>'
    '<Default Extension=".png" ContentType="image/png"/>'
    '<Default Extension=".vsixmanifest" ContentType="text/xml"/>'
    "</Types>"
)


def vsix_manifest(package):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata>
    <Identity Language="en-US" Id="{package['name']}" Version="{package['version']}" Publisher="{package['publisher']}" />
    <DisplayName>{escape(package['displayName'])}</DisplayName>
    <Description xml:space="preserve">{escape(package['description'])}</Description>
    <Categories>Other</Categories>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{package['engines']['vscode']}" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="ui" />
      <Property Id="Microsoft.VisualStudio.Code.ExecutesCode" Value="true" />
    </Properties>
    <Icon>extension/{package['icon']}</Icon>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code"/>
  </Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
    <Asset Type="Microsoft.VisualStudio.Services.Icons.Default" Path="extension/{package['icon']}" Addressable="true" />
  </Assets>
</PackageManifest>
"""


def build_vsix(target):
    with open(os.path.join(EXTENSION_DIR, "package.json"), encoding="utf-8") as file:
        package = json.load(file)

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as vsix:
        vsix.writestr("[Content_Types].xml", CONTENT_TYPES)
        vsix.writestr("extension.vsixmanifest", vsix_manifest(package))
        for name in FILES:
            vsix.write(os.path.join(EXTENSION_DIR, name), f"extension/{name}")
        vsix.writestr("extension/repo.json", json.dumps({"path": REPO_DIR}))


def find_cli(editor):
    found = shutil.which(editor)
    if found:
        return found
    for candidate in CLI_FALLBACKS.get(editor, []):
        if os.path.isfile(candidate):
            return candidate
    return None


def main():
    parser = argparse.ArgumentParser(description="Nainstaluje tlačítko ADT Flutter Tools do VS Code.")
    parser.add_argument("--editor", default="code", help="příkaz editoru: code (výchozí), cursor, …")
    args = parser.parse_args()

    cli = find_cli(args.editor)
    if cli is None:
        print(f"Příkaz '{args.editor}' nebyl nalezen. Ve VS Code: Cmd+Shift+P → "
              "„Shell Command: Install 'code' command in PATH“ a spusť skript znovu.")
        return 1

    with tempfile.TemporaryDirectory() as temp:
        vsix = os.path.join(temp, "adt-flutter-tools.vsix")
        build_vsix(vsix)
        result = subprocess.run([cli, "--install-extension", vsix, "--force"], shell=os.name == "nt")

    if result.returncode != 0:
        return result.returncode

    print(f"\nHotovo. Tlačítko spouští ADT Flutter Tools z {REPO_DIR}")
    print("Ve VS Code obnov okno: Cmd/Ctrl+Shift+P → „Developer: Reload Window“.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
