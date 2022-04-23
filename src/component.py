"""
Template Component main class.

"""
import logging
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import List, Dict

import urllib3
from keboola.component.base import ComponentBase
from keboola.component.dao import TableDefinition
from keboola.component.exceptions import UserException
from keboola.csvwriter import ElasticDictWriter

# configuration variables
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
REQUIRED_PARAMETERS = [KEY_PASSWORD, KEY_USERNAME, KEY_DATABASE, KEY_BASEURL, KEY_LAYOUT_NAME]
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
        self.validate_configuration_parameters([KEY_BASEURL, KEY_DATABASE])

        self._client = DataApiClient(self.configuration.parameters[KEY_BASEURL],
                                     self.configuration.parameters[KEY_DATABASE],
                                     ssl_verify=self.configuration.parameters.get('ssl_verify', True))
        state = self.get_state_file() or {}
        self._layout_schemas: dict = state.get('table_schemas') or {}
        self._writer_cache: Dict[str, WriterCacheEntry] = {}
        self._current_state = state.copy()

        if not self._current_state.get('previous_run_values'):
            self._current_state['previous_run_values'] = {}

        # suppress ssl warnings and rather log once
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def run(self):
        """
        Main execution code
        """

        self.validate_configuration_parameters(REQUIRED_PARAMETERS)
        params = self.configuration.parameters

        self._client.login(params[KEY_USERNAME], params[KEY_PASSWORD])
        self._init_state()
        if not params.get('ssl_verify', True):
            logging.warning("SSL certificate verification is disabled!")

        try:
            self._download_layout_data()
            result_tables = self._close_writers()
            self._current_state['table_schemas'] = self._layout_schemas
            self.write_state_file(self._current_state)
            self.write_tabledef_manifests(result_tables)
        finally:
            self._client.logout()

    def _init_state(self):
        if not self._current_state.get('previous_run_values'):
            self._current_state['previous_run_values'][self.configuration.parameters[KEY_LAYOUT_NAME]] = {}

    def _get_last_max_timestamp_value(self, layout_name: str, field_name: str):
        """
        Retrieves max timetamp value from previous execution for this layout
        Args:
            layout_name:
            field_name:

        Returns:

        """
        state = self.get_state_file()
        return state.get('previous_run_values', {}).get(layout_name, {}).get(field_name)

    def _apply_incremental_fetching(self, layout_name: str, query_list: List[dict]):
        """
        Inplace, Applies incremental fetching filter if specified. Based on previous execution

        Returns:

        """
        field_name = self.configuration.parameters.get('loading_options', {}).get('incremental_field')
        incremental_fetching = self.configuration.parameters.get('loading_options', {}).get('incremental_fetch')
        previous_value = self._get_last_max_timestamp_value(layout_name, field_name)
        if incremental_fetching and previous_value:
            query_list.append({field_name: f'>= {previous_value}'})

        return field_name

    def _store_max_timestamp_value(self, layout_name: str, row: dict, field_name: str):
        """
        Stores max timestamp value from the row based on previous call of this method.
        Args:
            layout_name:
            row:
            field_name:

        Returns:

        """
        if not field_name:
            return

        last_timestamp_str = self._current_state.get('previous_run_values', {}).get(
            layout_name, {}).get(field_name) or '01/01/2000 00:00:00'
        last_timestamp = datetime.strptime(last_timestamp_str, TIMESTAMP_FORMAT)

        timestamp = datetime.strptime(row[field_name], TIMESTAMP_FORMAT)
        datetime.strptime(row[field_name], TIMESTAMP_FORMAT)
        if timestamp > last_timestamp:
            self._current_state['previous_run_values'][layout_name][field_name] = timestamp.strftime(TIMESTAMP_FORMAT)

    def _download_layout_data(self):
        """
        Downlaods layout data. Performs incremental fetch if selected.
        Returns:

        """
        layout_name = self.configuration.parameters[KEY_LAYOUT_NAME]

        # build query
        query_list = self._build_queries()
        fetching_field = self._apply_incremental_fetching(layout_name, query_list)

        logging.info(f'Fetching data for layout "{layout_name}", filter: {query_list}')

        pagination_limit = self.configuration.parameters.get('page_size', 1000)

        # when the query is empty, list records without filter
        if not query_list:
            response_iterator = self._client.get_records(layout_name, pagination_limit)
        else:
            response_iterator = self._client.find_records(layout_name, query_list, pagination_limit)

        count = 1
        for data_page, data_info in response_iterator:
            page_size = len(data_page)
            logging.info(f'Downloading records {count} - {count + page_size}')
            count += page_size
            # this is cached, we do not know table name before first response. Datainfo is same in all parts
            table_definition = self._build_table_definition(data_info['table'])
            writer = self._get_writer_from_cache(table_definition, data_info['table'])

            # select max timestamp value to reduce sorting load on FileMaker db.
            for row in data_page:
                self._store_max_timestamp_value(layout_name, row['fieldData'], fetching_field)
                writer.writerow(row['fieldData'])

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
