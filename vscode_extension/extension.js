// VS Code extension that launches ADT Flutter Tools (main.py) with one click.
// Plain JavaScript on purpose: install.py packages it without Node.js or a build step.
//
// The button always starts `main.py --from-editor --project <workspace folder>`. When the
// tools already run, that process hands the folder to the open window and exits
// (src/instance_link.py), so the window switches to the project instead of a second one opening.
'use strict';

const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const vscode = require('vscode');

/** The tools folder: the setting if filled in, otherwise the repository install.py ran from. */
function toolsDir() {
  const configured = (vscode.workspace.getConfiguration('adtTools').get('dir') || '').trim();
  if (configured) return configured.replace(/^~(?=$|[\\/])/, os.homedir());

  try {
    return JSON.parse(fs.readFileSync(path.join(__dirname, 'repo.json'), 'utf8')).path;
  } catch {
    return '';
  }
}

/** Workspace folder of the active editor, otherwise the first one; undefined without a local folder. */
function projectFolder() {
  const document = vscode.window.activeTextEditor && vscode.window.activeTextEditor.document;
  const folder =
    (document && vscode.workspace.getWorkspaceFolder(document.uri)) ||
    (vscode.workspace.workspaceFolders || [])[0];
  return folder && folder.uri.scheme === 'file' ? folder.uri.fsPath : undefined;
}

/** Starts main.py as from the console: through a login shell, so PATH (brewed python3 with Tk) matches. */
function launch(dir, mainArgs) {
  const logDir = path.join(os.homedir(), '.cache', 'adt_flutter_tools');
  fs.mkdirSync(logDir, { recursive: true });
  const log = fs.openSync(path.join(logDir, 'vscode-launch.log'), 'a');

  // Arguments go through "$@", so paths with spaces or quotes need no escaping.
  const [command, args] =
    process.platform === 'win32'
      ? ['python', ['main.py', ...mainArgs]]
      : [process.env.SHELL || '/bin/zsh', ['-lc', 'exec python3 main.py "$@"', 'adt-tools', ...mainArgs]];

  const child = spawn(command, args, { cwd: dir, detached: true, stdio: ['ignore', log, log], windowsHide: true });
  child.on('error', (error) => vscode.window.showErrorMessage(`ADT Flutter Tools se nepodařilo spustit: ${error.message}`));
  child.unref();
  vscode.window.setStatusBarMessage('Otevírám ADT Flutter Tools…', 3000);
}

async function open() {
  const dir = toolsDir();
  if (!dir || !fs.existsSync(path.join(dir, 'main.py'))) {
    const choice = await vscode.window.showErrorMessage(
      `ADT Flutter Tools nejsou ve složce „${dir || '?'}“. Spusť znovu vscode_extension/install.py z repozitáře, nebo vyplň nastavení adtTools.dir.`,
      'Otevřít nastavení',
    );
    if (choice) vscode.commands.executeCommand('workbench.action.openSettings', 'adtTools.dir');
    return;
  }

  const project = projectFolder();
  launch(dir, ['--from-editor', ...(project ? ['--project', project] : [])]);
}

function activate(context) {
  const statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, -100);
  statusItem.text = '$(tools) ADT Tools';
  statusItem.tooltip = 'Otevřít ADT Flutter Tools s projektem z tohoto okna';
  statusItem.command = 'adtTools.open';
  statusItem.show();

  context.subscriptions.push(statusItem, vscode.commands.registerCommand('adtTools.open', open));
}

function deactivate() {}

module.exports = { activate, deactivate };
