# -*- coding: utf-8 -*-
"""IRC bot to poke people when their deploy windows are up"""

import argparse
import logging
import os

import mwclient

from jouncebot import configloader
from jouncebot import deploypage
from jouncebot import JounceBot


parser = argparse.ArgumentParser(description='Jouncebot')
parser.add_argument(
    '-c', '--config',
    default='jouncebot.yaml', help='Path to configuration file')
parser.add_argument(
    '-v', '--verbose', action='count',
    default=0, dest='loglevel', help='Increase logging verbosity')
args = parser.parse_args()

# Attempt to load the configuration
config_path = os.path.join(os.path.dirname(__file__), 'DefaultConfig.yaml')
configloader.import_file(config_path)
configloader.import_file(args.config)

# Initialize logger
logging.basicConfig(
    level=max(logging.DEBUG, logging.WARNING - (10 * args.loglevel)),
    format='%(asctime)s %(name)-12s %(levelname)-8s: %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%SZ'
)
logging.captureWarnings(True)
logger = logging.getLogger('JounceBot')
logger.setLevel(logging.DEBUG)

# Mwclient connection
mw = mwclient.Site(host=('https', configloader.values['mwclient']['wiki']))
deploy_page = deploypage.DeployPage(
    mw, configloader.values['mwclient']['calPage'], logger)

# Create the application
bot = JounceBot(configloader.values, logger, deploy_page)
logger.info('Attempting to connect to server')

try:
    bot.start()
except KeyboardInterrupt:
    deploy_page.stop()
    bot.disconnect()
except Exception:
    logger.exception('Unhandled exception. Terminating.')
    deploy_page.stop()
    bot.disconnect()
    raise SystemExit()
