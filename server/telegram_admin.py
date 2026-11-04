"""Request a graceful reload of external Telegram roles, without restarting trading."""
from pathlib import Path
import argparse
import time
import uuid
from .atomic_json import atomic_write_json


def request_reload(root):
    path=Path(root).resolve()/'logs'/'telegram_reload.json'
    generation=uuid.uuid4().hex
    atomic_write_json(path,{'generation':generation,'requested_utc_epoch':time.time()})
    return generation


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['reload'])
    parser.add_argument('--root')
    args=parser.parse_args()
    from .admin_launcher import owner_home
    request_reload(args.root or owner_home())
    print('Telegram reload requested. The integrated Admin will restart only Telegram/notification/maintenance workers. Trading processes remain running.')


if __name__=='__main__':
    main()
