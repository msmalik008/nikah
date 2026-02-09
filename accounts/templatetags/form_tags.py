from django import template

register = template.Library()


@register.filter
def add_class(field, css_class):
    """Add CSS class to form field"""
    return field.as_widget(attrs={"class": css_class})


@register.filter
def add_placeholder(field, placeholder):
    """Add placeholder to form field"""
    return field.as_widget(attrs={"placeholder": placeholder})


@register.filter
def is_checkbox(field):
    """Check if field is a checkbox"""
    return field.field.widget.__class__.__name__ == 'CheckboxInput'


@register.filter
def is_radio(field):
    """Check if field is a radio button"""
    return field.field.widget.__class__.__name__ == 'RadioSelect'


@register.filter
def is_select(field):
    """Check if field is a select dropdown"""
    return field.field.widget.__class__.__name__ == 'Select'


@register.filter
def is_textarea(field):
    """Check if field is a textarea"""
    return field.field.widget.__class__.__name__ == 'Textarea'