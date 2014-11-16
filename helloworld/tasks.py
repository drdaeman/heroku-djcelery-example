from celery import task
import requests

@task()
def fetch_url(url, **kwargs):
    """
    A simple task that fetches the provided URL and returns a tuple
    with the HTTP status code and response body (if any)
    """
    r = requests.get(url, **kwargs)
    return (r.status_code, r.content)
