# FiLeMaker Extractor

Extract layout data from [FileMaker](https://www.claris.com/filemaker/) relational database via [FileMaker Data API](https://help.claris.com/en/data-api-guide/content/write-data-api-calls.html).

**Table of contents:**

[TOC]

Functionality notes
===================

Prerequisites
=============

- Prepare your database for FileMaker Data API access, by [creating specific layouts](https://help.claris.com/en/data-api-guide/content/prepare-databases-for-access.html)
- Obtain FileMaker Data API credentials, host URL + username and password


Configuration
=============

## FileMaker Credentials
 - Host URL of the FileMaker server. (base_url) - [REQ] 
 - User Name (username) - [REQ] 
 - Password (#password) - [REQ] 
 - Verify SSL certificate. (ssl_verify) - [OPT] Set to false to disable SSL (https) certificate verification. Use with caution.


## Query Configuration
 - Object type (object_type) - [REQ] "enum": ["Metadata", "Layout"], type of object you wish to download. 
   - Metadata - Download schemas of selected layouts
   - Layout - Download data of particular layout
 - Database (database) - [OPT] FileMaker database name
 - FileMaker layout name (layout_name) - [OPT] Name of the Layout
 - Field Metadata (field_metadata) - [OPT] Download schemas of selected layouts. If left empty only list of available databases and layouts is downloaded.
 - Query Group (query) - [OPT] Groups of filter criteria. 'OR' logical operation is applied to each group. 'AND' logical operation is applied to each set of queries. Note that if you include field used for incremental fetching, the incremental fetching will not work as expected.
 - Loading Options (loading_options) - [OPT] Options that define how the data is synced
   - Load Type (incremental) - Full load (0) data in destination is overwritten each run, Incremental Update (1) - each data in destination is upserted.
   - Primary key (pkey) - list of primary key columns if present. Needed for incremental load type
   - Incremental fetching (incremental_fetch) - If true each consecutive run will return only records with values >= than the highest incremental fields values from last run.
   - Incremental fields (incremental_fields) - List of columns used for incremental fetching. If multiple specified AND relation is used.
 - Page size (page_size) - [OPT] Number of records retrieved in single API call. Note that to large page size may affect load on the destination database


Sample Configuration
=============
```json
{
    "parameters": {
        "ssl_verify": false,
        "object_type": "Layout",
        "base_url": "https://localhost:8900",
        "username": "keboola",
        "#password": "SECRET_VALUE",
        "database": "NAC_Staff",
        "layout_name": "WS_Data_Analytics_PAC_StaffTeam",
        "query": [],
        "loading_options": {
            "incremental_fields": [
                "Timestamp_Modified",
                "UID"
            ],
            "pkey": [
                "Id"
            ],
            "incremental_fetch": true,
            "incremental": 1
        }
    },
    "action": "run"
}
```

Output
======

**NOTE** The columns prefixed `_` are prefixed with hsh prefix in the result table. This is because the Keboola Connection Storage does not allow to store columns prefixed with underscore. So the column _Timestamp will be stored as hsh_Timestamp in the resulting table.

### Metadata


####**layouts** 

- List of available layouts

columns [`table`, `layout_name`, `parent_layout_name`] 

  
####**layout_fields_metadata** 

-  Schema and metadata describing the particular layout.

columns: [ `displayType`,
	`repetitionEnd`,
	`numeric`,
	`maxCharacters`,
	`maxRepeat`,
	`fourDigitYear`,
	`layout_name`,
	`database_name`,
	`type`,
	`repetitionStart`,
	`autoEnter`,
	`name`,
	`global`,
	`result`,
	`notEmpty`,
	`timeOfDay`]


### Layouts

Layout data defined by the particular query definition.

Development
-----------

If required, change local data folder (the `CUSTOM_FOLDER` placeholder) path to your custom path in
the `docker-compose.yml` file:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    volumes:
      - ./:/code
      - ./CUSTOM_FOLDER:/data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Clone this repository, init the workspace and run the component with following command:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
docker-compose build
docker-compose run --rm dev
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run the test suite and lint check using this command:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
docker-compose run --rm test
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Integration
===========

For information about deployment and integration with KBC, please refer to the
[deployment section of developers documentation](https://developers.keboola.com/extend/component/deployment/)