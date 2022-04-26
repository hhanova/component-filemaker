from typing import Tuple, List, Iterator

import requests
from keboola.http_client import HttpClient
from requests import HTTPError
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry


class ClientUserError(Exception):
    pass


class DataApiClient(HttpClient):

    def __init__(self,
                 server_url: str,
                 user: str,
                 password: str,
                 ssl_verify: bool = True,
                 max_retries: int = 3,
                 backoff_factor: float = 0.3,
                 status_forcelist: Tuple[int, ...] = (500, 502, 504)) -> None:
        base_url = f'{server_url}/fmi/data/v2/'

        self._user = user
        self._password = password
        self._ssl_verify = ssl_verify
        self._current_session_token = None
        self._current_database = ''
        super().__init__(base_url=base_url, max_retries=max_retries, backoff_factor=backoff_factor,
                         status_forcelist=status_forcelist)

    def login_to_database_session(self, database: str):
        """
        Login and open FileMaker DataApi session. Remember to call the logout method, otherwise the session is closed
        automatically after 15 min of inactivity.
        Args:
            database:

        Returns: session_token

        """
        try:
            response = self.post_raw(f'databases/{database}/sessions', json={}, auth=(self._user, self._password),
                                     verify=self._ssl_verify)
            response.raise_for_status()
            token = response.json()['response']['token']
            return token
        except HTTPError as e:
            raise ClientUserError(
                f'Failed to login to database {database}! Please verify your user name and password or database name.',
                e.response.text) from e

    def logout_from_database_session(self, database: str, session_token: str):
        """
        Performs logout from current session
        Returns:

        """
        self.delete(f'databases/{database}/sessions/{session_token}',
                    verify=self._ssl_verify)

    def find_records(self, database: str, layout: str,
                     query: List[dict], page_size=1000) -> Iterator[Tuple[List[dict], dict]]:
        """

        Args:
            database (str): Database name
            layout (str): Layout name
            query (List[dict]: List of find queries, e.g.  [{"_Timestamp_Modified":">= 4/11/2022"}]. Required parameter.
            Each dictionary is logical OR. Each property in the dictionary is evaluated as logical AND
            page_size:

        Returns: Iterator of response data pages.

        """

        session_key = self.login_to_database_session(database)
        auth_header = {"Authorization": f'Bearer {session_key}'}
        json_data = {}
        if query:
            json_data["query"] = query

        endpoint = f'databases/{database}/layouts/{layout}/_find'

        has_more = True
        json_data['offset'] = 1
        try:
            while has_more:
                json_data['limit'] = page_size

                response = self.post_raw(endpoint, json=json_data, verify=self._ssl_verify, headers=auth_header)
                self._handle_http_error(response)
                response_data = response.json().get('response', {})

                if response_data.get('data', []):
                    has_more = True
                    json_data['offset'] += page_size
                else:
                    has_more = False

                yield response_data['data'], response_data['dataInfo']
        finally:
            self.logout_from_database_session(database, session_key)

    def get_records(self, database: str, layout: str, page_size=1000) -> Iterator[Tuple[List[dict], dict]]:
        """
        Get all layout records, paginated.
        Args:
            database: database name
            layout:
            page_size:

        Returns: Iterator of response data pages.

        """
        session_key = self.login_to_database_session(database)
        auth_header = {"Authorization": f'Bearer {session_key}'}

        endpoint = f'databases/{database}/layouts/{layout}/records'
        has_more = True
        parameters = {"_offset": 1, "_limit": page_size}
        try:
            while has_more:

                response = self.get_raw(endpoint, params=parameters, verify=self._ssl_verify, headers=auth_header)
                self._handle_http_error(response)
                response_data = response.json().get('response', {})

                if response_data['dataInfo']['returnedCount'] == page_size:
                    has_more = True
                    parameters['_offset'] += page_size
                else:
                    has_more = False

                yield response_data['data'], response_data['dataInfo']
        finally:
            self.logout_from_database_session(database, session_key)

    def get_database_names(self) -> List[str]:
        """
        Get all available database names for the logged-in user.
        Returns:

        """
        response = self.get_raw('databases', auth=(self._user, self._password), verify=self._ssl_verify)
        self._handle_http_error(response)
        response_data = response.json().get('response', {})
        return [record.get('name') for record in response_data['databases']]

    def get_layouts(self, database: str) -> List[dict]:
        """
        Get available layouts for the database
        Args:
            database: database name

        Returns:

        """
        session_key = self.login_to_database_session(database)
        auth_header = {"Authorization": f'Bearer {session_key}'}
        endpoint = f'databases/{database}/layouts'
        try:
            response = self.get_raw(endpoint, headers=auth_header, verify=self._ssl_verify)
            self._handle_http_error(response)
            response_data = response.json().get('response', {})
            return response_data.get('layouts', [])
        finally:
            self.logout_from_database_session(database, session_key)

    def get_layout_field_metadata(self, database: str, layout: str) -> List[dict]:
        """
        Get layout field metadata
        Args:
            database: database name
            layout: layout name

        Returns:

        """
        session_key = self.login_to_database_session(database)
        auth_header = {"Authorization": f'Bearer {session_key}'}
        endpoint = f'databases/{database}/layouts/{layout}'
        try:
            response = self.get_raw(endpoint, headers=auth_header, verify=self._ssl_verify)
            self._handle_http_error(response)
            response_data = response.json().get('response', {})
            return response_data.get('fieldMetaData', [])
        finally:
            self.logout_from_database_session(database, session_key)

    def _handle_http_error(self, response):

        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            raise ClientUserError(f'Failed to perform find request. Detail: {e.response.text}')

    # override to continue on failure
    def _requests_retry_session(self, session=None):
        session = session or requests.Session()
        retry = Retry(
            total=self.max_retries,
            read=self.max_retries,
            connect=self.max_retries,
            backoff_factor=self.backoff_factor,
            status_forcelist=self.status_forcelist,
            allowed_methods=self.allowed_methods,
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session
