from django.conf.urls import patterns, include, url
from django.contrib import admin

urlpatterns = patterns('',
    url(r'^$', 'helloworld.views.home', name='home'),
    url(r'^/?status/(?P<task_name>[A-Za-z0-9_\.]+)/(?P<task_id>[0-9a-f-]+)/?$', 'helloworld.views.status', name='status'),

    url(r'^admin/', include(admin.site.urls)),
)
