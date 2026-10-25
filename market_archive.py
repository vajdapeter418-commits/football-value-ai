"""Separate private market archive, using the existing safe GitHub transport only."""
import base64
from copy import deepcopy
import json
from urllib.parse import urlencode

from forecast_cloud import ArchiveMissing, GitHubArchive
from forecast_journal import canonical
from market_research import MAX_BYTES, COLLECTIONS, empty_state, validate_state


class MarketArchive(GitHubArchive):
    def __init__(self, token, repository):
        super().__init__(token, repository)
        self.branch = 'market-research'
        self.endpoint = self.repo_url + '/contents/archive/market-research.json'

    def load(self):
        self._private()
        response = self._request('GET', self.endpoint + '?' + urlencode({'ref': self.branch}))
        if response.get('encoding') != 'base64' or not response.get('sha'):
            raise ValueError('Invalid market archive response')
        raw = base64.b64decode(response['content'], validate=False)
        if len(raw) > MAX_BYTES:
            raise ValueError('Market archive too large')
        return validate_state(json.loads(raw)), response['sha']

    def initialize(self):
        meta = self._private()
        try:
            return self.load()[0]
        except ArchiveMissing:
            pass
        branch_url = self.repo_url + '/git/ref/heads/' + self.branch
        try:
            self._request('GET', branch_url)
        except ArchiveMissing:
            from urllib.parse import quote
            head = self._request('GET', self.repo_url + '/git/ref/heads/' + quote(meta['default_branch'], safe=''))
            self._request('POST', self.repo_url + '/git/refs',
                          {'ref': 'refs/heads/' + self.branch, 'sha': head['object']['sha']})
        state = empty_state()
        response = self._request('PUT', self.endpoint,
                                {'message': 'Initialize separate market research archive',
                                 'branch': self.branch,
                                 'content': base64.b64encode(canonical(state).encode()).decode()})
        if not response.get('commit', {}).get('sha'):
            raise ValueError('Market archive initialization not acknowledged')
        return state

    def change(self, mutator):
        state, sha = self.load()
        original = deepcopy(state)
        updated = validate_state(mutator(state))
        for key in COLLECTIONS:
            if updated[key][:len(original[key])] != original[key]:
                raise ValueError('Market history may only be extended')
        raw = canonical(updated).encode()
        # Contents API read limit: stay below 1 MB after base64 response expansion.
        if len(raw) > min(MAX_BYTES, 700000):
            raise ValueError('Market archive file size limit reached')
        response = self._request('PUT', self.endpoint,
                                {'message': 'Append market research evidence',
                                 'branch': self.branch, 'sha': sha,
                                 'content': base64.b64encode(raw).decode()})
        if not response.get('commit', {}).get('sha'):
            raise ValueError('Market save not acknowledged; refresh before retry')
        return updated
