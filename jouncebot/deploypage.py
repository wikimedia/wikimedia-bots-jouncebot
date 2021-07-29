# -*- coding: utf-8 -*-
"""Read the deployments page."""
import collections
import datetime
import math
import re
import threading

import dateutil.parser
import lxml.etree
import pytz


class DeployPage:
    """Read the deployments page."""

    SELECT_ITEM = ".deploycal-item"
    SELECT_WINDOW = ".deploycal-item-window"
    SELECT_DEPLOYERS = ".deploycal-item-deployer .ircnick"
    SELECT_OWNERS = ".deploycal-item-changes .ircnick"

    # Texts to remove from the calendar when notifying on irc:
    RE_MAX_X_PATCHES = re.compile(r"\(Max \d+ patches\)")
    BACKPORT_WARNING = (
        "Your patch may or may not be deployed at the "
        "sole discretion of the deployer"
    )

    def __init__(self, mwcon, page, logger, update_interval=15):
        """Create a DeployPage object.

        :param mwclient.Site mwcon: Connection to MediaWiki server
        :param string page: Title of page that hosts the deployment calendar
        :param int update_interval: Number of minutes between requests for
            the deployment page
        """
        self.mwcon = mwcon
        self.page = page
        self.logger = logger
        self.update_interval = update_interval

        # Things I hate about the MW API right here...
        # This is getting the full URL of the deployments page so we can create
        # nice links in IRC messages
        page_url_result = mwcon.api(
            "query",
            **{"titles": "Deployments", "prop": "info", "inprop": "url"},
        )
        idx = list(page_url_result["query"]["pages"].keys())[0]
        self.page_url = page_url_result["query"]["pages"][idx]["fullurl"]

        self.notify_callback = None
        self.notify_timer = None
        self.update_timer = None
        self.deploy_items = {}

    def start(self, notify_callback):
        """Start all the various timers."""
        self.notify_callback = notify_callback
        self._reparse_on_timer()

    def stop(self):
        """Stop all the timers."""
        if self.notify_timer:
            self.notify_timer.cancel()
        if self.update_timer:
            self.update_timer.cancel()

    def reparse(self, set_timer=False):
        """Reparse the deployment page."""
        deploy_items = collections.defaultdict(list)

        self.logger.debug(
            "Collecting new deployment information from the server"
        )
        html = self._get_page_html()
        if not html:
            self.logger.error("Failed to get any page content.")
            return

        try:
            tree = lxml.etree.HTML(html)
        except lxml.etree.XMLSyntaxError:
            self.logger.exception("Failed to parse Deployment page")
            self.logger.error('Invalid HTML? "%s"', html)
            return

        for item in tree.cssselect(self.SELECT_ITEM):
            item_id = item.get("id")
            start_time = dateutil.parser.parse(item.get("data-utcstart"))
            end_time = dateutil.parser.parse(item.get("data-utcend"))

            window_node = item.cssselect(self.SELECT_WINDOW)
            # In lxml, element.text only returns the first text node.
            # use xpath("string()") here so that it combines all text in
            # the element, including styled text, links, paragraphs, etc.
            window = (
                window_node[0].xpath("string()").strip()
                if len(window_node)
                else "Unnamed window"
            )

            # Remove unneeded text present in the calendar
            window = self.RE_MAX_X_PATCHES.sub("", window)
            window = window.replace(self.BACKPORT_WARNING, "")

            deployers = [x.text for x in item.cssselect(self.SELECT_DEPLOYERS)]

            owners = [x.text for x in item.cssselect(self.SELECT_OWNERS)]
            owners = [x for x in owners if x != "irc-nickname"]

            item_obj = DeployItem(
                item_id,
                "%s#%s" % (self.page_url, item_id),
                start_time,
                end_time,
                window,
                deployers,
                owners,
            )

            deploy_items[start_time].append(item_obj)

        self.logger.debug("Got %s items", len(deploy_items))
        self.deploy_items = deploy_items

        if set_timer:
            self._set_deploy_timer()

        return deploy_items

    def get_events(self):
        """Get all events."""
        return self.deploy_items

    def get_current_events(self):
        """Get the set of DeployEvents overlapping the current time."""
        ctime = datetime.datetime.now(pytz.utc)
        found = []
        for _stime, items in list(self.deploy_items.items()):
            for item in items:
                if item.start <= ctime and item.end >= ctime:
                    found.append(item)
        return found

    def get_next_events(self):
        """Get the first set of DeployEvents in the future."""
        ctime = datetime.datetime.now(pytz.utc)
        nexttime = None
        for time in sorted(self.deploy_items.keys()):
            if ctime < time:
                nexttime = time
                break

        if nexttime:
            return self.deploy_items[nexttime]
        else:
            return []

    def _get_page_html(self):
        try:
            # T158715: Use a raw POST instead of 'parse'
            return self.mwcon.post("parse", page=self.page)["parse"]["text"][
                "*"
            ]
        except Exception:  # noqa: B902
            self.logger.exception("Could not fetch page due to exception")
            return ""

    def _reparse_on_timer(self):
        self.reparse(set_timer=True)
        if self.update_timer:
            self.update_timer.cancel()

        self.update_timer = threading.Timer(
            self.update_interval * 60, self._reparse_on_timer
        )
        self.update_timer.start()

    def _set_deploy_timer(self):
        next_events = self.get_next_events()
        if len(next_events) > 0:
            now = datetime.datetime.now(pytz.utc)
            td = 5 + math.floor((next_events[0].start - now).total_seconds())
            if self.notify_timer:
                self.notify_timer.cancel()

            self.logger.debug(
                "Setting deploy timer to %s for %s", td, next_events[0]
            )
            self.notify_timer = threading.Timer(td, self._on_deploy_timer)
            self.notify_timer.start()

    def _on_deploy_timer(self):
        self.logger.info("Deploy timer kicked. Attempting to notify.")
        # T243394: reparse at window to catch last minute additions
        self.reparse(set_timer=False)
        events = self.get_current_events()
        self.notify_callback(events)
        self._set_deploy_timer()


class DeployItem:
    """A deployment instance."""

    def __init__(self, item_id, url, start, end, window, deployers, owners):
        """Make item."""
        self.id = item_id
        self.url = url
        self.start = start
        self.end = end
        self.window = window
        self.deployers = deployers
        self.owners = owners

    def __repr__(self):
        """Generate string representation."""
        return "%s: (%s -> %s) %s; %s for %s" % (
            self.id,
            self.start,
            self.end,
            self.window,
            ", ".join(self.deployers),
            ", ".join(self.owners),
        )
