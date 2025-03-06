# FiLeMaker Extractor

FileMaker is a cross-platform relational database application from Claris International.
This component extracts layout data from [FileMaker](https://www.claris.com/filemaker/) relational databases using the [FileMaker Data API](https://help.claris.com/en/data-api-guide/content/write-data-api-calls.html).

**Table of contents:**

[TOC]

Functionality notes
===================

Prerequisites
=============

- Configure your database for FileMaker Data API access by [creating specific layouts](https://help.claris.com/en/data-api-guide/content/prepare-databases-for-access.html).
- Obtain FileMaker Data API credentials, including the host URL, username, and password.


Configuration
=============

## FileMaker Credentials
 - **Host URL** of the FileMaker server (`base_url`, required) – The FileMaker server host URL.
 - **User Name** (`username`, required) – The username for authentication. 
 - **Password** (`#password`, required) – The corresponding password.
 - **Verify SSL certificate** (`ssl_verify`, optional) – Set to `false` to disable SSL (https) certificate verification. Use with caution.


## Query Configuration
 - Object type (object_type) - [REQ] "enum": ["Metadata", "Layout"]; Define the object type to extract. 
   - Metadata - Download schemas of selected layouts. 
   - Layout - Download data from a specific layout.
 - Database (database) - [OPT] The name of the FileMaker database.
 - FileMaker layout name (layout_name) - [OPT] The name of the layout.
 - Field Metadata (field_metadata) - [OPT] Download schemas of selected layouts. If left empty, only a list of available databases and layouts will be downloaded.
 - Query Group (query, optional) – Groups of filter criteria.
    - The logical 'OR' operation is applied between groups.
    - The logical 'AND' operation is applied within a set of queries.
    - ***Note:** If you include a field used for incremental fetching, the incremental fetching may not work as expected.*
  - Loading Options (loading_options) - [OPT] Options that define how the data is synced.
   - Load Type (incremental) - Full load (0) overwrites data in the destination on run, Incremental Update (1) upserts data in the destination on each run.
   - Primary key (pkey) - List of primary key columns, if available. Required for incremental load.
   - Incremental fetching (incremental_fetch) - If `true`, only records with values >=to the last incremental field value will be retrieved in consecutive runs.
   - Incremental fields (incremental_fields) - List of columns used for incremental fetching. If multiple specified, an `AND` relation is applied.
 - Page size (page_size) - [OPT] The number of records retrieved per API call. ***Note:** A large page size may impact performance on the destination database.*

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

***Note:** Columns prefixed with `_` are stored in Keboola Storage with the `hsh` prefix in the resulting table. This is because Keboola Storage does not allow columns to begin with an underscore. For example, the column `_Timestamp` will be stored as `hsh_Timestamp` in the resulting table.*

### Metadata


#### layouts 

List of available layouts.

columns [`table`, `layout_name`, `parent_layout_name`] 

  
#### layout_fields_metadata

-  Schema and metadata describing a specific layout.

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

Layout data is extracted based on the query definition provided.

Development
-----------

If needed, update the local data folder path (the `CUSTOM_FOLDER` placeholder) to your custom path in
the `docker-compose.yml` file:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    volumes:
      - ./:/code
      - ./CUSTOM_FOLDER:/data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Clone this repository, initialize the workspace, and run the component with the following commands:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
docker-compose build
docker-compose run --rm dev
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run the test suite and perform a lint check using this command:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
docker-compose run --rm test
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Integration
===========

For details on deployment and integration with Keboola, refer to the
[deployment section of the developer documentation](https://developers.keboola.com/extend/component/deployment/).
