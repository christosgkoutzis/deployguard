import time
import urllib.request

if __name__ == '__main__':
    with urllib.request.urlopen('http://fixture-api-service/ready',timeout=5) as result:
        assert result.status == 200
    while True:
        print('Fixture worker running without an HTTP port',flush=True)
        time.sleep(5)
