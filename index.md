---
layout: index
title: A basic Celery on Heroku guide
---

A basic Celery on Heroku guide
==============================

This guide starts right where the "[Getting Started with Django on Heroku][11]" ends.
It's assumed you have a basic and empty Django project. As a result, we'll have a basic
Django/Celery site that enqueues immediate and periodic tasks.

Basic preparations
------------------

First of all, let's actually install Celery and add it to our requirements list
(as we had just started, let's just overwrite `requirements.txt` here):

    $ pip install celery django-celery
    $ pip freeze > requirements.txt

The `django-celery` package will be eventually [outdated][13] and integrated into
Celery itself, but for a time being it's still required, as it provides database
models to store task results and a database-driven periodic task scheduler,
so we won't have to implement our own.

We'll mostly proceed according to official [Django/Celery tutorial][1],
taking some additional steps to accommodate for Heroku's specifics.

As tutorial says, let's touch our `settings.py` adding the following snippet:

    import djcelery
    djcelery.setup_loader()

And include `"djcelery"` into `INSTALLED_APPS` tuple.

AMQP broker
-----------

One option is to use AMQP-based broker (RabbitMQ). In my perception, it's the most popular
option in Celery community.

Let's add it to our Heroku app:

    $ heroku addons:add cloudamqp
    Adding cloudamqp on secure-fortress-6930... done, v6 (free)
    Use `heroku addons:docs cloudamqp` to view documentation.

The first tier [("Little Lemur")][2] is free but limited to 3 concurrent connections.
Those should be enough for the single-worker setup, but any additional workers would
require larger tiers.

There's also `rabbitmq-bigwig` addon, but unfortunately, Celery does not
support separate consumer and producer connections (there's a yet-unfulfilled
[feature request][3] for it), so I'm not sure how to deal with it.

We'll need some settings:

    BROKER_URL = os.environ.get("CLOUDAMQP_URL", "django://")
    BROKER_POOL_LIMIT = 1
    BROKER_CONNECTION_MAX_RETRIES = None

    CELERY_TASK_SERIALIZER = "json"
    CELERY_ACCEPT_CONTENT = ["json", "msgpack"]
    CELERYBEAT_SCHEDULER = 'djcelery.schedulers.DatabaseScheduler'

    if BROKER_URL == "django://":
        INSTALLED_APPS += ("kombu.transport.django",)


There are a few options that aren't covered by Celery tutorial.

- The [`BROKER_POOL_LIMIT` option][4] controls the maximum number of connections that
  will be open in the connection pool. Since we're using a free tier and limited on those,
  according to [addon's suggestion][5], we'll set this to 1.

  Please, be aware that even though documentation say `1` should be a good choice,
  Celery may try to open more than 3 connections. In particular, this may happen when
  multiple requests happen to a website and both try to queue a task. Another option
  is to set `BROKER_POOL_LIMIT = None` to disable pool at all and create new connections
  on demand. This will have some performance penalties (a new TCP connection will be made,
  and this takes time), but may help in case of tight limits.

- `BROKER_CONNECTION_MAX_RETRIES` says we shouldn't give up connecting to AMQP broker
  no matter how many attempts had failed. The default is 100 retries, but I don't see
  any reason why not try until we succeed.

- The `CELERY_TASK_SERIALIZER` and `CELERY_ACCEPT_CONTENT` options are necessary to
  disable using `pickle`-based serializer and not accept pickled data.
  Starting from version 3.2 Celery would by default refuse to do so for security reasons,
  so let's be future-proof.

- The [`CELERYBEAT_SCHEDULER`][6] option here's to set we'll be using Django database
  for scheduled tasks. By default, even with `djcelery` a filesystem-based storage is used,
  which is not what we would want on Heroku.

- The `"django://"` fallback is for debugging on a local machine, when AMQP broker is
  unavailable or is just an overkill to have installed. It doesn't support some features,
  but should be fine for a basic local debugging before pushing to staging or production servers.

When working with "bare" Celery, without Django we'd also have to configure
result backend - the place where task results would be stored. In our case,
`djcelery` does the setup automatically, so we don't have to worry about this.

Redis broker
------------

Another option would be a Redis-based broker. AMQP is great, but three connections are barely
enough - it's a really tight limitation. RedisToGo addon allows for 10 connections, so we
may consider using it instead. Both RabbitMQ and Redis brokers are considered stable and
fully featured.

Let's install the addon and Python module for Redis:

    $ heroku addons:add rediscloud
    Adding rediscloud on secure-fortress-6930... done, v10 (free)
    Use `heroku addons:docs rediscloud` to view documentation.

    $ echo 'redis==2.10.3' >> requirements.txt
    $ pip install redis==2.10.3

*Note:* we could've achieved the same effect by installing not just `celery` but `celery[redis]`
at the very first step of this tutorial. On a command line, a quotes may be neccessary
(i.e. `pip install 'celery[redis]' djcelery`) since some shells may try to interpret
the square brackets.

Then, do the same `settings.py` editing as with CloudAMQP setup (see the above section),
with the sole exception of using another environment variable name for `BROKER_URL`:

    BROKER_URL = os.environ.get("REDISCLOUD_URL", "django://")

That's the all differences between broker setup. Since we're using database backend to store
results and brokers do not need to persist any information you can switch back and forth
without any problems.

Continue with broker setup
--------------------------

It's a good time to commit. And since `djcelery` app has some models, let's also do `syncdb`:

    $ git add helloworld/settings.py requirements.txt
    $ git commit -m 'Added basic Celery support. Nothing useful yet.'
    [master 65d3525] Added basic Celery support. Nothing useful yet.
     2 files changed, 26 insertions(+)
    $ git push heroku master
    ...
    -----> Installing dependencies with pip
           Installing collected packages: amqp, anyjson, billiard, celery, django-celery, kombu, pytz
    ...
    $ heroku run python manage.py syncdb
    Running `python manage.py syncdb` attached to terminal... up, run.3774
    Operations to perform:
      Synchronize unmigrated apps: djcelery
      Apply all migrations: admin, auth, contenttypes, sessions
    Synchronizing apps without migrations:
      Creating tables...
        Creating table celery_taskmeta
        Creating table celery_tasksetmeta
        Creating table djcelery_intervalschedule
        Creating table djcelery_crontabschedule
        Creating table djcelery_periodictasks
        Creating table djcelery_periodictask
        Creating table djcelery_workerstate
        Creating table djcelery_taskstate
      Installing custom SQL...
      Installing indexes...
    Running migrations:
      No migrations to apply.

Until now, all we've did, except for obtaining `BROKER_URL` wasn't service-dependent.
Now, for a Heroku-specific thing. For now, we had only told Heroku to run a website.
We also have to run Celery worker and scheduler.

There are three options on how we could achieve this. I'll describe pros and cons of
them but it's up to you to chose which one you like the most.

### Three-dyno setup

A most nice-looking but money-hungry approach would be to declare a separate worker
and a scheduler dynos. In `Procfile` that would be two additional entries:

    worker: python manage.py celery worker --loglevel=info
    celery_beat: python manage.py celery beat --loglevel=info

This way, when we'll need additional workes, we could scale with a simple
`heroku ps:scale worker=N` command.

### A compromise: two-dyno setup

Another way is to spawn just a single additional dyno instead of two shown in
previous option is to add the following new entry to the `Procfile`:

    main_worker: python manage.py celery worker --beat --loglevel=info

Here, to save on dynos count I've used `--beat` option to run celerybeat scheduler and
worker in a same process. In such setup we must be sure there's *only one* instance
of the `main_worker` (thus, the name), so do not scale it.

### Staying in a free tier with a single dyno

The third approach is to save money on the start by not using the second dyno at all.
From a `Procfile` we'll start a process manager that would run multiple processes for us.
This just can't scale at all (any attempts to scale would give unpredictable results),
but we could easily revise this at a later time.

The only issue is, since this will be the web dyno, it will be killed ("sleeping" in Heroku terms)
if no requests happen within one hour. Since we have a scheduler, we could probably
work around this limitation by sending an HTTP request to ourselves, though.

Let's consider we've added Celery worker to `Procfile` using one of the above methods.
Some suggest to use Foreman, but in this tutorial I'll stick to Python-only and
use Foreman's clone, [Honcho][7].

    $ echo 'honcho==0.5.0' >> requirements.txt
    $ pip install honcho==0.5.0

As with the three-dyno setup, we'll need a workers declared in a `Procfile`.
Then we'll swap the file with a "proxy" one:

    $ echo 'worker: python manage.py celery worker --loglevel=info' >> Procfile
    $ echo 'celery_beat: python manage.py celery beat --loglevel=info' >> Procfile
    $ git mv Procfile Procfile.real
    $ echo 'web: env > .env; env PYTHONUNBUFFERED=true honcho start -f Procfile.real 2>&1' > Procfile

The `PYTHONUNBUFFERED` variable is there for logging. By default python has
a bit aggressive policy on stream buffering that in some cases may hinder our logs.
This has some performance implications, but allows us to be sure whatever subprocesses
write to stdout will make it to the logs.

Let's push this to production and see whenever everything runs well:

    $ git add requirements.txt Procfile Procfile.real
    $ git commit -m 'Use Honcho to run multiple processes in a single dyno.'

    [master 5c3d926] Use Honcho to run multiple processes in a single dyno.
     3 files changed, 5 insertions(+), 1 deletion(-)
     create mode 100644 Procfile.real
    $ git push heroku master
    ...
    $ heroku logs -t | cut -c34-
    heroku[api]: Deploy 5c3d926 by drdaeman@drdaeman.pp.ru
    heroku[api]: Release v8 created by drdaeman@drdaeman.pp.ru
    slug-compiler]: Slug compilation finished
    heroku[web.1]: State changed from up to starting
    heroku[web.1]: Stopping all processes with SIGTERM
    app[web.1]: [2014-11-16 20:43:56 +0000] [2] [INFO] Shutting down: Master
    app[web.1]: [2014-11-16 20:43:56 +0000] [2] [INFO] Handling signal: term
    app[web.1]: [2014-11-16 20:43:56 +0000] [7] [INFO] Worker exiting (pid: 7)
    heroku[web.1]: Starting process with command `... honcho start -f Procfile.real 2>&1`
    heroku[web.1]: Process exited with status 0
    app[web.1]: 20:43:57 web.1         | started with pid 5
    app[web.1]: 20:43:57 worker.1      | started with pid 7
    app[web.1]: 20:43:57 celery_beat.1 | started with pid 9
    app[web.1]: 20:43:58 web.1         | [...] [6] [INFO] Starting gunicorn 19.1.1
    app[web.1]: 20:43:58 web.1         | [...0] [6] [INFO] Listening at: http://0.0.0.0:41360 (6)
    app[web.1]: 20:43:58 web.1         | [...] [6] [INFO] Using worker: sync
    app[web.1]: 20:43:58 web.1         | [...] [26] [INFO] Booting worker with pid: 26
    heroku[web.1]: State changed from starting to up
    app[web.1]: 20:43:58 celery_beat.1 | celery beat v3.1.16 (Cipater) is starting.
    ...
    app[web.1]: 20:44:00 worker.1      | [...: WARNING/MainProcess] celery@... ready

As you may see, another downside of this approach is messy logging.
I had to manually clean up the above output for documentation purposes.
Unfortunately, it seems this can't be fixed without hacking on Honcho's
code to tune the output format and installing a fork instead of the
official version from PyPI, which is out of scope of this guide.

Celery essentials
-----------------

Now, we're done with the basic setup so let's actually write some tasks and their
management code.

First of all, let's create `tasks.py`. A simple task that'd fetch an URL and
return a status code would look as following:

    from celery import task
    import requests


    @task()
    def fetch_url(url, **kwargs):
        """
        A simple task that fetches the provided URL and returns a tuple
        with the HTTP status code and binary response body (if any)
        """
        r = requests.get(url, **kwargs)
        return (r.status_code, r.content)

For convenience I have used `requests` module here, so let's install it and
add to our `requirements.txt`.

    $ echo 'requests==2.4.3' >> requirements.txt
    $ pip install requests==2.4.3
    $ git add helloworld/tasks.py requirements.txt
    $ git commit -m 'Added a module with a simple fetch_url task'
    [master 2bf607d] Added a module with a simple fetch_url task
     2 files changed, 12 insertions(+)
     create mode 100644 helloworld/tasks.py

In the actual example project there's also a second task called `echo` that
just returns its sole argument's value. This was done to keep the form's
task selection widget populated and not just having a lone "fetch_url" entry.

The only thing that's left is a management code. It's a bit lengthy to cite
the whole thing in documentation, so I'll highlight just the most important parts.

Conveniently, `django-celery` already provides us with all the necessary models
to schedule tasks, so we won't need to create any on our own.

Enqueuing the task to run immediately is as simple as a one-liner:

      async_result = tasks.fetch_url.delay("http://example.org/")
      task_id = async_result.id   # For the next example

The returned `AsyncResult` has a lot of useful methods and properties that allow
to see what's going on with the task and fetch the results when they are available.
Please refer to [Celery documentation for those][10].

To obtain the result at a later time, given only ID string we could use the following code:

      async_result = tasks.fetch_url.AsyncResult(task_id)

To schedule a task we'll essentially just need to put things into a database, in a manner
similar to the following code:

    # Schedule for every 15 minutes on any hour.
    #
    # Please, note this is not an interval, but a pattern
    # that matches ??:00, ??:15, ??:30 and ??:45.
    #
    schedule, _unused = CrontabSchedule.objects.get_or_create(
        minute="*/15", hour="*", day_of_week="*", 
        day_of_month="*", month_of_year="*"
    )

    # Actual scheduling
    periodic_task = PeriodicTask(
        name="some_unique_periodic_task_name",
        task="helloworld.tasks.fetch_url",
        crontab=schedule,
        args=json.dumps(["http://example.org/"])
    )
    periodic_task.save()

`CrontabSchedules` are fixed to exact time values. That is, a schedule of `"*/15 * * *"`
means not "every 15 minutes" but "any hour, when minutes are multiple of 15."
This may be not the most convenient option, but fortunately there's `IntervalSchedule`
class. To use it with a `PeriodicTask` instead of `crontab` argument use `interval` one:

    schedule, _unused = IntervalSchedule.objects.get_or_create(every="hours", period=1)

    periodic_task = PeriodicTask(
        name="some_unique_periodic_task_name2",
        task="helloworld.tasks.fetch_url",
        interval=schedule,
        args=json.dumps(["http://example.org/"])
    )
    periodic_task.save()

The `IntervalSchedule` model has two fields, `every` and `period`. The former is a
a `CharField` with choices [defined in `djcelery.models.PERIOD_CHOICES` tuple][14].
Possible values and are ranging from `"microseconds"` to `"days"`. The latter is
just an `IntegerField`.

When periodic tasks are queued, their IDs are not available, though, so those tasks
shouldn't return anything useful and instead keep this in a database. While this is
probably out of scope of a basic guide, if, at some time, you would need to work around 
this limitation, you could subclass `djcelery.schedulers.DatabaseScheduler`,
implement your own [`apply_entry` method][9] that'd keep the IDs and specify this
custom class in project's `CELERYBEAT_SCHEDULER` setting.

The code in actual project is more complex than the crude examples shown above, but
it's essentially a boilerplate code that handles the form and renders the templates.

The actual project contains:

- A `forms.TaskForm` that has task, its JSON-encoded arguments and desired schedule.

- Simple custom form field classes (`JSONField` and `ScheduleField`) to ease working
  with the form. With those, `task_form.cleaned_data` will contain the actual task and
  `CrontabSchedule` (or `IntervalSchedule`) objects instead of raw user input,
  so view code will cleaner from boilerplate code and easier to read.

- A `views.home` view that displays a form and processes it. It either schedules a task or
  enqueues it immediately, depending on whenever schedule string is provided.

- A `views.status` view that displays the task status by its name and ID.

To try the project, one can do the following:

    $ git clone https://github.com/drdaeman/heroku-djcelery-example
    $ cd heroku-djcelery-example
    $ heroku create
    $ heroku addons:add rediscloud
    $ git push heroku master
    $ heroku run python manage.py syncdb
    $ heroku open

And, optionally, for local development and debugging create a virtualenv and
run `pip install -r requirements.txt` to setup all the necessary dependencies.

That's it. Hope this guide helped!



[1]: http://docs.celeryproject.org/en/2.5/django/first-steps-with-django.html
[2]: https://addons.heroku.com/cloudamqp#lemur
[3]: https://github.com/celery/celery/issues/1560
[4]: http://celery.readthedocs.org/en/latest/configuration.html#broker-pool-limit
[5]: https://devcenter.heroku.com/articles/cloudamqp#celery
[6]: http://celery.readthedocs.org/en/latest/configuration.html#celerybeat-scheduler
[7]: https://github.com/nickstenning/honcho
[8]: http://celery.readthedocs.org/en/latest/userguide/periodic-tasks.html#crontab-schedules
[9]: https://github.com/celery/celery/blob/b0cfa0d818743262a032c541cce2fa8c43fabad4/celery/beat.py#L203
[10]: http://celery.readthedocs.org/en/latest/reference/celery.result.html#celery.result.AsyncResult
[11]: https://devcenter.heroku.com/articles/getting-started-with-django
[13]: https://github.com/celery/django-celery#readme
[14]: https://github.com/celery/django-celery/blob/554984b0f637d4e65b087abced0371a0bc369cc7/djcelery/models.py#L86
