# -*- coding: utf-8 -*-
"""CLI process to test and preview the IRC bot behaviour."""

import argparse
import logging
import os

import mwclient

from jouncebot import configloader
from jouncebot import deploypage

parser = argparse.ArgumentParser(description="preview jouncebot")
parser.add_argument(
    "-v",
    "--verbose",
    action="count",
    default=0,
    dest="loglevel",
    help="Increase logging verbosity",
)
args = parser.parse_args()

# Load the configuration
config_path = os.path.join(
    os.path.dirname(__file__), "etc", "DefaultConfig.yaml"
)
configloader.import_file(config_path)

# Initialize logger
logging.basicConfig(
    level=max(logging.DEBUG, logging.WARNING - (10 * args.loglevel)),
    format="%(asctime)s %(name)-12s %(levelname)-8s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logging.captureWarnings(True)
logger = logging.getLogger("JounceBot")
logger.setLevel(logging.DEBUG)

# Mwclient connection
mw = mwclient.Site(
    host=configloader.values["mwclient"]["wiki"], scheme="https"
)

deploy_page = deploypage.DeployPage(
    mw, configloader.values["mwclient"]["calPage"], logger
)
deploy_items = deploy_page.reparse()
for _stime, items in list(deploy_items.items()):
    for item in items:
        print(
            {
                "id": item.id,
                "url": item.url,
                "start": item.start.isoformat(),
                "end": item.end.isoformat(),
                "window": item.window,
                "deployers": item.deployers,
                "owners": item.owners,
            }
        )
