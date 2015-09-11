.. _mongo_logs_module:

===========================
Mongo logs module
===========================


This broker module to store Shinken logs in a MongoDB database. It also allows to store availability data for hosts and/or services.

No more need for Livestatus to store Shinken logs and hosts/services availability data! 

This module is a must-have for some Shinken Web UI features: host/service history, Shinken activity, hosts availability, ...



Requirements 
=============

The current version needs: 
 - python pymongo library, at least version 3


Enabling module 
=============================

To use the mongo-logs module you must declare it in your broker configuration.

::
   define broker {
      ... 

      modules    	 ..., mongo-logs

   }


The module configuration is defined in the file: mongo-logs.cfg.


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
   
   # Elasticsearch part ...
   # elasticsearch_uri    http://localhost:9200

   # MongoDB part ...
   uri                  mongodb://localhost
   
   # If you are running a MongoDB cluster (called a “replica set” in MongoDB),
   # you need to specify it's name here. 
   # With this option set, you can also write the mongodb_uri as a comma-separated
   # list of host:port items. (But one is enough, it will be used as a “seed”)
   #replica_set

   # Database name where to store the logs/availability collection
   database             shinken
   
   # Database authentication
   #username
   #password
   
   # DB connection test period
   # Every db_test_period seconds, the module tests if the DB connection is alive
   # 0 to skip this test
   #db_test_period    60
   
   ### ------------------------------------------------------------------------
   ### Logs management
   ### ------------------------------------------------------------------------
   # Logs collection name
   logs_collection      logs
   
   # Logs rotation
   #
   # Remove logs older than the specified value
   # Value is specified as : 
   # 1d: 1 day
   # 3m: 3 months ...
   max_logs_age    3m  ; d = days, w = weeks, m = months, y = years
   
   # Commit volume
   # The module commits at most commit_volume logs in the DB at every commit period
   #commit_volume     1000
   
   # Commit period
   # Every commit_period seconds, the module stores the received logs in the DB
   #commit_period     10
   
   ### ------------------------------------------------------------------------
   ### Hosts/services management
   ### ------------------------------------------------------------------------
   # Hosts/services availability collection name
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
   services_filter ^SSH Connexion$, bi:>4
}
```
