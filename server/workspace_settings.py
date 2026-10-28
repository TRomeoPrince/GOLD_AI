"""Owner display/reconnect/reminder settings, containing no credentials."""
from pathlib import Path
import json
import math
import os
from zoneinfo import ZoneInfo
from .atomic_json import atomic_write_json

DEFAULTS = dict(display_timezone='UTC', retry_interval=5, retry_cap=30,
                retries_before_alert=5, alert_cooldown=300, reminder_days=[3, 1, 0])


def settings_path():
    from .store import DB_PATH
    return Path(os.getenv('GOLD_AI_STATE_DIR', str(DB_PATH.parent))) / 'workspace_settings.json'


def _validate(values):
    result = {**DEFAULTS, **{key:value for key,value in values.items() if key in DEFAULTS}}
    ZoneInfo(str(result['display_timezone']))
    for key, low, high in [('retry_interval',1,300),('retry_cap',5,3600),('retries_before_alert',1,100),('alert_cooldown',0,86400)]:
        number = float(result[key])
        if not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f'{key} must be between {low} and {high}.')
        result[key] = int(number) if key == 'retries_before_alert' else number
    if result['retry_cap'] < result['retry_interval']:
        raise ValueError('Maximum retry must be at least the initial retry interval.')
    days = result['reminder_days']
    if not isinstance(days, list) or not days or len(days) > 20:
        raise ValueError('Provide between 1 and 20 reminder thresholds.')
    if any(not isinstance(day,int) or isinstance(day,bool) or day < 0 or day > 365 for day in days):
        raise ValueError('Reminder days must be whole numbers from 0 to 365.')
    result['reminder_days'] = sorted(set(days), reverse=True)
    return result


def load_settings():
    try:
        data = json.loads(settings_path().read_text(encoding='utf-8'))
    except FileNotFoundError:
        data = {}
    return _validate(data)


def save_settings(**changes):
    values = _validate({**load_settings(), **changes})
    atomic_write_json(settings_path(), values)
    return values
