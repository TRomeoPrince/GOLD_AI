"""Request a graceful reload of external Telegram roles, without restarting trading."""
from pathlib import Path
import argparse
import os
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
    parser.add_argument('--root',default=os.getenv('GOLD_AI_HOME',str(Path(__file__).resolve().parents[1])))
    args=parser.parse_args()
    request_reload(args.root)
    print('Telegram reload requested. The integrated Admin will restart only Telegram/notification/maintenance workers. Trading processes remain running.')


if __name__=='__main__':
    main()
