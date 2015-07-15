#!/usr/bin/python

# -*- coding: utf-8 -*-

# Copyright (C) 2009-2012:
#    Gabes Jean, naparuba@gmail.com
#    Gerhard Lausser, Gerhard.Lausser@consol.de
#    Gregory Starck, g.starck@gmail.com
#    Hartmut Goebel, h.goebel@goebel-consult.de
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
    logger.error('[MongoDB Module] Can not import pymongo and/or MongoClient'
                 'Your pymongo lib is too old. '
                 'Please install it with a 3.x+ version from '
                 'https://pypi.python.org/pypi/pymongo')
    MongoClient = None

from shinken.basemodule import BaseModule
from shinken.objects.module import Module
from shinken.log import logger
from shinken.util import to_bool

properties = {
    'daemons': ['broker'],
    'type': 'mongo-logs',
    'external': True,
    'phases': ['running'],
    }


# called by the plugin manager
def get_instance(plugin):
    logger.info("[mongo-logs] Get an LogStore MongoDB module for plugin %s" % plugin.get_name())
    instance = MongoLogs(plugin)
    return instance


def row_factory(cursor, row):
    """Handler for the sqlite fetch method."""
    return Logline(cursor.description, row)

CONNECTED = 1
DISCONNECTED = 2
SWITCHING = 3


class MongoLogsError(Exception):
    pass


class MongoLogs(BaseModule):

    def __init__(self, modconf):
        BaseModule.__init__(self, modconf)

        self.uri = getattr(modconf, 'uri', None)
        logger.info('[mongo-logs] mongo uri: %s', self.uri)
        
        self.replica_set = getattr(modconf, 'replica_set', None)
        if self.replica_set and int(pymongo.version[0]) < 3:
            logger.error('[MongoDB Module] Can not initialize module with '
                         'replica_set because your pymongo lib is too old. '
                         'Please install it with a 3.x+ version from '
                         'https://pypi.python.org/pypi/pymongo')
            return None

        self.database = getattr(modconf, 'database', 'shinken')
        logger.info('[mongo-logs] database: %s', self.database)
        
        self.username = getattr(modconf, 'username', None)
        self.password = getattr(modconf, 'password', None)
        
        self.logs_collection = getattr(modconf, 'logs_collection', 'logs')
        logger.info('[mongo-logs] collection: %s', self.logs_collection)
        
        self.hav_collection = getattr(modconf, 'hav_collection', 'logs')
        logger.info('[mongo-logs] hosts availability collection: %s', self.hav_collection)
        
        self.mongodb_fsync = to_bool(getattr(modconf, 'mongodb_fsync', "True"))
        
        max_logs_age = getattr(modconf, 'max_logs_age', '365')
        maxmatch = re.match(r'^(\d+)([dwmy]*)$', max_logs_age)
        if maxmatch is None:
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

        self.is_connected = DISCONNECTED
        self.backlog = []
        
        # Now sleep one second, so that won't get lineno collisions with the last second
        time.sleep(1)
        self.lineno = 0
        
        self.cache = {}
        self.cache_backlog = []

    def load(self, app):
        self.app = app

    def init(self):
        self.open()

    def open(self):
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
            self.next_log_db_rotate = time.time()
            
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
        self.conn.disconnect()

    def commit(self):
        pass

    def commit_and_rotate_log_db(self):
        """For a MongoDB there is no rotate, but we will delete old contents."""
        now = time.time()
        if self.next_log_db_rotate <= now:
            logger.info("[mongo-logs] rotating logs ...")
            
            today = datetime.date.today()
            today0000 = datetime.datetime(today.year, today.month, today.day, 0, 0, 0)
            today0005 = datetime.datetime(today.year, today.month, today.day, 0, 5, 0)
            oldest = today0000 - datetime.timedelta(days=self.max_logs_age)
            self.db[self.logs_collection].remove({u'time': {'$lt': time.mktime(oldest.timetuple())}})
            logger.info("[mongo-logs] removed logs older than %s days.", self.max_logs_age)

            if now < time.mktime(today0005.timetuple()):
                nextrotation = today0005
            else:
                nextrotation = today0005 + datetime.timedelta(days=1)

            # See you tomorrow
            self.next_log_db_rotate = time.mktime(nextrotation.timetuple())
            logger.info("[mongo-logs] Next log rotation at %s " % time.asctime(time.localtime(self.next_log_db_rotate)))


    def manage_log_brok(self, b):
        data = b.data
        line = data['log']
        if re.match("^\[[0-9]*\] [A-Z][a-z]*.:", line):
            # Match log which NOT have to be stored
            logger.warning('[mongo-logs] do not store: %s', line)
            return
            
        logline = Logline(line=line)
        values = logline.as_dict()
        if logline.logclass != LOGCLASS_INVALID:
            logger.debug('[mongo-logs] store values: %s', values)
            try:
                self.db[self.logs_collection].insert(values)
                self.is_connected = CONNECTED
                # If we have a backlog from an outage, we flush these lines
                # First we make a copy, so we can delete elements from
                # the original self.backlog
                backloglines = [bl for bl in self.backlog]
                for backlogline in backloglines:
                    try:
                        self.db[self.logs_collection].insert(backlogline)
                        self.backlog.remove(backlogline)
                    except AutoReconnect, exp:
                        self.is_connected = SWITCHING
                    except Exception, exp:
                        logger.error("[mongo-logs] Got an exception inserting the backlog: %s", str(exp))
            except AutoReconnect, exp:
                if self.is_connected != SWITCHING:
                    self.is_connected = SWITCHING
                    time.sleep(5)
                    # Under normal circumstances after these 5 seconds
                    # we should have a new primary node
                else:
                    # Not yet? Wait, but try harder.
                    time.sleep(0.1)
                # At this point we must save the logline for a later attempt
                # After 5 seconds we either have a successful write
                # or another exception which means, we are disconnected
                self.backlog.append(values)
            except Exception, exp:
                self.is_connected = DISCONNECTED
                logger.error("[mongo-logs] Database error occurred: %s", exp)
                raise MongoLogsError
        else:
            logger.info("[mongo-logs] This line is invalid: %s", line)

    def manage_host_check_result_brok(self, b):
        host_name = b.data['host_name']
        logger.debug("[mongo-logs] host check result: %s is %s", host_name, b.data['state'])
        start = time.time()
        self.record_availability(host_name, '', b)
        logger.debug("[mongo-logs] host check result: %s, %d seconds", host_name, time.time() - start)
        
    ## Update hosts/services availability
    def record_availability(self, hostname, service, b):
        # Insert/update in shinken state table
        logger.debug("[mongo-logs] record availability: %s/%s: %s", hostname, service, b.data)
            
        # Host check brok:
        # ----------------
        # {'last_time_unreachable': 0, 'last_problem_id': 1, 'check_type': 1, 'retry_interval': 1, 'last_event_id': 1, 'problem_has_been_acknowledged': False, 'last_state': 'DOWN', 'latency': 0, 'last_state_type': 'HARD', 'last_hard_state_change': 1433822140, 'last_time_up': 1433822140, 'percent_state_change': 0.0, 'state': 'UP', 'last_chk': 1433822138, 'last_state_id': 0, 'end_time': 0, 'timeout': 0, 'current_event_id': 1, 'execution_time': 0, 'start_time': 0, 'return_code': 0, 'state_type': 'HARD', 'output': '', 'in_checking': False, 'early_timeout': 0, 'in_scheduled_downtime': False, 'attempt': 1, 'state_type_id': 1, 'acknowledgement_type': 1, 'last_state_change': 1433822140.825969, 'last_time_down': 1433821584, 'instance_id': 0, 'long_output': '', 'current_problem_id': 0, 'host_name': 'sim-0003', 'check_interval': 60, 'state_id': 0, 'has_been_checked': 1, 'perf_data': u''}
        #
        # Interesting information ...
        # 'state_id': 0 / 'state': 'UP' / 'state_type': 'HARD'
        # 'last_state_id': 0 / 'last_state': 'UP' / 'last_state_type': 'HARD'
        # 'last_time_unreachable': 0 / 'last_time_up': 1433152221 / 'last_time_down': 0
        # 'last_chk': 1433152220 / 'last_state_change': 1431420780.184517
        # 'in_scheduled_downtime': False
        
        # Service check brok:
        # -------------------
        # {'last_problem_id': 0, 'check_type': 0, 'retry_interval': 2, 'last_event_id': 0, 'problem_has_been_acknowledged': False, 'last_time_critical': 0, 'last_time_warning': 0, 'end_time': 0, 'last_state': 'OK', 'latency': 0.2347090244293213, 'last_time_unknown': 0, 'last_state_type': 'HARD', 'last_hard_state_change': 1433736035, 'percent_state_change': 0.0, 'state': 'OK', 'last_chk': 1433785101, 'last_state_id': 0, 'host_name': u'shinken24', 'has_been_checked': 1, 'check_interval': 5, 'current_event_id': 0, 'execution_time': 0.062339067459106445, 'start_time': 0, 'return_code': 0, 'state_type': 'HARD', 'output': 'Ok : memory consumption is 37%', 'service_description': u'Memory', 'in_checking': False, 'early_timeout': 0, 'in_scheduled_downtime': False, 'attempt': 1, 'state_type_id': 1, 'acknowledgement_type': 1, 'last_state_change': 1433736035.927526, 'instance_id': 0, 'long_output': u'', 'current_problem_id': 0, 'last_time_ok': 1433785103, 'timeout': 0, 'state_id': 0, 'perf_data': u'cached=13%;;;0%;100% buffered=1%;;;0%;100% consumed=37%;80%;90%;0%;100% used=53%;;;0%;100% free=46%;;;0%;100% swap_used=0%;;;0%;100% swap_free=100%;;;0%;100% buffered_abs=36076KB;;;0KB;2058684KB used_abs=1094544KB;;;0KB;2058684KB cached_abs=284628KB;;;0KB;2058684KB consumed_abs=773840KB;;;0KB;2058684KB free_abs=964140KB;;;0KB;2058684KB total_abs=2058684KB;;;0KB;2058684KB swap_total=392188KB;;;0KB;392188KB swap_used=0KB;;;0KB;392188KB swap_free=392188KB;;;0KB;392188KB'}
        #
        # Interesting information ...
        # 'state_id': 0 / 'state': 'OK' / 'state_type': 'HARD'
        # 'last_state_id': 0 / 'last_state': 'OK' / 'last_state_type': 'HARD'
        # 'last_time_critical': 0 / 'last_time_warning': 0 / 'last_time_unknown': 0 / 'last_time_ok': 1433785103
        # 'last_chk': 1433785101 / 'last_state_change': 1433736035.927526
        # 'in_scheduled_downtime': False
        
        # Only for simulated hosts ...
        # if not hostname.startswith('kiosk-0001'):
            # return
            
        # Only for host check at the moment ...
        if not service is '':
            return
            
        # Ignoring SOFT states ...
        # if b.data['state_type_id']==0:
            # logger.warning("[mongo-logs] record availability for: %s/%s, but no HARD state, ignoring ...", hostname, service)
        
        
        midnight = datetime.datetime.combine(datetime.date.today(), datetime.time.min)
        midnight_timestamp = time.mktime (midnight.timetuple())
        # Number of seconds today ...
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
            self.cache[query] = self.db[self.hav_collection].find_one( q_day )
            if '_id' in self.cache[query]:
                exists = True
                logger.debug("[mongo-logs] found a today record for: %s", query)
                
                # Test if yesterday record exists ...
                # data_yesterday = self.db[self.hav_collection].find_one( q_yesterday )
                # if '_id' in data_yesterday:
                    # exists = True
                    # logger.info("[mongo-logs] found a yesterday record for: %s", query)
        except Exception, exp:
            logger.error("[mongo-logs] Exception when querying database: %s", str(exp))
            # return
        
        # Configure recorded data
        current_state = b.data['state']
        current_state_id = b.data['state_id']
        last_state = b.data['last_state']
        last_check_state = self.cache[query]['last_check_state'] if exists else 3
        last_check_timestamp = self.cache[query]['last_check_timestamp'] if exists else midnight_timestamp
        since_last_check = 0
        logger.debug("[mongo-logs] current state: %s, last state: %s", current_state, last_state)
        
        # Host check
        if service=='':
            last_time_unreachable = b.data['last_time_unreachable']
            last_time_up = b.data['last_time_up']
            last_time_down = b.data['last_time_down']
            last_state_change = b.data['last_state_change']
            last_check = b.data['last_chk']
            since_last_check = int(last_check - last_check_timestamp)
            
            # if current_state == 'UP':
                # since_last_check = int(last_check - last_check_timestamp)
                    
            # elif current_state== 'UNREACHABLE':
                # since_last_check = int(last_check - last_check_timestamp)
                    
            # elif current_state == 'DOWN':
                # since_last_check = int(last_check - last_check_timestamp)

        # Service check
        # else:
            # To be implemented !!!
            # if hostname.startswith('kiosk-0001'):
                # logger.warning("[mongo-logs] last_state_change: %d", last_state_change)
                # logger.warning("[mongo-logs] last_time_unknown: %d", b.data['last_time_unknown'])
                # logger.warning("[mongo-logs] last_time_ok: %d", b.data['last_time_ok'])
                # logger.warning("[mongo-logs] last_time_warning: %d", b.data['last_time_warning'])
                # logger.warning("[mongo-logs] last_time_critical: %d", b.data['last_time_critical'])
        
        if exists:
            # Update existing record
            data = self.cache[query]

            # Update record
            if since_last_check > seconds_today:
                # Last state changed before today ...
                # Current state duration for all seconds of today
                data["daily_%d" % data['last_check_state']] = seconds_today
            else:
                # Increase current state duration with seconds since last state
                data["daily_%d" % data['last_check_state']] += (since_last_check)
            
        else:
            # Create record
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
        self.cache[query] = data

        # Unchecked state for all day duration minus all states duration
        data['daily_4'] = 86400
        for value in [ data['daily_0'], data['daily_1'], data['daily_2'], data['daily_3'] ]:
            data['daily_4'] -= int(value)
        
        # Last check state and timestamp
        data['last_check_state'] = current_state_id
        data['last_check_timestamp'] = int(b.data['last_chk'])
        
        self.cache[query] = data
            
        # Store cached values ...
        try:
            logger.warning("[mongo-logs] store for: %s", self.cache[query])
            self.db[self.hav_collection].save(self.cache[query])
                
            self.is_connected = CONNECTED
            # If we have a backlog from an outage, we flush these lines
            # First we make a copy, so we can delete elements from
            # the original cache backlog
            backloglines = [bl for bl in self.cache_backlog]
            for backlogline in backloglines:
                try:
                    self.db[self.hav_collection].insert(backlogline)
                    self.cache_backlog.remove(backlogline)
                except AutoReconnect, exp:
                    self.is_connected = SWITCHING
                except Exception, exp:
                    logger.error("[mongo-logs] Got an exception inserting the availability backlog: %s", str(exp))
        except AutoReconnect, exp:
            if self.is_connected != SWITCHING:
                self.is_connected = SWITCHING
                time.sleep(5)
                # Under normal circumstances after these 5 seconds
                # we should have a new primary node
            else:
                # Not yet? Wait, but try harder.
                time.sleep(0.1)
            # At this point we must save the logline for a later attempt
            # After 5 seconds we either have a successful write
            # or another exception which means, we are disconnected
            self.cache_backlog.append(self.cache[query])
            
        except Exception, exp:
            self.is_connected = DISCONNECTED
            logger.error("[mongo-logs] Database error occurred: %s", exp)
            raise MongoLogsError

    def main(self):
        self.set_proctitle(self.name)
        self.set_exit_handler()
        
        db_commit_next_time = time.time()

        while not self.interrupted:
            now = time.time()

            if db_commit_next_time < now:
                # Commit every 5 seconds ...
                db_commit_next_time = now + 5
                self.commit_and_rotate_log_db()

            l = self.to_q.get()
            for b in l:
                b.prepare()
                self.manage_brok(b)
