from __future__ import absolute_import

from django import forms
from django.utils.translation import ugettext_lazy as _
from django.utils.text import Truncator
from djcelery.models import CrontabSchedule
import celery
import json

from . import tasks


class JSONField(forms.CharField):
    """
    A simple text field that handles the input as JSON-encoded data.
    """
    def clean(self, value):
        value = super(JSONField, self).clean(value)
        try:
            return json.loads(value)
        except:
            raise forms.ValidationError(_(u"Value must be a valid JSON-encoded data"))


class ScheduleField(forms.CharField):
    """
    A crontab-like field, that handles 2 to 5 space-separated fields, in order:
    minute, hour, day of week, day of month and month of year. That is, just like
    with classic UNIX crontab(5) file entries. Omited entries default to '*'.

    Please refer to Celery or crond documentation for explainations.
    """
    def __init__(self, *args, **kwargs):
        if not "help_text" in kwargs:
            kwargs["help_text"] = _(u"Crontab-like schedule string containing"
                                    u" at least minutes and hours, e.g. \"*/15 *\"")
        return super(ScheduleField, self).__init__(*args, **kwargs)

    def clean(self, value):
        if value in self.empty_values:
            return None

        schedule = value.split()
        if not 2 <= len(schedule) <= 5:
            raise forms.ValidationError(_(u"Bad schedule string, must contain between"
                                          u" 2 and 5 space-separated fields."))

        schedule = dict(zip(["minute", "hour", "day_of_week", "day_of_month", "month_of_year"],
                            schedule + ["*", "*", "*"]))
        schedule, _unused = CrontabSchedule.objects.get_or_create(**schedule)
        return schedule


def _get_taskinfo(task_name):
    """
    Given a task name, return a TaskInfo object or raise an exception.
    """
    t = tasks.ALL_TASKS.get(task_name, None)
    if t is None:
        # While task_name is probably already validated, it won't hurt to check again
        raise forms.ValidationError("Invalid task name: {0}".format(task_name))
    return t


class TaskForm(forms.Form):
    """
    A simple form to select a task, its argument and optional schedule.
    """
    TASK_CHOICES = [
        (_t.fullname, "{0}: {1}".format(_t.name, Truncator(_t.task.__doc__ or "(no description given)").chars(55)))
        for _t in tasks.ALL_TASKS.values()
    ]

    task = forms.TypedChoiceField(label=_(u"Task name"), choices=TASK_CHOICES, coerce=_get_taskinfo, empty_value=None)
    args = JSONField(label=_(u"Task arguments"), help_text=_(u"JSON-encoded task argument array"))
    schedule = ScheduleField(label=_(u"Schedule"), required=False)

    def clean_args(self):
        data = self.cleaned_data["args"]
        if not isinstance(data, list):
            raise forms.ValidationError(_(u"Arguments must be a JSON-encoded array"))

        # TODO: Inspect task's function object to see whenever argument count is matching
        return data
