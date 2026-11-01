"""Explicit additive adoption migration using the configured private backend."""
import argparse
import json
from scripts.agentcon_config import read_settings
from agent_market.application_runtime import open_runtime_storage
from agent_market.agent_access.storage import migrate


def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--run',action='store_true',required=True)
    parser.parse_args()
    values=read_settings('gateway-data/agentcon.env')
    if values.get('APPLICATION_STORE_BACKEND')!='postgresql':raise ValueError('Explicit PostgreSQL settings required.')
    runtime=open_runtime_storage(None,values=values)
    try:print(json.dumps(migrate(runtime.store),sort_keys=True))
    finally:runtime.close()


if __name__=='__main__':main()
