#! /usr/bin/env python2
# -*- coding: utf-8 -*-
"""IRC bot to poke people when their deploy windows are up"""

import configloader
import datetime
import deploypage
import irc.bot
import irc.buffer
import irc.client
import irc.strings
import logging
import logging.handlers
import mwclient
import optparse
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


class JounceBot(irc.bot.SingleServerIRCBot):

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

        # Don't even get me started on how stupid a pattern this is
        irc.client.ServerConnection.buffer_class = \
            irc.buffer.LenientDecodingLineBuffer

        irc.bot.SingleServerIRCBot.__init__(
            self,
            [(self.config['irc']['server'], self.config['irc']['port'])],
            self.config['irc']['nick'],
            self.config['irc']['realname']
        )

    def on_nicknameinuse(self, conn, event):
        self.logger.warning(
            "Requested nickname %s already in use, appending _" %
            conn.get_nickname())
        conn.nick(conn.get_nickname() + "_")
        conn.execute_delayed(30, self.do_reclaim_nick)

    def do_reclaim_nick(self):
        nick = self.connection.get_nickname()
        if nick != self.config['irc']['nick']:
            self.connection.nick(self.config['irc']['nick'])
            self.logger.info("Nickname changed to default.")

    def on_welcome(self, conn, event):
        self.logger.info("Connected to server")
        self.do_identify()
        self.logger.info(
            "Getting information about the wiki and starting event handler")
        self.deploy_page.start(self.on_deployment_event)

    def on_error(self, conn, event):
        self.logger.warning('%s: %s' % (event.source, event.arguments[0]))

    def on_privnotice(self, conn, event):
        msg = event.arguments[0]
        self.logger.warning('%s: %s' % (event.source, msg))

        if event.source.nick == "NickServ":
            if "NickServ identify" in msg:
                self.do_identify()
            elif "Invalid password" in msg:
                sys.exit("Invalid password. Check settings")
            elif "You are now identified" in msg:
                self.logger.debug("Login succeeded")
                self.logger.info("Attempting to join channel %s", self.channel)
                conn.join(self.channel)

    def on_join(self, conn, event):
        nick = event.source.nick
        if nick == conn.get_nickname():
            self.logger.info("Successfully joined channel %s" % event.target)

    def on_privmsg(self, conn, event):
        self.do_command(conn, event, event.source.nick, event.arguments[0])

    def on_pubmsg(self, conn, event):
        msg_parts = event.arguments[0].split(" ", 1)
        if len(msg_parts) > 1:
            handle = re.match(r"^([a-z0-9_\-\|]+)",
                irc.strings.lower(msg_parts[0]))
            nick = irc.strings.lower(self.connection.get_nickname())
            if handle and handle.group(0) == nick:
                self.do_command(
                    conn, event, event.target, msg_parts[1].strip())
        return

    def do_identify(self):
        """Send NickServ an identify message."""
        self.logger.info("Authenticating with Nickserv")
        self.connection.privmsg("NickServ", "identify %s %s" % (
            self.config['irc']['nick'], self.config['irc']['password']))

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
        for event in self.deploy_page.get_next_events():
            td = event.start - ctime
            conn.privmsg(source,
                "In %d hour(s) and %d minute(s): %s (%s)" % (
                    td.days * 24 + td.seconds / 60 / 60,
                    td.seconds % (60 * 60) / 60,
                    event.window,
                    event.url))

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
            td = upcoming[0].start - ctime
            conn.privmsg(
                source,
                ("No deployments scheduled for the next "
                "%d hour(s) and %d minute(s)") % (
                    td.days * 24 + td.seconds / 60 / 60,
                    td.seconds % (60 * 60) / 60))

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

            self.connection.privmsg(
                self.channel, msg.format(deployers=deployers, event=event))

            if len(event.owners) > 0:
                owners = comma_join(event.owners)
                msg = random.choice(self.config['messages']['owner'])
                self.connection.privmsg(
                    self.channel, msg.format(owners=owners, event=event))

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


if __name__ == "__main__":
    parser = optparse.OptionParser(usage="usage: %prog [options]")
    parser.add_option("-c", "--config", dest='configFile',
        default='jouncebot.yaml', help='Path to configuration file')
    (options, args) = parser.parse_args()

    # Attempt to load the configuration
    config_path = os.path.join(os.path.dirname(__file__), 'DefaultConfig.yaml')
    configloader.import_file(config_path)
    if options.configFile is not None:
        configloader.import_file(options.configFile)

    # Initialize some sort of logger
    logger = logging.getLogger('JounceBot')
    logger.setLevel(logging.DEBUG)
    if sys.stdin.isatty() or not configloader.values['logging']['useSyslog']:
        # Just need to log to the console
        handler = logging.StreamHandler(sys.stdout)
        logger.addHandler(handler)
        handler.setFormatter(
            logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    else:
        # Log to syslog
        logger.addHandler(logging.handlers.SysLogHandler(address="/dev/log"))

    # Mwclient connection
    mw = mwclient.Site(host=('https', configloader.values['mwclient']['wiki']))
    deploy_page = deploypage.DeployPage(
        mw, configloader.values['mwclient']['calPage'], logger)

    # Create the application
    bot = JounceBot(configloader.values, logger, deploy_page)
    logger.info("Attempting to connect to server")

    try:
        bot.start()
    except KeyboardInterrupt:
        deploy_page.stop()
        exit(0)
    except Exception:
        logging.exception("Unhandled exception. Terminating.")
        deploy_page.stop()
        exit(1)

    logging.error("No idea how I got here...")
