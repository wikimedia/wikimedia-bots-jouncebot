# -*- coding: utf-8 -*-
import collections
import datetime
import dateutil.parser
import lxml.etree
import math
import pytz
import threading


class DeployPage:
    XPATH_ITEM = '//tr[@class="deploycal-item"]'
    XPATH_TIMES = 'td//span[@class="deploycal-time-utc"]/time'
    XPATH_WINDOW = 'td//span[@class="deploycal-window"]'
    XPATH_NICK = 'td//span[@class="ircnick-container"]/span[@class="ircnick"]'

    def __init__(self, mwcon, page, logger, update_interval=15):
        """Create a DeployPage object
        :param mwclient.Site mwcon: Connection to MediaWiki server that
            hosts :param page
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
        page_url_result = mwcon.api('query',
            **{'titles': 'Deployments', 'prop': 'info', 'inprop': 'url'})
        idx = page_url_result['query']['pages'].keys()[0]
        self.page_url = page_url_result['query']['pages'][idx]['fullurl']

        self.notify_callback = None
        self.notify_timer = None
        self.update_timer = None
        self.deploy_items = {}

    def start(self, notify_callback):
        """Start all the various timers"""
        self.notify_callback = notify_callback
        self._reparse_on_timer()

    def stop(self):
        if self.notify_timer:
            self.notify_timer.cancel()
        if self.update_timer:
            self.update_timer.cancel()

    def reparse(self, set_timer=False):
        deploy_items = collections.defaultdict(list)

        def stringify_children(node):
            from itertools import chain
            parts = (
                [node.text] +
                list(chain(
                    *(stringify_children(c) for c in node.getchildren()))) +
                [node.tail]
            )
            # filter removes possible Nones in texts and tails
            return ''.join(filter(None, parts))

        self.logger.debug(
            "Collecting new deployment information from the server")
        tree = lxml.etree.fromstring(
            self._get_page_html(), lxml.etree.HTMLParser())
        for item in tree.xpath(self.XPATH_ITEM):
            id = item.get('id')
            times = item.xpath(self.XPATH_TIMES)
            start_time = dateutil.parser.parse(times[0].get('datetime'))
            end_time = dateutil.parser.parse(times[1].get('datetime'))
            window = stringify_children(
                item.xpath(self.XPATH_WINDOW)[0]).replace("\n", " ").strip()
            owners = map(lambda x: x.text, item.xpath(self.XPATH_NICK))

            item_obj = DeployItem(id, '%s#%s' % (self.page_url, id),
                start_time, end_time, window, owners)

            deploy_items[start_time].append(item_obj)

        self.logger.debug("Got %s items" % len(deploy_items))
        self.deploy_items = deploy_items

        if set_timer:
            self._set_deploy_timer()

        return deploy_items

    def get_events(self):
        return self.deploy_items

    def get_current_events(self):
        pass

    def get_next_events(self):
        """What are the first set of DeployEvents in the future"""
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
            return self.mwcon.parse(
                self.mwcon.pages[self.page].edit())['text']['*']
        except Exception as ex:
            self.logger.error(
                "Could not fetch page due to exception: " + repr(ex))
            return ""

    def _reparse_on_timer(self):
        self.reparse(set_timer=True)
        if self.update_timer:
            self.update_timer.cancel()

        self.update_timer = threading.Timer(
            self.update_interval * 60, self._reparse_on_timer)
        self.update_timer.start()

    def _set_deploy_timer(self):
        next_events = self.get_next_events()
        if len(next_events) > 0:
            now = datetime.datetime.now(pytz.utc)
            td = 5 + math.floor((next_events[0].start - now).total_seconds())
            if self.notify_timer:
                self.notify_timer.cancel()

            self.logger.debug(
                "Setting deploy timer to %s for %s" % (td, next_events[0]))
            self.notify_timer = threading.Timer(
                td, self._on_deploy_timer, [next_events])
            self.notify_timer.start()

    def _on_deploy_timer(self, events):
        self.logger.info('Deploy timer kicked. Attempting to notify.')
        self.logger.debug("Num events: %s" % len(events))
        self.notify_callback(events)
        self._set_deploy_timer()


class DeployItem:
    def __init__(self, id, url, start, end, window, owners):
        self.id = id
        self.url = url
        self.start = start
        self.end = end
        self.window = window
        self.owners = owners

    def __repr__(self):
        return "%s: (%s -> %s) %s; %s" % (
            self.id,
            self.start,
            self.end,
            self.window,
            ", ".join(self.owners)
        )
