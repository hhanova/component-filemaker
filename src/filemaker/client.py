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
                 database: str,
                 ssl_verify: bool = True,
                 max_retries: int = 3,
                 backoff_factor: float = 0.3,
                 status_forcelist: Tuple[int, ...] = (500, 502, 504)) -> None:
        base_url = f'{server_url}/fmi/data/v2/databases/{database}/'
        self._ssl_verify = ssl_verify
        self._current_session_token = None
        super().__init__(base_url=base_url, max_retries=max_retries, backoff_factor=backoff_factor,
                         status_forcelist=status_forcelist)

    def login(self, user: str, password: str):
        """
        Login and open FileMaker DataApi session. Remember to call the logout method, otherwise the session is closed
        automatically after 15 min of inactivity.
        Args:
            user:
            password:

        Returns:

        """
        try:
            response = self.post_raw('sessions', json={}, auth=(user, password), verify=self._ssl_verify)
            response.raise_for_status()
            token = response.json()['response']['token']
            self._current_session_token = token
            self._auth_header = {"Authorization": f'Bearer {token}'}
        except HTTPError as e:
            raise ClientUserError('Failed to login! Please verify your user name and password or database name.',
                                  e.response.text) from e

    def logout(self):
        """
        Performs logout from current session
        Returns:

        """
        self.delete(f'sessions/{self._current_session_token}', verify=self._ssl_verify)

    def find_records(self, layout: str, query: List[dict], page_size=1000) -> Iterator[Tuple[List[dict], dict]]:
        """

        Args:
            layout (str): Layout name
            query (List[dict]: List of find queries, e.g.  [{"_Timestamp_Modified":">= 4/11/2022"}]. Required parameter.
            Each dictionary is logical OR. Each property in the dictionary is evaluated as logical AND
            page_size:

        Returns: Iterator of response data pages.

        """
        json_data = {}
        if query:
            json_data["query"] = query

        endpoint = f'layouts/{layout}/_find'
        return self._get_paged_result_pages(endpoint, json_data, limit=page_size)

    def get_records(self, layout: str, page_size=1000) -> Iterator[Tuple[List[dict], dict]]:
        """
        Get all layout records, paginated.
        Args:
            layout:
            page_size:

        Returns: Iterator of response data pages.

        """
        endpoint = f'layouts/{layout}/records'
        has_more = True
        parameters = {"_offset": 1, "_limit": page_size}
        while has_more:

            response = self.get_raw(endpoint, params=parameters, verify=self._ssl_verify)
            self._handle_http_error(response)
            response_data = response.json().get('response', {})

            if response_data['dataInfo']['returnedCount'] == page_size:
                has_more = True
                parameters['_offset'] += page_size
            else:
                has_more = False

            yield response_data['data'], response_data['dataInfo']

    def _handle_http_error(self, response):

        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            raise ClientUserError(f'Failed to perform find request. Detail: {e.response.text}')

    def _get_paged_result_pages(self, endpoint: str,
                                json_data: dict,
                                parameters: dict = None,
                                limit=100) -> Iterator[Tuple[List[dict], dict]]:
        """
        Get paginated data
        Args:
            endpoint:
            json_data:
            parameters:
            limit:

        Returns:

        """

        has_more = True
        json_data['offset'] = 1
        while has_more:
            json_data['limit'] = limit

            response = self.post_raw(endpoint, json=json_data, params=parameters, verify=self._ssl_verify)
            self._handle_http_error(response)
            response_data = response.json().get('response', {})

            if response_data.get('data', []):
                has_more = True
                json_data['offset'] += limit
            else:
                has_more = False

            yield response_data['data'], response_data['dataInfo']

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
