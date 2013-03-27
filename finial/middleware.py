import simplejson as json

from django.conf import settings
from django.conf.urls.defaults import include, patterns, url
from django.core.cache import cache
from django.forms.models import model_to_dict

from finial import models

DEFAULT_TEMPLATE_DIRS = (
    settings.PROJECT_PATH + '/templates',
)


def get_module_by_path(path):
    mod = __import__(path)
    for sub in path.split('.')[1:]:
        mod = getattr(mod, sub)
    return mod


class TemplateOverrideMiddleware(object):
    """Override templates on a per-user basis; modify TEMPLATE_DIRS.

    Since we're using request.user for most of our logic, this
    Middleware must be placed sometime "after" Session and Authentication
    Middlwares.

    """
    @staticmethod
    def get_tmpl_override_cache_key(user):
        return 'tmpl_override:user_id:{0}'.format(user.pk)

    def override_urlconf(self, request, overrides):
        """If there are overrides, we make a custom urlconf."""
        url_override_cls = getattr(settings, 'FINIAL_URL_OVERRIDES', None)
        if not url_override_cls:
            return

        url_override_inst = get_module_by_path(url_override_cls)
        # These should be in priority order, higher priority at the top.
        args = []
        for override in overrides:
            url_pattern = url_override_inst.override_urlpatterns[
                override['template_name']
            ]
            args.append(url(
                r'^', include(url_pattern, namespace=override['template_name'])
            ))

        args.append(url(r'^', include(getattr(
            get_module_by_path(settings.ROOT_URLCONF), 'urlpatterns'
        ))))

        request.urlconf = patterns('', *args)

        return request.urlconf

    def process_request(self, request):
        """See if there are any overrides, apply them to TEMPLATE_DIRS.

        Here the assumption is that the model fields for:
            user, override_name, tempalte_dir, priority

        """
        settings.TEMPLATE_DIRS = DEFAULT_TEMPLATE_DIRS
        override_values = cache.get(self.get_tmpl_override_cache_key(request.user))
        overrides = None
        template_dir_overrides = []
        if override_values is not None:
            # If we have *something* set, even an empty list
            override_values = json.loads(override_values)
        else:
            # Fetch from SQL
            overrides = models.UserTemplateOverride.objects.filter(
                user=request.user
            ).order_by('priority')
            override_values = [model_to_dict(override) for override in overrides]

        if override_values:
            # Reset URLConf for specific views
            self.override_urlconf(request, override_values)

            # If we had a cached value
            template_dir_overrides = [
                override['template_dir'] for override in override_values
            ]
            # Add in the default TEMPLATE_DIR at the end
            template_dir_overrides.append(DEFAULT_TEMPLATE_DIRS[0])

            # Temporarily set our global settings' TEMPLATE_DIRS var.
            settings.TEMPLATE_DIRS = tuple(template_dir_overrides)
            # Cache whatever we've found in the database.
            cache.set(
                self.get_tmpl_override_cache_key(request.user),
                json.dumps(override_values),
                600
            )
        else:
            # Cache the negative presence of overrides.
            cache.set(self.get_tmpl_override_cache_key(request.user),'[]', 600)

        return None

    def process_response(self, request):
        # Maybe we don't need to do anything here?
        pass
