"""Verify the demo's HTTP, messaging, cache, search, and CSV export flows."""
import csv
import io
import os
import time
from urllib.parse import parse_qs, urlparse
import uuid

import pytest
import requests

TARGET_URL = os.getenv('TARGET_URL','http://ruby-gateway-service:80')
BACKEND_URL = os.getenv('BACKEND_URL','http://python-backend-service:80')
S3_ENDPOINT = os.getenv('S3_ENDPOINT','http://seaweedfs-all-in-one:8333')
GREETING = 'Integration Test Greeting '+uuid.uuid4().hex


def eventually(check, description, seconds=90):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if check():
            return
        time.sleep(2)
    pytest.fail(description)


def response(method,path,**kwargs):
    result=requests.request(method,TARGET_URL+path,timeout=10,**kwargs)
    result.raise_for_status()
    return result


def test_sync_mock():
    def propagated():
        try:
            html=response('GET','/').text
            return 'Hello from python-backend!' in html and 'Hello from the mocked API!' in html
        except requests.RequestException:
            return False
    eventually(propagated,'Backend and mock greetings were not propagated to the gateway')


def test_event_driven_write_and_read():
    response('POST','/write',data={'greeting_text':GREETING})
    def approved():
        result=requests.get(BACKEND_URL+'/db/read',timeout=10)
        result.raise_for_status()
        data=result.json()
        return data.get('greeting')==GREETING and data.get('status')=='Approved'
    eventually(approved,'The specific written event was not approved by the Kafka worker')
    data=requests.get(BACKEND_URL+'/db/read',timeout=10).json()
    assert data['source']=='Redis Cache'
    redirected=response('GET','/read',allow_redirects=False)
    assert redirected.status_code in [301,302,303]
    assert 'Approved' in parse_qs(urlparse(redirected.headers['Location']).query)['db_message'][0]


def test_elasticsearch():
    def indexed():
        result=requests.get(BACKEND_URL+'/search',params={'q':GREETING},timeout=10)
        result.raise_for_status()
        return any(hit.get('greeting')==GREETING and hit.get('status')=='Approved'
                   for hit in result.json().get('results',[]))
    eventually(indexed,'The specific approved greeting was not indexed in Elasticsearch')
    result=response('GET','/search',params={'q':GREETING},allow_redirects=False)
    assert result.status_code in [301,302,303]
    assert 'ID:' in parse_qs(urlparse(result.headers['Location']).query)['search_results'][0]


def test_async_export():
    response('POST','/report/generate')
    def exported():
        result=response('GET','/report/download',allow_redirects=False)
        if result.status_code not in [301,302,303]:
            return False
        url=result.headers.get('Location','')
        parsed = urlparse(url)
        assert parsed.scheme == urlparse(S3_ENDPOINT).scheme
        assert parsed.netloc == urlparse(S3_ENDPOINT).netloc
        assert parse_qs(parsed.query).get('X-Amz-Signature')
        assert requests.get(parsed._replace(query='').geturl(), timeout=10).status_code in [401,403]
        report=requests.get(url,timeout=10)
        if report.status_code==404:
            return False
        report.raise_for_status()
        return any(row.get('Greeting')==GREETING and row.get('Status')=='Approved'
                   for row in csv.DictReader(io.StringIO(report.text)))
    eventually(exported,'RabbitMQ/S3 did not produce a downloadable CSV containing the new event')
