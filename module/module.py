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


from pymongo import Connection
try:
    from pymongo import ReplicaSetConnection, ReadPreference
except ImportError:
    ReplicaSetConnection = None
    ReadPreference = None
from pymongo.errors import AutoReconnect

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
        self.plugins = []
        # mongodb://host1,host2,host3/?safe=true;w=2;wtimeoutMS=2000
        self.mongodb_uri = getattr(modconf, 'mongodb_uri', None)
        logger.info('[mongo-logs] mongo uri: %s' % self.mongodb_uri)
        self.mongodb_host = getattr(modconf, 'mongodb_host', 'localhost')
        self.mongodb_port = int(getattr(modconf, 'mongodb_port', '27017'))
        logger.info("[mongo-logs] mongodb host:port: %s:%d", self.mongodb_host, self.mongodb_port)
        self.replica_set = getattr(modconf, 'replica_set', None)
        if self.replica_set and not ReplicaSetConnection:
            logger.error('[mongo-logs] Can not initialize LogStoreMongoDB module with '
                         'replica_set because your pymongo lib is too old. '
                         'Please install it with a 2.x+ version from '
                         'https://github.com/mongodb/mongo-python-driver/downloads')
            return None
        self.database = getattr(modconf, 'database', 'logs')
        logger.info('[mongo-logs] database: %s' % self.database)
        self.collection = getattr(modconf, 'collection', 'logs')
        logger.info('[mongo-logs] collection: %s' % self.collection)
        self.use_aggressive_sql = True
        self.mongodb_fsync = to_bool(getattr(modconf, 'mongodb_fsync', "True"))
        max_logs_age = getattr(modconf, 'max_logs_age', '365')
        maxmatch = re.match(r'^(\d+)([dwmy]*)$', max_logs_age)
        if maxmatch is None:
            logger.info('[mongo-logs] Wrong format for max_logs_age. Must be <number>[d|w|m|y] or <number> and not %s' % max_logs_age)
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
        logger.info('[mongo-logs] max_logs_age: %s' % self.max_logs_age)
        self.use_aggressive_sql = (getattr(modconf, 'use_aggressive_sql', '1') == '1')
        # This stack is used to create a full-blown select-statement
        # self.mongo_filter_stack = LiveStatusMongoStack()
        # This stack is used to create a minimal select-statement which
        # selects only by time >= and time <=
        # self.mongo_time_filter_stack = LiveStatusMongoStack()
        self.is_connected = DISCONNECTED
        self.backlog = []
        # Now sleep one second, so that won't get lineno collisions with the last second
        time.sleep(1)
        self.lineno = 0

    def load(self, app):
        self.app = app

    def init(self):
        self.open()

    def open(self):
        try:
            if self.replica_set:
                self.conn = pymongo.ReplicaSetConnection(self.mongodb_uri, replicaSet=self.replica_set, fsync=self.mongodb_fsync)
            else:
                # Old versions of pymongo do not known about fsync
                if ReplicaSetConnection:
                    self.conn = pymongo.Connection(self.mongodb_uri, fsync=self.mongodb_fsync)
                else:
                    self.conn = pymongo.Connection(self.mongodb_uri)
            logger.info("[mongo-logs] connected to mongodb: %s", self.mongodb_uri)
            
            self.db = self.conn[self.database]
            logger.info("[mongo-logs] connected to the database: %s", self.database)
            
            self.db[self.collection].ensure_index([('host_name', pymongo.ASCENDING), ('time', pymongo.ASCENDING), ('lineno', pymongo.ASCENDING)], name='logs_idx')
            self.db[self.collection].ensure_index([('time', pymongo.ASCENDING), ('lineno', pymongo.ASCENDING)], name='time_1_lineno_1')
            
            if self.replica_set:
                pass
                # This might be a future option prefer_secondary
                #self.db.read_preference = ReadPreference.SECONDARY
            self.is_connected = CONNECTED
            self.next_log_db_rotate = time.time()
            logger.info('[mongo-logs] database connection established')
        except AutoReconnect, exp:
            # now what, ha?
            logger.error("[mongo-logs] MongoLogs.AutoReconnect: %s" % (exp))
            # The mongodb is hopefully available until this module is restarted
            raise MongoLogsError
        except Exception, exp:
            # If there is a replica_set, but the host is a simple standalone one
            # we get a "No suitable hosts found" here.
            # But other reasons are possible too.
            logger.error("[mongo-logs] Could not open the database" % exp)
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
            self.db[self.collection].remove({u'time': {'$lt': time.mktime(oldest.timetuple())}})
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
                self.db[self.collection].insert(values)
                self.is_connected = CONNECTED
                # If we have a backlog from an outage, we flush these lines
                # First we make a copy, so we can delete elements from
                # the original self.backlog
                backloglines = [bl for bl in self.backlog]
                for backlogline in backloglines:
                    try:
                        self.db[self.collection].insert(backlogline)
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


    def main(self):
        self.set_proctitle(self.name)
        self.set_exit_handler()
        while not self.interrupted:
            l = self.to_q.get()
            for b in l:
                b.prepare()
                self.manage_brok(b)
