#! /usr/bin/env python2
# -*- coding: utf-8 -*-
"""IRC bot to poke people when their deploy windows are up"""

import argparse
import configloader
import datetime
import deploypage
import ib3
import ib3.auth
import ib3.connection
import ib3.mixins
import ib3.nick
import irc.strings
import logging
import logging.handlers
import mwclient
import os
import pytz
import random
import re
import sys
import time


def comma_join(items, oxford=True):
    """Join an iterable of strings into a comma-separated unicode string."""
    items = list(items)
    if len(items) < 2:
        return u''.join(items)
    if len(items) == 2:
        return u' and '.join(items)
    last = items.pop()
    sep = ', and ' if oxford else ' and '
    return u'%s%s%s' % (', '.join(items), sep, last)


class JounceBot(
    ib3.auth.SASL,
    ib3.connection.SSL,
    ib3.mixins.DisconnectOnError,
    ib3.mixins.PingServer,
    ib3.mixins.RejoinOnBan,
    ib3.mixins.RejoinOnKick,
    ib3.nick.Regain,
    ib3.Bot
):

    def __init__(self, config, logger, deploy_page):
        self.config = config
        self.channel = config['irc']['channel']
        self.logger = logger
        self.deploy_page = deploy_page

        self.brain = {
            'help': self.do_command_help,
            'die': self.do_command_die,
            'next': self.do_command_next,
            'now': self.do_command_now,
            'refresh': self.do_command_refresh,
        }
        if self.config['debug']:
            self.brain['debug'] = self.do_command_debug

        super(JounceBot, self).__init__(
            server_list=[
                (self.config['irc']['server'], self.config['irc']['port']),
            ],
            nickname=self.config['irc']['nick'],
            realname=self.config['irc']['realname'],
            ident_password=self.config['irc']['password'],
            channels=[self.channel],
        )

    def on_welcome(self, conn, event):
        self.logger.info("Connected to server")
        self.logger.info(
            "Getting information about the wiki and starting event handler")
        self.deploy_page.start(self.on_deployment_event)

    def on_join(self, conn, event):
        nick = event.source.nick
        if nick == conn.get_nickname():
            self.logger.info("Successfully joined channel %s" % event.target)

    def on_privmsg(self, conn, event):
        self.do_command(conn, event, event.source.nick, event.arguments[0])

    def on_pubmsg(self, conn, event):
        msg_parts = event.arguments[0].split(" ", 1)
        if len(msg_parts) > 1:
            handle = re.match(
                r"^([a-z0-9_\-\|]+)",
                irc.strings.lower(msg_parts[0]))
            nick = irc.strings.lower(self.connection.get_nickname())
            if handle and handle.group(0) == nick:
                self.do_command(
                    conn, event, event.target, msg_parts[1].strip())

    def do_command(self, conn, event, source, cmd):
        """Attempt to perform a given command given to the bot via IRC
        :param irc.client.ServerConnection conn
        :param irc.client.Event event
        :param string cmd: String given to the bot via IRC (without bot name)
        """
        nickmask = event.source.userhost
        self.logger.debug("Received command from %s at %s!%s: %s" % (
            source, event.source.nick, nickmask, cmd))

        cmd = cmd.split(" ", 1)
        if cmd[0].lower() in self.brain:
            self.brain[cmd[0].lower()](
                conn, event, cmd, source, nickmask)

    def do_command_help(self, conn, event, cmd, source, nickmask):
        """Prints the list of all commands known to the server"""
        self.multiline(
            conn,
            source,
            """
            \x02**** JounceBot Help ****\x02
            JounceBot is a deployment helper bot for the Wikimedia Foundation.
            You can find my source at https://github.com/mattofak/jouncebot
            \x02Available commands:\x02"""
        )
        for cmd in sorted(self.brain):
            self.multiline(conn, source, " %-7s %s" % (
                cmd.upper(), self.brain[cmd].__doc__))

    def do_command_die(self, conn, event, cmd, nick, nickmask):
        """Kill this bot"""
        self.deploy_page.stop()
        self.die("Killed by %s" % nick)
        exit()

    def do_command_refresh(self, conn, event, cmd, source, nickmask):
        """Refresh my knowledge about deployments"""
        self.deploy_page.reparse(True)
        conn.privmsg(source, "I refreshed my knowledge about deployments.")

    def do_command_next(self, conn, event, cmd, source, nickmask):
        """Get the next deployment event(s if they happen at the same time)"""
        ctime = datetime.datetime.now(pytz.utc)
        future = self.deploy_page.get_next_events()
        if future:
            for event in future:
                td = event.start - ctime
                conn.privmsg(
                    source,
                    "In %d hour(s) and %d minute(s): %s (%s)" % (
                        td.days * 24 + td.seconds / 60 / 60,
                        td.seconds % (60 * 60) / 60,
                        event.window,
                        event.url))
        else:
            conn.privmsg(
                source,
                "No deployments scheduled for the forseeable future!")

    def do_command_now(self, conn, event, cmd, source, nickmask):
        """Get the current deployment event(s) or the time until the next"""
        ctime = datetime.datetime.now(pytz.utc)
        active = self.deploy_page.get_current_events()
        for event in active:
            td = event.end - ctime
            conn.privmsg(
                source,
                "For the next %d hour(s) and %d minute(s): %s (%s)" % (
                    td.days * 24 + td.seconds / 60 / 60,
                    td.seconds % (60 * 60) / 60,
                    event.window,
                    event.url))
        if not active:
            upcoming = self.deploy_page.get_next_events()
            if upcoming:
                td = upcoming[0].start - ctime
                conn.privmsg(
                    source,
                    (
                        "No deployments scheduled for the next "
                        "%d hour(s) and %d minute(s)"
                    ) % (
                        td.days * 24 + td.seconds / 60 / 60,
                        td.seconds % (60 * 60) / 60
                    ))
            else:
                conn.privmsg(
                    source,
                    "No deployments scheduled for the forseeable future!")

    def do_command_debug(self, conn, event, cmd, source, nickmask):
        """Debugging commands"""
        if len(cmd) > 1 and cmd[1] == 'play events':
            events = self.deploy_page.get_events()
            for window in sorted(events):
                self.on_deployment_event(events[window])
                time.sleep(2)

    def on_deployment_event(self, next_events):
        for event in next_events:
            if len(event.deployers) > 0:
                deployers = comma_join(event.deployers)
                msg = random.choice(self.config['messages']['deployer'])
            else:
                deployers = False
                msg = random.choice(self.config['messages']['generic'])

            if len(event.owners) > 0:
                # Don't ping deployers unless there are patches to be deployed
                self.connection.privmsg(
                    self.channel, msg.format(deployers=deployers, event=event)
                )
                owners = comma_join(event.owners)
                msg = random.choice(self.config['messages']['owner'])
                self.connection.privmsg(
                    self.channel, msg.format(owners=owners, event=event))
            else:
                self.connection.privmsg(
                    self.channel,
                    'No patches in the queue for this window. Wheeee!'
                )

    def multiline(self, conn, nick, text):
        lines = text.expandtabs().splitlines()
        indent = sys.maxint
        if lines[1:]:
            stripped = lines[1].lstrip()
            if stripped:
                indent = min(indent, len(lines[1]) - len(stripped))
        if lines[0] == '':
            del lines[0]
            conn.privmsg(nick, lines[0][indent:])
        else:
            conn.privmsg(nick, lines[0])

        for line in lines[1:]:
            conn.privmsg(nick, line[indent:])


if __name__ == '__main__':
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
        exit(1)
