#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright (C) 2009-2012:
#    Gabes Jean, naparuba@gmail.com
#    Gerhard Lausser, Gerhard.Lausser@consol.de
#    Gregory Starck, g.starck@gmail.com
#    Hartmut Goebel, h.goebel@goebel-consult.de
#    Frederic Mohier, frederic.mohier@gmail.com
#
# This file is part of Shinken.
#
# Shinken is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Shinken is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with Shinken.  If not, see <http://www.gnu.org/licenses/>.


"""
This class is for attaching a mongodb database to a broker module.
It is one possibility for an exchangeable storage for log broks
"""

import os
import time
import datetime
import re
import sys
import pymongo
import traceback

from shinken.objects.service import Service
from shinken.modulesctx import modulesctx

# Import a class from the livestatus module, should be already loaded!
# livestatus = modulesctx.get_module('livestatus')

# LiveStatusStack = livestatus.LiveStatusStack
# LOGCLASS_INVALID = livestatus.LOGCLASS_INVALID
# Logline = livestatus.Logline
from .log_line import (
    Logline,
    LOGCLASS_INVALID
)


try:
    import pymongo
    from pymongo import MongoClient
    from pymongo.errors import AutoReconnect
except ImportError:
    logger.error('[mongo-logs] Can not import pymongo and/or MongoClient'
                 'Your pymongo lib is too old. '
                 'Please install it with a 3.x+ version from '
                 'https://pypi.python.org/pypi/pymongo')
    MongoClient = None

from shinken.basemodule import BaseModule
from shinken.objects.module import Module
from shinken.log import logger
from shinken.util import to_bool

from collections import deque

properties = {
    'daemons': ['broker', 'webui'],
    'type': 'mongo-logs',
    'external': True,
    'phases': ['running'],
    }


# called by the plugin manager
def get_instance(plugin):
    logger.info("[mongo-logs] got an instance of MongoLogs for module: %s", plugin.get_name())
    instance = MongoLogs(plugin)
    return instance


CONNECTED = 1
DISCONNECTED = 2
SWITCHING = 3


class MongoLogsError(Exception):
    pass


class MongoLogs(BaseModule):

    def __init__(self, mod_conf):
        try:
            import pymongo
        except ImportError:
            logger.error('[WebUI-mongo-logs] Can not import pymongo'
                         'Please install it with a 3.x+ version from '
                         'https://pypi.python.org/pypi/pymongo')
            raise

        BaseModule.__init__(self, mod_conf)

        self.uri = getattr(mod_conf, 'uri', 'mongodb://localhost')
        logger.info('[mongo-logs] mongo uri: %s', self.uri)

        self.replica_set = getattr(mod_conf, 'replica_set', None)
        if self.replica_set and int(pymongo.version[0]) < 3:
            logger.error('[mongo-logs] Can not initialize module with '
                         'replica_set because your pymongo lib is too old. '
                         'Please install it with a 3.x+ version from '
                         'https://pypi.python.org/pypi/pymongo')
            return None

        self.database = getattr(mod_conf, 'database', 'shinken')
        self.username = getattr(mod_conf, 'username', None)
        self.password = getattr(mod_conf, 'password', None)
        logger.info('[mongo-logs] database: %s, username: %s', self.database, self.username)

        self.commit_period = int(getattr(mod_conf, 'commit_period', '10'))
        logger.info('[mongo-logs] periodical commit period: %ds', self.commit_period)

        self.commit_volume = int(getattr(mod_conf, 'commit_volume', '1000'))
        logger.info('[mongo-logs] periodical commit volume: %d lines', self.commit_volume)

        self.db_test_period = int(getattr(mod_conf, 'db_test_period', '0'))
        logger.info('[mongo-logs] periodical DB connection test period: %ds', self.db_test_period)

        self.logs_collection = getattr(mod_conf, 'logs_collection', 'logs')
        logger.info('[mongo-logs] logs collection: %s', self.logs_collection)

        self.hav_collection = getattr(mod_conf, 'hav_collection', 'availability')
        logger.info('[mongo-logs] hosts availability collection: %s', self.hav_collection)

        self.mongodb_fsync = to_bool(getattr(mod_conf, 'mongodb_fsync', "True"))

        max_logs_age = getattr(mod_conf, 'max_logs_age', '365')
        maxmatch = re.match(r'^(\d+)([dwmy]*)$', max_logs_age)
        if not maxmatch:
            logger.error('[mongo-logs] Wrong format for max_logs_age. Must be <number>[d|w|m|y] or <number> and not %s' % max_logs_age)
            return None
        else:
            if not maxmatch.group(2):
                self.max_logs_age = int(maxmatch.group(1))
            elif maxmatch.group(2) == 'd':
                self.max_logs_age = int(maxmatch.group(1))
            elif maxmatch.group(2) == 'w':
                self.max_logs_age = int(maxmatch.group(1)) * 7
            elif maxmatch.group(2) == 'm':
                self.max_logs_age = int(maxmatch.group(1)) * 31
            elif maxmatch.group(2) == 'y':
                self.max_logs_age = int(maxmatch.group(1)) * 365
        logger.info('[mongo-logs] max_logs_age: %s', self.max_logs_age)

        self.services_cache = {}
        services_filter = getattr(mod_conf, 'services_filter', '')
        logger.info('[mongo-logs] services filtering: %s', services_filter)

        self.filter_service_description = None
        self.filter_service_criticality = None
        if services_filter:
            # Decode services filter
            services_filter = [s for s in services_filter.split(',')]
            for rule in services_filter:
                rule = rule.strip()
                if not rule:
                    continue
                logger.info('[mongo-logs] services filtering rule: %s', rule)
                elts = rule.split(':', 1)

                t = 'service_description'
                if len(elts) > 1:
                    t = elts[0].lower()
                    s = elts[1].lower()

                if t == 'service_description':
                    self.filter_service_description = rule
                    logger.info('[mongo-logs] services will be filtered by description: %s', self.filter_service_description)

                if t == 'bp' or t == 'bi':
                    self.filter_service_criticality = s
                    logger.info('[mongo-logs] services will be filtered by criticality: %s', self.filter_service_criticality)


        # Elasticsearch configuration part ... prepare next version !
        # self.elasticsearch_uri = getattr(mod_conf, 'elasticsearch_uri', None)
        # if self.elasticsearch_uri:
            # try:
                # import rawes
                # from rawes.elastic_exception import ElasticException
            # except ImportError:
                # logger.error('[mongo-logs] Can not import rawes library. Data will not be sent to your configured ElasticSearch: %s', self.elasticsearch_uri)
                # self.elasticsearch_uri = None
            # else:
                # logger.info('[mongo-logs] data will be sent to ElasticSearch: %s', self.elasticsearch_uri)


        self.is_connected = DISCONNECTED

        self.logs_cache = deque()

        self.availability_cache = {}
        self.availability_cache_backlog = []

    def load(self, app):
        self.app = app

    def init(self):
        self.open()

    def open(self):
        try:
            from pymongo import MongoClient
        except ImportError:
            logger.error('[WebUI-mongo-logs] Can not import pymongo.MongoClient')
            raise

        try:
            if self.replica_set:
                self.con = MongoClient(self.uri, replicaSet=self.replica_set, fsync=self.mongodb_fsync)
            else:
                self.con = MongoClient(self.uri, fsync=self.mongodb_fsync)
            logger.info("[mongo-logs] connected to mongodb: %s", self.uri)

            self.db = getattr(self.con, self.database)
            logger.info("[mongo-logs] connected to the database: %s", self.database)

            if self.username and self.password:
                self.db.authenticate(self.username, self.password)
                logger.info("[mongo-logs] user authenticated: %s", self.username)

            self.is_connected = CONNECTED
            self.next_logs_rotation = time.time()

            logger.info('[mongo-logs] database connection established')
        except AutoReconnect, exp:
            # now what, ha?
            logger.error("[mongo-logs] MongoLogs.AutoReconnect: %s", exp)
            # The mongodb is hopefully available until this module is restarted
            raise MongoLogsError
        except Exception, exp:
            # If there is a replica_set, but the host is a simple standalone one
            # we get a "No suitable hosts found" here.
            # But other reasons are possible too.
            logger.error("[mongo-logs] Could not open the database", exp)
            raise MongoLogsError

    def close(self):
        self.is_connected = DISCONNECTED
        self.con.close()
        logger.info('[mongo-logs] database connection closed')

    def commit(self):
        pass

    def rotate_logs(self):
        """
        For a Mongo DB there is no rotate, but we will delete logs older than configured maximum age.
        """
        logger.info("[mongo-logs] rotating logs ...")

        now = time.time()
        today = datetime.date.today()
        today0000 = datetime.datetime(today.year, today.month, today.day, 0, 0, 0)
        today0005 = datetime.datetime(today.year, today.month, today.day, 0, 5, 0)
        oldest = today0000 - datetime.timedelta(days=self.max_logs_age)
        result = self.db[self.logs_collection].delete_many({u'time': {'$lt': time.mktime(oldest.timetuple())}})
        logger.info("[mongo-logs] removed %d logs older than %s days.", result.deleted_count, self.max_logs_age)

        if now < time.mktime(today0005.timetuple()):
            nextrotation = today0005
        else:
            nextrotation = today0005 + datetime.timedelta(days=1)

        # See you tomorrow
        self.next_logs_rotation = time.mktime(nextrotation.timetuple())
        logger.info("[mongo-logs] next log rotation at %s " % time.asctime(time.localtime(self.next_logs_rotation)))

    def commit_logs(self):
        """
        Peridically called (commit_period), this method prepares a bunch of queued logs (commit_colume) to insert them in the DB
        """
        if not self.logs_cache:
            return

        logger.debug("[mongo-logs] commiting ...")

        logger.debug("[mongo-logs] %d lines to insert in database (max insertion is %d lines)", len(self.logs_cache), self.commit_volume)

        # Flush all the stored log lines
        logs_to_commit = 1
        now = time.time()
        some_logs = []
        while True:
            try:
                # result = self.db[self.logs_collection].insert_one(self.logs_cache.popleft())
                some_logs.append(self.logs_cache.popleft())
                logs_to_commit = logs_to_commit + 1
                if logs_to_commit >= self.commit_volume:
                    break
            except IndexError:
                logger.debug("[mongo-logs] prepared all available logs for commit")
                break
            except Exception, exp:
                logger.error("[mongo-logs] exception: %s", str(exp))
        logger.debug("[mongo-logs] time to prepare %s logs for commit (%2.4f)", logs_to_commit, time.time() - now)

        now = time.time()
        try:
            result = self.db[self.logs_collection].insert_many(some_logs)
            logger.debug("[mongo-logs] inserted %d logs.", len(result.inserted_ids))
        except AutoReconnect, exp:
            logger.error("[mongo-logs] Autoreconnect exception when inserting lines: %s", str(exp))
            self.is_connected = SWITCHING
            # Abort commit ... will be finished next time!
        except Exception, exp:
            self.close()
            logger.error("[mongo-logs] Database error occurred when commiting: %s", exp)
        logger.debug("[mongo-logs] time to insert %s logs (%2.4f)", logs_to_commit, time.time() - now)

    def manage_brok(self, brok):
        """
        Overloaded parent class manage_brok method:
        - select which broks management functions are to be called
        """
        manage = getattr(self, 'manage_' + brok.type + '_brok', None)
        if manage:
            return manage(brok)

    def manage_initial_host_status_brok(self, brok):
        start = time.clock()
        host_name = brok.data['host_name']
        service_description = ''
        service_id = host_name+"/"+service_description
        logger.debug("[mongo-logs] initial host status received: %s (bi=%d)", host_name, int (brok.data["business_impact"]))

        self.services_cache[service_id] = { "hostname": host_name, "service": service_description }
        logger.info("[mongo-logs] host registered: %s (bi=%d)", service_id, brok.data["business_impact"])

    def manage_host_check_result_brok(self, brok):
        start = time.clock()
        host_name = brok.data['host_name']
        service_description = ''
        service_id = host_name+"/"+service_description
        logger.debug("[mongo-logs] host check result received: %s", service_id)

        if self.services_cache and service_id in self.services_cache:
            self.record_availability(host_name, service_description, brok)
            logger.debug("[mongo-logs] host check result: %s, %.2gs", service_id, time.clock() - start)

    def manage_initial_service_status_brok(self, brok):
        start = time.clock()
        host_name = brok.data['host_name']
        service_description = brok.data['service_description']
        service_id = host_name+"/"+service_description
        logger.debug("[mongo-logs] initial service status received: %s (bi=%d)", host_name, int (brok.data["business_impact"]))

        # Filter service if needed: reference service in services cache ...
        # ... if description filter matches ...
        if self.filter_service_description:
            pat = re.compile(self.filter_service_description, re.IGNORECASE)
            if pat.search(service_id):
                self.services_cache[service_id] = { "hostname": host_name, "service": service_description }
                logger.info("[mongo-logs] service description filter matches for: %s (bi=%d)", service_id, brok.data["business_impact"])

        # ... or if criticality filter matches.
        if self.filter_service_criticality:
            include = False
            bi = int (brok.data["business_impact"])
            if self.filter_service_criticality.startswith('>='):
                if bi >= int(self.filter_service_criticality[2:]):
                    include = True
            elif self.filter_service_criticality.startswith('<='):
                if bi <= int(self.filter_service_criticality[2:]):
                    include = True
            elif self.filter_service_criticality.startswith('>'):
                if bi > int(self.filter_service_criticality[1:]):
                    include = True
            elif self.filter_service_criticality.startswith('<'):
                if bi < int(self.filter_service_criticality[1:]):
                    include = True
            elif self.filter_service_criticality.startswith('='):
                if bi == int(self.filter_service_criticality[1:]):
                    include = True
            if include:
                self.services_cache[service_id] = { "hostname": host_name, "service": service_description }
                logger.info("[mongo-logs] criticality filter matches for: %s (bi=%d)", service_id, brok.data["business_impact"])

    def manage_service_check_result_brok(self, brok):
        start = time.clock()
        host_name = brok.data['host_name']
        service_description = brok.data['service_description']
        service_id = host_name+"/"+service_description
        logger.debug("[mongo-logs] service check result received: %s", service_id)

        if self.services_cache and service_id in self.services_cache:
            self.record_availability(host_name, service_description, brok)
            logger.debug("[mongo-logs] service check result: %s, %.2gs", service_id, time.clock() - start)

    def manage_log_brok(self, brok):
        """
        Parse a Shinken log brok to enqueue a log line for DB insertion
        """
        line = brok.data['log']
        if re.match("^\[[0-9]*\] [A-Z][a-z]*.:", line):
            # Match log which NOT have to be stored
            logger.warning('[mongo-logs] do not store: %s', line)
            return

        logline = Logline(line=line)
        values = logline.as_dict()
        if logline.logclass != LOGCLASS_INVALID:
            logger.debug('[mongo-logs] store log line values: %s', values)
            self.logs_cache.append(values)
        else:
            logger.info("[mongo-logs] This line is invalid: %s", line)

        return

    def record_availability(self, hostname, service, b):
        """
        Parse a Shinken check brok to compute availability and store a daily availability record in the DB

        Main principles:

        Host check brok:
        ----------------
        {'last_time_unreachable': 0, 'last_problem_id': 1, 'check_type': 1, 'retry_interval': 1, 'last_event_id': 1, 'problem_has_been_acknowledged': False, 'last_state': 'DOWN', 'latency': 0, 'last_state_type': 'HARD', 'last_hard_state_change': 1433822140, 'last_time_up': 1433822140, 'percent_state_change': 0.0, 'state': 'UP', 'last_chk': 1433822138, 'last_state_id': 0, 'end_time': 0, 'timeout': 0, 'current_event_id': 1, 'execution_time': 0, 'start_time': 0, 'return_code': 0, 'state_type': 'HARD', 'output': '', 'in_checking': False, 'early_timeout': 0, 'in_scheduled_downtime': False, 'attempt': 1, 'state_type_id': 1, 'acknowledgement_type': 1, 'last_state_change': 1433822140.825969, 'last_time_down': 1433821584, 'instance_id': 0, 'long_output': '', 'current_problem_id': 0, 'host_name': 'sim-0003', 'check_interval': 60, 'state_id': 0, 'has_been_checked': 1, 'perf_data': u''}

        Interesting information ...
        'state_id': 0 / 'state': 'UP' / 'state_type': 'HARD'
        'last_state_id': 0 / 'last_state': 'UP' / 'last_state_type': 'HARD'
        'last_time_unreachable': 0 / 'last_time_up': 1433152221 / 'last_time_down': 0
        'last_chk': 1433152220 / 'last_state_change': 1431420780.184517
        'in_scheduled_downtime': False

        Service check brok:
        -------------------
        {'last_problem_id': 0, 'check_type': 0, 'retry_interval': 2, 'last_event_id': 0, 'problem_has_been_acknowledged': False, 'last_time_critical': 0, 'last_time_warning': 0, 'end_time': 0, 'last_state': 'OK', 'latency': 0.2347090244293213, 'last_time_unknown': 0, 'last_state_type': 'HARD', 'last_hard_state_change': 1433736035, 'percent_state_change': 0.0, 'state': 'OK', 'last_chk': 1433785101, 'last_state_id': 0, 'host_name': u'shinken24', 'has_been_checked': 1, 'check_interval': 5, 'current_event_id': 0, 'execution_time': 0.062339067459106445, 'start_time': 0, 'return_code': 0, 'state_type': 'HARD', 'output': 'Ok : memory consumption is 37%', 'service_description': u'Memory', 'in_checking': False, 'early_timeout': 0, 'in_scheduled_downtime': False, 'attempt': 1, 'state_type_id': 1, 'acknowledgement_type': 1, 'last_state_change': 1433736035.927526, 'instance_id': 0, 'long_output': u'', 'current_problem_id': 0, 'last_time_ok': 1433785103, 'timeout': 0, 'state_id': 0, 'perf_data': u'cached=13%;;;0%;100% buffered=1%;;;0%;100% consumed=37%;80%;90%;0%;100% used=53%;;;0%;100% free=46%;;;0%;100% swap_used=0%;;;0%;100% swap_free=100%;;;0%;100% buffered_abs=36076KB;;;0KB;2058684KB used_abs=1094544KB;;;0KB;2058684KB cached_abs=284628KB;;;0KB;2058684KB consumed_abs=773840KB;;;0KB;2058684KB free_abs=964140KB;;;0KB;2058684KB total_abs=2058684KB;;;0KB;2058684KB swap_total=392188KB;;;0KB;392188KB swap_used=0KB;;;0KB;392188KB swap_free=392188KB;;;0KB;392188KB'}

        Interesting information ...
        'state_id': 0 / 'state': 'OK' / 'state_type': 'HARD'
        'last_state_id': 0 / 'last_state': 'OK' / 'last_state_type': 'HARD'
        'last_time_critical': 0 / 'last_time_warning': 0 / 'last_time_unknown': 0 / 'last_time_ok': 1433785103
        'last_chk': 1433785101 / 'last_state_change': 1433736035.927526
        'in_scheduled_downtime': False
        """
        logger.debug("[mongo-logs] record availability for: %s/%s: %s", hostname, service, b.data['state'])
        logger.debug("[mongo-logs] record availability: %s/%s: %s", hostname, service, b.data)


        # Only for host check at the moment ...
        # if not service is '':
            # logger.warning("[mongo-logs] record availability is only available for hosts checks (%s/%s)", hostname, service)
            # return

        # Ignoring SOFT states ...
        # if b.data['state_type_id']==0:
            # logger.warning("[mongo-logs] record availability for: %s/%s, but no HARD state, ignoring ...", hostname, service)


        # Compute number of seconds today ...
        midnight = datetime.datetime.combine(datetime.date.today(), datetime.time.min)
        midnight_timestamp = time.mktime (midnight.timetuple())
        seconds_today = int(b.data['last_chk']) - midnight_timestamp
        # Scheduled downtime
        scheduled_downtime = bool(b.data['in_scheduled_downtime'])
        # Day
        day = datetime.date.today()
        yesterday = day - datetime.timedelta(days=1)

        # Cache index ...
        query = """%s/%s_%s""" % (hostname, service, day)
        q_day = { "hostname": hostname, "service": service, "day": day.strftime('%Y-%m-%d') }
        q_yesterday = { "hostname": hostname, "service": service, "day": yesterday.strftime('%Y-%m-%d') }

        # Test if record for current day still exists
        exists = False
        try:
            self.availability_cache[query] = self.db[self.hav_collection].find_one( q_day )
            if '_id' in self.availability_cache[query]:
                exists = True
                logger.debug("[mongo-logs] found a today record for: %s", query)

                # Test if yesterday record exists ...
                # TODO: Not yet implemented:
                # - update yesterday with today's first received check will provide a more accurate information.
                # data_yesterday = self.db[self.hav_collection].find_one( q_yesterday )
                # if '_id' in data_yesterday:
                    # exists = True
                    # logger.info("[mongo-logs] found a yesterday record for: %s", query)
        except TypeError, exp:
            logger.debug("[mongo-logs] Exception when querying database - no cache query available: %s", str(exp))
        except Exception, exp:
            logger.error("[mongo-logs] Exception when querying database: %s", str(exp))
            return

        # Configure recorded data
        current_state = b.data['state']
        current_state_id = b.data['state_id']
        last_state = b.data['last_state']
        last_check_state = self.availability_cache[query]['last_check_state'] if exists else 3
        last_check_timestamp = self.availability_cache[query]['last_check_timestamp'] if exists else midnight_timestamp
        since_last_check = 0
        logger.debug("[mongo-logs] current state: %s, last state: %s", current_state, last_state)

        # Host/service check
        last_check = b.data['last_chk']
        since_last_check = int(last_check - last_check_timestamp)

        if exists:
            # Update existing record
            data = self.availability_cache[query]

            # Update record
            if since_last_check > seconds_today:
                # Last state changed before today ...
                # Current state duration for all seconds of today
                data["daily_%d" % data['last_check_state']] = seconds_today
            else:
                # Increase current state duration with seconds since last state
                data["daily_%d" % data['last_check_state']] += (since_last_check)

        else:
            # Create new daily record
            data = {}
            data['hostname'] = hostname
            data['service'] = service
            data['day'] = day.strftime('%Y-%m-%d')
            data['day_ts'] = midnight_timestamp
            data['is_downtime'] = '1' if bool(b.data['in_scheduled_downtime']) else '0'

            # All possible states are 0 seconds duration.
            data['daily_0'] = 0
            data['daily_1'] = 0
            data['daily_2'] = 0
            data['daily_3'] = 0
            data['daily_4'] = 0

            # First check state and timestamp
            data['first_check_state'] = current_state_id
            data['first_check_timestamp'] = int(b.data['last_chk'])

        # Update cache ...
        self.availability_cache[query] = data

        # Unchecked state for all day duration minus all states duration
        data['daily_4'] = 86400
        for value in [ data['daily_0'], data['daily_1'], data['daily_2'], data['daily_3'] ]:
            data['daily_4'] -= int(value)

        # Last check state and timestamp
        data['last_check_state'] = current_state_id
        data['last_check_timestamp'] = int(b.data['last_chk'])

        self.availability_cache[query] = data

        # Store cached values ...
        try:
            logger.debug("[mongo-logs] store for: %s", self.availability_cache[query])
            # self.db[self.hav_collection].save(self.availability_cache[query])
            self.db[self.hav_collection].replace_one( q_day, self.availability_cache[query], upsert=True )
        except AutoReconnect, exp:
            logger.error("[mongo-logs] Autoreconnect exception when updating availability: %s", str(exp))
            self.is_connected = SWITCHING
            # Abort update ... no backlog management currently!
        except Exception, exp:
            self.is_connected = DISCONNECTED
            logger.error("[mongo-logs] Database error occurred: %s", exp)
            raise MongoLogsError

    def main(self):
        self.set_proctitle(self.name)
        self.set_exit_handler()

        db_commit_next_time = time.time()
        db_test_connection = time.time()

        while not self.interrupted:
            logger.debug("[mongo-logs] queue length: %s", self.to_q.qsize())
            now = time.time()

            # DB connection test ?
            if self.db_test_period and db_test_connection < now:
                logger.info("[mongo-logs] Testing database connection ...")
                # Test connection every 5 seconds ...
                db_test_connection = now + self.db_test_period
                if self.is_connected == DISCONNECTED:
                    logger.warning("[mongo-logs] Trying to connect database ...")
                    self.open()

            # Logs commit ?
            if db_commit_next_time < now:
                logger.debug("[mongo-logs] Logs commit time ...")
                # Commit periodically ...
                db_commit_next_time = now + self.commit_period
                self.commit_logs()

            # Logs rotation ?
            if self.next_logs_rotation < now:
                logger.debug("[mongo-logs] Logs rotation time ...")
                self.rotate_logs()

            # Broks management ...
            l = self.to_q.get()
            for b in l:
                b.prepare()
                self.manage_brok(b)

            logger.debug("[mongo-logs] time to manage %s broks (%3.4fs)", len(l), time.time() - now)
