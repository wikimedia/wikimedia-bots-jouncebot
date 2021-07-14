# -*- coding: utf-8 -*-
"""IRC bot to poke people when their deploy windows are up."""

import datetime
import random
import re
import sys
import time

import ib3
import ib3.auth
import ib3.connection
import ib3.mixins
import ib3.nick
import irc.strings
import pytz


def comma_join(items, oxford=True):
    """Join an iterable of strings into a comma-separated unicode string."""
    items = list(items)
    if len(items) < 2:
        return "".join(items)
    if len(items) == 2:
        return " and ".join(items)
    last = items.pop()
    sep = ", and " if oxford else " and "
    return "%s%s%s" % (", ".join(items), sep, last)


class JounceBot(
    ib3.auth.SASL,
    ib3.connection.SSL,
    ib3.mixins.DisconnectOnError,
    ib3.mixins.PingServer,
    ib3.mixins.RejoinOnBan,
    ib3.mixins.RejoinOnKick,
    ib3.nick.Regain,
    ib3.Bot,
):
    """IRC bot to poke people when their deploy windows are up."""

    def __init__(self, config, logger, deploy_page):
        """Create a bot."""
        self.config = config
        self.channel = config["irc"]["channel"]
        self.logger = logger
        self.deploy_page = deploy_page

        self.brain = {
            "help": self.do_command_help,
            "next": self.do_command_next,
            "now": self.do_command_now,
            "nowandnext": self.do_command_now_and_next,
            "refresh": self.do_command_refresh,
        }
        if self.config["debug"]:
            self.brain["debug"] = self.do_command_debug

        super(JounceBot, self).__init__(
            server_list=[
                (self.config["irc"]["server"], self.config["irc"]["port"]),
            ],
            nickname=self.config["irc"]["nick"],
            realname=self.config["irc"]["realname"],
            ident_password=self.config["irc"]["password"],
            channels=[self.channel],
        )

    def on_welcome(self, conn, event):
        """Handle a welcome message."""
        self.logger.info("Connected to server")
        self.logger.info(
            "Getting information about the wiki and starting event handler"
        )
        self.deploy_page.start(self.on_deployment_event)

    def on_join(self, conn, event):
        """Handle a join event."""
        nick = event.source.nick
        if nick == conn.get_nickname():
            self.logger.info("Successfully joined channel %s", event.target)

    def on_privmsg(self, conn, event):
        """Handle a PM message."""
        self.do_command(conn, event, event.source.nick, event.arguments[0])

    def on_pubmsg(self, conn, event):
        """Handle a public channel message."""
        msg_parts = event.arguments[0].split(" ", 1)
        if len(msg_parts) > 1:
            handle = re.match(
                r"^([a-z0-9_\-\|]+)", irc.strings.lower(msg_parts[0])
            )
            nick = irc.strings.lower(self.connection.get_nickname())
            if handle and handle.group(0) == nick:
                self.do_command(
                    conn, event, event.target, msg_parts[1].strip()
                )

    def do_command(self, conn, event, source, cmd):
        """Attempt to perform a given command given to the bot via IRC.

        :param irc.client.ServerConnection conn
        :param irc.client.Event event
        :param string cmd: String given to the bot via IRC (without bot name)
        """
        nickmask = event.source.userhost
        self.logger.debug(
            "Received command from %s at %s!%s: %s",
            source,
            event.source.nick,
            nickmask,
            cmd,
        )

        cmd = cmd.split(" ", 1)
        if cmd[0].lower() in self.brain:
            self.brain[cmd[0].lower()](conn, event, cmd, source, nickmask)

    def do_command_help(self, conn, event, cmd, source, nickmask):
        """Print all commands known to the server."""
        self.multiline(
            conn,
            source,
            """
            \x02**** JounceBot Help ****\x02
            JounceBot is a deployment helper bot for the Wikimedia movement.
            Source at: https://gerrit.wikimedia.org/g/wikimedia/bots/jouncebot
            \x02Available commands:\x02""",
        )
        for cmd in sorted(self.brain):
            self.multiline(
                conn,
                source,
                " %-7s %s" % (cmd.upper(), self.brain[cmd].__doc__),
            )

    def do_command_refresh(self, conn, event, cmd, source, nickmask):
        """Refresh my knowledge about deployments."""
        self.deploy_page.reparse(True)
        conn.privmsg(source, "I refreshed my knowledge about deployments.")

    def do_command_next(self, conn, event, cmd, source, nickmask):
        """Get the next deployment event(s if they happen at the same time)."""
        ctime = datetime.datetime.now(pytz.utc)
        future = self.deploy_page.get_next_events()
        if future:
            for event in future:
                td = event.start - ctime
                conn.privmsg(
                    source,
                    "In %d hour(s) and %d minute(s): %s (%s)"
                    % (
                        td.days * 24 + td.seconds / 60 / 60,
                        td.seconds % (60 * 60) / 60,
                        event.window,
                        event.url,
                    ),
                )
        else:
            conn.privmsg(
                source, "No deployments scheduled for the forseeable future!"
            )

    def do_command_now(self, conn, event, cmd, source, nickmask):
        """Get the current deployment event(s) or the time until the next."""
        ctime = datetime.datetime.now(pytz.utc)
        active = self.deploy_page.get_current_events()
        for event in active:
            td = event.end - ctime
            conn.privmsg(
                source,
                "For the next %d hour(s) and %d minute(s): %s (%s)"
                % (
                    td.days * 24 + td.seconds / 60 / 60,
                    td.seconds % (60 * 60) / 60,
                    event.window,
                    event.url,
                ),
            )
        if not active:
            upcoming = self.deploy_page.get_next_events()
            if upcoming:
                td = upcoming[0].start - ctime
                conn.privmsg(
                    source,
                    (
                        "No deployments scheduled for the next "
                        "%d hour(s) and %d minute(s)"
                    )
                    % (
                        td.days * 24 + td.seconds / 60 / 60,
                        td.seconds % (60 * 60) / 60,
                    ),
                )
            else:
                conn.privmsg(
                    source,
                    "No deployments scheduled for the forseeable future!",
                )

    def do_command_debug(self, conn, event, cmd, source, nickmask):
        """Handle debugging commands."""
        if len(cmd) > 1 and cmd[1] == "play events":
            events = self.deploy_page.get_events()
            for window in sorted(events):
                self.on_deployment_event(events[window])
                time.sleep(2)

    def do_command_now_and_next(self, conn, event, cmd, source, nickmask):
        """Get the current and next deployment event(s)."""
        self.do_command_now(conn, event, cmd, source, nickmask)
        self.do_command_next(conn, event, cmd, source, nickmask)

    def on_deployment_event(self, next_events):
        """Handle a deployment event."""
        for event in next_events:
            if len(event.deployers) > 0:
                deployers = comma_join(event.deployers)
                msg = random.choice(self.config["messages"]["deployer"])
            else:
                deployers = False
                msg = random.choice(self.config["messages"]["generic"])

            self.connection.privmsg(
                self.channel, msg.format(deployers=deployers, event=event)
            )
            if len(event.owners) > 0:
                owners = comma_join(event.owners)
                msg = random.choice(self.config["messages"]["owner"])
                self.connection.privmsg(
                    self.channel, msg.format(owners=owners, event=event)
                )
            elif "backport window" in event.window:
                self.connection.privmsg(
                    self.channel,
                    "No GERRIT patches in the queue for this window AFAICS.",
                )

    def multiline(self, conn, nick, text):
        """Send multiline message."""
        lines = text.expandtabs().splitlines()
        indent = sys.maxsize
        if lines[1:]:
            stripped = lines[1].lstrip()
            if stripped:
                indent = min(indent, len(lines[1]) - len(stripped))
        if lines[0] == "":
            del lines[0]
            conn.privmsg(nick, lines[0][indent:])
        else:
            conn.privmsg(nick, lines[0])

        for line in lines[1:]:
            conn.privmsg(nick, line[indent:])
