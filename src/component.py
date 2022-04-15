"""
Template Component main class.

"""
import logging
from functools import lru_cache
from typing import List, Dict

from keboola.component.base import ComponentBase
from keboola.component.exceptions import UserException
from keboola.csvwriter import ElasticDictWriter

# configuration variables
from filemaker.client import DataApiClient, ClientUserError

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
                                     ssl_verify=False)
        state = self.get_state_file() or {}
        self._layout_schemas: dict = state.get('table_schemas') or {}
        self._writer_cache: Dict[str, ElasticDictWriter] = {}

    def run(self):
        """
        Main execution code
        """

        self.validate_configuration_parameters(REQUIRED_PARAMETERS)
        params = self.configuration.parameters

        self._client.login(params[KEY_USERNAME], params[KEY_PASSWORD])
        try:
            self._download_layout_data()
            self._close_writers()
        finally:
            self._client.logout()

    def _download_layout_data(self):
        # build query
        query_list = self._build_queries()
        for data_page, data_info in self._client.find_records(self.configuration.parameters[KEY_LAYOUT_NAME],
                                                              query_list):
            # this is cached, we do not know table name before first response. Datainfo is same in all parts
            table_definition = self._build_table_definition(data_info['table'])
            writer = self._get_writer_from_cache(table_definition.full_path, data_info['table'])

            writer.writerows([record['fieldData'] for record in data_page])

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
        incremental = self.configuration.parameters['loading_options'].get('incremental', False)
        return self.create_out_table_definition(f'{table_name}.csv', primary_key=primary_key, incremental=incremental)

    @lru_cache(10)
    def _get_writer_from_cache(self, output_path: str, table_name: str) -> ElasticDictWriter:

        if not self._writer_cache.get(table_name):
            column_headers = self._layout_schemas.get(table_name, [])
            self._writer_cache[table_name] = ElasticDictWriter(output_path, column_headers)
            self._writer_cache[table_name].writeheader()

        return self._writer_cache[table_name]

    def _close_writers(self):
        """
        Finalizes the writers and store schemas in cache
        Returns:

        """
        for key, wr in self._writer_cache.items():
            wr.close()
            self._layout_schemas[key] = wr.fieldnames


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
