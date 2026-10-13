# src/logic/web_deploy.py
"""
Nasazení web buildu Deployerem (adt/docker-deployer) po pushi. Server si naklonuje větev BRANCH
z config/.env.<stage> projektu a vezme z ní commitnutý build/web, proto se ta větev nejdřív
posune na právě pushnutý commit (jen fast-forward). Pak `make dep -- <stage>` nahraje release
a po potvrzení `make dep-pub -- <stage>` na něj přepne.
"""
import os
from tkinter import messagebox

from .build_common import execute_command, parse_env_file

WEB_DEPLOY_STAGE_KEY = "WEB_DEPLOY_STAGE"


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

    ret_code, _ = execute_command(['make', 'dep', '--', stage], logger, title=f"Nahrávám release (make dep -- {stage})")
    if ret_code != 0:
        logger.error("make dep selhal (běží Docker? je SSH klíč v agentovi?).")
        return False

    # Release je na serverech, ale web ho servíruje až po přepnutí symlinku.
    if not messagebox.askyesno(
        "Nasazení webu",
        f"Release je nahraný na stage {stage}.\n\nPřepnout web na novou verzi (make dep-pub)?",
        icon='question'
    ):
        logger.warn(f"Release je nahraný, ale web běží na předchozím. Přepnutí: make dep-pub -- {stage}")
        return True

    ret_code, _ = execute_command(['make', 'dep-pub', '--', stage], logger, title=f"Přepínám web (make dep-pub -- {stage})")
    if ret_code != 0:
        logger.error(f"make dep-pub selhal, release zůstal nahraný. Znovu: make dep-pub -- {stage}")
        return False

    logger.success(f"Web na stage {stage} běží na nové verzi.")
    return True


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
