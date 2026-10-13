import json
import os
import urllib.request

if os.getenv("FAIL_ONCE"):
    with urllib.request.urlopen('http://fixture-api-service/retry',timeout=5) as result:
        if json.load(result)['attempt']==1:
            raise RuntimeError("deliberate first-attempt failure")

if __name__ == '__main__':
    with urllib.request.urlopen('http://fixture-api-service/data',timeout=5) as result:
        data=json.load(result)
    assert data['message']=='inline override'
    assert data['secret_present'] is True
    with urllib.request.urlopen('http://fixture-mock-service/fixture',timeout=5) as result:
        assert json.load(result)['mocked'] is True
    print('Generic platform fixture passed')
