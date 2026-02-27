# accounts/templatetags/querystring.py
from django import template
from urllib.parse import urlencode

register = template.Library()

@register.simple_tag
def querystring(request, **kwargs):
    """
    Returns the query string for the current request, updated with the given parameters.
    Usage: {% querystring request page=page_obj.next_page_number %}
    """
    querydict = request.GET.copy()
    for key, value in kwargs.items():
        if value is not None:
            querydict[key] = value
        elif key in querydict:
            del querydict[key]
    return querydict.urlencode()