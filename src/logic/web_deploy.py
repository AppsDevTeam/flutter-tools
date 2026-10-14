# src/logic/web_deploy.py
"""
Nasazení web buildu Deployerem (adt/docker-deployer) po pushi. Server si naklonuje větev BRANCH
z config/.env.<stage> projektu a vezme z ní commitnutý build/web, proto se ta větev nejdřív
posune na právě pushnutý commit (jen fast-forward). Pak `make dep -- <stage>` nahraje release
a po potvrzení `make dep-pub -- <stage>` na něj přepne.
"""
import os
import platform
import re
from tkinter import messagebox

from .build_common import execute_command, parse_env_file

WEB_DEPLOY_STAGE_KEY = "WEB_DEPLOY_STAGE"

# Deployer běží v Dockeru, který na agenta macOS (klíč s heslem z Keychainu) nedosáhne; Docker
# Desktop i OrbStack ho zpřístupní tady. Skript vendor/bin/dep si ho vezme z SSH_AUTH_SOCK.
_DOCKER_SSH_AGENT = "/run/host-services/ssh-auth.sock"


def read_deploy_stage(env_vars):
    """Stage z adt_tools_config.env; None = projekt web nasazovat nechce."""
    return env_vars.get(WEB_DEPLOY_STAGE_KEY, "").strip() or None


def stage_config_path(stage):
    return os.path.join('config', f'.env.{stage}')


def deploy_web(logger, stage):
    """Vrací True, když je release nahraný (i když ho uživatel nechal nepřepnutý)."""
    logger.header(f"--- Nasazuji web na stage {stage} ---")

    config_path = stage_config_path(stage)
    if not os.path.exists(config_path):
        logger.error(f"Chybí {config_path} — stage {stage} nejde nasadit.")
        return False

    branch = parse_env_file(logger, config_path).get('BRANCH')
    if not branch:
        logger.error(f"V {config_path} chybí BRANCH (větev, kterou server klonuje).")
        return False

    if not _move_stage_branch(logger, branch):
        logger.error(f"Nasazení přerušeno, ručně: posunout {branch} a pak make dep -- {stage}.")
        return False

    if not _ensure_deployer(logger):
        return False

    ret_code, output = _make(logger, 'dep', stage, f"Nahrávám release (make dep -- {stage})")

    # Zámek z předchozího nasazení, které se nedokončilo (nahráno bez přepnutí, přerušené).
    if ret_code != 0 and _is_locked(output):
        logger.error(
            f"Na stage {stage} je zámek z předchozího nasazení, které se nedokončilo (release nahraný, "
            f"ale nepřepnutý, nebo přerušené nasazení)."
        )
        if not messagebox.askyesno(
            "Nasazení webu",
            f"Na stage {stage} zůstal zámek z předchozího nasazení, které se nedokončilo.\n\n"
            "Uvolnit ho a nasadit znovu? Ne, pokud právě nasazuje někdo jiný.",
            icon='warning'
        ):
            logger.warn(f"Zámek zůstal. Ručně: vendor/bin/dep deploy:unlock {stage} a pak make dep -- {stage}")
            return False

        unlock_code, _ = execute_command(
            ['vendor/bin/dep', 'deploy:unlock', stage], logger,
            title=f"Uvolňuji zámek (dep deploy:unlock {stage})", extra_env=_deployer_env()
        )
        if unlock_code != 0:
            logger.error("Zámek se nepodařilo uvolnit.")
            return False
        ret_code, output = _make(logger, 'dep', stage, f"Nahrávám release znovu (make dep -- {stage})")

    if ret_code != 0:
        logger.error(f"make dep selhal: {_explain_failure(output)}")
        return False

    # Release je na serverech, ale web ho servíruje až po přepnutí symlinku.
    if not messagebox.askyesno(
        "Nasazení webu",
        f"Release je nahraný na stage {stage}.\n\nPřepnout web na novou verzi (make dep-pub)?",
        icon='question'
    ):
        logger.warn(f"Release je nahraný, ale web běží na předchozím. Přepnutí: make dep-pub -- {stage}")
        return True

    ret_code, output = _make(logger, 'dep-pub', stage, f"Přepínám web (make dep-pub -- {stage})")
    if ret_code != 0:
        logger.error(f"make dep-pub selhal ({_explain_failure(output)}), release zůstal nahraný. "
                     f"Znovu: make dep-pub -- {stage}")
        return False

    logger.success(f"Web na stage {stage} běží na nové verzi.")
    return True


def _make(logger, target, stage, title):
    return execute_command(['make', target, '--', stage], logger, title=title, extra_env=_deployer_env())


def _deployer_env():
    """Na macOS agent z Dockeru (viz _DOCKER_SSH_AGENT), jinde beze změny."""
    return {"SSH_AUTH_SOCK": _DOCKER_SSH_AGENT} if platform.system() == "Darwin" else None


def _is_locked(output):
    return "Deploy locked" in (output or "")


def _explain_failure(output):
    """Srozumitelný důvod podle výpisu Deployeru; jinak obecná rada."""
    output = output or ""
    match = re.search(r'Bad configuration option: (\w+)', output)
    if match:
        return (f"SSH v Dockeru nezná volbu {match.group(1)} z ~/.ssh/config; přidejte před ni "
                f"řádek „IgnoreUnknown {match.group(1)}“.")
    if "Permission denied (publickey" in output:
        return ("server odmítl SSH klíč: je klíč v agentovi (ssh-add -l) a má uživatel stage na serveru "
                "přidaný váš veřejný klíč?")
    if "Cannot connect to the Docker daemon" in output or "docker: command not found" in output:
        return "Docker neběží (spusťte Docker Desktop nebo OrbStack)."
    if "chybí build/web/index.html" in output:
        return "ve větvi stage chybí commitnutý build/web."
    return "viz výpis výše (běží Docker? je SSH klíč v agentovi?)."


def _move_stage_branch(logger, branch):
    """Posune větev stage na serveru na HEAD; push bez --force projde jen jako fast-forward."""
    ret_code, output = execute_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], logger, log_stdout=False)
    current = output.strip() if ret_code == 0 else ""
    if current == branch:
        logger.info(f"Build je přímo ve větvi {branch}.")
        return True

    remote = "origin"
    if current:
        ret_code, output = execute_command(['git', 'config', f'branch.{current}.remote'], logger, log_stdout=False)
        if ret_code == 0 and output.strip():
            remote = output.strip()

    logger.info(f"Posouvám {remote}/{branch} na {current or 'HEAD'} (jen fast-forward)...")
    ret_code, _ = execute_command(['git', 'push', remote, f'HEAD:refs/heads/{branch}'], logger)
    if ret_code != 0:
        logger.error(f"{branch} nejde posunout fast-forwardem: má commity, které {current or 'HEAD'} nemá.")
        return False
    return True


def _ensure_deployer(logger):
    """vendor/bin/dep z composer.json projektu; bez lokálního composeru přes jeho Docker image."""
    if os.path.exists(os.path.join('vendor', 'bin', 'dep')):
        return True

    ret_code, _ = execute_command(['composer', 'install'], logger, title="Instaluji Deployer (composer install)")
    if ret_code == -1:
        # Composer není nainstalovaný; Docker je pro Deployer potřeba tak jako tak.
        command = ['docker', 'run', '--rm', '-v', f'{os.getcwd()}:/app', '-w', '/app']
        if hasattr(os, 'getuid'):
            command += ['-u', f'{os.getuid()}:{os.getgid()}']
        ret_code, _ = execute_command(command + ['composer:2', 'install'], logger, title="Instaluji Deployer (composer v Dockeru)")

    if ret_code != 0 or not os.path.exists(os.path.join('vendor', 'bin', 'dep')):
        logger.error("Deployer (vendor/bin/dep) se nepodařilo nainstalovat.")
        return False
    return True
