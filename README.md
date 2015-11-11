# Shinken logs MongoDB storage

Shinken broker module used to :
- store Shinken logs in a MongoDB database
- store hosts/services vailability data in a MongoDB database

**No more need for Livestatus to store Shinken logs and hosts availability data!**

**Note:** This module is a must-have for the new Web UI features: host/service history, Shinken activity, hosts availability, ...


## Main features

This module intercepts Shinken logs and analyses each log to store it in MongoDB collection. The logs are then available for an application such as Web UI: see https://github.com/shinken-monitoring/mod-webui.

This module also intercepts Shinken hosts and services checks results to store daily data in MongoDB collection. For each concerned host and service, the data stored allow to have a daily availability for the host/service.

Concerned hosts and services are defined as is:
- host availability is always stored
- service availability is stored depending upon a configurable filter:
    - regexp on the service description
    - rules on the service business impact
For more information see, examples hereunder and configuration file that is documented.

For each host/service, the availability follow the rules:
- one record per service per day
- for each day, 86400 seconds
- first check result received is stored (state and timestamp)
- last check result received is stored (state and timestamp)
- day period outside of first/last check is considered as unchecked (daily_4 seconds)
- each state duration seconds is stored (daily_0, daily_1, daily_2)

With this information it is possible to know how many seconds is spent in a certain state

**Note:** the pros of this method is that is is really a simple and 'real time' time to get availability for an host/service. Np need to parse a huge amount of logs to get some data!

**Note:** the only cons of this method is that it is not very precise ... based on the first/last daily received check, it does not care about the previous day last state!



## Requirements
Use pymongo version > 3.0.

```
   pip install pymongo>=3
```


## Enabling Mongo logs

To use the mongo-logs module you must declare it in your broker configuration.
```
   define broker {
      ...

      modules    	 ..., mongo-logs

   }
```


The module configuration is defined in the file: `mongo-logs.cfg`.

Default configuration needs to be tuned up to your MongoDB configuration.

```
## Module:      mongo-logs
## Loaded by:   Broker
# Store the Shinken logs in a mongodb database
# Store hosts/services availability in a mongodb database
#
# This module is necessary if you intend to use the logs and availability features offered
# by the Shinken WebUI2
#
# -----------------
# IMPORTANT ADVICE:
# -----------------
# If you change the default configuration in this file, you MUST copy the same configuration
# parameters in your webui2.cfg file.
#
# Please note that the max_logs_age parameter is not used in the WebUI
#
define module {
   module_name         mongo-logs
   module_type         mongo-logs

   # MongoDB connection string
   # EXAMPLE
   # To describe a connection to a replica set named test, with the following mongod hosts:
   #   db1.example.net on port 27017 with sysop credentials and
   #   db2.example.net on port 2500.
   # You would use a connection string that resembles the following:
   #   uri     mongodb://sysop:password@db1.example.net,db2.example.net:2500/?replicaSet=test
   #
   # Default is a non replicated localhost server
   #uri                  mongodb://localhost

   # Database name where to store the logs/availability collection
   # Default is shinken
   #database             shinken

   # DB connection test period
   # Every db_test_period seconds, the module tests if the DB connection is alive
   # Default is 0 to skip this test
   #db_test_period    300

   ### ------------------------------------------------------------------------
   ### Logs management
   ### ------------------------------------------------------------------------
   # Logs collection name
   # Default is a collection named logs
   #logs_collection      logs

   # Logs rotation
   #
   # Remove logs older than the specified value
   # Value is specified as :
   # 1d: 1 day
   # 3m: 3 months ...
   # d = days, w = weeks, m = months, y = years
   # Default is 3 months
   #max_logs_age    3m

   # Commit volume
   # The module commits at most commit_volume logs in the DB at every commit period
   # Default is 1000 lines
   #commit_volume     1000

   # Commit period
   # Every commit_period seconds, the module stores the received logs in the DB
   # Default is to commit every 60 seconds
   #commit_period     60

   ### ------------------------------------------------------------------------
   ### Hosts/services availability management
   ### ------------------------------------------------------------------------
   # Hosts/services availability collection name
   # Default is a collection named availability
   #hav_collection      availability

   # Services filtering
   # Filter is declared as a comma separated list of items:
   # An item can be a regexp which is matched against service description (hostname/service)
   #  ^test*, matches all hosts which name starts with test
   #  /test*, matches all services which name starts with test
   #
   # An item containing : is a specific filter (only bi is supported currently)
   #  bi:>x, bi:>=x, bi:<x, bi:<=x, bi:=x to match business impact

   # default is to consider only the services which business impact is > 4
   # 3 is the default value for business impact if property is not explicitely declared
   # Default is only bi>4 (most important services)
   #services_filter bi:>4
}

```

## Doc
### Logs collection

Logs are stored in a collection which default name is *logs*

Each document in the collection contain always the same fields wichever is the stored log line:

- _id: added by mongodb when document is inserted

- type:
    -   INFO, DEBUG, WARNING, ERROR for specific Shinken logs, or
    -   NAGIOS log type (eg. SERVICE ALERT, PASSIVE HOST CHECK, ...)

- logobject: monitoring object concerned by the log line
```
    LOGOBJECT_INFO = 0
    LOGOBJECT_HOST = 1
    LOGOBJECT_SERVICE = 2
    LOGOBJECT_CONTACT = 3
```

- logclass:
```
    LOGCLASS_INFO = 0          # all messages not in any other class
    LOGCLASS_ALERT = 1         # alerts: the change service/host state
    LOGCLASS_PROGRAM = 2       # important program events (restart, ...)
    LOGCLASS_NOTIFICATION = 3  # host/service notifications
    LOGCLASS_PASSIVECHECK = 4  # passive checks
    LOGCLASS_COMMAND = 5       # external commands
    LOGCLASS_STATE = 6         # initial or current states
```
- time: log line UTC timestamp
- message: complete log line message

The following fields are always present but their value are completed depending upon the message logclass value:
- comment
- plugin_output
- attempt
- options
- state_type
- state
- host_name
- service_description
- contact_name
- command_name

Logs stored in the mongodb collection (example):
```
    { "_id" : "shinken-test", "last_test" : 1441968270.48028 } ,
    { "_id" : { "$oid" : "55f118cca5d69827ccea9520" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863874] TIMEPERIOD TRANSITION: workhours;-1;0", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 614, "state" : 0, "host_name" : "", "time" : 1441863874, "service_description" : "", "logobject" : 0, "type" : "TIMEPERIOD TRANSITION", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f118cca5d69827ccea9521" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863870] INFO: [Shinken] OK, all schedulers configurations are dispatched :)\n", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 615, "state" : 0, "host_name" : "", "time" : 1441863870, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f118cca5d69827ccea9522" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863870] INFO: [Shinken] [All] Trying to send configuration to receiver receiver-master", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 616, "state" : 0, "host_name" : "", "time" : 1441863870, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f118eaa5d69827ccea95cf" }, "comment" : "", "plugin_output" : "ERROR : this plugin needs the python-paramiko module. Please install it", "attempt" : 1, "message" : "[1441863885] SERVICE ALERT: pi2;CPU Stats;CRITICAL;SOFT;1;ERROR : this plugin needs the python-paramiko module. Please install it", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 789, "state" : 2, "host_name" : "pi2", "time" : 1441863885, "service_description" : "CPU Stats", "logobject" : 2, "type" : "SERVICE ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f118eaa5d69827ccea95d0" }, "comment" : "", "plugin_output" : "ERROR : this plugin needs the python-paramiko module. Please install it", "attempt" : 1, "message" : "[1441863885] SERVICE ALERT: pi2;Reboot;CRITICAL;SOFT;1;ERROR : this plugin needs the python-paramiko module. Please install it", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 790, "state" : 2, "host_name" : "pi2", "time" : 1441863885, "service_description" : "Reboot", "logobject" : 2, "type" : "SERVICE ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f118eaa5d69827ccea95d1" }, "comment" : "", "plugin_output" : "check_ping: Invalid hostname/address - pi2", "attempt" : 1, "message" : "[1441863885] HOST ALERT: pi2;DOWN;SOFT;1;check_ping: Invalid hostname/address - pi2", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 791, "state" : 1, "host_name" : "pi2", "time" : 1441863885, "service_description" : "", "logobject" : 1, "type" : "HOST ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f118f5a5d69827ccea95d2" }, "comment" : "", "plugin_output" : "check_ping: Invalid hostname/address - pi2", "attempt" : 2, "message" : "[1441863887] HOST ALERT: pi2;DOWN;HARD;2;check_ping: Invalid hostname/address - pi2", "logclass" : 1, "options" : "", "state_type" : "HARD", "lineno" : 792, "state" : 1, "host_name" : "pi2", "time" : 1441863887, "service_description" : "", "logobject" : 1, "type" : "HOST ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f118f5a5d69827ccea95d3" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863887] HOST NOTIFICATION: admin;pi2;DOWN;notify-host-by-email;check_ping: Invalid hostname/address - pi2", "logclass" : 3, "options" : "", "state_type" : "DOWN", "lineno" : 793, "state" : 1, "host_name" : "pi2", "time" : 1441863887, "service_description" : "", "logobject" : 1, "type" : "HOST NOTIFICATION", "contact_name" : "admin", "command_name" : "notify-host-by-email" } ,
    { "_id" : { "$oid" : "55f118f5a5d69827ccea95d4" }, "comment" : "", "plugin_output" : "check_ping: Invalid hostname/address - pi1", "attempt" : 1, "message" : "[1441863895] HOST ALERT: pi1;DOWN;SOFT;1;check_ping: Invalid hostname/address - pi1", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 794, "state" : 1, "host_name" : "pi1", "time" : 1441863895, "service_description" : "", "logobject" : 1, "type" : "HOST ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f118f5a5d69827ccea95d5" }, "comment" : "", "plugin_output" : "ERROR : this plugin needs the python-paramiko module. Please install it", "attempt" : 1, "message" : "[1441863901] SERVICE ALERT: pi1;NET Stats;CRITICAL;SOFT;1;ERROR : this plugin needs the python-paramiko module. Please install it", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 795, "state" : 2, "host_name" : "pi1", "time" : 1441863901, "service_description" : "NET Stats", "logobject" : 2, "type" : "SERVICE ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f118f5a5d69827ccea95d6" }, "comment" : "", "plugin_output" : "check_ping: Invalid hostname/address - pi1", "attempt" : 1, "message" : "[1441863903] HOST ALERT: pi1;DOWN;SOFT;1;check_ping: Invalid hostname/address - pi1", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 796, "state" : 1, "host_name" : "pi1", "time" : 1441863903, "service_description" : "", "logobject" : 1, "type" : "HOST ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f118f5a5d69827ccea95d7" }, "comment" : "", "plugin_output" : "check_ping: Invalid hostname/address - graphite", "attempt" : 1, "message" : "[1441863911] HOST ALERT: graphite;DOWN;SOFT;1;check_ping: Invalid hostname/address - graphite", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 797, "state" : 1, "host_name" : "graphite", "time" : 1441863911, "service_description" : "", "logobject" : 1, "type" : "HOST ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f118f5a5d69827ccea95d8" }, "comment" : "", "plugin_output" : "ERROR : this plugin needs the python-paramiko module. Please install it", "attempt" : 1, "message" : "[1441863915] SERVICE ALERT: pi1;Kernel Stats;CRITICAL;SOFT;1;ERROR : this plugin needs the python-paramiko module. Please install it", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 798, "state" : 2, "host_name" : "pi1", "time" : 1441863915, "service_description" : "Kernel Stats", "logobject" : 2, "type" : "SERVICE ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f118f5a5d69827ccea95d9" }, "comment" : "", "plugin_output" : "check_ping: Invalid hostname/address - pi1", "attempt" : 1, "message" : "[1441863917] HOST ALERT: pi1;DOWN;SOFT;1;check_ping: Invalid hostname/address - pi1", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 799, "state" : 1, "host_name" : "pi1", "time" : 1441863917, "service_description" : "", "logobject" : 1, "type" : "HOST ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f118f5a5d69827ccea95da" }, "comment" : "", "plugin_output" : "ERROR : this plugin needs the python-paramiko module. Please install it", "attempt" : 1, "message" : "[1441863924] SERVICE ALERT: pi1;NFS Stats;CRITICAL;SOFT;1;ERROR : this plugin needs the python-paramiko module. Please install it", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 800, "state" : 2, "host_name" : "pi1", "time" : 1441863924, "service_description" : "NFS Stats", "logobject" : 2, "type" : "SERVICE ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f118ffa5d69827ccea95db" }, "comment" : "", "plugin_output" : "check_ping: Invalid hostname/address - pi1", "attempt" : 1, "message" : "[1441863927] HOST ALERT: pi1;DOWN;SOFT;1;check_ping: Invalid hostname/address - pi1", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 801, "state" : 1, "host_name" : "pi1", "time" : 1441863927, "service_description" : "", "logobject" : 1, "type" : "HOST ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f118ffa5d69827ccea95dc" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863933] INFO: [broker-master] We have our schedulers: {0: {'broks': {}, 'data_timeout': 120, 'name': u'scheduler-master', 'last_connection': 0, 'hard_ssl_name_check': False, 'uri': u'http://localhost:7768/', 'instance_id': 0, 'running_id': 1441863854.7471528, 'timeout': 3, 'address': u'localhost', 'active': True, 'use_ssl': False, 'push_flavor': 138339, 'port': 7768}}", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 802, "state" : 0, "host_name" : "", "time" : 1441863933, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1190aa5d69827ccea968d" }, "comment" : "", "plugin_output" : "check_ping: Invalid hostname/address - pi1", "attempt" : 1, "message" : "[1441863942] HOST ALERT: pi1;DOWN;SOFT;1;check_ping: Invalid hostname/address - pi1", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 979, "state" : 1, "host_name" : "pi1", "time" : 1441863942, "service_description" : "", "logobject" : 1, "type" : "HOST ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1190aa5d69827ccea968e" }, "comment" : "", "plugin_output" : "ERROR : this plugin needs the python-paramiko module. Please install it", "attempt" : 1, "message" : "[1441863944] SERVICE ALERT: pi2;Memory;CRITICAL;SOFT;1;ERROR : this plugin needs the python-paramiko module. Please install it", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 980, "state" : 2, "host_name" : "pi2", "time" : 1441863944, "service_description" : "Memory", "logobject" : 2, "type" : "SERVICE ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f11914a5d69827ccea968f" }, "comment" : "", "plugin_output" : "ERROR : this plugin needs the python-paramiko module. Please install it", "attempt" : 1, "message" : "[1441863946] SERVICE ALERT: pi2;Disks;CRITICAL;SOFT;1;ERROR : this plugin needs the python-paramiko module. Please install it", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 981, "state" : 2, "host_name" : "pi2", "time" : 1441863946, "service_description" : "Disks", "logobject" : 2, "type" : "SERVICE ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f11914a5d69827ccea9690" }, "comment" : "", "plugin_output" : "ERROR : this plugin needs the python-paramiko module. Please install it", "attempt" : 1, "message" : "[1441863947] SERVICE ALERT: pi2;Read-only Filesystems;CRITICAL;SOFT;1;ERROR : this plugin needs the python-paramiko module. Please install it", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 982, "state" : 2, "host_name" : "pi2", "time" : 1441863947, "service_description" : "Read-only Filesystems", "logobject" : 2, "type" : "SERVICE ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f11914a5d69827ccea9691" }, "comment" : "", "plugin_output" : "check_ping: Invalid hostname/address - pi2", "attempt" : 1, "message" : "[1441863947] HOST ALERT: pi2;DOWN;SOFT;1;check_ping: Invalid hostname/address - pi2", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 983, "state" : 1, "host_name" : "pi2", "time" : 1441863947, "service_description" : "", "logobject" : 1, "type" : "HOST ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f11914a5d69827ccea9692" }, "comment" : "", "plugin_output" : "check_ping: Invalid hostname/address - pi2", "attempt" : 1, "message" : "[1441863949] HOST ALERT: pi2;DOWN;SOFT;1;check_ping: Invalid hostname/address - pi2", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 984, "state" : 1, "host_name" : "pi2", "time" : 1441863949, "service_description" : "", "logobject" : 1, "type" : "HOST ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f11914a5d69827ccea9693" }, "comment" : "", "plugin_output" : "check_ping: Invalid hostname/address - pi2", "attempt" : 1, "message" : "[1441863951] HOST ALERT: pi2;DOWN;SOFT;1;check_ping: Invalid hostname/address - pi2", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 985, "state" : 1, "host_name" : "pi2", "time" : 1441863951, "service_description" : "", "logobject" : 1, "type" : "HOST ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1191ea5d69827ccea9694" }, "comment" : "", "plugin_output" : "ERROR : this plugin needs the python-paramiko module. Please install it", "attempt" : 1, "message" : "[1441863965] SERVICE ALERT: pi2;Load Average;CRITICAL;SOFT;1;ERROR : this plugin needs the python-paramiko module. Please install it", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 986, "state" : 2, "host_name" : "pi2", "time" : 1441863965, "service_description" : "Load Average", "logobject" : 2, "type" : "SERVICE ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f11929a5d69827ccea9695" }, "comment" : "", "plugin_output" : "check_ping: Invalid hostname/address - pi2", "attempt" : 1, "message" : "[1441863967] HOST ALERT: pi2;DOWN;SOFT;1;check_ping: Invalid hostname/address - pi2", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 987, "state" : 1, "host_name" : "pi2", "time" : 1441863967, "service_description" : "", "logobject" : 1, "type" : "HOST ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f11929a5d69827ccea9696" }, "comment" : "", "plugin_output" : "ERROR : this plugin needs the python-paramiko module. Please install it", "attempt" : 1, "message" : "[1441863973] SERVICE ALERT: pi2;Disks Stats;CRITICAL;SOFT;1;ERROR : this plugin needs the python-paramiko module. Please install it", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 988, "state" : 2, "host_name" : "pi2", "time" : 1441863973, "service_description" : "Disks Stats", "logobject" : 2, "type" : "SERVICE ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f11929a5d69827ccea9697" }, "comment" : "", "plugin_output" : "check_ping: Invalid hostname/address - pi2", "attempt" : 1, "message" : "[1441863976] HOST ALERT: pi2;DOWN;SOFT;1;check_ping: Invalid hostname/address - pi2", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 989, "state" : 1, "host_name" : "pi2", "time" : 1441863976, "service_description" : "", "logobject" : 1, "type" : "HOST ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea9698" }, "comment" : "", "plugin_output" : "ERROR : this plugin needs the python-paramiko module. Please install it", "attempt" : 1, "message" : "[1441863988] SERVICE ALERT: pi1;NFS Stats;CRITICAL;SOFT;1;ERROR : this plugin needs the python-paramiko module. Please install it", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 990, "state" : 2, "host_name" : "pi1", "time" : 1441863988, "service_description" : "NFS Stats", "logobject" : 2, "type" : "SERVICE ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea9699" }, "comment" : "", "plugin_output" : "check_ping: Invalid hostname/address - pi2", "attempt" : 2, "message" : "[1441863990] HOST ALERT: pi2;DOWN;HARD;2;check_ping: Invalid hostname/address - pi2", "logclass" : 1, "options" : "", "state_type" : "HARD", "lineno" : 991, "state" : 1, "host_name" : "pi2", "time" : 1441863990, "service_description" : "", "logobject" : 1, "type" : "HOST ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea969a" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863990] HOST NOTIFICATION: admin;pi2;DOWN;notify-host-by-email;check_ping: Invalid hostname/address - pi2", "logclass" : 3, "options" : "", "state_type" : "DOWN", "lineno" : 992, "state" : 1, "host_name" : "pi2", "time" : 1441863990, "service_description" : "", "logobject" : 1, "type" : "HOST NOTIFICATION", "contact_name" : "admin", "command_name" : "notify-host-by-email" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea969b" }, "comment" : "", "plugin_output" : "check_ping: Invalid hostname/address - pi1", "attempt" : 1, "message" : "[1441863991] HOST ALERT: pi1;DOWN;SOFT;1;check_ping: Invalid hostname/address - pi1", "logclass" : 1, "options" : "", "state_type" : "SOFT", "lineno" : 993, "state" : 1, "host_name" : "pi1", "time" : 1441863991, "service_description" : "", "logobject" : 1, "type" : "HOST ALERT", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea969c" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863993] INFO: [Shinken] [reactionner-master] We already got the conf 0 (scheduler-master)", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 994, "state" : 0, "host_name" : "", "time" : 1441863993, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea969d" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863993] INFO: [Shinken] [reactionner-master] Using max workers: 15", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 995, "state" : 0, "host_name" : "", "time" : 1441863993, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea969e" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863993] INFO: [Shinken] [reactionner-master] Using min workers: 1", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 996, "state" : 0, "host_name" : "", "time" : 1441863993, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea969f" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863993] INFO: [Shinken] We have our schedulers: {0: {'wait_homerun': {}, 'data_timeout': 120, 'name': u'scheduler-master', 'hard_ssl_name_check': False, 'uri': u'http://localhost:7768/', 'actions': {}, 'instance_id': 0, 'running_id': 0, 'timeout': 3, 'address': u'localhost', 'active': True, 'use_ssl': False, 'push_flavor': 797380, 'port': 7768}}\n", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 997, "state" : 0, "host_name" : "", "time" : 1441863993, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea96a0" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863993] INFO: [Shinken] [reactionner-master] Init connection with scheduler-master at http://localhost:7768/ (3s,120s)", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 998, "state" : 0, "host_name" : "", "time" : 1441863993, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea96a1" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863993] INFO: [Shinken] [reactionner-master] Connection OK with scheduler scheduler-master", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 999, "state" : 0, "host_name" : "", "time" : 1441863993, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea96a2" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863993] INFO: [broker-master] We have our schedulers: {0: {'broks': {}, 'data_timeout': 120, 'name': u'scheduler-master', 'last_connection': 0, 'hard_ssl_name_check': False, 'uri': u'http://localhost:7768/', 'instance_id': 0, 'running_id': 1441863854.7471528, 'timeout': 3, 'address': u'localhost', 'active': True, 'use_ssl': False, 'push_flavor': 797380, 'port': 7768}}", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 1000, "state" : 0, "host_name" : "", "time" : 1441863993, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea96a3" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863993] INFO: [broker-master] We have our schedulers: {0: {'broks': {}, 'data_timeout': 120, 'name': u'scheduler-master', 'last_connection': 0, 'hard_ssl_name_check': False, 'uri': u'http://localhost:7768/', 'instance_id': 0, 'running_id': 1441863854.7471528, 'timeout': 3, 'address': u'localhost', 'active': True, 'use_ssl': False, 'push_flavor': 797380, 'port': 7768}}", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 1001, "state" : 0, "host_name" : "", "time" : 1441863993, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea96a4" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863993] INFO: [broker-master] We have our schedulers: {0: {'broks': {}, 'data_timeout': 120, 'name': u'scheduler-master', 'last_connection': 0, 'hard_ssl_name_check': False, 'uri': u'http://localhost:7768/', 'instance_id': 0, 'running_id': 1441863854.7471528, 'timeout': 3, 'address': u'localhost', 'active': True, 'use_ssl': False, 'push_flavor': 797380, 'port': 7768}}", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 1002, "state" : 0, "host_name" : "", "time" : 1441863993, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea96a5" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863993] INFO: [broker-master] We have our schedulers: {0: {'broks': {}, 'data_timeout': 120, 'name': u'scheduler-master', 'last_connection': 0, 'hard_ssl_name_check': False, 'uri': u'http://localhost:7768/', 'instance_id': 0, 'running_id': 1441863854.7471528, 'timeout': 3, 'address': u'localhost', 'active': True, 'use_ssl': False, 'push_flavor': 797380, 'port': 7768}}", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 1003, "state" : 0, "host_name" : "", "time" : 1441863993, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea96a6" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863993] INFO: [broker-master] We have our schedulers: {0: {'broks': {}, 'data_timeout': 120, 'name': u'scheduler-master', 'last_connection': 0, 'hard_ssl_name_check': False, 'uri': u'http://localhost:7768/', 'instance_id': 0, 'running_id': 1441863854.7471528, 'timeout': 3, 'address': u'localhost', 'active': True, 'use_ssl': False, 'push_flavor': 797380, 'port': 7768}}", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 1004, "state" : 0, "host_name" : "", "time" : 1441863993, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea96a7" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863993] INFO: [broker-master] We have our schedulers: {0: {'broks': {}, 'data_timeout': 120, 'name': u'scheduler-master', 'last_connection': 0, 'hard_ssl_name_check': False, 'uri': u'http://localhost:7768/', 'instance_id': 0, 'running_id': 1441863854.7471528, 'timeout': 3, 'address': u'localhost', 'active': True, 'use_ssl': False, 'push_flavor': 797380, 'port': 7768}}", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 1005, "state" : 0, "host_name" : "", "time" : 1441863993, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea96a8" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863993] INFO: [broker-master] We have our arbiters: {0: {'broks': {}, 'last_connection': 0, 'name': u'arbiter-master', 'hard_ssl_name_check': False, 'uri': u'http://localhost:7770/', 'instance_id': 0, 'running_id': 0, 'address': u'localhost', 'use_ssl': False, 'port': 7770}}", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 1006, "state" : 0, "host_name" : "", "time" : 1441863993, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
    { "_id" : { "$oid" : "55f1193ea5d69827ccea96a9" }, "comment" : "", "plugin_output" : "", "attempt" : 0, "message" : "[1441863993] INFO: [broker-master] We have our arbiters: {0: {'broks': {}, 'last_connection': 0, 'name': u'arbiter-master', 'hard_ssl_name_check': False, 'uri': u'http://localhost:7770/', 'instance_id': 0, 'running_id': 0, 'address': u'localhost', 'use_ssl': False, 'port': 7770}}", "logclass" : 2, "options" : "", "state_type" : "", "lineno" : 1007, "state" : 0, "host_name" : "", "time" : 1441863993, "service_description" : "", "logobject" : 0, "type" : "INFO", "contact_name" : "", "command_name" : "" } ,
```

### Availability collection

Hosts/services daily availability are stored in a collection which default name is *availability*

Each document in the collection contain always the same fields:

- _id: added by mongodb when document is inserted

- first_check_state: state of first received check for the day
- first_check_timestamp: timestamp of first received check
- last_check_state: state of last received check for the day
- last_check_timestamp: timestamp of last received check
- day_ts: timestamp for 00:00 of the day
- day: day in YYYY-MM-DD format
- hostname: hostname
- service: service description (empty for host check)
- daily_0: number of seconds in state 0 (UP/OK)
- daily_1: number of seconds in state 1 (DOWN/WARNING)
- daily_2: number of seconds in state 2 (UNREACHABLE/CRITICAL)
- daily_3: number of seconds in state 3 (UNKNOWN)
- daily_4: number of seconds in state 4 (OTHER) - unchecked period ...
- is_downtime: currently in downtime

Example:
```
    { "_id" : { "$oid" : "55f118eac4e7774e6d845809" }, "first_check_state" : 1, "day_ts" : 1441836000, "service" : "", "first_check_timestamp" : 1441863885, "daily_4" : 59028, "hostname" : "pi2", "daily_1" : 27372, "daily_0" : 0, "daily_3" : 0, "daily_2" : 0, "is_downtime" : "0", "last_check_timestamp" : 1441891257, "day" : "2015-09-10", "last_check_state" : 1 } ,
    { "_id" : { "$oid" : "55f118eac4e7774e6d84580a" }, "first_check_state" : 1, "day_ts" : 1441836000, "service" : "", "first_check_timestamp" : 1441863894, "daily_4" : 59044, "hostname" : "pi1", "daily_1" : 27356, "daily_0" : 0, "daily_3" : 0, "daily_2" : 0, "is_downtime" : "0", "last_check_timestamp" : 1441891250, "day" : "2015-09-10", "last_check_state" : 1 } ,
    { "_id" : { "$oid" : "55f118eac4e7774e6d84580b" }, "first_check_state" : 1, "day_ts" : 1441836000, "service" : "", "first_check_timestamp" : 1441863910, "daily_4" : 59728, "hostname" : "graphite", "daily_1" : 26672, "daily_0" : 0, "daily_3" : 0, "daily_2" : 0, "is_downtime" : "0", "last_check_timestamp" : 1441890582, "day" : "2015-09-10", "last_check_state" : 1 } ,
    { "_id" : { "$oid" : "55f118ebc4e7774e6d84580c" }, "first_check_state" : 0, "day_ts" : 1441836000, "service" : "", "first_check_timestamp" : 1441863912, "daily_4" : 59273, "hostname" : "webui", "daily_1" : 0, "daily_0" : 27127, "daily_3" : 0, "daily_2" : 0, "is_downtime" : "0", "last_check_timestamp" : 1441891039, "day" : "2015-09-10", "last_check_state" : 0 } ,
    { "_id" : { "$oid" : "55f1289a72777c74656f0d56" }, "first_check_state" : 0, "day_ts" : 1441836000, "service" : "", "first_check_timestamp" : 1441867909, "daily_4" : 83545, "hostname" : "localhost", "daily_1" : 0, "daily_0" : 2855, "daily_3" : 0, "daily_2" : 0, "is_downtime" : "0", "last_check_timestamp" : 1441870764, "day" : "2015-09-10", "last_check_state" : 0 }
```
