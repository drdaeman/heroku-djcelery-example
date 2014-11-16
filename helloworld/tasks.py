from celery import task, Task
import requests
import inspect
import collections
import sys


@task()
def fetch_url(url, **kwargs):
    """
    A simple task that fetches the provided URL and returns a tuple
    with the HTTP status code and response body (if any)
    """
    r = requests.get(url, **kwargs)
    return (r.status_code, r.content)


#
# Introspect the current module and find all the declared tasks.
#
# This is useful to have since we'll allow user to provide us with a
# task name and need to get a corresponding task function. By having
# it in a single data structure we won't have to repeat ourselves
# with lots of similar getattr calls and string mangling operations.
#
TaskInfo = collections.namedtuple("TaskInfo", "fullname name task")
ALL_TASKS = {
    __name__ + "." + _k: TaskInfo(__name__ + "." + _k, _k, _v)
    for _k, _v in inspect.getmembers(sys.modules[__name__])
    if isinstance(_v, Task)
}
