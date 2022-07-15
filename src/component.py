"""
Template Component main class.

"""
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Dict

import urllib3
from keboola.component.base import ComponentBase
from keboola.component.dao import TableDefinition
from keboola.component.exceptions import UserException
from keboola.csvwriter import ElasticDictWriter
# configuration variables
from requests.exceptions import RequestException

from filemaker.client import DataApiClient, ClientUserError

TIMESTAMP_FORMAT = '%m/%d/%Y %H:%M:%S'

KEY_PASSWORD = '#password'
KEY_USERNAME = 'username'
KEY_DATABASE = 'database'
KEY_BASEURL = 'base_url'

KEY_LAYOUT_NAME = 'layout_name'
KEY_QUERY = 'query'
KEY_FIELD_NAME = 'field_name'
KEY_FIND_CRITERIA = 'find_criteria'

# list of mandatory parameters => if some is missing,
# component will fail with readable message on initialization.
REQUIRED_PARAMETERS = [KEY_PASSWORD, KEY_USERNAME, KEY_DATABASE, KEY_BASEURL]
REQUIRED_IMAGE_PARS = []


@dataclass
class WriterCacheEntry:
    writer: ElasticDictWriter
    table_definition: TableDefinition


class HeaderNormalizer:
    UNDERSCORE_PREFIX = 'hsh'

    @staticmethod
    def reconstruct_original_columns(column_names: List[str]) -> List[str]:
        """
        Reconstructs normalized header
        Args:
            column_names:

        Returns:

        """
        new_header = []
        for c in column_names:
            if c.startswith(f'{HeaderNormalizer.UNDERSCORE_PREFIX}_'):
                new_col = c.replace(f'{HeaderNormalizer.UNDERSCORE_PREFIX}_', '_')
            else:
                new_col = c
            new_header.append(new_col)
        return new_header

    @staticmethod
    def normalize_columns(column_names: List[str]) -> List[str]:
        """
        Normalizes header to store in KBC STorage
        Args:
            column_names:

        Returns:

        """
        new_header = []
        for c in column_names:
            if c.startswith('_'):
                new_col = f'{HeaderNormalizer.UNDERSCORE_PREFIX}{c}'
            else:
                new_col = c
            new_header.append(new_col)
        return new_header


class Component(ComponentBase):
    """
        Extends base class for general Python components. Initializes the CommonInterface
        and performs configuration validation.

        For easier debugging the data folder is picked up by default from `../data` path,
        relative to working directory.

        If `debug` parameter is present in the `config.json`, the default logger is set to verbose DEBUG mode.
    """

    def __init__(self):
        super().__init__()
        self.validate_configuration_parameters([KEY_USERNAME, KEY_PASSWORD, KEY_BASEURL])
        self._client = DataApiClient(self.configuration.parameters[KEY_BASEURL],
                                     self.configuration.parameters[KEY_USERNAME],
                                     self.configuration.parameters[KEY_PASSWORD],
                                     ssl_verify=self.configuration.parameters.get('ssl_verify', True))
        state = self.get_state_file() or {}
        self._layout_schemas: dict = state.get('table_schemas') or {}
        self._writer_cache: Dict[str, WriterCacheEntry] = {}
        self._current_state = state.copy()

        if not self._current_state.get('previous_run_values'):
            self._current_state['previous_run_values'] = {}

        self.validate_configuration_parameters(REQUIRED_PARAMETERS)
        # suppress ssl warnings and rather log once
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def run(self):
        """
        Main execution code
        """

        params = self.configuration.parameters

        self.test_connection()

        if not params.get('ssl_verify', True):
            logging.warning("SSL certificate verification is disabled!")

        if params.get('object_type', 'Layout') == 'Metadata':
            self._download_metadata()
        elif params.get('object_type', 'Layout') == 'Layout':
            self._init_state()
            self.validate_configuration_parameters(REQUIRED_PARAMETERS + [KEY_LAYOUT_NAME])
            self._download_layout_data()

        else:
            raise UserException(f"Invalid object type '{params['object_type']}'!")

        result_tables = self._close_writers()
        self._current_state['table_schemas'] = self._layout_schemas
        self.write_state_file(self._current_state)
        self.write_manifests(result_tables)

    def test_connection(self):
        try:
            self._client.get_product_information()
        except Exception as e:
            raise UserException(f"The connection cannot be established, "
                                f"please check your credentials. Detail: {e}") from e

    def _init_state(self):
        if not self._current_state.get('previous_run_values'):
            self._current_state['previous_run_values'][self.configuration.parameters[KEY_LAYOUT_NAME]] = {}
        elif not self._current_state['previous_run_values'].get(self.configuration.parameters[KEY_LAYOUT_NAME]):
            # fix kbc bug converting obj to array
            self._current_state['previous_run_values'][self.configuration.parameters[KEY_LAYOUT_NAME]] = {}

    def _get_last_values(self, layout_name: str, field_names: List[str]) -> Dict:
        """
        Retrieves max incremental fetching value from previous execution for this layout
        Args:
            layout_name:
            field_name:

        Returns:

        """
        state = self.get_state_file()
        prev_run_values = state.get('previous_run_values', {})
        if not prev_run_values.get(layout_name, {}):
            # fix kbc bug converting obj to array
            prev_run_values[layout_name] = {}
        last_values = {}
        for field in field_names:
            prev_value = prev_run_values.get(layout_name, {}).get(field)
            if prev_value:
                last_values[field] = prev_run_values.get(layout_name, {}).get(field)
        return last_values

    def _apply_incremental_fetching(self, layout_name: str, query_list: List[dict]):
        """
        Inplace, Applies incremental fetching filter if specified. Based on previous execution

        Returns:

        """
        field_names = self.configuration.parameters.get('loading_options', {}).get('incremental_fields', [])
        incremental_fetching = self.configuration.parameters.get('loading_options', {}).get('incremental_fetch')
        previous_values = self._get_last_values(layout_name, field_names)
        query = {}
        if incremental_fetching and previous_values:
            for field_name, previous_value in previous_values.items():
                query[field_name] = f'>= {previous_value}'
            query_list.append(query)

        return field_names

    def _build_sort_expression(self):
        field_names = self.configuration.parameters.get('loading_options', {}).get('incremental_fields')
        incremental_fetching = self.configuration.parameters.get('loading_options', {}).get('incremental_fetch')
        sort = []
        if incremental_fetching and field_names:
            for field in field_names:
                sort.append({'fieldName': field})
        return sort

    def _store_max_value(self, layout_name: str, row: dict, field_names: List[str]):
        """
        Stores max timestamp value from the row based on previous call of this method.
        Args:
            layout_name:
            row:
            field_names:

        Returns:

        """
        if not field_names or not row:
            return

        for field_name in field_names:
            current_value = row[field_name]
            self._current_state['previous_run_values'][layout_name][field_name] = current_value

    def _download_layout_data(self):
        """
        Downlaods layout data. Performs incremental fetch if selected.
        Returns:

        """
        layout_name = self.configuration.parameters[KEY_LAYOUT_NAME]
        database_name = self.configuration.parameters[KEY_DATABASE]

        # build query
        query_list = self._build_queries()
        fetching_fields = self._apply_incremental_fetching(layout_name, query_list)

        sort_expression = self._build_sort_expression()

        logging.info(f'Fetching data for layout "{layout_name}", filter: {query_list}, sort: {sort_expression}')

        pagination_limit = self.configuration.parameters.get('page_size', 1000)

        # when the query is empty, list records without filter
        if not query_list:
            response_iterator = self._client.get_records(database_name, layout_name, pagination_limit, sort_expression)
        else:
            response_iterator = self._client.find_records(database_name, layout_name, query_list, pagination_limit,
                                                          sort_expression)
        try:
            count = 1
            last_row = dict()
            for data_page, data_info in response_iterator:
                page_size = len(data_page)
                logging.info(f'Downloading records {count} - {count + page_size}')
                count += page_size
                # this is cached, we do not know table name before first response. Datainfo is same in all parts
                table_definition = self._build_table_definition(data_info['table'])
                writer = self._get_writer_from_cache(table_definition, data_info['table'])

                # select max timestamp value to reduce sorting load on FileMaker db.
                last_row = {}
                for row in data_page:
                    writer.writerow(row['fieldData'])
                    if row['fieldData']:
                        last_row = row['fieldData']

            self._store_max_value(layout_name, last_row, fetching_fields)

        except RequestException as e:
            raise UserException(e) from e

        except Exception:
            raise

    def _build_queries(self) -> List[dict]:
        """
        Builds query in format accepted by DataAPI
        Returns:

        """

        query_list = list()
        for query_group in self.configuration.parameters[KEY_QUERY]:
            single_query = {}
            for q in query_group:
                single_query[q[KEY_FIELD_NAME]] = q[KEY_FIND_CRITERIA]
            query_list.append(single_query)
        return query_list

    def _download_metadata(self):
        """
        Download available databases and layouts and field metadata

        Returns:

        """
        logging.info('Downloading available databases and layouts')
        layouts_table = self.create_out_table_definition('layouts.csv', incremental=False)

        database_names = self._client.get_database_names()
        layouts_writer = self._get_writer_from_cache(layouts_table, layouts_table.name)

        for database in database_names:
            layouts = self._client.get_layouts(database)
            layouts_data = self._parse_layout_data(layouts, database)
            layouts_writer.writerows(layouts_data)

        field_metadata_filter = self.configuration.parameters.get('field_metadata', [])
        layout_metadata_table = self.create_out_table_definition('layout_fields_metadata.csv', incremental=False)
        layout_metadata_writer = self._get_writer_from_cache(layout_metadata_table, layout_metadata_table.name)
        if field_metadata_filter:
            logging.info('Downloading available field schemas for specified layouts.')
        for field_f in field_metadata_filter:
            layout_metadata = self._client.get_layout_field_metadata(field_f['database'], field_f['layout_name'])
            layout_metadata_writer.writerows(
                self._parse_layout_metadata(layout_metadata, field_f['database'], field_f['layout_name']))

    def _parse_layout_metadata(self, layout_metadata: List[dict], database: str, layout_name: str):
        for record in layout_metadata:
            record['database_name'] = database
            record['layout_name'] = layout_name
            yield record

    def _parse_layout_data(self, layouts: List[dict], database: str) -> List[dict]:
        layout_records = []

        for lo in layouts:
            if lo.get('isFolder', False):
                parent_layout_name = lo['name']
                children = [
                    {"database_name": database, "parent_layout_name": parent_layout_name, "layout_name": child['name'],
                     "table": child.get('table', '')}
                    for child in lo['folderLayoutNames']]
                layout_records.extend(children)
            else:
                layout_records.append({"database_name": database,
                                       "parent_layout_name": '',
                                       "layout_name": lo["name"],
                                       "table": lo['table']})
        return layout_records

    @lru_cache(10)
    def _build_table_definition(self, table_name: str):
        primary_key = self.configuration.parameters['loading_options'].get('pkey', [])
        # normalize
        primary_key = HeaderNormalizer.normalize_columns(primary_key)
        incremental = self.configuration.parameters['loading_options'].get('incremental', False)
        return self.create_out_table_definition(f'{table_name}.csv', primary_key=primary_key, incremental=incremental)

    @lru_cache(10)
    def _get_writer_from_cache(self, table_definition: TableDefinition, table_name: str) -> ElasticDictWriter:

        if not self._writer_cache.get(table_name):
            column_headers = HeaderNormalizer.reconstruct_original_columns(self._layout_schemas.get(table_name, []))
            writer = ElasticDictWriter(table_definition.full_path, column_headers)
            self._writer_cache[table_name] = WriterCacheEntry(writer, table_definition)

        return self._writer_cache[table_name].writer

    def _close_writers(self) -> List[TableDefinition]:
        """
        Finalizes the writers and store schemas in cache.
        Returns: List of resulting table definitions

        """

        result_tables = []
        for key, wr in self._writer_cache.items():
            wr.writer.close()
            self._layout_schemas[key] = wr.writer.fieldnames
            # set columns
            wr.table_definition.columns = HeaderNormalizer.normalize_columns(wr.writer.fieldnames)
            result_tables.append(wr.table_definition)
        return result_tables


"""
        Main entrypoint
"""
if __name__ == "__main__":
    try:
        comp = Component()
        # this triggers the run method by default and is controlled by the configuration.action parameter
        comp.execute_action()
    except (UserException, ClientUserError) as exc:
        logging.exception(exc)
        exit(1)
    except Exception as exc:
        logging.exception(exc)
        exit(2)
