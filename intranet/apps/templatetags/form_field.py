from django import template
from django.forms.boundfield import BoundField

register = template.Library()


@register.filter(name="field_")
def field_(self, name):
    """
    From https://github.com/halfnibble/django-underscore-filters

    Get a form field starting with _.
    Taken near directly from Django > forms.
    Returns a BoundField with the given name.
    """
    try:
        field = self.fields[name]
    except KeyError as e:
        raise KeyError(f"Key {name!r} not found in '{self.__class__.__name__}'") from e
    return BoundField(self, field, name)
