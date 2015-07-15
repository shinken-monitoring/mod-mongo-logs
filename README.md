Shinken logs MongoDB storage 
============================

Shinken module for storing Shinken logs to mongodb from the Broker daemon

No need for Livestatus to store Shinken logs and hosts availability data.

This module is a must-have for some Shinken Web UI features: host/service history, Shinken activity, hosts availability, ...


**Please note that this module is still on tests ... and do not hesitate to report any issue!**



Requirements 
=============
Use pymongo version > 3.0.

```
   pip install pymongo
```


Enabling Mongo logs 
=============================

To use the mongo-logs module you must declare it in your broker configuration.
```
   define broker {
      ... 

      modules    	 ..., mongo-logs

   }
```


The module configuration is defined in the file: mongo-logs.cfg.

Default configuration needs to be tuned up to your MongoDB configuration. 

```
## Module:      mongo-logs
## Loaded by:   Broker
# Store the Shinken logs in a mongodb database, so anyone can query them ...
define module {
   module_name         mongo-logs
   module_type         mongo-logs
   
   uri                 mongodb://localhost
   
   # If you are running a MongoDB cluster (called a “replica set” in MongoDB),
   # you need to specify it's name here. 
   # With this option set, you can also write the mongodb_uri as a comma-separated
   # list of host:port items. (But one is enough, it will be used as a “seed”)
   #replica_set

   # Database name where to store the logs collection
   database            shinken
   
   # Logs collection name
   logs_collection     logs
   
   # Logs rotation
   # Remove logs older than the specified value
   # Value is specified as : 
   # 1d: 1 day
   # 3m: 3 months ...
   max_logs_age    3m  ; d = days, w = weeks, m = months, y = years
   
   # Hosts availability collection name
   hav_collection      availability
}
```

It's done :)
