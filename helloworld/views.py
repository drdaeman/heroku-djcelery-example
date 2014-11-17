from __future__ import absolute_import

from django.shortcuts import render, redirect
from django.http import Http404
from djcelery.models import PeriodicTask, CrontabSchedule
import celery
import json
import subprocess
import uuid
from . import tasks, forms


def home(request):
    """
    Displays a task enqueuement form and processes it.

    When schedule is set, an PeriodicTask model instance is created
    to spawn at a later time. Internally, in Celery there are pre_save
    and pre_delete signals attached to model, so celerybeat scheduler
    will be notified about the changes automagically.
    """
    if request.method == "POST":
        task_form = forms.TaskForm(request.POST)
        if task_form.is_valid():
            data = task_form.cleaned_data
            fullname = data["task"].fullname
            name = data["task"].name

            if data["schedule"] is not None:
                # Not the prettiest way, but necessary since different schedule
                # types must be provided as a differently named kwargs.
                if isinstance(data["schedule"], CrontabSchedule):
                    crontab, interval = data["schedule"], None
                else:
                    crontab, interval = None, data["schedule"]

                # This is a task to be scheduled periodically
                ptask_name = "generated_{0}_{1}".format(name, str(uuid.uuid4()))
                ptask = PeriodicTask(
                    name=ptask_name,
                    task=fullname,
                    args=json.dumps(data["args"]),
                    crontab=crontab, interval=interval
                )
                ptask.save()
                return render(request, "helloworld/message.html", {
                    "heading": "scheduled",
                    "message": "Created PeriodicTask #{0.id} {0.name}".format(ptask)
                })
            else:
                # This is a task to be enqueued immediately
                result = data["task"].task.delay(*data["args"])
                return redirect("status", task_name=fullname, task_id=result.id)
    else:
        task_form = forms.TaskForm(initial={"args": '["http://example.org/"]'})

    return render(request, "helloworld/home.html", {"task_form": task_form})


def status(request, task_name, task_id):
    """
    Given a task name and ID, provides information on task's status
    and results (if any).
    """
    ti = tasks.ALL_TASKS.get(task_name, None)
    if ti is None:
        raise Http404

    async_result = ti.task.AsyncResult(task_id)
    if async_result.successful():
        result = async_result.get(timeout=5)
    else:
        result = None
    return render(request, "helloworld/status.html", {
        "task": ti,
        "task_id": task_id,
        "async_result": async_result,
        "result": result
    })
